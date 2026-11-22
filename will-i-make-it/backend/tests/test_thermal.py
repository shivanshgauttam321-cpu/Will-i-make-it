"""
Unit Tests for Stage C4 Battery Thermal Dynamics & BTMS
========================================================
Validates lumped thermal modeling, analytical updates, active BTMS,
and thermal derating limits.
"""
import pytest
import math

from app.domain.provenance import DataStatus
from app.services.energy.thermal_model import (
    ThermalConfig,
    ThermalState,
    BtmsMode,
    ThermalDerateMode,
    ThermalStepResult,
    compute_thermal_derating,
    simulate_thermal_step,
)


def test_thermal_config_validation():
    cfg = ThermalConfig(pack_mass_kg=300.0, specific_heat_j_per_kg_k=1000.0)
    assert cfg.lumped_heat_capacity_j_per_k == 300000.0

    with pytest.raises(ValueError):
        ThermalConfig(target_heat_temp_c=35.0, target_cool_temp_c=25.0)

    with pytest.raises(ValueError):
        ThermalConfig(temp_derate_hot_start_c=55.0, temp_derate_hot_cutoff_c=50.0)


def test_insulated_pack_temperature_rise():
    # C_th = 200 kg * 1000 J/kg/K = 200,000 J/K
    # h_A = 0 (insulated)
    # 20,000 W heat generation for 10 seconds -> 200,000 J added -> delta_T = 1.0 K
    cfg = ThermalConfig(
        pack_mass_kg=200.0,
        specific_heat_j_per_kg_k=1000.0,
        heat_transfer_coeff_w_per_k=0.0,
        enable_active_cooling=False,
        enable_active_heating=False,
    )
    init_state = ThermalState(temperature_c=25.0)
    new_state, res = simulate_thermal_step(
        state=init_state,
        q_gen_w=20000.0,
        ambient_temp_c=25.0,
        dt_s=10.0,
        config=cfg,
    )
    assert pytest.approx(new_state.temperature_c, abs=1e-3) == 26.0
    assert pytest.approx(res.q_gen_w, abs=1e-2) == 20000.0
    assert res.q_ambient_w == 0.0


def test_cooling_to_ambient_exponential_decay():
    # Hot pack at 45°C cooling towards ambient at 25°C with no internal generation
    cfg = ThermalConfig(
        pack_mass_kg=100.0,
        specific_heat_j_per_kg_k=1000.0,  # C_th = 100,000 J/K
        heat_transfer_coeff_w_per_k=100.0, # tau = 1000 s
        enable_active_cooling=False,
        enable_active_heating=False,
    )
    init_state = ThermalState(temperature_c=45.0)
    dt = 1000.0  # 1 tau
    new_state, res = simulate_thermal_step(
        state=init_state,
        q_gen_w=0.0,
        ambient_temp_c=25.0,
        dt_s=dt,
        config=cfg,
    )
    # After 1 tau: T = 25 + (45 - 25)*exp(-1) = 25 + 20/e ≈ 32.3576 °C
    expected = 25.0 + 20.0 * math.exp(-1.0)
    assert pytest.approx(new_state.temperature_c, abs=1e-2) == expected
    assert res.q_ambient_w > 0.0


def test_active_btms_cooling_and_power_consumption():
    cfg = ThermalConfig(
        target_cool_temp_c=30.0,
        cooling_proportional_gain_w_per_k=200.0,
        cop_cooling=2.5,
        max_cooling_power_w=3000.0,
    )
    # Pack at 35°C (5°C above target)
    init_state = ThermalState(temperature_c=35.0)
    new_state, res = simulate_thermal_step(
        state=init_state,
        q_gen_w=500.0,
        ambient_temp_c=35.0,
        dt_s=10.0,
        config=cfg,
    )
    # Cooling power: 5 K * 200 W/K = 1000 W
    assert pytest.approx(res.q_cool_w, abs=1e-1) == 1000.0
    # Electrical power: 1000 W / 2.5 / 1000 = 0.400 kW
    assert pytest.approx(res.p_btms_electrical_kw, abs=1e-3) == 0.400
    assert res.btms_mode == BtmsMode.COOLING


def test_active_btms_heating_in_cold():
    cfg = ThermalConfig(
        target_heat_temp_c=10.0,
        heating_proportional_gain_w_per_k=100.0,
        cop_heating=1.0,
        max_heating_power_w=2000.0,
    )
    # Pack at 0°C (10°C below target)
    init_state = ThermalState(temperature_c=0.0)
    new_state, res = simulate_thermal_step(
        state=init_state,
        q_gen_w=0.0,
        ambient_temp_c=-5.0,
        dt_s=10.0,
        config=cfg,
    )
    # Heating power: 10 K * 100 W/K = 1000 W
    assert pytest.approx(res.q_heat_w, abs=1e-1) == 1000.0
    # Electrical power: 1000 W / 1.0 / 1000 = 1.0 kW
    assert pytest.approx(res.p_btms_electrical_kw, abs=1e-3) == 1.0
    assert res.btms_mode == BtmsMode.HEATING
    assert res.derate_mode == ThermalDerateMode.COLD_DERATED


def test_thermal_derating_multipliers():
    cfg = ThermalConfig(
        temp_derate_hot_start_c=45.0,
        temp_derate_hot_cutoff_c=55.0,
        temp_derate_cold_start_c=5.0,
        temp_derate_cold_cutoff_c=-15.0,
        min_cold_derate_fraction=0.20,
    )

    # Nominal zone
    f, m = compute_thermal_derating(25.0, cfg)
    assert f == 1.0 and m == ThermalDerateMode.NOMINAL
    f, m = compute_thermal_derating(45.0, cfg)
    assert f == 1.0 and m == ThermalDerateMode.NOMINAL
    f, m = compute_thermal_derating(5.0, cfg)
    assert f == 1.0 and m == ThermalDerateMode.NOMINAL

    # Hot zone
    f, m = compute_thermal_derating(50.0, cfg)
    assert pytest.approx(f, abs=1e-3) == 0.50 and m == ThermalDerateMode.HOT_DERATED
    f, m = compute_thermal_derating(55.0, cfg)
    assert f == 0.0 and m == ThermalDerateMode.OVERHEAT_CRITICAL
    f, m = compute_thermal_derating(60.0, cfg)
    assert f == 0.0 and m == ThermalDerateMode.OVERHEAT_CRITICAL

    # Cold zone
    f, m = compute_thermal_derating(-5.0, cfg)
    assert pytest.approx(f, abs=1e-3) == 0.60 and m == ThermalDerateMode.COLD_DERATED
    f, m = compute_thermal_derating(-15.0, cfg)
    assert pytest.approx(f, abs=1e-3) == 0.20 and m == ThermalDerateMode.COLD_DERATED
    f, m = compute_thermal_derating(-20.0, cfg)
    assert pytest.approx(f, abs=1e-3) == 0.20 and m == ThermalDerateMode.COLD_DERATED
