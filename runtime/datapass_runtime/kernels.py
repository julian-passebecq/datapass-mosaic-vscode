"""Serialized persistent workers with timeout, restart and bounded concurrency.

Process separation is lifecycle isolation, NOT a sandbox for hostile Python.
The API has one process; each worker owns its own database. Do not run this
manager behind multiple Uvicorn workers.
"""
from __future__ import annotations
from contextlib import contextmanager
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from .content import CONTENT


class KernelTimeout(TimeoutError):
    pass


class Kernel:
    def __init__(self, directory: Path, mode: str, trusted: bool):
        args = [sys.executable,'-m','datapass_runtime.worker','--directory',str(directory),'--mode',mode]
        if trusted:
            args += ['--trusted-python']
        directory.mkdir(parents=True,exist_ok=True)
        self.log = open(directory / 'worker.stderr.log','a',encoding='utf-8')
        env = {k:v for k,v in os.environ.items() if not any(word in k.upper() for word in ('TOKEN','SECRET','PASSWORD','API_KEY'))}
        env['PYTHONUNBUFFERED'] = '1'
        env['DATAPASS_CONTENT_ROOT'] = str(CONTENT)
        self.process = subprocess.Popen(args,cwd=directory,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,text=True,encoding='utf-8',env=env)
        self.lock = threading.Lock()
        self.last_used = time.monotonic()
        self.reservations = 0

    def call(self, request: dict, timeout: float):
        with self.lock:
            self.last_used = time.monotonic()
            if self.process.poll() is not None:
                raise RuntimeError('The kernel exited. Restart the workspace kernel.')
            response = queue.Queue(maxsize=1)
            self.process.stdin.write(json.dumps(request)+'\n')
            self.process.stdin.flush()
            def read():
                try:
                    response.put(self.process.stdout.readline(3_000_002))
                except Exception as error:
                    response.put(error)
            thread = threading.Thread(target=read,daemon=True)
            thread.start()
            try:
                value = response.get(timeout=timeout)
            except queue.Empty:
                self.stop()
                raise KernelTimeout('Execution timed out. The kernel was terminated; restart it. Persisted tables remain, variables do not.')
            if isinstance(value, Exception):
                raise value
            if not value:
                raise RuntimeError('The worker exited without a response. Inspect worker.stderr.log.')
            if len(value) > 3_000_000:
                self.stop()
                raise RuntimeError('The worker returned too much output and was stopped.')
            try:
                payload = json.loads(value)
            except json.JSONDecodeError:
                self.stop()
                raise RuntimeError('The worker protocol was corrupted. The process was stopped.')
            if not payload['ok']:
                # A validated request rejected by the worker is not an outage.
                if payload.get('error_type') == 'ValueError':
                    raise ValueError(payload['error'])
                raise RuntimeError(payload['error'])
            return payload['result']

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        for stream in (self.process.stdin,self.process.stdout,self.log):
            if stream and not stream.closed:
                stream.close()


class KernelManager:
    def __init__(self, mode='auto',trusted=False,timeout=20.0,max_workers=6):
        self.mode,self.trusted,self.timeout,self.max_workers = mode,trusted,timeout,max_workers
        self.workers = {}
        self.workspace_locks = {}
        self.lock = threading.RLock()

    def get(self,id: str,directory: Path):
        with self.lock:
            if id in self.workers and self.workers[id].process.poll() is not None:
                self.workers.pop(id).stop()
            if id not in self.workers:
                if len(self.workers) >= self.max_workers:
                    idle = [(key,k) for key,k in self.workers.items() if not k.lock.locked() and k.reservations == 0]
                    if not idle:
                        raise RuntimeError('All local kernels are busy. Try again after a run completes.')
                    key,kernel = min(idle,key=lambda pair:pair[1].last_used)
                    kernel.stop()
                    del self.workers[key]
                self.workers[id] = Kernel(directory,self.mode,self.trusted)
            return self.workers[id]

    @contextmanager
    def workspace_lease(self, id):
        # Reentrant so pipeline tasks can use the same serialized kernel protocol.
        with self.lock:
            gate = self.workspace_locks.setdefault(id, threading.RLock())
        with gate:
            yield

    def call(self,id,directory,request):
        with self.workspace_lease(id):
            with self.lock:
                kernel = self.get(id,directory)
                kernel.reservations += 1
            try:
                return kernel.call(request,self.timeout)
            finally:
                with self.lock:
                    kernel.reservations -= 1

    def interrupt(self,id):
        """Cancellation path: must not wait on an external writer's lease."""
        with self.lock:
            if id in self.workers:
                self.workers.pop(id).stop()

    def restart(self,id):
        with self.workspace_lease(id):
            self.interrupt(id)
        return {'status':'restarted','message':'A new process will start on the next request. Tables persist; variables reset.'}

    def close(self):
        with self.lock:
            for kernel in self.workers.values():
                kernel.stop()
            self.workers.clear()
