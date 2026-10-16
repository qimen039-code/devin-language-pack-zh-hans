// Build an offline fixture for the proxy self-test.
//
// The fixture must reproduce BOTH serialisation forms the live bundles use, or
// the self-test would pass while production silently missed half the strings:
//
//   form 1 (large per-locale resource maps)
//     {"localSettings":"Local Settings"}
//   form 2 (minified per-component label maps, bare keys + template literals)
//     localSettings:`Local Settings`
//
// It also embeds a verbatim excerpt of a real bundle chunk, so the test can pin
// a ~1.2 KB window of genuine upstream bytes and prove nothing else was touched.
//
// Usage:
//   node webapp/make-fixture.mjs <fixtureDir> [--cache <rawCacheDir>] [--dict <dict.json>]
//
// <rawCacheDir> is the proxy's cache directory (upstream, verbatim).  If it is
// absent the verbatim excerpt is skipped and the test degrades to a pure
// mechanism check.
//
// Read-only with respect to the installed app and to the upstream site.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));

function flag(name, dflt) {
  const i = process.argv.indexOf('--' + name);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : dflt;
}

const outDir = process.argv[2];
if (!outDir || outDir.startsWith('--')) {
  console.error('usage: node webapp/make-fixture.mjs <fixtureDir> '
    + '[--cache <rawCacheDir>] [--dict <dict.json>]');
  process.exit(2);
}
const dictPath = flag('dict', path.join(HERE, 'zh-hans.json'));
const rawCache = flag('cache', path.join(
  process.env.LOCALAPPDATA || process.env.HOME || '.', 'Devin', 'zh-webapp-cache',
));

const dict = JSON.parse(fs.readFileSync(dictPath, 'utf8'));
const entries = Object.entries(dict).filter(([k, v]) => !k.startsWith('_') && v && v.en && v.zh);

// --- form 1 ---------------------------------------------------------------
const pairs = entries
  .map(([k, v]) => JSON.stringify(k) + ':' + JSON.stringify(v.en))
  .join(',');

// --- form 2 ---------------------------------------------------------------
const bareOk = (k) => /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(k);
const noTick = (s) => !s.includes('`') && !s.includes('${');
const bareEntries = entries.filter(([k, v]) => bareOk(k) && noTick(v.en) && noTick(v.zh));
const barePairs = bareEntries.map(([k, v]) => k + ':`' + v.en + '`').join(',');

// --- verbatim excerpt of a real bundle chunk ------------------------------
let ctx = '';
const assets = path.join(rawCache, 'assets');
if (fs.existsSync(assets)) {
  for (const f of fs.readdirSync(assets)) {
    if (!/\.(js|mjs)$/i.test(f)) continue;
    const t = fs.readFileSync(path.join(assets, f), 'utf8');
    const anchor = t.indexOf('backToOrganization:`Back to organization`');
    if (anchor !== -1) {
      ctx = t.slice(Math.max(0, anchor - 600), Math.min(t.length, anchor + 600));
      break;
    }
  }
}

const slice = [
  'const __vite__mapDeps=(i,m=__vite__mapDeps,d=(m.f||(m.f=[])));',
  'const ZH_FIXTURE_FORM1={' + pairs + '};',
  'const ZH_FIXTURE_FORM2={' + barePairs + '};',
  ctx ? '/* --- verbatim excerpt from the live bundle --- */' : '',
  ctx ? 'export const REAL_CONTEXT=' + JSON.stringify(ctx) + ';' : '',
  '',
].join('\n');

const dir = path.join(outDir, 'assets');
fs.mkdirSync(dir, { recursive: true });
const file = path.join(dir, 'ui-fixture.js');
fs.writeFileSync(file, slice, 'utf8');

let inF1 = 0; let inF2 = 0; let alreadyZh = 0;
let translated = 0;
for (const [k, v] of entries) {
  if (slice.includes('"' + k + '":"' + v.en + '"')) inF1++;
  if (bareOk(k) && slice.includes(k + ':`' + v.en + '`')) inF2++;
  // Only entries that actually differ can prove the fixture starts untranslated;
  // brand names (zh === en) would always "match" and are false positives.
  if (v.zh !== v.en) {
    translated++;
    if (slice.includes(v.zh)) alreadyZh++;
  }
}
console.log(`fixture bytes=${slice.length}`);
console.log(`form1 (json)      present=${inF1}/${entries.length}`);
console.log(`form2 (template)  present=${inF2}/${bareEntries.length}`);
console.log(`verbatim excerpt  ${ctx ? 'embedded (' + ctx.length + ' chars)' : 'NOT FOUND (no --cache)'}`);
console.log(`pre-existing zh   ${alreadyZh}/${translated} (must be 0 - fixture starts untranslated)`);
console.log(`written -> ${file}`);
if (alreadyZh) {
  console.error('ERROR: fixture already contains translated text - the source cache '
    + 'is not pristine (it was written by an older proxy build).');
  process.exitCode = 1;
}
