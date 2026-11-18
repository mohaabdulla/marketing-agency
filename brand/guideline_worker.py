"""Server-controlled PDF parser subprocess; no user-selected executable or output path."""
import sys
from pathlib import Path
from brand.guidelines import extract

source,destination=sys.argv[1:]
try:
    text=extract(Path(source).read_bytes(),'guideline.pdf')
    Path(destination).write_text(text,encoding='utf-8')
except ValueError as exc:
    safe=str(exc) if str(exc).startswith(('Use an unencrypted','This PDF has no extractable','Guideline text must')) else 'PDF could not be parsed; export a text PDF or TXT guideline'
    Path(destination).with_suffix('.error').write_text(safe,encoding='utf-8')
    raise SystemExit(2)
