"""Bounded in-flight document Q&A; excess work is rejected, never silently queued."""
import threading

class ModelBusyError(RuntimeError):
    pass

class Lease:
    def __init__(self,semaphore):
        self.semaphore=semaphore;self.lock=threading.Lock();self.released=False
    def release(self):
        with self.lock:
            if not self.released:self.released=True;self.semaphore.release()
    def __enter__(self):return self
    def __exit__(self,*args):self.release()

class ModelAdmission:
    def __init__(self,capacity=16):
        self.capacity=capacity;self.semaphore=threading.BoundedSemaphore(capacity)
    def acquire(self):
        return Lease(self.semaphore) if self.semaphore.acquire(blocking=False) else None
    def require(self):
        lease=self.acquire()
        if lease is None:raise ModelBusyError('Local AI is busy. Please retry shortly.')
        return lease

document_model_admission=ModelAdmission()
