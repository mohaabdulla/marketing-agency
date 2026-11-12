"""SQLite repository: transactions, optimistic locking, immutable revisions and audit."""
import hashlib
import json
import os
import sqlite3
import threading
import uuid
from functools import lru_cache
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOME = ROOT / 'output/agency'
SCHEMA_VERSION = 1
APPLICATION_ID = 0x4C584E53
ORG_ID = '00000000000000000000000000000001'
ACTOR_ID = '00000000000000000000000000000002'


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


def uid():
    return uuid.uuid4().hex


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def packed(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True)


def checksum(value):
    return hashlib.sha256(packed(value).encode('utf-8')).hexdigest()


MIGRATION_1 = """
CREATE TABLE organizations(id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE operators(id TEXT PRIMARY KEY, organization_id TEXT NOT NULL REFERENCES organizations(id),
 name TEXT NOT NULL, role TEXT NOT NULL CHECK(role='local-operator'));
CREATE TABLE clients(id TEXT PRIMARY KEY, organization_id TEXT NOT NULL REFERENCES organizations(id),
 name TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL CHECK(json_valid(payload)),
 version INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE records(id TEXT PRIMARY KEY, client_id TEXT NOT NULL REFERENCES clients(id),
 kind TEXT NOT NULL, name TEXT NOT NULL, project_id TEXT, campaign_id TEXT,
 payload TEXT NOT NULL CHECK(json_valid(payload)), version INTEGER NOT NULL,
 archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(id,client_id),
 FOREIGN KEY(project_id,client_id) REFERENCES records(id,client_id),
 FOREIGN KEY(campaign_id,client_id) REFERENCES records(id,client_id));
CREATE INDEX records_scope ON records(client_id,kind,archived,updated_at);
CREATE TABLE links(source_id TEXT NOT NULL, target_id TEXT NOT NULL, client_id TEXT NOT NULL,
 relation TEXT NOT NULL, target_version INTEGER NOT NULL,
 PRIMARY KEY(source_id,target_id,relation),
 FOREIGN KEY(source_id,client_id) REFERENCES records(id,client_id),
 FOREIGN KEY(target_id,client_id) REFERENCES records(id,client_id));
CREATE TABLE revisions(resource_id TEXT NOT NULL, resource_type TEXT NOT NULL, client_id TEXT NOT NULL,
 version INTEGER NOT NULL, snapshot TEXT NOT NULL CHECK(json_valid(snapshot)), sha256 TEXT NOT NULL,
 actor_id TEXT NOT NULL REFERENCES operators(id), created_at TEXT NOT NULL,
 PRIMARY KEY(resource_id,version));
CREATE TABLE audit(id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id TEXT NOT NULL REFERENCES operators(id),
 client_id TEXT, resource_id TEXT NOT NULL, action TEXT NOT NULL, version INTEGER NOT NULL,
 created_at TEXT NOT NULL, details TEXT NOT NULL CHECK(json_valid(details)));
CREATE TABLE documents(id TEXT PRIMARY KEY, client_id TEXT NOT NULL REFERENCES clients(id), filename TEXT NOT NULL,
 original_name TEXT NOT NULL, mime TEXT NOT NULL, size INTEGER NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE job_links(job_id TEXT PRIMARY KEY, client_id TEXT NOT NULL REFERENCES clients(id),
 target_id TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE jobs(id TEXT PRIMARY KEY, client_id TEXT NOT NULL REFERENCES clients(id),
 kind TEXT NOT NULL, state TEXT NOT NULL, payload TEXT NOT NULL CHECK(json_valid(payload)),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
"""


def schema_signature(db):
    return packed([tuple(row) for row in db.execute("SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name")])


@lru_cache(maxsize=1)
def expected_schema():
    with closing(sqlite3.connect(':memory:')) as db:
        db.executescript(MIGRATION_1)
        return schema_signature(db)


