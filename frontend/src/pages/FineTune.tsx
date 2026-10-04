import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { ENDPOINTS } from '../config';
import {
  GraduationCap, RefreshCw, Database, Play, Square, CheckCircle2, XCircle, Loader2, Cpu,
  Rocket, History, Boxes, CircleDashed, MinusCircle
} from 'lucide-react';

type JobKind = 'dataset' | 'train' | 'retrain' | null;

interface JobState {
  kind: JobKind;
  status: string;
  started?: number;
  finished?: number;
  error?: string;
}

interface Phase {
  name: string;
  label: string;
  status: 'pending' | 'running' | 'done' | 'failed' | 'skipped';
  detail?: string;
  started?: number;
  finished?: number;
}

interface Candidate {
  tag: string;
  s6: number;
  n: number;
  at: string;
  gate_pass: boolean;
}

interface PipelineState {
  running: boolean;
  candidate: string;
  error: string;
  expected: { name: string; label: string }[];
  phases: Phase[];
  results: { s6?: number; gate_pass?: boolean; eval_file?: string };
  train_progress: { step: number; total: number; pct: number } | null;
  live: { tag?: string; s6?: number; n?: number; at?: string; note?: string };
  candidates: Candidate[];
  job_running: boolean;
  log_tails: Record<string, string[]>;
  hardware: { vram_free_mb: number | null };
}

interface Stats {
  examples: number;
  trainable: number;
  dropped_over_cap: number;
  median_tokens: number | null;
  max_tokens: number | null;
  planned_steps: number;
  est_minutes: number;
  export_minutes: number;
  est_total_minutes: number;
  sec_per_step: number;
}

const phaseIcon = (status: Phase['status']) => {
  if (status === 'running') return <Loader2 className="w-3.5 h-3.5 text-violet-400 animate-spin" />;
  if (status === 'done') return <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />;
  if (status === 'failed') return <XCircle className="w-3.5 h-3.5 text-red-400" />;
  if (status === 'skipped') return <MinusCircle className="w-3.5 h-3.5 text-amber-400/70" />;
  return <CircleDashed className="w-3.5 h-3.5 text-gray-600" />;
};

const fmtMinutes = (m: number) => (m >= 60 ? `${(m / 60).toFixed(1)} h` : `${Math.round(m)} min`);

