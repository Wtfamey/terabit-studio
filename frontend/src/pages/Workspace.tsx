import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import {
  FolderOpen, FileCode2, Save, RefreshCw, Sparkles, Check, ChevronRight,
  AlertTriangle, Loader2, X, FolderTree, FilePlus2, Replace, ShieldCheck,
} from 'lucide-react';
import { API_BASE, ENDPOINTS } from '../config';
import { Wordmark } from '../components/Brand';

interface WsFile { path: string; size: number; language: string }
interface Tree { id: string; root: string; name: string; files: WsFile[]; truncated: boolean }
interface Change { path: string; state: 'new' | 'replace'; bytes: number }
interface GenResult {
  files: { path: string; content: string }[];
  changes: Change[];
  context_files_sent: number;
  bundle_ok: boolean;
  personalisation?: { score: number; name_hits: number; has_name: boolean };
  app_name?: string;
}

/** The desktop shell's folder picker. Absent in a plain browser, where the
 *  user types the path instead -- the backend does the work either way. */
declare global {
  interface Window {
    terabit?: {
      baseUrl(): Promise<string>;
      env(): Promise<unknown>;
      bootLog(): Promise<string[]>;
      openExternal(url: string): Promise<void>;
      chooseFolder(): Promise<{ canceled: boolean; path?: string }>;
      onBootLog(cb: (line: string) => void): () => void;
    };
  }
}

const ws = (id: string, rest: string) => `${API_BASE}/api/workspace/${id}/${rest}`;

/** Errors arrive as {"detail": "..."} from FastAPI; show the reason, because
 *  every refusal in the workspace API says what was refused and why. */
function reasonOf(err: unknown): string {
  const d = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof d === 'string') return d;
  if (Array.isArray(d) && d.length) return JSON.stringify(d);
  return (err as Error)?.message || 'Something went wrong.';
}

