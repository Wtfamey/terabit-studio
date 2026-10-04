/**
 * Settings -- the screen every desktop app is expected to have and this one
 * did not.
 *
 * Rules this follows, on purpose:
 *   * nothing here pretends: every control is wired to behaviour, and every
 *     value shown comes from the machine it is running on (/api/app/env,
 *     /api/models/state, the Electron bridge), never from a hard-coded text;
 *   * diagnostics are one keystroke away (Ctrl+,) and copyable, because the
 *     user of a local-first app IS the support line -- there is no server to
 *     file a ticket with;
 *   * destructive actions are absent rather than half-built: the app points
 *     at the folders it owns so a human can inspect them, and leaves deleting
 *     to the operating system;
 *   * the sections mirror what other professional tools ship: General,
 *     Model & performance, Storage, Privacy & licences, Diagnostics, and
 *     Keyboard shortcuts.
 */
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowLeft, Check, Clipboard, Cpu, ExternalLink, FolderOpen, Gauge,
  HardDrive, Info, Keyboard, Loader2, RefreshCw, ShieldCheck, Stethoscope,
  TriangleAlert, Zap, Star,
} from 'lucide-react';
import { ui } from '../theme';
import { COPY_LANGUAGES, resetSettings, saveSettings, useSettings } from '../settings';
import { ENDPOINTS } from '../config';

// ─────────────────────────────── shared types ───────────────────────────────

export interface EnvReport {
  ok: boolean;
  issues: string[];
  backend: { status: string; data_dir: string; frozen: boolean; build: { label?: string; source?: string } };
  runtime: {
    reachable: boolean; base_url: string; error: string | null;
    models: string[]; loaded: string[]; model: string; model_ready: boolean;
    num_ctx?: number; loaded_context?: number | null; n_gpu_layers?: string;
    n_threads?: string; kv_cache_type?: string;
  };
  ui: { built: boolean; dir: string };
  storage: { writable: boolean };
  first_run: boolean;
}

export interface CatalogRow {
  id: string; label: string; note: string; file_name: string; bytes: number;
  gib: number; params_b: number; quant: string; license: string;
  min_vram_gb: number; finetuned: boolean; recommended: boolean;
  ollama_tag: string; url: string; downloadable: boolean;
  status: 'installed' | 'ollama' | 'absent'; delivery?: string | null;
  path: string; verified: boolean; available: boolean;
}

export interface ModelState {
  ok: boolean;
  issues: string[];
  catalog: CatalogRow[];
  models_dir: string;
  disk: { path: string; free_bytes: number; total_bytes: number; free_human: string };
  ollama: { reachable: boolean; base_url: string; tags: string[]; error: string | null };
  runtime: { llama_server: { found: boolean; path: string; source: string }; ollama: boolean };
  vram_gb: number | null;
  recommended: string;
  active: { id: string; model_path: string; model_name: string };
  imports: { record_id: string; path: string; name: string; bytes: number; exists: boolean; verified: boolean }[];
  unmatched_ggufs: { path: string; name: string; bytes: number; gib: number }[];
  search_dirs: string[];
}

interface DesktopBridge {
  baseUrl(): Promise<string>;
  env(): Promise<unknown>;
  bootLog(): Promise<string>;
  state(): Promise<unknown>;
  version(): Promise<string>;
  retry(): Promise<unknown>;
  chooseFolder(): Promise<{ canceled: boolean; path?: string }>;
  openExternal(url: string): Promise<unknown>;
  openLogs(): Promise<string>;
  openPath(path: string): Promise<unknown>;
  versions(): Promise<Record<string, string>>;
  onBootLog(cb: (line: string) => void): () => void;
  onState(cb: (s: unknown) => void): () => void;
}

type SectionId = 'general' | 'model' | 'storage' | 'privacy' | 'diagnostics' | 'shortcuts';

const SECTIONS: { id: SectionId; label: string; icon: React.ReactNode; blurb: string }[] = [
  { id: 'general', label: 'General', icon: <Gauge className="w-4 h-4" />, blurb: 'Defaults for new builds' },
  { id: 'model', label: 'Model & performance', icon: <Cpu className="w-4 h-4" />, blurb: 'What generates your sites' },
  { id: 'storage', label: 'Storage', icon: <HardDrive className="w-4 h-4" />, blurb: 'Where your data lives' },
  { id: 'privacy', label: 'Privacy & licences', icon: <ShieldCheck className="w-4 h-4" />, blurb: 'What leaves this machine' },
  { id: 'diagnostics', label: 'Diagnostics', icon: <Stethoscope className="w-4 h-4" />, blurb: 'Environment check and logs' },
  { id: 'shortcuts', label: 'Keyboard shortcuts', icon: <Keyboard className="w-4 h-4" />, blurb: 'Move without the mouse' },
];