export function FineTune() {
  const navigate = useNavigate();
  const [job, setJob] = useState<JobState>({ kind: null, status: '' });
  const [running, setRunning] = useState(false);
  const [logTail, setLogTail] = useState<string[]>([]);
  const [pipeline, setPipeline] = useState<PipelineState | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [models, setModels] = useState<{ name: string; size: string }[]>([]);
  const [count, setCount] = useState(25);
  const [epochs, setEpochs] = useState(3);
  const [seqLen, setSeqLen] = useState(3584);
  const [evalLimit, setEvalLimit] = useState(4);
  const [autoPromote, setAutoPromote] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [statusRes, pipelineRes, modelsRes] = await Promise.all([
        axios.get(ENDPOINTS.finetuneStatus),
        axios.get(ENDPOINTS.finetunePipeline),
        axios.get(ENDPOINTS.finetuneModels),
      ]);
      setJob({
        kind: statusRes.data.job?.kind ?? null,
        status: statusRes.data.job?.status ?? '',
        started: statusRes.data.job?.started,
        finished: statusRes.data.job?.finished,
        error: statusRes.data.job?.error,
      });
      setRunning(statusRes.data.running);
      setLogTail(statusRes.data.log_tail || []);
      setPipeline(pipelineRes.data);
      setModels(modelsRes.data.models || []);
      setError(null);
    } catch {
      setError('Backend unreachable — is it running on port 8000?');
    }
  }, []);

  const refreshStats = useCallback(async () => {
    try {
      const r = await axios.get(ENDPOINTS.finetuneStats, { params: { max_seq_length: seqLen, epochs } });
      setStats(r.data);
    } catch { /* stats are advisory only */ }
  }, [seqLen, epochs]);

  useEffect(() => {
    refresh();
    pollRef.current = window.setInterval(refresh, 5000);
    return () => { if (pollRef.current) window.clearInterval(pollRef.current); };
  }, [refresh]);

  useEffect(() => { refreshStats(); }, [refreshStats]);

  const start = async (kind: 'dataset' | 'train' | 'retrain') => {
    setError(null);
    try {
      if (kind === 'dataset') await axios.post(ENDPOINTS.finetuneDataset, { count });
      else if (kind === 'train') await axios.post(ENDPOINTS.finetuneTrain, { epochs, max_seq_length: seqLen });
      else await axios.post(ENDPOINTS.finetuneRetrain, {
        epochs, max_seq_length: seqLen, eval_limit: evalLimit, auto_promote: autoPromote,
      });
      await refresh();
    } catch (e: any) {
      setError(e?.response?.data?.detail || `Failed to start ${kind} job`);
    }
  };

  const cancel = async () => {
    try { await axios.post(ENDPOINTS.finetuneCancel); await refresh(); }
    catch (e: any) { setError(e?.response?.data?.detail || 'Cancel failed'); }
  };

  const statusIcon = running
    ? <Loader2 className="w-4 h-4 text-violet-400 animate-spin" />
    : job.status === 'done'
      ? <CheckCircle2 className="w-4 h-4 text-emerald-400" />
      : job.status === 'failed' || job.status === 'cancelled'
        ? <XCircle className="w-4 h-4 text-red-400" />
        : <Cpu className="w-4 h-4 text-gray-500" />;

  // Merge the static phase list with whatever the pipeline has reported.
  const actual = new Map((pipeline?.phases || []).map(p => [p.name, p]));
  const timeline: Phase[] = (pipeline?.expected || []).map(e =>
    actual.get(e.name) || { name: e.name, label: e.label, status: 'pending' as const });
  const trainProgress = pipeline?.train_progress;

  // Merge the job tail with each phase's own stream (merge/convert/quantize/
  // serve/eval) so a long export or eval is observable while it runs, not
  // only once the subprocess exits.
  const streamLogs = Object.entries(pipeline?.log_tails || {})
    .filter(([, lines]) => (lines?.length || 0) > 0)
    .map(([name, lines]) => `── ${name} ──\n${lines.join('\n')}`);
  const logView = [
    ...streamLogs,
    ...(logTail.length > 0 ? [`── job ──\n${logTail.join('\n')}`] : []),
  ].join('\n');

  return (
    <div className="min-h-screen bg-[#07070d] relative overflow-hidden">
      <div className="fixed inset-0 pointer-events-none">
        <div className="absolute top-[-15%] left-[-5%] w-[600px] h-[600px] bg-violet-600/15 rounded-full blur-[140px]" />
        <div className="absolute bottom-[-10%] right-[-5%] w-[500px] h-[500px] bg-cyan-500/15 rounded-full blur-[120px]" />
      </div>

      <div className="relative z-10 max-w-5xl mx-auto px-6 py-8">
        <div className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-gradient-to-br from-violet-600 to-cyan-600 rounded-xl">
              <GraduationCap className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-gray-100">Teach Terabit your patterns</h1>
              <p className="text-xs text-gray-500">
                In-house fine-tuning: teacher data → QLoRA → GGUF → eval gate → hot-swap promote
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => navigate('/')}
              className="px-3 py-1.5 bg-white/5 border border-white/10 rounded-lg text-xs text-gray-400 hover:text-white hover:bg-white/10 transition-all"
            >Home</button>
            <button
              onClick={() => navigate('/builder')}
              className="px-3 py-1.5 bg-white/5 border border-white/10 rounded-lg text-xs text-gray-400 hover:text-white hover:bg-white/10 transition-all"
            >Builder</button>
          </div>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-xs">{error}</div>
        )}
        {pipeline?.error && (
          <div className="mb-4 p-3 bg-amber-500/10 border border-amber-500/20 rounded-xl text-amber-300 text-xs">
            {pipeline.error}
          </div>
        )}

        {/* Live model + headroom */}
        <div className="grid md:grid-cols-3 gap-4 mb-6">
          <div className="bg-white/[0.02] border border-white/[0.06] rounded-2xl p-5">
            <div className="flex items-center gap-2 mb-2">
              <Rocket className="w-4 h-4 text-emerald-400" />
              <h2 className="text-sm font-semibold text-gray-200">Serving now</h2>
            </div>
            <p className="font-mono text-xs text-emerald-300 mb-1">{pipeline?.live?.tag || '—'}</p>
            <p className="text-[11px] text-gray-500">
              gate S6 {pipeline?.live?.s6 ?? '—'}% over {pipeline?.live?.n ?? '—'} prompts
            </p>
          </div>
          <div className="bg-white/[0.02] border border-white/[0.06] rounded-2xl p-5">
            <div className="flex items-center gap-2 mb-2">
              <Database className="w-4 h-4 text-cyan-400" />
              <h2 className="text-sm font-semibold text-gray-200">Training data</h2>
            </div>
            <p className="text-xs text-gray-300">
              {stats ? `${stats.examples} examples · ${stats.trainable} fit ${seqLen} tokens` : '…'}
            </p>
            <p className="text-[11px] text-gray-500 mt-1">
              {stats
                ? `${stats.planned_steps} steps ≈ ${fmtMinutes(stats.est_minutes)} train + ${Math.round(stats.export_minutes)} min export ≈ ${fmtMinutes(stats.est_total_minutes)} total`
                : 'loading stats'}
            </p>
            {stats && stats.dropped_over_cap > 0 && (
              <p className="text-[11px] text-amber-400/80 mt-1">
                {stats.dropped_over_cap} dropped (over cap — keep them small rather than truncated)
              </p>
            )}
          </div>
          <div className="bg-white/[0.02] border border-white/[0.06] rounded-2xl p-5">
            <div className="flex items-center gap-2 mb-2">
              <Cpu className="w-4 h-4 text-violet-400" />
              <h2 className="text-sm font-semibold text-gray-200">GPU</h2>
            </div>
            <p className="text-xs text-gray-300">
              {pipeline?.hardware?.vram_free_mb != null
                ? `${Math.round(pipeline.hardware.vram_free_mb)} MB VRAM free`
                : 'nvidia-smi unavailable'}
            </p>
            <p className="text-[11px] text-gray-500 mt-1">
              the pipeline unloads the served model before training so QLoRA gets the VRAM
            </p>
          </div>
        </div>

        {/* One-click retrain */}
        <div className="bg-white/[0.02] border border-violet-500/20 rounded-2xl p-5 mb-6">
          <div className="flex items-center gap-2 mb-3">
            <Rocket className="w-4 h-4 text-violet-400" />
            <h2 className="text-sm font-semibold text-gray-200">Retrain &amp; promote (one click)</h2>
            <span className="text-[10px] uppercase tracking-wide text-violet-300/80 bg-violet-500/10 border border-violet-500/20 rounded px-1.5 py-0.5">
              {pipeline?.running ? `running ${pipeline.candidate}` : 'idle'}
            </span>
          </div>
          <p className="text-xs text-gray-500 mb-4">
            train → export GGUF → <span className="font-mono">ollama create</span> a candidate tag → eval it through the live
            backend → gate against the current model → hot-swap promote (no restart). Cancel-safe between and during phases.
          </p>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
            <label className="text-[11px] text-gray-400">
              Epochs
              <input
                type="number" min={1} max={10} value={epochs}
                onChange={e => setEpochs(Math.max(1, Math.min(10, Number(e.target.value) || 1)))}
                disabled={running}
                className="mt-1 w-full bg-white/5 border border-white/10 rounded-lg px-2 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-violet-500/50 disabled:opacity-50"
              />
            </label>
            <label className="text-[11px] text-gray-400">
              Max seq length
              <input
                type="number" min={1024} max={8192} step={128} value={seqLen}
                onChange={e => setSeqLen(Math.max(1024, Math.min(8192, Number(e.target.value) || 3584)))}
                disabled={running}
                className="mt-1 w-full bg-white/5 border border-white/10 rounded-lg px-2 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-violet-500/50 disabled:opacity-50"
              />
            </label>
            <label className="text-[11px] text-gray-400">
              Eval prompts
              <input
                type="number" min={1} max={10} value={evalLimit}
                onChange={e => setEvalLimit(Math.max(1, Math.min(10, Number(e.target.value) || 4)))}
                disabled={running}
                className="mt-1 w-full bg-white/5 border border-white/10 rounded-lg px-2 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-violet-500/50 disabled:opacity-50"
              />
              <span className={`text-[10px] ${evalLimit < 10 ? 'text-amber-500/70' : 'text-gray-600'}`}>
                {evalLimit < 10 ? 'quick gate (~9 min each)' : 'full 10-prompt suite'}
              </span>
            </label>
            <label className="text-[11px] text-gray-400 flex flex-col justify-between">
              Auto-promote on pass
              <button
                onClick={() => setAutoPromote(v => !v)}
                disabled={running}
                className={`mt-1 w-full px-2 py-1.5 rounded-lg text-xs border transition-all disabled:opacity-50 ${
                  autoPromote
                    ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-300'
                    : 'bg-white/5 border-white/10 text-gray-400'
                }`}
              >{autoPromote ? 'enabled (hot-swap)' : 'off (eval only)'}</button>
            </label>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => start('retrain')} disabled={running}
              className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-violet-600 to-cyan-600 rounded-xl text-sm font-medium text-white hover:opacity-90 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
            ><Rocket className="w-4 h-4" /> Start full retrain</button>
            {running && (
              <button
                onClick={cancel}
                className="flex items-center gap-1.5 px-3 py-2 bg-red-500/15 border border-red-500/30 rounded-lg text-xs text-red-300 hover:bg-red-500/25 transition-all"
              ><Square className="w-3 h-3" /> Cancel</button>
            )}
            {stats && (
              <span className="text-[11px] text-gray-500">
                ≈ {fmtMinutes(stats.est_total_minutes)} + ~9 min per gated prompt
              </span>
            )}
          </div>

          {/* Phase timeline */}
          {timeline.length > 0 && (
            <div className="mt-5 space-y-2">
              {timeline.map(p => (
                <div key={p.name} className="flex items-start gap-2 text-xs">
                  <div className="mt-0.5">{phaseIcon(p.status)}</div>
                  <div className="flex-1">
                    <span className={p.status === 'pending' ? 'text-gray-600' : 'text-gray-300'}>{p.label}</span>
                    {p.detail && <span className="text-gray-500"> — {p.detail}</span>}
                  </div>
                </div>
              ))}
            </div>
          )}

          {trainProgress && (
            <div className="mt-4">
              <div className="flex justify-between text-[11px] text-gray-500 mb-1">
                <span>training step {trainProgress.step}/{trainProgress.total}</span>
                <span>{trainProgress.pct}%</span>
              </div>
              <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-violet-500 to-cyan-500 transition-all"
                  style={{ width: `${trainProgress.pct ?? 0}%` }}
                />
              </div>
            </div>
          )}
        </div>

        {/* Smaller jobs */}
        <div className="grid md:grid-cols-2 gap-4 mb-6">
          <div className="bg-white/[0.02] border border-white/[0.06] rounded-2xl p-5">
            <div className="flex items-center gap-2 mb-3">
              <Database className="w-4 h-4 text-cyan-400" />
              <h2 className="text-sm font-semibold text-gray-200">1 · Generate teacher data</h2>
            </div>
            <p className="text-xs text-gray-500 mb-4">
              New examples from the quota-rotating Gemini chain, merge-safe into training_data.jsonl. Free tier: ~20 req/day/model.
            </p>
            <div className="flex items-center gap-3 mb-4">
              <label className="text-xs text-gray-400">Examples</label>
              <input
                type="number" min={1} max={200} value={count}
                onChange={e => setCount(Math.max(1, Math.min(200, Number(e.target.value) || 1)))}
                disabled={running}
                className="w-20 bg-white/5 border border-white/10 rounded-lg px-2 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-violet-500/50 disabled:opacity-50"
              />
            </div>
            <button
              onClick={() => start('dataset')} disabled={running}
              className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-cyan-500/20 border border-cyan-500/30 rounded-xl text-sm font-medium text-cyan-300 hover:bg-cyan-500/30 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
            ><Play className="w-4 h-4" /> Start dataset job</button>
          </div>

          <div className="bg-white/[0.02] border border-white/[0.06] rounded-2xl p-5">
            <div className="flex items-center gap-2 mb-3">
              <Cpu className="w-4 h-4 text-violet-400" />
              <h2 className="text-sm font-semibold text-gray-200">Training only (no gate/promote)</h2>
            </div>
            <p className="text-xs text-gray-500 mb-4">
              Just the QLoRA run + GGUF export to D:/terabit-retrain, for experimenting with seq length or epochs before
              committing to a promoted model.
            </p>
            <button
              onClick={() => start('train')} disabled={running}
              className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-violet-500/20 border border-violet-500/30 rounded-xl text-sm font-medium text-violet-300 hover:bg-violet-500/30 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
            ><Play className="w-4 h-4" /> Start training run</button>
          </div>
        </div>

        {/* Status + log */}
        <div className="bg-white/[0.02] border border-white/[0.06] rounded-2xl p-5 mb-6">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              {statusIcon}
              <h2 className="text-sm font-semibold text-gray-200">
                {running ? `Running: ${job.kind}` : job.status ? `Last job: ${job.kind ?? '?'} · ${job.status}` : 'Idle'}
              </h2>
            </div>
            <button
              onClick={refresh}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-white/5 border border-white/10 rounded-lg text-xs text-gray-400 hover:text-white hover:bg-white/10 transition-all"
            ><RefreshCw className="w-3 h-3" /> Refresh</button>
          </div>

          <div className="bg-black/40 border border-white/[0.06] rounded-xl p-3 font-mono text-[11px] leading-relaxed text-gray-400 max-h-64 overflow-y-auto whitespace-pre-wrap">
            {logView || 'No job output yet. Start a dataset or training job.'}
          </div>
        </div>

        {/* Gate history + model zoo */}
        <div className="grid md:grid-cols-2 gap-4">
          <div className="bg-white/[0.02] border border-white/[0.06] rounded-2xl p-5">
            <div className="flex items-center gap-2 mb-3">
              <History className="w-4 h-4 text-amber-400" />
              <h2 className="text-sm font-semibold text-gray-200">Gate history</h2>
            </div>
            {(pipeline?.candidates?.length || 0) === 0 ? (
              <p className="text-xs text-gray-500">No candidate evaluated yet.</p>
            ) : (
              <div className="space-y-2">
                {pipeline!.candidates.slice().reverse().map(c => (
                  <div key={`${c.tag}-${c.at}`} className="flex items-center justify-between text-xs">
                    <span className="font-mono text-gray-300">{c.tag}</span>
                    <span className={c.gate_pass ? 'text-emerald-400' : 'text-red-400'}>
                      S6 {c.s6}% · n={c.n} · {c.gate_pass ? 'passed' : 'failed'}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="bg-white/[0.02] border border-white/[0.06] rounded-2xl p-5">
            <div className="flex items-center gap-2 mb-3">
              <Boxes className="w-4 h-4 text-cyan-400" />
              <h2 className="text-sm font-semibold text-gray-200">Model zoo</h2>
            </div>
            {models.length === 0 ? (
              <p className="text-xs text-gray-500">ollama list unavailable.</p>
            ) : (
              <div className="space-y-1.5">
                {models.map(m => (
                  <div key={m.name} className="flex items-center justify-between text-xs">
                    <span className={`font-mono ${m.name.startsWith(pipeline?.live?.tag || '\u0000') ? 'text-emerald-300' : 'text-gray-400'}`}>
                      {m.name}
                    </span>
                    <span className="text-gray-600">{m.size}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