export function Workspace() {
  const navigate = useNavigate();
  const [tree, setTree] = useState<Tree | null>(null);
  const [manualPath, setManualPath] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [content, setContent] = useState('');
  const [original, setOriginal] = useState('');
  const [note, setNote] = useState<{ kind: 'ok' | 'bad' | 'busy'; text: string } | null>(null);
  const [prompt, setPrompt] = useState('');
  const [busy, setBusy] = useState(false);
  const [plan, setPlan] = useState<GenResult | null>(null);
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  const [filter, setFilter] = useState('');

  const dirty = content !== original;

  const open = useCallback(async (path: string) => {
    setNote({ kind: 'busy', text: `Opening ${path}...` });
    try {
      const { data } = await axios.post<Tree>(ENDPOINTS.workspaceOpen, { path });
      setTree(data);
      setPlan(null);
      setSelected(null);
      setNote({
        kind: 'ok',
        text: `${data.files.length} file${data.files.length === 1 ? '' : 's'}` +
          (data.truncated ? ' (listing truncated)' : ''),
      });
    } catch (err) {
      setTree(null);
      setNote({ kind: 'bad', text: reasonOf(err) });
    }
  }, []);

  const pickFolder = useCallback(async () => {
    if (!window.terabit) {
      setNote({ kind: 'bad', text: 'Type the folder path to open it in a browser.' });
      return;
    }
    const result = await window.terabit.chooseFolder();
    if (result.canceled || !result.path) return;
    setManualPath(result.path);
    await open(result.path);
  }, [open]);

  const load = useCallback(async (path: string) => {
    setNote({ kind: 'busy', text: `Reading ${path}...` });
    try {
      const { data } = await axios.get(ws(tree!.id, 'file'), { params: { path } });
      if (data.binary || data.too_large) {
        setContent('');
        setOriginal('');
        setNote({ kind: 'bad', text: data.message });
        setSelected(path);
        return;
      }
      setContent(data.content);
      setOriginal(data.content);
      setSelected(path);
      setNote(null);
    } catch (err) {
      setNote({ kind: 'bad', text: reasonOf(err) });
    }
  }, [tree]);

  const save = useCallback(async () => {
    if (!tree || !selected) return;
    setBusy(true);
    try {
      const { data } = await axios.put(ws(tree.id, 'file'), {
        path: selected, content,
      });
      setOriginal(content);
      setNote({
        kind: 'ok',
        text: `${data.created ? 'Created' : 'Saved'} ${selected} (${data.bytes} bytes)` +
          (data.previous !== null && data.previous !== undefined ? ' — Ctrl+Z restores the previous version' : ''),
      });
    } catch (err) {
      setNote({ kind: 'bad', text: reasonOf(err) });
    } finally {
      setBusy(false);
    }
  }, [tree, selected, content]);

  const generate = useCallback(async () => {
    if (!tree || !prompt.trim()) return;
    setBusy(true);
    setPlan(null);
    setNote({ kind: 'busy', text: 'Generating… a full run takes minutes on a local model, nothing is written yet.' });
    try {
      const { data } = await axios.post<GenResult>(ws(tree.id, 'generate'), {
        prompt, use_project_context: true,
      });
      setPlan(data);
      // Everything is pre-ticked except replacements: the folder the user
      // opened is usually not a React app, so silently overwriting it is the
      // wrong default.
      setPicked(Object.fromEntries(data.changes.map((c) => [c.path, c.state === 'new'])));
      setNote({
        kind: 'ok',
        text: `${data.changes.length} file${data.changes.length === 1 ? '' : 's'} ready` +
          ` (${data.context_files_sent} project files used as context) — review, then apply.`,
      });
    } catch (err) {
      setNote({ kind: 'bad', text: reasonOf(err) });
    } finally {
      setBusy(false);
    }
  }, [tree, prompt]);

  const apply = useCallback(async (overwrite: boolean) => {
    if (!tree || !plan) return;
    const files = plan.files.filter((f) => picked[f.path]);
    if (!files.length) {
      setNote({ kind: 'bad', text: 'Nothing is ticked.' });
      return;
    }
    setBusy(true);
    try {
      const { data } = await axios.post(ws(tree.id, 'apply'), { files, overwrite });
      const parts = [`${data.written.length} written`];
      if (data.skipped.length) parts.push(`${data.skipped.length} skipped (already exists)`);
      if (data.failed.length) parts.push(`${data.failed.length} refused: ${data.failed[0].error}`);
      setNote({ kind: data.failed.length ? 'bad' : 'ok', text: parts.join(' · ') });
      await open(tree.root);
      setPlan(null);
    } catch (err) {
      setNote({ kind: 'bad', text: reasonOf(err) });
    } finally {
      setBusy(false);
    }
  }, [tree, plan, picked, open]);

  // Ctrl+S saves. The editor is a plain textarea on purpose: the point of
  // this screen is the folder, and a real editor is a separate concern.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault();
        if (dirty && !busy) void save();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [dirty, busy, save]);

  const visible = useMemo(() => {
    if (!tree) return [];
    const q = filter.trim().toLowerCase();
    const list = q ? tree.files.filter((f) => f.path.toLowerCase().includes(q)) : tree.files;
    return list.slice(0, 800);
  }, [tree, filter]);

  const ticked = plan ? plan.changes.filter((c) => picked[c.path]).length : 0;

  return (
    <div className="flex h-screen flex-col bg-[#0b0b0f] text-slate-200">
      <header className="flex items-center gap-3 border-b border-white/10 px-4 py-2.5">
        <button onClick={() => navigate('/')} className="hover:opacity-80" title="Home">
          <Wordmark />
        </button>
        <span className="text-sm text-slate-400">Workspace</span>
        {tree && (
          <span className="flex min-w-0 items-center gap-1.5 rounded-md bg-white/5 px-2.5 py-1 text-xs text-slate-300">
            <FolderOpen size={13} className="shrink-0" />
            <span className="truncate" title={tree.root}>{tree.root}</span>
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {tree && (
            <button onClick={() => void open(tree.root)} title="Rescan the folder"
              className="rounded-md p-2 text-slate-400 hover:bg-white/5 hover:text-slate-200">
              <RefreshCw size={15} />
            </button>
          )}
          <button onClick={() => void pickFolder()}
            className="flex items-center gap-2 rounded-md bg-indigo-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-400">
            <FolderOpen size={15} /> Open folder
          </button>
        </div>
      </header>

      {!tree && (
        <div className="flex flex-1 items-center justify-center p-8">
          <div className="w-full max-w-lg">
            <FolderTree size={34} className="mb-4 text-slate-500" />
            <h2 className="mb-1.5 text-lg font-medium text-slate-100">
              Point this at a real folder
            </h2>
            <p className="mb-5 text-sm leading-relaxed text-slate-400">
              Terabit reads the files, generates against what is actually there,
              and shows you every change before anything is written. Paths that
              point outside the folder are refused.
            </p>
            <div className="flex gap-2">
              <input
                value={manualPath}
                onChange={(e) => setManualPath(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && void open(manualPath)}
                placeholder="C:\Users\you\projects\my-thing"
                className="min-w-0 flex-1 rounded-md border border-white/10 bg-black/30 px-3 py-2 text-sm outline-none focus:border-indigo-500"
              />
              <button onClick={() => void open(manualPath)} disabled={!manualPath.trim()}
                className="rounded-md bg-white/10 px-3 text-sm hover:bg-white/15 disabled:opacity-40">
                Open
              </button>
            </div>
            {note?.kind === 'bad' && (
              <p className="mt-3 flex items-start gap-2 text-xs text-red-400">
                <AlertTriangle size={14} className="mt-px shrink-0" /> {note.text}
              </p>
            )}
          </div>
        </div>
      )}

      {tree && (
        <div className="flex min-h-0 flex-1">
          <aside className="flex w-64 shrink-0 flex-col border-r border-white/10">
            <div className="border-b border-white/10 p-2">
              <input value={filter} onChange={(e) => setFilter(e.target.value)}
                placeholder="Filter files"
                className="w-full rounded bg-black/30 px-2 py-1.5 text-xs outline-none focus:ring-1 focus:ring-indigo-500" />
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto py-1">
              {visible.map((f) => (
                <button key={f.path} onClick={() => void load(f.path)}
                  className={`flex w-full items-center gap-1.5 px-3 py-1 text-left text-xs hover:bg-white/5 ${
                    selected === f.path ? 'bg-indigo-500/15 text-indigo-200' : 'text-slate-400'
                  }`}
                  title={f.path}>
                  <FileCode2 size={12} className="shrink-0 opacity-60" />
                  <span className="truncate">{f.path}</span>
                  <span className="ml-auto shrink-0 text-[10px] text-slate-600">
                    {f.size > 1024 ? `${Math.round(f.size / 1024)}k` : f.size}
                  </span>
                </button>
              ))}
              {!visible.length && (
                <p className="px-3 py-2 text-xs text-slate-600">No files match.</p>
              )}
            </div>
          </aside>

          <main className="flex min-w-0 flex-1 flex-col">
            <div className="flex items-center gap-2 border-b border-white/10 px-3 py-2">
              <span className="truncate text-xs text-slate-400">
                {selected || 'No file open'}
              </span>
              {dirty && <span className="shrink-0 text-[10px] text-amber-400">unsaved</span>}
              <button onClick={() => void save()} disabled={!dirty || busy}
                className="ml-auto flex items-center gap-1.5 rounded-md bg-white/10 px-2.5 py-1 text-xs hover:bg-white/15 disabled:opacity-30">
                <Save size={13} /> Save <kbd className="text-[10px] text-slate-500">Ctrl+S</kbd>
              </button>
            </div>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              spellCheck={false}
              placeholder="Pick a file on the left."
              className="min-h-0 flex-1 resize-none bg-black/30 p-3 font-mono text-xs leading-relaxed outline-none"
            />
          </main>

          <aside className="flex w-80 shrink-0 flex-col border-l border-white/10">
            <div className="border-b border-white/10 p-3">
              <label className="mb-1.5 block text-xs font-medium text-slate-300">
                Build or change
              </label>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={4}
                placeholder="Describe what you want in this project…"
                className="w-full resize-none rounded-md border border-white/10 bg-black/30 p-2.5 text-xs leading-relaxed outline-none focus:border-indigo-500"
              />
              <button onClick={() => void generate()} disabled={busy || !prompt.trim()}
                className="mt-2 flex w-full items-center justify-center gap-2 rounded-md bg-indigo-500 px-3 py-2 text-xs font-medium text-white hover:bg-indigo-400 disabled:opacity-40">
                {busy ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                Generate into this folder
              </button>
            </div>

            {plan && (
              <div className="min-h-0 flex-1 overflow-y-auto">
                <div className="flex items-center gap-2 px-3 py-2 text-xs text-slate-400">
                  <ShieldCheck size={13} className="text-emerald-400" />
                  {ticked} of {plan.changes.length} ticked
                  <button onClick={() => void apply(false)}
                    className="ml-auto rounded bg-emerald-500/15 px-2 py-1 text-[11px] text-emerald-300 hover:bg-emerald-500/25">
                    Apply new only
                  </button>
                </div>
                {plan.changes.map((c) => (
                  <button
                    key={c.path}
                    onClick={() => setPicked((p) => ({ ...p, [c.path]: !p[c.path] }))}
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-white/5">
                    {picked[c.path]
                      ? <Check size={13} className="shrink-0 text-emerald-400" />
                      : <X size={13} className="shrink-0 text-slate-600" />}
                    {c.state === 'new'
                      ? <FilePlus2 size={12} className="shrink-0 text-sky-400" />
                      : <Replace size={12} className="shrink-0 text-amber-400" />}
                    <span className="truncate text-slate-300">{c.path}</span>
                    <ChevronRight size={11} className="ml-auto shrink-0 text-slate-600" />
                  </button>
                ))}
              </div>
            )}

            {note && (
              <div className={`flex items-start gap-2 border-t border-white/10 px-3 py-2 text-[11px] leading-relaxed ${
                note.kind === 'bad' ? 'text-red-400'
                  : note.kind === 'busy' ? 'text-slate-400' : 'text-emerald-400'
              }`}>
                {busy && <Loader2 size={12} className="mt-px shrink-0 animate-spin" />}
                <span className="min-w-0 break-words">{note.text}</span>
              </div>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
