"""Automatic backups for Expo Design AI (Windows-friendly, pure Python).

Every night (and on demand from Manage › System health) this:

1. Takes a consistent snapshot of every database (the SQLite online-backup API, safe
   while the app is running) plus data/secret.key and data/.env-free settings, into
       <backup dir>/db/<YYYY-MM-DD_HHMM>/
   The newest EXPO_BACKUP_KEEP snapshots are kept (default 14).
2. Mirrors the project files (documents, drawings, models, private uploads, CAD
   revisions, search index, recycle bin, reports, exports) into
       <backup dir>/files/
   copying only new or changed files. Files deleted in the app are NOT deleted from
   the mirror, so an accidental delete can still be recovered. (The search index is
   mirrored exactly, because it is rebuilt from the documents anyway.)

Settings (.env):
    EXPO_BACKUP_DIR=D:\\ExpoBackups     default: a folder next to the app folder.
                                        Best on a different disk or a network share.
    EXPO_BACKUP_HOUR=2                  local hour for the nightly run (0-23)
    EXPO_BACKUP_KEEP=14                 database snapshots to keep
    EXPO_BACKUP_ENABLED=1               0 turns the nightly run off

Restore: stop the app, copy files/<folder> back into data/<folder>, copy the .db files
and secret.key from the chosen db/<date> folder into data/, start the app.
"""
import datetime
import json
import os
import shutil
import sqlite3
import threading
import time

from loguru import logger

import db

MIRROR_DIRS = ["docs", "projects", "private_uploads", "cad_revisions", "recycle_bin", "reports", "exports",
               "workspace", "samples", "dashboards", "faiss_index"]
EXACT_MIRROR = {"faiss_index"}          # rebuildable: keep the mirror identical
DB_SUFFIXES = (".db", ".sqlite3", ".sqlite")
EXTRA_FILES = ["secret.key"]

_lock = threading.Lock()
_state = {"running": False}


def backup_dir():
    d = (os.getenv("EXPO_BACKUP_DIR") or "").strip()
    if not d:
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        d = os.path.join(os.path.dirname(app_dir), os.path.basename(app_dir) + "_Backups")
    return os.path.abspath(d)


def _status_path():
    return os.path.join(db.DATA_DIR, "backup_status.json")


def status():
    st = {}
    try:
        with open(_status_path(), encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError):
        pass
    st.update({"running": _state["running"], "backup_dir": backup_dir(),
               "enabled": os.getenv("EXPO_BACKUP_ENABLED", "1") != "0",
               "hour": _hour(), "keep": _keep()})
    try:
        st["same_disk_as_data"] = (os.path.splitdrive(os.path.abspath(db.DATA_DIR))[0].lower()
                                   == os.path.splitdrive(backup_dir())[0].lower())
    except Exception:
        pass
    last = st.get("finished_at")
    if last:
        try:
            st["age_hours"] = round((time.time() - datetime.datetime.fromisoformat(last).timestamp()) / 3600, 1)
        except Exception:
            pass
    return st


def _hour():
    try:
        return min(23, max(0, int(os.getenv("EXPO_BACKUP_HOUR", "2"))))
    except ValueError:
        return 2


def _keep():
    try:
        return max(1, int(os.getenv("EXPO_BACKUP_KEEP", "14")))
    except ValueError:
        return 14


def _snapshot_databases(dest):
    os.makedirs(dest, exist_ok=True)
    done = []
    for name in sorted(os.listdir(db.DATA_DIR)):
        src = os.path.join(db.DATA_DIR, name)
        if not os.path.isfile(src):
            continue
        if name.endswith(DB_SUFFIXES):
            if os.path.getsize(src) == 0:
                continue
            target = os.path.join(dest, name)
            s = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=60)
            t = sqlite3.connect(target)
            try:
                s.backup(t)
            finally:
                t.close(); s.close()
            done.append(name)
        elif name in EXTRA_FILES:
            shutil.copy2(src, os.path.join(dest, name))
            done.append(name)
    return done


