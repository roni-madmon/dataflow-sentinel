import hashlib
import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_DIR = PROJECT_ROOT / "docs" / "knowledge_base"
OUTPUT_PATH = PROJECT_ROOT / "artifacts" / "rag" / "chunks.json"

files = sorted(KNOWLEDGE_DIR.glob("*.md"))
if not files:
    raise SystemExit(f"No Markdown files found in: {KNOWLEDGE_DIR}")

chunks = []

for path in files:
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig").strip()

    if not text:
        raise SystemExit(f"Empty document: {path}")

    title = text.splitlines()[0].lstrip("#").strip()
    source = path.relative_to(PROJECT_ROOT).as_posix()
    source_hash = hashlib.sha256(raw).hexdigest()

    # Keep each section together, including its tables.
    sections = re.split(r"(?m)(?=^##[ \t]+)", text)

    for number, section in enumerate(sections, start=1):
        section = section.strip()
        if not section:
            continue

        heading = section.splitlines()[0].lstrip("#").strip()

        chunks.append({
            "chunk_id": f"{path.stem}:{number:02d}",
            "source": source,
            "source_sha256": source_hash,
            "title": title,
            "section": heading,
            "text": section,
        })

OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
OUTPUT_PATH.write_text(
    json.dumps(chunks, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

print(f"Documents: {len(files)}")
print(f"Chunks: {len(chunks)}")
print(f"Saved to: {OUTPUT_PATH}")

for chunk in chunks:
    print(f"  {chunk['chunk_id']} | {chunk['section']}")
