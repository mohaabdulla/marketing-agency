"""Run isolated agency checks and write a machine-readable result; optional real browsers/media."""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', action='store_true')
    parser.add_argument('--media', action='store_true')
    args = parser.parse_args()
    scripts = ['verify_agency_core.py', 'verify_local_text_adapter.py', 'verify_agency_production.py',
               'verify_agency_acquisition.py', 'verify_agency_audio.py', 'verify_agency_privacy.py', 'verify_agency_planning.py']
    if args.browser:
        scripts += ['verify_agency_browser.py', 'verify_agency_production_browser.py', 'verify_agency_acquisition_browser.py']
    if args.media:
        scripts += ['run_agency_regressions.py', 'test_professional_agency_suite.py']
    folder = ROOT / 'output/agency-verification'
    folder.mkdir(parents=True, exist_ok=True)
    results = []
    for script in scripts:
        started = time.monotonic()
        try:
            result = subprocess.run([sys.executable, '-u', str(ROOT / 'scripts' / script)], cwd=ROOT,
                                    env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}, capture_output=True,
                                    text=True, encoding='utf-8', errors='replace', timeout=900,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            log = result.stdout + '\n' + result.stderr
            passed = result.returncode == 0
        except subprocess.TimeoutExpired:
            passed, log = False, 'Verification exceeded fifteen minutes'
        (folder / (Path(script).stem + '.log')).write_text(log, encoding='utf-8')
        count = re.search(r'Ran (\d+) tests?', log)
        entry = dict(script=script, passed=passed, tests=int(count[1]) if count else None, seconds=round(time.monotonic() - started, 2))
        results.append(entry)
        (folder / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
        print(('PASS' if passed else 'FAIL') + ': ' + script, flush=True)
    print('Results: output/agency-verification/results.json')
    raise SystemExit(0 if all(r['passed'] for r in results) else 1)


if __name__ == '__main__':
    main()
