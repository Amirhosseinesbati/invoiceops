"""Collect document-only extraction and score saved InvoiceOps observations.

`collect-demo` never opens private labels. `score` is an offline step that opens
labels only after observed outputs have been saved. Neither command posts bills.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any


HEADER_FIELDS = (
    "vendor_name", "invoice_number", "invoice_date", "due_date", "po_number",
    "currency", "subtotal", "tax", "total",
)
MONEY_FIELDS = {"subtotal", "tax", "total"}
SUPPORTED_CURRENCIES = {"USD", "EUR", "GBP"}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def inputs_for(dataset_dir: Path, split: str) -> list[dict[str, Any]]:
    names = ("development", "held_out") if split == "both" else (split,)
    return [row for name in names for row in load_jsonl(dataset_dir / "evals" / "scenarios" / f"{name}.jsonl")]


def collect_demo(dataset_dir: Path, output: Path, split: str) -> dict[str, Any]:
    """Use the app's visible-document parser; no labels or seed JSON are read."""
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "apps" / "api"))
    from invoiceops.extraction import _page_texts, parse_visible_invoice

    root = dataset_dir.resolve()
    observations = []
    for case in inputs_for(dataset_dir, split):
        path = (dataset_dir / case["document_path"]).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"Scenario path escapes dataset: {case['case_id']}")
        row: dict[str, Any] = {
            "case_id": case["case_id"], "split": case["split"],
            "collector": "invoiceops.extraction._page_texts + parse_visible_invoice",
            "document_path": case["document_path"],
        }
        try:
            pages, warnings = _page_texts(path)
            row["extraction"] = parse_visible_invoice(pages).model_dump(mode="json")
            row["extraction_status"] = "extracted"
            row["warnings"] = warnings
        except Exception as exc:
            row["extraction_status"] = "failed"
            row["error"] = f"{type(exc).__name__}: {exc}"
        observations.append(row)
    write_jsonl(output, observations)
    return {"cases": len(observations), "extracted": sum(row["extraction_status"] == "extracted" for row in observations), "output": str(output)}


def normalized(field: str, value: Any) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    if field in MONEY_FIELDS:
        try:
            return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        except InvalidOperation:
            return str(value).strip()
    text = " ".join(str(value).strip().split())
    return text.casefold() if field == "vendor_name" else text.upper() if field in {"invoice_number", "po_number", "currency"} else text


def _metric(correct: int, predicted: int, expected: int) -> dict[str, Any]:
    return {
        "correct": correct,
        "predicted_nonempty": predicted,
        "expected": expected,
        "precision": round(correct / predicted, 6) if predicted else None,
        "recall": round(correct / expected, 6) if expected else None,
    }


