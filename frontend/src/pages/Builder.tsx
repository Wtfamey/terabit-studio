import { useEffect, useState, useRef, useCallback } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Message, GeneratedFile, FileItem, ChatSession as ChatSessionType, UserAsset } from '../types';
import { FileExplorer } from '../components/FileExplorer';
import { CodeEditor } from '../components/CodeEditor';
import { PreviewFrame } from '../components/PreviewFrame';
import { AssetManager } from '../components/AssetManager';
import { useAuth } from '../contexts/AuthContext';
import axios from 'axios';
import { ENDPOINTS } from '../config';
import {
  Send, Sparkles, Bot, User, Loader2,
  AlertCircle, Download, Square, Plus, Clock, Trash2,
  LogIn, UserCircle, PanelLeftClose, PanelLeft, PanelRightClose, PanelRight,
  Code2, Eye, History, Undo2, Hammer, Lightbulb, Image
} from 'lucide-react';

interface Snapshot {
  files: FileItem[];
  selectedFile: FileItem | null;
}

export function Builder() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const state = location.state as {
    prompt: string; template: string | null; features: string;
    assets?: { url: string; filename: string; original_name: string; mime_type: string }[];
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
  const [chatOpen, setChatOpen] = useState(true);
  const [history, setHistory] = useState<Snapshot[]>([]);
  const [builderAssets, setBuilderAssets] = useState<UserAsset[]>([]);
  const [showAssets, setShowAssets] = useState(false);

  const chatEndRef = useRef<HTMLDivElement>(null);
  const initialized = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  const [sessionReady, setSessionReady] = useState(false);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    if (user) {
      axios.get(ENDPOINTS.sessions).then(r => setSessions(r.data)).catch(() => {});
    }
  }, [user]);

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
          : "Hi! Describe the app you want to build, and I'll generate it for you.",
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

  const parseFilesFromResponse = (response: string): GeneratedFile[] => {
    const patterns: RegExp[] = [
      /`(.+?)`\s*\n```[\w]*\n([\s\S]*?)```/g,
      /####\s*`(.+?)`\s*\n```[\w]*\n([\s\S]*?)```/g,
      /\*\*(.+?\.\w+)\*\*\s*\n```[\w]*\n([\s\S]*?)```/g,
    ];
    for (const pattern of patterns) {
      const items: GeneratedFile[] = [];
      let match;
      while ((match = pattern.exec(response)) !== null) {
        const path = match[1].replace(/^`|`$/g, '').replace(/^\*\*|\*\*$/g, '').replace(/^####\s*/, '').trim();
        const content = match[2].trim();
        if (path && content) items.push({ path, content });
      }
      if (items.length > 0) return items;
    }
    return [];
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

  const saveSnapshot = () => {
    setHistory(prev => [...prev, { files: JSON.parse(JSON.stringify(files)), selectedFile: selectedFile ? { ...selectedFile } : null }]);
  };

  const handleUndo = () => {
    if (history.length === 0) return;
    const prev = history[history.length - 1];
    setFiles(prev.files);
    setSelectedFile(prev.selectedFile);
    setHistory(h => h.slice(0, -1));
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

  const handleGenerate = async (prompt: string, template?: string, features?: string) => {
    setLoading(true);
    setStreaming(true);
    setError(null);
    abortRef.current = new AbortController();
    saveSnapshot();

    try {
      const sid = await ensureSession();
      const res = await axios.post(ENDPOINTS.generate, {
        prompt,
        business_type: template || 'business-app',
        features: features ? features.split(',').map(f => f.trim()) : [],
        assets: builderAssets.map(a => ({ url: a.url, filename: a.filename, mime_type: a.mime_type })),
        temperature: 0.7,
        session_id: sid,
      });
      const response = res.data.response;
      setMessages(prev => [...prev, { role: 'assistant', content: response }]);

      const parsed: GeneratedFile[] = res.data.files || parseFilesFromResponse(response);
      if (parsed.length > 0) {
        setFiles(buildFileTree(parsed));
        setSelectedFile({
          name: parsed[0].path.split('/').pop()!,
          path: parsed[0].path,
          type: 'file',
          content: parsed[0].content,
        });
        setActiveView('preview');
      }
    } catch (err: any) {
      if (err?.code !== 'ERR_CANCELED') {
        const msg = err?.response?.data?.detail || 'Generation failed. Is the model server running?';
        setError(msg);
        setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${msg}` }]);
      }
    } finally {
      setLoading(false);
      setStreaming(false);
      abortRef.current = null;
    }
  };

  const handleSend = async () => {
    if (!input.trim() || (loading && !streaming)) return;
    const userMsg: Message = { role: 'user', content: input };
    setMessages(prev => [...prev, userMsg]);
    const query = input;
    setInput('');
    setLoading(true);
    setStreaming(mode === 'build');
    setError(null);
    abortRef.current = new AbortController();

    try {
      if (mode === 'plan') {
        const res = await axios.post(ENDPOINTS.chat, {
          messages: [...messages, userMsg].map(m => ({ role: m.role, content: m.content })),
          max_tokens: 1024,
        });
        setMessages(prev => [...prev, { role: 'assistant', content: res.data.response }]);
      } else {
        const sid = await ensureSession();
        saveSnapshot();
        const res = await axios.post(ENDPOINTS.generate, {
          prompt: query,
          business_type: state?.template || 'business-app',
          features: state?.features ? state.features.split(',').map(f => f.trim()) : [],
          assets: builderAssets.map(a => ({ url: a.url, filename: a.filename, mime_type: a.mime_type })),
          temperature: 0.7,
          session_id: sid,
        });
        const reply = res.data.response;
        setMessages(prev => [...prev, { role: 'assistant', content: reply }]);
        const parsed: GeneratedFile[] = res.data.files || parseFilesFromResponse(reply);
        if (parsed.length > 0) {
          setFiles(prev => buildFileTree([...flattenFiles(prev), ...parsed]));
        }
      }
    } catch (err: any) {
      if (err?.code !== 'ERR_CANCELED') {
        setError(err?.response?.data?.detail || 'Connection error');
      }
    } finally {
      setLoading(false);
      setStreaming(false);
      abortRef.current = null;
    }
  };

  const handleNewSession = () => {
    setMessages([{ role: 'assistant', content: 'Hi! What would you like to build?' }]);
    setFiles([]);
    setSelectedFile(null);
    setCurrentSessionId(null);
    setHistory([]);
    setInput('');
    setError(null);
  };

  const handleDeleteSession = async (id: number) => {
    try {
      await axios.delete(`${ENDPOINTS.sessions}/${id}`);
      setSessions(prev => prev.filter(s => s.id !== id));
      if (currentSessionId === id) handleNewSession();
    } catch {}
  };

  return (
    <div className="h-screen flex flex-col bg-[#0a0e1a] overflow-hidden">
      {/* ─── Top bar ─── */}
      <header className="flex items-center justify-between px-4 py-2 border-b border-white/[0.06] bg-[#0a0e1a]/90 backdrop-blur-xl z-20 flex-shrink-0">
        <div className="flex items-center gap-3">
          <button
            onClick={() => setChatOpen(!chatOpen)}
            className="p-1.5 rounded-lg text-gray-500 hover:text-white hover:bg-white/5 transition-all"
          >
            {chatOpen ? <PanelLeftClose className="w-4 h-4" /> : <PanelLeft className="w-4 h-4" />}
          </button>
          <div className="flex items-center gap-2 pr-3 border-r border-white/[0.06]">
            <div className="p-1 bg-gradient-to-br from-violet-600 to-cyan-600 rounded-lg">
              <Sparkles className="w-3.5 h-3.5 text-white" />
            </div>
            <span className="font-bold text-sm text-gray-100">TerabitStudio</span>
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
          {history.length > 0 && (
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
            onClick={() => setShowAssets(!showAssets)}
            className={`p-1.5 rounded-lg transition-all ${
              showAssets ? 'text-violet-400 bg-violet-500/15' : 'text-gray-500 hover:text-white hover:bg-white/5'
            }`}
          ><Image className="w-4 h-4" /></button>
          <button
            onClick={() => setShowSessions(!showSessions)}
            className="p-1.5 rounded-lg text-gray-500 hover:text-white hover:bg-white/5 transition-all"
          ><History className="w-4 h-4" /></button>
          <button
            onClick={() => setShowFiles(!showFiles)}
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
          <div className="w-64 bg-[#0d1225] border-r border-white/[0.05] overflow-y-auto p-3 flex-shrink-0 z-10">
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

        {/* ─── Assets panel ─── */}
        {showAssets && (
          <div className="w-64 bg-[#0d1225] border-r border-white/[0.05] overflow-y-auto p-3 flex-shrink-0 z-10">
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
          <div className="w-[380px] flex flex-col border-r border-white/[0.05] bg-[#0d1225] flex-shrink-0">
            <div className="flex items-center justify-between px-4 py-2.5 border-b border-white/[0.05]">
              <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                {mode === 'plan' ? 'Plan' : 'Chat'}
              </span>
              {mode === 'plan' && <span className="text-[10px] text-amber-500/70 bg-amber-500/10 px-2 py-0.5 rounded-full">No code changes</span>}
            </div>
            <div className="flex-1 overflow-y-auto p-3 space-y-3">
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
              {error && (
                <div className="flex items-center gap-2 p-2.5 bg-red-500/8 border border-red-500/15 rounded-lg text-red-400 text-xs">
                  <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
                  {error}
                </div>
              )}
              <div ref={chatEndRef} />
            </div>

            <div className="p-3 border-t border-white/[0.05]">
              <div className="relative flex items-center gap-2 bg-white/5 border border-white/10 rounded-xl px-3 py-2 focus-within:border-violet-500/50 transition-all">
                <input
                  type="text"
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && !e.shiftKey && !streaming && handleSend()}
                  placeholder={mode === 'plan' ? 'Ask a question about your project...' : 'Describe what to build or change...'}
                  className="flex-1 bg-transparent text-sm text-gray-100 placeholder-gray-600 focus:outline-none"
                  disabled={loading && !streaming}
                />
                {streaming ? (
                  <button onClick={handleStop} className="flex-shrink-0 p-1.5 bg-red-500/80 hover:bg-red-500 rounded-lg text-white transition-all">
                    <Square className="w-4 h-4" />
                  </button>
                ) : (
                  <button
                    onClick={handleSend}
                    disabled={loading || !input.trim()}
                    className="flex-shrink-0 p-1.5 bg-gradient-to-r from-violet-600 to-cyan-600 rounded-lg text-white disabled:opacity-40 transition-all hover:shadow-lg hover:shadow-violet-500/20"
                  ><Send className="w-4 h-4" /></button>
                )}
              </div>
              {mode === 'plan' && (
                <p className="text-[10px] text-gray-600 mt-1.5 px-1">Plan mode lets you discuss without changing your project</p>
              )}
            </div>
          </div>
        )}

        {/* ─── Main canvas ─── */}
        <div className="flex-1 flex flex-col min-w-0 bg-[#0a0e1a]">
          {activeView === 'code' && files.length > 0 ? (
            <div className="flex-1 flex min-h-0">
              {showFiles && (
                <div className="w-56 bg-[#0d1225] border-r border-white/[0.05] overflow-y-auto p-3 flex-shrink-0">
                  <FileExplorer files={files} onFileSelect={setSelectedFile} selectedPath={selectedFile?.path} />
                </div>
              )}
              <div className="flex-1 overflow-hidden">
                <CodeEditor file={selectedFile} />
              </div>
            </div>
          ) : (
            <div className="flex-1 flex min-h-0">
              <div className="flex-1 overflow-hidden">
                <PreviewFrame files={files} />
              </div>
              {showFiles && activeView === 'preview' && files.length > 0 && (
                <div className="w-56 bg-[#0d1225] border-l border-white/[0.05] overflow-y-auto p-3 flex-shrink-0">
                  <FileExplorer files={files} onFileSelect={(f) => { setSelectedFile(f); setActiveView('code'); }} selectedPath={selectedFile?.path} />
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ─── Status bar ─── */}
      <footer className="flex items-center justify-between px-4 py-1 border-t border-white/[0.05] bg-[#0a0e1a] flex-shrink-0">
        <div className="flex items-center gap-3 text-[10px] text-gray-600">
          <span className="flex items-center gap-1">
            <span className={`w-1.5 h-1.5 rounded-full ${loading ? 'bg-violet-400 animate-pulse' : 'bg-green-500'}`} />
            {loading ? 'Generating...' : 'Ready'}
          </span>
          {files.length > 0 && <span>{flattenFiles(files).length} files</span>}
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
