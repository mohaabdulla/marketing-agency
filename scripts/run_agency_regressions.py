"""Execute every existing scripts/test*.py with bounded, offline providers."""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT/"output/agency_regressions"
LOGS.mkdir(parents=True, exist_ok=True)
worker = ROOT/"scripts/agency_regression_worker.py"
with socket.socket() as probe:
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
environment = {**os.environ, "PYTHONIOENCODING":"utf-8", "AGENCY_REGRESSION_PORT":str(port), "OMP_NUM_THREADS":"2"}
results = []
if "--retry-failed" in sys.argv and (LOGS/"results.json").is_file():
    results = [r for r in json.loads((LOGS/"results.json").read_text(encoding="utf-8")) if r["status"] == "passed"]
with (LOGS/"server.log").open("w", encoding="utf-8") as log:
    process = subprocess.Popen([sys.executable, "-u", str(worker), "--serve", str(port)], cwd=ROOT, env=environment,
                               stdout=log, stderr=log, creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    try:
        for _ in range(120):
            try:
                with socket.create_connection(("127.0.0.1",port), timeout=1):
                    break
            except OSError:
                if process.poll() is not None:
                    raise RuntimeError("Regression server failed; see server.log")
                time.sleep(.5)
        for target in sorted((ROOT/"scripts").glob("test*.py")):
            if target.name == "test_professional_agency_suite.py":
                continue  # Executed separately with its own detailed integration assertions.
            if any(r["script"] == target.name and r["status"] == "passed" for r in results):
                continue
            started = time.monotonic()
            with (LOGS/(target.stem+".log")).open("w", encoding="utf-8") as output:
                try:
                    # Video tests set their isolated storage BEFORE importing their modules.
                    # The legacy worker imports server first, which otherwise contaminates that isolation.
                    command = [sys.executable,"-u",str(target)] if target.name in {
                        "test_video_studio.py","test_video_studio_browser.py"} else [sys.executable,"-u",str(worker),target.name]
                    result = subprocess.run(command,cwd=ROOT,env=environment,
                                            stdout=output,stderr=output,timeout=600,
                                            creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
                    status = "passed" if result.returncode == 0 else "failed"
                except subprocess.TimeoutExpired:
                    status = "timeout"
            entry = {"script":target.name,"status":status,"seconds":round(time.monotonic()-started,1)}
            results.append(entry)
            (LOGS/"results.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
            print(f"{status.upper()}: {target.name} ({entry['seconds']}s)",flush=True)
    finally:
        process.terminate()
        process.wait(timeout=15)
sys.exit(0 if all(r["status"] == "passed" for r in results) else 1)