def score(dataset_dir: Path, observations_path: Path, results_path: Path, report_path: Path, split: str) -> dict[str, Any]:
    inputs = inputs_for(dataset_dir, split)
    labels = {row["case_id"]: row for row in load_jsonl(dataset_dir / "evaluation_private" / "scenario_truth.jsonl")}
    observations = {row["case_id"]: row for row in load_jsonl(observations_path)}
    if len(observations) != len(load_jsonl(observations_path)):
        raise ValueError("Observation file has duplicate case_id values")
    field_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "predicted": 0, "expected": 0})
    group_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "predicted": 0, "expected": 0})
    operational_counts = {name: {"correct": 0, "measured": 0} for name in ("status", "blocking_finding", "approval_roles", "draft_bill_count")}
    case_rows = []
    supported_case_count = 0
    missing_observations = 0
    for case in inputs:
        case_id = case["case_id"]
        if case_id not in labels:
            raise ValueError(f"Missing private label for {case_id}")
        label = labels[case_id]
        observation = observations.get(case_id)
        if observation is None:
            missing_observations += 1
        extraction = observation.get("extraction", {}) if observation else {}
        supported = label["expected_blocking_finding"] != "corrupted_document" and label["expected_header"]["currency"] in SUPPORTED_CURRENCIES
        if supported:
            supported_case_count += 1
        details: dict[str, Any] = {"case_id": case_id, "split": case["split"], "supported_document": supported, "layout": label["layout"], "is_scanned": label["is_scanned"], "observation_present": observation is not None, "field_matches": {}}
        if supported:
            group_names = ("all_supported", f"layout:{label['layout']}", "scanned" if label["is_scanned"] else "native", f"split:{case['split']}")
            for field in HEADER_FIELDS:
                expected = normalized(field, label["expected_header"].get(field))
                predicted = normalized(field, extraction.get(field))
                matched = predicted is not None and predicted == expected
                details["field_matches"][field] = matched
                field_counts[field]["expected"] += int(expected is not None)
                field_counts[field]["predicted"] += int(predicted is not None)
                field_counts[field]["correct"] += int(matched)
                for group in group_names:
                    group_counts[group]["expected"] += int(expected is not None)
                    group_counts[group]["predicted"] += int(predicted is not None)
                    group_counts[group]["correct"] += int(matched)
        operational = observation.get("operational") if observation else None
        if isinstance(operational, dict):
            checks = {
                "status": operational.get("status") == label["expected_outcome"],
                "blocking_finding": (
                    label["expected_blocking_finding"] is None and not operational.get("finding_codes")
                    or label["expected_blocking_finding"] is not None and label["expected_blocking_finding"].upper() in set(operational.get("finding_codes", []))
                ),
                "approval_roles": set(operational.get("approval_roles", [])) == set(label["expected_approval_roles"]),
                "draft_bill_count": operational.get("draft_bill_count") == label["expected_draft_count_after_required_approvals"],
            }
            for name, matched in checks.items():
                source_key = {"status": "status", "blocking_finding": "finding_codes", "approval_roles": "approval_roles", "draft_bill_count": "draft_bill_count"}[name]
                if source_key in operational:
                    operational_counts[name]["measured"] += 1
                    operational_counts[name]["correct"] += int(matched)
            details["operational_matches"] = {name: checks[name] for name in checks if {"status": "status", "blocking_finding": "finding_codes", "approval_roles": "approval_roles", "draft_bill_count": "draft_bill_count"}[name] in operational}
        case_rows.append(details)
    all_fields = {
        "correct": sum(row["correct"] for row in field_counts.values()),
        "predicted": sum(row["predicted"] for row in field_counts.values()),
        "expected": sum(row["expected"] for row in field_counts.values()),
    }
    results: dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_dir": str(dataset_dir),
        "observations_path": str(observations_path),
        "split": split,
        "scenario_count": len(inputs),
        "supported_document_count": supported_case_count,
        "observation_count": len(inputs) - missing_observations,
        "missing_observation_count": missing_observations,
        "header_extraction": {
            "scope": "supported documents; nine material header fields",
            "overall": _metric(all_fields["correct"], all_fields["predicted"], all_fields["expected"]),
            "by_field": {field: _metric(row["correct"], row["predicted"], row["expected"]) for field, row in sorted(field_counts.items())},
            "by_group": {group: _metric(row["correct"], row["predicted"], row["expected"]) for group, row in sorted(group_counts.items())},
        },
        "operational": {
            name: {"correct": row["correct"], "measured": row["measured"], "accuracy": round(row["correct"] / row["measured"], 6) if row["measured"] else None}
            for name, row in operational_counts.items()
        },
        "cases": case_rows,
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    overall = results["header_extraction"]["overall"]
    lines = [
        "# InvoiceOps evaluation report", "",
        f"Generated: {results['generated_at_utc']}",
        f"Split: `{split}`; scenarios: {len(inputs)}; supported documents: {supported_case_count}; observations: {len(inputs) - missing_observations}; missing observations: {missing_observations}.",
        "", "## Deterministic header extraction", "",
        f"Exact normalized field matches: {overall['correct']}/{overall['predicted_nonempty']} nonempty predictions (precision); {overall['correct']}/{overall['expected']} expected fields (recall).",
        "", "| Group | Correct | Predicted | Expected | Precision | Recall |", "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, metric in results["header_extraction"]["by_group"].items():
        precision = "pending" if metric["precision"] is None else f"{metric['precision']:.3f}"
        recall = "pending" if metric["recall"] is None else f"{metric['recall']:.3f}"
        lines.append(f"| {name} | {metric['correct']} | {metric['predicted_nonempty']} | {metric['expected']} | {precision} | {recall} |")
    lines += ["", "## Operational outcomes", "", "Operational figures require saved observations from actual triggered workflow runs; document-only collection leaves these pending.", "", "| Check | Correct | Measured | Accuracy |", "| --- | ---: | ---: | ---: |"]
    for name, metric in results["operational"].items():
        accuracy = "pending" if metric["accuracy"] is None else f"{metric['accuracy']:.3f}"
        lines.append(f"| {name} | {metric['correct']} | {metric['measured']} | {accuracy} |")
    lines += ["", "## Interpretation", "", "This is synthetic-fixture measurement. `collect-demo` exercises the app's visible-text/OCR parser only. It does not prove asynchronous n8n routing, Xero behavior, or live-model quality. Missing observations lower coverage; null metrics mean unmeasured, not zero. Human review of a sample and separate connected-model testing remain required.", ""]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    collect = sub.add_parser("collect-demo", help="Run document-only local parser without opening private labels")
    collect.add_argument("--dataset-dir", type=Path, required=True)
    collect.add_argument("--output", type=Path, required=True)
    collect.add_argument("--split", choices=("development", "held_out", "both"), default="both")
    score_cmd = sub.add_parser("score", help="Compare saved observations with private labels offline")
    score_cmd.add_argument("--dataset-dir", type=Path, required=True)
    score_cmd.add_argument("--observations", type=Path, required=True)
    score_cmd.add_argument("--results", type=Path, required=True)
    score_cmd.add_argument("--report", type=Path, required=True)
    score_cmd.add_argument("--split", choices=("development", "held_out", "both"), default="held_out")
    args = parser.parse_args()
    if args.command == "collect-demo":
        print(json.dumps(collect_demo(args.dataset_dir, args.output, args.split), indent=2))
    else:
        result = score(args.dataset_dir, args.observations, args.results, args.report, args.split)
        print(json.dumps({key: result[key] for key in ("scenario_count", "supported_document_count", "observation_count", "missing_observation_count")}, indent=2))


if __name__ == "__main__":
    main()
