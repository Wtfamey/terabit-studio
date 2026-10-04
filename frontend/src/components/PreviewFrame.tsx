import { useMemo, useState, useEffect, useRef } from 'react';
import { FileItem, GeneratedFile } from '../types';
import { Monitor, Globe, FolderOpen, ChevronRight, ChevronDown, Loader2, AlertTriangle, RefreshCw, ExternalLink, Hammer, Crosshair, Smartphone, Tablet, MousePointerClick } from 'lucide-react';
import axios from 'axios';
import { ENDPOINTS } from '../config';

/** Injected into every preview so the host can drive element selection.
 *  Kept self-contained and defensive: a failure here must never break the
 *  generated app. Communicates over the existing 'terabit-preview' channel. */
const SELECT_TOOL_SCRIPT = `<script>(function () {
  if (window.__terabitSelectInstalled) return;
  window.__terabitSelectInstalled = true;
  var on = false, hovered = null, styleEl = null;
  function ensureStyle() {
    if (styleEl) return;
    styleEl = document.createElement('style');
    styleEl.textContent = '.__tb_hover{outline:2px solid #22d3ee !important;outline-offset:2px !important;cursor:crosshair !important}*{cursor:crosshair !important}'
      + 'html,body{cursor:crosshair !important}';
    document.head.appendChild(styleEl);
  }
  function describe(el) {
    if (!el || el === document.documentElement || el === document.body) return null;
    var label = el.tagName.toLowerCase();
    if (el.id) label += '#' + el.id;
    var cls = (el.getAttribute('class') || '').split(/\\s+/).filter(Boolean);
    if (cls.length) label += '.' + cls.slice(0, 3).join('.');
    var txt = (el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
    var imgs = el.querySelectorAll('img').length;
    var btns = el.querySelectorAll('button,a').length;
    var extra = [];
    if (imgs) extra.push(imgs + ' image' + (imgs > 1 ? 's' : ''));
    if (btns) extra.push(btns + ' interactive');
    return { label: label, text: txt, detail: extra.join(' · ') };
  }
  function clearHover() {
    if (hovered) { hovered.classList.remove('__tb_hover'); hovered = null; }
  }
  function onOver(e) { if (!on) return; clearHover(); hovered = e.target; if (hovered && hovered.classList) hovered.classList.add('__tb_hover'); }
  function onOut() { clearHover(); }
  function onClick(e) {
    if (!on) return;
    e.preventDefault(); e.stopPropagation();
    var info = describe(e.target);
    if (!info) return;
    var rect = e.target.getBoundingClientRect();
    window.parent.postMessage({
      source: 'terabit-preview', type: 'element-selected',
      payload: { label: info.label, text: info.text, detail: info.detail,
                 box: { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) } }
    }, '*');
  }
  window.addEventListener('message', function (e) {
    var d = e.data;
    if (!d || d.source !== 'terabit-host' || d.type !== 'set-select-mode') return;
    on = !!d.on;
    if (on) { ensureStyle(); document.addEventListener('mouseover', onOver, true); document.addEventListener('mouseout', onOut, true); document.addEventListener('click', onClick, true); }
    else {
      clearHover(); document.removeEventListener('mouseover', onOver, true); document.removeEventListener('mouseout', onOut, true); document.removeEventListener('click', onClick, true);
      if (styleEl && styleEl.parentNode) styleEl.parentNode.removeChild(styleEl); styleEl = null;
    }
  });
})();</script>`;

function injectSelectTool(html: string): string {
  if (html.includes('__terabitSelectInstalled')) return html;
  if (/<\/body>/i.test(html)) return html.replace(/<\/body>/i, `${SELECT_TOOL_SCRIPT}</body>`);
  return html + SELECT_TOOL_SCRIPT;
}

interface ElementSelection {
  label: string;
  text: string;
  detail?: string;
}

interface PreviewFrameProps {
  files: FileItem[];
  onRuntimeError?: (message: string) => void;
  onElementSelect?: (sel: ElementSelection) => void;
}

type Device = 'desktop' | 'tablet' | 'mobile';
const DEVICE_WIDTH: Record<Device, number | null> = { desktop: null, tablet: 834, mobile: 400 };

