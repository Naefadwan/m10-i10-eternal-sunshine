"""RAG composer — retrieve → assemble → generate → cite → grounding check.

Grounding contract: when `answer` is not the empty-retrieval sentinel,
`len(citations) > 0` is required. Every cited `chunk_id` corresponds to
a chunk in the top-`k` retrieved from Weaviate.

Generator called with `do_sample=False` for reproducibility.

Integration hardening (added layer):
- Per-call timeout on the generator wrapper via `concurrent.futures`
  so a stuck model does not block the worker indefinitely.
- Structured logging at each RAG stage for `docker compose logs`
  readability.
"""
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Tuple

logger = logging.getLogger("api.rag")

PROMPT_TEMPLATE = """\
You are answering a recipe question. Use ONLY the numbered sources below.
Cite each claim with the source number in square brackets, e.g. [1].
If the sources do not contain the answer, say: I cannot answer this from the available sources.

Sources:
{sources}

Question: {question}
Answer:"""

SENTINEL = "I cannot answer this from the available sources"
CITATION_PATTERN = re.compile(r"\[(\d+)\]")

# Configurable via env var; default 30 s is generous for flan-t5-base on CPU.
GENERATOR_TIMEOUT_S = int(os.environ.get("GENERATOR_TIMEOUT_S", "30"))

# Module-level executor — one thread is enough because the generator
# itself is single-threaded and we only need the timeout wrapper.
_executor = ThreadPoolExecutor(max_workers=1)


def assemble_prompt(question: str, chunks: list[dict]) -> Tuple[str, dict[int, dict]]:
    """Number the retrieved chunks 1..k and substitute into the prompt template.

    Returns (prompt_str, {citation_index: chunk_dict}). Index starts at 1.
    """
    numbered: dict[int, dict] = {}
    lines = []
    for i, chunk in enumerate(chunks, start=1):
        numbered[i] = chunk
        lines.append(f"[{i}] {chunk['text']}")
    sources = "\n".join(lines)
    return PROMPT_TEMPLATE.format(sources=sources, question=question), numbered


def extract_citations(answer: str, numbered: dict[int, dict]) -> list[dict]:
    """Pull [N]-style markers from `answer` and resolve to retrieved chunks.

    Returns one {"chunk_id", "score"} dict per unique resolvable index.
    """
    cited: list[dict] = []
    seen: set[int] = set()
    for match in CITATION_PATTERN.finditer(answer):
        idx = int(match.group(1))
        if idx in numbered and idx not in seen:
            seen.add(idx)
            chunk = numbered[idx]
            cited.append({"chunk_id": chunk["chunk_id"], "score": chunk["score"]})
    return cited


def _run_generator(generator, prompt: str) -> str:
    """Call the HuggingFace pipeline synchronously (target for executor)."""
    return generator(prompt, max_new_tokens=256, do_sample=False)[0]["generated_text"]


def compose_rag(question: str, embedder, weaviate_client, generator, k: int = 4) -> dict:
    """Run the four-stage RAG pipeline.

    Encodes the question via the externally-loaded sentence-transformers
    embedder and queries Weaviate with `with_near_vector`. The Weaviate
    class is `vectorizer=none`, so `with_near_text` would fail at
    runtime with `KeyError: 'data'`.

    Returns {"answer": str, "citations": list[dict], "confidence": float}.
    """
    t0 = time.monotonic()

    # --- Stage 1: Retrieve ---
    vector = embedder.encode(question).tolist()
    raw_query = (
        weaviate_client.query.get("Chunk", ["chunk_id", "text"])
        .with_near_vector({"vector": vector})
        .with_limit(k)
        .with_additional(["distance"])
        .do()
    )
    retrieved = [
        {
            "chunk_id": c["chunk_id"],
            "text": c["text"],
            "score": 1.0 - c["_additional"]["distance"],
        }
        for c in raw_query["data"]["Get"]["Chunk"]
    ]
    t_retrieve = time.monotonic()
    logger.info(
        "rag.retrieve k=%d retrieved=%d elapsed_ms=%.1f",
        k,
        len(retrieved),
        (t_retrieve - t0) * 1000,
    )

    if not retrieved:
        logger.info("rag.empty_retrieval question=%r", question)
        return {"answer": SENTINEL, "citations": [], "confidence": 0.0}

    # --- Stage 2: Assemble ---
    prompt, numbered = assemble_prompt(question, retrieved)
    t_assemble = time.monotonic()
    logger.info(
        "rag.assemble prompt_len=%d elapsed_ms=%.1f",
        len(prompt),
        (t_assemble - t_retrieve) * 1000,
    )

    # --- Stage 3: Generate (with timeout) ---
    try:
        future = _executor.submit(_run_generator, generator, prompt)
        raw = future.result(timeout=GENERATOR_TIMEOUT_S)
    except FuturesTimeoutError:
        logger.error(
            "rag.generate_timeout timeout_s=%d question=%r",
            GENERATOR_TIMEOUT_S,
            question,
        )
        return {"answer": SENTINEL, "citations": [], "confidence": 0.0}

    t_generate = time.monotonic()
    logger.info(
        "rag.generate answer_len=%d elapsed_ms=%.1f",
        len(raw),
        (t_generate - t_assemble) * 1000,
    )

    # --- Stage 4: Cite + ground ---
    citations = extract_citations(raw, numbered)
    if not citations:
        logger.info("rag.grounding_refusal no_citations question=%r", question)
        return {"answer": SENTINEL, "citations": [], "confidence": 0.0}

    confidence = sum(c["score"] for c in citations) / len(citations)
    confidence = max(0.0, min(1.0, confidence))

    t_end = time.monotonic()
    logger.info(
        "rag.complete citations=%d confidence=%.3f total_ms=%.1f",
        len(citations),
        confidence,
        (t_end - t0) * 1000,
    )
    return {"answer": raw, "citations": citations, "confidence": confidence}
