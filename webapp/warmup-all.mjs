#!/usr/bin/env node
// Warm the whole app.devin.ai asset graph through the local rewriting proxy.
//
// The webapp is a Vite build: the entry document references a fixed set of
// modulepreload chunks, and every other route/feature chunk is reached only
// through runtime `import()` calls whose specifier is a plain string literal
// inside an already-loaded chunk.  A depth-1 scan of the entry document
// therefore misses every lazily loaded page (settings, review, automations...).
//
// This crawler closes the graph instead: it reads every chunk already on disk,
// extracts `assets/<name>.js` literals, fetches whatever is still missing via
// the proxy, and repeats until no new specifiers appear.
//
// Usage:
//   node webapp/warmup-all.mjs --port 5175 [--cache <dir>] [--limit 2000] [--rounds 8]

import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';

function arg(name, dflt) {
  const i = process.argv.indexOf('--' + name);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : dflt;
}

const PORT = Number(arg('port', 5175));
const CACHE = path.resolve(
  arg('cache', path.join(process.env.LOCALAPPDATA || process.env.HOME || '.', 'Devin', 'zh-webapp-cache'))
);
const LIMIT = Number(arg('limit', 2000));
const ROUNDS = Number(arg('rounds', 8));
const ENTRY = arg('route', '/desktop-no-surfaces');

const ASSET_RE = /assets\/[A-Za-z0-9_.@-]+\.(?:js|mjs|css)/g;

function req(urlPath) {
  return new Promise((resolve, reject) => {
    const r = http.request(
      { host: '127.0.0.1', port: PORT, path: urlPath, method: 'GET',
        headers: { 'accept': '*/*', 'accept-encoding': 'identity' }, timeout: 60000 },
      (res) => {
        const chunks = [];
        res.on('data', (c) => chunks.push(c));
        res.on('end', () => resolve({ status: res.statusCode, body: Buffer.concat(chunks) }));
      }
    );
    r.on('timeout', () => { r.destroy(new Error('timeout')); });
    r.on('error', reject);
    r.end();
  });
}

function collectRefs(text, into) {
  let m;
  ASSET_RE.lastIndex = 0;
  while ((m = ASSET_RE.exec(text)) !== null) into.add(m[0]);
}

function readAllCachedText() {
  const dir = path.join(CACHE, 'assets');
  const out = [];
  if (!fs.existsSync(dir)) return out;
  for (const name of fs.readdirSync(dir)) {
    if (!/\.(js|mjs|css)$/i.test(name)) continue;
    try { out.push(fs.readFileSync(path.join(dir, name), 'utf8')); } catch {}
  }
  return out;
}

function cachedSet() {
  const dir = path.join(CACHE, 'assets');
  const s = new Set();
  if (!fs.existsSync(dir)) return s;
  for (const name of fs.readdirSync(dir)) s.add('assets/' + name);
  return s;
}

const seen = new Set();
let fetched = 0, failed = 0, rounds = 0;

// Seed with the entry document routes.
async function main() {
  console.log(`[warm-all] proxy http://127.0.0.1:${PORT}  cache ${CACHE}`);
  console.log(`[warm-all] seed route ${ENTRY}`);

  const seeds = [ENTRY, '/', '/desktop-no-surfaces'];
  for (const route of seeds) {
    try {
      const r = await req(route);
      if (r.status === 200) {
        const refs = new Set();
        collectRefs(r.body.toString('utf8'), refs);
        for (const x of refs) seen.add(x);
        console.log(`[warm-all] seed ${route} -> ${r.status} ${r.body.length}B, ${refs.size} refs`);
      }
    } catch (e) { console.log(`[warm-all] seed ${route} failed: ${e.message}`); }
  }

  while (rounds < ROUNDS) {
    rounds++;
    // Harvest specifiers from everything already on disk.
    for (const text of readAllCachedText()) collectRefs(text, seen);

    const have = cachedSet();
    const todo = [...seen].filter((p) => !have.has(p));

    if (rounds === 1 || todo.length) {
      console.log(`[warm-all] round ${rounds}: known=${seen.size} cached=${have.size} todo=${todo.length}`);
    }
    if (!todo.length) { console.log('[warm-all] graph closed.'); break; }

    const batch = todo.slice(0, LIMIT);
    let idx = 0;
    const CONC = 6;
    async function worker() {
      while (idx < batch.length) {
        const p = batch[idx++];
        try {
          const r = await req('/' + p);
          if (r.status === 200) fetched++;
          else failed++;
        } catch { failed++; }
      }
    }
    await Promise.all(Array.from({ length: CONC }, worker));
    if (todo.length > LIMIT) console.log(`[warm-all] limit reached, deferring ${todo.length - LIMIT}`);
  }

  const have = cachedSet();
  console.log(`[warm-all] done. distinct refs=${seen.size} cached=${have.size} fetched=${fetched} failed=${failed} rounds=${rounds}`);

  // Report which dictionary targets are now reachable on disk.
  const dictPath = arg('dict', path.join(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')), 'zh-hans.json'));
  try {
    const dict = JSON.parse(fs.readFileSync(dictPath, 'utf8'));
    const keys = Object.keys(dict);
    const blob = readAllCachedText().join('\n');
    let pair = 0, bare = 0, none = 0;
    for (const k of keys) {
      const en = dict[k].en;
      const zh = dict[k].zh;
      if (blob.includes(JSON.stringify(k) + ':' + JSON.stringify(en))) pair++;
      else if (blob.includes(en)) bare++;
      else none++;
    }
    console.log(`[warm-all] dict targets: total=${keys.length} as-key:value-pair=${pair} bare-text-only=${bare} absent=${none}`);
    const absent = keys.filter((k) => {
      const en = dict[k].en;
      return !blob.includes(JSON.stringify(k) + ':' + JSON.stringify(en)) && !blob.includes(en);
    });
    if (absent.length) console.log('[warm-all] absent keys: ' + absent.join(', '));
  } catch (e) { console.log('[warm-all] dict report skipped: ' + e.message); }
}

main().catch((e) => { console.error('[warm-all] fatal', e); process.exit(1); });
