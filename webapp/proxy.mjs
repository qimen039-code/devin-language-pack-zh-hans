// Local reverse proxy that serves the Devin web app (app.devin.ai) from
// 127.0.0.1 with Simplified Chinese strings substituted into the JS bundles.
//
//   node webapp/proxy.mjs [--port 5175] [--cache <dir>] [--dict <file>]
//                         [--upstream-proxy auto|none|host:port] [--offline]
//
// Upstream routing
//   `auto` (default) uses the standard HTTPS_PROXY / HTTP_PROXY / ALL_PROXY
//   environment variables when one of them is a plain http:// CONNECT endpoint,
//   and otherwise connects directly.  It never guesses local ports, so no
//   particular proxy setup is baked into this file.  Pass an explicit
//   host:port, or `none`, to bypass the environment.
//
// Why this exists
//   Devin Desktop renders its Sessions / Settings surface in a sandboxed
//   iframe pointed at https://app.devin.ai (see webapp/README.md). That app is
//   closed source and ships only en/ja/es/pt, so a VS Code language pack cannot
//   reach it. This proxy re-serves the same live bundles from loopback with the
//   strings replaced, which needs no certificate authority and no TLS
//   interception: the browser talks plain HTTP to 127.0.0.1 and this process is
//   an ordinary HTTPS client upstream.
//
// Privacy
//   Binds loopback only. Never logs request/response headers, cookies, tokens
//   or bodies. Only method, path, status and rewrite counters are logged.

import fs from 'node:fs';
import http from 'node:http';
import https from 'node:https';
import path from 'node:path';
import tls from 'node:tls';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const UPSTREAM_HOST = 'app.devin.ai';
const UPSTREAM_PORT = 443;

function arg(name, fallback) {
  const i = process.argv.indexOf('--' + name);
  if (i === -1) return fallback;
  const v = process.argv[i + 1];
  return v && !v.startsWith('--') ? v : true;
}

const PORT = Number(arg('port', 5175));
const DICT_PATH = String(arg('dict', path.join(HERE, 'zh-hans.json')));
const CACHE_DIR = String(
  arg('cache', path.join(process.env.LOCALAPPDATA || process.env.HOME || '.', 'Devin', 'zh-webapp-cache')),
);
const OFFLINE = arg('offline', false) === true;
const STATIC_ONLY = arg('static-only', false) === true;

// ---------------------------------------------------------------- dictionary

let ENTRIES = [];
function loadDict() {
  const raw = JSON.parse(fs.readFileSync(DICT_PATH, 'utf8'));
  ENTRIES = Object.entries(raw)
    .map(([key, v]) => {
      const pats = [];
      // Form 1 - JSON/string-literal object, as emitted for the big per-locale
      // resource maps:  {"localSettings":"Local Settings"}
      pats.push({
        from: JSON.stringify(key) + ':' + JSON.stringify(v.en),
        to: JSON.stringify(key) + ':' + JSON.stringify(v.zh),
      });
      // Form 2 - minified object with bare identifier keys and template-literal
      // values, as emitted for the small per-component label maps:
      //   backToOrganization:`Back to organization`
      // Both forms carry the key name, so the substitution stays unambiguous.
      const bareOk = /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(key);
      const noTick = (s) => typeof s === 'string' && !s.includes('`') && !s.includes('${');
      if (bareOk && noTick(v.en) && noTick(v.zh)) {
        pats.push({ from: key + ':`' + v.en + '`', to: key + ':`' + v.zh + '`' });
      }
      return { key, en: v.en, zh: v.zh, hits: 0, pats };
    })
    .filter((e) => e.en && e.zh && e.zh !== e.en);
  console.log(
    `[zh] dictionary loaded: ${ENTRIES.length} entries `
    + `(${ENTRIES.reduce((n, e) => n + e.pats.length, 0)} patterns) from ${DICT_PATH}`,
  );
}

function rewrite(text) {
  let hits = 0;
  let out = text;
  for (const e of ENTRIES) {
    for (const p of e.pats) {
      if (!out.includes(p.from)) continue;
      const parts = out.split(p.from);
      const n = parts.length - 1;
      hits += n;
      e.hits += n;
      out = parts.join(p.to);
    }
  }
  return { text: out, hits };
}

