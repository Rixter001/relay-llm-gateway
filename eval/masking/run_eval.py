"""Masking evaluation: how much of the labeled PII does Relay's masker actually catch?

Usage:  python eval/masking/run_eval.py [--min-recall 0.9]

Metrics, computed over every labeled entity in dataset.jsonl:
  recall     share of labeled PII values that are FULLY covered by detections. A value that is
             only partly masked ("Marie <PERSON_1>") counts as a miss, because part of it leaks.
  precision  share of detections that overlap a labeled PII value (the rest are false positives,
             i.e. harmless words masked by mistake, which degrade the answer but leak nothing).

Recall matters most for compliance, so it is the metric that fails the CI build.
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.masking import build_presidio_masker  # noqa: E402

DATASET = Path(__file__).with_name("dataset.jsonl")


def expected_spans(text: str, entities: list[dict[str, str]]) -> list[tuple[str, int, int]]:
    spans = []
    for entity in entities:
        start = text.index(entity["value"])
        spans.append((entity["type"], start, start + len(entity["value"])))
    return spans


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-recall", type=float, default=0.90)
    parser.add_argument("--report", type=Path, default=Path(__file__).with_name("report.json"))
    args = parser.parse_args()

    started = time.perf_counter()
    masker = build_presidio_masker(languages=["en", "fr"], entities=None, score_threshold=0.35)
    print(f"Loaded Presidio in {time.perf_counter() - started:.1f}s")

    samples = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines()]
    caught_by_type: dict[str, list[bool]] = defaultdict(list)
    true_pos = false_pos = 0
    misses: list[dict[str, object]] = []
    false_positives: list[dict[str, object]] = []

    for sample in samples:
        text = sample["text"]
        truth = expected_spans(text, sample["entities"])
        detected = masker.detect(text)
        covered = set()
        for d in detected:
            covered.update(range(d.start, d.end))

        for entity_type, start, end in truth:
            # Whitespace inside a value ("FR76 3000 ...") does not need to be covered.
            needed = {i for i in range(start, end) if not text[i].isspace()}
            caught = needed <= covered
            caught_by_type[entity_type].append(caught)
            if not caught:
                misses.append({"id": sample["id"], "type": entity_type, "value": text[start:end]})

        for d in detected:
            if any(d.start < end and start < d.end for _, start, end in truth):
                true_pos += 1
            else:
                false_pos += 1
                false_positives.append(
                    {"id": sample["id"], "type": d.entity_type, "value": text[d.start : d.end]}
                )

    total = sum(len(v) for v in caught_by_type.values())
    caught_total = sum(sum(v) for v in caught_by_type.values())
    recall = caught_total / total if total else 1.0
    precision = true_pos / (true_pos + false_pos) if (true_pos + false_pos) else 1.0

    lines = [
        "## Masking evaluation",
        "",
        f"{len(samples)} prompts, {total} labeled PII values.",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Recall | {recall:.1%} ({caught_total}/{total}) |",
        f"| Precision | {precision:.1%} ({true_pos}/{true_pos + false_pos}) |",
        "",
        "| Entity type | Recall |",
        "|---|---|",
    ]
    for entity_type, results in sorted(caught_by_type.items()):
        lines.append(
            f"| {entity_type} | {sum(results) / len(results):.0%} ({sum(results)}/{len(results)}) |"
        )
    lines.append("")
    lines.append(f"Threshold: recall >= {args.min_recall:.0%}")
    summary = "\n".join(lines)
    print(summary)
    if misses:
        print("\nMissed:", *[f"  #{m['id']} {m['type']}: {m['value']}" for m in misses], sep="\n")
    if false_positives:
        print(
            "\nFalse positives:",
            *[f"  #{f['id']} {f['type']}: {f['value']}" for f in false_positives],
            sep="\n",
        )

    args.report.write_text(
        json.dumps(
            {
                "recall": recall,
                "precision": precision,
                "recall_by_type": {k: sum(v) / len(v) for k, v in caught_by_type.items()},
                "misses": misses,
                "false_positives": false_positives,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    # On GitHub Actions, also show the table on the workflow run page.
    if step_summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write(summary + "\n")

    if recall < args.min_recall:
        print(f"\nFAIL: recall {recall:.1%} is below the {args.min_recall:.0%} threshold")
        return 1
    print("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
