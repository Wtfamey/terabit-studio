/**
 * Terabit Studio -- Electron main process.
 *
 * The shell exists for four things a browser cannot do:
 *   1. start the local model backend and supervise it (boot.js owns the how);
 *   2. open a real folder with the native picker, so "connect your project"
 *      is a button rather than a path typed into a text box;
 *   3. show a first-run screen that explains a broken environment in words a
 *      non-technical user can act on (Ollama missing, model not pulled, UI not
 *      built) instead of a blank window;
 *   4. keep everything on this machine -- no telemetry, no remote origin; the
 *      renderer is only ever loaded from 127.0.0.1.
 *
 * The app loads the UI from the BACKEND's origin. That is what makes the
 * production build work: frontend/src/config.ts uses relative API URLs when
 * built, so same-origin is the only configuration where no URL has to be
 * injected. Any free port is therefore fine -- nothing is hard-coded.
 */
'use strict';

const { app, BrowserWindow, dialog, ipcMain, Menu, shell } = require('electron');
const fs = require('fs');
const path = require('path');

const boot = require('./boot');

const DEV = process.argv.includes('--dev') || process.env.TERABIT_DEV === '1';
const SMOKE = process.argv.includes('--smoke');
const PREFERRED_PORT = Number(process.env.TERABIT_PORT || 8000);
const DEV_UI = process.env.TERABIT_UI_URL || 'http://localhost:5173';
const IS_PACKAGED = app.isPackaged;

const state = {
  phase: 'booting',           // booting | ready | failed
  message: 'Starting up...',
  base: '',
  uiUrl: '',
  reused: false,
  env: null,
  model: null,
  child: null,
  log: new boot.BootLog(),
  startedAt: 0,
};

let firstRunWin = null;
let mainWin = null;
let quitting = false;

// ------------------------------------------------------------------ logging

function logDir() {
  const dir = path.join(app.getPath('userData'), 'logs');
  try {
    fs.mkdirSync(dir, { recursive: true });
  } catch { /* logging must never be the thing that breaks startup */ }
  return dir;
}

let logStream = null;
function toLogFile(line) {
  try {
    if (!logStream) {
      const file = path.join(logDir(), 'terabit.log');
      try {
        if (fs.existsSync(file) && fs.statSync(file).size > 5 * 1024 * 1024) {
          fs.renameSync(file, `${file}.1`);
        }
      } catch { /* rotation is best effort */ }
      logStream = fs.createWriteStream(file, { flags: 'a' });
    }
    logStream.write(`${new Date().toISOString()} ${line}\n`);
  } catch { /* best effort */ }
}

function note(line) {
  state.log.push(line);
  toLogFile(line);
  if (firstRunWin && !firstRunWin.isDestroyed()) {
    firstRunWin.webContents.send('terabit:boot-log', String(line));
  }
  if (!SMOKE) {
    // Mirror to the terminal that launched the app, for support and for
    // `electron . --dev` sessions.
    process.stdout.write(`${line}\n`);
  }
}

function setPhase(phase, message) {
  state.phase = phase;
  state.message = message;
  note(`[${phase}] ${message}`);
  if (firstRunWin && !firstRunWin.isDestroyed()) {
    firstRunWin.webContents.send('terabit:state', publicState());
  }
}

function publicState() {
  return {
    phase: state.phase,
    message: state.message,
    base: state.base,
    dev: DEV,
    reused: state.reused,
    version: app.getVersion(),
    env: state.env,
    model: state.model,
  };
}

// ------------------------------------------------------------------- windows

function harden(win) {
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/i.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (event, url) => {
    const allowed = [state.base, state.uiUrl].filter(Boolean);
    if (!allowed.some((a) => url.startsWith(a))) {
      event.preventDefault();
      if (/^https?:/i.test(url)) shell.openExternal(url);
    }
  });
}

