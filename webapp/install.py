#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Install the Devin zh-hans overlay.

Two independent layers are patched here.

Layer 1 - the remote web app's iframe base URL
    Devin Desktop can render its Sessions / Settings UI in a frame that loads the
    remote web app (https://app.devin.ai).  The injector lives in TWO bundles, and
    each carries its own copy of the URL builder plus its own copy of the
    install-host resolver:

        out/vs/sessions/sessions.desktop.main.js
            V6r(But(this._authService,this._devinService), ...)     x2
            V6r = URL builder      But = webappHost/webUrl resolver

        out/vs/workbench/workbench.desktop.main.js
            oSe(QC(this._authService,this._devinService), ...)      x2   (desktop nav)
            oSe(this._devinService.webUrl, ...)                     x1   (Devin Sidebar)
            oSe = URL builder      QC  = webappHost/webUrl resolver

    Both are rewritten so the frame loads from the local proxy instead of the
    remote origin.

Layer 2 - the shipped chat client's own English catalogue
    The built chat client embeds its i18next resources outright:

        Ua.init({ resources: { en: { translation: jr } }, lng: "en", fallbackLng: "en" })

    `jr` is a plain {"camelCaseKey":"English"} map (the same catalogue is inlined
    into the sessions window bundle), so translating it is a byte-level pair swap
    - no resident proxy, no network, no runtime.  Keys are unique identifiers,
    which keeps the substitution unambiguous.

Edits are byte-level throughout: files are never decoded, so no encoding can be
damaged.

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

HERE = os.path.dirname(os.path.abspath(__file__))

# Relative to <app>/resources/app/out/
SESSIONS_KEY = "vs/sessions/sessions.desktop.main.js"
WORKBENCH_KEY = "vs/workbench/workbench.desktop.main.js"
CHATUI_KEY = "vs/workbench/windsurf-chat-client/index.js"
PRODUCT = os.path.join("resources", "app", "product.json")
OUT_PREFIX = os.path.join("resources", "app", "out")
ORIG_SUFFIX = ".zh-orig"
STATE = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                     "Devin", "zh-webapp.json")

# Translation source for layer 2 (built from webapp/dict-zh.json).
CHATUI_DICT = os.path.join(HERE, "zh-hans.json")

# English this install ships for the few keys whose catalogue text differs from
# the remote one.  Kept explicit rather than sniffed from the bundle so the edit
# set stays a pure function of the dictionary and --status stays meaningful.
CHATUI_EN_ALIASES = {
    "codeSessions": ["Code sessions"],
    "coding": ["Coding"],
    "allowModelProviderDataRetentionDisabledDescription": [
        "Disabling this setting disables all routing to Fable-family models, "
        "and also disables Devin Ultra mode.",
    ],
}


# The probe file used to decide whether a directory is a Devin install.
PROBE = os.path.join(OUT_PREFIX, SESSIONS_KEY)

CANDIDATES = [
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Devin"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Devin Desktop"),
    os.path.join(os.environ.get("PROGRAMFILES", ""), "Devin"),
    os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Devin"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Devin"),
]


def _pair(key, text):
    """`<key>:<value>` exactly as the bundle stores it, ASCII-only.

    Non-ASCII is emitted as \\uXXXX escapes to match the catalogue's own
    convention (its Japanese copy is escaped the same way).  That keeps the
    edited bundle pure ASCII, so no charset assumption can corrupt the strings
    when the file is loaded over the custom file protocol.
    """
    return (json.dumps(key, ensure_ascii=True) + ":"
            + json.dumps(text, ensure_ascii=True))


_chatui_cache = []


def chatui_edits():
    """[(pattern_bytes, replacement_str, None)] - one pair swap per dictionary key.

    `expect` is None: this set spans a whole catalogue, so what matters is that
    no English original is left behind, not how many swaps were made.
    """
    if _chatui_cache:
        return _chatui_cache
    try:
        with io.open(CHATUI_DICT, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError) as e:
        print("WARN: cannot read %s (%s); chat UI strings will stay English."
              % (CHATUI_DICT, e))
        return _chatui_cache
    seen = set()
    for key, val in sorted(raw.items()):
        if key.startswith("_") or not isinstance(val, dict):
            continue
        zh = val.get("zh")
        if not zh:
            continue
        # A key whose Chinese equals its English (brand names, "Devin Desktop",
        # "Wiki") is already correct and produces no edit at all.
        rep = _pair(key, zh)
        rep_b = rep.encode("ascii")
        for en in [val.get("en")] + CHATUI_EN_ALIASES.get(key, []):
            if not en or en == zh:
                continue
            # The catalogue sits inside single-quoted JS strings, so an
            # apostrophe is stored escaped; try both spellings.  De-duplicate by
            # pattern, not by key: one key may legitimately need several
            # spellings (dictionary text + local alias).
            for text in (en, en.replace("'", "\\'")):
                pat = _pair(key, text).encode("ascii")
                if pat == rep_b or pat in seen:
                    continue
                seen.add(pat)
                _chatui_cache.append((pat, rep, None))
    return _chatui_cache


