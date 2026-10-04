/**
 * Backend lifecycle for the desktop shell -- pure Node, no Electron.
 *
 * Everything that makes the app start is here rather than in main.js, for one
 * reason: Electron cannot be unit-tested in CI, but this file can. `main.js`
 * is wiring, `boot.js` is behaviour, and `test_boot.js` runs the whole thing
 * for real -- spawn the backend on a free port, wait for health, ask for the
 * environment report, shut it down -- without opening a window.
 *
 * A packaged build lands on a machine we know nothing about, so the rules are:
 *   * reuse a backend that is already healthy on the preferred port instead of
 *     spawning a second one (developers usually have one running);
 *   * never hard-code the port -- the app is loaded FROM the backend origin,
 *     so any free port works;
 *   * a missing model runtime is a FIRST-RUN issue to report, not a crash:
 *     Ollama not installed, model not pulled, UI not built are all states the
 *     app must survive and explain.
 */
'use strict';

const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const http = require('http');
const net = require('net');
const path = require('path');

const LOG_RING = 400;

function stripAnsi(s) {
  // eslint-disable-next-line no-control-regex
  return String(s).replace(/\u001b\[[0-9;]*m/g, '');
}

/** Rolling boot log: the last N lines, which is what first-run and the log
 *  file both need. A bounded ring means a chatty model server can never grow
 *  the app's memory without limit. */
class BootLog {
  constructor(max = LOG_RING) {
    this.max = max;
    this.lines = [];
  }

  push(line) {
    for (const raw of String(line).split(/\r?\n/)) {
      const text = stripAnsi(raw).trimEnd();
      if (!text) continue;
      this.lines.push(text);
      if (this.lines.length > this.max) this.lines.splice(0, this.lines.length - this.max);
    }
    return this.lines;
  }

  text() {
    return this.lines.join('\n');
  }
}

function httpGetJson(url, timeoutMs = 2000) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        const body = Buffer.concat(chunks).toString('utf8');
        if (res.statusCode !== 200) {
          return reject(new Error(`HTTP ${res.statusCode}`));
        }
        try {
          resolve(JSON.parse(body));
        } catch (err) {
          reject(new Error(`not JSON: ${body.slice(0, 120)}`));
        }
      });
    });
    req.setTimeout(timeoutMs, () => req.destroy(new Error('timeout')));
    req.on('error', reject);
  });
}

/** Is a Terabit backend already answering on this base URL? */
async function isHealthy(base, timeoutMs = 1200) {
  try {
    const data = await httpGetJson(`${base}/api/health`, timeoutMs);
    return { ok: true, data };
  } catch (err) {
    return { ok: false, error: err.message };
  }
}

function portFree(port, host = '127.0.0.1') {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.once('error', () => resolve(false));
    srv.once('listening', () => srv.close(() => resolve(true)));
    srv.listen(port, host);
  });
}

