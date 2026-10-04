import { History, RotateCcw, Check, Clock, FileCode2, Lock } from 'lucide-react';

export interface Version {
  id: number;
  label: string;
  at: number;
  fileCount: number;
  /** true for the version currently shown on the canvas */
  current?: boolean;
}

interface VersionHistoryProps {
  versions: Version[];
  onRestore: (id: number) => void;
  /** restores are disabled while the agent is mid-build, like Bolt */
  locked: boolean;
  onClose: () => void;
}

function relTime(ts: number): string {
  const s = Math.max(0, Math.round((Date.now() - ts) / 1000));
  if (s < 60) return 'just now';
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

export function VersionHistory({ versions, onRestore, locked, onClose }: VersionHistoryProps) {
  return (
    <div className="w-72 bg-[#0b0b14] border-r border-white/[0.05] flex flex-col flex-shrink-0 z-10 animate-slide-left">
      <div className="flex items-center gap-2 px-3 py-2.5 border-b border-white/[0.05]">
        <History className="w-3.5 h-3.5 text-cyan-400" />
        <span className="text-xs font-semibold text-gray-300">Version history</span>
        <button onClick={onClose} className="ml-auto text-gray-600 hover:text-white text-[11px]">Close</button>
      </div>

      {locked && (
        <div className="mx-3 mt-3 flex items-start gap-2 px-2.5 py-2 bg-amber-500/10 border border-amber-500/20 rounded-lg">
          <Lock className="w-3.5 h-3.5 text-amber-400 flex-shrink-0 mt-0.5" />
          <p className="text-[10px] text-amber-300/90 leading-snug">
            Stop or wait for the current build to finish before restoring a version.
          </p>
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-2">
        {versions.length === 0 ? (
          <p className="text-xs text-gray-600 px-2 py-3">No versions yet. Each build saves a restore point here.</p>
        ) : (
          <div className="relative">
            {/* the vertical rail */}
            <div className="absolute left-[15px] top-2 bottom-2 w-px bg-white/[0.07]" />
            <div className="space-y-1">
              {versions.map(v => (
                <div key={v.id} className="relative flex items-start gap-2.5 pl-1">
                  <span className={`relative z-10 mt-1.5 w-2.5 h-2.5 rounded-full border-2 flex-shrink-0 ${
                    v.current
                      ? 'bg-cyan-400 border-cyan-400'
                      : 'bg-[#0b0b14] border-white/20'
                  }`} />
                  <button
                    onClick={() => !locked && !v.current && onRestore(v.id)}
                    disabled={locked || v.current}
                    className={`flex-1 text-left rounded-lg px-2.5 py-2 transition-all group ${
                      v.current
                        ? 'bg-cyan-500/10 border border-cyan-500/25'
                        : locked
                          ? 'opacity-50 cursor-not-allowed'
                          : 'hover:bg-white/[0.04] border border-transparent'
                    }`}
                  >
                    <div className="flex items-center gap-1.5">
                      <span className={`text-[11.5px] truncate ${v.current ? 'text-cyan-200' : 'text-gray-300'}`}>
                        {v.label || 'Initial version'}
                      </span>
                      {v.current && <Check className="w-3 h-3 text-cyan-400 flex-shrink-0" />}
                    </div>
                    <div className="flex items-center gap-2.5 mt-0.5 text-[10px] text-gray-600">
                      <span className="flex items-center gap-1"><Clock className="w-2.5 h-2.5" />{relTime(v.at)}</span>
                      <span className="flex items-center gap-1"><FileCode2 className="w-2.5 h-2.5" />{v.fileCount}</span>
                    </div>
                  </button>
                  {!v.current && !locked && (
                    <RotateCcw className="w-3 h-3 text-gray-600 group-hover:text-cyan-400 mt-2 mr-1 flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" />
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
