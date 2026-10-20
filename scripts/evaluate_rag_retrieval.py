import json
import re
from pathlib import Path

from search_rag import search


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHUNKS_PATH = PROJECT_ROOT / "artifacts" / "rag" / "chunks.json"
OUTPUT_PATH = PROJECT_ROOT / "artifacts" / "rag" / "retrieval_benchmark.json"


BENCHMARK = [
    {
        "question": "What is the alert threshold for HGB V2?",
        "expected": ["hgb_v2_model_card:03"],
    },
    {
        "question": "What was the Test precision of HGB V2?",
        "expected": ["hgb_v2_model_card:04"],
    },
    {
        "question": "Is the model score a calibrated probability?",
        "expected": [
            "hgb_v2_model_card:03",
            "hgb_v2_model_card:06",
        ],
    },
    {
        "question": "What should I check about CPU and memory for a risky Job?",
        "expected": ["job_failure_investigation_runbook:04"],
    },
    {
        "question": "What should I review about task counts and task types?",
        "expected": ["job_failure_investigation_runbook:05"],
    },
    {
        "question": "What should I do when planning metadata is missing?",
        "expected": ["job_failure_investigation_runbook:06"],
    },
    {
        "question": "Is HGB V2 verified as leakage-safe before execution?",
        "expected": [
            "job_failure_investigation_runbook:08",
            "hgb_v2_model_card:06",
        ],
    },
    {
        "question": "What investigation steps should I follow after a high-risk alert?",
        "expected": ["job_failure_investigation_runbook:09"],
    },
]


def tokens(text):
    return set(re.findall(r"[a-z0-9_]+", text.lower()))


def lexical_search(question, chunks, top_k=3):
    q = tokens(question)
    scored = []

    for chunk in chunks:
        doc = tokens(chunk["section"] + " " + chunk["text"])

        overlap = len(q & doc)
        union = len(q | doc)
        jaccard = overlap / union if union else 0.0

        scored.append(
            {
                "chunk_id": chunk["chunk_id"],
                "score": (overlap, jaccard),
            }
        )

    scored.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    return scored[:top_k]


def is_hit(results, expected, k):
    ids = [result["chunk_id"] for result in results[:k]]
    return any(chunk_id in expected for chunk_id in ids)


def evaluate():
    chunks = json.loads(CHUNKS_PATH.read_text(encoding="utf-8"))

    rows = []

    embedding_hit1 = 0
    embedding_hit3 = 0
    lexical_hit1 = 0
    lexical_hit3 = 0

    print("=" * 78)
    print("RAG RETRIEVAL BENCHMARK")
    print("=" * 78)

    for number, item in enumerate(BENCHMARK, start=1):
        embedding = search(item["question"], top_k=3)
        lexical = lexical_search(item["question"], chunks, top_k=3)

        e1 = is_hit(embedding, item["expected"], 1)
        e3 = is_hit(embedding, item["expected"], 3)
        l1 = is_hit(lexical, item["expected"], 1)
        l3 = is_hit(lexical, item["expected"], 3)

        embedding_hit1 += int(e1)
        embedding_hit3 += int(e3)
        lexical_hit1 += int(l1)
        lexical_hit3 += int(l3)

        row = {
            "question": item["question"],
            "expected": item["expected"],
            "embedding_top3": [
                result["chunk_id"] for result in embedding
            ],
            "lexical_top3": [
                result["chunk_id"] for result in lexical
            ],
            "embedding_hit_at_1": e1,
            "embedding_hit_at_3": e3,
            "lexical_hit_at_1": l1,
            "lexical_hit_at_3": l3,
        }

        rows.append(row)

        print()
        print(f"[{number}] {item['question']}")
        print(f"Expected:       {', '.join(item['expected'])}")
        print(
            "Embedding top3: "
            + ", ".join(row["embedding_top3"])
        )
        print(
            "Lexical top3:   "
            + ", ".join(row["lexical_top3"])
        )
        print(
            f"Embedding: Hit@1={e1} Hit@3={e3} | "
            f"Lexical: Hit@1={l1} Hit@3={l3}"
        )

    total = len(BENCHMARK)

    summary = {
        "questions": total,
        "embedding_hit_at_1": embedding_hit1 / total,
        "embedding_hit_at_3": embedding_hit3 / total,
        "lexical_hit_at_1": lexical_hit1 / total,
        "lexical_hit_at_3": lexical_hit3 / total,
    }

    print()
    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(f"Questions:           {total}")
    print(f"Embedding Hit@1:     {summary['embedding_hit_at_1']:.3f}")
    print(f"Embedding Hit@3:     {summary['embedding_hit_at_3']:.3f}")
    print(f"Lexical Hit@1:       {summary['lexical_hit_at_1']:.3f}")
    print(f"Lexical Hit@3:       {summary['lexical_hit_at_3']:.3f}")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(
            {
                "summary": summary,
                "results": rows,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print(f"Saved to: {OUTPUT_PATH}")


if __name__ == "__main__":
    evaluate()
