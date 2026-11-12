"""Local operator backup/restore. Restore always targets a NEW empty directory."""
import argparse
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agency.database import repository
from agency.exports import backup_bundle,restore_bundle


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['create','validate','restore'])
    parser.add_argument('--file',type=Path)
    parser.add_argument('--destination',type=Path)
    args=parser.parse_args()
    if args.action=='create':
        manifest=backup_bundle()
        print(json.dumps(dict(manifest,file=str(repository.home/'backups'/(manifest['id']+'.zip'))),indent=2))
    elif not args.file:
        parser.error('--file is required for validation or restoration')
    elif args.action=='validate':
        with tempfile.TemporaryDirectory(prefix='lexnis-backup-validation-') as tmp:
            result=restore_bundle(args.file,Path(tmp)/'validated')
        print(json.dumps(dict(validated=True,schema_version=result['schema_version'])))
    elif not args.destination:
        parser.error('--destination must name an empty new directory')
    else:
        print(json.dumps(restore_bundle(args.file,args.destination),indent=2))
        print('Original storage was retained. To use the restored data, stop the application, set AGENCY_DATA_DIR to the destination, then restart.')


if __name__=='__main__':main()
