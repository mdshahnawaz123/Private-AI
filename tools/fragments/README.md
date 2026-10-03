# IFC → Fragments converter

Converts a raw `.ifc` into The Open Company **Fragments** binary (`.frag`) — ~9× smaller
and much faster to load. Runs server-side (Node) and is invoked automatically by the
backend as a background task when an `.ifc` is uploaded (see `convert_ifc_to_fragments`
in `main.py`).

## One-time install (on the machine that runs the backend)

```bash
cd tools/fragments
npm install
```

This pins `@thatopen/fragments@3.4.7`, `web-ifc@0.0.77`, `three@0.186.1` — the exact
versions proven in `OPENCOMPANY_FRAGMENTS_POC_RESULTS.md`. **web-ifc 0.0.78 is upstream-broken;
do not bump it without re-verifying the `StreamMeshes` binding.**

Requires Node 18+ (`node --version`). On Windows, make sure `node` is on `PATH`.

## Manual use / testing

```bash
node convert_ifc_to_frag.mjs path/to/model.ifc path/to/model.ifc.frag
```

Prints a one-line JSON result on success, e.g.:

```json
{"ok":true,"in":"model.ifc","out":"model.ifc.frag","inBytes":83656608,"outBytes":9080832,"ratio":9.21,"ms":9850}
```

On missing dependencies or a conversion error it prints `{"ok":false,"error":"..."}` to
stderr and exits non-zero. The backend treats any failure as "skip" — the original `.ifc`
is kept and the viewer falls back to parsing it directly, so a missing/broken converter
never blocks uploads.

## Backend controls (environment variables)

| Var | Default | Meaning |
|-----|---------|---------|
| `EXPO_FRAGMENTS_CONVERT` | `1` | `0` disables upload-time conversion entirely. |
| `EXPO_NODE_BIN` | `node` | Path to the Node binary if not on `PATH`. |
| `EXPO_FRAGMENTS_TIMEOUT` | `900` | Per-file conversion timeout, seconds. |
