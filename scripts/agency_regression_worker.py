"""Run legacy scripts or a test HTTP server with local deterministic providers."""
import os
import runpy
import socket
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
import visual_engine
patch.object(visual_engine, "preferred_local_model", return_value=None).start()
import campaign_generator
patch.object(campaign_generator.LexnisCampaignStudio, "_chat", side_effect=RuntimeError("Offline regression runner")).start()
real_connect = socket.socket.connect


def local_connect(sock, address):
    if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "localhost", "::1"):
        raise OSError("External network disabled in regression runner")
    return real_connect(sock, address)


patch.object(socket.socket, "connect", local_connect).start()
import server
server.AGENCY_BUNDLES_DIR = server.RENDERS_DIR

if sys.argv[1] == "--serve":
    import uvicorn
    uvicorn.run(server.app, host="127.0.0.1", port=int(sys.argv[2]), log_level="error")
else:
    target = ROOT / "scripts" / sys.argv[1]
    source = target.read_text(encoding="utf-8")
    source = source.replace("http://127.0.0.1:8000", "http://127.0.0.1:" + os.environ["AGENCY_REGRESSION_PORT"])
    source = source.replace("http://localhost:8000", "http://127.0.0.1:" + os.environ["AGENCY_REGRESSION_PORT"])
    sys.argv = [str(target)]
    globals()["__file__"] = str(target)
    exec(compile(source, str(target), "exec"), globals())
