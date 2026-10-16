#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Install the Devin webapp zh-hans overlay.

Patches the Devin Desktop sessions bundle so its embedded web app iframe loads
from the local proxy instead of https://app.devin.ai. Byte-level edit: the
original file is never decoded, so no encoding can be damaged.

    python webapp/install.py --app "D:\\AI\\Devin" [--port 5175] [--dry-run]

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

BUNDLE = os.path.join("resources", "app", "out", "vs", "sessions", "sessions.desktop.main.js")
PRODUCT = os.path.join("resources", "app", "product.json")
ORIG_SUFFIX = ".zh-orig"
PATTERN = b"V6r(But(this._authService,this._devinService),"
CHECKSUM_KEY = b'"vs/sessions/sessions.desktop.main.js"'
STATE = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                     "Devin", "zh-webapp.json")
CANDIDATES = [
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Devin"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Devin Desktop"),
    os.path.join(os.environ.get("PROGRAMFILES", ""), "Devin"),
    os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Devin"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Devin"),
]


def _registry_candidates():
    """Devin may live anywhere (e.g. D:\\AI\\Devin).

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


def patch_product_checksum(product_path, new_digest, dry_run):
    """Byte-level swap of one checksum value so nothing else in the file moves."""
    with open(product_path, "rb") as fh:
        raw = fh.read()
    i = raw.find(CHECKSUM_KEY)
    if i < 0:
        return None, "checksum key not found"
    q1 = raw.find(b'"', i + len(CHECKSUM_KEY))
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
    backup = product_path + ORIG_SUFFIX
    # Always refresh, same reasoning as the bundle backup.
    shutil.copy2(product_path, backup)
    out = raw[:q1 + 1] + new_digest.encode("ascii") + raw[q2:]
    with open(product_path, "wb") as fh:
        fh.write(out)
    with open(product_path, "rb") as fh:
        check = fh.read()
    if new_digest.encode("ascii") not in check:
        shutil.copy2(backup, product_path)
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
            if os.path.isfile(os.path.join(v, BUNDLE)):
                return os.path.abspath(v)
    st = load_state()
    if st.get("app"):
        tried.append(("state", st["app"]))
        if os.path.isfile(os.path.join(st["app"], BUNDLE)):
            return st["app"]
    for cand in CANDIDATES:
        if cand:
            tried.append(("candidate", cand))
            if os.path.isfile(os.path.join(cand, BUNDLE)):
                return os.path.abspath(cand)
    for cand in _registry_candidates():
        tried.append(("registry", cand))
        if os.path.isfile(os.path.join(cand, BUNDLE)):
            return os.path.abspath(cand)
    if verbose:
        for src, p in tried:
            print("  tried  %-10s %s" % (src, p))
    return None


def resolve_app(arg):
    if arg:
        return os.path.abspath(arg)
    return find_app(verbose=True)


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
    bundle = os.path.join(app, BUNDLE)
    if not os.path.isfile(bundle):
        print("ERROR: bundle not found: %s" % bundle)
        return 2
    product = os.path.join(app, PRODUCT)

    replacement = ('V6r("http://127.0.0.1:%d",' % args.port).encode("ascii")

    with open(bundle, "rb") as fh:
        data = fh.read()
    size_before = len(data)

    already = data.count(replacement)
    hits = data.count(PATTERN)

    if args.status:
        checks = []
        try:
            with open(product, "rb") as fh:
                praw = fh.read()
            i = praw.find(CHECKSUM_KEY)
            q1 = praw.find(b'"', i + len(CHECKSUM_KEY))
            q2 = praw.find(b'"', q1 + 1)
            checks.append(("checksum_table", praw[q1 + 1:q2].decode("ascii")))
            checks.append(("checksum_matches", praw[q1 + 1:q2].decode("ascii") == b64_sha256(data)))
        except Exception as e:  # noqa: BLE001
            checks.append(("checksum_table", "unreadable: %s" % e))
        print("app          : %s" % app)
        print("bundle bytes : %d" % size_before)
        print("patched      : %s  (%d occurrence(s))" % (already > 0, already))
        print("original     : %s" % (hits > 0))
        print("backup       : %s" % ("present" if os.path.exists(bundle + ORIG_SUFFIX) else "absent"))
        for k, v in checks:
            print("%-13s: %s" % (k, v))
        print("state file   : %s" % ("present" if os.path.exists(STATE) else "absent"))
        return 0

    print("app          : %s" % app)
    print("bundle       : %s" % bundle)
    print("bundle bytes : %d" % size_before)
    print("pattern hits : %d" % hits)
    print("already done : %d" % already)

    if hits == 0 and already == 0:
        print("ERROR: target pattern not found - Devin build layout changed.")
        return 3
    if hits == 0 and already:
        print("OK: already installed (no change).")
        with open(bundle, "rb") as fh:
            cur = fh.read()
        if os.path.isfile(product):
            old, note = patch_product_checksum(product, b64_sha256(cur), False)
            print("checksum     : %s  (%s)" % (old[:12] + "...", note))
        state = load_state()
        state.update({"app": app, "port": args.port, "installed": True})
        save_state(state)
        return 0
    if hits != 2:
        print("WARNING: expected 2 occurrences, found %d." % hits)

    backup = bundle + ORIG_SUFFIX
    if args.dry_run:
        print("dry-run: would create backup %s" % backup)
    else:
        # Always refresh: after a Devin update the byte image changes, and a
        # stale backup would restore the wrong build on uninstall.
        shutil.copy2(bundle, backup)
        print("backup       : %s (refreshed)" % backup)

    patched = data.replace(PATTERN, replacement)
    print("replaced     : %d" % (hits + already))
    print("bytes delta  : %+d" % (len(patched) - size_before))

    if args.dry_run:
        print("dry-run: no write performed.")
        return 0

    with open(bundle, "wb") as fh:
        fh.write(patched)

    # verify
    with open(bundle, "rb") as fh:
        check = fh.read()
    ok = check.count(replacement) == 2 and check.count(PATTERN) == 0
    print("verify       : %s" % ("PASS" if ok else "FAIL"))
    if not ok:
        print("restoring from backup")
        shutil.copy2(backup, bundle)
        return 4

    # product.json carries a checksum table that covers this bundle; keep it
    # consistent so no integrity check reports a corrupt installation.
    digest = b64_sha256(check)
    if os.path.isfile(product):
        old, note = patch_product_checksum(product, digest, False)
        print("checksum     : %s -> %s  (%s)" % (old, digest, note))
    else:
        print("checksum     : product.json not found, skipped")

    state = load_state()
    state.update({"app": app, "port": args.port, "installed": True,
                  "backup": bundle + ORIG_SUFFIX})
    save_state(state)
    print("state        : %s" % STATE)
    print("\nNext: start the proxy, then launch Devin.")
    print("  node webapp/proxy.mjs --port %d" % args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
