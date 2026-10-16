#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Uninstall the Devin webapp zh-hans overlay: restore the original bundle.

    python webapp/uninstall.py [--app "<devin-install-dir>"] [--keep-backup]

Restores resources/app/out/vs/sessions/sessions.desktop.main.js from the
.zh-orig backup and puts the original product.json back, so the checksum table
is byte-identical to the shipped one again.
"""
import argparse
import base64
import hashlib
import io
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from install import (  # noqa: E402  (path is fixed up above)
    BUNDLE, PRODUCT, ORIG_SUFFIX, STATE, PATTERN, find_app, load_state,
)

PATCHED_MARK = b'V6r("http://127.0.0.1:'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app")
    ap.add_argument("--keep-backup", action="store_true")
    args = ap.parse_args()

    app = os.path.abspath(args.app) if args.app else find_app(verbose=True)
    if not app:
        print("ERROR: cannot locate the Devin install directory. Pass --app <dir>.")
        return 2

    bundle = os.path.join(app, BUNDLE)
    backup = bundle + ORIG_SUFFIX

    if not os.path.exists(backup):
        if os.path.isfile(bundle):
            with open(bundle, "rb") as fh:
                raw = fh.read()
            if PATTERN in raw:
                print("OK: not installed (bundle is original, no backup present).")
                return 0
            if PATCHED_MARK in raw:
                print("ERROR: bundle is patched but the backup is missing.")
                print("       Reinstall Devin, or re-run install.py to refresh both.")
                return 3
        print("ERROR: bundle not found: %s" % bundle)
        return 3

    with open(backup, "rb") as fh:
        data = fh.read()
    with open(bundle, "wb") as fh:
        fh.write(data)
    print("restored : %s (%d bytes)" % (bundle, len(data)))

    with open(bundle, "rb") as fh:
        check = fh.read()
    ok = PATTERN in check and PATCHED_MARK not in check
    print("verify   : %s" % ("PASS (original restored)" if ok else "FAIL"))
    if not ok:
        print("         backup did not look like the pristine bundle; aborting.")
        return 4

    if not args.keep_backup:
        os.remove(backup)
        print("removed  : %s" % backup)

    product = os.path.join(app, PRODUCT)
    prod_backup = product + ORIG_SUFFIX
    digest = base64.b64encode(hashlib.sha256(data).digest()).decode("ascii").rstrip("=")
    if os.path.exists(prod_backup):
        shutil.copy2(prod_backup, product)
        print("restored : %s" % product)
    elif os.path.isfile(product):
        print("note     : no product.json backup; leaving it as-is")
    else:
        print("note     : product.json not found")

    if os.path.isfile(product):
        with open(product, "rb") as fh:
            pj = fh.read()
        print("checksum : %s" % ("matches restored bundle" if digest.encode("ascii") in pj
                                 else "MISMATCH - run install.py --status to inspect"))

    if not args.keep_backup and os.path.exists(prod_backup):
        os.remove(prod_backup)
        print("removed  : %s" % prod_backup)

    state = load_state()
    if state:
        state["installed"] = False
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with io.open(STATE, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)

    print("done. Devin will load https://app.devin.ai again on next start.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
