"""Prepare a synthetic local demonstration; never observes personal directories."""
from dataclasses import asdict
import argparse
import json
from pathlib import Path
from companion.config import Config
from companion.tests.fixtures import make_documents


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", required=True)
    args = parser.parse_args()
    base = Path(__file__).resolve().parent/".data"
    base.mkdir(exist_ok=True)
    docs = base/"demo-documents"
    if not docs.exists():
        make_documents(docs)
    filename = base/"demo.json"
    if filename.exists():
        raise SystemExit(f"Existing demo config preserved: {filename}")
    data = asdict(Config()) | {"data_dir":str(base/"demo-state"), "watch_dirs":[str(docs)], "model_path":str(Path(args.model_path).expanduser())}
    filename.write_text(json.dumps(data,ensure_ascii=False,indent=2))
    print(filename)


if __name__ == "__main__":
    main()
