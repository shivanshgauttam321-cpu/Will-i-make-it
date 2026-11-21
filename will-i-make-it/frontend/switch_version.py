"""
Version Switcher Utility for Will I Make It? Frontend.
Usage:
  python switch_version.py original     # Restore original untouched project (ACTIVE)
  python switch_version.py redesign_v1  # Switch to the dark charcoal & orange multi-panel redesign
  python switch_version.py meitriya_v2  # Switch to the Meitriya 3-column cockpit
"""
import sys
import os
import shutil

FRONTEND_DIR = os.path.dirname(os.path.abspath(__file__))
VERSIONS_DIR = os.path.join(FRONTEND_DIR, '.versions')

def switch_to(version_name: str):
    target_v = os.path.join(VERSIONS_DIR, version_name)
    if not os.path.exists(target_v):
        print(f"Error: Version '{version_name}' not found in {VERSIONS_DIR}")
        print("Available versions:", [d for d in os.listdir(VERSIONS_DIR) if os.path.isdir(os.path.join(VERSIONS_DIR, d))])
        sys.exit(1)

    print(f"Switching frontend to: {version_name}...")

    # Copy files
    for root, dirs, files in os.walk(target_v):
        for f in files:
            src = os.path.join(root, f)
            rel = os.path.relpath(src, target_v)
            dst = os.path.join(FRONTEND_DIR, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            print(f"  -> {rel}")

    # Clean up non-original files if switching to original
    if version_name == 'original':
        extra = [
            'MeitriyaCockpit.tsx',
            'NavigationRail.tsx',
            'HeaderBar.tsx',
            'JourneyResultsPanel.tsx',
            'EnergyIntelligencePanel.tsx'
        ]
        for e in extra:
            p = os.path.join(FRONTEND_DIR, 'src', 'components', e)
            if os.path.exists(p):
                os.remove(p)
                print(f"  Removed {e}")

    print(f"\nSuccessfully switched to '{version_name}'!")
    print("Run: npm.cmd run build (or npm.cmd run dev) to start.")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python switch_version.py <original | redesign_v1 | meitriya_v2>")
        sys.exit(1)
    switch_to(sys.argv[1].strip().lower())