// Diagnostic: for entries that never matched, explain *why*.  Reads the cache
// blob once; reports whether the English text is present as a `"key":"en"`
// pair (pattern broken), as bare text (hardcoded literal, needs a different
// pattern), or absent entirely (string lives on a route we never fetched).
//
// The cache mirrors upstream verbatim, so this reads pristine bundles - it is
// never confused by our own substitutions.
function readCacheBlob() {
  const dir = path.join(CACHE_DIR, 'assets');
  const files = fs.existsSync(dir) ? fs.readdirSync(dir) : [];
  const parts = [];
  for (const f of files) {
    if (!/\.(js|mjs|css)$/i.test(f)) continue;
    try { parts.push(fs.readFileSync(path.join(dir, f), 'utf8')); } catch {}
  }
  return { files, blob: parts.join('\n') };
}

function coverageReport() {
  const { files, blob } = readCacheBlob();
  const perKey = {};
  const whichPattern = {};
  const buckets = { matched: [], pair_present_pattern_broken: [], bare_text_hardcoded: [], absent: [] };
  for (const e of ENTRIES) {
    let n = 0;
    const used = [];
    for (const p of e.pats) {
      let from = 0;
      let c = 0;
      for (;;) {
        const i = blob.indexOf(p.from, from);
        if (i === -1) break;
        c++; from = i + 1;
      }
      if (c) used.push(p.from.startsWith('"') ? 'json' : 'template');
      n += c;
    }
    perKey[e.key] = n;
    whichPattern[e.key] = used;
    if (n > 0) { buckets.matched.push(e.key); continue; }
    if (blob.includes(e.en)) buckets.bare_text_hardcoded.push(e.key);
    else buckets.absent.push(e.key);
  }
  return { cacheFiles: files.length, perKey, whichPattern, buckets };
}

function diagnoseMisses() {
  return coverageReport();
}

// ------------------------------------------------------------ upstream agent

class TunnelAgent extends https.Agent {
  constructor(proxy) {
    super({ keepAlive: true, maxSockets: 32 });
    this.proxy = proxy;
  }
  createConnection(opts, cb) {
    const target = `${opts.host}:${opts.port || UPSTREAM_PORT}`;
    const creq = http.request({
      host: this.proxy.host,
      port: this.proxy.port,
      method: 'CONNECT',
      path: target,
      headers: { host: target },
      timeout: 15000,
    });
    creq.once('connect', (res, socket) => {
      if (res.statusCode !== 200) {
        socket.destroy();
        cb(new Error(`upstream CONNECT failed: ${res.statusCode}`));
        return;
      }
      const tlsSocket = tls.connect({ socket, servername: opts.host }, () => cb(null, tlsSocket));
      tlsSocket.once('error', cb);
    });
    creq.once('timeout', () => creq.destroy(new Error('upstream CONNECT timeout')));
    creq.once('error', cb);
    creq.end();
  }
}

// Resolve an upstream CONNECT tunnel without hard-coding anyone's local setup.
//
// `auto` (the default) honours the standard proxy environment variables, which
// is what a launcher normally exports for the whole process tree.  If none are
// set the proxy goes direct - it never guesses ports.
function envProxySpec() {
  for (const name of ['HTTPS_PROXY', 'https_proxy', 'HTTP_PROXY', 'http_proxy', 'ALL_PROXY', 'all_proxy']) {
    const v = process.env[name];
    if (!v) continue;
    try {
      const u = new URL(v);
      // Only plain HTTP CONNECT endpoints are usable here; socks5:// would need
      // a different agent entirely, so ignore it rather than fail obscurely.
      if (u.protocol !== 'http:') continue;
      return { host: u.hostname, port: Number(u.port || 80), from: name };
    } catch { /* ignore malformed */ }
  }
  return null;
}

let AGENT;
async function resolveAgent() {
  const spec = arg('upstream-proxy', 'auto');
  if (spec === 'none' || OFFLINE) {
    AGENT = undefined;
    console.log('[zh] upstream: direct');
    return;
  }
  if (spec === 'auto') {
    const env = envProxySpec();
    if (env) {
      AGENT = new TunnelAgent({ host: env.host, port: env.port });
      console.log(`[zh] upstream: CONNECT via ${env.host}:${env.port} (from ${env.from})`);
      return;
    }
    AGENT = undefined;
    console.log('[zh] upstream: direct (no HTTP proxy in the environment)');
    return;
  }
  const [host, port] = String(spec).split(':');
  AGENT = new TunnelAgent({ host, port: Number(port) });
  console.log(`[zh] upstream: CONNECT via ${host}:${port}`);
}

function upstreamRequest(method, urlPath, headers, body) {
  return new Promise((resolve, reject) => {
    const req = https.request(
      {
        host: UPSTREAM_HOST,
        port: UPSTREAM_PORT,
        method,
        path: urlPath,
        headers: { ...headers, host: UPSTREAM_HOST },
        agent: AGENT,
      },
      resolve,
    );
    req.once('error', reject);
    req.setTimeout(30000, () => req.destroy(new Error('upstream timeout')));
    if (body && body.length) req.write(body);
    req.end();
  });
}

