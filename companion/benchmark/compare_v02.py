"""Identity/workload/prompt gate; no latency speedup claims from desktop runs."""
import argparse
import hashlib
import json
from pathlib import Path


def compare(a, b):
    failures = []
    for key in ("status", "kind", "suite_sha256", "fixture_sha256", "generation", "pipeline_config", "source_sha256"):
        if key not in a or key not in b or a[key] != b[key]:
            failures.append(key)
    if a.get("status") != "completed" or a.get("kind") != "real_model":
        failures.append("complete_real_runs_required")
    for report in (a, b):
        identity = report.get("identity", {})
        if not identity or report.get("identity_sha256") != hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest():
            failures.append("model_identity_missing_or_invalid")
    if a.get("identity", {}).get("hardware") != b.get("identity", {}).get("hardware"):
        failures.append("hardware")
    for report in (a, b):
        if len({r["id"] for r in report.get("rows", [])}) != len(report.get("rows", [])):
            failures.append("duplicate_cases")
    if {r["id"]:r["prompt_sha256"] for r in a.get("rows", [])} != {r["id"]:r["prompt_sha256"] for r in b.get("rows", [])}:
        failures.append("case_or_prompt_drift")
    return {"status":"BLOCKED" if failures else "accepted_diagnostic_comparison", "failures":sorted(set(failures)),
            "accepted_speedup":None,"speedup_status":"UNKNOWN: uncontrolled desktop load and differing output lengths",
            "first":a.get("metrics"),"second":b.get("metrics"),
            "same_prompt_count":sum(r["prompt_sha256"] == next((x["prompt_sha256"] for x in b.get("rows", []) if x["id"] == r["id"]), None) for r in a.get("rows", []))}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("first")
    p.add_argument("second")
    p.add_argument("--output", required=True)
    args = p.parse_args()
    result = compare(json.loads(Path(args.first).read_text()), json.loads(Path(args.second).read_text()))
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(result["status"])


if __name__ == "__main__":
    main()
