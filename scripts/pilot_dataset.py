"""Validate and export the pilot; no model calls, network or trading."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "research" / "pilot-001"
LABELS = {"SUFFICIENT_YES", "SUFFICIENT_NO", "INSUFFICIENT", "AMBIGUOUS"}
TASK = """Use only the supplied rule and evidence. Judge whether the evidence is
sufficient to establish the specified market outcome, not whether it is likely.
Return SUFFICIENT_YES, SUFFICIENT_NO, INSUFFICIENT, or AMBIGUOUS, with a brief
reason and supporting evidence IDs. Future plans are not completed events.
An announcement can suffice when the rule explicitly asks for an announcement.
Missing evidence is not evidence of absence. Do not use remembered later events.
AMBIGUOUS means the supplied rule/evidence has conflicting reasonable readings;
INSUFFICIENT means a required fact is missing or a future condition is unsettled.
Do not browse or use market prices. These are curated historical reading tasks,
not forecasts or instructions to trade."""


def build():
    corpus = json.loads((BASE / "corpus.json").read_text())
    labels = json.loads((BASE / "labels.provisional.json").read_text())
    cases = corpus["cases"]
    ids = [case["id"] for case in cases]
    if len(ids) != 10 or len(set(ids)) != 10:
        raise ValueError("Expected exactly ten unique pilot cases")
    if len(labels) != 10 or {row["id"] for row in labels} != set(ids):
        raise ValueError("Labels must match cases one-to-one")
    if any(row["provisional_label"] not in LABELS for row in labels):
        raise ValueError("Unknown label")
    inputs = []
    for case in cases:
        source = corpus["sources"][case["source_id"]]
        market = corpus["markets"][case["market_id"]]
        if not source["url"].startswith("https://"):
            raise ValueError("Missing official-source URL")
        facts = [source["facts"][i] for i in case["evidence_fact_indices"]]
        if not facts:
            raise ValueError("Empty evidence")
        # Whitelist fields. Never pass the research labels, rationales,
        # settled market page, case-type notes or future outcomes to a model.
        inputs.append({
            "id": case["id"],
            "instruction": TASK,
            "market": {
                "title": market["title"],
                "option": market["option"],
                "rule_paraphrase": market["rule"],
                "deadline": market["deadline"],
            },
            "evidence": {
                "publisher": source["publisher"],
                "publication_date_only": source["published_date"],
                "representation": "researcher paraphrase; original URLs and short excerpts in corpus.json",
                "segments": [
                    {"id": f"E{i + 1}", "text": fact}
                    for i, fact in enumerate(facts)
                ],
            },
        })
    return corpus, labels, inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, help="Write label-free JSON inputs")
    args = parser.parse_args()
    corpus, labels, inputs = build()
    payload = json.dumps(inputs, ensure_ascii=False, indent=2) + "\n"
    if args.export:
        args.export.parent.mkdir(parents=True, exist_ok=True)
        args.export.write_text(payload)
    print(json.dumps({
        "status": "validated_not_model_evaluated",
        "cases": len(inputs),
        "event_groups": len({c["event_group"] for c in corpus["cases"]}),
        "sources": len(corpus["sources"]),
        "provisional_labels": dict(Counter(r["provisional_label"] for r in labels)),
        "input_sha256": hashlib.sha256(payload.encode()).hexdigest(),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
