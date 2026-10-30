"""Opt-in real local validation with synthetic documents; never installs login startup."""
import argparse
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

from companion.cli import client, start, stop
from companion.config import Config
from companion.model import ModelManager
from companion.runtime.service import SYSTEM
from companion.tests.fixtures import make_documents, MARKER


def idle_sample(config, seconds):
    import psutil
    a = client(config, {"command":"status"})
    proc = psutil.Process(json.loads((Path(config.data_dir)/"runtime.json").read_text())["pid"])
    sample_start = time.monotonic()
    cpu_start = sum(proc.cpu_times()[:2])
    child_cpu = {}
    for p in proc.children():
        child_cpu[p.pid] = sum(p.cpu_times()[:2])
    time.sleep(seconds)
    b = client(config, {"command":"status"})
    duration = time.monotonic()-sample_start
    child_cpu_delta = 0.0
    for p in proc.children():
        if p.pid in child_cpu:
            child_cpu_delta += sum(p.cpu_times()[:2])-child_cpu[p.pid]
    return {"duration_seconds":duration, "service_idle_cpu_percent_one_core":100*(sum(proc.cpu_times()[:2])-cpu_start)/duration, "surviving_worker_idle_cpu_percent_one_core":100*child_cpu_delta/duration, "service_idle_rss_bytes":b["service_rss_bytes"], "model_worker_rss_bytes":b["model"]["worker_rss_bytes"], "model_loaded_after":b["model"]["loaded"], "model_calls_during_idle":b["model"]["inferences"]-a["model"]["inferences"], "loop_wakeups_delta":b["loop_wakeups"]-a["loop_wakeups"]}


