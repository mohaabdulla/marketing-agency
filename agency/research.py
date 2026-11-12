"""Bounded UTF-8 imports and optional, allowlisted, robots-aware single-page capture."""
import csv
import concurrent.futures
import hashlib
import http.client
import io
import ipaddress
import json
import os
import socket
import ssl
import tempfile
import threading
import time
import requests
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
from bs4 import BeautifulSoup
from .database import repository, uid, timestamp
from .schemas import RecordInput
from .services import service

MAX_FILE=10*1024**2
MAX_PAGE=2*1024**2
MAX_FETCH_SECONDS=20
_slots=threading.BoundedSemaphore(2)
_rate_lock=threading.Lock()
_last_request={}
_dns_pool=concurrent.futures.ThreadPoolExecutor(max_workers=2,thread_name_prefix='research-dns')
_dns_slots=threading.BoundedSemaphore(4)


def document(client_id,filename,content,mime,repo=repository):
    """Store immutable original bytes and metadata. Paths never come from the browser."""
    repo.initialize()
    if not 0<len(content)<=MAX_FILE:
        raise ValueError('Research file is empty or exceeds 10 MB')
    key=uid()
    extension=Path(filename).suffix.lower()
    if extension not in {'.txt','.csv'}:
        raise ValueError('Research imports support UTF-8 TXT and CSV')
    used=sum(p.stat().st_size for p in (repo.home/'documents').iterdir() if p.is_file())
    if used+len(content)>1024**3:
        raise ValueError('Research document storage limit reached')
    path=repo.home/'documents'/(key+extension)
    path.write_bytes(content)
    try:
        with repo.connection(write=True) as db:
            repo.client(db,client_id,active=True)
            db.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?,?)',
                (key,client_id,path.name,Path(filename.replace('\\','/')).name[:160],mime,len(content),
                 hashlib.sha256(content).hexdigest(),timestamp()))
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return key


def import_file(client_id,file,repo=repository,agency=service):
    if not _slots.acquire(blocking=False):
        raise ValueError('Two research imports are already running; retry shortly')
    try:
        with repo.connection() as db:
            repo.client(db,client_id,active=True)
        name=file.filename or ''
        ext=Path(name).suffix.lower()
        if ext not in {'.txt','.csv'}:
            raise ValueError('Use a UTF-8 TXT or CSV file. PDF and office formats are not enabled.')
        allowed={'text/plain','text/csv','application/csv','application/octet-stream','application/vnd.ms-excel'}
        if file.content_type not in allowed:
            raise ValueError('Unexpected research file MIME type')
        raw=file.file.read(MAX_FILE+1)
        if not raw or len(raw)>MAX_FILE or b'\x00' in raw or raw.startswith((b'PK\x03\x04',b'%PDF-',b'MZ')):
            raise ValueError('Invalid text document or file exceeds 10 MB')
        try:
            text=raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise ValueError('Import UTF-8 text; binary and legacy-encoded files are not accepted')
        if any(ord(c)<32 and c not in '\t\r\n' for c in text):
            raise ValueError('Text contains unsupported control characters')
        if ext=='.csv':
            rows=[]
            try:
                for n,row in enumerate(csv.reader(io.StringIO(text),strict=True)):
                    if n>=10000 or len(row)>100 or any(len(cell)>10000 for cell in row):
                        raise ValueError('CSV exceeds 10,000 rows, 100 columns or 10,000 characters per cell')
                    if sum(len(x) for x in rows)<120000:
                        rows.append(' | '.join(row))
            except csv.Error:
                raise ValueError('Invalid CSV structure')
            excerpt='\n'.join(rows)[:120000]
        else:
            excerpt=text[:120000]
        key=document(client_id,name,raw,'text/csv' if ext=='.csv' else 'text/plain',repo)
        try:
            return agency.save(client_id,'sources',RecordInput(name=Path(name).name[:160],data=dict(
                source_type='csv' if ext=='.csv' else 'document',content=excerpt,document_id=key,
                annotation='Imported original retained. Text shown is limited to the first 120,000 characters.')))
        except BaseException:
            with repo.connection(write=True) as db:
                row=db.execute('SELECT filename FROM documents WHERE id=?',(key,)).fetchone()
                db.execute('DELETE FROM documents WHERE id=?',(key,))
            if row:
                (repo.home/'documents'/row['filename']).unlink(missing_ok=True)
            raise
    finally:
        _slots.release()


def target(url):
    p=urlsplit(url)
    if p.scheme not in {'http','https'} or not p.hostname or p.username or p.password or p.fragment:
        raise ValueError('Research URL must be a public HTTP/HTTPS page without credentials or fragments')
    port=p.port or (443 if p.scheme=='https' else 80)
    if port not in {80,443}:
        raise ValueError('Research allows only ports 80 and 443')
    allowed={x.strip().lower() for x in os.getenv('AGENCY_RESEARCH_ALLOWED_DOMAINS','').split(',') if x.strip()}
    blocked={x.strip().lower() for x in os.getenv('AGENCY_RESEARCH_BLOCKED_DOMAINS','').split(',') if x.strip()}
    host=p.hostname.encode('idna').decode('ascii').lower()
    if os.getenv('AGENCY_WEB_RESEARCH','0')!='1' or host not in allowed or host in blocked:
        raise ValueError('Online capture is disabled or this exact domain is not allowlisted')
    if not _dns_slots.acquire(blocking=False):
        raise ValueError('Research DNS checks are busy; retry shortly')
    lookup=_dns_pool.submit(socket.getaddrinfo,host,port,type=socket.SOCK_STREAM)
    lookup.add_done_callback(lambda future:_dns_slots.release())
    try:
        resolved=lookup.result(timeout=3)
    except (concurrent.futures.TimeoutError,socket.gaierror):
        lookup.cancel()
        raise ValueError('Research hostname resolution failed or exceeded three seconds')
    addresses={entry[4][0] for entry in resolved}
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ValueError('Private, local and reserved research addresses are prohibited')
    return p,host,port,sorted(addresses,key=lambda ip:(ipaddress.ip_address(ip).version,ip))[0]


