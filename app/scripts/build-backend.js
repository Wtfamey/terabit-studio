#!/usr/bin/env node
/**
 * Build the backend the installer will ship, then PROVE it runs.
 *
 * A build that exits 0 is not a working bundle: frozen Python has a whole
 * class of failures (dynamic imports, data files, wrong paths) that only
 * appear when the binary is executed. So this script does what a user would:
 * start the bundle on a free port, wait for /api/health, ask /api/app/env,
 * fetch the served UI, and only then report success. `--verify-only` skips
 * the build and just re-checks an existing bundle (useful after copying one
 * to another machine).
 *
 * Usage:
 *   node scripts/build-backend.js                 # build + verify
 *   node scripts/build-backend.js --verify-only   # verify an existing bundle
 *   TERABIT_SKIP_BACKEND_BUILD=1 npm run dist     # ship an existing bundle
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const boot = require('../boot');

const APP_ROOT = path.resolve(__dirname, '..');
const REPO = path.resolve(APP_ROOT, '..');
const BACKEND = path.join(REPO, 'backend');
const BUNDLE = path.join(BACKEND, 'dist', 'terabit-backend');
const EXE = path.join(BUNDLE, process.platform === 'win32'
  ? 'terabit-backend.exe' : 'terabit-backend');

const VERIFY_ONLY = process.argv.includes('--verify-only');
const SKIP = process.env.TERABIT_SKIP_BACKEND_BUILD === '1';

function python() {
  return process.env.TERABIT_PYTHON || 'python';
}

function build() {
  const webIndex = path.join(REPO, 'frontend', 'dist', 'index.html');
  if (!fs.existsSync(webIndex)) {
    console.error('[backend] frontend/dist is missing. Build the UI first:');
    console.error('          cd frontend && npm install && npm run build');
    return false;
  }
  console.log('[backend] building with PyInstaller (this takes a few minutes)...');
  const res = spawnSync(python(), ['build_backend.py'], {
    cwd: BACKEND,
    stdio: 'inherit',
    windowsHide: true,
  });
  if (res.status !== 0) {
    console.error(`[backend] build failed (exit ${res.status})`);
    return false;
  }
  return true;
}

async function verify() {
  if (!fs.existsSync(EXE)) {
    console.error(`[backend] no bundle at ${EXE}; build it first.`);
    return false;
  }
  const port = await boot.pickPort(8166);
  const base = `http://127.0.0.1:${port}`;
  const log = new boot.BootLog();
  console.log(`[backend] verifying ${path.relative(REPO, EXE)} on port ${port}...`);
  const child = boot.startBackend({ kind: 'bundled', cmd: EXE, args: [], cwd: BUNDLE },
    { port, log });
  let ok = false;
  try {
    const health = await boot.waitForHealth(base, { timeoutMs: 120000, child });
    if (!health.ok) {
      console.error(`[backend] health failed: ${health.error}`);
      console.error(log.lines.slice(-20).join('\n'));
      return false;
    }
    const env = await boot.probeEnv(base);
    if (!env || env.backend === undefined) {
      console.error('[backend] /api/app/env did not answer as expected');
      return false;
    }
    console.log(`[backend] health ok (${Math.round(health.elapsedMs / 1000)}s); ` +
      `frozen=${env.backend.frozen} build=${JSON.stringify(env.backend.build)}`);
    console.log(`[backend] data dir: ${env.backend.data_dir}`);
    console.log(`[backend] model runtime: ${env.runtime && env.runtime.model_ready ? 'ready' : 'NOT ready'}` +
      (env.issues.length ? ` (issues: ${env.issues.join(' | ')})` : ''));
    if (env.ui && env.ui.built) {
      const res = await fetch(`${base}/`);
      const html = await res.text();
      if (!res.ok || !/id="root"/.test(html)) {
        console.error('[backend] the bundle did not serve the built UI at /');
        return false;
      }
      console.log('[backend] bundled UI served at /');
    } else {
      console.log('[backend] warning: this bundle carries no web/ (--no-web build)');
    }
    ok = true;
  } finally {
    await boot.stopBackend(child);
  }
  return ok;
}

async function main() {
  if (SKIP) {
    console.log('[backend] TERABIT_SKIP_BACKEND_BUILD=1; verifying the existing bundle only.');
    return (await verify()) ? 0 : 1;
  }
  if (!VERIFY_ONLY && !build()) return 1;
  const verified = await verify();
  if (!verified) {
    console.error('[backend] the bundle did not verify; not safe to package.');
    return 1;
  }
  console.log('[backend] bundle verified and ready for packaging.');
  return 0;
}

main().then((code) => process.exit(code)).catch((err) => {
  console.error(err && err.stack ? err.stack : String(err));
  process.exit(1);
});