function flattenFiles(items: FileItem[]): GeneratedFile[] {
  const result: GeneratedFile[] = [];
  const walk = (list: FileItem[]) => {
    for (const f of list) {
      if (f.type === 'file' && f.content) result.push({ path: f.path, content: f.content });
      if (f.children) walk(f.children);
    }
  };
  walk(items);
  return result;
}

function previewContentFromFiles(files: GeneratedFile[]): string | null {
  const html = files.find(f => f.path === 'index.html' || f.path.endsWith('/index.html'));
  const preview = files.find(f => f.path === 'preview.html');
  return preview?.content || html?.content || null;
}

function StructureView({ files, depth = 0 }: { files: FileItem[]; depth?: number }) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const toggle = (path: string) => setExpanded(p => ({ ...p, [path]: !p[path] }));
  return (
    <div className="font-mono text-xs">
      {files.map(item => {
        const isExpanded = expanded[item.path] !== false;
        return (
          <div key={item.path}>
            <div
              className="flex items-center gap-1.5 py-1 hover:bg-white/[0.03] rounded px-2 cursor-pointer"
              style={{ paddingLeft: `${depth * 16 + 8}px` }}
              onClick={() => item.type === 'folder' && toggle(item.path)}
            >
              {item.type === 'folder' ? (
                <>
                  {isExpanded ? <ChevronDown className="w-3 h-3 text-gray-500" /> : <ChevronRight className="w-3 h-3 text-gray-500" />}
                  <FolderOpen className="w-3.5 h-3.5 text-amber-400" />
                </>
              ) : (
                <>
                  <span className="w-3" />
                  <span className="text-[10px]">{getIcon(item.name)}</span>
                </>
              )}
              <span className="text-gray-300">{item.name}</span>
              {item.name === 'index.html' && <span className="text-cyan-500 text-[10px] ml-1">(preview)</span>}
            </div>
            {item.type === 'folder' && isExpanded && item.children && (
              <StructureView files={item.children} depth={depth + 1} />
            )}
          </div>
        );
      })}
    </div>
  );
}

function getIcon(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase() || '';
  const m: Record<string, string> = {
    html: '🌐', css: '🎨', js: '⚡', ts: '🔷', jsx: '⚛', tsx: '⚛',
    json: '📋', md: '📝', py: '🐍', yml: '⚙', yaml: '⚙',
  };
  return m[ext] || '📄';
}

