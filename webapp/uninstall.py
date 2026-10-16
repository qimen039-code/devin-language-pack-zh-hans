#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Uninstall the Devin webapp zh-hans overlay: restore the original bundles.

    python webapp/uninstall.py [--app "<devin-install-dir>"] [--keep-backup]

Restores every patched bundle from its .zh-orig backup and rewrites the
product.json checksum table from the restored files, so the table is exact
again - no copy of product.json is kept, because a copy would have to be
refreshed on install and would capture an already-half-patched file.
"""
import argparse
import os
import shutil
import sys

from install import (  # noqa: WPS433 - sibling script, run from the repo
    ORIG_SUFFIX,
    PRODUCT,
    b64_sha256,
    build_targets,
    bundle_path,
    load_state,
    patch_product_checksum,
    read_checksum,
    resolve_app,
    save_state,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", help="Devin install directory (contains resources/app)")
    ap.add_argument("--port", type=int, default=5175)
    ap.add_argument("--keep-backup", action="store_true",
                    help="leave the .zh-orig backups in place")
    args = ap.parse_args()

    app = resolve_app(args.app)
    if not app:
        print("ERROR: cannot locate the Devin install directory. Pass --app <dir>.")
        return 2

    targets = build_targets(args.port)
    product = os.path.join(app, PRODUCT)
    state = load_state()
    orig_digests = dict(state.get("original_checksums") or {})

    print("app          : %s" % app)
    restored_any = False
    mismatches = []

    for t in targets:
        path = bundle_path(app, t["key"])
        expect_total = sum(e[2] for e in t["edits"])
        backup = path + ORIG_SUFFIX
        print("--- %s" % t["key"])

        if not os.path.isfile(path):
            print("    ERROR: bundle missing: %s" % path)
            return 2

        with open(path, "rb") as fh:
            data = fh.read()
        still_patched = sum(data.count(e[1].encode("ascii")) for e in t["edits"])
        original_present = sum(data.count(e[0]) for e in t["edits"])

        if original_present >= expect_total and still_patched == 0:
            print("    already original (%d pattern(s)) - nothing to restore" % original_present)
        elif not os.path.isfile(backup):
            print("    ERROR: patched but no backup at %s - refusing to guess." % backup)
            return 3
        else:
            shutil.copy2(backup, path)
            restored_any = True
            with open(path, "rb") as fh:
                data = fh.read()
            original_present = sum(data.count(e[0]) for e in t["edits"])
            print("    restored from backup (%d pattern(s) back)" % original_present)

        digest = b64_sha256(data)
        want = orig_digests.get(t["key"])
        if want and want != digest:
            mismatches.append((t["key"], want, digest))
        if os.path.isfile(product):
            old, note = patch_product_checksum(product, t["key"], digest, False)
            print("    checksum %-42s %s (%s)" % (t["key"], digest[:16] + "...", note))
            if want:
                print("    shipped  %-42s %s" % (t["key"], want[:16] + "..."))

        if not args.keep_backup and os.path.isfile(backup):
            os.remove(backup)
            print("    backup removed")

    # Legacy installs (before product.json stopped being file-backed-up) may
    # have left one behind.  It is stale by construction; drop it.
    legacy = product + ORIG_SUFFIX
    if os.path.isfile(legacy):
        os.remove(legacy)
        print("legacy backup: removed %s" % legacy)

    if mismatches:
        print("\nWARNING: restored bundles do not hash to the digests recorded at install time.")
        for key, want, got in mismatches:
            print("  %s\n    recorded %s\n    restored %s" % (key, want, got))
        print("  (expected if Devin was updated since the overlay was installed)")

    state.update({"app": app, "installed": False})
    state.pop("files", None)
    save_state(state)

    print("\nverdict      : %s" % ("RESTORED" if restored_any else "not installed"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
