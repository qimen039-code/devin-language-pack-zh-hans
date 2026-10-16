#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Install the Devin webapp zh-hans overlay.

Devin Desktop renders its Sessions / Settings UI inside a sandboxed iframe that
loads the remote web app (https://app.devin.ai).  The iframe injector lives in
TWO bundles, and each carries its own copy of the URL builder plus its own copy
of the install-host resolver:

    out/vs/sessions/sessions.desktop.main.js
        V6r(But(this._authService,this._devinService), ...)     x2
        V6r = URL builder      But = webappHost/webUrl resolver

    out/vs/workbench/workbench.desktop.main.js
        oSe(QC(this._authService,this._devinService), ...)      x2   (desktop nav)
        oSe(this._devinService.webUrl, ...)                     x1   (Devin Sidebar)
        oSe = URL builder      QC  = webappHost/webUrl resolver

Both are rewritten so the iframe loads from the local proxy instead of the
remote origin.  Edits are byte-level: the file is never decoded, so no encoding
can be damaged.

    python webapp/install.py --app "<devin-install-dir>" [--port 5175] [--dry-run]
    python webapp/install.py --status

The install directory is remembered in %LOCALAPPDATA%\\Devin\\zh-webapp.json.
"""
import argparse
import base64
import hashlib
import io
import json
import os
import shutil
import sys

# Relative to <app>/resources/app/out/
SESSIONS_KEY = "vs/sessions/sessions.desktop.main.js"
WORKBENCH_KEY = "vs/workbench/workbench.desktop.main.js"
PRODUCT = os.path.join("resources", "app", "product.json")
OUT_PREFIX = os.path.join("resources", "app", "out")
ORIG_SUFFIX = ".zh-orig"
STATE = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                     "Devin", "zh-webapp.json")

# The probe file used to decide whether a directory is a Devin install.
PROBE = os.path.join(OUT_PREFIX, SESSIONS_KEY)

CANDIDATES = [
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Devin"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Devin Desktop"),
    os.path.join(os.environ.get("PROGRAMFILES", ""), "Devin"),
    os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Devin"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Devin"),
]


def build_targets(port):
    """(checksum key, [edits]) per bundle.  Each edit is (pattern, replacement, expect).

    The PR-review webview (`oSe(this.devinService.webUrl, ...)`, no underscore)
    is deliberately NOT patched: it authenticates with per-origin request headers
    pinned to the app origin, so moving its base would break its auth.
    """
    return [
        {
            "key": SESSIONS_KEY,
            "edits": [
                (b"V6r(But(this._authService,this._devinService),",
                 'V6r("http://127.0.0.1:%d",' % port, 2),
            ],
        },
        {
            "key": WORKBENCH_KEY,
            "edits": [
                (b"oSe(QC(this._authService,this._devinService),",
                 'oSe("http://127.0.0.1:%d",' % port, 2),
                (b"oSe(this._devinService.webUrl,",
                 'oSe("http://127.0.0.1:%d",' % port, 1),
            ],
        },
    ]


def _registry_candidates():
    """Devin may live anywhere (it is a portable Electron install).

    The app registers a `devin://` URL handler and a per-user "App Paths" entry,
    both of which carry the install directory.  Read them instead of guessing.
    """
    out = []
    try:
        import winreg  # noqa: WPS433 - windows only, guarded
    except ImportError:
        return out
    def read(root, path, name=""):
        try:
            with winreg.OpenKey(root, path) as k:
                return winreg.QueryValueEx(k, name)[0]
        except OSError:
            return None
    def add(cmd):
        if not cmd:
            return
        cmd = cmd.strip().strip('"')
        for exe in (".exe", ".cmd", ".bat"):
            i = cmd.lower().find(exe)
            if i != -1:
                out.append(cmd[:i + len(exe)])
                return
    for root, sub in (
        (winreg.HKEY_CLASSES_ROOT, r"devin\shell\open\command"),
        (winreg.HKEY_CLASSES_ROOT, r"Devin\shell\open\command"),
    ):
        add(read(root, sub))
    for sub in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Devin.exe",
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\devin.exe"):
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            add(read(root, sub))
    return [os.path.dirname(p) for p in out if p]


def b64_sha256(data):
    """base64(SHA-256) without padding - matches product.json's checksum style."""
    return base64.b64encode(hashlib.sha256(data).digest()).decode("ascii").rstrip("=")


def read_checksum(product_path, key):
    """Return (value, error). Reads the raw bytes so nothing else in the file moves."""
    try:
        with open(product_path, "rb") as fh:
            raw = fh.read()
    except OSError as e:
        return None, "unreadable: %s" % e
    marker = ('"%s"' % key).encode("ascii")
    i = raw.find(marker)
    if i < 0:
        return None, "checksum key not found"
    q1 = raw.find(b'"', i + len(marker))
    if q1 < 0:
        return None, "malformed checksum entry"
    q2 = raw.find(b'"', q1 + 1)
    if q2 < 0:
        return None, "malformed checksum entry"
    return raw[q1 + 1:q2].decode("ascii"), None


def patch_product_checksum(product_path, key, new_digest, dry_run):
    """Byte-level swap of one checksum value.

    product.json is NOT file-backed-up.  A backup would have to be refreshed on
    every install (a Devin update changes the byte image), but refreshing it
    after the first edit would capture an already-half-patched file - and a
    restore would then hand back a table whose values disagree with the restored
    bundles.  uninstall.py instead recomputes the digests from the restored
    bundles, which is exact and needs no copy of the file at all.
    """
    with open(product_path, "rb") as fh:
        raw = fh.read()
    marker = ('"%s"' % key).encode("ascii")
    i = raw.find(marker)
    if i < 0:
        return None, "checksum key not found"
    q1 = raw.find(b'"', i + len(marker))
    if q1 < 0:
        return None, "malformed checksum entry"
    q2 = raw.find(b'"', q1 + 1)
    if q2 < 0:
        return None, "malformed checksum entry"
    old = raw[q1 + 1:q2].decode("ascii")
    if old == new_digest:
        return old, "already current"
    if dry_run:
        return old, "would update"
    out = raw[:q1 + 1] + new_digest.encode("ascii") + raw[q2:]
    with open(product_path, "wb") as fh:
        fh.write(out)
    now, err = read_checksum(product_path, key)
    if err or now != new_digest:
        with open(product_path, "wb") as fh:   # roll back from memory
            fh.write(raw)
        return old, "verify failed, restored"
    return old, "updated"


def load_state():
    try:
        with io.open(STATE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with io.open(STATE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)


def find_app(verbose=False):
    """Return the Devin install directory, or None."""
    tried = []
    for env in ("DEVIN_APP", "DEVIN_HOME"):
        v = os.environ.get(env)
        if v:
            tried.append(("env:" + env, v))
            if os.path.isfile(os.path.join(v, PROBE)):
                return os.path.abspath(v)
    st = load_state()
    if st.get("app"):
        tried.append(("state", st["app"]))
        if os.path.isfile(os.path.join(st["app"], PROBE)):
            return st["app"]
    for cand in CANDIDATES:
        if cand:
            tried.append(("candidate", cand))
            if os.path.isfile(os.path.join(cand, PROBE)):
                return os.path.abspath(cand)
    for cand in _registry_candidates():
        tried.append(("registry", cand))
        if os.path.isfile(os.path.join(cand, PROBE)):
            return os.path.abspath(cand)
    if verbose:
        for src, p in tried:
            print("  tried  %-10s %s" % (src, p))
    return None


def resolve_app(arg):
    if arg:
        return os.path.abspath(arg)
    return find_app(verbose=True)


def bundle_path(app, key):
    return os.path.join(app, OUT_PREFIX, *key.split("/"))


def apply_edits(data, edits):
    """Return (new_data, rows) where rows is [(pattern, hits, expect)]."""
    out = data
    rows = []
    for pattern, replacement, expect in edits:
        rep = replacement.encode("ascii")
        hits = out.count(pattern)
        if hits:
            out = out.replace(pattern, rep)
        rows.append((pattern, hits, expect))
    return out, rows


def expectations(edits):
    """De-duplicated {replacement_bytes: expected total}.

    Several edits can share one replacement string (both workbench hosts are
    rewritten to the same literal), so counting per edit double-counts.  Counting
    per distinct replacement is the honest number.
    """
    exp = {}
    for _pattern, replacement, expect in edits:
        rep = replacement.encode("ascii")
        exp[rep] = exp.get(rep, 0) + expect
    return exp


def count_applied(data, edits):
    return sum(data.count(rep) for rep in expectations(edits))


def report_status(app, port):
    targets = build_targets(port)
    product = os.path.join(app, PRODUCT)
    print("app          : %s" % app)
    ok_all = True
    for t in targets:
        path = bundle_path(app, t["key"])
        expect_total = sum(expectations(t["edits"]).values())
        print("--- %s" % t["key"])
        if not os.path.isfile(path):
            print("    missing   : file not found")
            ok_all = False
            continue
        with open(path, "rb") as fh:
            data = fh.read()
        remaining = sum(data.count(e[0]) for e in t["edits"])
        applied = count_applied(data, t["edits"])
        # Several edits share one replacement string, so both `applied` and
        # `expect_total` count distinct replacements, not edits.
        print("    bytes     : %d" % len(data))
        print("    original  : %d left" % remaining)
        print("    patched   : %d / %d" % (applied, expect_total))
        print("    backup    : %s" % ("present" if os.path.exists(path + ORIG_SUFFIX) else "absent"))
        if os.path.isfile(product):
            val, err = read_checksum(product, t["key"])
            if err:
                print("    checksum  : %s" % err)
                ok_all = False
            else:
                match = val == b64_sha256(data)
                print("    checksum  : %s  match=%s" % (val[:16] + "...", match))
                if not match:
                    ok_all = False
        else:
            print("    checksum  : product.json missing")
            ok_all = False
    print("state file   : %s" % ("present" if os.path.exists(STATE) else "absent"))
    print("verdict      : %s" % ("INSTALLED" if ok_all else "NOT INSTALLED / INCOMPLETE"))
    return 0 if ok_all else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", help="Devin install directory (contains resources/app)")
    ap.add_argument("--port", type=int, default=5175)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--status", action="store_true", help="report state and exit")
    args = ap.parse_args()

    app = resolve_app(args.app)
    if not app:
        print("ERROR: cannot locate the Devin install directory. Pass --app <dir>.")
        return 2

    if args.status:
        return report_status(app, args.port)

    targets = build_targets(args.port)
    product = os.path.join(app, PRODUCT)
    print("app          : %s" % app)

    any_hits = 0
    results = []

    for t in targets:
        path = bundle_path(app, t["key"])
        expect_total = sum(expectations(t["edits"]).values())
        print("--- %s" % t["key"])
        if not os.path.isfile(path):
            print("ERROR: bundle not found: %s" % path)
            return 2
        with open(path, "rb") as fh:
            data = fh.read()
        size_before = len(data)
        patched, rows = apply_edits(data, t["edits"])
        hits = sum(r[1] for r in rows)
        for pattern, n, expect in rows:
            flag = "" if n == expect else "   <-- expected %d" % expect
            print("    %-52s %d%s" % (pattern.decode("ascii"), n, flag))
        any_hits += hits
        results.append((t, path, data, patched, rows, hits, size_before, expect_total))

    if not any_hits:
        print("OK: already installed (no change).")
        if not args.dry_run and os.path.isfile(product):
            for t in targets:
                path = bundle_path(app, t["key"])
                with open(path, "rb") as fh:
                    cur = fh.read()
                old, note = patch_product_checksum(product, t["key"], b64_sha256(cur), False)
                print("    checksum %-44s %s" % (t["key"], note))
        state = load_state()
        state.update({"app": app, "port": args.port, "installed": True})
        save_state(state)
        return 0

    if args.dry_run:
        for t, path, data, patched, rows, hits, size_before, expect_total in results:
            if hits:
                print("    dry-run: would write %s (%+d bytes)" % (t["key"], len(patched) - size_before))
        print("dry-run: no write performed.")
        return 0

    installed = []
    orig_digests = dict(load_state().get("original_checksums") or {})
    for t, path, data, patched, rows, hits, size_before, expect_total in results:
        # Snapshot the shipped digest before touching anything, so uninstall can
        # prove it restored the right table.
        if os.path.isfile(product) and t["key"] not in orig_digests:
            val, err = read_checksum(product, t["key"])
            if not err and val:
                orig_digests[t["key"]] = val

        if not hits:
            # Keep the checksum honest even for a file we did not touch.
            with open(path, "rb") as fh:
                cur = fh.read()
            if os.path.isfile(product):
                patch_product_checksum(product, t["key"], b64_sha256(cur), False)
            installed.append(t["key"])
            continue

        backup = path + ORIG_SUFFIX
        # Always refresh: after a Devin update the byte image changes, and a
        # stale backup would restore the wrong build on uninstall.
        shutil.copy2(path, backup)

        with open(path, "wb") as fh:
            fh.write(patched)

        with open(path, "rb") as fh:
            check = fh.read()
        still_original = sum(check.count(e[0]) for e in t["edits"])
        now_applied = count_applied(check, t["edits"])
        ok = still_original == 0 and now_applied >= expect_total
        print("    write %-44s verify=%s (%d applied, delta %+d)"
              % (t["key"], "PASS" if ok else "FAIL", now_applied, len(check) - size_before))
        if not ok:
            print("    restoring from backup")
            shutil.copy2(backup, path)
            return 4

        if os.path.isfile(product):
            old, note = patch_product_checksum(product, t["key"], b64_sha256(check), False)
            print("    checksum %-42s %s" % (t["key"], note))
        installed.append(t["key"])

    state = load_state()
    state.update({"app": app, "port": args.port, "installed": True,
                  "files": [bundle_path(app, k) for k in installed],
                  "original_checksums": orig_digests})
    save_state(state)
    print("state        : %s" % STATE)
    print("\nNext: start the proxy, then launch Devin.")
    print("  node webapp/proxy.mjs --port %d" % args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