export function PreviewFrame({ files, onRuntimeError, onElementSelect }: PreviewFrameProps) {
  const [previewHtml, setPreviewHtml] = useState<string | null>(null);
  const [tier, setTier] = useState<string | null>(null);
  const [building, setBuilding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryCount, setRetryCount] = useState(0);
  const [runtimeError, setRuntimeError] = useState<string | null>(null);
  const [device, setDevice] = useState<Device>('desktop');
  const [selectMode, setSelectMode] = useState(false);
  const maxRetries = 3;
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const loadTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const htmlForFrame = useMemo(
    () => (previewHtml ? injectSelectTool(previewHtml) : null),
    [previewHtml],
  );

  // Push the current select-mode into the iframe whenever it changes (and
  // after a rebuild, since a fresh document loses the listener).
  useEffect(() => {
    if (!htmlForFrame) return;
    const id = setTimeout(() => {
      iframeRef.current?.contentWindow?.postMessage(
        { source: 'terabit-host', type: 'set-select-mode', on: selectMode }, '*',
      );
    }, 700);
    return () => clearTimeout(id);
  }, [selectMode, htmlForFrame]);

  // Runtime errors reported by the preview's in-iframe error overlay
  // (window.onerror / unhandledrejection inside the generated app).
  useEffect(() => {
    const handler = (e: MessageEvent) => {
      const d = e.data;
      if (!d || d.source !== 'terabit-preview') return;
      if (d.type === 'element-selected') {
        const p = d.payload || {};
        onElementSelect?.({ label: p.label || 'element', text: p.text || '', detail: p.detail });
        // One selection is enough -- drop out of select mode so clicks work again.
        setSelectMode(false);
        return;
      }
      if (d.type !== 'runtime-error') return;
      setRuntimeError(`[preview] ${d.title}: ${d.message}`);
      onRuntimeError?.(`[preview] ${d.title}: ${d.message}`);
    };
    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, [onRuntimeError, onElementSelect]);

  const flatFiles = useMemo(() => flattenFiles(files), [files]);
  const projectFilesCount = flatFiles.length;

  const clearLoadTimeout = () => {
    if (loadTimeoutRef.current) {
      clearTimeout(loadTimeoutRef.current);
      loadTimeoutRef.current = null;
    }
  };

  const buildPreview = async () => {
    if (flatFiles.length === 0) {
      setPreviewHtml(null);
      return;
    }
    
    const hasComponents = flatFiles.some(f => /\.(jsx?|tsx?)$/.test(f.path));
    if (!hasComponents) {
      const cached = previewContentFromFiles(flatFiles);
      if (cached) {
        setPreviewHtml(cached);
        return;
      }
    }
    
    setBuilding(true);
    setError(null);
    setRuntimeError(null);
    console.log('[Preview] Building preview with', flatFiles.length, 'files');
    
    try {
      const res = await axios.post(ENDPOINTS.preview, { files: flatFiles }, { timeout: 30000 });
      console.log('[Preview] Preview built successfully');
      setPreviewHtml(res.data.html);
      // Which tier the server reached: tier1 = real esbuild+Tailwind bundle
      // (offline-capable); tier2/tier3 mean the project didn't compile and the
      // server fell back. Surfaced in the toolbar so it is never silent.
      setTier(typeof res.data.tier === 'string' ? res.data.tier : null);
      setRetryCount(0);
    } catch (err: any) {
      console.error('[Preview] Build failed:', err);
      const errMsg = err?.response?.data?.detail || err.message || 'Preview generation failed';
      
      // Try fallback: raw index.html
      const idx = flatFiles.find(f => f.path === 'index.html' || f.path.endsWith('/index.html'));
      if (idx?.content) {
        setPreviewHtml(idx.content);
        console.log('[Preview] Using raw index.html fallback');
      } else {
        setError(errMsg);
      }
    } finally {
      setBuilding(false);
      clearLoadTimeout();
    }
  };

  useEffect(() => {
    buildPreview();
    
    // Cleanup on unmount
    return () => clearLoadTimeout();
  }, [flatFiles]);

  // Handle iframe load errors
  const handleIframeError = () => {
    console.error('[Preview] Iframe failed to load');
    if (retryCount < maxRetries) {
      console.log(`[Preview] Retrying... (${retryCount + 1}/${maxRetries})`);
      setRetryCount(c => c + 1);
      buildPreview();
    } else {
      setError('Preview failed to load after retries. Check console for details.');
    }
  };

  // Handle iframe load success - check if content actually rendered
  const handleIframeLoad = () => {
    // Check if iframe has content after a short delay
    loadTimeoutRef.current = setTimeout(() => {
      try {
        const iframeDoc = iframeRef.current?.contentDocument || iframeRef.current?.contentWindow?.document;
        if (iframeDoc && iframeDoc.body && iframeDoc.body.innerHTML.trim() === '') {
          console.warn('[Preview] Iframe loaded but appears empty');
          if (retryCount < maxRetries) {
            setRetryCount(c => c + 1);
            buildPreview();
          }
        }
      } catch (e) {
        // Cross-origin or other error - can't inspect
        console.log('[Preview] Iframe loaded (cross-origin, cannot inspect content)');
      }
    }, 5000); // Increased from 2s to 5s for large bundles
  };

  if (building) {
    return (
      <div className="h-full flex flex-col">
        <div className="flex items-center gap-2 px-4 py-2 bg-black/20 border-b border-white/5">
          <Monitor className="w-4 h-4 text-cyan-400" />
          <span className="text-xs text-gray-400">Preview</span>
        </div>
        <div className="flex-1 flex items-center justify-center text-gray-500">
          <div className="text-center">
            <Loader2 className="w-8 h-8 mx-auto mb-2 animate-spin text-violet-400" />
            <p className="text-sm">Building preview...</p>
          </div>
        </div>
      </div>
    );
  }

  if (previewHtml) {
    return (
      <div className="h-full flex flex-col">
        <div className="flex items-center gap-2 px-4 py-2 bg-black/20 border-b border-white/5">
          <Monitor className="w-4 h-4 text-cyan-400" />
          <span className="text-xs font-medium text-gray-300">Live Preview</span>
          {tier && tier !== 'tier1-bundled' && (
            <span
              className="text-[10px] text-amber-500 flex items-center gap-1 bg-amber-500/10 px-2 py-0.5 rounded-full"
              title={tier === 'tier2-cdn'
                ? 'The project did not bundle with esbuild; the preview is running through the in-browser CDN fallback (needs internet).'
                : 'No bundleable app found; showing the file listing fallback.'}
            >
              <AlertTriangle className="w-3 h-3" />
              {tier === 'tier2-cdn' ? 'CDN fallback' : 'File listing'}
            </span>
          )}
          {error && (
            <span className="text-[10px] text-amber-500 flex items-center gap-1 bg-amber-500/10 px-2 py-0.5 rounded-full">
              <AlertTriangle className="w-3 h-3" />
              Fallback Mode
            </span>
          )}
          <div className="ml-auto flex items-center gap-1.5">
            {/* device switcher */}
            <div className="flex bg-white/[0.04] rounded-lg p-0.5 border border-white/[0.06]">
              <DeviceButton active={device === 'desktop'} onClick={() => setDevice('desktop')} icon={<Monitor className="w-3 h-3" />} label="Desktop" />
              <DeviceButton active={device === 'tablet'} onClick={() => setDevice('tablet')} icon={<Tablet className="w-3 h-3" />} label="Tablet" />
              <DeviceButton active={device === 'mobile'} onClick={() => setDevice('mobile')} icon={<Smartphone className="w-3 h-3" />} label="Mobile" />
            </div>
            <button
              onClick={() => setSelectMode(s => !s)}
              title="Select an element in the preview to focus your prompt on it"
              className={`flex items-center gap-1.5 px-2 py-1 rounded-md text-[10px] font-medium transition-all border ${
                selectMode
                  ? 'bg-cyan-500/20 border-cyan-500/40 text-cyan-300'
                  : 'bg-white/[0.03] border-white/[0.08] text-gray-400 hover:text-white hover:bg-white/10'
              }`}
            >
              <Crosshair className="w-3 h-3" /> Select
            </button>
            <span className="text-[10px] text-gray-600">{projectFilesCount} files</span>
            <button
              onClick={buildPreview}
              title="Refresh Preview"
              className="p-1 rounded-md text-gray-400 hover:text-white hover:bg-white/10 transition-all"
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={() => {
                const blob = new Blob([previewHtml], { type: 'text/html' });
                const url = URL.createObjectURL(blob);
                window.open(url, '_blank');
              }}
              title="Open preview in new window"
              className="p-1 rounded-md text-gray-400 hover:text-white hover:bg-white/10 transition-all"
            >
              <ExternalLink className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
        {selectMode && (
          <div className="flex items-center gap-2 px-4 py-1.5 bg-cyan-500/10 border-b border-cyan-500/20 text-[11px] text-cyan-300">
            <MousePointerClick className="w-3.5 h-3.5" />
            Click any element in the preview to focus your next prompt on it
            <button onClick={() => setSelectMode(false)} className="ml-auto text-cyan-500/70 hover:text-cyan-200 text-[10px]">Cancel (Esc)</button>
          </div>
        )}
        <div className="flex-1 bg-[#020617] relative overflow-auto flex justify-center">
          <div
            className="relative bg-white transition-[width] duration-300 ease-out"
            style={{
              width: DEVICE_WIDTH[device] ? `${DEVICE_WIDTH[device]}px` : '100%',
              maxWidth: '100%',
              height: '100%',
            }}
          >
          <iframe
            ref={iframeRef}
            srcDoc={htmlForFrame ?? previewHtml}
            className="w-full h-full border-none"
            title="Preview"
            sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals allow-downloads allow-popups-to-escape-sandbox"
            onError={handleIframeError}
            onLoad={handleIframeLoad}
          />
          </div>
          {runtimeError && (
            <div className="absolute top-2 left-2 right-2 z-20 flex items-start gap-2 bg-red-500/10 border border-red-500/30 rounded-lg p-2.5 backdrop-blur-sm">
              <AlertTriangle className="w-4 h-4 text-red-400 flex-shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0">
                <p className="text-[11px] font-medium text-red-300">Runtime error in preview</p>
                <p className="text-[10px] text-red-400/80 font-mono truncate">{runtimeError.slice(0, 160)}</p>
              </div>
              {onRuntimeError && (
                <button
                  onClick={() => onRuntimeError(runtimeError)}
                  className="flex-shrink-0 flex items-center gap-1 px-2 py-1 bg-violet-600 hover:bg-violet-500 rounded-md text-[10px] font-medium text-white transition-all"
                >
                  <Hammer className="w-3 h-3" /> Fix with agent
                </button>
              )}
            </div>
          )}
          {error && (
            <div className="absolute inset-0 bg-black/80 flex items-center justify-center z-10 p-4">
              <div className="bg-gray-900 border border-red-500/30 rounded-xl p-6 max-w-md text-center">
                <AlertTriangle className="w-10 h-10 text-red-400 mx-auto mb-3" />
                <h3 className="text-white font-semibold mb-2">Preview Error</h3>
                <p className="text-gray-400 text-sm mb-4">{error}</p>
                <button
                  onClick={buildPreview}
                  className="px-4 py-2 bg-violet-600 hover:bg-violet-700 rounded-lg text-white text-sm flex items-center gap-2 mx-auto"
                >
                  <RefreshCw className="w-4 h-4" />
                  Retry
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-2 px-4 py-2 bg-black/20 border-b border-white/5">
        <Monitor className="w-4 h-4 text-cyan-400" />
        <span className="text-xs text-gray-400">Preview</span>
        {projectFilesCount > 0 && <span className="text-[10px] text-gray-600 ml-auto">{projectFilesCount} files generated</span>}
      </div>
      {files.length > 0 ? (
        <div className="flex-1 overflow-y-auto p-6">
          <div className="max-w-2xl mx-auto">
            <div className="flex items-center gap-3 mb-6">
              <Globe className="w-8 h-8 text-violet-400" />
              <div>
                <h2 className="text-lg font-semibold text-gray-200">Project Generated</h2>
                <p className="text-sm text-gray-500">{projectFilesCount} files · Preview requires an index.html</p>
              </div>
            </div>
            <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-4">
              <div className="flex items-center gap-2 mb-3 text-xs text-gray-500 uppercase tracking-wider">
                <FolderOpen className="w-3.5 h-3.5" />
                Project Structure
              </div>
              <StructureView files={files} />
            </div>
          </div>
        </div>
      ) : (
        <div className="flex-1 grid-backdrop flex items-center justify-center">
          <div className="text-center max-w-sm animate-fade-in">
            <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-gradient-to-br from-violet-600/20 to-cyan-600/20 border border-white/[0.06] flex items-center justify-center">
              <Monitor className="w-7 h-7 text-violet-300/70" />
            </div>
            <p className="text-sm text-gray-400 mb-1">Your live preview appears here</p>
            <p className="text-xs text-gray-600 leading-relaxed">
              Describe what to build in the chat and the app will render, fully interactive,
              the moment the bundle is verified.
            </p>
            <p className="text-[10px] text-gray-700 mt-4">
              Tip: after generating, use <span className="text-cyan-500/80">Select</span> to click
              any element and target your next prompt at it.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

function DeviceButton({ active, onClick, icon, label }: {
  active: boolean; onClick: () => void; icon: React.ReactNode; label: string;
}) {
  return (
    <button
      onClick={onClick}
      title={label}
      className={`flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium transition-all ${
        active ? 'bg-cyan-500/20 text-cyan-300' : 'text-gray-500 hover:text-gray-300'
      }`}
    >
      {icon}
      <span className="hidden lg:inline">{label}</span>
    </button>
  );
}
