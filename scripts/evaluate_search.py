"""Small curated evaluation, not a general retrieval benchmark. Uses the active full catalog."""

import argparse
import json
import statistics
import time
from pathlib import Path

from aimo.config import settings
from aimo.db import connection
from aimo.schemas import Requirements, SearchRequest
from aimo.search import model_key, search_products
from aimo.search_provider import RERANK_MODEL

MILKS = {
    "464306",
    "465039",
    "464398",
    "464201",
    "464440",
    "466288",
    "464073",
    "464119",
    "464237",
    "463380",
    "463335",
    "464198",
}
CASES = [
    ("464306", {"464306"}, {}, "identifier"),
    ("465039", {"465039"}, {}, "identifier"),
    ("460123", {"460123"}, {}, "identifier"),
    ("460675", {"460675"}, {}, "identifier"),
    ("460035", {"460035"}, {}, "identifier"),
    ("6408430000487", {"464306"}, {}, "identifier"),
    ("laktoositon kevytmaito", MILKS, {"lactose_free": True}, "description"),
    ("lactose free milk", MILKS, {"lactose_free": True}, "description"),
    ("lactose free milk for hotel breakfast", MILKS, {"lactose_free": True}, "description"),
    ("plain lactose free semi skimmed milk 1 litre", MILKS, {"lactose_free": True}, "description"),
    ("Valio Eila kevytmaitojuoma 1 l", {"465039", "464306", "464398"}, {}, "description"),
    ("Valio Eila semi skimmed milk drink 1 l", {"465039", "464306", "464398"}, {}, "description"),
    ("Arki Eila maitojuoma", {"464306"}, {}, "description"),
    ("Arki lactose free milk", {"464306"}, {"lactose_free": True}, "description"),
    (
        "UHT lactose free milk",
        {"464398", "464201", "464440", "466288"},
        {"lactose_free": True},
        "description",
    ),
    (
        "laktoositon iskukuumennettu maito",
        {"464398", "464201", "464440", "466288"},
        {"lactose_free": True},
        "description",
    ),
    ("Snellman flank steak", {"460675"}, {}, "description"),
    ("flank steak", {"460675", "467050", "469861"}, {}, "description"),
    ("Snellman naudan kuve", {"460675"}, {}, "description"),
    ("lettuce mix", {"460035", "473237", "472063", "473739"}, {}, "description"),
    ("salaattisekoitus", {"460035", "473237", "472063", "473739"}, {}, "description"),
    ("Järvikylä Maukas salaatti", {"473237", "472063"}, {}, "description"),
    ("Järvikylä salad mix", {"473237", "472063", "473739"}, {}, "description"),
    ("Vitamin Well 500 ml", {"460123", "477289", "476953", "477138"}, {}, "description"),
    ("Vitamin Well Antioxidant peach", {"476953"}, {}, "description"),
    ("Vitamin Well Awake raspberry", {"477138"}, {}, "description"),
    ("Vitamin Well Prepare", {"477289"}, {}, "description"),
    ("464306", set(), {"milk_free": True}, "no_match"),
    ("468044", set(), {"milk_free": True}, "no_match"),
    ("469429", set(), {"milk_free": True}, "no_match"),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/search-evaluation.json"))
    parser.add_argument(
        "--strategies",
        nargs="+",
        choices=("keyword", "semantic", "hybrid"),
        default=["keyword", "semantic", "hybrid"],
    )
    args = parser.parse_args()
    with connection() as c:
        identity = c.execute("SELECT * FROM identities WHERE id='demo-agent'").fetchone()
    report = {
        "model": model_key(),
        "reranker": RERANK_MODEL
        if settings().embedding_backend == "openrouter" and settings().rerank_enabled
        else None,
        "rerank_enabled": settings().embedding_backend == "openrouter"
        and settings().rerank_enabled,
        "cases": len(CASES),
        "scope": "Curated challenge cases; labels are incomplete beyond top-five relevance. Not a held-out benchmark.",
        "strategies": {},
    }
    for strategy in args.strategies:
        rows = []
        for query, relevant, requirements, kind in CASES:
            start = time.perf_counter()
            result = search_products(
                identity,
                SearchRequest(query=query, requirements=Requirements(**requirements), limit=5),
                strategy,
            )
            elapsed = (time.perf_counter() - start) * 1000
            ids = [p["id"] for p in result["products"]]
            violations = sum(
                bool(requirements.get("lactose_free") and "FREE_FROM_LACTOSE" not in p["claims"])
                or bool(
                    requirements.get("milk_free")
                    and ("AM" not in p["free_from"] or "AM" in p["allergens"])
                )
                for p in result["products"]
            )
            rows.append(
                {
                    "query": query,
                    "kind": kind,
                    "ids": ids,
                    "top1_relevant": ids[0] in relevant if ids else not relevant,
                    "top5_hit": bool(set(ids) & relevant) if relevant else not ids,
                    "constraint_violations": violations,
                    "latency_ms": round(elapsed, 1),
                    "rerank_status": result.get("rerank_status", "disabled"),
                }
            )
        report["strategies"][strategy] = {
            "top1": sum(r["top1_relevant"] for r in rows),
            "top5": sum(r["top5_hit"] for r in rows),
            "constraint_violations": sum(r["constraint_violations"] for r in rows),
            "warm_median_ms": round(statistics.median(r["latency_ms"] for r in rows[1:]), 1),
            "first_query_ms": rows[0]["latency_ms"],
            "rerank_unavailable": sum(r["rerank_status"] == "unavailable" for r in rows),
            "description_median_ms": round(
                statistics.median(r["latency_ms"] for r in rows if r["kind"] == "description"), 1
            ),
            "by_kind": {
                kind: {
                    "count": sum(r["kind"] == kind for r in rows),
                    "top1": sum(r["top1_relevant"] for r in rows if r["kind"] == kind),
                    "top5": sum(r["top5_hit"] for r in rows if r["kind"] == kind),
                }
                for kind in ("identifier", "description", "no_match")
            },
            "details": rows,
        }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: {a: b for a, b in v.items() if a != "details"}
                for k, v in report["strategies"].items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
