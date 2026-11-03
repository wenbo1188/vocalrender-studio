'use strict';
// Bridge between the page and the main process. Exposes window.vrDesktop; the page checks for it
// to switch on the Windows skin, native file dialogs, WAV export and main-process networking.

const { contextBridge, ipcRenderer, webUtils } = require('electron');

const info = ipcRenderer.sendSync('vr:info');

let closeHandler = null;
ipcRenderer.on('vr:close-request', async () => {
  ipcRenderer.send('vr:close-ack');
  let ok = true;
  try { if (closeHandler) ok = await closeHandler(); } catch { ok = true; }
  ipcRenderer.send('vr:close-reply', !!ok);
});

const openListeners = [];
let pendingFile = null;
ipcRenderer.on('vr:open-file', (_e, f) => {
  if (openListeners.length) openListeners.forEach(cb => cb(f));
  else pendingFile = f;
});

const accentListeners = [];
ipcRenderer.on('vr:accent', (_e, hex) => accentListeners.forEach(cb => cb(hex)));

function toBytes(d) {
  if (typeof d === 'string' || d instanceof Uint8Array) return d;
  if (ArrayBuffer.isView(d)) return new Uint8Array(d.buffer, d.byteOffset, d.byteLength);
  if (d instanceof ArrayBuffer) return new Uint8Array(d);
  return new Uint8Array(Object.values(d || {}));
}

contextBridge.exposeInMainWorld('vrDesktop', {
  info,
  request: req => ipcRenderer.invoke('vr:request', req),
  saveFile: o => ipcRenderer.invoke('vr:save', { kind: o.kind, path: o.path || null, defaultName: o.defaultName, data: toBytes(o.data) }),
  openFile: () => ipcRenderer.invoke('vr:open'),
  pathForFile: file => { try { return webUtils.getPathForFile(file) || null; } catch { return null; } },
  onCloseRequest: cb => { closeHandler = cb; },
  onOpenFile: cb => {
    openListeners.push(cb);
    if (pendingFile) { const f = pendingFile; pendingFile = null; cb(f); }
  },
  onAccentChange: cb => { accentListeners.push(cb); },
});
