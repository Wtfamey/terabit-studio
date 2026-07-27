import { useState, useEffect, useRef, useCallback } from 'react';
import { UserAsset } from '../types';
import { ENDPOINTS, ASSETS_BASE } from '../config';
import axios from 'axios';
import {
  Upload, Trash2, Image, FileText, Loader2, X, AlertCircle, Check
} from 'lucide-react';

interface AssetManagerProps {
  onAssetsChange?: (assets: UserAsset[]) => void;
  compact?: boolean;
}

const MIME_ICONS: Record<string, React.ReactNode> = {
  'image/': <Image className="w-5 h-5 text-emerald-400" />,
  'application/pdf': <FileText className="w-5 h-5 text-red-400" />,
  'text/': <FileText className="w-5 h-5 text-blue-400" />,
};

function getAssetIcon(mime: string) {
  for (const [prefix, icon] of Object.entries(MIME_ICONS)) {
    if (mime.startsWith(prefix)) return icon;
  }
  return <FileText className="w-5 h-5 text-gray-400" />;
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

export function AssetManager({ onAssetsChange, compact }: AssetManagerProps) {
  const [assets, setAssets] = useState<UserAsset[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const loadAssets = useCallback(async () => {
    try {
      const res = await axios.get(ENDPOINTS.assets);
      setAssets(res.data);
      onAssetsChange?.(res.data);
    } catch {
      // silently fail for anonymous users
    }
  }, [onAssetsChange]);

  useEffect(() => { loadAssets(); }, [loadAssets]);

  const upload = async (file: File) => {
    setError(null);
    const allowed = ['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/svg+xml', 'application/pdf', 'text/plain', 'text/csv'];
    if (!allowed.includes(file.type)) {
      setError(`Unsupported type: ${file.type}`);
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setError('File too large (max 10MB)');
      return;
    }
    setUploading(true);
    try {
      const form = new FormData();
      form.append('file', file);
      await axios.post(ENDPOINTS.upload, form);
      await loadAssets();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) upload(f);
  };

  const handleDelete = async (id: number) => {
    try {
      await axios.delete(`${ENDPOINTS.assets}/${id}`);
      setAssets(prev => prev.filter(a => a.id !== id));
      onAssetsChange?.(assets.filter(a => a.id !== id));
    } catch {}
  };

  return (
    <div>
      {!compact && (
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Your Assets</h3>
          <span className="text-[10px] text-gray-600">{assets.length} file{assets.length !== 1 ? 's' : ''}</span>
        </div>
      )}

      <div
        onDragOver={e => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={`border-2 border-dashed rounded-xl p-4 text-center cursor-pointer transition-all ${
          dragging
            ? 'border-violet-500 bg-violet-500/10'
            : 'border-white/[0.08] hover:border-violet-500/40 hover:bg-white/[0.02]'
        } ${compact ? 'mb-2' : 'mb-3'}`}
      >
        <input
          ref={inputRef}
          type="file"
          accept="image/*,application/pdf,text/plain,text/csv"
          className="hidden"
          onChange={e => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ''; }}
        />
        {uploading ? (
          <Loader2 className="w-5 h-5 mx-auto text-violet-400 animate-spin" />
        ) : (
          <Upload className="w-5 h-5 mx-auto text-gray-500 mb-1" />
        )}
        <p className="text-[10px] text-gray-500">
          {uploading ? 'Uploading...' : 'Drop images or assets here, or click to browse'}
        </p>
        <p className="text-[9px] text-gray-600 mt-0.5">JPEG, PNG, GIF, WebP, SVG, PDF — max 10MB</p>
      </div>

      {error && (
        <div className="flex items-center gap-1.5 mb-2 p-2 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-[10px]">
          <AlertCircle className="w-3 h-3 flex-shrink-0" />
          {error}
        </div>
      )}

      {assets.length > 0 && (
        <div className={`grid gap-2 ${compact ? 'grid-cols-3' : 'grid-cols-2'}`}>
          {assets.map(a => (
            <div key={a.id} className="group relative bg-white/[0.03] border border-white/[0.06] rounded-lg overflow-hidden hover:border-white/10 transition-all">
              {a.mime_type.startsWith('image/') ? (
                <div className="aspect-square bg-black/20 flex items-center justify-center overflow-hidden">
                  <img
                    src={`${ASSETS_BASE}/${a.filename}`}
                    alt={a.original_name}
                    className="w-full h-full object-cover"
                    loading="lazy"
                  />
                </div>
              ) : (
                <div className="aspect-square flex items-center justify-center bg-white/[0.02]">
                  {getAssetIcon(a.mime_type)}
                </div>
              )}
              <div className="p-1.5">
                <p className="text-[10px] text-gray-400 truncate">{a.original_name}</p>
                <p className="text-[9px] text-gray-600">{formatSize(a.size)}</p>
              </div>
              <button
                onClick={e => { e.stopPropagation(); handleDelete(a.id); }}
                className="absolute top-1 right-1 p-1 bg-black/60 rounded-full text-gray-400 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all"
              >
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>
      )}

      {assets.length === 0 && !compact && (
        <p className="text-xs text-gray-600 text-center py-4">No assets uploaded yet. Drop your brand logos, product images, or any files you want the AI to use.</p>
      )}
    </div>
  );
}
