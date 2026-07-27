import { useMemo, useState, useEffect } from 'react';
import { FileItem, GeneratedFile } from '../types';
import { Monitor, Globe, FolderOpen, ChevronRight, ChevronDown, Loader2 } from 'lucide-react';
import axios from 'axios';
import { ENDPOINTS } from '../config';

interface PreviewFrameProps {
  files: FileItem[];
}

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

export function PreviewFrame({ files }: PreviewFrameProps) {
  const [previewHtml, setPreviewHtml] = useState<string | null>(null);
  const [building, setBuilding] = useState(false);

  const flatFiles = useMemo(() => flattenFiles(files), [files]);
  const projectFilesCount = flatFiles.length;

  useEffect(() => {
    if (flatFiles.length === 0) {
      setPreviewHtml(null);
      return;
    }
    // Only take the raw-HTML shortcut for genuinely static projects (no
    // separate component files) - anything with .js/.jsx/.ts/.tsx files
    // needs the backend bundler to resolve imports/exports between them,
    // otherwise the raw index.html's <script src="/src/main.jsx"> just
    // 404s inside the sandboxed iframe and nothing renders.
    const hasComponents = flatFiles.some(f => /\.(jsx?|tsx?)$/.test(f.path));
    if (!hasComponents) {
      const cached = previewContentFromFiles(flatFiles);
      if (cached) {
        setPreviewHtml(cached);
        return;
      }
    }
    setBuilding(true);
    axios.post(ENDPOINTS.preview, { files: flatFiles })
      .then(r => setPreviewHtml(r.data.html))
      .catch(() => {
        // Fallback: use raw index.html
        const idx = flatFiles.find(f => f.path === 'index.html' || f.path.endsWith('/index.html'));
        setPreviewHtml(idx?.content || null);
      })
      .finally(() => setBuilding(false));
  }, [flatFiles]);

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
          <span className="text-xs text-gray-400">Live Preview</span>
          <span className="text-[10px] text-gray-600 ml-auto">{projectFilesCount} files</span>
        </div>
        <div className="flex-1 bg-white">
          <iframe
            srcDoc={previewHtml}
            className="w-full h-full border-none"
            title="Preview"
            sandbox="allow-scripts allow-same-origin"
          />
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
        <div className="h-full flex items-center justify-center text-gray-500">
          <div className="text-center max-w-sm">
            <Monitor className="w-12 h-12 mx-auto mb-3 opacity-30" />
            <p className="text-sm text-gray-500 mb-1">No files to preview</p>
            <p className="text-xs text-gray-600">Generate a project above to see files and preview.</p>
          </div>
        </div>
      )}
    </div>
  );
}
