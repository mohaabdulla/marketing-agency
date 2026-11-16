"""Operator-only cleanup of old generated renders (output/renders). Default is a dry run.

Generated cards, loops and campaign kits accumulate there and nothing else removes them.
Only regular files directly inside the renders folder are considered; nothing is followed
out of it. Deleted files cannot be recovered: keep anything you still need first.

    python scripts/cleanup_renders.py                 # report what is older than 14 days
    python scripts/cleanup_renders.py --days 7 --apply
    python scripts/cleanup_renders.py --only gif,zip --days 3 --apply
"""
import argparse
import json
import time
from pathlib import Path

RENDERS = Path(__file__).resolve().parents[1] / 'output' / 'renders'


def candidates(folder, days, only=None, now=None):
    cutoff = (now or time.time()) - days * 86400
    wanted = {'.' + ext.strip().lower().lstrip('.') for ext in only} if only else None
    found = []
    if not folder.is_dir():
        return found
    for path in folder.iterdir():
        if path.is_symlink() or not path.is_file() or path.name.startswith('.'):
            continue
        if wanted and path.suffix.lower() not in wanted:
            continue
        stat = path.stat()
        if stat.st_mtime < cutoff:
            found.append((path, stat.st_size))
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--days', type=float, default=14, help='remove files last modified more than this many days ago')
    parser.add_argument('--only', default='', help='comma-separated extensions to limit the cleanup to, e.g. gif,zip')
    parser.add_argument('--apply', action='store_true', help='actually delete; without it nothing is changed')
    args = parser.parse_args(argv)
    if args.days < 1:
        raise SystemExit('Refusing to remove renders newer than one day')
    root = RENDERS.resolve()
    found = candidates(root, args.days, [e for e in args.only.split(',') if e.strip()] or None)
    removed = 0
    if args.apply:
        for path, _ in found:
            # Verify each resolved target immediately before removal.
            if path.resolve().parent != root:
                raise SystemExit('Refusing a target outside the renders folder')
            path.unlink(missing_ok=True)
            removed += 1
    by_type = {}
    for path, size in found:
        entry = by_type.setdefault(path.suffix.lower() or '(none)', [0, 0])
        entry[0] += 1
        entry[1] += size
    print(json.dumps(dict(dry_run=not args.apply, older_than_days=args.days, files=len(found), megabytes=round(sum(s for _, s in found) / 1e6, 1),
                          by_type={k: dict(files=v[0], megabytes=round(v[1] / 1e6, 1)) for k, v in sorted(by_type.items())}, removed=removed)))


if __name__ == '__main__':
    main()
