#!/usr/bin/env node
/**
 * Make sure the Electron binary in node_modules is actually complete.
 *
 * Live failure this exists for: `npm install` reported success while
 * electron's postinstall died mid-extract -- zip downloaded, exit code 0, and
 * a `dist/` containing a single file. The next `electron .` then failed with
 * a message about a missing binary that gives no hint about the cause. Some
 * npm builds also block install scripts outright (seen here: "1 package had
 * install scripts blocked"), which produces the same half-installed state.
 *
 * So: verify the binary, and if it is incomplete, repair it from the cached
 * download with 7-Zip (7zip-bin) or the platform's own tar, then verify
 * again. Exit 1 only when the install cannot be made usable -- an install
 * that cannot run the app should fail loudly rather than ship a broken shell.
 *
 * Usage:  node scripts/ensure-electron.js [--force]
 */
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const FORCE = process.argv.includes('--force');
const APP_ROOT = path.resolve(__dirname, '..');
const ELECTRON_DIR = path.join(APP_ROOT, 'node_modules', 'electron');
const MIN_BYTES = 60 * 1024 * 1024; // a real Electron binary is > 100 MB

function log(line) {
  process.stdout.write(`[ensure-electron] ${line}\n`);
}

// Electron's own convention: `path.txt` holds the executable path RELATIVE TO
// dist/ ("electron.exe", "Electron.app/Contents/MacOS/Electron", "electron").
// Comparing it against "dist/electron.exe" -- as the first version of this
// script did -- reports a perfectly good install as broken.
function exeRelPath() {
  if (process.platform === 'win32') return 'electron.exe';
  if (process.platform === 'darwin') return 'Electron.app/Contents/MacOS/Electron';
  return 'electron';
}

function inspect() {
  const rel = exeRelPath();
  const full = path.join(ELECTRON_DIR, 'dist', rel);
  const pathTxt = path.join(ELECTRON_DIR, 'path.txt');
  const problems = [];
  if (!fs.existsSync(ELECTRON_DIR)) {
    return { state: 'missing', problems: ['electron package is not installed'] };
  }
  let size = 0;
  try {
    size = fs.statSync(full).size;
  } catch {
    problems.push(`binary missing: ${rel}`);
  }
  if (size && size < MIN_BYTES) {
    problems.push(`binary is only ${(size / 1048576).toFixed(1)} MB (truncated extract)`);
  }
  let recorded = '';
  try {
    recorded = fs.readFileSync(pathTxt, 'utf8').trim().replace(/\\/g, '/');
  } catch {
    problems.push('path.txt is missing');
  }
  if (recorded && recorded !== rel.replace(/\\/g, '/')) {
    problems.push(`path.txt says "${recorded}", expected "${rel}"`);
  }
  return {
    state: problems.length ? 'broken' : 'ok',
    problems,
    binary: full,
    size,
    version: (() => {
      try {
        return require(path.join(ELECTRON_DIR, 'package.json')).version;
      } catch {
        return 'unknown';
      }
    })(),
  };
}

function findZip(version) {
  const suffix = `${process.platform}-${process.arch}`;
  const names = [
    `electron-v${version}-${suffix}.zip`,
    `electron-v${version}-${suffix}-symbols.zip`,
  ];
  const dirs = [
    process.env.ELECTRON_CACHE,
    path.join(ELECTRON_DIR, 'cache'),
    process.platform === 'win32'
      ? path.join(os.homedir(), 'AppData', 'Local', 'electron', 'Cache')
      : path.join(os.homedir(), '.cache', 'electron'),
    path.join(os.homedir(), '.electron'),
  ].filter(Boolean);
  for (const dir of dirs) {
    for (const name of names) {
      const full = path.join(dir, name);
      try {
        if (fs.statSync(full).size > MIN_BYTES) return full;
      } catch { /* keep looking */ }
    }
  }
  return null;
}

function extract(zip, destDir) {
  fs.mkdirSync(destDir, { recursive: true });
  let sevenZip = null;
  try {
    sevenZip = require('7zip-bin').path7za;
  } catch { /* fall back below */ }

  if (sevenZip && fs.existsSync(sevenZip)) {
    const res = spawnSync(sevenZip, ['x', '-y', `-o${destDir}`, zip], {
      stdio: 'inherit',
      windowsHide: true,
    });
    if (res.status === 0) return '7za';
    log(`7za exited ${res.status}; trying the platform tar`);
  }
  // Windows 10+ ships bsdtar, which reads zip; macOS and Linux have tar too.
  const tar = spawnSync('tar', ['-xf', zip, '-C', destDir], {
    stdio: 'inherit',
    windowsHide: true,
  });
  if (tar.status === 0) return 'tar';
  return null;
}

function main() {
  const before = inspect();
  if (before.state === 'missing') {
    // Not a failure: some installs intentionally skip the optional shell.
    log('electron is not installed; skipping (the web app still runs).');
    return 0;
  }
  if (before.state === 'ok' && !FORCE) {
    log(`electron ${before.version} is complete (${(before.size / 1048576).toFixed(0)} MB)`);
    return 0;
  }
  const zip = findZip(before.version);
  if (!zip) {
    if (before.state === 'ok') {
      log(`electron ${before.version} verifies; no cached download to re-extract from.`);
      return 0;
    }
    log(`electron ${before.version} looks incomplete: ${before.problems.join('; ')}`);
    log('No cached Electron download was found to repair from.');
    log('Fix: run `npm install` again with network access, or delete');
    log(`      ${ELECTRON_DIR} and reinstall.`);
    return 1;
  }
  log(before.state === 'ok'
    ? `electron ${before.version} verifies; re-extracting from ${zip} (--force)`
    : `electron ${before.version} looks incomplete (${before.problems.join('; ')}); ` +
      `repairing from ${zip}`);

  // Extract to a staging directory and only swap it in after the new copy
  // verifies. Deleting a working dist/ first would mean a failed extraction
  // leaves the user with no Electron at all -- the opposite of a repair.
  const dist = path.join(ELECTRON_DIR, 'dist');
  const staging = path.join(ELECTRON_DIR, 'dist.new');
  fs.rmSync(staging, { recursive: true, force: true });
  const used = extract(zip, staging);
  const staged = path.join(staging, exeRelPath());
  let stagedOk = false;
  try {
    stagedOk = fs.statSync(staged).size >= MIN_BYTES;
  } catch { stagedOk = false; }
  if (!used || !stagedOk) {
    fs.rmSync(staging, { recursive: true, force: true });
    log(used
      ? `extraction produced no usable binary at ${staged}; keeping the existing install.`
      : 'Extraction failed with both 7-Zip and tar; keeping the existing install.');
    return before.state === 'ok' ? 0 : 1;
  }
  fs.rmSync(dist, { recursive: true, force: true });
  fs.renameSync(staging, dist);
  try {
    fs.writeFileSync(path.join(ELECTRON_DIR, 'path.txt'), exeRelPath(), 'utf8');
  } catch (err) {
    log(`Could not write path.txt: ${err.message}`);
  }
  const after = inspect();
  if (after.state === 'ok') {
    log(`repaired with ${used}: electron ${after.version} ` +
        `(${(after.size / 1048576).toFixed(0)} MB)`);
    return 0;
  }
  log(`still broken after repair: ${after.problems.join('; ')}`);
  return 1;
}

process.exitCode = main();
