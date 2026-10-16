// Offline self-test for webapp/proxy.mjs.
//
//   node webapp/make-fixture.mjs <fixtureDir> [--cache <rawCacheDir>]
//   node webapp/test-proxy.mjs   [fixtureDir]
//
// Runs the proxy against a fixture cache with --offline (no network at all) and
// checks that:
//   - both serialisation forms are substituted,
//   - no pattern is left untranslated,
//   - a pinned window of real bundle bytes is edited exactly as expected,
//   - non-asset paths are still refused when offline.
//
// The expected rewrite count is derived from the fixture bytes rather than
// hard-coded, so the test tracks dictionary growth automatically.
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const repo = path.join(HERE, '..');
const cache = process.argv[2] && !process.argv[2].startsWith('--')
  ? process.argv[2]
  : path.join(os.tmpdir(), 'devin-zh-fixture');
const port = 5176;
const node = process.execPath;

const dictPath = path.join(HERE, 'zh-hans.json');
const rawDict = JSON.parse(fs.readFileSync(dictPath, 'utf8'));
// The proxy drops entries whose translation equals the English original
// (brand names such as "Devin Desktop").
const entries = Object.entries(rawDict)
  .filter(([k, v]) => !k.startsWith('_') && v.zh && v.zh !== v.en);

const bareOk = (k) => /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(k);
const noTick = (s) => !s.includes('`') && !s.includes('${');

const fixtureFile = path.join(cache, 'assets', 'ui-fixture.js');
if (!fs.existsSync(fixtureFile)) {
  console.error('fixture missing: ' + fixtureFile);
  console.error('run: node webapp/make-fixture.mjs ' + cache);
  process.exit(2);
}
const fixtureRaw = fs.readFileSync(fixtureFile, 'utf8');

const countOcc = (hay, needle) => {
  let n = 0; let from = 0;
  for (;;) {
    const i = hay.indexOf(needle, from);
    if (i === -1) return n;
    n++; from = i + 1;
  }
};

let expectedRewrites = 0;
const form1 = [];
const form2 = [];
for (const [k, v] of entries) {
  const p1 = JSON.stringify(k) + ':' + JSON.stringify(v.en);
  const c1 = countOcc(fixtureRaw, p1);
  if (c1) { expectedRewrites += c1; form1.push([p1, JSON.stringify(k) + ':' + JSON.stringify(v.zh)]); }
  if (bareOk(k) && noTick(v.en) && noTick(v.zh)) {
    const p2 = k + ':`' + v.en + '`';
    const c2 = countOcc(fixtureRaw, p2);
    if (c2) { expectedRewrites += c2; form2.push([p2, k + ':`' + v.zh + '`']); }
  }
}
console.log(`fixture: ${fixtureFile}`);
console.log(`expected: entries=${entries.length} form1=${form1.length} form2=${form2.length} rewrites=${expectedRewrites}`);

const child = spawn(node, [
  path.join(HERE, 'proxy.mjs'),
  '--offline', '--port', String(port), '--cache', cache,
], { stdio: ['ignore', 'pipe', 'pipe'] });

let log = '';
child.stdout.on('data', (d) => { log += d.toString(); });
child.stderr.on('data', (d) => { log += '[err] ' + d.toString(); });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitForHealth() {
  for (let i = 0; i < 40; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/__zh/health`);
      if (r.ok) return await r.json();
    } catch { /* retry */ }
    await sleep(150);
  }
  throw new Error('proxy did not become healthy\n' + log);
}

let failures = 0;
function check(name, ok, extra = '') {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  ' + extra : ''}`);
  if (!ok) failures++;
}

try {
  const health = await waitForHealth();
  console.log(`proxy log: ${log.trim().split('\n').join(' | ')}`);
  check('health ok', health.ok === true);
  check('dictionary loaded', health.dict === entries.length,
    `dict=${health.dict} expected=${entries.length}`);

  const res = await fetch(`http://127.0.0.1:${port}/assets/ui-fixture.js`);
  const body = await res.text();
  check('asset served', res.status === 200, `status=${res.status}`);
  check('rewrite count reported',
    Number(res.headers.get('x-zh-rewrites')) === expectedRewrites,
    `x-zh-rewrites=${res.headers.get('x-zh-rewrites')} expected=${expectedRewrites}`);
  check('source = cache', res.headers.get('x-zh-source') === 'cache');

  // form 1 - spot check a few (the full list is covered by the leftovers check)
  for (const [from, to] of form1.slice(0, 6)) {
    check(`form1 applied ${from.slice(0, 48)}`, body.includes(to));
  }
  // form 2 - every entry (this is the form the minified bundles use)
  for (const [from, to] of form2) {
    check(`form2 applied ${from}`, body.includes(to));
  }

  const leftovers = [...form1, ...form2].filter(([from]) => body.includes(from));
  check('no pattern left untranslated', leftovers.length === 0,
    leftovers.length ? `left=${leftovers.slice(0, 3).map(([f]) => f).join(' ; ')}` : '');

  // The verbatim excerpt must come back with exactly the expected substitutions
  // applied and nothing else changed: this pins ~1.2 KB of real bundle bytes.
  const m = /export const REAL_CONTEXT=("(?:[^"\\]|\\.)*");/.exec(fixtureRaw);
  if (m) {
    const ctx = JSON.parse(m[1]);
    check('excerpt really contains the English form', ctx.includes('Back to organization'));
    let expectCtx = ctx;
    for (const [from, to] of [...form1, ...form2]) expectCtx = expectCtx.split(from).join(to);
    check('verbatim excerpt edited exactly as expected',
      body.includes(JSON.stringify(expectCtx)) && expectCtx !== ctx);
  } else {
    check('fixture embeds verbatim excerpt', false,
      'REAL_CONTEXT not found - regenerate the fixture with --cache');
  }

  const api = await fetch(`http://127.0.0.1:${port}/api/users/preferences`);
  check('non-asset path refused offline', api.status === 502, `status=${api.status}`);
} catch (e) {
  console.log('FAIL  ' + e.message);
  failures++;
} finally {
  child.kill('SIGTERM');
  await sleep(400);
  child.kill('SIGKILL');
}

console.log(failures === 0 ? '\nALL PASS' : `\n${failures} FAILURE(S)`);
process.exit(failures === 0 ? 0 : 1);
