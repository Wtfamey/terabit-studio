import { Link } from 'react-router-dom';
import { ArrowLeft, ShieldCheck, Zap, Code2 } from 'lucide-react';
import { Aurora, Wordmark } from './Brand';
import { ui } from '../theme';

const PROOF = [
  { icon: <Zap className="w-3.5 h-3.5" />, text: 'Runs entirely on your machine — nothing leaves it' },
  { icon: <Code2 className="w-3.5 h-3.5" />, text: 'React + Tailwind output, verified by a real bundler' },
  { icon: <ShieldCheck className="w-3.5 h-3.5" />, text: 'Every build checked for bundle and render errors' },
];

export function AuthLayout({
  title,
  subtitle,
  notice,
  children,
  footer,
}: {
  title: string;
  subtitle: string;
  notice?: React.ReactNode;
  children: React.ReactNode;
  footer: React.ReactNode;
}) {
  return (
    <div className="relative min-h-screen overflow-hidden" style={{ background: '#07070d' }}>
      <Aurora />

      <div className="relative z-10 min-h-screen grid lg:grid-cols-[1.05fr_1fr]">
        {/* ── left: brand story (desktop only) ── */}
        <div className="hidden lg:flex flex-col justify-between p-10 xl:p-14">
          <div className="flex items-center justify-between">
            <Link to="/" className="transition-transform duration-300 hover:scale-[1.02]">
              <Wordmark size="md" />
            </Link>
            <Link
              to="/"
              className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-200 transition-colors"
            >
              <ArrowLeft className="w-3.5 h-3.5" /> Back
            </Link>
          </div>

          <div className="max-w-lg">
            <h2 className="text-4xl xl:text-5xl font-black tracking-tight leading-[1.08] mb-5">
              <span className="text-gradient-animated">Build real apps</span>
              <br />
              <span className="text-slate-200">with a model you own.</span>
            </h2>
            <p className="text-slate-400 leading-relaxed mb-8">
              Terabit Studio plans the file structure, writes every section, then bundles,
              renders and repairs the result before you ever see it.
            </p>

            <ul className="stagger space-y-3">
              {PROOF.map((p) => (
                <li key={p.text} className="flex items-center gap-3">
                  <span className="flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center text-violet-300 bg-violet-500/12 border border-violet-400/20">
                    {p.icon}
                  </span>
                  <span className="text-sm text-slate-400">{p.text}</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="flex items-center gap-3 text-[11px] text-slate-600">
            <span className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse-dot" />
              Qwen 2.5 7B · local inference
            </span>
          </div>
        </div>

        {/* ── right: the form ── */}
        <div className="flex items-center justify-center p-6 sm:p-10">
          <div className="w-full max-w-md animate-slide-up">
            <div className="lg:hidden flex items-center justify-between mb-8">
              <Link to="/"><Wordmark size="md" /></Link>
              <Link to="/" className="text-xs text-slate-500 hover:text-slate-200">Back</Link>
            </div>

            <div className={`${ui.panel} shadow-panel p-7 sm:p-8`}>
              <div className="mb-6">
                <h1 className="text-2xl font-bold text-slate-100 tracking-tight">{title}</h1>
                <p className="text-sm text-slate-500 mt-1.5">{subtitle}</p>
              </div>

              {notice}

              {children}
            </div>

            <div className="mt-5 text-center">{footer}</div>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Small helper the forms use for saved-prompt / asset banners. */
export function Notice({
  tone = 'brand',
  children,
}: {
  tone?: 'brand' | 'success' | 'error';
  children: React.ReactNode;
}) {
  const tones = {
    brand: 'bg-violet-500/10 border-violet-400/25 text-violet-200',
    success: 'bg-emerald-500/10 border-emerald-400/25 text-emerald-300',
    error: 'bg-red-500/10 border-red-500/25 text-red-300',
  }[tone];
  return (
    <div className={`mb-4 rounded-xl border px-3 py-2 text-xs animate-slide-up ${tones}`}>
      {children}
    </div>
  );
}
