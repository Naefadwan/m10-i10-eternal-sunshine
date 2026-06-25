"""End-to-end smoke harness — Infra-Integration lead authors.

Brings the four-service stack up via `docker compose up -d --wait` and
verifies the demo `/rag/answer` curl returns 200 with citations against
the seeded fixture. Skipped in the autograder (which exercises compose
topology structurally, not at runtime); used locally during demo-prep
and by the TA during walkthrough.
"""
import os
import subprocess
import time
import httpx
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.mark.skipif(
    os.environ.get("RUN_E2E") != "true",
    reason="Skipping E2E stack test by default. Set RUN_E2E=true to run this integration test."
)
def test_stack_e2e_seeded_rag_query():
    # Ensure .env exists or write a temporary one with default credentials
    # so docker compose command resolves correctly.
    env_path = REPO_ROOT / ".env"
    had_env = env_path.exists()
    
    if not had_env:
        print("\nCreating a temporary .env file for the integration test...")
        temp_env_content = (
            "NEO4J_USER=neo4j\n"
            "NEO4J_PASSWORD=integration-test-password-12345\n"
            "NEO4J_AUTH=neo4j/integration-test-password-12345\n"
            "WEB_ORIGIN=http://localhost:3000\n"
        )
        env_path.write_text(temp_env_content)
        
    try:
        # 1. Clean down and bring up the stack with --wait
        print("\nBringing down any running containers...")
        subprocess.run(["docker", "compose", "down", "-v"], cwd=REPO_ROOT, check=True)
        
        print("Bringing up stack via docker compose up -d --wait...")
        subprocess.run(["docker", "compose", "up", "-d", "--wait"], cwd=REPO_ROOT, check=True)
        
        # 2. Wait for health check stack script to confirm readiness
        print("Running healthcheck_stack.sh...")
        subprocess.run(["bash", "scripts/healthcheck_stack.sh"], cwd=REPO_ROOT, check=True)
        
        # 3. Seed databases
        print("Seeding Neo4j database...")
        subprocess.run(["bash", "scripts/seed_neo4j.sh"], cwd=REPO_ROOT, check=True)
        
        print("Seeding Weaviate database...")
        subprocess.run(["bash", "scripts/seed_weaviate.sh"], cwd=REPO_ROOT, check=True)
        
        # 4. Perform the RAG query
        print("Sending RAG query payload...")
        url = "http://localhost:8000/rag/answer"
        payload = {"question": "How do I prep ginger for stir-fry?", "k": 4}
        
        # Retry logic in case uvicorn needs a couple seconds to fully initialize its internals
        response = None
        for attempt in range(5):
            try:
                response = httpx.post(url, json=payload, timeout=30.0)
                if response.status_code == 200:
                    break
            except (httpx.ConnectError, httpx.HTTPError) as e:
                print(f"HTTP attempt {attempt+1} failed: {e}")
            time.sleep(2)
            
        assert response is not None, "Failed to connect to API endpoint."
        assert response.status_code == 200, f"RAG query returned status {response.status_code}: {response.text}"
        
        data = response.json()
        assert "answer" in data
        assert data["answer"] != ""
        assert "citations" in data
        assert len(data["citations"]) > 0, f"No citations returned from the seeded fixture: {data}"
        
        # Validate structure of citations
        for citation in data["citations"]:
            assert "chunk_id" in citation
            assert "score" in citation
            
        print("RAG Query Verification succeeded!")
        print(f"Answer: {data['answer']}")
        print(f"Citations: {data['citations']}")
        
    finally:
        # Clean down the stack after the e2e smoke run
        print("Cleaning down the stack...")
        subprocess.run(["docker", "compose", "down", "-v"], cwd=REPO_ROOT, check=True)
        
        # Clean up temporary .env if we created it
        if not had_env and env_path.exists():
            print("Removing temporary .env file...")
            env_path.unlink()