// ------------------------------------------------------------------- caching

function cachePathFor(urlPath) {
  const clean = decodeURIComponent(urlPath.split('?')[0]).replace(/^\/+/, '');
  const safe = clean.split('/').filter((s) => s && s !== '..' && s !== '.').join(path.sep);
  return path.join(CACHE_DIR, safe);
}

function readCache(urlPath) {
  const p = cachePathFor(urlPath);
  try {
    return { path: p, body: fs.readFileSync(p) };
  } catch {
    return null;
  }
}

function writeCache(urlPath, body) {
  const p = cachePathFor(urlPath);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, body);
  return p;
}

// ------------------------------------------------------------------- helpers

const REWRITABLE = /\.(?:m?js)$/i;

function decompress(buf, encoding) {
  const enc = (encoding || '').toLowerCase();
  try {
    if (enc.includes('br')) return zlib.brotliDecompressSync(buf);
    if (enc.includes('gzip')) return zlib.gunzipSync(buf);
    if (enc.includes('deflate')) return zlib.inflateSync(buf);
  } catch {
    return null;
  }
  return buf;
}

async function collect(stream, limit = 24 * 1024 * 1024) {
  const chunks = [];
  let size = 0;
  for await (const c of stream) {
    size += c.length;
    if (size > limit) throw new Error('upstream body too large');
    chunks.push(c);
  }
  return Buffer.concat(chunks);
}

const HOP = new Set(['connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
  'te', 'trailer', 'transfer-encoding', 'upgrade', 'content-length', 'content-encoding']);

function forwardHeaders(src) {
  const out = {};
  for (const [k, v] of Object.entries(src)) {
    const key = k.toLowerCase();
    if (k.startsWith(':')) continue;
    if (HOP.has(key)) continue;
    // The upstream must see its own Host, never our loopback authority.
    // Sending Host: 127.0.0.1:5175 makes CloudFront answer 403.
    if (key === 'host') continue;
    out[key] = v;
  }
  // Same reason: present the upstream origin so server-side origin checks pass.
  const upstreamOrigin = `https://${UPSTREAM_HOST}`;
  if (out.origin) out.origin = out.origin.replace(/^https?:\/\/[^/]+/i, upstreamOrigin);
  if (out.referer) out.referer = out.referer.replace(/^https?:\/\/[^/]+/i, upstreamOrigin);
  return out;
}

const stats = { requests: 0, cacheHits: 0, upstream: 0, rewrites: 0, rewrittenAssets: 0, errors: 0 };

// --------------------------------------------------------------------- server

function send(res, status, headers, body) {
  res.writeHead(status, headers);
  res.end(body);
}

async function handleAsset(req, res, urlPath) {
  const cached = readCache(urlPath);
  let body;
  let source;
  if (cached) {
    stats.cacheHits++;
    body = cached.body;
    source = 'cache';
  } else {
    if (OFFLINE || STATIC_ONLY) {
      stats.errors++;
      send(res, 502, { 'content-type': 'text/plain' }, `not cached: ${urlPath}\n`);
      return;
    }
    const up = await upstreamRequest('GET', urlPath, {
      accept: req.headers.accept || '*/*',
      'accept-encoding': 'br, gzip, deflate',
      'user-agent': req.headers['user-agent'] || 'devin-zh-proxy',
    });
    if (up.statusCode !== 200) {
      up.resume();
      stats.errors++;
      send(res, up.statusCode || 502, { 'content-type': 'text/plain' }, 'upstream error\n');
      return;
    }
    stats.upstream++;
    const raw = await collect(up);
    const plain = decompress(raw, up.headers['content-encoding']);
    if (!plain) {
      stats.errors++;
      send(res, 502, { 'content-type': 'text/plain' }, 'decode failed\n');
      return;
    }
    body = plain;
    source = 'upstream';
    // The cache mirrors upstream verbatim.  Rewriting happens at serve time so
    // that (a) the cached bytes stay a faithful reference for diagnostics and
    // (b) a translation can never be applied twice.
    if (!OFFLINE && !STATIC_ONLY) {
      try {
        writeCache(urlPath, body);
      } catch (e) {
        console.log(`[zh] cache write failed for ${urlPath.split('?')[0]}: ${e.code || e.message}`);
      }
    }
  }

  let hits = 0;
  if (REWRITABLE.test(urlPath)) {
    const r = rewrite(body.toString('utf8'));
    hits = r.hits;
    if (hits) {
      stats.rewrites += hits;
      stats.rewrittenAssets++;
      body = Buffer.from(r.text, 'utf8');
    }
  }
  const type = urlPath.endsWith('.css') ? 'text/css; charset=utf-8' : 'text/javascript; charset=utf-8';
  send(res, 200, {
    'content-type': type,
    'content-length': body.length,
    'cache-control': 'no-store',
    'x-zh-source': source,
    'x-zh-rewrites': String(hits),
  }, body);
}

