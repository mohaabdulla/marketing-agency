"""Status or explicit real local-text inference. Mocks never write verification markers."""
import argparse
import json
import platform
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agency.local_text import status,complete,CACHE,installation


class Progress:
    def check(self):pass
    def update(self,**values):print(json.dumps(values),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-inference',action='store_true')
    args=parser.parse_args()
    info=status();print(json.dumps(info,indent=2))
    if not args.run_inference:
        print('Status only: no model downloads or inference.');return
    if not info['available']:
        raise SystemExit(info['reason'])
    started=time.monotonic()
    draft=complete(dict(instruction='Draft a concise invitation to a product demonstration; do not invent performance claims.',
                        approved_claims=[],brief={'campaign_objective':'Invite a demo request'}),Progress(),max_tokens=512)
    manifest=installation()
    try:
        import psutil
        ram=round(psutil.virtual_memory().total/1024**3,2)
    except ImportError:ram=None
    marker=dict(success=True,model_id=info['id'],revision=manifest['revision'],sha256=manifest['sha256'],
                verified_at=time.time(),elapsed_seconds=round(time.monotonic()-started,2),
                hardware=dict(platform=platform.platform(),system_ram_gb=ram,peak_ram_gb=None,peak_vram_gb=None),
                output=draft.model_dump(),verification_scope='Actual schema-validated local inference, not quality certification')
    temp=CACHE/'verification.tmp';temp.write_text(json.dumps(marker,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(CACHE/'verification.json')
    print(json.dumps(marker,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