def build_targets(port):
    """[{key, edits}] - one entry per bundle, edits merged across every concern.

    Each edit is (pattern, replacement, expect); `expect` may be None, meaning
    "no fixed occurrence count".

    The PR-review webview (`oSe(this.devinService.webUrl, ...)`, no underscore)
    is deliberately NOT patched: it authenticates with per-origin request headers
    pinned to the app origin, so moving its base would break its auth.

    out/vs/workbench/workbench.desktop.main.js is not touched by layer 2 - it
    carries none of the catalogue.
    """
    groups = {}

    def add(key, edits):
        groups.setdefault(key, []).extend(edits)

    # Layer 1 - point the web-app frame at the local proxy.
    add(SESSIONS_KEY, [
        (b"V6r(But(this._authService,this._devinService),",
         'V6r("http://127.0.0.1:%d",' % port, 2),
    ])
    add(WORKBENCH_KEY, [
        (b"oSe(QC(this._authService,this._devinService),",
         'oSe("http://127.0.0.1:%d",' % port, 2),
        (b"oSe(this._devinService.webUrl,",
         'oSe("http://127.0.0.1:%d",' % port, 1),
    ])

    # Layer 2 - translate the shipped catalogue itself.  Present in both the chat
    # client bundle and the sessions window bundle.
    for key in (CHATUI_KEY, SESSIONS_KEY):
        add(key, chatui_edits())

    return [{"key": k, "edits": v} for k, v in groups.items()]


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


def digest_file(path):
    with open(path, "rb") as fh:
        return b64_sha256(fh.read())


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


def record_original(orig_digests, path, key):
    """Pin original_checksums[key] to the digest of the factory backup.

    The factory digest is *defined* as the digest of the factory image, and the
    backup is that image.  Reading it out of product.json instead only works on
    a first-ever install: on any later run product.json already carries a
    patched digest, so storing that would make the field mean "whatever the file
    happened to hash to", which tells uninstall nothing.  The backup is the
    authority, and a stale value is repaired here.
    """
    backup = path + ORIG_SUFFIX
    if not os.path.exists(backup):
        return False
    want = digest_file(backup)
    if orig_digests.get(key) != want:
        orig_digests[key] = want
        return True
    return False


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
    """De-duplicated {replacement_bytes: expected total} for edits that carry a count.

    Several edits can share one replacement string (both workbench hosts are
    rewritten to the same literal), so counting per edit double-counts.  Counting
    per distinct replacement is the honest number.  Edits with expect=None (the
    catalogue pairs) are excluded: their count is not knowable up front.
    """
    exp = {}
    for _pattern, replacement, expect in edits:
        if expect is None:
            continue
        rep = replacement.encode("ascii")
        exp[rep] = exp.get(rep, 0) + expect
    return exp


def all_replacements(edits):
    """Every distinct replacement, including the ones with no fixed count."""
    return {e[1].encode("ascii") for e in edits}


def count_fixed(data, edits):
    """Occurrences of the fixed-count replacements (unit: occurrences)."""
    return sum(data.count(rep) for rep in expectations(edits))


def count_swaps(rows):
    """Occurrences actually swapped, across every edit (unit: occurrences)."""
    return sum(n for _pattern, n, _expect in rows)


def catalogue_stats(data, edits):
    """(keys_landed, keys_total, occurrences) for the expect=None half.

    Counted per *distinct replacement* - i.e. per dictionary key - not per
    pattern.  A key can need several patterns, because the shipped catalogue
    spells its English differently in different places, and inferring "pattern
    landed" from "replacement present" credits every spelling of a key as soon
    as any one of them lands (that inflated this line to 35 when only 32 keys
    had actually gone in).  Occurrences are reported separately, because the
    catalogue is inlined into the bundle several times: `"review":"..."` alone
    lands 29 times in the live install.

    Must be handed the *patched* bytes: a key has landed iff its Chinese
    replacement is now present.
    """
    reps = {rep.encode("ascii") for _p, rep, _e in edits if _e is None}
    hit = sum(1 for rep in reps if data.count(rep))
    occ = sum(data.count(rep) for rep in reps)
    return hit, len(reps), occ


