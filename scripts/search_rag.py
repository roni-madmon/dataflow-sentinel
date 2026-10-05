import hashlib
import json
import math
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, build_opener

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAG_DIR = PROJECT_ROOT / "artifacts" / "rag"


def search(question, top_k=3):
    if not question.strip():
        raise ValueError("The question cannot be empty.")

    index = json.loads(
        (RAG_DIR / "vector_index.json").read_text(encoding="utf-8-sig")
    )

    # Ensure the index matches the prepared chunks.
    chunks_hash = hashlib.sha256(
        (RAG_DIR / "chunks.json").read_bytes()
    ).hexdigest()

    if chunks_hash != index["chunks_sha256"]:
        raise ValueError("Chunks changed. Run embed_rag_chunks.py again.")

    # Ensure the original documents have not changed.
    for chunk in index["chunks"]:
        source = PROJECT_ROOT / chunk["source"]
        current_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        if current_hash != chunk["source_sha256"]:
            raise ValueError(
                f"Source changed: {chunk['source']}. "
                "Run prepare_rag_chunks.py and embed_rag_chunks.py again."
            )

    payload = {
        "model": index["embedding_model"],
        "input": f"task: search result | query: {question}",
        "truncate": False,
    }

    request = Request(
        "http://127.0.0.1:11434/api/embed",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    opener = build_opener(ProxyHandler({}))
    with opener.open(request, timeout=180) as response:
        reply = json.load(response)

    vectors = reply.get("embeddings", [])
    if len(vectors) != 1:
        raise ValueError("Expected exactly one query vector.")

    query_vector = vectors[0]
    if len(query_vector) != index["dimension"]:
        raise ValueError("Query and document dimensions do not match.")
    if not all(math.isfinite(value) for value in query_vector):
        raise ValueError("Invalid query vector.")

    norm = math.hypot(*query_vector)
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError("Invalid query vector length.")

    query_vector = [value / norm for value in query_vector]

    if index.get("normalized") is not True:
        raise ValueError("This search expects normalized document vectors.")

    results = []
    for chunk in index["chunks"]:
        # For normalized vectors, the dot product is cosine similarity.
        similarity = math.fsum(
            a * b
            for a, b in zip(
                query_vector, chunk["embedding"], strict=True
            )
        )
        results.append({
            "chunk_id": chunk["chunk_id"],
            "source": chunk["source"],
            "section": chunk["section"],
            "text": chunk["text"],
            "similarity": similarity,
        })

    results.sort(key=lambda result: result["similarity"], reverse=True)
    return results[:top_k]


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]).strip()
    if not question:
        raise SystemExit('Usage: python scripts/search_rag.py "Your question"')

    print(f"Question: {question}", flush=True)

    try:
        results = search(question)
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Ollama HTTP {error.code}: {details}")
    except (URLError, TimeoutError, ValueError, OSError) as error:
        raise SystemExit(f"Search failed: {error}")

    for rank, result in enumerate(results, start=1):
        print(f"\n[{rank}] Cosine similarity: {result['similarity']:.4f}")
        print(f"Chunk: {result['chunk_id']}")
        print(f"Source: {result['source']}")
        print(result["text"])
