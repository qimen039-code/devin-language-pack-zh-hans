#!/usr/bin/env node
/**
 * build.mjs — package this repository into a .vsix language pack.
 *
 * Zero dependencies: the ZIP container is written directly with `node:zlib`.
 * Node.js >= 16 is the only requirement.
 *
 * Usage:
 *   node build/build.mjs                 # -> dist/<publisher>.<name>-<version>.vsix
 *   node build/build.mjs --out some.vsix
 *   node build/build.mjs --publisher my-github-name
 *   node build/build.mjs --date 2026-10-16T00:00:00Z    # reproducible build
 */
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..');

/* ------------------------------------------------------------------ *
 * 1. minimal ZIP writer (deflate, UTF-8 names, no data descriptors)
 * ------------------------------------------------------------------ */

const CRC_TABLE = (() => {
  const t = new Int32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c;
  }
  return t;
})();

function crc32(buf) {
  let c = -1;
  for (let i = 0; i < buf.length; i++) c = (c >>> 8) ^ CRC_TABLE[(c ^ buf[i]) & 0xff];
  return (c ^ -1) >>> 0;
}

/**
 * MS-DOS timestamp. Pass `utc = true` together with a fixed date to get a
 * byte-identical archive on any machine and any timezone.
 */
function dosStamp(d = new Date(), utc = false) {
  const H = utc ? d.getUTCHours() : d.getHours();
  const M = utc ? d.getUTCMinutes() : d.getMinutes();
  const S = utc ? d.getUTCSeconds() : d.getSeconds();
  const Y = utc ? d.getUTCFullYear() : d.getFullYear();
  const Mo = utc ? d.getUTCMonth() : d.getMonth();
  const D = utc ? d.getUTCDate() : d.getDate();
  return {
    time: ((H & 31) << 11) | ((M & 63) << 5) | ((S / 2) & 31),
    date: (((Y - 1980) & 127) << 9) | (((Mo + 1) & 15) << 5) | (D & 31),
  };
}

/** @param {{name:string, data:Buffer}[]} files @param {{time:number,date:number}} [stamp] */
function makeZip(files, stamp = dosStamp()) {
  const chunks = [];
  const central = [];
  let offset = 0;

  for (const f of files) {
    const name = Buffer.from(f.name, 'utf8');
    const crc = crc32(f.data);
    const raw = zlib.deflateRawSync(f.data, { level: 9 });
    const useDeflate = raw.length < f.data.length;
    const payload = useDeflate ? raw : f.data;
    const method = useDeflate ? 8 : 0;

    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);        // version needed
    local.writeUInt16LE(0x0800, 6);    // UTF-8 names
    local.writeUInt16LE(method, 8);
    local.writeUInt16LE(stamp.time, 10);
    local.writeUInt16LE(stamp.date, 12);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(payload.length, 18);
    local.writeUInt32LE(f.data.length, 22);
    local.writeUInt16LE(name.length, 26);
    local.writeUInt16LE(0, 28);

    chunks.push(local, name, payload);

    const cd = Buffer.alloc(46);
    cd.writeUInt32LE(0x02014b50, 0);
    cd.writeUInt16LE(0x031e, 4);       // made by: unix, 3.0
    cd.writeUInt16LE(20, 6);
    cd.writeUInt16LE(0x0800, 8);
    cd.writeUInt16LE(method, 10);
    cd.writeUInt16LE(stamp.time, 12);
    cd.writeUInt16LE(stamp.date, 14);
    cd.writeUInt32LE(crc, 16);
    cd.writeUInt32LE(payload.length, 20);
    cd.writeUInt32LE(f.data.length, 24);
    cd.writeUInt16LE(name.length, 28);
    cd.writeUInt16LE(0, 30);           // extra
    cd.writeUInt16LE(0, 32);           // comment
    cd.writeUInt16LE(0, 34);           // disk
    cd.writeUInt16LE(0, 36);           // internal attrs
    cd.writeUInt32LE((0o100644 << 16) >>> 0, 38);   // unix mode rw-r--r--
    cd.writeUInt32LE(offset, 42);
    central.push(cd, name);

    offset += local.length + name.length + payload.length;
  }

  const cdBuf = Buffer.concat(central);
  const eocd = Buffer.alloc(22);
  eocd.writeUInt32LE(0x06054b50, 0);
  eocd.writeUInt16LE(0, 4);
  eocd.writeUInt16LE(0, 6);
  eocd.writeUInt16LE(files.length, 8);
  eocd.writeUInt16LE(files.length, 10);
  eocd.writeUInt32LE(cdBuf.length, 12);
  eocd.writeUInt32LE(offset, 16);
  eocd.writeUInt16LE(0, 20);

  return Buffer.concat([...chunks, cdBuf, eocd]);
}

