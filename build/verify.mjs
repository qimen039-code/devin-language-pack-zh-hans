#!/usr/bin/env node
/**
 * verify.mjs — integrity + coverage self-check for a built .vsix.
 *
 * Zero dependencies. Reads the central directory directly and asserts:
 *   1. ZIP magic / EOCD signature are present (the very failure mode that
 *      breaks truncated marketplace downloads).
 *   2. Every entry is individually inflatable and its CRC32 matches.
 *   3. package.json / vsixmanifest identity fields agree.
 *   4. Every string in translations/overrides/devin-zh-hans.json is present
 *      in the packaged main.i18n.json.
 *
 * Usage:
 *   node build/verify.mjs [path/to/file.vsix]
 */
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..');

const CRC_TABLE = (() => {
  const t = new Int32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c;
  }
  return t;
})();
const crc32 = (b) => {
  let c = -1;
  for (let i = 0; i < b.length; i++) c = (c >>> 8) ^ CRC_TABLE[(c ^ b[i]) & 0xff];
  return (c ^ -1) >>> 0;
};

/* ---- locate the file ---- */
let vsix = process.argv[2];
if (!vsix) {
  const dist = path.join(ROOT, 'dist');
  if (!fs.existsSync(dist)) throw new Error('dist/ not found — run: node build/build.mjs');
  const cands = fs.readdirSync(dist).filter((f) => f.endsWith('.vsix'));
  if (cands.length !== 1) throw new Error(`expected exactly one .vsix in dist/, found ${cands.length}`);
  vsix = path.join(dist, cands[0]);
}

const buf = fs.readFileSync(vsix);
const fail = [];
const ok = (cond, msg, extra = '') => {
  console.log(`  ${cond ? 'PASS' : 'FAIL'}  ${msg}${extra ? '  ' + extra : ''}`);
  if (!cond) fail.push(msg);
};

console.log('file    :', vsix);
console.log('size    :', buf.length, 'bytes');
console.log('');

console.log('[1] container');
ok(buf.readUInt32LE(0) === 0x04034b50, 'local file header magic 50 4B 03 04', `got ${buf.subarray(0, 4).toString('hex')}`);
const eocdSig = Buffer.from([0x50, 0x4b, 0x05, 0x06]);
const eocdPos = buf.lastIndexOf(eocdSig);
ok(eocdPos > 0, 'EOCD signature found', eocdPos > 0 ? `@${eocdPos}` : 'NOT FOUND (truncated file)');
if (eocdPos < 0) {
  console.log('\nRESULT: FAIL — not a valid ZIP, cannot continue.');
  process.exit(1);
}

const entryCount = buf.readUInt16LE(eocdPos + 10);
const cdSize = buf.readUInt32LE(eocdPos + 12);
const cdOffset = buf.readUInt32LE(eocdPos + 16);
ok(cdOffset + cdSize === eocdPos, 'central directory size/offset consistent');

/* ---- walk central directory ---- */
console.log('');
console.log('[2] entries');
const entries = [];
let p = cdOffset;
for (let i = 0; i < entryCount; i++) {
  if (buf.readUInt32LE(p) !== 0x02014b50) { ok(false, `central header #${i} signature`); break; }
  const method = buf.readUInt16LE(p + 10);
  const crc = buf.readUInt32LE(p + 16);
  const compSize = buf.readUInt32LE(p + 20);
  const size = buf.readUInt32LE(p + 24);
  const nameLen = buf.readUInt16LE(p + 28);
  const extraLen = buf.readUInt16LE(p + 30);
  const commentLen = buf.readUInt16LE(p + 32);
  const localOff = buf.readUInt32LE(p + 42);
  const name = buf.subarray(p + 46, p + 46 + nameLen).toString('utf8');
  entries.push({ name, method, crc, compSize, size, localOff });
  p += 46 + nameLen + extraLen + commentLen;
}
ok(entries.length === entryCount, `read ${entryCount} central directory entries`);

let crcBad = 0;
let inflated = 0;
for (const e of entries) {
  const nl = buf.readUInt16LE(e.localOff + 26);
  const el = buf.readUInt16LE(e.localOff + 28);
  const start = e.localOff + 30 + nl + el;
  const payload = buf.subarray(start, start + e.compSize);
  let data;
  try {
    data = e.method === 8 ? zlib.inflateRawSync(payload) : Buffer.from(payload);
  } catch {
    crcBad++; continue;
  }
  if (data.length !== e.size || crc32(data) !== e.crc) { crcBad++; continue; }
  inflated++;
}
ok(crcBad === 0, `all ${entries.length} entries inflate with matching CRC32`, crcBad ? `${crcBad} bad` : '');

function readEntry(name) {
  const e = entries.find((x) => x.name === name);
  if (!e) return null;
  const start = e.localOff + 30 + buf.readUInt16LE(e.localOff + 26) + buf.readUInt16LE(e.localOff + 28);
  const raw = buf.subarray(start, start + e.compSize);
  return e.method === 8 ? zlib.inflateRawSync(raw) : Buffer.from(raw);
}

console.log('');
console.log('[3] identity');
const pkg = JSON.parse(readEntry('extension/package.json').toString('utf8'));
const man = readEntry('extension.vsixmanifest').toString('utf8');
const identity = (man.match(/<Identity\b[^>]*\/>/) || [''])[0];
const attr = (re) => (man.match(re) || [])[1];
const idAttr = (name) => (identity.match(new RegExp(`\\b${name}="([^"]+)"`)) || [])[1];
ok(pkg.name === idAttr('Id'), 'package.json name == manifest Identity Id', `${pkg.name}`);
ok(pkg.publisher === idAttr('Publisher'), 'package.json publisher == manifest Identity Publisher', `${pkg.publisher}`);
ok(pkg.version === idAttr('Version'), 'package.json version == manifest Identity Version', `${pkg.version}`);
ok(pkg.engines.vscode === attr(/Code\.Engine" Value="([^"]+)"/), 'engines.vscode == manifest Engine', `${pkg.engines.vscode}`);
ok(pkg.contributes.localizations[0].languageId === 'zh-cn', 'localizations languageId == zh-cn');

console.log('');
console.log('[4] translation coverage');
const main = JSON.parse(readEntry('extension/translations/main.i18n.json').toString('utf8'));
let total = 0;
for (const m of Object.keys(main.contents)) total += Object.keys(main.contents[m]).length;
ok(total > 20000, `core strings present: ${total}`);

const overrides = JSON.parse(fs.readFileSync(path.join(ROOT, 'translations/overrides/devin-zh-hans.json'), 'utf8'));
let missing = 0;
for (const compound of Object.keys(overrides)) {
  const i = compound.indexOf('::');
  const mod = compound.slice(0, i);
  const key = compound.slice(i + 2);
  if (!main.contents[mod] || !main.contents[mod][key]) missing++;
}
ok(missing === 0, `all ${Object.keys(overrides).length} Devin-specific overrides packaged`, missing ? `${missing} missing` : '');

const extFiles = entries.filter((e) => /^extension\/translations\/extensions\/.+\.i18n\.json$/.test(e.name)).length;
ok(extFiles === 93, 'built-in extension translation files: 93', `got ${extFiles}`);

console.log('');
if (fail.length) {
  console.log(`RESULT: FAIL (${fail.length})`);
  for (const f of fail) console.log('  - ' + f);
  process.exit(1);
}
console.log('RESULT: PASS — VSIX is structurally valid and fully packaged.');
