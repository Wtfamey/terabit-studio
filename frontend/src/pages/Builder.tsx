import { useEffect, useState, useRef, useCallback } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { BrandProfile, Message, GeneratedFile, FileItem, ChatSession as ChatSessionType, UserAsset } from '../types';
import { FileExplorer } from '../components/FileExplorer';
import { CodeEditor } from '../components/CodeEditor';
import { PreviewFrame } from '../components/PreviewFrame';
import { AssetManager } from '../components/AssetManager';
import { PromptComposer } from '../components/PromptComposer';
import { AgentSteps } from '../components/AgentSteps';
import { VersionHistory, Version } from '../components/VersionHistory';
import { Wordmark } from '../components/Brand';
import { useAuth } from '../contexts/AuthContext';
import { getSettings, withLanguageDirective } from '../settings';
import axios from 'axios';
import { ENDPOINTS } from '../config';
import {
  Send, Sparkles, Bot, User, Loader2,
  AlertCircle, Download, Square, Plus, Clock, Trash2,
  LogIn, UserCircle, PanelLeftClose, PanelLeft, PanelRightClose, PanelRight,
  Code2, Eye, History, Undo2, Hammer, Lightbulb, Image, X, Pause, Play, ListTodo, GripVertical
} from 'lucide-react';

interface Snapshot {
  id: number;
  label: string;
  at: number;
  files: FileItem[];
  selectedFile: FileItem | null;
}

interface QueuedPrompt {
  id: number;
  prompt: string;
}

interface ElementSelection {
  label: string;
  text: string;
  detail?: string;
}

const STARTER_IDEAS = [
  { label: 'Restaurant site', prompt: 'A website for Casa Verde, a family-run Italian restaurant. Warm, appetising, with a menu, story and reservation form.' },
  { label: 'Product designer portfolio', prompt: 'A portfolio for a product designer: selected work, about, and a contact section. Warm minimal aesthetic.' },
  { label: 'SaaS landing page', prompt: 'A landing page for a developer-tools SaaS: hero, feature grid, pricing, testimonials, FAQ and a call to action.' },
  { label: 'Law firm site', prompt: 'A website for Hartwell & Sawyer, a boutique law firm. Trustworthy and calm, with practice areas, team and consultation booking.' },
];

