import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import {
  Send, Square, Plus, Mic, MicOff, Wand2, ImagePlus, FileCode2,
  Loader2, X, Crosshair, CornerDownLeft,
} from 'lucide-react';

export interface SelectedElementInfo {
  label: string;
  text?: string;
  detail?: string;
}

interface PromptComposerProps {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  onStop: () => void;
  /** false = a build is running (queue mode is active) */
  idle: boolean;
  disabled?: boolean;
  /** busy but not streaming (planning / building) shows the spinner state */
  busy: boolean;
  placeholder: string;
  mode: 'build' | 'plan';
  filePaths: string[];
  selectedElement?: SelectedElementInfo | null;
  onClearElement?: () => void;
  onAttach?: () => void;
  onEnhance?: (prompt: string) => Promise<string | null>;
}

const ENHANCE_QUESTIONS = [
  { key: 'audience', q: 'Who is this for?', hint: 'e.g. a boutique law firm in Austin' },
  { key: 'style', q: 'What look and feel?', hint: 'e.g. warm minimal, dark and cinematic' },
  { key: 'must', q: 'What must it include?', hint: 'e.g. pricing, testimonials, booking form' },
];

export function PromptComposer({
  value, onChange, onSend, onStop, idle, disabled, busy, placeholder, mode,
  filePaths, selectedElement, onClearElement, onAttach, onEnhance,
}: PromptComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [mention, setMention] = useState<{ query: string; start: number } | null>(null);
  const [mentionIndex, setMentionIndex] = useState(0);
  const [listening, setListening] = useState(false);
  const [enhancing, setEnhancing] = useState(false);
  const [enhanceOpen, setEnhanceOpen] = useState(false);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const recognitionRef = useRef<any>(null);

  // auto-grow the textarea without ever scrollbar-ing inside it
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  const fileMatches = useMemo(() => {
    if (!mention) return [];
    const q = mention.query.toLowerCase();
    const all = filePaths.filter(p => !q || p.toLowerCase().includes(q));
    // prefer basename matches, then shorter paths — mirrors how Bolt ranks
    return all
      .sort((a, b) => {
        const ab = a.split('/').pop()!.toLowerCase();
        const bb = b.split('/').pop()!.toLowerCase();
        const aHit = ab.includes(q) ? 0 : 1;
        const bHit = bb.includes(q) ? 0 : 1;
        return aHit - bHit || a.length - b.length;
      })
      .slice(0, 8);
  }, [mention, filePaths]);

  useEffect(() => { setMentionIndex(0); }, [mention?.query]);

  const detectMention = useCallback((text: string, caret: number) => {
    // scan back from the caret for an '@' that starts a token
    for (let i = caret - 1; i >= 0; i--) {
      const ch = text[i];
      if (ch === '@') {
        if (i === 0 || /\s|[(\[]/.test(text[i - 1])) {
          setMention({ query: text.slice(i + 1, caret), start: i });
          return;
        }
        break;
      }
      // a completed token ends the search
      if (/\s/.test(ch) || ch === ']' || ch === ')') break;
    }
    setMention(null);
  }, []);

  const applyMention = (path: string) => {
    if (!mention) return;
    const before = value.slice(0, mention.start);
    const after = value.slice(mention.start + mention.query.length + 1);
    const next = `${before}@${path} ${after.replace(/^\s+/, '')}`;
    onChange(next);
    setMention(null);
    requestAnimationFrame(() => textareaRef.current?.focus());
  };

  const toggleDictation = () => {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) return;
    if (listening) {
      recognitionRef.current?.stop();
      setListening(false);
      return;
    }
    const rec = new SR();
    rec.lang = 'en-US';
    rec.continuous = true;
    rec.interimResults = true;
    const base = value;
    rec.onresult = (e: any) => {
      let finalTxt = '';
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalTxt += t;
        else interim += t;
      }
      if (finalTxt) {
        // append dictation rather than clobbering what was typed
        onChange(`${base}${base && !base.endsWith(' ') ? ' ' : ''}${finalTxt.trim()} `);
      } else if (interim) {
        onChange(`${base}${base && !base.endsWith(' ') ? ' ' : ''}${interim}`);
      }
    };
    rec.onend = () => setListening(false);
    rec.onerror = () => setListening(false);
    recognitionRef.current = rec;
    rec.start();
    setListening(true);
  };

  const runEnhance = async () => {
    if (!onEnhance || enhancing) return;
    const base = value.trim();
    setEnhancing(true);
    setEnhanceOpen(false);
    try {
      const context = ENHANCE_QUESTIONS
        .map(({ key, q }) => (answers[key] ? `${q} ${answers[key]}` : ''))
        .filter(Boolean)
        .join('\n');
      const improved = await onEnhance(context ? `${base}\n\n${context}` : base);
      if (improved) onChange(improved);
    } finally {
      setEnhancing(false);
      setAnswers({});
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (mention && fileMatches.length > 0) {
      if (e.key === 'ArrowDown') { e.preventDefault(); setMentionIndex(i => (i + 1) % fileMatches.length); return; }
      if (e.key === 'ArrowUp') { e.preventDefault(); setMentionIndex(i => (i - 1 + fileMatches.length) % fileMatches.length); return; }
      if (e.key === 'Tab' || e.key === 'Enter') { e.preventDefault(); applyMention(fileMatches[mentionIndex]); return; }
      if (e.key === 'Escape') { e.preventDefault(); setMention(null); return; }
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  };

  const canSend = value.trim().length > 0 && !disabled;

  return (
    <div className="relative">
      {/* ── @-mention dropdown ── */}
      {mention && fileMatches.length > 0 && (
        <div className="absolute bottom-full left-0 right-0 mb-2 bg-[#141a2e] border border-white/10 rounded-xl shadow-2xl shadow-black/60 overflow-hidden z-30 animate-slide-up">
          <div className="px-3 py-1.5 text-[10px] uppercase tracking-wider text-gray-500 border-b border-white/[0.06] flex items-center gap-1.5">
            <FileCode2 className="w-3 h-3" /> Tag a project file
          </div>
          <div className="max-h-52 overflow-y-auto py-1">
            {fileMatches.map((p, i) => (
              <button
                key={p}
                onMouseDown={(e) => { e.preventDefault(); applyMention(p); }}
                className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors ${
                  i === mentionIndex ? 'bg-violet-500/20 text-violet-200' : 'text-gray-400 hover:bg-white/[0.04]'
                }`}
              >
                <span className="text-[10px] opacity-70">{iconFor(p)}</span>
                <span className="truncate">{p.split('/').pop()}</span>
                <span className="ml-auto text-[10px] text-gray-600 truncate max-w-[45%]">{p.split('/').slice(0, -1).join('/')}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* ── Enhance prompt dialog ── */}
      {enhanceOpen && (
        <div className="absolute bottom-full left-0 right-0 mb-2 bg-[#141a2e] border border-white/10 rounded-xl shadow-2xl shadow-black/60 p-3 z-30 animate-slide-up">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-gray-300 flex items-center gap-1.5">
              <Wand2 className="w-3.5 h-3.5 text-violet-400" /> Enhance your prompt
            </span>
            <button onClick={() => setEnhanceOpen(false)} className="text-gray-500 hover:text-white"><X className="w-3.5 h-3.5" /></button>
          </div>
          <p className="text-[10px] text-gray-500 mb-2.5">A few details make the generated site dramatically better.</p>
          <div className="space-y-2">
            {ENHANCE_QUESTIONS.map(({ key, q, hint }) => (
              <div key={key}>
                <label className="text-[10px] text-gray-400 block mb-1">{q}</label>
                <input
                  value={answers[key] || ''}
                  onChange={e => setAnswers(a => ({ ...a, [key]: e.target.value }))}
                  placeholder={hint}
                  className="w-full bg-white/[0.04] border border-white/10 rounded-lg px-2.5 py-1.5 text-xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-violet-500/50"
                />
              </div>
            ))}
          </div>
          <button
            onClick={runEnhance}
            disabled={enhancing || !value.trim()}
            className="mt-3 w-full flex items-center justify-center gap-1.5 py-2 bg-gradient-to-r from-violet-600 to-cyan-600 rounded-lg text-xs font-medium text-white disabled:opacity-40 transition-all"
          >
            {enhancing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Wand2 className="w-3.5 h-3.5" />}
            {enhancing ? 'Rewriting prompt...' : 'Generate better prompt'}
          </button>
        </div>
      )}

      {/* ── selected element chip ── */}
      {selectedElement && (
        <div className="mb-2 flex items-center gap-2 bg-cyan-500/10 border border-cyan-500/25 rounded-lg px-2.5 py-1.5 animate-slide-up">
          <Crosshair className="w-3.5 h-3.5 text-cyan-400 flex-shrink-0" />
          <div className="min-w-0 flex-1">
            <p className="text-[11px] text-cyan-200 font-medium truncate">{selectedElement.label}</p>
            {selectedElement.text && (
              <p className="text-[10px] text-cyan-500/70 truncate">“{selectedElement.text}”</p>
            )}
          </div>
          <button onClick={onClearElement} className="text-cyan-400/70 hover:text-cyan-200 flex-shrink-0">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* ── composer box ── */}
      <div className={`bg-white/[0.04] border rounded-2xl transition-all ${
        disabled ? 'border-white/[0.06] opacity-70' : 'border-white/10 focus-within:border-violet-500/50 focus-within:bg-white/[0.05]'
      }`}>
        <textarea
          ref={textareaRef}
          aria-label={placeholder || 'Describe what to build or change'}
          value={value}
          onChange={e => {
            onChange(e.target.value);
            detectMention(e.target.value, e.target.selectionStart ?? e.target.value.length);
          }}
          onKeyDown={onKeyDown}
          onClick={e => detectMention(value, (e.target as HTMLTextAreaElement).selectionStart ?? 0)}
          onBlur={() => setTimeout(() => setMention(null), 120)}
          rows={1}
          placeholder={placeholder}
          className="w-full bg-transparent text-sm text-gray-100 placeholder-gray-600 focus:outline-none resize-none px-3.5 pt-3 pb-1 leading-relaxed max-h-[200px]"
          disabled={disabled}
        />

        <div className="flex items-center gap-1 px-2 pb-2 pt-1">
          {/* + menu */}
          <div className="relative">
            <button
              onClick={() => setMenuOpen(o => !o)}
              title="More tools"
              className={`p-1.5 rounded-lg transition-all ${menuOpen ? 'text-violet-300 bg-violet-500/15' : 'text-gray-500 hover:text-white hover:bg-white/[0.06]'}`}
            >
              <Plus className="w-4 h-4" />
            </button>
            {menuOpen && (
              <>
                <div className="fixed inset-0 z-20" onClick={() => setMenuOpen(false)} />
                <div className="absolute bottom-full left-0 mb-2 w-52 bg-[#141a2e] border border-white/10 rounded-xl shadow-2xl shadow-black/60 py-1 z-30 animate-slide-up">
                  <MenuItem
                    icon={<Wand2 className="w-3.5 h-3.5" />}
                    label="Enhance prompt"
                    hint="Answer a few questions"
                    onClick={() => { setMenuOpen(false); setEnhanceOpen(true); }}
                  />
                  <MenuItem
                    icon={<ImagePlus className="w-3.5 h-3.5" />}
                    label="Attach images"
                    hint="Add to project assets"
                    onClick={() => { setMenuOpen(false); onAttach?.(); }}
                  />
                  <MenuItem
                    icon={<FileCode2 className="w-3.5 h-3.5" />}
                    label="Tag a file"
                    hint="or just type @"
                    onClick={() => {
                      setMenuOpen(false);
                      onChange(`${value}${value && !value.endsWith(' ') ? ' ' : ''}@`);
                      requestAnimationFrame(() => {
                        textareaRef.current?.focus();
                        setMention({ query: '', start: value.length + (value && !value.endsWith(' ') ? 1 : 0) });
                      });
                    }}
                  />
                </div>
              </>
            )}
          </div>

          <button
            onClick={toggleDictation}
            title="Dictate"
            className={`p-1.5 rounded-lg transition-all ${listening ? 'text-red-400 bg-red-500/15 animate-glow' : 'text-gray-500 hover:text-white hover:bg-white/[0.06]'}`}
          >
            {listening ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
          </button>

          <div className="flex-1" />

          <span className="text-[10px] text-gray-600 hidden sm:flex items-center gap-1 mr-1">
            <CornerDownLeft className="w-3 h-3" /> to {idle ? 'send' : 'queue'}
          </span>

          {!idle ? (
            <button onClick={onStop} className="p-2 bg-red-500/90 hover:bg-red-500 rounded-lg text-white transition-all" title="Stop">
              <Square className="w-3.5 h-3.5" />
            </button>
          ) : (
            <button
              onClick={onSend}
              disabled={!canSend}
              className="p-2 bg-gradient-to-r from-violet-600 to-cyan-600 rounded-lg text-white disabled:opacity-30 transition-all hover:shadow-lg hover:shadow-violet-500/25"
              title={mode === 'plan' ? 'Ask' : 'Send'}
            >
              {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function MenuItem({ icon, label, hint, onClick }: { icon: React.ReactNode; label: string; hint?: string; onClick: () => void }) {
  return (
    <button onClick={onClick} className="w-full text-left px-3 py-2 hover:bg-white/[0.05] transition-colors flex items-start gap-2.5">
      <span className="text-gray-400 mt-0.5">{icon}</span>
      <span className="min-w-0">
        <span className="block text-xs text-gray-200">{label}</span>
        {hint && <span className="block text-[10px] text-gray-600">{hint}</span>}
      </span>
    </button>
  );
}

function iconFor(path: string): string {
  const ext = path.split('.').pop()?.toLowerCase() || '';
  const m: Record<string, string> = {
    html: '🌐', css: '🎨', js: '⚡', ts: '🔷', jsx: '⚛', tsx: '⚛',
    json: '📋', md: '📝', py: '🐍', yml: '⚙', yaml: '⚙',
  };
  return m[ext] || '📄';
}
