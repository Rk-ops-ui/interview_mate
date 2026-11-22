
import re
import numpy as np

GOOD_SIMILARITY = 0.75
FAIR_SIMILARITY = 0.50

_encoder = None


def _count_tokens(text):
    global _encoder

    try:
        if _encoder is None:
            import tiktoken
            _encoder = tiktoken.get_encoding("cl100k_base")

        return len(_encoder.encode(text))

    except Exception:
        return max(1, len(text) // 4)


def _is_english(text):
    letters = [c for c in text if c.isalpha()]

    if not letters:
        return True

    ascii_letters = sum(1 for c in letters if c.isascii())
    return ascii_letters / len(letters) >= 0.8


def _grade(similarity):
    if similarity >= GOOD_SIMILARITY:
        return "good"
    elif similarity >= FAIR_SIMILARITY:
        return "fair"
    return "poor"


def build_report(pairs, embeddings):
    """
    pairs:
    [
        {
            "chunk_id": 0,
            "source": "document.pdf",
            "original": "Original chunk text",
            "summary": "Compressed summary string"
        }
    ]

    embeddings: normalized LangChain embeddings object.
    """

    # Keep valid dictionary entries
    pairs = [
        p for p in pairs
        if isinstance(p, dict)
        and isinstance(p.get("original"), str)
        and p["original"].strip()
        and isinstance(p.get("summary"), str)
    ]

    if not pairs:
        return {"chunks": 0}

    originals = [p["original"] for p in pairs]
    summaries = [p["summary"] for p in pairs]

    # Generate embeddings together
    vectors = np.array(
        embeddings.embed_documents(originals + summaries),
        dtype=np.float32
    )

    orig_vecs = vectors[:len(pairs)]
    sum_vecs = vectors[len(pairs):]

    # Cosine similarity (vectors are normalized)
    similarities = np.sum(
        orig_vecs * sum_vecs,
        axis=1
    ).clip(0, 1)

    rows = []

    for p, original, summary, sim in zip(
        pairs, originals, summaries, similarities
    ):

        before = _count_tokens(original)
        after = _count_tokens(summary)

        rows.append({
            "chunk_id": p.get("chunk_id"),
            "source": p.get("source"),

            "tokens_before": before,
            "tokens_after": after,

            "similarity": round(float(sim), 3),
            "grade": _grade(float(sim)),

            # compress_text returns only a string
            "concept_coverage": None,

            "english": _is_english(summary),

            "degraded": False,
            "topic": "",

            "summary_preview": summary[:220],
            "original_preview": re.sub(
                r"\s+", " ", original
            )[:220],
        })

    total_before = sum(
        r["tokens_before"] for r in rows
    )

    total_after = sum(
        r["tokens_after"] for r in rows
    )

    grades = {
        grade: sum(
            1 for r in rows if r["grade"] == grade
        )
        for grade in ("good", "fair", "poor")
    }

    similarities = [r["similarity"] for r in rows]

    return {
        "chunks": len(rows),

        "tokens_before": total_before,
        "tokens_after": total_after,
        "tokens_saved": total_before - total_after,

        "reduction_percent": round(
            100 * (1 - total_after / total_before), 1
        ) if total_before else 0,

        "compression_ratio": round(
            total_before / total_after, 2
        ) if total_after else None,

        "avg_similarity": round(
            float(np.mean(similarities)), 3
        ),

        "min_similarity": round(
            float(np.min(similarities)), 3
        ),

        "avg_concept_coverage": None,

        "grades": grades,

        "non_english": sum(
            1 for r in rows if not r["english"]
        ),

        "degraded": 0,

        "thresholds": {
            "good": GOOD_SIMILARITY,
            "fair": FAIR_SIMILARITY
        },

        "weakest": sorted(
            rows,
            key=lambda r: r["similarity"]
        )[:5],

        "rows": rows,
    }
