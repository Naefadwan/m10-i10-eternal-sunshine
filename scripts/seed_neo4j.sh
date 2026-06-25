#!/usr/bin/env bash
# Seed the running Neo4j container with the recipe fixture.
#
# Idempotent — `MERGE` and `CREATE CONSTRAINT IF NOT EXISTS` in seed.cypher
# mean repeat runs do not duplicate nodes.

set -euo pipefail

NEO4J_USER="${NEO4J_USER:-neo4j}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-testtest12345}"

# Pipe seed.cypher into the neo4j container via cypher-shell
docker compose exec -T neo4j cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" < api/seed.cypher

echo "Neo4j database successfully seeded."
