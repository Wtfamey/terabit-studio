/**
 * End-to-end test for the desktop shell's boot sequence, without Electron.
 *
 * This spawns the REAL backend on a free port, waits for /api/health, asks for
 * the first-run environment report and shuts the process down -- the same code
 * path `main.js` takes when the app launches, so a broken boot is caught here
 * instead of by a user opening a window that never loads.
 *
 * Run:  cd app && node test_boot.js
 */
'use strict';

const fs = require('fs');
const http = require('http');
const os = require('os');
const path = require('path');

const boot = require('./boot');

let PASS = 0;
function check(cond, msg) {
  if (!cond) throw new Error(`FAIL ${msg}`);
  PASS += 1;
}

async function main() {
  // ── ports ──────────────────────────────────────────────────────────────
  const preferred = 8138;
  const port = await boot.pickPort(preferred);
  check(Number.isInteger(port) && port > 0, `pickPort returned ${port}`);
  check(await boot.portFree(port), 'the chosen port is actually free');

  const held = http.createServer(() => {});
  await new Promise((r) => held.listen(0, '127.0.0.1', r));
  const heldPort = held.address().port;
  check((await boot.portFree(heldPort)) === false, 'a listening port reads as busy');

  // ── locating the backend ───────────────────────────────────────────────
  const here = boot.locateBackend({ appRoot: __dirname });
  check(here && here.kind === 'python', `source tree backend: ${JSON.stringify(here)}`);
  check(fs.existsSync(path.join(here.cwd, 'main.py')), 'source backend has main.py');

  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'terabit-boot-'));
  const resDir = path.join(tmp, 'backend');
  fs.mkdirSync(resDir, { recursive: true });
  fs.writeFileSync(path.join(resDir, 'terabit-backend.exe'), 'not really an exe');
  const bundled = boot.locateBackend({ appRoot: tmp, resourcesPath: tmp, isPackaged: true });
  check(bundled && bundled.kind === 'bundled', `bundled exe wins: ${JSON.stringify(bundled)}`);
  const fakeMain = path.join(tmp, 'src-backend');
  fs.mkdirSync(fakeMain, { recursive: true });
  fs.writeFileSync(path.join(fakeMain, 'main.py'), '# fake');
  process.env.TERABIT_BACKEND = fakeMain;
  const fromEnv = boot.locateBackend({ appRoot: tmp });
  check(fromEnv && fromEnv.kind === 'python', `TERABIT_BACKEND honoured: ${JSON.stringify(fromEnv)}`);
  delete process.env.TERABIT_BACKEND;
  fs.rmSync(tmp, { recursive: true, force: true });

  const py = boot.resolvePython(here.cwd);
  check(py.ok, `python with uvicorn available (${JSON.stringify(py.errors || py.cmd)})`);

  // ── failure path first: nothing listens, so it must give up cleanly ────
  const deadPort = await boot.pickPort(0);
  const dead = await boot.waitForHealth(`http://127.0.0.1:${deadPort}`, { timeoutMs: 2500, intervalMs: 300 });
  check(dead.ok === false && /no health/.test(dead.error), `dead port reports: ${dead.error}`);

  // ── the real boot ─────────────────────────────────────────────────────
  const base = `http://127.0.0.1:${port}`;
  const reused = await boot.isHealthy(base, 800);
  check(!reused.ok, 'nothing is answering on the chosen port before we start it');
  const log = new boot.BootLog(50);
  const child = boot.startBackend(here, { port, log });
  check(child.pid > 0, 'backend process has a pid');

  const up = await boot.waitForHealth(base, { timeoutMs: 180000, child, intervalMs: 700 });
  check(up.ok, `backend became healthy (${JSON.stringify(up.error || up.elapsedMs)})`);
  check(up.data && typeof up.data === 'object', 'health returned JSON');
  check(log.lines.length > 0, 'boot log captured backend output');

  const env = await boot.probeEnv(base);
  check(env && typeof env.ok === 'boolean', `first-run env report: ${JSON.stringify(env && env.issues)}`);
  check(env && env.ui && typeof env.ui.built === 'boolean', 'env reports whether the UI is built');
  check(env && env.runtime && 'model_ready' in env.runtime, 'env reports model readiness');

  // a second health probe now sees it (this is the "reuse instead of spawn" path)
  check((await boot.isHealthy(base, 1500)).ok, 'health is reusable while running');

  const stopped = await boot.stopBackend(child);
  check(stopped, 'stopBackend reports the process was killed');
  await new Promise((r) => setTimeout(r, 600));
  check((await boot.isHealthy(base, 800)).ok === false, 'backend is down after stop');
  check((await boot.stopBackend(child)) === false, 'stopping twice is a no-op');

  let threw = false;
  try {
    boot.startBackend(null, { port });
  } catch {
    threw = true;
  }
  check(threw, 'starting with no backend spec throws instead of crashing later');

  held.close();
  console.log(`ALL BOOT TESTS PASS (${PASS} checks)`);
}

main().catch((err) => {
  console.error(err && err.stack ? err.stack : String(err));
  process.exit(1);
});