// ─────────────────────────────── primitives ───────────────────────────────

function Card({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className={`${ui.panel} p-5`}>
      <h2 className="text-[15px] font-semibold text-slate-100">{title}</h2>
      {hint && <p className="mt-1 text-[12.5px] text-slate-500">{hint}</p>}
      <div className="mt-4 space-y-3">{children}</div>
    </section>
  );
}

function Row({ label, hint, children }: { label: string; hint?: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/[0.06] bg-white/[0.02] px-4 py-3">
      <div className="min-w-[220px] flex-1">
        <div className="text-[13.5px] text-slate-200">{label}</div>
        {hint && <div className="mt-0.5 text-[12px] leading-relaxed text-slate-500">{hint}</div>}
      </div>
      {children && <div className="flex items-center gap-2">{children}</div>}
    </div>
  );
}

function Chip({ tone, children }: { tone: 'ok' | 'warn' | 'bad' | 'muted'; children: React.ReactNode }) {
  const tones = {
    ok: 'border-emerald-400/25 bg-emerald-400/10 text-emerald-300',
    warn: 'border-amber-400/25 bg-amber-400/10 text-amber-300',
    bad: 'border-rose-400/25 bg-rose-400/10 text-rose-300',
    muted: 'border-white/[0.09] bg-white/[0.04] text-slate-400',
  } as const;
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${tones[tone]}`}>
      {children}
    </span>
  );
}

function GhostButton({ onClick, children, title }: { onClick: () => void; children: React.ReactNode; title?: string }) {
  return (
    <button onClick={onClick} title={title} className={`${ui.btnGhost} px-3 py-2 text-[12.5px]`}>
      {children}
    </button>
  );
}

const fmtBytes = (n: number) => {
  if (!Number.isFinite(n) || n < 0) return 'unknown';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let v = n, i = 0;
  while (v >= 1000 && i < units.length - 1) { v /= 1000; i += 1; }
  return `${v.toFixed(i >= 3 ? 1 : 0)} ${units[i]}`;
};

// ─────────────────────────────── the page ───────────────────────────────

export function Settings() {
  const navigate = useNavigate();
  const settings = useSettings();
  const [section, setSection] = useState<SectionId>('general');
  const [env, setEnv] = useState<EnvReport | null>(null);
  const [models, setModels] = useState<ModelState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [versions, setVersions] = useState<Record<string, string> | null>(null);
  const [bootLog, setBootLog] = useState('');

  const desktop = typeof window !== 'undefined'
    ? (window as unknown as { terabit?: DesktopBridge }).terabit
    : undefined;
  const isDesktop = Boolean(desktop);

  const load = useCallback(async (refresh = false) => {
    setLoading(true);
    setError(null);
    try {
      const [envRes, modelRes] = await Promise.all([
        fetch(ENDPOINTS.appEnv, { cache: 'no-store' }),
        fetch(refresh ? `${ENDPOINTS.modelsState}?refresh=true` : ENDPOINTS.modelsState, { cache: 'no-store' }),
      ]);
      if (!envRes.ok) throw new Error(`environment check failed (HTTP ${envRes.status})`);
      setEnv(await envRes.json());
      // The model inventory is supplementary: if it fails, the page still works.
      if (modelRes.ok) setModels(await modelRes.json());
      setCheckedAt(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (desktop?.versions) desktop.versions().then((v) => setVersions(v as Record<string, string>)).catch(() => {});
  }, [desktop]);

  const copy = useCallback(async (label: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(label);
      setTimeout(() => setCopied(null), 1600);
    } catch { /* clipboard refused */ }
  }, []);

  const diagnostics = useCallback(() => {
    const runtime = env?.runtime;
    const server = models?.runtime?.llama_server;
    return [
      'Terabit Studio -- diagnostics',
      `time: ${new Date().toISOString()}`,
      `version: ${versions?.app || 'unknown'}  build: ${env?.backend?.build?.label || 'source'}`,
      `electron/chrome/node: ${versions?.electron || '-'} / ${versions?.chrome || '-'} / ${versions?.node || '-'}`,
      `backend: ${env?.backend?.status || 'unknown'}  frozen=${env?.backend?.frozen ?? '?'}  data=${env?.backend?.data_dir || '?'}`,
      `runtime: ${runtime?.reachable ? 'reachable' : 'unreachable'} at ${runtime?.base_url || '?'}  server=${server?.found ? server.path : 'none'}`,
      `model: ${runtime?.model || '?'}  ready=${runtime?.model_ready ?? '?'}  loaded=${(runtime?.loaded || []).join(', ') || 'none'}`,
      `perf: ctx=${runtime?.num_ctx ?? '?'}  gpu_layers=${runtime?.n_gpu_layers ?? '?'}  threads=${runtime?.n_threads ?? '?'}  kv=${runtime?.kv_cache_type ?? '?'}`,
      `storage: ${models?.models_dir || '?'}  free=${models?.disk?.free_human || '?'}  vram=${models?.vram_gb ?? 'unknown'}GB`,
      '',
      `environment issues (${env?.issues?.length ?? 0}):`,
      ...(env?.issues || []).map((i) => `  - ${i}`),
      `model issues (${models?.issues?.length ?? 0}):`,
      ...(models?.issues || []).map((i) => `  - ${i}`),
    ].join('\n');
  }, [env, models, versions]);

  const openPath = useCallback((p: string) => {
    if (desktop?.openPath) desktop.openPath(p).catch(() => {});
  }, [desktop]);

  const openLogs = useCallback(() => {
    if (desktop?.openLogs) desktop.openLogs().catch(() => {});
  }, [desktop]);

  const shown = SECTIONS.find((s) => s.id === section)!;

  return (
    <div className="min-h-screen" style={{ background: '#07070d' }}>
      <header className="sticky top-0 z-20 border-b border-white/[0.05] bg-[#07070d]/80 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-6xl items-center gap-3 px-5">
          <button onClick={() => navigate('/')} className={`${ui.btnGhost} px-3 py-2`} aria-label="Back to home">
            <ArrowLeft className="h-4 w-4" />
          </button>
          <div>
            <h1 className="text-[15px] font-semibold text-slate-100">Settings</h1>
            <p className="text-[12px] text-slate-500">
              {checkedAt ? `Checked ${checkedAt.toLocaleTimeString()} · runs on this machine` : 'Checking this machine...'}
            </p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            {loading && <Loader2 className="h-4 w-4 animate-spin text-violet-300" />}
            <GhostButton onClick={() => load(true)} title="Re-read the environment and model inventory">
              <RefreshCw className="h-3.5 w-3.5" /> Re-check
            </GhostButton>
          </div>
        </div>
      </header>

      <div className="mx-auto flex max-w-6xl flex-col gap-6 px-5 py-6 md:flex-row">
        <nav aria-label="Settings sections" className="md:w-60 md:shrink-0">
          <ul className="flex gap-2 overflow-x-auto md:flex-col md:overflow-visible">
            {SECTIONS.map((s) => {
              const active = s.id === section;
              return (
                <li key={s.id}>
                  <button
                    onClick={() => setSection(s.id)}
                    aria-current={active ? 'page' : undefined}
                    className={`flex w-full items-center gap-2.5 whitespace-nowrap rounded-xl px-3 py-2.5 text-left text-[13px] transition-colors ${
                      active
                        ? 'bg-violet-500/15 text-violet-200 border border-violet-400/25'
                        : 'text-slate-400 border border-transparent hover:bg-white/[0.04] hover:text-slate-200'
                    }`}
                  >
                    {s.icon}
                    <span className="font-medium">{s.label}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>

        <main className="min-w-0 flex-1 space-y-5">
          <div>
            <h2 className="text-lg font-semibold text-slate-100">{shown.label}</h2>
            <p className="text-[12.5px] text-slate-500">{shown.blurb}</p>
          </div>

          {error && (
            <div role="alert" className="rounded-xl border border-rose-400/25 bg-rose-500/10 px-4 py-3 text-[13px] text-rose-200">
              <TriangleAlert className="mr-2 inline h-4 w-4" />
              {error}
              <button className="ml-3 underline hover:no-underline" onClick={() => load(true)}>retry</button>
            </div>
          )}

          {section === 'general' && <GeneralSection />}
          {section === 'model' && <ModelSection env={env} models={models} loading={loading} />}
          {section === 'storage' && (
            <StorageSection models={models} env={env} isDesktop={isDesktop}
              onOpenPath={openPath} onOpenLogs={openLogs} onCopy={copy} copied={copied} />
          )}
          {section === 'privacy' && <PrivacySection onCopy={copy} copied={copied} />}
          {section === 'diagnostics' && (
            <DiagnosticsSection env={env} models={models} isDesktop={isDesktop} bootLog={bootLog}
              onLoadBootLog={() => {
                if (desktop?.bootLog) desktop.bootLog().then((t) => setBootLog(String(t || ''))).catch(() => {});
              }}
              onCopy={copy} copied={copied} onOpenLogs={openLogs}
              onReload={() => load(true)} diagnostics={diagnostics()} />
          )}
          {section === 'shortcuts' && <ShortcutsSection />}
        </main>
      </div>
    </div>
  );
}

// ─────────────────────────────── sections ───────────────────────────────

function GeneralSection() {
  const settings = useSettings();
  const [saved, setSaved] = useState(false);
  const flash = () => { setSaved(true); setTimeout(() => setSaved(false), 1200); };

  const set = (patch: Parameters<typeof saveSettings>[0]) => { saveSettings(patch); flash(); };

  return (
    <>
      <Card title="Defaults for new builds"
        hint="These apply to every new prompt in the builder and are stored on this machine only.">
        <Row label="Model provider"
          hint="Local is the product: nothing leaves this machine and there is no bill. Cloud providers are optional and need a key in the app's .env.">
          <select
            aria-label="Model provider"
            value={settings.provider}
            onChange={(e) => set({ provider: e.target.value as typeof settings.provider })}
            className="rounded-lg border border-white/[0.09] bg-white/[0.05] px-3 py-2 text-[13px] text-slate-100 outline-none focus:border-violet-400/60"
          >
            <option value="auto">Automatic — local first</option>
            <option value="local">Local model only</option>
            <option value="openai">Cloud (OpenAI-compatible)</option>
          </select>
        </Row>

        <Row label={`Creativity — temperature ${settings.temperature.toFixed(2)}`}
          hint="Low values stick to the brief; high values explore more layout and copy ideas. 0.7 is what the fine-tune was tuned around.">
          <input
            type="range" min={0} max={1} step={0.05}
            aria-label="Default temperature"
            value={settings.temperature}
            onChange={(e) => set({ temperature: Number(e.target.value) })}
            className="w-44 accent-violet-500"
          />
        </Row>

        <Row label="Copy language for generated sites"
          hint="Auto follows the language of your prompt (Hinglish and Devanagari included). A fixed choice appends an instruction to every prompt.">
          <select
            aria-label="Copy language"
            value={settings.copyLanguage}
            onChange={(e) => set({ copyLanguage: e.target.value })}
            className="rounded-lg border border-white/[0.09] bg-white/[0.05] px-3 py-2 text-[13px] text-slate-100 outline-none focus:border-violet-400/60"
          >
            {COPY_LANGUAGES.map((l) => <option key={l.value} value={l.value}>{l.label}</option>)}
          </select>
        </Row>

        <Row label="Reduce motion"
          hint="Follows your operating system setting by default; turn this on to force the calm version of the interface.">
          <label className="inline-flex cursor-pointer items-center gap-2 text-[13px] text-slate-300">
            <input type="checkbox" checked={settings.reduceMotion}
              onChange={(e) => set({ reduceMotion: e.target.checked })} className="accent-violet-500" />
            {settings.reduceMotion ? 'On' : 'Off'}
          </label>
        </Row>

        <div className="flex items-center justify-between pt-1">
          <span className="text-[12px] text-slate-500">
            {saved ? <span className="text-emerald-300"><Check className="mr-1 inline h-3.5 w-3.5" />Saved</span>
              : 'Changes save immediately.'}
          </span>
          <GhostButton onClick={() => { resetSettings(); flash(); }}>Reset to defaults</GhostButton>
        </div>
      </Card>

      <Card title="What this product is">
        <p className="text-[13px] leading-relaxed text-slate-400">
          Terabit Studio turns a sentence into a working website or app: a model on this
          machine plans the files, writes each section, then bundles and render-tests the
          result before you see it. No account is needed to build, no API key is required,
          and your prompts and projects stay in the folders shown under Storage.
        </p>
      </Card>
    </>
  );
}

function ModelSection({ env, models, loading }: { env: EnvReport | null; models: ModelState | null; loading: boolean }) {
  const runtime = env?.runtime;
  const server = models?.runtime?.llama_server;
  const recommended = models?.catalog.find((m) => m.recommended);
  const vram = models?.vram_gb ?? null;

  return (
    <>
      <Card title="Runtime" hint="The process that actually runs the model on this machine.">
        <Row label={runtime?.reachable ? 'Model server answering' : 'No model server answering'}
          hint={runtime ? `${runtime.base_url} · ${runtime.models.length} model${runtime.models.length === 1 ? '' : 's'} available` : 'Waiting for the environment check.'}>
          {runtime?.reachable
            ? <Chip tone="ok"><Check className="h-3 w-3" /> Online</Chip>
            : <Chip tone="bad">Offline</Chip>}
        </Row>
        <Row label="Serving" hint={runtime?.loaded?.length ? `Loaded: ${runtime.loaded.join(', ')}` : 'Nothing loaded yet — the first build pages the model in.'}>
          <span className="font-mono text-[12.5px] text-slate-300">{!runtime && loading ? '…' : runtime?.model || '—'}</span>
          {runtime?.model_ready
            ? <Chip tone="ok">ready</Chip>
            : <Chip tone="warn">not pulled</Chip>}
        </Row>
        <Row label="llama.cpp server" hint={server?.found ? server.path : 'Not found next to this app or on PATH. The self-contained build ships it inside the app folder.'}>
          {server?.found ? <Chip tone="ok">{server.source}</Chip> : <Chip tone="muted">not found</Chip>}
        </Row>
        {models?.ollama?.reachable && (
          <Row label="Ollama detected" hint={`Tags: ${(models.ollama.tags || []).slice(0, 6).join(', ') || 'none'}`}>
            <Chip tone="ok">{models.ollama.tags.length}</Chip>
          </Row>
        )}
      </Card>

      <Card title="Performance" hint="Read from this install, not from a defaults table.">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            { k: 'Context window', v: runtime?.num_ctx ? `${runtime.num_ctx} tokens` : '—' },
            { k: 'GPU layers', v: runtime?.n_gpu_layers === '-1' ? 'All (-1)' : runtime?.n_gpu_layers || '—' },
            { k: 'CPU threads', v: runtime?.n_threads || '—' },
            { k: 'KV cache', v: (runtime?.kv_cache_type || 'f16').toUpperCase() },
          ].map(({ k, v }) => (
            <div key={k} className="rounded-xl border border-white/[0.06] bg-white/[0.02] px-3.5 py-3">
              <div className="text-[11px] uppercase tracking-wide text-slate-500">{k}</div>
              <div className="mt-1 font-mono text-[14px] text-slate-100">{v}</div>
            </div>
          ))}
        </div>
        {runtime?.loaded_context && runtime.loaded_context !== runtime.num_ctx && (
          <Row label="Context actually in use"
            hint={`The server loaded ${runtime.loaded_context} tokens while the app asks for ${runtime.num_ctx}. Ollama ignores a per-request num_ctx on its OpenAI endpoint — the model's own Modelfile wins — so this costs VRAM and speed for no benefit.`}>
            <Chip tone="warn">{runtime.loaded_context} tokens</Chip>
          </Row>
        )}

        <Row label="Graphics memory detected"
          hint={vram === null
            ? 'No NVIDIA GPU probe answered. On integrated graphics the small model below is the honest choice.'
            : `${vram} GB visible to nvidia-smi. The fine-tune is comfortable from about 8 GB; 6 GB runs it with a small CPU spill.`}>
          <Chip tone={vram === null ? 'muted' : vram >= 8 ? 'ok' : 'warn'}>
            <Zap className="h-3 w-3" /> {vram === null ? 'unknown' : `${vram} GB`}
          </Chip>
        </Row>
        {recommended && (
          <Row label="Recommended here" hint={recommended.note}>
            <Chip tone="ok"><Star className="h-3 w-3" /> {recommended.label.split('(')[0].trim()}</Chip>
          </Row>
        )}
      </Card>

      <Card title="Model inventory"
        hint={`Models are searched for in ${models ? models.search_dirs.length : 3} folders (data dir, app folder, ~/.terabit/models) plus any local Ollama.`}>
        {(models?.catalog || []).map((m) => (
          <div key={m.id} className="rounded-xl border border-white/[0.06] bg-white/[0.02] px-4 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[13.5px] font-medium text-slate-100">{m.label}</span>
              {m.recommended && <Chip tone="ok"><Star className="h-3 w-3" /> recommended</Chip>}
              {m.finetuned && <Chip tone="muted">fine-tuned</Chip>}
              {m.status === 'installed' && <Chip tone="ok">installed</Chip>}
              {m.status === 'ollama' && <Chip tone="ok">Ollama tag</Chip>}
              {m.status === 'absent' && <Chip tone="warn">not on disk</Chip>}
            </div>
            <div className="mt-1.5 text-[12px] text-slate-500">
              {m.params_b}B · {m.quant} · {fmtBytes(m.bytes)} · {m.license}
            </div>
            {m.path && (
              <div className="mt-1 break-all font-mono text-[11.5px] text-slate-500">
                {m.path}{m.verified ? '  ✓ sha256 verified' : '  (not hash-verified yet)'}
              </div>
            )}
            {m.status === 'absent' && !m.downloadable && (
              <div className="mt-1 text-[11.5px] text-amber-300/80">
                No download source configured in this build — the self-contained package ships this file inside the app.
              </div>
            )}
          </div>
        ))}
        {(models?.unmatched_ggufs || []).length > 0 && (
          <Row label={`Other .gguf files found (${models!.unmatched_ggufs.length})`}
            hint={models!.unmatched_ggufs.map((g) => `${g.name} — ${g.gib} GB`).join(' · ')}>
            <Chip tone="muted">not catalogued</Chip>
          </Row>
        )}
      </Card>

      {(models?.issues || []).length > 0 && (
        <Card title="Worth knowing">
          <ul className="space-y-2">
            {models!.issues.map((issue, i) => (
              <li key={i} className="flex gap-2 text-[13px] text-amber-200/90">
                <Info className="mt-0.5 h-4 w-4 shrink-0" /> {issue}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}

function StorageSection({ models, env, isDesktop, onOpenPath, onOpenLogs, onCopy, copied }: {
  models: ModelState | null; env: EnvReport | null; isDesktop: boolean;
  onOpenPath: (p: string) => void; onOpenLogs: () => void;
  onCopy: (label: string, text: string) => void; copied: string | null;
}) {
  const disk = models?.disk;
  const usedPct = disk && disk.total_bytes > 0
    ? Math.min(100, Math.round(((disk.total_bytes - disk.free_bytes) / disk.total_bytes) * 100))
    : null;
  const dataDir = env?.backend?.data_dir || '';
  const modelsDir = models?.models_dir || '';

  return (
    <>
      <Card title="Where your work lives" hint="Nothing here is uploaded to a service; these are ordinary folders on this machine.">
        <Row label="App data" hint={dataDir || 'Waiting for the environment check.'}>
          {isDesktop && dataDir && <GhostButton onClick={() => onOpenPath(dataDir)}><FolderOpen className="h-3.5 w-3.5" /> Open</GhostButton>}
          {dataDir && (
            <GhostButton onClick={() => onCopy('data', dataDir)}>
              <Clipboard className="h-3.5 w-3.5" /> {copied === 'data' ? 'Copied' : 'Copy'}
            </GhostButton>
          )}
        </Row>
        <Row label="Models" hint={modelsDir || '—'}>
          {isDesktop && modelsDir && <GhostButton onClick={() => onOpenPath(modelsDir)}><FolderOpen className="h-3.5 w-3.5" /> Open</GhostButton>}
          {modelsDir && (
            <GhostButton onClick={() => onCopy('models', modelsDir)}>
              <Clipboard className="h-3.5 w-3.5" /> {copied === 'models' ? 'Copied' : 'Copy'}
            </GhostButton>
          )}
        </Row>
        {isDesktop && (
          <Row label="Logs" hint="Startup and backend output, kept to the last 5 MB.">
            <GhostButton onClick={onOpenLogs}><FolderOpen className="h-3.5 w-3.5" /> Open log folder</GhostButton>
          </Row>
        )}
        <Row label={env?.storage?.writable === false ? 'App data is NOT writable' : 'App data is writable'}
          hint={env?.storage?.writable === false
            ? 'The app fell back to a temporary folder. Point TERABIT_DATA_DIR at a writable drive.'
            : 'Projects, uploads, backups and the local database are written here.'}>
          {env?.storage?.writable === false
            ? <Chip tone="bad">read-only</Chip>
            : <Chip tone="ok"><Check className="h-3 w-3" /> ok</Chip>}
        </Row>
      </Card>

      <Card title="Disk space" hint={disk ? `${disk.path} · ${disk.free_human} free of ${fmtBytes(disk.total_bytes)}` : 'Reading…'}>
        <div className="h-2.5 w-full overflow-hidden rounded-full bg-white/[0.06]" role="img"
          aria-label={`Disk ${usedPct ?? '?'}% used`}>
          <div className="h-full rounded-full bg-[linear-gradient(90deg,#a78bfa,#22d3ee)]"
            style={{ width: `${usedPct ?? 0}%` }} />
        </div>
        <p className="text-[12px] text-slate-500">
          {usedPct !== null ? `${usedPct}% used on the drive that holds your models and projects.` : 'Waiting for the disk probe.'}
          {' '}A 7B model needs about 4.7 GB; the app warns before a download that will not fit.
        </p>
        {disk && disk.free_bytes >= 0 && disk.free_bytes < 2_000_000_000 && (
          <div className="flex items-start gap-2 rounded-xl border border-amber-400/25 bg-amber-400/10 px-4 py-3 text-[12.5px] text-amber-200">
            <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />
            Under 2 GB free. Set TERABIT_DATA_DIR to a roomier drive before adding models.
          </div>
        )}
      </Card>

      <Card title="Where models are looked for"
        hint="A .gguf dropped into any of these is picked up without copying it.">
        <ul className="space-y-1.5">
          {(models?.search_dirs || []).map((d) => (
            <li key={d} className="break-all font-mono text-[11.5px] text-slate-400">{d}</li>
          ))}
          {!models && <li className="text-[12px] text-slate-500">Reading…</li>}
        </ul>
      </Card>
    </>
  );
}

function PrivacySection({ onCopy, copied }: { onCopy: (label: string, text: string) => void; copied: string | null }) {
  const statement = [
    'Terabit Studio — privacy statement',
    '',
    'This app runs entirely on this machine. It has no telemetry, no analytics,',
    'no crash reporting and no account requirement. Prompts, generated code,',
    'uploads and logs never leave the computer. The only outbound connections',
    'the product makes are: (1) a model download you start yourself, and',
    '(2) a cloud model provider, only if you configure a key in .env and',
    'choose that provider. Everything else is localhost.',
  ].join('\n');

  return (
    <>
      <Card title="What leaves this machine"
        hint="The answer is meant to be short enough to actually read.">
        <ul className="space-y-2 text-[13px] text-slate-300">
          <li className="flex gap-2"><Check className="mt-0.5 h-4 w-4 text-emerald-300" /> Your prompts and projects stay in the folders shown under Storage.</li>
          <li className="flex gap-2"><Check className="mt-0.5 h-4 w-4 text-emerald-300" /> No telemetry, no crash reports, no usage analytics — there is no server to send them to.</li>
          <li className="flex gap-2"><Check className="mt-0.5 h-4 w-4 text-emerald-300" /> The model runs locally; nothing is billed per token.</li>
          <li className="flex gap-2"><Info className="mt-0.5 h-4 w-4 text-slate-400" /> Optional cloud providers are opt-in per request and need a key you add yourself.</li>
        </ul>
        <div className="pt-1">
          <GhostButton onClick={() => onCopy('privacy', statement)}>
            <Clipboard className="h-3.5 w-3.5" /> {copied === 'privacy' ? 'Copied' : 'Copy privacy statement'}
          </GhostButton>
        </div>
      </Card>

      <Card title="Licences and credits" hint="What ships inside this app and under which terms.">
        <Row label="Terabit Studio" hint="The application, its pipeline and its training data pipeline.">
          <span className="text-[12px] text-slate-400">See LICENSE in the app folder</span>
        </Row>
        <Row label="Qwen2.5-Coder (base model + fine-tune)" hint="The fine-tuned model this app ships is derived from Qwen2.5-Coder, Apache-2.0.">
          <a className="inline-flex items-center gap-1 text-[12.5px] text-violet-300 hover:text-violet-200"
            href="https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct" target="_blank" rel="noreferrer">
            Model card <ExternalLink className="h-3.5 w-3.5" />
          </a>
        </Row>
        <Row label="llama.cpp" hint="The inference engine that runs GGUF models (MIT licence).">
          <a className="inline-flex items-center gap-1 text-[12.5px] text-violet-300 hover:text-violet-200"
            href="https://github.com/ggml-org/llama.cpp" target="_blank" rel="noreferrer">
            Project <ExternalLink className="h-3.5 w-3.5" />
          </a>
        </Row>
        <Row label="NVIDIA CUDA runtime libraries" hint="cuBLAS/cuDART redistributables, included only in GPU builds and used under the NVIDIA CUDA Toolkit EULA; MIT-licensed alternatives exist for CPU-only packages.">
          <span className="text-[12px] text-slate-400">Redistributable</span>
        </Row>
        <Row label="Ollama (optional)" hint="If you already have Ollama installed, the app can serve models from it instead of its own runtime.">
          <a className="inline-flex items-center gap-1 text-[12.5px] text-violet-300 hover:text-violet-200"
            href="https://ollama.com" target="_blank" rel="noreferrer">
            ollama.com <ExternalLink className="h-3.5 w-3.5" />
          </a>
        </Row>
      </Card>
    </>
  );
}

function DiagnosticsSection({ env, models, isDesktop, bootLog, onLoadBootLog, onCopy, copied, onOpenLogs, onReload, diagnostics }: {
  env: EnvReport | null; models: ModelState | null; isDesktop: boolean; bootLog: string;
  onLoadBootLog: () => void; onCopy: (label: string, text: string) => void; copied: string | null;
  onOpenLogs: () => void; onReload: () => void; diagnostics: string;
}) {
  const issues = [...(env?.issues || []), ...(models?.issues || [])];

  return (
    <>
      <Card title="Environment check"
        hint="The same check the desktop shell runs before opening, available on demand.">
        <Row label={env?.ok && (models?.ok ?? true) ? 'Everything needed is present' : `${issues.length} item${issues.length === 1 ? '' : 's'} to review`}
          hint="Runs without a network connection and reports rather than blocks.">
          {env?.ok && (models?.ok ?? true)
            ? <Chip tone="ok"><Check className="h-3 w-3" /> healthy</Chip>
            : <Chip tone="warn"><TriangleAlert className="h-3 w-3" /> attention</Chip>}
        </Row>
        <ul className="space-y-2">
          {issues.map((issue, i) => (
            <li key={i} className="flex gap-2 text-[12.5px] text-amber-200/90">
              <Info className="mt-0.5 h-4 w-4 shrink-0" /> {issue}
            </li>
          ))}
          {issues.length === 0 && (
            <li className="text-[12.5px] text-slate-500">No issues reported by the backend or the model inventory.</li>
          )}
        </ul>
        <div className="flex flex-wrap gap-2 pt-1">
          <GhostButton onClick={onReload}><RefreshCw className="h-3.5 w-3.5" /> Run check again</GhostButton>
          <GhostButton onClick={() => onCopy('diag', diagnostics)}>
            <Clipboard className="h-3.5 w-3.5" /> {copied === 'diag' ? 'Copied' : 'Copy diagnostics'}
          </GhostButton>
          {isDesktop && <GhostButton onClick={onOpenLogs}><FolderOpen className="h-3.5 w-3.5" /> Open log folder</GhostButton>}
        </div>
      </Card>

      <Card title="This build">
        <div className="grid gap-3 sm:grid-cols-2">
          {[
            { k: 'Version', v: env?.backend?.build?.label || 'source run' },
            { k: 'Backend', v: env?.backend?.status || '—' },
            { k: 'Packaged', v: env ? (env.backend.frozen ? 'yes (frozen bundle)' : 'no (source)') : '—' },
            { k: 'Interface', v: env?.ui?.built ? 'built and served locally' : 'not built' },
          ].map(({ k, v }) => (
            <div key={k} className="rounded-xl border border-white/[0.06] bg-white/[0.02] px-3.5 py-3">
              <div className="text-[11px] uppercase tracking-wide text-slate-500">{k}</div>
              <div className="mt-1 break-all font-mono text-[12.5px] text-slate-200">{v}</div>
            </div>
          ))}
        </div>
      </Card>

      {isDesktop && (
        <Card title="Startup log" hint="The exact output of this launch: backend discovery, port, model runtime, errors.">
          <div className="flex flex-wrap gap-2">
            <GhostButton onClick={onLoadBootLog}><RefreshCw className="h-3.5 w-3.5" /> Load log</GhostButton>
            <GhostButton onClick={() => onCopy('bootlog', bootLog || '')}>
              <Clipboard className="h-3.5 w-3.5" /> {copied === 'bootlog' ? 'Copied' : 'Copy'}
            </GhostButton>
          </div>
          <pre className="max-h-72 overflow-auto rounded-xl border border-white/[0.06] bg-black/40 p-3 text-[11.5px] leading-relaxed text-slate-400 whitespace-pre-wrap">
            {bootLog || 'Nothing loaded yet — press Load log.'}
          </pre>
        </Card>
      )}
    </>
  );
}

const SHORTCUTS: { keys: string; what: string }[] = [
  { keys: 'Ctrl / Cmd + O', what: 'Open a project folder' },
  { keys: 'Ctrl / Cmd + ,', what: 'Open Settings (this page)' },
  { keys: 'Enter', what: 'Send the prompt in the builder' },
  { keys: 'Shift + Enter', what: 'New line inside the prompt' },
  { keys: 'Esc', what: 'Clear the selected element in the preview' },
  { keys: 'Ctrl / Cmd + R', what: 'Reload the window' },
  { keys: 'Ctrl + Shift + I', what: 'Toggle developer tools' },
  { keys: 'Ctrl / Cmd + + / - / 0', what: 'Zoom in, zoom out, reset zoom' },
  { keys: 'F11', what: 'Full screen' },
  { keys: 'Ctrl / Cmd + Q', what: 'Quit' },
];

function ShortcutsSection() {
  return (
    <Card title="Keyboard shortcuts"
      hint="Desktop-app shortcuts come from the application menu; the builder ones work everywhere.">
      <ul className="divide-y divide-white/[0.05]">
        {SHORTCUTS.map((s) => (
          <li key={s.keys} className="flex items-center justify-between gap-4 py-2.5">
            <span className="text-[13px] text-slate-300">{s.what}</span>
            <kbd className="rounded-md border border-white/[0.1] bg-white/[0.05] px-2 py-1 font-mono text-[11.5px] text-slate-200">
              {s.keys}
            </kbd>
          </li>
        ))}
      </ul>
      <p className="text-[12px] text-slate-500">
        On macOS, use Cmd where Ctrl is written. Shortcuts that belong to the window
        are handled by the operating system's menu bar and can be remapped there.
      </p>
    </Card>
  );
}
