"""Bounded in-flight document Q&A; excess work is rejected, never silently queued."""
import threading

class ModelBusyError(RuntimeError):
    pass

class Lease:
    def __init__(self,semaphore,owner=None):
        self.semaphore=semaphore;self.lock=threading.Lock();self.released=False;self.owner=owner
    def release(self):
        with self.lock:
            if not self.released:
                self.released=True;self.semaphore.release()
                if self.owner is not None:self.owner._dec()
    def __enter__(self):return self
    def __exit__(self,*args):self.release()

class ModelAdmission:
    def __init__(self,capacity=16):
        self.capacity=capacity;self.semaphore=threading.BoundedSemaphore(capacity)
        self._count_lock=threading.Lock();self._active=0
    def _dec(self):
        with self._count_lock:self._active=max(0,self._active-1)
    def active(self):
        """Interactive questions currently being answered. Background model
        work (Document Memory) waits while this is non-zero so a user's
        question is never stuck behind a long extraction call."""
        with self._count_lock:return self._active
    def acquire(self):
        if not self.semaphore.acquire(blocking=False):return None
        with self._count_lock:self._active+=1
        return Lease(self.semaphore,self)
    def require(self):
        lease=self.acquire()
        if lease is None:raise ModelBusyError('Local AI is busy. Please retry shortly.')
        return lease

document_model_admission=ModelAdmission()
