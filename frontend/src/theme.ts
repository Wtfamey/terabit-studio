/**
 * Terabit Studio design tokens.
 *
 * One dark theme, lifted from the Freebuff surface language: near-black
 * canvas with a violet->cyan aurora, glassy translucent panels, hairline
 * borders, and motion on everything interactive. Pages import these strings
 * instead of re-inventing class soup, so the product reads as one app.
 */

export const c = {
  /** page canvas */
  bg: '#07070d',
  /** raised surfaces */
  panel: 'rgba(255,255,255,0.028)',
  panelHover: 'rgba(255,255,255,0.05)',
  /** hairline border */
  line: 'rgba(255,255,255,0.075)',
  lineStrong: 'rgba(255,255,255,0.13)',
} as const;

export const BRAND = {
  name: 'Terabit',
  product: 'TerabitStudio',
  tagline: 'Local-first AI website & app builder',
} as const;

/** Repeated class strings. */
export const ui = {
  /** glass panel */
  panel: 'bg-white/[0.028] border border-white/[0.075] rounded-2xl backdrop-blur-xl',
  panelHover: 'transition-all duration-300 hover:bg-white/[0.05] hover:border-white/[0.13]',
  /** primary gradient button */
  btnPrimary:
    'inline-flex items-center justify-center gap-2 rounded-xl font-semibold text-white ' +
    'bg-[linear-gradient(110deg,#a78bfa_0%,#7c5cff_45%,#22d3ee_100%)] bg-[length:200%_100%] ' +
    'shadow-[0_8px_30px_-10px_rgba(124,92,255,0.7)] ' +
    'transition-all duration-300 hover:bg-[position:100%_0] hover:shadow-[0_12px_40px_-10px_rgba(124,92,255,0.85)] ' +
    'active:scale-[0.975] disabled:opacity-40 disabled:pointer-events-none',
  /** quiet button */
  btnGhost:
    'inline-flex items-center justify-center gap-2 rounded-xl font-medium text-slate-300 ' +
    'bg-white/[0.04] border border-white/[0.09] ' +
    'transition-all duration-200 hover:text-white hover:bg-white/[0.09] hover:border-white/[0.16] ' +
    'active:scale-[0.975]',
  /** text field */
  input:
    'w-full rounded-xl bg-white/[0.04] border border-white/[0.09] px-3.5 py-2.5 text-sm text-slate-100 ' +
    'placeholder-slate-500 outline-none transition-all duration-200 ' +
    'hover:border-white/[0.15] focus:border-violet-400/60 focus:bg-white/[0.06] ' +
    'focus:shadow-[0_0_0_4px_rgba(124,92,255,0.14)]',
  /** gradient headline text */
  textGradient:
    'bg-[linear-gradient(100deg,#c4b5fd_0%,#a78bfa_30%,#67e8f9_75%)] bg-clip-text text-transparent',
  /** muted body copy */
  muted: 'text-slate-400',
  label: 'text-xs font-medium text-slate-400',
} as const;

/** Standard transition sweep used on hover-lift cards. */
export const lift = 'transition-all duration-300 hover:-translate-y-1 hover:shadow-2xl hover:shadow-black/50';
