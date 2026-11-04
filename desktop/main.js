'use strict';
// VocalRender Studio — Windows desktop shell (Electron main process).
// The UI is the same index.html as the web version (copied into app/ by scripts/sync-web.js);
// this file adds the Windows 11 window chrome, native file dialogs and network access for the render service.

const { app, BrowserWindow, ipcMain, dialog, net, shell, nativeTheme, Menu, systemPreferences, session } = require('electron');
const path = require('path');
const fs = require('fs/promises');
const os = require('os');

const APP_ID = 'com.wenbo1188.vocalrenderstudio';
const IS_WIN = process.platform === 'win32';
const TITLEBAR_HEIGHT = 44;

let win = null;
let allowClose = false;
let closeAckTimer = null;
let pendingOpenPath = null;

// Mica needs Windows 11 22H2 (build 22621) or later; older systems get a solid background.
const MICA = IS_WIN && parseInt(os.release().split('.')[2] || '0', 10) >= 22621;

function accentHex() {
  if (!IS_WIN) return null;
  try { return '#' + systemPreferences.getAccentColor().slice(0, 6); } catch { return null; }
}
function solidBackground() { return nativeTheme.shouldUseDarkColors ? '#202020' : '#f3f3f3'; }
function titleBarOverlay() {
  return { color: '#00000000', symbolColor: nativeTheme.shouldUseDarkColors ? '#ffffff' : '#1b1b1b', height: TITLEBAR_HEIGHT };
}
function projectArg(argv) {
  return argv.slice(1).find(a => !a.startsWith('-') && /\.(vrproj|json|mid|midi|kar)$/i.test(a)) || null;
}
const safeName = n => String(n || '未命名').replace(/[\\/:*?"<>|]/g, '_').slice(0, 120);

async function readProject(p) {
  if (/\.(mid|midi|kar)$/i.test(p)) { // MIDI is binary: the page imports it
    const buf = await fs.readFile(p);
    return { path: p, name: path.basename(p), b64: buf.toString('base64') };
  }
  const text = await fs.readFile(p, 'utf8');
  return { path: p, name: path.basename(p), text };
}
async function sendOpen(p) {
  if (!win) return;
  try {
    const f = await readProject(p);
    app.addRecentDocument(p);
    win.webContents.send('vr:open-file', f);
  } catch (err) {
    dialog.showErrorBox('无法打开文件', `${p}\n\n${err.message || err}`);
  }
}

function createWindow() {
  const opts = {
    width: 1440, height: 900, minWidth: 1200, minHeight: 700,
    show: false,
    title: 'VocalRender Studio',
    icon: path.join(__dirname, 'build', IS_WIN ? 'icon.ico' : 'icon.png'),
    backgroundColor: MICA ? '#00000000' : solidBackground(),
    titleBarStyle: 'hidden',
    titleBarOverlay: titleBarOverlay(),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      spellcheck: false,
    },
  };
  if (MICA) opts.backgroundMaterial = 'mica';
  win = new BrowserWindow(opts);

  win.once('ready-to-show', () => win.show());
  win.loadFile(path.join(__dirname, 'app', 'index.html'));

  win.webContents.on('did-finish-load', () => {
    if (pendingOpenPath) { const p = pendingOpenPath; pendingOpenPath = null; sendOpen(p); }
  });

  // Ask the page whether there are unsaved changes before closing.
  win.on('close', e => {
    if (allowClose) return;
    e.preventDefault();
    win.webContents.send('vr:close-request');
    clearTimeout(closeAckTimer);
    // If the page does not answer (hung or crashed), close anyway.
    closeAckTimer = setTimeout(() => { allowClose = true; win && win.close(); }, 2000);
  });
  win.on('closed', () => { win = null; });

  if (!app.isPackaged) {
    win.webContents.on('before-input-event', (e, input) => {
      if (input.type === 'keyDown' && (input.key === 'F12' || (input.control && input.shift && input.key.toLowerCase() === 'i'))) {
        win.webContents.toggleDevTools();
      }
    });
  }
}

/* ---------- IPC ---------- */
ipcMain.on('vr:info', e => {
  e.returnValue = { version: app.getVersion(), platform: process.platform, mica: MICA, accent: accentHex() };
});

ipcMain.on('vr:close-ack', () => clearTimeout(closeAckTimer));
ipcMain.on('vr:close-reply', (_e, ok) => {
  clearTimeout(closeAckTimer);
  if (ok && win) { allowClose = true; win.close(); }
});

// Render-service requests go through Chromium's network stack in the main process,
// so the service does not need to send CORS headers.
ipcMain.handle('vr:request', async (_e, req) => {
  const url = new URL(String(req && req.url));
  if (!/^https?:$/.test(url.protocol)) throw new Error('服务地址只支持 http 或 https');
  const init = { method: req.method || 'GET', headers: req.headers || {} };
  if (!['GET', 'HEAD'].includes(init.method)) {
    if (req.bodyB64 != null) init.body = Buffer.from(req.bodyB64, 'base64'); // binary bodies, e.g. the reference-audio upload
    else if (req.body != null) init.body = req.body;
  }
  const res = await net.fetch(url.toString(), init);
  const body = Buffer.from(await res.arrayBuffer());
  return { status: res.status, statusText: res.statusText, headers: Object.fromEntries(res.headers.entries()), body: body.toString('base64') };
});

ipcMain.handle('vr:save', async (_e, o) => {
  const isWav = o.kind === 'wav';
  let target = o.path || null;
  if (!target) {
    const r = await dialog.showSaveDialog(win, {
      title: isWav ? '导出音频' : '保存工程',
      defaultPath: path.join(app.getPath(isWav ? 'music' : 'documents'), safeName(o.defaultName)),
      filters: isWav ? [{ name: 'WAV 音频', extensions: ['wav'] }] : [{ name: 'VocalRender 工程', extensions: ['vrproj'] }],
    });
    if (r.canceled || !r.filePath) return null;
    target = r.filePath;
  }
  const d = o.data;
  const buf = typeof d === 'string' ? Buffer.from(d, 'utf8')
    : ArrayBuffer.isView(d) ? Buffer.from(d.buffer, d.byteOffset, d.byteLength)
    : d instanceof ArrayBuffer ? Buffer.from(d)
    : Buffer.from(Object.values(d || {}));
  await fs.writeFile(target, buf);
  if (!isWav) app.addRecentDocument(target);
  return { path: target, name: path.basename(target) };
});

ipcMain.handle('vr:open', async () => {
  const r = await dialog.showOpenDialog(win, {
    title: '打开工程或乐谱',
    defaultPath: app.getPath('documents'),
    properties: ['openFile'],
    filters: [
      { name: 'VocalRender 工程或乐谱', extensions: ['vrproj', 'json', 'mid', 'midi', 'kar'] },
      { name: 'VocalRender 工程', extensions: ['vrproj'] },
      { name: 'MIDI', extensions: ['mid', 'midi', 'kar'] },
      { name: 'JSON 乐谱 / 转写', extensions: ['json', 'txt'] },
    ],
  });
  if (r.canceled || !r.filePaths[0]) return null;
  app.addRecentDocument(r.filePaths[0]);
  return readProject(r.filePaths[0]);
});

/* ---------- app lifecycle ---------- */
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', (_e, argv) => {
    if (!win) return;
    if (win.isMinimized()) win.restore();
    win.focus();
    const p = projectArg(argv);
    if (p) sendOpen(p);
  });

  if (IS_WIN) app.setAppUserModelId(APP_ID);
  pendingOpenPath = projectArg(process.argv);

  app.whenReady().then(() => {
    Menu.setApplicationMenu(null); // the app draws its own menus inside the title bar
    session.defaultSession.setPermissionRequestHandler((_wc, _perm, cb) => cb(false));
    createWindow();

    nativeTheme.on('updated', () => {
      if (!win) return;
      win.setTitleBarOverlay(titleBarOverlay());
      if (!MICA) win.setBackgroundColor(solidBackground());
    });
    if (IS_WIN) {
      systemPreferences.on('accent-color-changed', (_e, c) => {
        if (win) win.webContents.send('vr:accent', '#' + String(c).slice(0, 6));
      });
    }
  });

  // External links open in the default browser; the app window never navigates away.
  app.on('web-contents-created', (_e, wc) => {
    wc.setWindowOpenHandler(({ url }) => {
      if (/^https?:\/\//i.test(url)) shell.openExternal(url);
      return { action: 'deny' };
    });
    wc.on('will-navigate', (ev, url) => {
      ev.preventDefault();
      if (/^https?:\/\//i.test(url)) shell.openExternal(url);
    });
  });

  app.on('window-all-closed', () => app.quit());
}