def catalogue_rows(rows, edits):
    """catalogue_stats' three numbers from apply_edits' per-pattern hit counts.

    Preferred while a patch is being written, so the figure is measured rather
    than inferred from the bytes.  De-duplicated by replacement, matching
    catalogue_stats() - see there for why the unit is the key, not the pattern.
    """
    hit_of = {pat: n for pat, n, _e in rows}
    reps = {}
    for pat, rep, expect in edits:
        if expect is None:
            reps[rep] = reps.get(rep, 0) + hit_of.get(pat, 0)
    hit = sum(1 for n in reps.values() if n)
    return hit, len(reps), sum(reps.values())


def report_status(app, port):
    targets = build_targets(port)
    product = os.path.join(app, PRODUCT)
    print("app          : %s" % app)
    ok_all = True
    for t in targets:
        path = bundle_path(app, t["key"])
        expect_total = sum(expectations(t["edits"]).values())
        n_derived = sum(1 for e in t["edits"] if e[2] is None)
        print("--- %s" % t["key"])
        if not os.path.isfile(path):
            print("    missing   : file not found")
            ok_all = False
            continue
        with open(path, "rb") as fh:
            data = fh.read()
        remaining = sum(data.count(e[0]) for e in t["edits"])
        print("    bytes     : %d" % len(data))
        print("    original  : %d left" % remaining)
        if n_derived:
            hit, total, occ = catalogue_stats(data, t["edits"])
            print("    catalogue : %d / %d keys landed, %d occurrences"
                  % (hit, total, occ))
            if hit < total:
                print("                (%d dictionary key(s) absent from this bundle)"
                      % (total - hit))
        if expect_total:
            print("    fixed     : %d / %d occurrences"
                  % (count_fixed(data, t["edits"]), expect_total))
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
        if remaining:
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
        hits = count_swaps(rows)
        for pattern, n, expect in rows:
            if expect is None:
                continue
            flag = "" if n == expect else "   <-- expected %d" % expect
            print("    %-52s %d%s" % (pattern.decode("ascii"), n, flag))
        pairs_hit, pairs_total, pairs_occ = catalogue_rows(rows, t["edits"])
        if pairs_total:
            print("    %-52s %d / %d keys landed, %d occurrences"
                  % ("catalogue", pairs_hit, pairs_total, pairs_occ))
        any_hits += hits
        results.append((t, path, data, patched, rows, hits, size_before, expect_total))

    if not any_hits:
        print("OK: already installed (no change).")
        orig_digests = dict(load_state().get("original_checksums") or {})
        for t in targets:
            path = bundle_path(app, t["key"])
            with open(path, "rb") as fh:
                cur = fh.read()
            if not args.dry_run and os.path.isfile(product):
                old, note = patch_product_checksum(product, t["key"], b64_sha256(cur), False)
                print("    checksum %-44s %s" % (t["key"], note))
            if record_original(orig_digests, path, t["key"]):
                print("    original: recorded factory digest %s"
                      % orig_digests[t["key"]][:16])
        state = load_state()
        state.update({"app": app, "port": args.port, "installed": True,
                      "original_checksums": orig_digests})
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
        if not hits:
            # Keep the checksum honest even for a file we did not touch.
            with open(path, "rb") as fh:
                cur = fh.read()
            if os.path.isfile(product):
                patch_product_checksum(product, t["key"], b64_sha256(cur), False)
            if record_original(orig_digests, path, t["key"]):
                print("    original: recorded factory digest %s"
                      % orig_digests[t["key"]][:16])
            installed.append(t["key"])
            continue

        backup = path + ORIG_SUFFIX
        # Refresh the backup only when this file is still pristine upstream.
        # Unconditionally copying would capture an already-patched file as
        # "original" whenever a *new* edit set is applied to a file an earlier
        # run already touched (exactly what happens to the sessions bundle when
        # layer 1 is live and layer 2 arrives), and uninstall would then restore
        # the patched bytes as if they were factory.
        already_touched = any(data.count(rep) for rep in all_replacements(t["edits"]))
        if not already_touched or not os.path.exists(backup):
            shutil.copy2(path, backup)
        else:
            print("    backup  : kept existing .zh-orig (file already patched)")

        # The factory digest comes from the backup, not from product.json - see
        # record_original() for why reading product.json here is wrong.
        if record_original(orig_digests, path, t["key"]):
            print("    original: recorded factory digest %s"
                  % orig_digests[t["key"]][:16])

        with open(path, "wb") as fh:
            fh.write(patched)

        with open(path, "rb") as fh:
            check = fh.read()
        still_original = sum(check.count(e[0]) for e in t["edits"])
        fixed_now = count_fixed(check, t["edits"])
        ok = still_original == 0 and fixed_now >= expect_total
        print("    write %-44s verify=%s (%d occurrences, delta %+d)"
              % (t["key"], "PASS" if ok else "FAIL", hits, len(check) - size_before))
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
