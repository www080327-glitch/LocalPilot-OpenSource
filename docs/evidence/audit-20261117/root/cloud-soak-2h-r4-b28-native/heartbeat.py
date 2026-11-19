import json,time
from pathlib import Path
start=time.monotonic()
with Path("heartbeat.jsonl").open("a") as stream:
    while time.monotonic()-start < 7200:
        stream.write(json.dumps({"elapsed":time.monotonic()-start})+"\n")
        stream.flush()
        time.sleep(min(30,max(0,7200-(time.monotonic()-start))))
Path("soak-finished.txt").write_text("LOCALPILOT_SOAK_COMPLETE")
print("LOCALPILOT_SOAK_COMPLETE",flush=True)
