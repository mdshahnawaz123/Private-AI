"""Restricted calculation sandbox for the answer agent (run as a child process).

    python -m services.agent_sandbox <job.json>

job.json = {"code": "...", "tables": {"<id>": {"title":..., "columns": [...], "rows": [[...]]}}}
The code sees `T` (dict of pandas DataFrames by table id, numbers already converted),
`pd`, `math`, `statistics`, and must print() its result. No imports, no file or
network access, no dunder attributes; the parent kills it after a time limit.
"""
import ast
import io
import json
import math
import re
import statistics
import sys
import contextlib

BANNED_NAMES = {"open", "exec", "eval", "compile", "__import__", "input", "globals", "locals", "vars",
                "getattr", "setattr", "delattr", "breakpoint", "exit", "quit", "help", "memoryview", "os", "sys",
                "subprocess", "shutil", "socket", "pathlib", "importlib", "builtins", "requests", "urllib", "httpx"}

BANNED_EXACT_ATTRS = {"eval", "query", "system", "popen", "read", "write", "load", "dump", "save", "pipe",
                      "io", "compat", "clipboard", "sql", "table", "parquet", "feather", "stata", "sas", "spss",
                      "memmap", "fromfile", "tofile", "loadtxt", "genfromtxt", "fromregex", "datasource", "savez"}


def check(code):
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)):
            raise ValueError("imports are not allowed")
        if isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            raise ValueError("'%s' is not allowed" % node.id)
        if isinstance(node, ast.Attribute):
            attr = node.attr.lower()
            if attr.startswith(("_", "read_", "to_", "load_", "save_", "from_")) or attr in BANNED_EXACT_ATTRS:
                raise ValueError("attribute '%s' is not allowed" % node.attr)
    return tree


def to_num(v):
    s = str(v if v is not None else "").replace(",", "").strip()
    pct = s.endswith("%")
    s = s.rstrip("%").strip()
    if re.fullmatch(r"[-+]?\d*\.?\d+(e[-+]?\d+)?", s, re.I):
        n = float(s)
        return n / 100.0 if pct else n
    return v


def main():
    import pandas as pd
    job = json.load(open(sys.argv[1], encoding="utf-8"))
    code = job.get("code") or ""
    try:
        check(code)
    except Exception as exc:
        print("ERROR: " + str(exc))
        return
    T = {}
    for tid, t in (job.get("tables") or {}).items():
        cols, seen = [], {}
        for c in t.get("columns") or []:
            c = str(c)
            seen[c] = seen.get(c, 0) + 1
            cols.append(c if seen[c] == 1 else "%s (%d)" % (c, seen[c]))
        rows = [[to_num(v) for v in (list(r) + [""] * (len(cols) - len(r)))[:len(cols)]] for r in t.get("rows") or []]
        df = pd.DataFrame(rows, columns=cols)
        # forgiving aliases: 'SQ.FT' for 'SQ.FT.', 'SQ.M.' for 'INCL. BALCONY / SQ.M.' (first wins)
        for c in list(cols):
            for al in (c.rstrip(".").strip(), c.split(" / ")[-1].strip(), c.split(" / ")[-1].rstrip(".").strip(),
                       c.upper(), c.lower(), c.title()):
                if al and al not in df.columns:
                    df[al] = df[c]
        try:
            df.attrs["title"] = t.get("title", "")
        except Exception:
            pass
        T[str(tid)] = df
        try:
            T[int(tid)] = df
        except ValueError:
            pass
    class SafePandas:
        Series = pd.Series
        DataFrame = pd.DataFrame
        concat = pd.concat
        isna = pd.isna
        notna = pd.notna
        to_numeric = pd.to_numeric
        merge = pd.merge
        pivot_table = pd.pivot_table

    safe_builtins = {k: __builtins__[k] if isinstance(__builtins__, dict) else getattr(__builtins__, k)
                     for k in ("abs", "all", "any", "bool", "dict", "enumerate", "filter", "float", "int", "len", "list",
                               "map", "max", "min", "print", "range", "round", "set", "sorted", "str", "sum", "tuple",
                               "zip", "isinstance", "reversed", "Exception", "ValueError", "KeyError", "TypeError")}
    import builtins
    builtins.open = None
    io.open = None
    import os
    os.open = None
    os.system = None
    os.popen = None

    env = {
        "__builtins__": safe_builtins,
        "T": T,
        "pd": SafePandas,
        "math": math,
        "statistics": statistics,
    }

    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            exec(compile(code, "<agent>", "exec"), env, env)
    except Exception as exc:
        buf.write("\nERROR: %s: %s" % (type(exc).__name__, str(exc)[:300]))
        if isinstance(exc, (KeyError, IndexError)):
            for tid, df in T.items():
                if isinstance(tid, str):
                    textc = [c for c in df.columns[:len(job["tables"][tid]["columns"])] if df[c].map(lambda v: isinstance(v, str) and v != "").any()]
                    buf.write("\nT[%s] columns: %s" % (tid, list(df.columns[:len(job["tables"][tid]["columns"])])))
                    for c in textc[:2]:
                        buf.write("\n  values in %r: %s" % (c, [v for v in df[c].tolist() if v][:20]))
    out = buf.getvalue().strip() or "(no output - use print())"
    print(out[:4000])


if __name__ == "__main__":
    main()
