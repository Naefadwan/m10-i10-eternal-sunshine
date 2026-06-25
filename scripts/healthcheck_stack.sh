#!/usr/bin/env bash
# Poll `docker compose ps` until all four services report healthy or
# until the 90s budget expires.

set -euo pipefail

services=("api" "web" "neo4j" "weaviate")
max_iterations=45
sleep_seconds=2

for i in $(seq 1 $max_iterations); do
  all_healthy=true
  for svc in "${services[@]}"; do
    # Get health status of the service
    status=$(docker compose ps "$svc" --format json | python3 -c "import sys,json; lines=[l for l in sys.stdin if l.strip()]; print(json.loads(lines[0]).get('Health','')) if lines else print('')" 2>/dev/null || true)
    if [ "$status" != "healthy" ]; then
      all_healthy=false
      break
    fi
  done

  if [ "$all_healthy" = "true" ]; then
    echo "All services are healthy!"
    exit 0
  fi

  sleep $sleep_seconds
done

echo "Timeout waiting for services to become healthy."
docker compose ps
exit 1