def fetch(url,path=None,max_bytes=MAX_PAGE):
    parsed,host,port,address=target(url)
    cls=http.client.HTTPSConnection if parsed.scheme=='https' else http.client.HTTPConnection
    kwargs=dict(timeout=10)
    if parsed.scheme=='https':
        kwargs['context']=ssl.create_default_context(cafile=os.getenv('AGENCY_RESEARCH_CA_BUNDLE') or requests.certs.where())
    connection=cls(host,port,**kwargs)
    # Pin the previously validated IP, while preserving TLS hostname verification and Host.
    connection._create_connection=lambda addr,timeout,source_address=None:socket.create_connection((address,port),timeout,source_address)
    request_path=path or ((parsed.path or '/')+('?' + parsed.query if parsed.query else ''))
    timer=None
    try:
        connection.connect()
        owned_socket=connection.sock
        def expire():
            try:owned_socket.shutdown(socket.SHUT_RDWR)
            except OSError:pass
        timer=threading.Timer(MAX_FETCH_SECONDS,expire)
        timer.daemon=True
        timer.start()
        connection.request('GET',request_path,headers={'User-Agent':'LexnisResearch/1.0','Accept':'text/html,text/plain','Accept-Encoding':'identity'})
        response=connection.getresponse()
        parts=[];size=0
        while size<=max_bytes:
            chunk=response.read1(min(65536,max_bytes+1-size))
            if not chunk:break
            parts.append(chunk);size+=len(chunk)
        body=b''.join(parts)
        if len(body)>max_bytes or response.getheader('Content-Encoding','identity') not in {'identity',''}:
            raise ValueError('Research response is compressed or exceeds its size limit')
        return response.status,response.getheader('Content-Type',''),body
    except ssl.SSLCertVerificationError:
        raise ValueError('Research TLS verification failed. Configure a trusted research CA bundle; certificate checks remain enabled.')
    finally:
        if timer:
            timer.cancel()
        connection.close()


def capture(client_id,source_id,expected_version,task,repo=repository,agency=service):
    source=agency.get(client_id,source_id,'sources')
    if source['version']!=expected_version:
        from .database import Conflict
        raise Conflict('Source changed; reload before capturing')
    url=source['data']['url']
    parsed,host,_,_=target(url)
    task.check()
    task.update(state='running',stage='Checking robots policy')
    status,_,robots=fetch(url,'/robots.txt',max_bytes=65536)
    delay=2.
    if status==200:
        policy=RobotFileParser()
        policy.parse(robots.decode('utf-8',errors='replace').splitlines())
        if not policy.can_fetch('LexnisResearch',url):
            raise ValueError('Robots policy disallows this page')
        delay=max(delay,policy.crawl_delay('LexnisResearch') or policy.crawl_delay('*') or 0)
    elif status!=404:
        raise ValueError('Could not confirm robots policy; capture stopped')
    if delay>30:
        raise ValueError('Site crawl delay exceeds this single-page capture budget')
    with _rate_lock:
        until=max(time.monotonic(),_last_request.get(host,0)+delay)
        if until-time.monotonic()>30:
            raise ValueError('Research domain rate queue is full; retry later')
        _last_request[host]=until
    while time.monotonic()<until:
        task.check()
        time.sleep(.1)
    task.check()
    task.update(stage='Capturing one public page')
    status,mime,body=fetch(url)
    if status!=200 or not any(x in mime.lower() for x in ['text/html','text/plain']):
        raise ValueError('Capture requires a successful HTML/text response; redirects are not followed')
    soup=BeautifulSoup(body.decode('utf-8',errors='replace'),'html.parser')
    for node in soup(['script','style','iframe','object','svg','noscript']):
        node.decompose()
    text=soup.get_text(' ',strip=True)[:120000]
    task.check()
    snapshot=document(client_id,'website-snapshot.txt',body,'text/plain',repo)
    data=dict(source['data'],content=text,snapshot_id=snapshot,captured_at=timestamp())
    # Capturing a page does not promote its evidence credibility.
    from .schemas import RecordInput
    try:
        result=agency.save(client_id,'sources',RecordInput(name=source['name'],project_id=source['project_id'],
            campaign_id=source['campaign_id'],data=data),source_id,expected_version)
    except BaseException:
        with repo.connection(write=True) as db:
            row=db.execute('SELECT filename FROM documents WHERE id=?',(snapshot,)).fetchone()
            db.execute('DELETE FROM documents WHERE id=?',(snapshot,))
        if row:
            (repo.home/'documents'/row['filename']).unlink(missing_ok=True)
        raise
    return result
