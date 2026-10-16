// Build webapp/zh-hans.json from the hand-written dict-zh.json plus the
// English originals harvested from the live bundle (pairs-en.json).
//
// Usage:
//   node build/webapp-dict.mjs <pairs-en.json> [out.json]
//
// The output is the runtime dictionary consumed by webapp/proxy.mjs:
//   { "<key>": { "en": "<english original>", "zh": "<chinese>" }, ... }
// Matching is done on the exact serialized pair `"<key>":"<en>"`, so the
// English original must be byte-accurate or the entry is skipped with a warning.
import fs from 'node:fs';
import path from 'node:path';

const pairsPath = process.argv[2];
if (!pairsPath) {
  console.error('usage: node build/webapp-dict.mjs <pairs-en.json> [out.json]');
  process.exit(2);
}
const here = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'));
const repoRoot = path.resolve(here, '..');
const dictPath = path.join(repoRoot, 'webapp', 'dict-zh.json');
const outPath = process.argv[3] || path.join(repoRoot, 'webapp', 'zh-hans.json');

const dict = JSON.parse(fs.readFileSync(dictPath, 'utf8'));
const en = JSON.parse(fs.readFileSync(pairsPath, 'utf8'));
const overrides = dict._enOverride || {};

const out = {};
const missing = [];
const skippedMeta = new Set(['_comment', '_enOverride']);
for (const [key, zh] of Object.entries(dict)) {
  if (skippedMeta.has(key)) continue;
  const source = en[key] !== undefined ? en[key] : overrides[key];
  if (typeof source !== 'string') {
    missing.push(key);
    continue;
  }
  if (typeof zh !== 'string' || !zh) {
    missing.push(key + ' (empty translation)');
    continue;
  }
  out[key] = { en: source, zh };
}

fs.writeFileSync(outPath, JSON.stringify(out, null, 2) + '\n', 'utf8');
console.log(`dictionary entries : ${Object.keys(dict).length - skippedMeta.size}`);
console.log(`resolved with en   : ${Object.keys(out).length}`);
console.log(`skipped            : ${missing.length}`);
for (const m of missing) console.log(`   - ${m}`);
console.log(`written -> ${outPath}`);
if (missing.length) process.exitCode = 1;