class Repository:
    def __init__(self, home=None):
        self.home = Path(home or os.getenv('AGENCY_DATA_DIR', DEFAULT_HOME)).resolve()
        self.path = self.home / 'agency.sqlite3'
        self._lock = threading.Lock()
        self._initialized = False

    def initialize(self):
        with self._lock:
            if self._initialized:
                return
            self.home.mkdir(parents=True, exist_ok=True)
            for name in ('documents','backups','exports','work'):
                (self.home/name).mkdir(exist_ok=True)
            db = sqlite3.connect(self.path, timeout=10)
            try:
                db.execute('PRAGMA foreign_keys=ON')
                version = db.execute('PRAGMA user_version').fetchone()[0]
                if version > SCHEMA_VERSION:
                    raise RuntimeError('Agency database is newer than this application; restore the matching application version')
                if version == 0:
                    # No existing database format is overwritten. Older JSON stores stay untouched.
                    tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                    if tables:
                        raise RuntimeError('Unrecognized agency database: migration stopped without modifying it')
                elif db.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID:
                    raise RuntimeError('Not a LEXNIS agency database')
                elif schema_signature(db)!=expected_schema():
                    raise RuntimeError('Agency schema differs from the supported version; migration stopped')
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('PRAGMA trusted_schema=OFF')
                if version == 0:
                    db.executescript('BEGIN IMMEDIATE;\n' + MIGRATION_1)
                    now = timestamp()
                    db.execute('INSERT INTO organizations VALUES (?,?)', (ORG_ID,'Local agency'))
                    db.execute('INSERT INTO operators VALUES (?,?,?,?)', (ACTOR_ID,ORG_ID,'Local operator','local-operator'))
                    db.execute('INSERT INTO migrations VALUES (?,?)', (SCHEMA_VERSION,now))
                    db.execute(f'PRAGMA application_id={APPLICATION_ID}')
                    db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
                    db.commit()
                self._initialized = True
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()

    @contextmanager
    def connection(self, write=False):
        self.initialize()
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA trusted_schema=OFF')
        db.execute('PRAGMA busy_timeout=10000')
        try:
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            if write:
                db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def client(db, client_id, active=False):
        row = db.execute('SELECT * FROM clients WHERE id=?', (client_id,)).fetchone()
        if not row:
            raise NotFound('Client not found')
        if active and row['status'] == 'archived':
            raise Conflict('Restore the archived client before making changes')
        return Repository.unpack_client(row)

    @staticmethod
    def record(db, client_id, key, kind=None, include_archived=False):
        row = db.execute('SELECT * FROM records WHERE id=? AND client_id=?', (key,client_id)).fetchone()
        if not row or (kind and row['kind'] != kind) or (row['archived'] and not include_archived):
            raise NotFound('Record not found in this client')
        return Repository.unpack_record(row)

    @staticmethod
    def unpack_client(row):
        return dict(json.loads(row['payload']),id=row['id'],version=row['version'],
                    created_at=row['created_at'],updated_at=row['updated_at'])

    @staticmethod
    def unpack_record(row):
        return dict(id=row['id'],client_id=row['client_id'],kind=row['kind'],name=row['name'],
                    project_id=row['project_id'],campaign_id=row['campaign_id'],data=json.loads(row['payload']),
                    version=row['version'],archived=bool(row['archived']),
                    created_at=row['created_at'],updated_at=row['updated_at'])

    @staticmethod
    def audit(db, client_id, key, action, version, details=None):
        db.execute('INSERT INTO audit(actor_id,client_id,resource_id,action,version,created_at,details) VALUES (?,?,?,?,?,?,?)',
                   (ACTOR_ID,client_id,key,action,version,timestamp(),packed(details or {})))

    @staticmethod
    def revision(db, item, resource_type):
        db.execute('INSERT INTO revisions VALUES (?,?,?,?,?,?,?,?)',
                   (item['id'],resource_type,item.get('client_id',item['id']),item['version'],
                    packed(item),checksum(item),ACTOR_ID,timestamp()))

    def save_client(self, payload, key=None, expected_version=None):
        with self.connection(write=True) as db:
            old = self.client(db,key) if key else None
            if old and expected_version != old['version']:
                raise Conflict('Client changed elsewhere; reload before saving')
            key = key or uid()
            now, version = timestamp(), (old['version']+1 if old else 1)
            data = dict(payload)
            if old:
                db.execute('UPDATE clients SET name=?,status=?,payload=?,version=?,updated_at=? WHERE id=?',
                           (data['name'],data['status'],packed(data),version,now,key))
            else:
                db.execute('INSERT INTO clients VALUES (?,?,?,?,?,?,?,?)',
                           (key,ORG_ID,data['name'],data['status'],packed(data),version,now,now))
            item = self.client(db,key)
            self.revision(db,item,'client')
            self.audit(db,key,key,'client.updated' if old else 'client.created',version)
            return item

    def clients(self, limit=25, offset=0, query='', include_archived=False):
        with self.connection() as db:
            where = "organization_id=? AND (? OR status!='archived') AND (instr(lower(name),lower(?))>0)"
            params = (ORG_ID,int(include_archived),query)
            count = db.execute('SELECT count(*) FROM clients WHERE '+where,params).fetchone()[0]
            rows = db.execute('SELECT * FROM clients WHERE '+where+' ORDER BY updated_at DESC,id LIMIT ? OFFSET ?',
                              (*params,limit,offset)).fetchall()
            return dict(items=[self.unpack_client(r) for r in rows],total=count,limit=limit,offset=offset)

    def records(self, client_id, kind=None, project_id=None, campaign_id=None, limit=25, offset=0, query='', include_archived=False):
        with self.connection() as db:
            self.client(db,client_id)
            where, params = ['client_id=?','(? OR archived=0)','instr(lower(name),lower(?))>0'], [client_id,int(include_archived),query]
            for column,value in [('kind',kind),('project_id',project_id),('campaign_id',campaign_id)]:
                if value:
                    where.append(column+'=?')
                    params.append(value)
            sql = ' AND '.join(where)
            count = db.execute('SELECT count(*) FROM records WHERE '+sql,params).fetchone()[0]
            rows = db.execute('SELECT * FROM records WHERE '+sql+' ORDER BY updated_at DESC,id LIMIT ? OFFSET ?',
                              (*params,limit,offset)).fetchall()
            return dict(items=[self.unpack_record(r) for r in rows],total=count,limit=limit,offset=offset)

    def revisions(self, client_id, key,limit=25,offset=0):
        with self.connection() as db:
            total=db.execute('SELECT count(*) FROM revisions WHERE resource_id=? AND client_id=?',(key,client_id)).fetchone()[0]
            if not total:
                raise NotFound('History not found in this client')
            rows = db.execute('SELECT version,sha256,created_at,actor_id,snapshot FROM revisions WHERE resource_id=? AND client_id=? ORDER BY version DESC LIMIT ? OFFSET ?',
                              (key,client_id,limit,offset)).fetchall()
            return dict(items=[dict(r,snapshot=json.loads(r['snapshot'])) for r in rows],total=total,limit=limit,offset=offset)

    def backup(self):
        self.initialize()
        key = uid()
        path = self.home/'backups'/(key+'.sqlite3')
        with self.connection() as source, closing(sqlite3.connect(path)) as dest:
            source.backup(dest, pages=256, sleep=.01)
        self.validate_backup(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest = dict(id=key,schema_version=SCHEMA_VERSION,sha256=digest,size=path.stat().st_size,created_at=timestamp())
        path.with_suffix('.json').write_text(packed(manifest),encoding='utf-8')
        with self.connection(write=True) as db:
            self.audit(db,None,key,'backup.created',1,dict(sha256=digest))
        return manifest

    @staticmethod
    def validate_backup(path):
        if path.stat().st_size > 512*1024**2:
            raise ValueError('Agency database backup exceeds validation limit')
        with path.open('rb') as f:
            if f.read(16) != b'SQLite format 3\x00':
                raise ValueError('Not a SQLite database backup')
        # Immutable read-only connection; never execute imported SQL or schema triggers.
        db = sqlite3.connect(path.resolve().as_uri()+'?mode=ro&immutable=1',uri=True)
        try:
            db.execute('PRAGMA trusted_schema=OFF')
            if db.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID:
                raise ValueError('Not a LEXNIS agency backup')
            if db.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
                raise ValueError('Unsupported agency backup schema')
            if schema_signature(db)!=expected_schema():
                raise ValueError('Backup schema differs from the supported agency schema')
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('Agency backup integrity check failed')
        finally:
            db.close()
        return True


repository = Repository()
