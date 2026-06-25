# Integration 10 — Dockerize the Four-Service Stack

This repository packages the recipe FastAPI backend (`api`) and Next.js frontend (`web`) together with containerized data tiers (**Neo4j** and **Weaviate**) into a unified, Docker-managed stack.

---

## Architecture & Port Contract

The stack operates under the following network topology:

| Service | Port (Host) | Internal DNS (Docker Network) | Healthcheck Method | Notes |
|---|---|---|---|---|
| **api** | `8000` | `api:8000` | Python `urllib` probe on `/healthz` | Depends on `neo4j` and `weaviate` |
| **web** | `3000` | `web:3000` | Node `http` probe on `/` | Depends on `api` |
| **neo4j** | `7474`, `7687` | `neo4j:7687` (Bolt) | `cypher-shell` validation query | Named volume: `neo4j_data` |
| **weaviate** | `8080` | `weaviate:8080` | HTTP probe on `/v1/.well-known/ready` | Named volume: `weaviate_data` |

### The Host-vs-Container DNS Distinction

- **Client Bundle (`web` Build Arg)**: `NEXT_PUBLIC_API_URL` is set to `http://localhost:8000` under `services.web.build.args`. Because Next.js executes client-side code *within the host user's web browser*, it must route requests through the host mapping (`localhost`). Setting this to `http://api:8000` would fail since the browser cannot resolve Docker's internal network DNS.
- **Backend Services (`api` Environment)**: The FastAPI container communicates directly with databases using Docker DNS names: `NEO4J_URI=bolt://neo4j:7687` and `WEAVIATE_URL=http://weaviate:8080`.
- **CORS Config**: `WEB_ORIGIN` is configured to `http://localhost:3000` to permit cross-origin requests from the browser frontend to the backend API.

---

## Onboarding Runbook (Step-by-Step)

Follow these steps to clone, configure, run, and verify the stack.

### 1. Prerequisites

Ensure you have the following installed on your host system:
- **Docker** and **Docker Compose (v2.x)**
- **Python 3.11+** (if running the pytest test suite locally)
- **curl** and **jq** (for testing queries from the command line)

### 2. Clone and Setup Environment

Clone the repository and copy the environment template:
```bash
cp .env.example .env
```
Open the newly created `.env` file and customize the database password:
```env
NEO4J_USER=neo4j
NEO4J_PASSWORD=my-secure-password
WEB_ORIGIN=http://localhost:3000
```
> [!WARNING]
> Keep the `.env` file secure and never commit it to git. It is excluded by default in `.gitignore`.

### 3. Spin Up the Stack

Build the containers and bring them up in detached mode:
```bash
docker compose up -d --build
```
This command builds the Next.js bundle baking in `NEXT_PUBLIC_API_URL=http://localhost:8000` and starts all four containers.

### 4. Wait for Service Health

Wait for the databases and services to initialize and complete healthchecks:
```bash
bash scripts/healthcheck_stack.sh
```
This script will poll `docker compose ps` until all four containers report `healthy` (up to 90 seconds).

### 5. Ingest Fixture Data (Seeding)

Seed the Neo4j graph database and Weaviate vector index with our recipe dataset:
```bash
bash scripts/seed_neo4j.sh
bash scripts/seed_weaviate.sh
```
Both seed scripts are **idempotent**; running them multiple times will not duplicate entries.

---

## Verification & Demos

### A. Terminal Smoke Curl
Query the RAG endpoint directly using `curl` to check if it answers cooking questions using the seeded text chunks:
```bash
curl -s -X POST http://localhost:8000/rag/answer \
  -H 'Content-Type: application/json' \
  -d '{"question": "How do I prep ginger for stir-fry?"}' | jq .
```
You should receive a `200 OK` response with a generated answer and citations referring to the chunk IDs (e.g. `[1]` and `[4]` corresponding to minced/sliced ginger preparation instructions).

### B. Interactive Web UI
Open your browser and navigate to:
- **RAG Interface**: [http://localhost:3000/rag](http://localhost:3000/rag) — Ask questions and see ground truth citations highlighted.
- **Knowledge Graph (KG)**: [http://localhost:3000/kg](http://localhost:3000/kg) — Query Cypher paths interactively.
- **Entity Extraction**: [http://localhost:3000/extract](http://localhost:3000/extract) — Paste recipes to identify ingredients and prep techniques.

### C. Host Integration Tests
To execute the automated structural and integration tests:
1. Create a Python virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate
   ```
2. Install test dependencies:
   ```bash
   pip install pytest pyyaml httpx
   ```
3. Run the pytest harness:
   ```bash
   pytest
   ```

---

## Teardown Runbook

To stop the containers and reclaim volume space:
```bash
# Stops services and removes containers/networks
docker compose down

# Stops services and completely removes named data volumes (clears database state)
docker compose down -v
```
