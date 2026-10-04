import { useEffect, useMemo, useRef } from 'react';
import {
  CheckCircle2, Loader2, FileCode2, Hammer, ShieldCheck, Layers,
  Palette, Wrench, RefreshCw, Sparkles, AlertTriangle, Package,
} from 'lucide-react';

interface AgentStepsProps {
  lines: string[];
  /** true while the run is still streaming (last step shows as active) */
  running: boolean;
  /** collapse to a compact one-line summary */
  compact?: boolean;
}

type Kind =
  | 'architect' | 'write' | 'shell' | 'assemble' | 'style'
  | 'verify' | 'repair' | 'retry' | 'done' | 'warn' | 'info';

interface Step {
  kind: Kind;
  label: string;
  detail?: string;
  /** file progress numerator/denominator when known */
  progress?: [number, number];
}

const ICONS: Record<Kind, React.ReactNode> = {
  architect: <Sparkles className="w-3.5 h-3.5" />,
  write: <FileCode2 className="w-3.5 h-3.5" />,
  shell: <Layers className="w-3.5 h-3.5" />,
  assemble: <Package className="w-3.5 h-3.5" />,
  style: <Palette className="w-3.5 h-3.5" />,
  verify: <ShieldCheck className="w-3.5 h-3.5" />,
  repair: <Hammer className="w-3.5 h-3.5" />,
  retry: <RefreshCw className="w-3.5 h-3.5" />,
  done: <CheckCircle2 className="w-3.5 h-3.5" />,
  warn: <AlertTriangle className="w-3.5 h-3.5" />,
  info: <Wrench className="w-3.5 h-3.5" />,
};

const TONE: Record<Kind, string> = {
  architect: 'text-violet-400',
  write: 'text-gray-400',
  shell: 'text-sky-400',
  assemble: 'text-amber-400',
  style: 'text-fuchsia-400',
  verify: 'text-cyan-400',
  repair: 'text-orange-400',
  retry: 'text-yellow-400',
  done: 'text-green-400',
  warn: 'text-red-400',
  info: 'text-gray-400',
};

/** Turn a raw agent progress line into a structured step. */
function classify(line: string): Step {
  const writing = line.match(/^Writing\s+(.+?)\s*\((\d+)\/(\d+)\)\.\.\./);
  if (writing) {
    return {
      kind: 'write',
      label: writing[1],
      detail: `file ${writing[2]} of ${writing[3]}`,
      progress: [Number(writing[2]), Number(writing[3])],
    };
  }
  if (/^Architecting/.test(line)) return { kind: 'architect', label: 'Planning the file structure' };
  if (/^App shell will be composed/.test(line)) return { kind: 'shell', label: 'Composing the app shell from generated sections' };
  if (/^Assembling project/.test(line)) return { kind: 'assemble', label: 'Assembling the project' };
  if (/^Applying design system|imagery/.test(line)) return { kind: 'style', label: 'Applying design system, imagery and animation' };
  if (/^Verification found/.test(line)) return { kind: 'warn', label: line.replace(/\.\.\.$/, '') };
  if (/^Verifying/.test(line)) return { kind: 'verify', label: 'Verifying with the real bundler + render smoke test' };
  if (/^Fixing\s+(.+?)\s*\((.+?)\s+reported/.test(line)) {
    const m = line.match(/^Fixing\s+(.+?)\s*\((.+?)\s+reported/)!;
    return { kind: 'repair', label: `Repairing ${m[1].split('/').pop()}`, detail: `${m[2]} error` };
  }
  if (/came back empty|degenerate stop/.test(line)) {
    const p = line.match(/^(.+?) came back empty/);
    return { kind: 'retry', label: `Retrying ${p ? p[1].split('/').pop() : 'file'} (empty response)` };
  }
  if (/hit the token cap/.test(line)) {
    const p = line.match(/^(.+?) hit the token cap/);
    return { kind: 'retry', label: `Re-requesting ${p ? p[1].split('/').pop() : 'file'} compactly` };
  }
  if (/^Recreating/.test(line)) {
    const p = line.match(/^Recreating\s+(.+?)\s*\(/);
    return { kind: 'retry', label: `Recreating ${p ? p[1].split('/').pop() : 'file'}` };
  }
  if (/^Production bundle verified/.test(line)) return { kind: 'done', label: 'Production bundle verified' };
  if (/still failing/.test(line)) return { kind: 'warn', label: line.replace(/\.\.\.$/, '') };
  return { kind: 'info', label: line.replace(/\.\.\.$/, '') };
}

export function AgentSteps({ lines, running, compact }: AgentStepsProps) {
  const endRef = useRef<HTMLDivElement>(null);
  const steps = useMemo(() => lines.filter(Boolean).map(classify), [lines]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [steps.length]);

  const fileProgress = useMemo(() => {
    const writes = steps.filter(s => s.kind === 'write');
    const last = writes[writes.length - 1];
    return last?.progress ?? null;
  }, [steps]);

  if (steps.length === 0) return null;

  if (compact) {
    const last = steps[steps.length - 1];
    return (
      <div className="flex items-center gap-2 text-[11px] text-gray-500">
        {running ? <Loader2 className="w-3 h-3 animate-spin text-violet-400" /> : <CheckCircle2 className="w-3 h-3 text-green-500" />}
        <span className="truncate">{last.label}</span>
      </div>
    );
  }

  return (
    <div className="bg-white/[0.02] border border-violet-500/20 rounded-xl overflow-hidden animate-slide-up">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-white/[0.05] bg-violet-500/[0.06]">
        {running
          ? <Loader2 className="w-3.5 h-3.5 text-violet-400 animate-spin" />
          : <CheckCircle2 className="w-3.5 h-3.5 text-green-500" />}
        <span className="text-xs font-medium text-violet-200">
          {running ? 'Building your app' : 'Build complete'}
        </span>
        {fileProgress && (
          <span className="ml-auto text-[10px] text-gray-500 tabular-nums">
            {fileProgress[0]}/{fileProgress[1]} files
          </span>
        )}
      </div>

      {running && (
        <div className="shimmer-track h-0.5 bg-white/5" />
      )}

      <div className="px-3 py-2 max-h-56 overflow-y-auto space-y-0.5">
        {steps.map((s, i) => {
          const isLast = i === steps.length - 1;
          const active = running && isLast;
          return (
            <div key={i} className="flex items-start gap-2 py-0.5 group">
              <span className={`mt-0.5 flex-shrink-0 ${active ? 'text-violet-300' : TONE[s.kind]}`}>
                {active ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : ICONS[s.kind]}
              </span>
              <div className="min-w-0 flex-1">
                <p className={`text-[11.5px] leading-snug truncate ${active ? 'text-gray-200' : 'text-gray-400'}`}>
                  {s.label}
                </p>
                {s.detail && (
                  <p className="text-[10px] text-gray-600 truncate">{s.detail}</p>
                )}
              </div>
            </div>
          );
        })}
        <div ref={endRef} />
      </div>
    </div>
  );
}
