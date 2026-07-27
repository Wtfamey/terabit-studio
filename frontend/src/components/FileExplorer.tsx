import { useState } from 'react';
import { FileItem } from '../types';
import { ChevronRight, ChevronDown, FolderOpen } from 'lucide-react';

interface FileNodeProps {
  item: FileItem;
  depth: number;
  onFileClick: (file: FileItem) => void;
  selectedPath?: string;
}

const FILE_ICONS: Record<string, string> = {
  html: '🌐', htm: '🌐',
  css: '🎨', scss: '🎨', less: '🎨',
  js: '⚡', mjs: '⚡', cjs: '⚡',
  ts: '🔷', tsx: '⚛', jsx: '⚛',
  json: '📋', md: '📝', mdx: '📝',
  py: '🐍', rb: '💎', rs: '🦀', go: '🔵', java: '☕',
  yml: '⚙', yaml: '⚙', toml: '⚙', ini: '⚙', cfg: '⚙',
  env: '🔒', gitignore: '🙈', dockerfile: '🐳',
  vue: '💚', svelte: '🧡', astro: '🧑‍🚀',
  test: '🧪', spec: '🧪',
  lock: '🔒', lockb: '🔒',
};

function getFileIcon(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase() || '';
  const lower = name.toLowerCase();
  if (lower === 'dockerfile') return '🐳';
  if (lower === '.gitignore') return '🙈';
  if (lower === '.env') return '🔒';
  if (lower === 'package.json') return '📦';
  if (lower === 'readme.md') return '📖';
  if (lower.startsWith('.env')) return '🔒';
  return FILE_ICONS[ext] || '📄';
}

function FileNode({ item, depth, onFileClick, selectedPath }: FileNodeProps) {
  const [expanded, setExpanded] = useState(true);

  const handleClick = () => {
    if (item.type === 'folder') {
      setExpanded(!expanded);
    } else {
      onFileClick(item);
    }
  };

  const isSelected = selectedPath === item.path;

  return (
    <div>
      <button
        onClick={handleClick}
        className={`w-full flex items-center gap-1.5 px-2 py-1 rounded-lg text-sm transition-all group ${
          isSelected
            ? 'bg-violet-500/15 text-violet-300'
            : 'text-gray-400 hover:text-gray-200 hover:bg-white/[0.03]'
        }`}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        {item.type === 'folder' ? (
          <>
            <span className="flex-shrink-0 w-4 flex justify-center">
              {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            </span>
            <FolderOpen className={`w-4 h-4 flex-shrink-0 ${expanded ? 'text-amber-400' : 'text-amber-500'}`} />
          </>
        ) : (
          <>
            <span className="w-4" />
            <span className="flex-shrink-0 text-[10px] leading-none">{getFileIcon(item.name)}</span>
          </>
        )}
        <span className="truncate text-xs">{item.name}</span>
      </button>
      {item.type === 'folder' && expanded && item.children && (
        <div>
          {item.children.map((child, idx) => (
            <FileNode
              key={`${child.path}-${idx}`}
              item={child}
              depth={depth + 1}
              onFileClick={onFileClick}
              selectedPath={selectedPath}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface FileExplorerProps {
  files: FileItem[];
  onFileSelect: (file: FileItem) => void;
  selectedPath?: string;
}

export function FileExplorer({ files, onFileSelect, selectedPath }: FileExplorerProps) {
  return (
    <div>
      <div className="flex items-center justify-between px-2 mb-3">
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Files</h3>
        {files.length > 0 && (
          <span className="text-[10px] text-gray-600">{files.length} items</span>
        )}
      </div>
      {files.length === 0 ? (
        <p className="text-xs text-gray-600 px-2">No files yet. Generate a project to see files.</p>
      ) : (
        files.map((file, idx) => (
          <FileNode
            key={`${file.path}-${idx}`}
            item={file}
            depth={0}
            onFileClick={onFileSelect}
            selectedPath={selectedPath}
          />
        ))
      )}
    </div>
  );
}