export function Builder() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const state = location.state as {
    prompt: string; template: string | null; features: string;
    assets?: { url: string; filename: string; original_name: string; mime_type: string }[];
    brand?: BrandProfile;
  } | null;

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [files, setFiles] = useState<FileItem[]>([]);
  const [selectedFile, setSelectedFile] = useState<FileItem | null>(null);
  const [mode, setMode] = useState<'build' | 'plan'>('build');
  const [activeView, setActiveView] = useState<'preview' | 'code'>('preview');
  const [error, setError] = useState<string | null>(null);
  const [projectName, setProjectName] = useState('my-project');
  const [sessions, setSessions] = useState<ChatSessionType[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<number | null>(null);
  const [showSessions, setShowSessions] = useState(false);
  const [showFiles, setShowFiles] = useState(true);
  const [showVersions, setShowVersions] = useState(false);
  const [chatOpen, setChatOpen] = useState(true);
  const [versions, setVersions] = useState<Snapshot[]>([]);
  const [builderAssets, setBuilderAssets] = useState<UserAsset[]>([]);
  const [showAssets, setShowAssets] = useState(false);
  const [agentProgress, setAgentProgress] = useState<string[]>([]);
  const [selectedElement, setSelectedElement] = useState<ElementSelection | null>(null);
  const [queue, setQueue] = useState<QueuedPrompt[]>([]);
  const [queuePaused, setQueuePaused] = useState(false);
  const [dragId, setDragId] = useState<number | null>(null);

  const chatEndRef = useRef<HTMLDivElement>(null);
  const initialized = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const versionIdRef = useRef(0);
  const queueIdRef = useRef(0);
  const dequeueingRef = useRef(false);
  const inputRef = useRef('');

  const [sessionReady, setSessionReady] = useState(false);

  useEffect(() => { inputRef.current = input; }, [input]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, agentProgress.length]);

  useEffect(() => {
    if (user) {
      axios.get(ENDPOINTS.sessions).then(r => setSessions(r.data)).catch(() => {});
    }
  }, [user]);

  // Esc clears a pending element selection (mirrors Bolt's select affordance)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setSelectedElement(null); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // Create session on mount if logged in and have prompt
  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    (async () => {
      if (state?.assets) {
        try {
          const res = await axios.get(ENDPOINTS.assets);
          setBuilderAssets(res.data);
        } catch {}
      }
      if (user && state?.prompt && !currentSessionId) {
        try {
          const res = await axios.post(ENDPOINTS.sessions, { name: state.prompt.slice(0, 40) });
          setCurrentSessionId(res.data.id);
        } catch {}
      }
      setSessionReady(true);
      const initialMsg: Message = {
        role: 'assistant',
        content: state?.prompt
          ? `I'll build your **${state.template || 'business'}** system.`
          : "Hi! Describe the app you want to build, and I'll generate it for you.\n\nTip: type **@** to tag a file, use **Select** in the preview to target an element, or hit the **+** menu to enhance your prompt.",
      };
      setMessages([initialMsg]);
      if (state?.prompt) {
        handleGenerate(state.prompt, state.template || 'business-app', state.features);
      }
    })();
  }, []);

  const ensureSession = useCallback(async () => {
    if (!user || !sessionReady) return null;
    if (currentSessionId) return currentSessionId;
    try {
      const name = state?.prompt?.slice(0, 40) || 'New Chat';
      const res = await axios.post(ENDPOINTS.sessions, { name });
      setCurrentSessionId(res.data.id);
      return res.data.id;
    } catch { return null; }
  }, [user, currentSessionId, state, sessionReady]);

  const cleanPath = (p: string) => {
    return p
      .replace(/^[#\s`*]+/, '')
      .replace(/[#\s`*]+$/, '')
      .replace(/^(?:exact\/path\/to\/|path\/to\/|relative\/path\/|relative\/path\s+|file:\s*)/i, '')
      .replace(/^["']|["']$/g, '')
      .trim();
  };

  const parseFilesFromResponse = (response: string): GeneratedFile[] => {
    const patterns: RegExp[] = [
      /(?:^|\n)(?:#{1,6}\s*)?`?([a-zA-Z0-9_.-]+(?:\/[a-zA-Z0-9_.-]+)*\.(?:jsx?|tsx?|css|html|json|js|ts|py|env|yml|yaml|md|config\.js|config\.cjs))`?\s*\n```[\w]*\n([\s\S]*?)\n```/gi,
      /(?:^|\n)(?:#{1,6}\s*)?\*\*([a-zA-Z0-9_.-]+(?:\/[a-zA-Z0-9_.-]+)*\.(?:jsx?|tsx?|css|html|json))\*\*\s*\n```[\w]*\n([\s\S]*?)\n```/gi,
      /`([^`]+\.(?:jsx?|tsx?|css|html|json|js|ts))`\s*\n```[\w]*\n([\s\S]*?)```/gi,
    ];

    const items: GeneratedFile[] = [];
    const seenPaths = new Set<string>();

    for (const pattern of patterns) {
      let match;
      pattern.lastIndex = 0;
      while ((match = pattern.exec(response)) !== null) {
        const path = cleanPath(match[1]);
        const content = match[2]?.trim() || '';

        if (path && content && !seenPaths.has(path)) {
          seenPaths.add(path);
          items.push({ path, content });
        }
      }
    }

    return items;
  };

  const extractConversationalResponse = (response: string): string => {
    const firstCodeBlock = response.indexOf('```');
    if (firstCodeBlock === -1) return response;
    const beforeCode = response.substring(0, firstCodeBlock).trim();
    return beforeCode || 'I\'ve generated the code for your project.';
  };

  const buildFileTree = (genFiles: GeneratedFile[]): FileItem[] => {
    const root: FileItem[] = [];
    for (const gf of genFiles) {
      const parts = gf.path.split('/');
      let current = root;
      for (let i = 0; i < parts.length; i++) {
        const isFile = i === parts.length - 1;
        const existing = current.find(c => c.name === parts[i]);
        if (existing) {
          if (isFile) existing.content = gf.content;
          current = existing.children || [];
        } else {
          const item: FileItem = {
            name: parts[i],
            path: parts.slice(0, i + 1).join('/'),
            type: isFile ? 'file' : 'folder',
            children: isFile ? undefined : [],
            content: isFile ? gf.content : undefined,
          };
          current.push(item);
          if (!isFile) current = item.children!;
        }
      }
    }
    return root;
  };

  const flattenFiles = (items: FileItem[]): GeneratedFile[] => {
    const result: GeneratedFile[] = [];
    const walk = (list: FileItem[]) => {
      for (const item of list) {
        if (item.type === 'file' && item.content) result.push({ path: item.path, content: item.content });
        if (item.children) walk(item.children);
      }
    };
    walk(items);
    return result;
  };

  const updateFileContent = (path: string, content: string) => {
    const update = (items: FileItem[]): FileItem[] => items.map(item => {
      if (item.path === path && item.type === 'file') return { ...item, content };
      return item.children ? { ...item, children: update(item.children) } : item;
    });
    setFiles(previous => update(previous));
    setSelectedFile(previous => previous?.path === path ? { ...previous, content } : previous);
  };

  // ─── Version history (restore points, not just a single undo) ───
  const saveVersion = (label: string) => {
    const snap: Snapshot = {
      id: ++versionIdRef.current,
      label: label.length > 46 ? `${label.slice(0, 46)}...` : label,
      at: Date.now(),
      files: JSON.parse(JSON.stringify(files)),
      selectedFile: selectedFile ? { ...selectedFile } : null,
    };
    setVersions(prev => [...prev, snap]);
  };

  const handleRestore = (id: number) => {
    const idx = versions.findIndex(v => v.id === id);
    if (idx === -1) return;
    const v = versions[idx];
    setFiles(v.files);
    setSelectedFile(v.selectedFile);
    // Restoring rewinds the timeline to that point, so you continue from there.
    setVersions(prev => prev.slice(0, idx + 1));
    setMessages(prev => [...prev, { role: 'assistant', content: `Restored version "${v.label}". Build on from here.` }]);
  };

  const handleUndo = () => {
    if (versions.length < 2) return;
    handleRestore(versions[versions.length - 2].id);
  };

  const handleStop = () => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
      setStreaming(false);
      setLoading(false);
      setMessages(prev => [...prev, { role: 'assistant', content: 'Generation stopped.' }]);
    }
  };

  const handleDownload = async () => {
    const flat = flattenFiles(files);
    if (flat.length === 0) return;
    try {
      const res = await axios.post(ENDPOINTS.download, {
        files: flat,
        project_name: projectName,
      }, { responseType: 'blob' });
      const url = URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement('a');
      a.href = url;
      a.download = `${projectName}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch { setError('Download failed'); }
  };

  // ─── Prompt enhancement (uses the local model to rewrite the request) ───
  const enhancePrompt = useCallback(async (raw: string): Promise<string | null> => {
    const meta = [
      'You rewrite brief website requests into excellent, specific build prompts for an AI website generator.',
      'Rules: plain prose only, 2 to 4 sentences, no markdown, no bullet points, no commentary, no quotes.',
      'Cover: who the site is for, the visual style and colour mood, the exact sections needed,',
      'and any interactive or animation touches worth including.',
      '',
      'Request:',
      raw,
      '',
      'Rewritten prompt:',
    ].join('\n');
    try {
      const res = await axios.post(ENDPOINTS.chat, {
        messages: [{ role: 'user', content: meta }],
        max_tokens: 360,
      }, { timeout: 120000 });
      const out = (res.data?.response || '').trim().replace(/^["'`]|["'`]$/g, '');
      return out.length > 20 ? out : null;
    } catch {
      return null;
    }
  }, []);

  // ─── Shared SSE consumption (resilient to events split across network chunks) ───
  const consumeSseStream = async (
    body: ReadableStream<Uint8Array> | null,
    onEvent: (data: any) => void,
  ) => {
    if (!body) return;
    const reader = body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let finished = false;
    while (!finished) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n\n');
      buffer = lines.pop() ?? '';
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        let payload: any = null;
        try { payload = JSON.parse(line.slice(6)); } catch { continue; }
        try { onEvent(payload); } catch (handlerErr) {
          console.error('[stream] event handler failed', handlerErr);
        }
        if (payload?.done || payload?.error) { finished = true; break; }
      }
    }
    if (finished) { try { await reader.cancel(); } catch { /* already closed */ } return; }
    const tail = buffer.trim();
    if (tail.startsWith('data: ')) {
      try { onEvent(JSON.parse(tail.slice(6))); } catch { /* truncated final event */ }
    }
  };

  // ─── Stream a generation request; returns true when files were delivered ───
  const runStreamGeneration = async (
    requestBody: Record<string, unknown>,
    signal: AbortSignal,
    options: { append?: boolean } = {},
  ): Promise<boolean> => {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 1800000); // 30 minute timeout

    signal.addEventListener('abort', () => {
      clearTimeout(timeoutId);
      controller.abort();
    });

    try {
      const response = await fetch(ENDPOINTS.generateStream, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody),
        signal: controller.signal,
      });
      clearTimeout(timeoutId);

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Generation failed: ${response.status} - ${errorText}`);
      }

      let assistantMessageId: number | null = null;
      let gotFiles = false;
      let convBuffer = '';

      await consumeSseStream(response.body, (data) => {
        if (data.error) {
          setError(String(data.error));
          setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${data.error}` }]);
          return;
        }
        if (data.conversational && typeof data.token === 'string') {
          convBuffer += data.token;
          const text = convBuffer.replace(/\n+$/, '');
          setAgentProgress(prev => {
            const lines = text.split('\n').filter(Boolean);
            return lines.length > 0 ? lines : prev;
          });
          return;
        }
        if (data.done && data.files) {
          gotFiles = true;
          const completion = (data.full_response as string) || '';
          const summary = (data.summary as string) || extractConversationalResponse(completion)
            || `Built ${data.files.length} files — bundle ${data.bundle_ok ? 'verified ✓' : 'needs attention ⚠'}.`;
          setMessages(prev => {
            const base = assistantMessageId !== null && prev[assistantMessageId]
              ? prev.slice(0, assistantMessageId)
              : prev;
            return [...base, { role: 'assistant' as const, content: summary }];
          });
          if (Array.isArray(data.agent_trace) && data.agent_trace.length > 0) {
            // keep the raw trace available for the code view / debugging
            console.debug('[agent trace]', data.agent_trace);
          }
          if (data.files.length > 0) {
            setFiles(prev => options.append
              ? buildFileTree([...flattenFiles(prev), ...data.files])
              : buildFileTree(data.files));
            setSelectedFile({
              name: data.files[0].path.split('/').pop()!,
              path: data.files[0].path,
              type: 'file' as const,
              content: data.files[0].content,
            });
            setActiveView('preview');
          }
        }
      });
      return gotFiles;
    } catch (err: any) {
      clearTimeout(timeoutId);
      throw err;
    }
  };

  // ─── Core: run one prompt through the stream (used by send + queue) ───
  const runPrompt = useCallback(async (prompt: string) => {
    setLoading(true);
    setStreaming(true);
    setAgentProgress([]);
    setError(null);
    abortRef.current = new AbortController();
    saveVersion(prompt);

    try {
      const sid = await ensureSession();
      // Preferences from Settings: provider, temperature and the optional
      // language directive are applied in ONE place, so the composer, the
      // queue and any future entry point cannot disagree about them.
      const prefs = getSettings();
      await runStreamGeneration({
        prompt: withLanguageDirective(prompt, prefs),
        business_type: state?.template || 'business-app',
        features: state?.features ? state.features.split(',').map(f => f.trim()) : [],
        assets: builderAssets.map(a => ({ url: a.url, filename: a.filename, mime_type: a.mime_type })),
        brand: state?.brand || {},
        project_files: flattenFiles(files),
        operation: files.length > 0 ? 'edit' : 'create',
        temperature: prefs.temperature,
        provider: prefs.provider,
        session_id: sid,
        use_agent: true,
      }, abortRef.current.signal, { append: files.length > 0 });
    } catch (err: any) {
      if (err?.code !== 'ERR_CANCELED' && err?.name !== 'AbortError') {
        const msg = err?.response?.data?.detail || err?.message || 'Generation failed. Is the model server running?';
        setError(msg);
        setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${msg}` }]);
      }
    } finally {
      setLoading(false);
      setStreaming(false);
      setAgentProgress([]);
      abortRef.current = null;
    }
  }, [files, builderAssets, state, ensureSession]);

  const handleGenerate = async (prompt: string, template?: string, features?: string) => {
    setMessages(prev => [...prev, { role: 'user', content: prompt }]);
    await runPrompt(prompt);
  };

  // ─── Queue: prompts submitted while a build is running ───
  const handleSend = async () => {
    const q = input.trim();
    if (!q) return;
    setInput('');

    if (mode === 'plan') {
      setMessages(prev => [...prev, { role: 'user', content: q }]);
      setLoading(true);
      try {
        const res = await axios.post(ENDPOINTS.chat, {
          messages: [...messages, { role: 'user', content: q }].map(m => ({ role: m.role, content: m.content })),
          max_tokens: 1024,
        }, { timeout: 120000 });
        setMessages(prev => [...prev, { role: 'assistant', content: res.data.response }]);
      } catch (err: any) {
        setError(err?.response?.data?.detail || 'Connection error');
      } finally {
        setLoading(false);
      }
      return;
    }

    // Attach the element context as part of the request, like Bolt's Select.
    const withElement = selectedElement
      ? `${q}\n\n(Context: focus this change on the ${selectedElement.label} element` +
        (selectedElement.text ? ` — currently showing "${selectedElement.text.slice(0, 60)}"` : '') + '.)'
      : q;
    setSelectedElement(null);

    if (loading || streaming) {
      const id = ++queueIdRef.current;
      setQueue(prev => [...prev, { id, prompt: withElement }]);
      setMessages(prev => [...prev, { role: 'user', content: q }]);
      return;
    }

    setMessages(prev => [...prev, { role: 'user', content: q }]);
    await runPrompt(withElement);
  };

  // Drain the queue whenever the agent goes idle
  useEffect(() => {
    if (loading || streaming || queuePaused || queue.length === 0) return;
    if (dequeueingRef.current) return;
    dequeueingRef.current = true;
    const [next, ...rest] = queue;
    setQueue(rest);
    // let the completion state settle before starting the next build
    const t = setTimeout(async () => {
      await runPrompt(next.prompt);
      dequeueingRef.current = false;
    }, 600);
    return () => { clearTimeout(t); dequeueingRef.current = false; };
  }, [loading, streaming, queue, queuePaused, runPrompt]);

  const removeQueued = (id: number) => setQueue(prev => prev.filter(q => q.id !== id));
  const editQueued = (id: number, prompt: string) => setQueue(prev => prev.map(q => q.id === id ? { ...q, prompt } : q));
  const reorderQueued = (from: number, to: number) => setQueue(prev => {
    const next = [...prev];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    return next;
  });

  const handleRuntimeError = useCallback((message: string) => {
    setInput(`Fix this runtime error from the preview and re-verify the app: ${message}`);
  }, []);

  const handleElementSelect = useCallback((sel: ElementSelection) => {
    setSelectedElement(sel);
    if (!inputRef.current.trim()) {
      setInput(`Change the ${sel.label} element: `);
    }
  }, []);

  const handleNewSession = () => {
    setMessages([{ role: 'assistant', content: 'Hi! What would you like to build?' }]);
    setFiles([]);
    setSelectedFile(null);
    setCurrentSessionId(null);
    setVersions([]);
    setQueue([]);
    setInput('');
    setError(null);
    setSelectedElement(null);
  };

  const handleDeleteSession = async (id: number) => {
    try {
      await axios.delete(`${ENDPOINTS.sessions}/${id}`);
      setSessions(prev => prev.filter(s => s.id !== id));
      if (currentSessionId === id) handleNewSession();
    } catch {}
  };

  const filePaths = flattenFiles(files).map(f => f.path);
  const versionList: Version[] = versions.map((v, i) => ({
    id: v.id,
    label: v.label,
    at: v.at,
    fileCount: flattenFiles(v.files).length,
    current: i === versions.length - 1,
  })).reverse();
  const showHero = messages.length <= 1 && files.length === 0 && !loading;

  return (
    <div id="main" className="h-screen flex flex-col bg-[#07070d] overflow-hidden">
      {/* The builder is a workspace, not a document: one screen-level heading
          exists for screen readers and the route title carries the rest. */}
      <h1 className="sr-only">Terabit Studio builder</h1>
      {/* ─── Top bar ─── */}
      <header className="flex items-center justify-between px-4 py-2 border-b border-white/[0.06] bg-[#07070d]/90 backdrop-blur-xl z-20 flex-shrink-0">
        <div className="flex items-center gap-3">
          <button
            onClick={() => setChatOpen(!chatOpen)}
            aria-label={chatOpen ? 'Hide the chat panel' : 'Show the chat panel'}
            aria-pressed={!chatOpen}
            className="p-1.5 rounded-lg text-gray-500 hover:text-white hover:bg-white/5 transition-all"
          >
            {chatOpen ? <PanelLeftClose className="w-4 h-4" /> : <PanelLeft className="w-4 h-4" />}
          </button>
          <div className="pr-3 border-r border-white/[0.06]">
            <Wordmark size="sm" />
          </div>
          <div className="flex items-center gap-2">
            <div className="flex bg-white/[0.04] rounded-lg p-0.5 border border-white/[0.06]">
              <button
                onClick={() => setMode('build')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                  mode === 'build' ? 'bg-violet-500/20 text-violet-300 shadow-sm' : 'text-gray-500 hover:text-gray-300'
                }`}
              ><Hammer className="w-3 h-3" /> Build</button>
              <button
                onClick={() => setMode('plan')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                  mode === 'plan' ? 'bg-amber-500/20 text-amber-300 shadow-sm' : 'text-gray-500 hover:text-gray-300'
                }`}
              ><Lightbulb className="w-3 h-3" /> Plan</button>
            </div>
            <div className="flex bg-white/[0.04] rounded-lg p-0.5 border border-white/[0.06]">
              <button
                onClick={() => setActiveView('preview')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                  activeView === 'preview' ? 'bg-cyan-500/20 text-cyan-300 shadow-sm' : 'text-gray-500 hover:text-gray-300'
                }`}
              ><Eye className="w-3 h-3" /> Preview</button>
              <button
                onClick={() => setActiveView('code')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                  activeView === 'code' ? 'bg-cyan-500/20 text-cyan-300 shadow-sm' : 'text-gray-500 hover:text-gray-300'
                }`}
              ><Code2 className="w-3 h-3" /> Code</button>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {versions.length > 1 && (
            <button
              onClick={handleUndo}
              className="flex items-center gap-1.5 px-2.5 py-1.5 bg-white/5 border border-white/10 rounded-lg text-xs text-gray-400 hover:text-white hover:bg-white/10 transition-all"
              title="Undo last generation"
            ><Undo2 className="w-3.5 h-3.5" /></button>
          )}
          <button
            onClick={handleNewSession}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-white/5 border border-white/10 rounded-lg text-xs font-medium text-gray-400 hover:text-white hover:bg-white/10 transition-all"
          ><Plus className="w-3.5 h-3.5" /> New</button>
          {files.length > 0 && (
            <button
              onClick={handleDownload}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-gradient-to-r from-violet-600 to-fuchsia-600 rounded-lg text-xs font-medium text-white hover:shadow-lg hover:shadow-violet-500/20 transition-all"
            ><Download className="w-3.5 h-3.5" /> Export</button>
          )}
          <button
            onClick={() => { setShowVersions(v => !v); setShowSessions(false); }}
            className={`p-1.5 rounded-lg transition-all ${
              showVersions ? 'text-cyan-400 bg-cyan-500/15' : 'text-gray-500 hover:text-white hover:bg-white/5'
            }`}
            title="Version history"
          ><ListTodo className="w-4 h-4" /></button>
          <button
            onClick={() => setShowAssets(!showAssets)}
            aria-label="Your images and brand assets"
            aria-expanded={showAssets}
            className={`p-1.5 rounded-lg transition-all ${
              showAssets ? 'text-violet-400 bg-violet-500/15' : 'text-gray-500 hover:text-white hover:bg-white/5'
            }`}
          ><Image className="w-4 h-4" /></button>
          <button
            onClick={() => { setShowSessions(!showSessions); setShowVersions(false); }}
            aria-label="Chat sessions"
            aria-expanded={showSessions}
            className={`p-1.5 rounded-lg transition-all ${
              showSessions ? 'text-violet-400 bg-violet-500/15' : 'text-gray-500 hover:text-white hover:bg-white/5'
            }`}
          ><History className="w-4 h-4" /></button>
          <button
            onClick={() => setShowFiles(!showFiles)}
            aria-label={showFiles ? 'Hide the files panel' : 'Show the files panel'}
            aria-pressed={!showFiles}
            className="p-1.5 rounded-lg text-gray-500 hover:text-white hover:bg-white/5 transition-all"
          >{showFiles ? <PanelRightClose className="w-4 h-4" /> : <PanelRight className="w-4 h-4" />}</button>

          <div className="h-5 w-px bg-white/[0.06] mx-1" />

          {user ? (
            <div className="relative group">
              <button className="flex items-center gap-1.5 px-2.5 py-1.5 bg-white/5 rounded-lg text-xs text-gray-400 hover:text-white hover:bg-white/10 transition-all">
                <UserCircle className="w-4 h-4" />
                {user.email.split('@')[0]}
              </button>
              <div className="absolute right-0 top-full mt-1 w-36 bg-gray-800 border border-gray-700 rounded-xl shadow-xl opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all z-50">
                <button onClick={() => { logout(); navigate('/'); }} className="w-full text-left px-4 py-2.5 text-xs text-gray-400 hover:text-white hover:bg-white/5 rounded-xl transition-colors">Sign out</button>
              </div>
            </div>
          ) : (
            <button onClick={() => navigate('/login')} className="flex items-center gap-1.5 px-3 py-1.5 bg-violet-500/20 border border-violet-500/30 rounded-lg text-xs font-medium text-violet-300 hover:bg-violet-500/30 transition-all">
              <LogIn className="w-3.5 h-3.5" /> Sign In
            </button>
          )}
        </div>
      </header>

      {/* ─── Main ─── */}
      <div className="flex-1 flex overflow-hidden">
        {/* Sessions overlay */}
        {showSessions && (
          <div className="w-64 bg-[#0b0b14] border-r border-white/[0.05] overflow-y-auto p-3 flex-shrink-0 z-10 animate-slide-left">
            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3 px-2">History</h3>
            {sessions.length === 0 ? (
              <p className="text-xs text-gray-600 px-2">No saved sessions.</p>
            ) : (
              <div className="space-y-1">
                {sessions.map(s => (
                  <div key={s.id}
                    className={`group flex items-center gap-2 px-3 py-2 rounded-lg text-xs cursor-pointer transition-all ${
                      currentSessionId === s.id ? 'bg-violet-500/15 text-violet-300' : 'text-gray-400 hover:bg-white/[0.03] hover:text-gray-200'
                    }`}
                    onClick={() => {
                      setCurrentSessionId(s.id);
                      setShowSessions(false);
                      axios.get(`${ENDPOINTS.sessions}/${s.id}/messages`).then(r => {
                        const msgs = r.data.map((m: any) => ({ role: m.role, content: m.content }));
                        setMessages(msgs.length > 0 ? msgs : [{ role: 'assistant', content: 'Session loaded.' }]);
                      }).catch(() => {});
                    }}
                  >
                    <Clock className="w-3.5 h-3.5 flex-shrink-0" />
                    <span className="truncate flex-1">{s.name}</span>
                    <button onClick={(e) => { e.stopPropagation(); handleDeleteSession(s.id); }} className="opacity-0 group-hover:opacity-100 text-gray-600 hover:text-red-400 transition-all">
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Versions panel */}
        {showVersions && (
          <VersionHistory
            versions={versionList}
            onRestore={handleRestore}
            locked={loading || streaming}
            onClose={() => setShowVersions(false)}
          />
        )}

        {/* ─── Assets panel ─── */}
        {showAssets && (
          <div className="w-64 bg-[#0b0b14] border-r border-white/[0.05] overflow-y-auto p-3 flex-shrink-0 z-10 animate-slide-left">
            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3 px-2">Assets</h3>
            <AssetManager
              onAssetsChange={setBuilderAssets}
              compact
            />
            {builderAssets.length > 0 && (
              <div className="mt-3 px-2">
                <p className="text-[10px] text-gray-600">{builderAssets.length} asset{builderAssets.length !== 1 ? 's' : ''} uploaded</p>
                <p className="text-[9px] text-gray-600 mt-0.5">These will be included with your next generation.</p>
              </div>
            )}
          </div>
        )}

        {/* ─── Chat sidebar ─── */}
        {chatOpen && (
          <div className="w-[420px] flex flex-col border-r border-white/[0.05] bg-[#0b0b14] flex-shrink-0">
            <div className="flex items-center justify-between px-4 py-2.5 border-b border-white/[0.05]">
              <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                {mode === 'plan' ? 'Plan' : 'Chat'}
              </span>
              <div className="flex items-center gap-2">
                {queue.length > 0 && (
                  <span className="text-[10px] text-violet-400 bg-violet-500/10 px-2 py-0.5 rounded-full flex items-center gap-1">
                    <ListTodo className="w-3 h-3" /> {queue.length} queued
                  </span>
                )}
                {mode === 'plan' && <span className="text-[10px] text-amber-500/70 bg-amber-500/10 px-2 py-0.5 rounded-full">No code changes</span>}
              </div>
            </div>

            <div className="flex-1 overflow-y-auto p-3 space-y-3">
              {/* ── hero / empty state ── */}
              {showHero && (
                <div className="pt-6 px-1 animate-fade-in">
                  <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-violet-600 to-cyan-600 flex items-center justify-center mb-3">
                    <Sparkles className="w-5 h-5 text-white" />
                  </div>
                  <h2 className="text-base font-semibold text-gray-100 mb-1">What do you want to build?</h2>
                  <p className="text-xs text-gray-500 mb-4 leading-relaxed">
                    Describe a website or app. A local model plans the files, writes each section,
                    then verifies the production bundle before showing you the live preview.
                  </p>
                  <div className="space-y-1.5">
                    {STARTER_IDEAS.map(idea => (
                      <button
                        key={idea.label}
                        onClick={() => setInput(idea.prompt)}
                        className="w-full text-left px-3 py-2.5 rounded-xl bg-white/[0.02] border border-white/[0.06] hover:border-violet-500/40 hover:bg-violet-500/[0.06] transition-all group"
                      >
                        <span className="block text-[11px] font-medium text-gray-300 group-hover:text-violet-200">{idea.label}</span>
                        <span className="block text-[10px] text-gray-600 truncate">{idea.prompt}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {messages.map((msg, i) => (
                <div key={i} className={`animate-fade-in flex gap-2.5 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
                  <div className={`flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center text-[10px] ${
                    msg.role === 'user' ? 'bg-cyan-500/15 text-cyan-400' : 'bg-violet-500/15 text-violet-400'
                  }`}>
                    {msg.role === 'user' ? <User className="w-3.5 h-3.5" /> : <Bot className="w-3.5 h-3.5" />}
                  </div>
                  <div className={`max-w-[88%] rounded-xl px-3.5 py-2.5 text-sm leading-relaxed ${
                    msg.role === 'user'
                      ? 'bg-cyan-500/8 border border-cyan-500/12 text-gray-200'
                      : 'bg-white/[0.02] border border-white/[0.06] text-gray-300 whitespace-pre-wrap'
                  }`}>
                    {msg.content}
                  </div>
                </div>
              ))}

              {/* ── queue ── */}
              {queue.length > 0 && (
                <div className="bg-white/[0.02] border border-white/[0.07] rounded-xl overflow-hidden animate-slide-up">
                  <div className="flex items-center gap-2 px-3 py-2 border-b border-white/[0.05]">
                    <ListTodo className="w-3.5 h-3.5 text-gray-500" />
                    <span className="text-[11px] font-medium text-gray-400">Up next</span>
                    <button
                      onClick={() => setQueuePaused(p => !p)}
                      className="ml-auto flex items-center gap-1 text-[10px] text-gray-400 hover:text-white px-1.5 py-0.5 rounded hover:bg-white/5 transition-all"
                    >
                      {queuePaused ? <Play className="w-3 h-3" /> : <Pause className="w-3 h-3" />}
                      {queuePaused ? 'Resume' : 'Pause'}
                    </button>
                  </div>
                  <div className="p-1.5 space-y-1">
                    {queue.map((q, i) => (
                      <div
                        key={q.id}
                        draggable
                        onDragStart={() => setDragId(q.id)}
                        onDragOver={e => e.preventDefault()}
                        onDrop={() => {
                          if (dragId === null || dragId === q.id) return;
                          const from = queue.findIndex(x => x.id === dragId);
                          if (from !== -1) reorderQueued(from, i);
                          setDragId(null);
                        }}
                        className={`group flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-white/[0.04] transition-colors ${
                          queuePaused ? 'opacity-55' : ''
                        }`}
                      >
                        <GripVertical className="w-3 h-3 text-gray-700 cursor-grab flex-shrink-0" />
                        <span className="text-[10px] text-gray-600 w-3 flex-shrink-0">{i + 1}</span>
                        <input
                          value={q.prompt}
                          onChange={e => editQueued(q.id, e.target.value)}
                          className="flex-1 bg-transparent text-[11px] text-gray-300 focus:outline-none min-w-0"
                        />
                        <button onClick={() => removeQueued(q.id)} className="opacity-0 group-hover:opacity-100 text-gray-600 hover:text-red-400 flex-shrink-0 transition-opacity">
                          <X className="w-3 h-3" />
                        </button>
                      </div>
                    ))}
                  </div>
                  {queuePaused && (
                    <p className="px-3 pb-2 text-[10px] text-amber-500/70">Queue paused — resume when you're ready.</p>
                  )}
                </div>
              )}

              {/* ── agent timeline ── */}
              {/* A PERSISTENT polite live region: it exists before the run
                  starts, so a screen reader announces each step as it lands
                  instead of staying silent for twenty minutes. */}
              <div aria-live="polite" aria-atomic="false">
              {streaming && agentProgress.length > 0 && (
                <AgentSteps lines={agentProgress} running={streaming} />
              )}

              {loading && !streaming && (
                <div className="flex gap-2.5">
                  <div className="w-7 h-7 rounded-lg bg-violet-500/15 flex items-center justify-center">
                    <Bot className="w-3.5 h-3.5 text-violet-400" />
                  </div>
                  <div className="bg-white/[0.02] border border-white/[0.06] rounded-xl px-3.5 py-2.5 flex items-center gap-2 text-sm text-gray-400">
                    <Loader2 className="w-3.5 h-3.5 text-violet-400 animate-spin" />
                    Thinking...
                  </div>
                </div>
              )}

              {streaming && agentProgress.length === 0 && (
                <div className="bg-white/[0.02] border border-violet-500/20 rounded-xl overflow-hidden">
                  <div className="flex items-center gap-2 px-3 py-2">
                    <Loader2 className="w-3.5 h-3.5 text-violet-400 animate-spin" />
                    <span className="text-xs font-medium text-violet-300">Starting the agent...</span>
                  </div>
                  <div className="shimmer-track h-0.5 bg-white/5" />
                </div>
              )}
              </div>

              {error && (
                <div role="alert" className="flex items-center gap-2 p-2.5 bg-red-500/8 border border-red-500/15 rounded-lg text-red-400 text-xs">
                  <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
                  {error}
                </div>
              )}
              <div ref={chatEndRef} />
            </div>

            <div className="p-3 border-t border-white/[0.05]">
              <PromptComposer
                value={input}
                onChange={setInput}
                onSend={handleSend}
                onStop={handleStop}
                idle={!loading && !streaming}
                busy={loading || streaming}
                placeholder={
                  mode === 'plan'
                    ? 'Ask a question about your project...'
                    : (loading || streaming)
                      ? 'Queue your next change...'
                      : 'Describe what to build or change...'
                }
                mode={mode}
                filePaths={filePaths}
                selectedElement={selectedElement}
                onClearElement={() => setSelectedElement(null)}
                onAttach={() => setShowAssets(true)}
                onEnhance={enhancePrompt}
              />
            </div>
          </div>
        )}

        {/* ─── Main canvas ─── */}
        <div className="flex-1 flex flex-col min-w-0 bg-[#07070d]">
          {activeView === 'code' && files.length > 0 ? (
            <div className="flex-1 flex min-h-0">
              {showFiles && (
                <div className="w-56 bg-[#0b0b14] border-r border-white/[0.05] overflow-y-auto p-3 flex-shrink-0">
                  <FileExplorer files={files} onFileSelect={setSelectedFile} selectedPath={selectedFile?.path} />
                </div>
              )}
              <div className="flex-1 overflow-hidden">
                <CodeEditor file={selectedFile} onChange={(content) => selectedFile && updateFileContent(selectedFile.path, content)} />
              </div>
            </div>
          ) : (
            <div className="flex-1 flex min-h-0">
              <div className="flex-1 overflow-hidden">
                <PreviewFrame
                  files={files}
                  onRuntimeError={handleRuntimeError}
                  onElementSelect={handleElementSelect}
                />
              </div>
              {showFiles && activeView === 'preview' && files.length > 0 && (
                <div className="w-56 bg-[#0b0b14] border-l border-white/[0.05] overflow-y-auto p-3 flex-shrink-0">
                  <FileExplorer files={files} onFileSelect={(f) => { setSelectedFile(f); setActiveView('code'); }} selectedPath={selectedFile?.path} />
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ─── Status bar ─── */}
      <footer className="flex items-center justify-between px-4 py-1 border-t border-white/[0.05] bg-[#07070d] flex-shrink-0">
        <div className="flex items-center gap-3 text-[10px] text-gray-600">
          <span className="flex items-center gap-1">
            <span className={`w-1.5 h-1.5 rounded-full ${loading ? 'bg-violet-400 animate-pulse-dot' : 'bg-emerald-500'}`} />
            {loading ? 'Generating...' : 'Ready'}
          </span>
          {files.length > 0 && <span>{flattenFiles(files).length} files</span>}
          {queue.length > 0 && <span className="text-violet-400/80">{queue.length} queued</span>}
          {versions.length > 0 && <span>{versions.length} versions</span>}
          {currentSessionId && <span>Session #{currentSessionId}</span>}
        </div>
        <div className="flex items-center gap-3 text-[10px] text-gray-600">
          <span>Qwen 2.5 7B</span>
          <span>Local</span>
        </div>
      </footer>
    </div>
  );
}