/* ------------------------------------------------------------------ *
 * 2. args + config
 * ------------------------------------------------------------------ */

const argv = process.argv.slice(2);
const argOf = (flag) => {
  const i = argv.indexOf(flag);
  return i === -1 ? undefined : argv[i + 1];
};

const cfg = JSON.parse(fs.readFileSync(path.join(ROOT, 'repo.config.json'), 'utf8'));
const publisher = argOf('--publisher') || cfg.publisher;
const outArg = argOf('--out');

// Reproducible builds: a fixed timestamp makes the archive byte-identical for
// the same inputs, so anyone can rebuild a release and compare SHA-256.
//   1) --date 2026-10-16T00:00:00Z
//   2) SOURCE_DATE_EPOCH=<unix seconds>   (the cross-ecosystem convention)
const dateArg = argOf('--date');
const epochArg = process.env.SOURCE_DATE_EPOCH;
let stampOverride;
if (dateArg) {
  const d = new Date(dateArg);
  if (Number.isNaN(d.getTime())) throw new Error(`--date is not a valid date: ${dateArg}`);
  stampOverride = dosStamp(d, true);
} else if (epochArg) {
  const d = new Date(Number(epochArg) * 1000);
  if (Number.isNaN(d.getTime())) throw new Error(`SOURCE_DATE_EPOCH is not a number: ${epochArg}`);
  stampOverride = dosStamp(d, true);
}

/* ------------------------------------------------------------------ *
 * 3. collect + validate payload
 * ------------------------------------------------------------------ */

const pkg = JSON.parse(fs.readFileSync(path.join(ROOT, 'package.json'), 'utf8'));
const pkgVersion = pkg.version;
const version = argOf('--version') || pkgVersion;
const engine = pkg.engines?.vscode || cfg.engine;

// package.json is the single source of truth for the version. repo.config.json
// used to carry a duplicate that silently drifted out of sync, so it no longer
// holds one. If anyone re-adds it (or a stale one survives), fail loudly rather
// than ship a VSIX whose name disagrees with its own manifest.
if (cfg.version !== undefined && cfg.version !== pkgVersion) {
  console.error(
    `ERROR: repo.config.json version "${cfg.version}" != package.json version "${pkgVersion}".\n` +
    '       package.json is authoritative; remove the duplicate field from repo.config.json.'
  );
  process.exit(1);
}

// Source-only trees that must not be shipped inside the VSIX.
// LICENSE / NOTICE.md are intentionally kept: the MIT notice must accompany copies.
// `webapp` is the separate app.devin.ai overlay (proxy + byte patch); it is not
// extension code and must never end up inside the language pack.
const excluded = new Set(['translations/overrides', 'webapp', 'build', 'vsix', 'dist', '.git', '.github', 'repo.config.json', '.gitignore']);
const files = [];

function walk(absDir, relDir) {
  for (const entry of fs.readdirSync(absDir, { withFileTypes: true })) {
    const rel = relDir ? `${relDir}/${entry.name}` : entry.name;
    if (excluded.has(rel)) continue;
    const abs = path.join(absDir, entry.name);
    if (entry.isDirectory()) walk(abs, rel);
    else files.push({ name: `extension/${rel}`, data: fs.readFileSync(abs) });
  }
}
walk(ROOT, '');

// root-level VSIX plumbing
files.push({ name: '[Content_Types].xml', data: fs.readFileSync(path.join(ROOT, 'vsix/[Content_Types].xml')) });

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const repoUrl = cfg.repository || `https://github.com/${publisher}/${pkg.name}`;

const tags = ['中文(简体)', 'lp-zh-cn', '__lp_vscode', '__lp-zh-cn_vscode',
  ...pkg.contributes.localizations[0].translations
    .filter((t) => t.id !== 'vscode')
    .flatMap((t) => [`__lp_${t.id}`, `__lp-zh-cn_${t.id}`])].join(',');