def _mirror(src_root, dst_root, exact=False):
    copied = 0
    nbytes = 0
    seen = set()
    for root, dirs, files in os.walk(src_root):
        rel = os.path.relpath(root, src_root)
        out = os.path.join(dst_root, rel) if rel != "." else dst_root
        os.makedirs(out, exist_ok=True)
        for fn in files:
            if fn.endswith((".tmp", ".partial", ".lock")):
                continue
            s = os.path.join(root, fn)
            d = os.path.join(out, fn)
            seen.add(os.path.normcase(os.path.abspath(d)))
            try:
                st = os.stat(s)
                if os.path.exists(d):
                    dt = os.stat(d)
                    if dt.st_size == st.st_size and int(dt.st_mtime) >= int(st.st_mtime):
                        continue
                tmp = d + ".bak-tmp"
                shutil.copy2(s, tmp)
                os.replace(tmp, d)
                copied += 1
                nbytes += st.st_size
            except OSError as e:
                logger.warning("backup: could not copy {}: {}", s, e)
    if exact and os.path.isdir(dst_root):
        for root, dirs, files in os.walk(dst_root):
            for fn in files:
                p = os.path.normcase(os.path.abspath(os.path.join(root, fn)))
                if p not in seen:
                    try:
                        os.remove(p)
                    except OSError:
                        pass
    return copied, nbytes


def _prune(db_root):
    try:
        snaps = sorted(d for d in os.listdir(db_root) if os.path.isdir(os.path.join(db_root, d)))
    except OSError:
        return 0
    old = snaps[:-_keep()]
    for d in old:
        shutil.rmtree(os.path.join(db_root, d), ignore_errors=True)
    return len(old)


def run_backup(trigger="manual"):
    """Run one backup now (blocking). Returns the status dict. Only one runs at a time."""
    if not _lock.acquire(blocking=False):
        return dict(status(), message="A backup is already running.")
    _state["running"] = True
    started = datetime.datetime.now()
    result = {"trigger": trigger, "started_at": started.isoformat(timespec="seconds")}
    try:
        root = backup_dir()
        os.makedirs(root, exist_ok=True)
        snap = os.path.join(root, "db", started.strftime("%Y-%m-%d_%H%M%S"))
        result["databases"] = _snapshot_databases(snap)
        files = 0
        nbytes = 0
        for name in MIRROR_DIRS:
            src = os.path.join(db.DATA_DIR, name)
            if os.path.isdir(src):
                c, b = _mirror(src, os.path.join(root, "files", name), exact=name in EXACT_MIRROR)
                files += c
                nbytes += b
        result.update(files_copied=files, mb_copied=round(nbytes / 1048576, 1), snapshots_pruned=_prune(os.path.join(root, "db")),
                      snapshot=snap, ok=True)
        try:
            free = shutil.disk_usage(root).free
            result["free_gb_on_backup_disk"] = round(free / 1073741824, 1)
        except OSError:
            pass
        logger.info("Backup finished: {} databases, {} files ({} MB) -> {}", len(result["databases"]), files,
                    result["mb_copied"], root)
    except Exception as e:
        logger.exception("Backup failed")
        result.update(ok=False, error=str(e)[:300])
    finally:
        result["finished_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        result["duration_s"] = round((datetime.datetime.now() - started).total_seconds(), 1)
        prev = {}
        try:
            with open(_status_path(), encoding="utf-8") as f:
                prev = json.load(f)
        except (OSError, ValueError):
            pass
        if not result.get("ok") and prev.get("last_ok_at"):
            result["last_ok_at"] = prev["last_ok_at"]
        elif result.get("ok"):
            result["last_ok_at"] = result["finished_at"]
        try:
            with open(_status_path(), "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
            with open(os.path.join(backup_dir(), "last_backup.json"), "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
        except OSError:
            pass
        _state["running"] = False
        _lock.release()
    try:
        db.audit("system.backup", detail={k: result.get(k) for k in ("ok", "files_copied", "mb_copied", "error", "trigger")})
    except Exception:
        pass
    return dict(status(), **result)


def run_in_background(trigger="manual"):
    if _state["running"]:
        return False
    threading.Thread(target=run_backup, args=(trigger,), name="expo-backup", daemon=True).start()
    return True


def start_scheduler():
    """Nightly run at EXPO_BACKUP_HOUR; also catches up shortly after startup if the last
    good backup is older than 26 hours (for a PC that was off at night)."""
    if os.getenv("EXPO_BACKUP_ENABLED", "1") == "0":
        logger.info("Automatic backups are off (EXPO_BACKUP_ENABLED=0)")
        return

    def loop():
        time.sleep(300)
        last_day = None
        while True:
            try:
                st = status()
                now = datetime.datetime.now()
                age = None
                if st.get("last_ok_at"):
                    age = (now - datetime.datetime.fromisoformat(st["last_ok_at"])).total_seconds() / 3600
                due_nightly = now.hour == _hour() and last_day != now.date()
                overdue = age is None or age > 26
                if (due_nightly or overdue) and not _state["running"]:
                    last_day = now.date()
                    run_backup("nightly" if due_nightly else "catch-up")
            except Exception as e:
                logger.warning("backup scheduler: {}", e)
            time.sleep(600)

    threading.Thread(target=loop, name="expo-backup-scheduler", daemon=True).start()