const server = http.createServer((req, res) => {
  stats.requests++;
  const url = req.url || '/';

  if (url.startsWith('/__zh/health')) {
    send(res, 200, { 'content-type': 'application/json' }, JSON.stringify({
      ok: true, dict: ENTRIES.length, cache: CACHE_DIR, offline: OFFLINE, stats,
    }));
    return;
  }

  if (url.startsWith('/__zh/keys')) {
    try {
      const report = coverageReport();
      send(res, 200, { 'content-type': 'application/json' }, JSON.stringify({
        dict: ENTRIES.length, ...report,
      }, null, 2));
    } catch (e) {
      send(res, 500, { 'content-type': 'application/json' }, JSON.stringify({ error: e.message }));
    }
    return;
  }

  const urlPath = url.split('?')[0];

  if (urlPath.startsWith('/assets/')) {
    handleAsset(req, res, urlPath).catch((e) => {
      stats.errors++;
      console.log(`[zh] asset error ${urlPath}: ${e.code || e.message}`);
      if (!res.headersSent) send(res, 502, { 'content-type': 'text/plain' }, 'proxy error\n');
    });
    return;
  }

  if (OFFLINE || STATIC_ONLY) {
    send(res, 502, { 'content-type': 'text/plain' }, 'offline mode: only /assets/* is served\n');
    return;
  }

  // Everything else (routes, /api/*, SSE, downloads) is a transparent live
  // passthrough. Nothing is buffered, cached or inspected.
  const up = upstreamRequest(req.method, url, forwardHeaders(req.headers));
  up.then((upRes) => {
    stats.upstream++;
    const headers = {};
    for (const [k, v] of Object.entries(upRes.headers)) {
      if (k.toLowerCase() === 'transfer-encoding') continue;
      headers[k] = v;
    }
    res.writeHead(upRes.statusCode || 502, headers);
    upRes.pipe(res);
    upRes.once('error', () => res.destroy());
  }).catch((e) => {
    stats.errors++;
    console.log(`[zh] upstream error ${urlPath}: ${e.code || e.message}`);
    if (!res.headersSent) send(res, 502, { 'content-type': 'text/plain' }, 'upstream unavailable\n');
  });
});

// WebSocket / SSE upgrades are tunnelled untouched.
server.on('upgrade', (req, clientSocket, head) => {
  if (OFFLINE || STATIC_ONLY || !AGENT) {
    clientSocket.destroy();
    return;
  }
  const target = `${UPSTREAM_HOST}:${UPSTREAM_PORT}`;
  const creq = http.request({
    host: AGENT.proxy.host, port: AGENT.proxy.port, method: 'CONNECT', path: target,
    headers: { host: target }, timeout: 15000,
  });
  creq.once('connect', (r, socket) => {
    if (r.statusCode !== 200) {
      socket.destroy();
      clientSocket.destroy();
      return;
    }
    const tlsSocket = tls.connect({ socket, servername: UPSTREAM_HOST }, () => {
      const lines = [`${req.method} ${req.url} HTTP/1.1`];
      for (const [k, v] of Object.entries(req.headers)) lines.push(`${k}: ${v}`);
      tlsSocket.write(lines.join('\r\n') + '\r\n\r\n');
      if (head && head.length) tlsSocket.write(head);
      clientSocket.pipe(tlsSocket);
      tlsSocket.pipe(clientSocket);
    });
    tlsSocket.once('error', () => clientSocket.destroy());
  });
  creq.once('error', () => clientSocket.destroy());
  creq.end();
});

loadDict();
await resolveAgent();
fs.mkdirSync(CACHE_DIR, { recursive: true });
server.listen(PORT, '127.0.0.1', () => {
  console.log(`[zh] listening http://127.0.0.1:${PORT}  (cache: ${CACHE_DIR})`);
  if (OFFLINE) console.log('[zh] offline mode: upstream disabled');
});

for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, () => {
    console.log(`[zh] shutdown  stats=${JSON.stringify(stats)}`);
    server.close(() => process.exit(0));
    setTimeout(() => process.exit(0), 1500);
  });
}
