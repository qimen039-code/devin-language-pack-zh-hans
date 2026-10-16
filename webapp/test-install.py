#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline self-test for install.py / uninstall.py.

Needs no Devin install and no network: it builds a synthetic app tree, patches
it, and checks the invariants that a real install relies on.

    python webapp/test-install.py

What it covers, and why each case is here rather than being left implicit:

  * a key repeated in two catalogue copies      -> the swap must land both times
  * a key needing two English spellings
    (dictionary text + alias)                   -> both spellings must be swapped
  * a key whose Chinese equals its English      -> must produce NO edit at all
  * a key with a {{product}} placeholder        -> placeholder must survive
  * `localSettings`                             -> translatable when the string
                                                   pair is actually present; it is
                                                   the *real* bundle that lacks it
  * the PR-review decoy `oSe(this.devinService.webUrl,`
    (no underscore, next to the one we do patch) -> must NOT be rewritten
  * the byte delta                              -> must equal the sum of the
                                                   per-swap deltas, which catches
                                                   any stray edit outside a pattern
  * install -> uninstall -> install             -> must be byte-exact and
                                                   reproducible

The state file is redirected to a scratch LOCALAPPDATA so the test never
touches a real install's recorded digests.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import install  # noqa: E402

PORT = 5175
PROXY = "http://127.0.0.1:%d" % PORT

# Keys this fixture writes into the synthetic catalogue.  Each one is a case.
FIXTURE_KEYS = [
    "review",                          # repeated in two catalogue copies
    "sessions",                        # duplicate English with other keys
    "coding",                          # needs the alias spelling too
    "wiki",                            # en == zh -> no edit may be produced
    "desktopApp",                      # en == zh (brand name), same rule
    "localSettings",                   # absent from the real bundle, present here
    "desktopIndividualDescription",    # {{product}} placeholder
    "modelProviderApiKeys",
    "navigateBack",
    "groupSettings",
    "automations",
]

failures = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        failures.append(msg)


def pair(key, en):
    return install._pair(key, en)


def catalogue_snippet():
    """Two 'catalogue copies', the second repeating review/sessions."""
    d = json.load(io.open(install.CHATUI_DICT, encoding="utf-8"))
    parts = []
    for k in FIXTURE_KEYS:
        if k not in d:
            raise SystemExit("fixture key %r vanished from %s" % (k, install.CHATUI_DICT))
        parts.append(pair(k, d[k]["en"]))
    copy_one = "var jr={" + ",".join(parts) + "};"
    # The alias spelling for `coding` (the shipped bundle spells it both ways).
    alias = 'var alias={"coding":"Coding"};'
    copy_two = "var jr2={%s,%s};" % (pair("review", d["review"]["en"]),
                                     pair("sessions", d["sessions"]["en"]))
    return "\n".join([copy_one, alias, copy_two]) + "\n"


def layer1_sessions():
    return (
        "function a(){return V6r(But(this._authService,this._devinService),{p:1})}\n"
        "function b(){return V6r(But(this._authService,this._devinService),"
        "{p:2})}\n"
    )


def layer1_workbench():
    # The last line is the PR-review decoy: same name, NO underscore.
    return (
        "function a(){return oSe(QC(this._authService,this._devinService),{p:1})}\n"
        "function b(){return oSe(QC(this._authService,this._devinService),"
        "{p:2})}\n"
        "function c(){return oSe(this._devinService.webUrl,{p:3})}\n"
        "function d(){return oSe(this.devinService.webUrl,{p:4})}\n"
    )


def build_fixture(root):
    app = os.path.join(root, "app")
    bodies = {
        install.SESSIONS_KEY: layer1_sessions() + catalogue_snippet(),
        install.WORKBENCH_KEY: layer1_workbench(),
        install.CHATUI_KEY: catalogue_snippet(),
    }
    for key, body in bodies.items():
        p = install.bundle_path(app, key)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with io.open(p, "w", encoding="ascii", newline="") as fh:
            fh.write(body)
    prod = os.path.join(app, install.PRODUCT)
    checks = {}
    for key in bodies:
        digest = install.digest_file(install.bundle_path(app, key))
        checks[key] = digest
    with io.open(prod, "w", encoding="ascii") as fh:
        fh.write(json.dumps({"checksums": checks}, indent=2))
    return app


def digests(app, keys):
    return {k: install.digest_file(install.bundle_path(app, k)) for k in keys}


def run(app, env, script, *extra):
    return subprocess.run(
        [sys.executable, os.path.join(HERE, script), "--app", app] + list(extra),
        env=env, capture_output=True, text=True)


