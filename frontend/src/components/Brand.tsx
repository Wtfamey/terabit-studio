/**
 * Terabit brand marks.
 *
 * The mark is a rounded gradient tile holding a white "T" (vertical + cross
 * bar) with a thin orbit ring and a node dot passing behind it -- "tera"
 * (scale) + "bit" (a single unit of data in orbit). Deliberately geometric so
 * it stays legible at 16px in a tab and at 240px in a hero.
 */
import { c, BRAND } from '../theme';

export function LogoMark({ size = 32, className = '' }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      className={className}
      role="img"
      aria-label={`${BRAND.name} logo`}
    >
      <defs>
        <linearGradient id="tb-mark" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#a78bfa" />
          <stop offset="0.5" stopColor="#7c5cff" />
          <stop offset="1" stopColor="#22d3ee" />
        </linearGradient>
        <radialGradient id="tb-sheen" cx="0.3" cy="0.15" r="1">
          <stop offset="0" stopColor="#ffffff" stopOpacity="0.45" />
          <stop offset="1" stopColor="#ffffff" stopOpacity="0" />
        </radialGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="url(#tb-mark)" />
      <rect width="32" height="32" rx="9" fill="url(#tb-sheen)" />
      <ellipse
        cx="16" cy="17.4" rx="9.6" ry="4.1"
        fill="none" stroke="#ffffff" strokeOpacity="0.4" strokeWidth="1.3"
        transform="rotate(-22 16 17.4)"
      />
      <path d="M9.6 11.4h12.8" stroke="#ffffff" strokeWidth="2.7" strokeLinecap="round" />
      <path d="M16 11.4v11.2" stroke="#ffffff" strokeWidth="2.7" strokeLinecap="round" />
      <circle cx="25.2" cy="12.6" r="2.1" fill="#ffffff" />
    </svg>
  );
}

export function Wordmark({
  size = 'md',
  showTag = false,
}: {
  size?: 'sm' | 'md' | 'lg';
  showTag?: boolean;
}) {
  const text = { sm: 'text-sm', md: 'text-base', lg: 'text-xl' }[size];
  const mark = { sm: 22, md: 28, lg: 36 }[size];
  return (
    <span className="inline-flex items-center gap-2.5 select-none">
      <LogoMark size={mark} className="drop-shadow-[0_4px_14px_rgba(124,92,255,0.45)]" />
      <span className="flex flex-col leading-none">
        <span className={`${text} font-bold tracking-tight text-slate-100`}>
          Terabit<span style={{ color: '#a78bfa' }}>Studio</span>
        </span>
        {showTag && (
          <span className="text-[10px] text-slate-500 mt-0.5">{BRAND.tagline}</span>
        )}
      </span>
    </span>
  );
}

/** The ambient aurora used behind hero/auth surfaces. */
export function Aurora({ intensity = 1 }: { intensity?: number }) {
  const o = (v: number) => ({ opacity: Math.min(1, v * intensity) });
  return (
    <div className="pointer-events-none fixed inset-0 overflow-hidden" aria-hidden>
      <div
        className="absolute -top-[22%] -left-[10%] w-[54vw] h-[54vw] max-w-[820px] max-h-[820px] rounded-full blur-[130px] animate-aurora"
        style={{ background: 'radial-gradient(circle, rgba(124,92,255,0.55), transparent 68%)', ...o(0.75) }}
      />
      <div
        className="absolute top-[28%] right-[-14%] w-[44vw] h-[44vw] max-w-[680px] max-h-[680px] rounded-full blur-[140px] animate-aurora-slow"
        style={{ background: 'radial-gradient(circle, rgba(34,211,238,0.42), transparent 68%)', ...o(0.7) }}
      />
      <div
        className="absolute bottom-[-18%] left-[24%] w-[40vw] h-[40vw] max-w-[600px] max-h-[600px] rounded-full blur-[150px] animate-aurora"
        style={{ background: 'radial-gradient(circle, rgba(217,70,239,0.32), transparent 70%)', ...o(0.6) }}
      />
      <div
        className="absolute inset-0"
        style={{
          background:
            `linear-gradient(to bottom, ${c.bg}00, ${c.bg}cc 70%, ${c.bg})`,
        }}
      />
    </div>
  );
}
