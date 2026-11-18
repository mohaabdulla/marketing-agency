"""Operator-only cleanup of expired public-test workspaces. Stop the server first; default is dry-run."""
import argparse
import json
import shutil
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.public_access import guest_root


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    root=guest_root().resolve()
    candidates=[]
    if root.exists():
        for record in root.glob('*/session.json'):
            target=record.parent.resolve()
            if target.parent!=root or record.parent.is_symlink():
                continue
            try:
                if json.loads(record.read_text())['expires']>time.time():
                    continue
                jobs=list((target/'video/jobs').glob('*.json'))
                if any(json.loads(p.read_text()).get('state') not in {'completed','failed','cancelled'} for p in jobs):
                    continue
                candidates.append(target)
            except (ValueError,OSError,KeyError):
                continue
    for target in candidates:
        # Verify each resolved absolute target immediately before recursive removal.
        if target.resolve().parent!=root or target.is_symlink():
            raise SystemExit('Refusing a target outside the explicit guest storage root')
        if args.apply:
            shutil.rmtree(target)
    print(json.dumps(dict(dry_run=not args.apply,expired_workspaces=len(candidates),removed=len(candidates) if args.apply else 0)))


if __name__=='__main__':
    main()