def main():
    tmp = tempfile.mkdtemp(prefix="devin-l10n-test-")
    try:
        app = build_fixture(tmp)
        env = dict(os.environ, LOCALAPPDATA=os.path.join(tmp, "user"))
        keys = [install.SESSIONS_KEY, install.WORKBENCH_KEY, install.CHATUI_KEY]

        with io.open(install.bundle_path(app, install.SESSIONS_KEY), "rb") as fh:
            factory = fh.read()
        before = digests(app, keys)
        print("fixture      : %s" % app)

        # --- install ------------------------------------------------------
        print("\n--- install")
        p = run(app, env, "install.py")
        print(p.stdout.rstrip())
        check(p.returncode == 0, "install exit 0 (got %d)" % p.returncode)

        after = digests(app, keys)
        for k in keys:
            check(after[k] != before[k], "%s was patched" % k)

        targets = {t["key"]: t for t in install.build_targets(PORT)}

        # 1. no English original of any pattern survives
        for k in keys:
            with io.open(install.bundle_path(app, k), "rb") as fh:
                data = fh.read()
            left = sum(data.count(pat) for pat, _r, _e in targets[k]["edits"])
            check(left == 0, "%s: English originals left = %d" % (k, left))

        # 2. a key repeated in two copies was swapped in both
        with io.open(install.bundle_path(app, install.CHATUI_KEY), "rb") as fh:
            blob = fh.read().decode("utf-8")
        rep = install._pair("review", "审查")
        check(blob.count(rep) == 2,
              "repeated key swapped in both copies (found %d, want 2)"
              % blob.count(rep))
        check(blob.count(install._pair("sessions", "会话")) == 2,
              "second repeated key swapped twice")

        # 3. both spellings of a two-spelling key were swapped
        for en in ("Sessions", "Coding"):
            check(install._pair("coding", en) not in blob,
                  "alias spelling %r of `coding` was swapped too" % en)
        check(blob.count(install._pair("coding", "会话")) == 2,
              "`coding` landed twice (one per spelling)")

        # 4. en == zh keys produce no edit
        check('"wiki":"Wiki"' in blob, "`wiki` (en == zh) left untouched")
        check('"desktopApp":"Devin Desktop"' in blob,
              "brand-name key `desktopApp` left untouched (en == zh)")

        # 5. placeholder survives translation
        want = install._pair("desktopIndividualDescription",
                             "管理你的 {{product}} API 密钥与隐私设置。")
        check(want in blob, "{{product}} placeholder preserved")
        check("{{product}}" in want, "sanity: fixture actually exercised a placeholder")

        # 6. localSettings is translatable when the pair is present
        check(install._pair("localSettings", "本地设置") in blob,
              "localSettings swapped (the real bundle simply lacks this pair)")

        # 7. the PR-review decoy must be untouched
        with io.open(install.bundle_path(app, install.WORKBENCH_KEY), "rb") as fh:
            wb = fh.read().decode("utf-8")
        check(wb.count("oSe(this.devinService.webUrl,") == 1,
              "PR-review decoy `oSe(this.devinService.webUrl,` left alone")
        check(wb.count('oSe("%s",' % PROXY) == 3,
              "workbench: 3 call sites rewritten to the proxy base")

        # 8. byte delta == sum of per-swap deltas
        for k in keys:
            with io.open(install.bundle_path(app, k), "rb") as fh:
                live = fh.read()
            back_path = install.bundle_path(app, k) + install.ORIG_SUFFIX
            with io.open(back_path, "rb") as fh:
                back = fh.read()
            expect = sum(back.count(pat) * (len(r.encode("ascii")) - len(pat))
                         for pat, r, _e in targets[k]["edits"])
            check(len(live) - len(back) == expect,
                  "%s: byte delta %+d == expected %+d"
                  % (k, len(live) - len(back), expect))

        # 9. ASCII purity preserved (fixture is ASCII by construction)
        for k in keys:
            with io.open(install.bundle_path(app, k), "rb") as fh:
                data = fh.read()
            try:
                data.decode("ascii")
                ok = True
            except UnicodeDecodeError:
                ok = False
            check(ok, "%s stays pure ASCII" % k)

        # 10. product.json checksums track the patched bytes
        prod = os.path.join(app, install.PRODUCT)
        for k in keys:
            val, err = install.read_checksum(prod, k)
            check(not err and val == after[k], "product.json checksum correct for %s" % k)

        # 11. status
        print("\n--- status")
        p = run(app, env, "install.py", "--status")
        print(p.stdout.rstrip())
        check("INSTALLED" in p.stdout, "status verdict INSTALLED")
        check("NOT INSTALLED" not in p.stdout, "status does not contradict itself")

        # 12. uninstall restores the factory bytes exactly
        print("\n--- uninstall")
        p = run(app, env, "uninstall.py", "--keep-backup")
        print(p.stdout.rstrip())
        check(p.returncode == 0, "uninstall exit 0 (got %d)" % p.returncode)
        restored = digests(app, keys)
        for k in keys:
            check(restored[k] == before[k], "%s byte-identical to factory" % k)
        p = run(app, env, "install.py", "--status")
        check("NOT INSTALLED" in p.stdout, "status verdict not-installed after uninstall")

        # 13. re-install is reproducible
        print("\n--- install #2")
        p = run(app, env, "install.py")
        check(p.returncode == 0, "install #2 exit 0")
        again = digests(app, keys)
        for k in keys:
            check(again[k] == after[k], "%s reproducible (install #2 == #1)" % k)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        print("RESULT: %d FAILURE(S)" % len(failures))
        for f in failures:
            print("  - %s" % f)
        return 1
    print("RESULT: ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
