// Seed script for Neo4j
// Run: node neo4j/seed.js (requires NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD in environment)

const CYPHER_QUERIES = [
  // Constraints
  "CREATE CONSTRAINT road_node_id IF NOT EXISTS FOR (n:RoadNode) REQUIRE n.node_id IS UNIQUE",
  "CREATE CONSTRAINT charger_id IF NOT EXISTS FOR (c:Charger) REQUIRE c.charger_id IS UNIQUE",

  // Chargers
  `MERGE (c:Charger {charger_id: 'CHR_MH_001'})
   SET c.name = 'Tata Power EV – Pune Kharadi', c.lat=18.5512, c.lng=73.9478,
       c.max_power_kw=50.0, c.operator='Tata Power', c.reliability_score=0.88`,

  `MERGE (c:Charger {charger_id: 'CHR_DL_001'})
   SET c.name = 'Fortum Charge – Connaught Place', c.lat=28.6315, c.lng=77.2167,
       c.max_power_kw=50.0, c.operator='Fortum', c.reliability_score=0.91`,

  // Road nodes (Mumbai–Pune corridor)
  `MERGE (n:RoadNode {node_id:'MUMBAI_PUNE_N0'}) SET n.name='Mumbai', n.lat=19.076, n.lng=72.8777`,
  `MERGE (n:RoadNode {node_id:'MUMBAI_PUNE_N1'}) SET n.name='Khopoli', n.lat=18.78, n.lng=73.25`,
  `MERGE (n:RoadNode {node_id:'MUMBAI_PUNE_N2'}) SET n.name='Lonavala', n.lat=18.7481, n.lng=73.4072`,
  `MERGE (n:RoadNode {node_id:'MUMBAI_PUNE_N3'}) SET n.name='Pune', n.lat=18.5204, n.lng=73.8567`,

  // Road segments
  `MATCH (a:RoadNode {node_id:'MUMBAI_PUNE_N0'}), (b:RoadNode {node_id:'MUMBAI_PUNE_N1'})
   MERGE (a)-[r:ROAD_SEGMENT {segment_id:'MP_01'}]->(b)
   SET r.distance_km=45, r.avg_speed_kmh=40, r.gradient_pct=0.0, r.road_type='urban'`,

  `MATCH (a:RoadNode {node_id:'MUMBAI_PUNE_N1'}), (b:RoadNode {node_id:'MUMBAI_PUNE_N2'})
   MERGE (a)-[r:ROAD_SEGMENT {segment_id:'MP_02'}]->(b)
   SET r.distance_km=25, r.avg_speed_kmh=35, r.gradient_pct=4.5, r.road_type='rural'`,

  `MATCH (a:RoadNode {node_id:'MUMBAI_PUNE_N2'}), (b:RoadNode {node_id:'MUMBAI_PUNE_N3'})
   MERGE (a)-[r:ROAD_SEGMENT {segment_id:'MP_03'}]->(b)
   SET r.distance_km=63, r.avg_speed_kmh=90, r.gradient_pct=-1.5, r.road_type='highway'`,

  // Charger location
  `MATCH (c:Charger {charger_id:'CHR_MH_001'}), (n:RoadNode {node_id:'MUMBAI_PUNE_N3'})
   MERGE (c)-[:LOCATED_AT]->(n)`,

  // Useful queries (comments for reference)
  // Find all road segments with positive gradient:
  // MATCH ()-[r:ROAD_SEGMENT]->() WHERE r.gradient_pct > 2 RETURN r.segment_id, r.gradient_pct ORDER BY r.gradient_pct DESC
  //
  // Find chargers with high reliability:
  // MATCH (c:Charger) WHERE c.reliability_score >= 0.8 RETURN c.name, c.reliability_score ORDER BY c.reliability_score DESC
  //
  // Find path from Mumbai to Pune:
  // MATCH path = (a:RoadNode {node_id:'MUMBAI_PUNE_N0'})-[:ROAD_SEGMENT*]->(b:RoadNode {node_id:'MUMBAI_PUNE_N3'})
  // WITH path, REDUCE(d=0, r IN relationships(path) | d + r.distance_km) AS total_km
  // RETURN path, total_km ORDER BY total_km LIMIT 3
];

console.log("Neo4j Seed Script - Will I Make It");
console.log("=====================================");
console.log("Set NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD environment variables,");
console.log("then run this via the Python seed script or Neo4j Browser.");
console.log("\nCypher queries to run:");
CYPHER_QUERIES.forEach((q, i) => console.log(`\n[${i+1}] ${q.trim()}`));
