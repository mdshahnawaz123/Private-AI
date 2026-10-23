"""Isolated subprocess runner for Masterplan Code Interpreter.

Executes AI-generated masterplan Python scripts inside an isolated child worker
without server memory access, without filesystem access, and without network access.
"""
import ast
import json
import math
import os
import re
import sys
import contextlib
import io
import pandas as pd
import numpy as np

BANNED_NAMES = {
    "open", "exec", "eval", "compile", "__import__", "input", "globals", "locals", "vars",
    "getattr", "setattr", "delattr", "breakpoint", "exit", "quit", "help", "memoryview",
    "os", "sys", "subprocess", "shutil", "socket", "pathlib", "importlib", "builtins",
    "requests", "urllib", "httpx"
}

BANNED_EXACT_ATTRS = {
    "eval", "query", "system", "popen", "read", "write", "load", "dump", "save", "pipe",
    "io", "compat", "clipboard", "sql", "table", "parquet", "feather", "stata", "sas", "spss",
    "memmap", "fromfile", "tofile", "loadtxt", "genfromtxt", "fromregex", "datasource", "savez", "savez_compressed"
}


def check_ast(code: str):
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)):
            raise ValueError("imports are not permitted in masterplan sandbox")
        if isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            raise ValueError(f"name '{node.id}' is not permitted")
        if isinstance(node, ast.Attribute):
            attr = node.attr.lower()
            if attr.startswith(("_", "read_", "to_", "load_", "save_", "from_")) or attr in BANNED_EXACT_ATTRS:
                raise ValueError(f"attribute '{node.attr}' is not permitted")
    return tree


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Missing job file argument"}))
        return

    job_path = sys.argv[1]
    with open(job_path, "r", encoding="utf-8") as f:
        job = json.load(f)

    code_str = job.get("code", "")
    try:
        check_ast(code_str)
    except Exception as exc:
        print(json.dumps({"error": f"AST validation failed: {exc}"}))
        return

    plots_records = job.get("plots", [])
    plots_df = pd.DataFrame(plots_records)

    # Sanitize pd to prevent any file I/O methods
    class SafePandas:
        Series = pd.Series
        DataFrame = pd.DataFrame
        concat = pd.concat
        isna = pd.isna
        notna = pd.notna
        to_numeric = pd.to_numeric
        merge = pd.merge
        pivot_table = pd.pivot_table

    class SafeNumpy:
        array = np.array
        asarray = np.asarray
        zeros = np.zeros
        ones = np.ones
        empty = np.empty
        arange = np.arange
        linspace = np.linspace
        mean = np.mean
        median = np.median
        std = np.std
        var = np.var
        sum = np.sum
        min = np.min
        max = np.max
        percentile = np.percentile
        round = np.round
        floor = np.floor
        ceil = np.ceil
        nan = np.nan
        inf = np.inf
        isnan = np.isnan
        isinf = np.isinf
        where = np.where
        unique = np.unique
        dot = np.dot
        sqrt = np.sqrt
        exp = np.exp
        log = np.log
        sin = np.sin
        cos = np.cos
        tan = np.tan
        pi = np.pi
        e = np.e
        ndarray = np.ndarray
        float64 = np.float64
        int64 = np.int64

    safe_builtins = {
        "len": len, "sum": sum, "min": min, "max": max, "round": round,
        "int": int, "float": float, "str": str, "bool": bool,
        "list": list, "dict": dict, "set": set, "sorted": sorted,
        "filter": filter, "map": map, "range": range, "isinstance": isinstance,
        "enumerate": enumerate, "zip": zip, "print": print, "abs": abs,
        "any": any, "all": all, "next": next,
    }

    env_globals = {
        "__builtins__": safe_builtins,
        "plots_df": plots_df,
        "pd": SafePandas,
        "np": SafeNumpy,
        "math": math,
        "re": re,
    }
    import builtins
    builtins.open = None
    io.open = None
    os.open = None
    os.system = None
    os.popen = None

    env_locals = {}
    try:
        exec(code_str, env_globals, env_locals)
    except Exception as exc:
        print(json.dumps({"error": f"Execution error: {exc}"}))
        return

    res = env_locals.get("result") or env_locals.get("esult")
    if isinstance(res, dict):
        print(json.dumps({"result": res}))
    else:
        print(json.dumps({"error": "No 'result' dictionary produced by script"}))


if __name__ == "__main__":
    main()
