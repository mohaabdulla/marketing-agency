"""Bounded private jobs. Client research never leaks through public video job endpoints."""
import concurrent.futures
import logging
import threading
from .database import repository, uid, timestamp, packed, NotFound, Conflict
import json


class Cancelled(Exception):
    pass


class Task:
    def __init__(self,queue,key,client_id,kind):
        self.queue,self.id,self.client_id,self.kind=queue,key,client_id,kind
        self.event=threading.Event()

    def cancelled(self):
        return self.event.is_set()

    def check(self):
        if self.cancelled():
            raise Cancelled()

    def update(self,**values):
        self.queue.update(self.client_id,self.id,**values)


class Queue:
    def __init__(self,repo=repository):
        self.repo=repo
        self.pool=concurrent.futures.ThreadPoolExecutor(max_workers=2,thread_name_prefix='agency')
        self.lock=threading.Lock()
        self.active={}

    def recover(self):
        with self.repo.connection(write=True) as db:
            rows=db.execute("SELECT id,client_id,payload FROM jobs WHERE state NOT IN ('completed','failed','cancelled')").fetchall()
            for row in rows:
                data=json.loads(row['payload'])
                data.update(state='failed',error='Application restarted; submit this job again',updated_at=timestamp())
                db.execute('UPDATE jobs SET state=?,payload=?,updated_at=? WHERE id=?',
                           ('failed',packed(data),data['updated_at'],row['id']))

    def get(self,client_id,key):
        with self.repo.connection() as db:
            self.repo.client(db,client_id)
            row=db.execute('SELECT payload FROM jobs WHERE id=? AND client_id=?',(key,client_id)).fetchone()
            if not row:
                raise NotFound('Job not found in this client')
            return json.loads(row['payload'])

    def update(self,client_id,key,**values):
        with self.repo.connection(write=True) as db:
            row=db.execute('SELECT payload FROM jobs WHERE id=? AND client_id=?',(key,client_id)).fetchone()
            if not row:
                raise NotFound('Job not found')
            value=json.loads(row['payload'])
            value.update(values,updated_at=timestamp())
            db.execute('UPDATE jobs SET state=?,payload=?,updated_at=? WHERE id=?',
                       (value['state'],packed(value),value['updated_at'],key))
            return value

    def submit(self,client_id,kind,function,target_id=None):
        with self.lock:
            if len(self.active)>=8:
                raise Conflict('Agency queue is full; wait for an existing job')
            key,now=uid(),timestamp()
            value=dict(id=key,client_id=client_id,kind=kind,state='queued',stage='Waiting',progress=None,created_at=now,updated_at=now)
            with self.repo.connection(write=True) as db:
                self.repo.client(db,client_id,active=True)
                if target_id:
                    self.repo.record(db,client_id,target_id)
                    value['target_id']=target_id
                db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?)',(key,client_id,kind,'queued',packed(value),now,now))
                if target_id:
                    db.execute('INSERT INTO job_links VALUES (?,?,?,?)',(key,client_id,target_id,now))
                self.repo.audit(db,client_id,key,'job.queued',1,dict(kind=kind))
            task=Task(self,key,client_id,kind)
            self.active[key]=task
            self.pool.submit(self.execute,task,function)
            return value

    def execute(self,task,function):
        try:
            task.check()
            task.update(state='preparing',stage='Preparing')
            result=function(task)
            task.check()
            task.update(state='completed',stage='Completed',result=result,progress=None)
        except Cancelled:
            task.update(state='cancelled',stage='Stopped',progress=None)
        except Exception:
            logging.getLogger('lexnis.agency').exception('Agency task failed; job=%s',task.id)
            task.update(state='failed',error='Task failed; inspect local server diagnostics using this job ID',progress=None)
        finally:
            with self.lock:
                self.active.pop(task.id,None)

    def cancel(self,client_id,key):
        item=self.get(client_id,key)
        with self.lock:
            task=self.active.get(key)
            if task and task.client_id==client_id:
                task.event.set()
                return self.update(client_id,key,cancel_requested=True)
        return item


queue=Queue()
