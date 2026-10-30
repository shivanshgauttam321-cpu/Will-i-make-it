"""
Neo4j Connection Diagnostic Tool
================================
Run this tool to diagnose and test your Neo4j / AuraDB connection.
Usage:
  python test_neo4j.py
"""

import os
import sys
from dotenv import load_dotenv

# Load .env
backend_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(backend_dir, ".env")
load_dotenv(env_path, override=True)

uri = os.environ.get("NEO4J_URI", "").strip()
raw_user = (os.environ.get("NEO4J_USERNAME") or os.environ.get("NEO4J_USER") or "neo4j").strip()
pwd = os.environ.get("NEO4J_PASSWORD", "").strip()
instance_id = os.environ.get("AURA_INSTANCEID", "").strip()

# Correct user if account label or instance id was used
actual_user = raw_user
if "@" in raw_user or "Aura" in raw_user or "(" in raw_user or raw_user == instance_id:
    actual_user = "neo4j"

try:
    from neo4j import GraphDatabase
except ImportError:
    print("[ERROR] 'neo4j' Python package is not installed.")
    print("Run: pip install neo4j")
    sys.exit(1)

schemes_to_try = [uri]
if uri.startswith("neo4j+s://"):
    # Also prepare fallback with self-signed / custom cert handling
    schemes_to_try.append(uri.replace("neo4j+s://", "neo4j+ssc://"))
elif uri.startswith("bolt+s://"):
    schemes_to_try.append(uri.replace("bolt+s://", "bolt+ssc://"))

connected = False
for test_uri in schemes_to_try:
    print(f"\nAttempting connection to {test_uri} with user '{actual_user}'...")
    try:
        driver = GraphDatabase.driver(test_uri, auth=(actual_user, pwd))
        driver.verify_connectivity()
        print(">>> [SUCCESS] Connected to Neo4j database successfully! <<<")
        
        with driver.session() as session:
            version_res = session.run("CALL dbms.components() YIELD name, versions, edition RETURN name, versions[0] AS version, edition").single()
            if version_res:
                print(f"Database: {version_res['name']} v{version_res['version']} ({version_res['edition']})")
            
            # Check node counts
            count_res = session.run("MATCH (n) RETURN count(n) AS total_nodes").single()
            print(f"Graph node count: {count_res['total_nodes']} nodes")
        
        driver.close()
        connected = True
        break
    except Exception as e:
        err_type = type(e).__name__
        err_msg = str(e)
        print(f"Failed with {test_uri}: [{err_type}] {err_msg}")
        
        if "Unauthorized" in err_msg or "authentication failure" in err_msg.lower():
            print("\n" + "!"*60)
            print("[DIAGNOSIS: AUTHENTICATION FAILURE]")
            print("The Neo4j server was reached, but the password was rejected.")
            print("Common causes in Neo4j Aura:")
            print("1. An Aura API Key / Client Secret was copied instead of the Database Password.")
            print("2. The database password was reset in console.neo4j.io.")
            print("\nHow to fix:")
            print("1. Go to https://console.neo4j.io")
            print("2. Find your instance (e.g. fca0bf5d) and click the three dots '...'")
            print("3. Click 'Reset password' -> Copy the newly generated password.")
            print(f"4. Put in {env_path}:")
            print("     NEO4J_URI=neo4j+s://<instance-id>.databases.neo4j.io")
            print("     NEO4J_USER=neo4j")
            print("     NEO4J_PASSWORD=<the-new-password>")
            print("!"*60)
            break
        elif "Unable to retrieve routing information" in err_msg or "ServiceUnavailable" in err_msg:
            print("\n[NOTE] Routing check failed on this scheme. Testing fallback scheme...")

if not connected:
    print("\n" + "="*60)
    print("RESULT: Could not establish authenticated connection.")
    print("The application will continue operating smoothly using its built-in")
    print("deterministic local routing fallback.")
    print("="*60 + "\n")
    sys.exit(1)
else:
    print("\n" + "="*60)
    print("RESULT: Neo4j connection is verified and ready for use!")
    print("="*60 + "\n")
    sys.exit(0)
