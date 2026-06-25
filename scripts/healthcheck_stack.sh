#!/usr/bin/env bash
# Poll `docker compose ps` until all four services report healthy or
# until the 90s budget expires.

set -euo pipefail

echo "Waiting for stack to become healthy (90 seconds max budget)..."

# Loop with 2s sleep, up to 45 iterations.
for i in {1..45}; do
  # Fetch JSON status of compose services
  STATUS_JSON=$(docker compose ps --format json)

  # Check health statuses of api, web, neo4j, and weaviate using a quick Python line parser
  HEALTHY_COUNT=$(python3 -c '
import sys, json
raw = sys.argv[1]
try:
    data = json.loads(raw)
except Exception:
    data = []
    # Handle line-delimited JSON
    for line in raw.strip().splitlines():
        if line.strip():
            try:
                data.append(json.loads(line))
            except Exception:
                pass

if not isinstance(data, list):
    data = [data]

required = {"api", "web", "neo4j", "weaviate"}
healthy = set()

for item in data:
    # Handle potential differences in service key depending on Compose version (e.g. Service or Name)
    svc = item.get("Service") or item.get("Name")
    health = item.get("Health") or item.get("HealthState") or ""
    
    # Strip project prefix or container suffixes from Service name if applicable
    if svc:
        # If svc is e.g. "m10-i10-eternal-sunshine-api-1", match the service name part
        for r_svc in required:
            if r_svc == svc or f"-{r_svc}-" in svc or svc.endswith(f"-{r_svc}"):
                if "healthy" in health.lower():
                    healthy.add(r_svc)

print(len(healthy))
' "$STATUS_JSON")

  if [ "$HEALTHY_COUNT" -eq 4 ]; then
    echo "All four services (api, web, neo4j, weaviate) are healthy!"
    exit 0
  else
    echo "Healthy services: $HEALTHY_COUNT/4. Sleeping 2 seconds..."
  fi
  sleep 2
done

echo "Error: Timeout waiting for services to become healthy." >&2
exit 1