const manifest = `<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011" xmlns:d="http://schemas.microsoft.com/developer/vsx-schema-design/2011">
  <Metadata>
    <Identity Language="en-US" Id="${esc(pkg.name)}" Version="${esc(version)}" Publisher="${esc(publisher)}" />
    <DisplayName>${esc(pkg.displayName)}</DisplayName>
    <Description xml:space="preserve">${esc(pkg.description)}</Description>
    <Tags>${esc(tags)}</Tags>
    <Categories>${esc(pkg.categories.join(','))}</Categories>
    <GalleryFlags>Public</GalleryFlags>
    <Properties>
      <Property Id="Microsoft.VisualStudio.Code.Engine" Value="${esc(engine)}" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionDependencies" Value="" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionPack" Value="" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionKind" Value="ui,workspace" />
      <Property Id="Microsoft.VisualStudio.Code.LocalizedLanguages" Value="中文(简体)" />
      <Property Id="Microsoft.VisualStudio.Code.EnabledApiProposals" Value="" />
      <Property Id="Microsoft.VisualStudio.Services.Links.Source" Value="${esc(repoUrl)}" />
      <Property Id="Microsoft.VisualStudio.Services.Links.Getstarted" Value="${esc(repoUrl)}" />
      <Property Id="Microsoft.VisualStudio.Services.Links.GitHub" Value="${esc(repoUrl)}" />
      <Property Id="Microsoft.VisualStudio.Services.Links.Support" Value="${esc(repoUrl)}/issues" />
      <Property Id="Microsoft.VisualStudio.Services.Links.Learn" Value="${esc(repoUrl)}#readme" />
      <Property Id="Microsoft.VisualStudio.Services.GitHubFlavoredMarkdown" Value="true" />
      <Property Id="Microsoft.VisualStudio.Services.Content.Pricing" Value="Free" />
    </Properties>
    <Icon>extension/languagepack.png</Icon>
  </Metadata>
  <Installation>
    <InstallationTarget Id="Microsoft.VisualStudio.Code" />
  </Installation>
  <Dependencies />
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true" />
    <Asset Type="Microsoft.VisualStudio.Services.Content.Details" Path="extension/README.md" Addressable="true" />
    <Asset Type="Microsoft.VisualStudio.Services.Content.Changelog" Path="extension/CHANGELOG.md" Addressable="true" />
    <Asset Type="Microsoft.VisualStudio.Services.Icons.Default" Path="extension/languagepack.png" Addressable="true" />
    <Asset Type="Microsoft.VisualStudio.Code.Translation.ZH-CN" Path="extension/translations/main.i18n.json" Addressable="true" />
  </Assets>
</PackageManifest>
`;
files.unshift({ name: 'extension.vsixmanifest', data: Buffer.from(manifest, 'utf8') });

// sanity checks
const need = ['extension/package.json', 'extension/translations/main.i18n.json', 'extension/README.md', 'extension/CHANGELOG.md'];
for (const n of need) {
  if (!files.some((f) => f.name === n)) throw new Error(`missing required entry: ${n}`);
}

/* ------------------------------------------------------------------ *
 * 4. write
 * ------------------------------------------------------------------ */

const distDir = path.join(ROOT, 'dist');
fs.mkdirSync(distDir, { recursive: true });
const out = outArg ? path.resolve(outArg) : path.join(distDir, `${publisher}.${pkg.name}-${version}.vsix`);

const zip = makeZip(files, stampOverride);
fs.writeFileSync(out, zip);

const i18n = JSON.parse(fs.readFileSync(path.join(ROOT, 'translations/main.i18n.json'), 'utf8'));
let keyCount = 0;
for (const m of Object.keys(i18n.contents)) keyCount += Object.keys(i18n.contents[m]).length;
const extCount = files.filter((f) => f.name.startsWith('extension/translations/extensions/')).length;

console.log('built   :', path.relative(ROOT, out));
console.log('entries :', files.length, `(${extCount} extension translation files)`);
console.log('size    :', zip.length, 'bytes');
console.log('sha256  :', crypto.createHash('sha256').update(zip).digest('hex'));
console.log('stamp   :', stampOverride ? 'fixed (reproducible)' : 'current time (non-reproducible)');
console.log('id      :', `${publisher}.${pkg.name}@${version}`);
console.log('engine  :', engine);
console.log('strings :', keyCount, 'core keys');
