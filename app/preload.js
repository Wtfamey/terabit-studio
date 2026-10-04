/**
 * The one bridge between the shell and the web UI.
 *
 * `contextIsolation` is on and `nodeIntegration` is off, so the page gets
 * exactly this object and nothing else. The surface is deliberately the one
 * the UI already calls (see frontend/src/pages/Workspace.tsx) plus the state
 * and diagnostics the first-run screen needs. Every method is an invoke --
 * the renderer never gets a path to the filesystem or to child processes.
 */
'use strict';

const { contextBridge, ipcRenderer } = require('electron');

function subscribe(channel, cb) {
  const listener = (_event, payload) => {
    try {
      cb(payload);
    } catch (err) {
      // A throwing renderer callback must not take the main process down.
      console.error('terabit listener error:', err);
    }
  };
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
}

contextBridge.exposeInMainWorld('terabit', {
  // The backend origin the renderer should use. In a packaged build the UI is
  // served BY that backend, so this is usually the window's own origin.
  baseUrl: () => ipcRenderer.invoke('terabit:base-url'),
  // First-run environment report: model runtime reachable, model pulled, UI
  // built, storage writable, and the human-readable issues list.
  env: () => ipcRenderer.invoke('terabit:env'),
  bootLog: () => ipcRenderer.invoke('terabit:boot-log'),
  state: () => ipcRenderer.invoke('terabit:state'),
  version: () => ipcRenderer.invoke('terabit:version'),
  retry: () => ipcRenderer.invoke('terabit:retry'),
  // The native folder picker: the one capability a browser does not have, and
  // the reason the desktop shell earns its keep.
  chooseFolder: () => ipcRenderer.invoke('terabit:choose-folder'),
  openExternal: (url) => ipcRenderer.invoke('terabit:open-external', url),
  openLogs: () => ipcRenderer.invoke('terabit:open-logs'),
  // Settings > Diagnostics: the shell owns the runtime versions, and opening
  // a folder is a shell capability because the renderer has no filesystem.
  versions: () => ipcRenderer.invoke('terabit:versions'),
  openPath: (target) => ipcRenderer.invoke('terabit:open-path', target),
  onBootLog: (cb) => subscribe('terabit:boot-log', cb),
  onState: (cb) => subscribe('terabit:state', cb),
});
