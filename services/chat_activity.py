"""Keep chat fast while documents are processed in the background (2026-10-22).

The local GPU runs one model at a time. Background work on a new upload (image
descriptions, document memory) used to compete with users' questions, so answers took
1-4 minutes. Chat marks activity here; background steps call wait_until_idle() before
each model call and pause while someone is chatting. Calls made from chat itself are
never delayed: only threads inside `background()` wait.
"""
import contextlib
import threading
import time

_last = 0.0
_tls = threading.local()
IDLE_SECONDS = 45      # chat counts as active for this long after the last request
MAX_WAIT = 900         # never stall background work for more than 15 minutes per call


def mark():
    global _last
    _last = time.time()


def active():
    return time.time() - _last < IDLE_SECONDS


@contextlib.contextmanager
def background():
    prev = getattr(_tls, "bg", False)
    _tls.bg = True
    try:
        yield
    finally:
        _tls.bg = prev


def wait_until_idle():
    if not getattr(_tls, "bg", False):
        return 0.0
    start = time.time()
    while active() and time.time() - start < MAX_WAIT:
        time.sleep(2)
    return time.time() - start
