'use strict';
// Copies the web app (../../index.html) into desktop/app/ for packaging.
// The desktop copy drops the Google Fonts links (the Windows skin uses system fonts, so the app works offline)
// and adds a Content-Security-Policy that blocks any network access from the page itself.

const fs = require('fs');
const path = require('path');

const src = path.resolve(__dirname, '..', '..', 'index.html');
const outDir = path.resolve(__dirname, '..', 'app');
const out = path.join(outDir, 'index.html');

let html = fs.readFileSync(src, 'utf8');

html = html
  .replace(/\s*<link rel="preconnect"[^>]*>/g, '')
  .replace(/\s*<link rel="stylesheet" href="https:\/\/fonts\.googleapis\.com[^>]*>/g, '');

const csp = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  "media-src 'self' data: blob:",
  "connect-src 'self' data: blob:",
  "worker-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
].join('; ');

const charset = '<meta charset="utf-8">';
if (!html.includes(charset)) throw new Error('index.html is missing <meta charset="utf-8">');
html = html.replace(charset, `${charset}\n<meta http-equiv="Content-Security-Policy" content="${csp}">`);

fs.mkdirSync(outDir, { recursive: true });
fs.writeFileSync(out, html);
console.log(`synced ${path.relative(process.cwd(), src)} -> ${path.relative(process.cwd(), out)}`);