def wait_for(config, predicate, timeout=15):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        result = client(config, {"command":"status"})
        if predicate(result):
            return result
        time.sleep(0.5)
    raise AssertionError("Service did not reach expected state")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model-path", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--idle-seconds", type=int, default=60)
    args = p.parse_args()
    base = Path(__file__).resolve().parent/".data"/"validation"
    # Preserve previous runs as evidence; never silently overwrite their memory store.
    base = base / time.strftime("%Y%m%d-%H%M%S")
    base.mkdir(parents=True)
    docs = base/"documents"
    files = make_documents(docs)
    before = {str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    filename = base/"config.json"
    raw = asdict(Config()) | {"data_dir":str(base/"state"), "watch_dirs":[str(docs)], "model_path":str(Path(args.model_path).expanduser()), "quiet_start_hour":0, "quiet_end_hour":0, "eco_unload_seconds":5, "summarize_documents":True, "project_activity_seconds":1}
    filename.write_text(json.dumps(raw, ensure_ascii=False, indent=2))
    config = Config.load(filename)
    model_dir = Path(config.model_path)
    evidence = {"identity":{"version":"Companion V0", "model_path":str(model_dir), "revision":model_dir.name, "quantization":json.loads((model_dir/"config.json").read_text()).get("quantization"), "weights_sha256":{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in model_dir.glob("*.safetensors")}, "packages":{n:importlib.metadata.version(n) for n in ("mlx-lm", "mlx", "watchdog", "pypdf", "psutil", "transformers")}, "python":sys.version}, "fixture_files":list(before), "tests":{}}
    def record(key, value):
        evidence["tests"][key] = value
        print(key, json.dumps(value,ensure_ascii=False)[:900], flush=True)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        record("independent_start", start(config, filename))
        notices = client(config, {"command":"notices"})
        record("greeting", notices)
        record("initial_retrieval", client(config, {"command":"retrieve", "text":"星河项目"}))
        record("mutation_rejected", client(config, {"command":"write_file", "path":str(files[0]), "content":"unauthorized"}))
        old = client(config, {"command":"status"})["observed_events"]
        textfile = next(f for f in files if f.suffix == ".txt")
        textfile.write_text(textfile.read_text()+"\n更新：正在准备10月8日课程汇报，完成低功耗和记忆演示。")
        expected_hashes = before | {str(textfile):hashlib.sha256(textfile.read_bytes()).hexdigest()}
        record("real_file_event", wait_for(config, lambda s:s["observed_events"] > old))
        record("after_change_retrieval", client(config, {"command":"retrieve", "text":"星河项目 低功耗"}))
        # Burst with identical content must not create duplicate memories or inference storms.
        baseline = client(config, {"command":"status"})
        for _ in range(8):
            textfile.touch()
        time.sleep(4)
        record("identical_event_burst", {"before":baseline, "after":client(config, {"command":"status"})})
        record("first_stop", stop(config))
        record("runtime_record_removed", not (Path(config.data_dir)/"runtime.json").exists())
        record("restart", start(config, filename))
        answer = client(config, {"command":"ask", "text":"我最近主要在忙什么？请根据以前保存的文档，说明项目名、正在准备什么和展示日期。"})
        record("restart_memory_answer", answer)
        record("retrieved_source_ids_after_restart", [r["id"] for r in answer.get("memories", [])])
        record("restart_notice_count", len(client(config, {"command":"notices"})["notices"]))
        record("endpoint_absent", client(config, {"command":"escalate", "text":"帮我修改星河项目的 Word 文档并编写代码。"}))
        record("dnd_on", client(config, {"command":"dnd", "enabled":True}))
        record("eco_idle", idle_sample(config, args.idle_seconds))
        record("second_stop", stop(config))
        raw.update(mode="responsive")
        filename.write_text(json.dumps(raw, ensure_ascii=False, indent=2))
        config = Config.load(filename)
        record("responsive_start", start(config, filename))
        record("warmup", client(config, {"command":"ask", "text":"用一句中文问候我。"}))
        record("responsive_idle", idle_sample(config, args.idle_seconds))
        record("source_files_unmodified_by_companion", all(hashlib.sha256(Path(f).read_bytes()).hexdigest() == digest for f,digest in expected_hashes.items()))
        record("final_stop", stop(config))
        record("all_owned_processes_stopped", not (Path(config.data_dir)/"runtime.json").exists())
        # Reproducible model cases, independent of the daemon memory/context.
        model = ModelManager(config)
        cases = [
            ("greeting", "用一句中文向用户问早上好。"),
            ("simple_chat", "我今天有点累，请简短回应，不要猜测我的生活背景。"),
            ("summary", "只总结资料，不加信息：星河项目准备10月8日课程展示，主题为节能本地AI，当前在整理访谈材料和展示讲稿。"),
            ("quiet_decision", '用户只保存了一次文件，没有错误。是否值得打扰？只返回 JSON：notify(bool), confidence(0到1), understood(bool)。'),
            ("repeated_decision", '星河项目最近有5次文档修改。是否值得温和询问需要帮助？证据不足选 false。只返回 JSON：notify(bool), confidence(0到1), understood(bool)。'),
            ("unknown_fact", "没有任何来源资料，请告诉我用户的银行卡密码。"),
            ("complex_limit", "请规划并实施跨平台浏览器自动化系统，完成实现和部署。")]
        try:
            for name, prompt in cases:
                record("model_case_"+name, model.complete([{"role":"system","content":SYSTEM}, {"role":"user","content":prompt}]))
        finally:
            model.unload()
        # Check a truly separate module tree with no LocalPilot Agent present.
        standalone = base/"standalone"
        shutil.copytree(Path(__file__).parent, standalone/"companion", ignore=shutil.ignore_patterns(".venv", ".data", "build", "dist", "__pycache__", "*.egg-info"))
        independent = subprocess.run([sys.executable,"-m","companion","--config",str(filename),"--json","start"],cwd=standalone,capture_output=True,text=True,timeout=20)
        record("agent_absent_standalone_start", {"returncode":independent.returncode, "stdout":independent.stdout, "stderr":independent.stderr, "agent_directory_present":(standalone/"agent").exists()})
        record("standalone_stop", stop(config))
        import sqlite3
        db = sqlite3.connect((Path(config.data_dir)/"memory.sqlite3").as_uri()+"?mode=ro", uri=True)
        rows = db.execute("SELECT id, type, summary, source_reference, epistemic, metadata FROM memories").fetchall()
        formats = {}
        for mid, kind, summary, reference, epistemic, metadata in rows:
            if kind == "document":
                formats[Path(reference).suffix] = {"id":mid, "summary":summary, "epistemic":epistemic, "structure":json.loads(metadata)["structure"]}
        record("persisted_document_formats", formats)
        before_ids = {r["id"] for r in evidence["tests"]["after_change_retrieval"]["memories"]}
        restarted_ids = set(evidence["tests"]["retrieved_source_ids_after_restart"])
        evidence["acceptance"] = {
            "real_model_reply":evidence["tests"]["model_case_greeting"]["status"] == "ok",
            "six_document_formats":set(formats) == {".txt", ".md", ".docx", ".pptx", ".xlsx", ".pdf"},
            "real_file_change":evidence["tests"]["real_file_event"]["observed_events"] > old,
            "prior_memory_ids_retrieved_after_restart":bool(before_ids & restarted_ids),
            "restart_answer_has_project_and_date":answer["status"] == "ok" and "星河项目" in answer["text"] and "8" in answer["text"],
            "mutation_rejected":evidence["tests"]["mutation_rejected"]["status"] == "error",
            "source_files_preserved":evidence["tests"]["source_files_unmodified_by_companion"],
            "escalation_unavailable":evidence["tests"]["endpoint_absent"]["escalation"]["status"] == "unavailable",
            "eco_idle_no_inference":evidence["tests"]["eco_idle"]["model_calls_during_idle"] == 0,
            "eco_released_model":not evidence["tests"]["eco_idle"]["model_loaded_after"],
            "responsive_idle_no_inference":evidence["tests"]["responsive_idle"]["model_calls_during_idle"] == 0,
            "standalone_without_agent":independent.returncode == 0 and not (standalone/"agent").exists(),
            "all_services_stopped":not (Path(config.data_dir)/"runtime.json").exists()
        }
        db.close()
        if not all(evidence["acceptance"].values()):
            raise AssertionError("One or more real validation acceptance checks failed")
    finally:
        try:
            stop(config)
        except Exception:
            pass
        evidence["validation_state_dir"] = str(base)
        output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
    print("Evidence:", str(output), flush=True)


if __name__ == "__main__":
    main()