/** Prefer the port a developer expects; fall back to any free one. */
async function pickPort(preferred) {
  if (preferred && await portFree(preferred)) return preferred;
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.once('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

/**
 * The self-contained runtime a full build ships: a llama.cpp server and the
 * model weights inside the app's resources, next to the backend.
 *
 * Paths are returned ABSOLUTE and the caller passes them to the backend as
 * environment variables -- deliberately not through the shipped .env. The
 * backend loads that file with override=True, and a relative path resolved
 * against a child process's working directory is exactly the kind of thing
 * that works on the build machine and fails on a user's (CreateProcess
 * resolves an executable relative to the *parent's* directory, not the
 * child's). Absolute paths cannot be wrong about where the app lives.
 */
function findBundledRuntime({ resourcesPath = null, appRoot = __dirname } = {}) {
  const exeName = process.platform === 'win32' ? 'llama-server.exe' : 'llama-server';
  const roots = [];
  if (resourcesPath) roots.push(resourcesPath);
  roots.push(path.join(appRoot, 'resources'));
  roots.push(appRoot);

  let llamaServer = '';
  let runtimeRoot = '';
  const models = [];
  for (const root of roots) {
    if (!llamaServer) {
      for (const candidate of [path.join(root, 'llama', exeName), path.join(root, exeName)]) {
        if (existsFile(candidate)) {
          llamaServer = candidate;
          runtimeRoot = candidate.includes(`${path.sep}llama${path.sep}`) ? path.join(root, 'llama') : root;
          break;
        }
      }
    }
    let entries = [];
    try {
      entries = fs.readdirSync(path.join(root, 'models'));
    } catch {
      entries = [];
    }
    for (const name of entries) {
      if (!/\.gguf$/i.test(name) || /\.part$/i.test(name)) continue;
      const full = path.join(root, 'models', name);
      let size = 0;
      try {
        size = fs.statSync(full).size;
      } catch {
        continue;
      }
      models.push({ path: full, name, bytes: size });
    }
  }
  models.sort((a, b) => b.bytes - a.bytes);
  // The fine-tune is the product; any other gguf in the folder is a fallback
  // (an upstream base a builder dropped in, or a previous model).
  const preferred = models.find((m) => /terabit-v3/i.test(m.name)) || models[0];
  const model = preferred ? preferred.path : '';
  return {
    found: Boolean(llamaServer && model),
    llamaServer,
    model,
    models,
    resources: runtimeRoot,
    sizeGb: preferred ? Math.round((preferred.bytes / 1024 ** 3) * 10) / 10 : 0,
  };
}

/** Environment the backend needs to serve from the bundled runtime. */
function bundledRuntimeEnv(runtime, modelPort) {
  if (!runtime || !runtime.found) return {};
  return {
    MODEL_PATH: runtime.model,
    LLAMA_SERVER_PATH: runtime.llamaServer,
    ...(modelPort ? { LLAMA_SERVER_PORT: String(modelPort), LLAMA_SERVER_HOST: '127.0.0.1' } : {}),
    TERABIT_BUNDLED_RUNTIME: '1',
  };
}

function pythonCandidates() {
  const explicit = process.env.TERABIT_PYTHON;
  if (explicit) return [{ cmd: explicit, args: [] }];
  if (process.platform === 'win32') {
    return [
      { cmd: 'python', args: [] },
      { cmd: 'py', args: ['-3'] },
      { cmd: 'python3', args: [] },
    ];
  }
  return [{ cmd: 'python3', args: [] }, { cmd: 'python', args: [] }];
}

function existsFile(p) {
  try {
    return fs.statSync(p).isFile();
  } catch {
    return false;
  }
}

/**
 * Where is the backend?
 *
 * Resolution order, most specific first:
 *   1. TERABIT_BACKEND -- a bundled executable, or a folder to look in.
 *   2. the packaged app's resources/backend (PyInstaller one-file or one-dir).
 *   3. the source tree next to this file (../backend with main.py) + a local
 *      Python. This is the developer path and it is also the honest fallback
 *      when a build shipped without its backend bundle.
 */
function locateBackend({ appRoot = __dirname, resourcesPath = null, isPackaged = false } = {}) {
  const exeName = process.platform === 'win32' ? 'terabit-backend.exe' : 'terabit-backend';
  const candidates = [];

  const explicit = process.env.TERABIT_BACKEND;
  if (explicit) {
    candidates.push(path.resolve(explicit));
    candidates.push(path.join(path.resolve(explicit), exeName));
  }
  if (resourcesPath) {
    candidates.push(path.join(resourcesPath, 'backend', exeName));
    candidates.push(path.join(resourcesPath, 'backend', 'terabit-backend', exeName));
    candidates.push(path.join(resourcesPath, 'backend'));
  }
  if (isPackaged) {
    candidates.push(path.join(process.resourcesPath || '', 'backend', exeName));
    candidates.push(path.join(process.resourcesPath || '', 'backend', 'terabit-backend', exeName));
  }
  const sourceDir = path.resolve(appRoot, '..', 'backend');
  candidates.push(sourceDir);

  for (const candidate of candidates) {
    if (!candidate) continue;
    if (existsFile(candidate) && /terabit-backend(\.exe)?$/.test(candidate)) {
      return { kind: 'bundled', cmd: candidate, args: [], cwd: path.dirname(candidate) };
    }
    if (fs.existsSync(candidate) && fs.statSync(candidate).isDirectory()) {
      const bundled = path.join(candidate, exeName);
      const bundledNested = path.join(candidate, 'terabit-backend', exeName);
      if (existsFile(bundled)) {
        return { kind: 'bundled', cmd: bundled, args: [], cwd: candidate };
      }
      if (existsFile(bundledNested)) {
        return { kind: 'bundled', cmd: bundledNested, args: [], cwd: path.dirname(bundledNested) };
      }
      if (existsFile(path.join(candidate, 'main.py'))) {
        return { kind: 'python', cwd: candidate };
      }
    }
  }
  return null;
}

/**
 * Which Python can actually run the backend?
 *
 * "python exists" is not the question -- the question is "python exists AND
 * can import uvicorn", so each candidate is probed with a real import. This
 * is the difference between a clear first-run message and a stack trace from
 * inside a child process nobody is watching.
 */
function resolvePython(cwd) {
  const errors = [];
  for (const { cmd, args } of pythonCandidates()) {
    const probe = spawnSync(cmd, [...args, '-c', 'import uvicorn, fastapi'], {
      cwd,
      encoding: 'utf8',
      timeout: 30000,
      windowsHide: true,
    });
    if (probe.status === 0) return { cmd, args, ok: true };
    const detail = (probe.stderr || probe.error?.message || `exit ${probe.status}`).trim();
    errors.push(`${cmd}${args.join(' ')}: ${detail.split('\n').pop()}`);
  }
  return { ok: false, errors };
}

function startBackend(spec, { port, log, extraEnv = {} } = {}) {
  if (!spec) throw new Error('No backend found to start.');
  let cmd = spec.cmd;
  let args = (spec.args || []).slice();
  if (spec.kind === 'python') {
    const py = resolvePython(spec.cwd);
    if (!py.ok) {
      const err = new Error(
        'Python with uvicorn/fastapi was not found, so the local backend cannot start.\n' +
        py.errors.map((e) => `  - ${e}`).join('\n'),
      );
      err.code = 'NO_PYTHON';
      throw err;
    }
    cmd = py.cmd;
    args = [...py.args, '-m', 'uvicorn', 'main:app',
      '--host', '127.0.0.1', '--port', String(port)];
  } else {
    args = [...args, '--host', '127.0.0.1', '--port', String(port)];
  }

  const child = spawn(cmd, args, {
    cwd: spec.cwd,
    windowsHide: true,
    env: {
      ...process.env,
      PYTHONUNBUFFERED: '1',
      PYTHONIOENCODING: 'utf-8',
      ...extraEnv,
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  if (log) {
    child.stdout.on('data', (d) => log.push(d.toString('utf8')));
    child.stderr.on('data', (d) => log.push(d.toString('utf8')));
  }
  return child;
}

function stopBackend(child, { timeoutMs = 4000 } = {}) {
  return new Promise((resolve) => {
    if (!child || child.exitCode !== null || child.signalCode) return resolve(false);
    let done = false;
    const finish = (killed) => {
      if (done) return;
      done = true;
      resolve(killed);
    };
    child.once('exit', () => finish(true));
    if (process.platform === 'win32' && child.pid) {
      // uvicorn may have spawned children; /T takes the tree, /F the process.
      spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true });
    } else {
      child.kill('SIGTERM');
    }
    setTimeout(() => {
      if (child.exitCode === null) {
        try { child.kill('SIGKILL'); } catch { /* already gone */ }
      }
      finish(true);
    }, timeoutMs).unref?.();
  });
}

async function waitForHealth(base, { timeoutMs = 120000, intervalMs = 600, child = null, onTick = null } = {}) {
  const started = Date.now();
  let lastError = 'not started';
  while (Date.now() - started < timeoutMs) {
    if (child && child.exitCode !== null) {
      return { ok: false, error: `backend exited with code ${child.exitCode}`,
        log: lastError, elapsedMs: Date.now() - started };
    }
    const health = await isHealthy(base, 1500);
    if (health.ok) return { ok: true, data: health.data, elapsedMs: Date.now() - started };
    lastError = health.error;
    if (onTick) onTick(Date.now() - started, health.error);
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  return { ok: false, error: `no health after ${Math.round(timeoutMs / 1000)}s (${lastError})`,
    elapsedMs: Date.now() - started };
}

/** First-run environment report (/api/app/env), or null if it is unavailable.
 *
 * Measured: the report makes two 2s-bounded probes of the model runtime, so it
 * answers in ~4s when Ollama is healthy and takes longer when it is not. A 4s
 * client timeout therefore reported "no report" for a healthy app -- the
 * timeout has to be larger than the endpoint's own worst case. */
async function probeEnv(base) {
  try {
    return await httpGetJson(`${base}/api/app/env`, 15000);
  } catch {
    return null;
  }
}

module.exports = {
  BootLog,
  httpGetJson,
  isHealthy,
  portFree,
  pickPort,
  locateBackend,
  findBundledRuntime,
  bundledRuntimeEnv,
  resolvePython,
  startBackend,
  stopBackend,
  waitForHealth,
  probeEnv,
};
