import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, build_opener

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHUNKS_PATH = PROJECT_ROOT / "artifacts" / "rag" / "chunks.json"
OUTPUT_PATH = PROJECT_ROOT / "artifacts" / "rag" / "vector_index.json"

MODEL = "embeddinggemma:300m-bf16"
URL = "http://127.0.0.1:11434/api/embed"

raw_chunks = CHUNKS_PATH.read_bytes()
chunks = json.loads(raw_chunks.decode("utf-8-sig"))

if not chunks:
    raise SystemExit("No chunks found. Run prepare_rag_chunks.py first.")

# Check that the source documents still match the prepared chunks.
for chunk in chunks:
    source_path = PROJECT_ROOT / chunk["source"]
    current_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    if current_hash != chunk["source_sha256"]:
        raise SystemExit(
            f"Source changed: {chunk['source']}. "
            "Run prepare_rag_chunks.py again."
        )

# EmbeddingGemma's document format.
inputs = [
    f"title: {chunk['title']} | text: {chunk['text']}"
    for chunk in chunks
]

payload = {
    "model": MODEL,
    "input": inputs,
    "truncate": False,
}

request = Request(
    URL,
    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)

opener = build_opener(ProxyHandler({}))
print(f"Embedding {len(chunks)} chunks with {MODEL}...", flush=True)

try:
    with opener.open(request, timeout=180) as response:
        reply = json.load(response)
except HTTPError as error:
    details = error.read().decode("utf-8", errors="replace")
    raise SystemExit(f"Ollama HTTP {error.code}: {details}")
except (URLError, TimeoutError) as error:
    raise SystemExit(f"Could not complete the local Ollama request: {error}")

vectors = reply.get("embeddings", [])
if len(vectors) != len(chunks):
    raise SystemExit("The number of vectors does not match the chunks.")

dimension = len(vectors[0])

for chunk, vector in zip(chunks, vectors):
    if not dimension or len(vector) != dimension:
        raise SystemExit("Invalid or inconsistent vector dimensions.")
    if not all(math.isfinite(value) for value in vector):
        raise SystemExit("A vector contains invalid numeric values.")

    norm = math.hypot(*vector)
    if not math.isfinite(norm) or norm <= 0:
        raise SystemExit("A vector has an invalid length.")

    chunk["embedding"] = [value / norm for value in vector]

index = {
    "schema_version": 1,
    "created_at_utc": datetime.now(timezone.utc).isoformat(),
    "embedding_model": MODEL,
    "dimension": dimension,
    "normalized": True,
    "chunks_sha256": hashlib.sha256(raw_chunks).hexdigest(),
    "chunks": chunks,
}

OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
OUTPUT_PATH.write_text(
    json.dumps(index, ensure_ascii=False, indent=2, allow_nan=False),
    encoding="utf-8",
)

print(f"Chunks embedded: {len(chunks)}")
print(f"Vector dimension: {dimension}")
print(f"Saved to: {OUTPUT_PATH}")
