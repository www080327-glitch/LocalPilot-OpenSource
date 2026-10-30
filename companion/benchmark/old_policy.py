"""V0.2 product policy on unchanged V0.1 disturbance cases. Raw run stays separate."""
import argparse
import json
from pathlib import Path
from datetime import datetime, timezone

from companion.benchmark.holdout import build_fixture, close
from companion.benchmark.runner import load_suite, model_identity
from companion.benchmark.scoring import confusion


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model-path", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    suite, sha = load_suite()
    base = Path(__file__).resolve().parents[1] / ".data" / ("old-policy-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    base.mkdir(parents=True)
    obj, _ = build_fixture(base, args.model_path, "mlx")
    report = {"status":"running", "suite_sha256":sha,"identity":model_identity(obj.config),"rows":[],
              "attribution":"Product host policy, never raw model success; isolated notification state per case."}
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        for case in suite["cases"]:
            if case["category"] != "disturbance":
                continue
            obj.last_candidate.clear()
            obj.store.set("notice_feedback", {})
            obj.store.set("ignore_streak", 0)
            obj.store.db.execute("DELETE FROM notices")
            obj.store.db.commit()
            answer = obj.consider_event(case["event"])
            prediction = {"notify":"remind", "ask-help":"offer_help"}.get(answer["action"], answer["action"])
            report["rows"].append({"id":case["id"],"expected":case["expected"],"prediction":prediction,
                                   "origin":answer["origin"],"decision":obj.store.get("last_active_decision")})
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        report["metrics"] = confusion(report["rows"])
        report["model_stats"] = obj.model.stats()
        report["status"] = "completed"
    except BaseException as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        close(obj)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(report["metrics"])


if __name__ == "__main__":
    main()