function openFirstRun() {
  if (SMOKE) return null;  // --smoke exercises boot only, no windows
  if (firstRunWin && !firstRunWin.isDestroyed()) return firstRunWin;
  firstRunWin = new BrowserWindow({
    width: 760,
    height: 520,
    minWidth: 620,
    minHeight: 420,
    show: false,
    backgroundColor: '#0b0f1a',
    title: 'Terabit Studio',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  firstRunWin.once('ready-to-show', () => firstRunWin.show());
  firstRunWin.on('closed', () => {
    firstRunWin = null;
  });
  firstRunWin.loadFile(path.join(__dirname, 'first-run.html'));
  return firstRunWin;
}

function openMainWindow() {
  if (SMOKE) {
    note('[smoke] backend ready; window would open here');
    return null;
  }
  if (mainWin && !mainWin.isDestroyed()) {
    mainWin.loadURL(state.uiUrl);
    return mainWin;
  }
  mainWin = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 900,
    minHeight: 600,
    show: false,
    backgroundColor: '#0b0f1a',
    title: 'Terabit Studio',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  harden(mainWin);
  mainWin.once('ready-to-show', () => mainWin.show());
  mainWin.webContents.on('did-fail-load', (_e, code, desc, url) => {
    note(`[ui] failed to load ${url}: ${desc} (${code})`);
    setPhase('failed', `The interface could not be loaded (${desc}).`);
    openFirstRun();
  });
  mainWin.on('closed', () => {
    mainWin = null;
  });
  mainWin.loadURL(state.uiUrl);
  return mainWin;
}

// --------------------------------------------------------------- boot cycle

async function bootSequence() {
  state.phase = 'booting';
  state.startedAt = Date.now();
  state.reused = false;
  state.env = null;
  state.model = null;
  note(`Terabit Studio ${app.getVersion()} (${IS_PACKAGED ? 'packaged' : 'source'}, ` +
    `${DEV ? 'dev' : 'production'} UI)`);
  openFirstRun();
  setPhase('booting', 'Looking for a local backend...');

  // 1. Reuse a healthy backend before starting another one. Developers almost
  //    always have one running, and two backends fighting over Ollama is the
  //    kind of bug that looks like a model problem.
  const preferred = `http://127.0.0.1:${PREFERRED_PORT}`;
  const existing = await boot.isHealthy(preferred, 900);
  if (existing.ok) {
    state.base = preferred;
    state.reused = true;
    note(`Reusing the backend already running on ${preferred}`);
  } else {
    // 2. Pick a port. In dev the Vite UI hard-codes :8000 as its API base, so
    //    there we need that exact port; a packaged app is served by the
    //    backend and can take any free one.
    let port;
    try {
      port = await boot.pickPort(PREFERRED_PORT);
    } catch (err) {
      setPhase('failed', `No free port could be found: ${err.message}`);
      return;
    }
    if (DEV && port !== PREFERRED_PORT) {
      setPhase('failed', `Port ${PREFERRED_PORT} is in use by something else, and ` +
        'the development UI expects the backend there. Stop it and retry.');
      return;
    }

    const spec = boot.locateBackend({
      appRoot: __dirname,
      resourcesPath: process.resourcesPath,
      isPackaged: IS_PACKAGED,
    });
    if (!spec) {
      setPhase('failed',
        'The local backend was not found next to the app. A packaged build ' +
        'must ship resources/backend; when running from source, keep the ' +
        'app/ and backend/ folders together.');
      return;
    }
    // A full build carries the model weights and the llama.cpp server inside
    // resources/. They are handed to the backend as ABSOLUTE env paths, and
    // the model server gets a port chosen at launch: the app then works from
    // any folder, unpacked anywhere, even beside an Ollama that owns 11434.
    let extraEnv = {};
    const runtime = boot.findBundledRuntime({
      resourcesPath: process.resourcesPath,
      appRoot: __dirname,
    });
    if (runtime.found) {
      let modelPort = null;
      try {
        modelPort = await boot.pickPort(18134);
      } catch { /* fall back to the .env/default port */ }
      extraEnv = boot.bundledRuntimeEnv(runtime, modelPort);
      state.model = {
        found: true, path: runtime.model, server: runtime.llamaServer,
        sizeGb: runtime.sizeGb, port: modelPort,
      };
      note(`Bundled model: ${runtime.model} (${runtime.sizeGb} GB) serving via ` +
        `${path.basename(runtime.llamaServer)}${modelPort ? ` on port ${modelPort}` : ''}`);
    } else {
      state.model = { found: false };
      note('This build ships no model runtime; expecting a local one (Ollama).');
    }

    note(`Starting backend (${spec.kind}) on port ${port}...`);
    setPhase('booting', 'Starting the local backend...');
    try {
      // The sink is note(), so backend output lands in the ring buffer, the
      // first-run window and the log file in one hop -- attaching a second
      // stdout listener here would duplicate every line.
      state.child = boot.startBackend(spec, {
        port,
        log: { push: (line) => note(String(line)) },
        extraEnv,
      });
    } catch (err) {
      setPhase('failed', err.message);
      return;
    }
    state.base = `http://127.0.0.1:${port}`;
    state.child.on('exit', (code) => {
      if (!quitting && state.phase !== 'ready') {
        setPhase('failed', `The backend stopped during startup (exit code ${code}).`);
      }
    });
  }

  // 3. Wait for health. First boot after an install can take a while (the
  //    model has to be located and paged in), so the wait is long and the
  //    message counts the seconds instead of pretending to be stuck.
  const wait = await boot.waitForHealth(state.base, {
    timeoutMs: 180000,
    child: state.child,
    onTick: (elapsed) => {
      if (elapsed % 3000 < 700) {
        setPhase('booting', `Waiting for the local model runtime... ${Math.round(elapsed / 1000)}s`);
      }
    },
  });
  if (!wait.ok) {
    setPhase('failed',
      `The backend did not become ready: ${wait.error}. ` +
      'The log below says what it was doing; retry after fixing the cause.');
    return;
  }
  note(`Backend ready in ${(wait.elapsedMs / 1000).toFixed(1)}s at ${state.base}`);
  setPhase('booting', 'Checking the model runtime...');

  // 4. Environment report. This is what turns "blank window" into "Ollama is
  //    not installed" -- it never blocks the app from opening, it reports.
  state.env = await boot.probeEnv(state.base);
  if (state.env) {
    if (state.env.ok) {
      note(`Environment ok: model "${state.env.runtime && state.env.runtime.model}" ready`);
      if (state.env.runtime && state.env.runtime.loaded && state.env.runtime.loaded.length) {
        note(`Loaded: ${state.env.runtime.loaded.join(', ')}`);
      }
    } else {
      note(`Environment issues: ${(state.env.issues || []).join(' | ')}`);
    }
  } else {
    note('Environment report unavailable; continuing.');
  }

  // 5. Open the app. Same origin as the backend, so the built UI's relative
  //    API URLs just work.
  // In dev the UI is the Vite server (its API base is hard-coded to :8000,
  // which is why the dev path insists on that port); in a packaged build the
  // backend serves the built UI itself, so same-origin relative URLs work.
  state.uiUrl = DEV ? DEV_UI : `${state.base}/`;
  setPhase('ready', state.env && !state.env.ok
    ? 'Ready -- with first-run issues to review'
    : 'Ready');
  openMainWindow();
  if (firstRunWin && !firstRunWin.isDestroyed() && (!state.env || state.env.ok)) {
    firstRunWin.close();
  }
}

async function retry() {
  if (state.child) {
    await boot.stopBackend(state.child);
    state.child = null;
  }
  await bootSequence();
}

// ---------------------------------------------------------------------- IPC

function registerIpc() {
  ipcMain.handle('terabit:base-url', () => state.base);
  ipcMain.handle('terabit:version', () => app.getVersion());
  ipcMain.handle('terabit:state', () => publicState());
  ipcMain.handle('terabit:boot-log', () => state.log.lines.join('\n'));
  ipcMain.handle('terabit:env', async () => {
    state.env = await boot.probeEnv(state.base);
    return state.env;
  });
  ipcMain.handle('terabit:retry', async () => {
    await retry();
    return publicState();
  });
  ipcMain.handle('terabit:open-logs', async () => {
    const dir = logDir();
    await shell.openPath(dir);
    return dir;
  });
  ipcMain.handle('terabit:versions', () => ({
    app: app.getVersion(),
    electron: process.versions.electron || '',
    chrome: process.versions.chrome || '',
    node: process.versions.node || '',
    v8: process.versions.v8 || '',
    platform: `${process.platform} ${process.arch}`,
    packaged: IS_PACKAGED,
  }));
  ipcMain.handle('terabit:open-path', async (_e, target) => {
    // The renderer has no filesystem access, so "open the data folder" is a
    // shell capability -- and therefore a path a compromised renderer could
    // abuse. Only folders this app owns, or the OS temp dir it may fall back
    // to, are allowed through.
    if (typeof target !== 'string' || !target) {
      throw new Error('A folder path is required.');
    }
    const resolved = path.resolve(target);
    const lower = resolved.toLowerCase();
    const roots = [app.getPath('userData'), app.getPath('temp'), process.resourcesPath]
      .filter(Boolean)
      .map((r) => path.resolve(String(r)).toLowerCase());
    try {
      roots.push(path.dirname(app.getAppPath()).toLowerCase());
    } catch { /* app path is always available, but never let it break the call */ }
    const allowed = roots.some((root) => lower === root || lower.startsWith(root + path.sep));
    if (!allowed) {
      throw new Error('Refused: that path is outside the folders this app manages.');
    }
    if (!fs.existsSync(resolved)) {
      throw new Error('That folder does not exist yet.');
    }
    const failure = await shell.openPath(resolved);
    if (failure) throw new Error(failure);
    return resolved;
  });
  ipcMain.handle('terabit:open-external', async (_e, url) => {
    if (typeof url !== 'string' || !/^https?:\/\//i.test(url)) {
      throw new Error('Only http(s) URLs can be opened externally.');
    }
    await shell.openExternal(url);
    return true;
  });
  ipcMain.handle('terabit:choose-folder', async () => {
    // Awaited and returned. The first version of this handler was
    // fire-and-forget, so it always resolved `undefined` and the picker could
    // never have worked -- it is the one flow the shell exists for.
    const win = mainWin && !mainWin.isDestroyed() ? mainWin : undefined;
    const result = await dialog.showOpenDialog(win, {
      title: 'Open a project folder',
      buttonLabel: 'Open project',
      properties: ['openDirectory', 'createDirectory'],
    });
    if (result.canceled || !result.filePaths.length) {
      return { canceled: true };
    }
    return { canceled: false, path: result.filePaths[0] };
  });
}

// --------------------------------------------------------------------- menu

/** Navigate the main window to a route, opening one if needed. Routes are
 *  same-origin with the backend, so this is just a loadURL -- no reload of the
 *  stack, no lost state beyond what the SPA keeps anyway. */
function openRoute(route) {
  const target = `${state.base}${route}`;
  if (mainWin && !mainWin.isDestroyed()) {
    mainWin.loadURL(target);
  } else if (state.phase === 'ready') {
    openMainWindow();
    if (mainWin) mainWin.loadURL(target);
  } else {
    openFirstRun();
  }
}

function buildMenu() {
  const template = [
    ...(process.platform === 'darwin' ? [{ role: 'appMenu' }] : []),
    {
      label: 'File',
      submenu: [
        {
          label: 'Open Project Folder...',
          accelerator: 'CmdOrCtrl+O',
          // Land on the workspace screen, which owns the folder flow (it
          // calls the same native picker through window.terabit).
          click: () => openRoute('/workspace'),
        },
        { type: 'separator' },
        {
          label: 'Settings…',
          accelerator: 'CmdOrCtrl+,',
          click: () => openRoute('/settings'),
        },
        { type: 'separator' },
        { role: process.platform === 'darwin' ? 'close' : 'quit' },
      ],
    },
    {
      label: 'View',
      submenu: [
        { role: 'reload' },
        { role: 'forceReload' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' },
      ],
    },
    {
      label: 'Help',
      submenu: [
        {
          label: 'Environment Check',
          click: () => {
            openFirstRun();
            if (firstRunWin) firstRunWin.show();
            state.env = null;
            state.phase = 'ready';
            if (firstRunWin && !firstRunWin.isDestroyed()) {
              firstRunWin.webContents.send('terabit:state', publicState());
            }
            boot.probeEnv(state.base).then((env) => {
              state.env = env;
              if (firstRunWin && !firstRunWin.isDestroyed()) {
                firstRunWin.webContents.send('terabit:state', publicState());
              }
            });
          },
        },
        {
          label: 'Open Log Folder',
          click: () => shell.openPath(logDir()),
        },
        {
          label: 'Keyboard Shortcuts',
          click: () => openRoute('/settings'),
        },
        {
          label: 'About',
          click: () => {
            dialog.showMessageBox({
              type: 'info',
              title: 'Terabit Studio',
              message: `Terabit Studio ${app.getVersion()}`,
              detail: 'Local-first AI app builder. Everything runs on this machine.',
            });
          },
        },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

// -------------------------------------------------------------------- smoke

async function runSmoke() {
  const started = Date.now();
  try {
    await bootSequence();
  } catch (err) {
    state.phase = 'failed';
    state.message = err.message;
  }
  const payload = {
    phase: state.phase,
    message: state.message,
    base: state.base,
    reused: state.reused,
    seconds: Math.round((Date.now() - started) / 100) / 10,
    env_ok: state.env ? state.env.ok : null,
    issues: state.env ? state.env.issues : [],
  };
  process.stdout.write(`SMOKE ${JSON.stringify(payload)}\n`);
  await shutdown();
  app.exit(state.phase === 'ready' ? 0 : 1);
}

async function shutdown() {
  quitting = true;
  if (state.child) {
    await boot.stopBackend(state.child);
    state.child = null;
  }
}

// --------------------------------------------------------------------- main

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWin) {
      if (mainWin.isMinimized()) mainWin.restore();
      mainWin.focus();
    }
  });

  app.whenReady().then(async () => {
    if (SMOKE) {
      await runSmoke();
      return;
    }
    registerIpc();
    buildMenu();
    bootSequence().catch((err) => setPhase('failed', String(err && err.message || err)));
  });

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0 && !SMOKE) {
      bootSequence().catch(() => { /* reported in the first-run window */ });
    }
  });

  app.on('window-all-closed', () => {
    app.quit();
  });

  app.on('before-quit', (event) => {
    if (state.child && !quitting) {
      event.preventDefault();
      shutdown().then(() => app.quit());
    }
  });
}
