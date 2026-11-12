# Agency backup and restore

Use Dashboard **Create agency backup**, or:

```powershell
python scripts/agency_backup.py create
python scripts/agency_backup.py validate --file "path/to/backup.zip"
python scripts/agency_backup.py restore --file "path/to/backup.zip" --destination "output/agency-restored"
```

Creation uses SQLite online backup, then bundles the snapshot, referenced immutable
research originals and every registered asset file version (`assets/<sha256>.<ext>`,
including superseded versions kept in history). Backups stop at 512 MB in total; larger
asset libraries need an operator-managed archive of `output/agency`. Manifest: schema version, SHA-256, sizes. Validation checks paths/
limits, expected SQLite schema/identity, foreign keys and document hashes. Restore uses
a NEW EMPTY directory; no running database or old media is overwritten/deleted.

Stop the app, set AGENCY_DATA_DIR=output/agency-restored in .env, then restart to use it.

Privacy & Retention also offers a client-only data portability ZIP (128 MB cap), including
that client's current records, versions, audit, research originals and registered media.
It is not a restore bundle. Client erasure does not remove previously downloaded/exported
copies or full backups: review/rotate these separately, as the erasure preview explains.
Startup initializes v1 transactionally and rejects unknown/newer DBs. This is the first
agency SQL schema; no historical migration from a nonexistent agency database is claimed.
Future SQL upgrades must add explicit migrations/backups.

These backups exclude legacy image/video stores, models, code, browser data and secrets.
For a whole-application archive, separately protect:

- output/renders, output/uploads, operator-supplied brand files;
- output/video or configured VIDEO_DATA_DIR;
- static/assets/brand_kits.json and referenced logos;
- configuration/secrets via a separate protected process.

Hash validation is not a creator's digital signature. Keep staging/snapshot/archive disk
space available. At most 20 agency ZIPs and a 512 MB bundle are supported; move older
bundles to managed archival storage. Document quota: 1 GiB. No scheduled purge runs.
