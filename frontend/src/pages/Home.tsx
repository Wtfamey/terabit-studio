import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { AssetManager } from '../components/AssetManager';
import { Aurora, LogoMark, Wordmark } from '../components/Brand';
import { ui, lift } from '../theme';
import {
  Sparkles, Globe, BarChart3, Users, ShoppingCart, Receipt, Briefcase,
  ArrowRight, Code2, Shield, Zap, UserCircle, Image, GraduationCap,
  Stethoscope, Package, IdCard, Wand2, Layers, CheckCircle2, Loader2,
} from 'lucide-react';
import { BUSINESS_TEMPLATES, BrandProfile, BusinessType, UserAsset } from '../types';

const TEMPLATE_ICONS: Record<string, React.ReactNode> = {
  Globe: <Globe className="w-5 h-5" />,
  BarChart3: <BarChart3 className="w-5 h-5" />,
  Users: <Users className="w-5 h-5" />,
  ShoppingCart: <ShoppingCart className="w-5 h-5" />,
  Receipt: <Receipt className="w-5 h-5" />,
  Briefcase: <Briefcase className="w-5 h-5" />,
  Stethoscope: <Stethoscope className="w-5 h-5" />,
  Package: <Package className="w-5 h-5" />,
  IdCard: <IdCard className="w-5 h-5" />,
};

const ROTATING = [
  'a law firm site',
  'a restaurant menu page',
  'a hospital management system',
  'an employee management system',
  'your product\u2019s landing page',
  'a store management system',
];

const STEPS = [
  {
    icon: <Wand2 className="w-5 h-5" />,
    title: 'Describe it',
    body: 'One prompt. Tag files with @, attach your own images and brand colours.',
  },
  {
    icon: <Layers className="w-5 h-5" />,
    title: 'Watch it plan',
    body: 'The agent plans the file structure, then writes each section and streams every step.',
  },
  {
    icon: <CheckCircle2 className="w-5 h-5" />,
    title: 'Verified, not just generated',
    body: 'Model output is bundled with a real compiler and render-tested before you see the preview.',
  },
];

export function Home() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [prompt, setPrompt] = useState('');
  const [selectedTemplate, setSelectedTemplate] = useState<string | null>(null);
  const [customFeatures, setCustomFeatures] = useState('');
  const [uploadedAssets, setUploadedAssets] = useState<UserAsset[]>([]);
  const [showAssets, setShowAssets] = useState(false);
  const [showBrand, setShowBrand] = useState(false);
  const [brand, setBrand] = useState<BrandProfile>({ name: '', website: '', primary_color: '#7c5cff', logo_url: '' });
  const [rotIdx, setRotIdx] = useState(0);

  // rotate the "build ___" placeholder so the hero feels alive
  useEffect(() => {
    const id = setInterval(() => setRotIdx(i => (i + 1) % ROTATING.length), 2600);
    return () => clearInterval(id);
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim()) return;
    const state = {
      prompt: prompt.trim(),
      template: selectedTemplate,
      features: customFeatures,
      brand,
      assets: uploadedAssets.map(a => ({
        url: a.url,
        filename: a.filename,
        original_name: a.original_name,
        mime_type: a.mime_type,
      })),
    };
    if (!user) {
      const params = new URLSearchParams({
        redirect: '/builder',
        prompt: prompt.trim(),
        template: selectedTemplate || '',
        features: customFeatures,
        brand: JSON.stringify(brand),
        assets: JSON.stringify(state.assets),
      });
      navigate(`/login?${params.toString()}`);
      return;
    }
    navigate('/builder', { state });
  };

  const handleTemplateClick = (t: BusinessType) => {
    setSelectedTemplate(prev => (prev === t.id ? null : t.id));
    if (!prompt) {
      setPrompt(`Build me a ${t.name.toLowerCase()} with ${t.features.slice(0, 3).join(', ')}`);
    }
  };

  return (
    <div className="relative min-h-screen overflow-x-hidden" style={{ background: '#07070d' }}>
      <Aurora />

      {/* ─── nav ─── */}
      <header className="relative z-20 sticky top-0 border-b border-white/[0.05] bg-[#07070d]/70 backdrop-blur-xl">
        <div className="max-w-6xl mx-auto px-5 sm:px-6 h-16 flex items-center justify-between">
          <button onClick={() => navigate('/')} className="transition-transform duration-300 hover:scale-[1.02]">
            <Wordmark size="md" />
          </button>

          <div className="hidden md:flex items-center gap-7 text-[13px] text-slate-400">
            <a href="#how" className="hover:text-slate-100 transition-colors">How it works</a>
            <a href="#templates" className="hover:text-slate-100 transition-colors">Templates</a>
            <a href="#start" className="hover:text-slate-100 transition-colors">Start building</a>
          </div>

          {user ? (
            <div className="flex items-center gap-2">
              <button onClick={() => navigate('/finetune')} className={`${ui.btnGhost} px-3 py-2 text-xs`}>
                <GraduationCap className="w-3.5 h-3.5" /> Fine-tune
              </button>
              <button onClick={() => navigate('/builder')} className={`${ui.btnPrimary} px-4 py-2 text-xs`}>
                Open studio <ArrowRight className="w-3.5 h-3.5" />
              </button>
              <div className="hidden sm:flex items-center gap-2 pl-3 ml-1 border-l border-white/[0.08] text-xs text-slate-500">
                <UserCircle className="w-4 h-4" />
                <span className="max-w-[110px] truncate">{user.email}</span>
              </div>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <button onClick={() => navigate('/login')} className={`${ui.btnGhost} px-4 py-2 text-xs`}>
                Sign in
              </button>
              <button onClick={() => navigate('/register')} className={`${ui.btnPrimary} px-4 py-2 text-xs`}>
                Get started <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>
          )}
        </div>
      </header>

      <main className="relative z-10">
        {/* ─── hero ─── */}
        <section id="start" className="max-w-5xl mx-auto px-5 sm:px-6 pt-16 sm:pt-24 pb-10 text-center">
          <div className="inline-flex items-center gap-2 rounded-full border border-white/[0.09] bg-white/[0.035] px-3.5 py-1.5 text-[11px] text-slate-400 mb-7 animate-slide-up">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse-dot" />
            Running locally · <span className="text-slate-300">Qwen 2.5 7B fine-tune</span>
          </div>

          <h1 className="text-[2.6rem] sm:text-6xl lg:text-7xl font-black tracking-[-0.03em] leading-[1.04] mb-5 animate-slide-up">
            <span className="text-slate-100">Build</span>{' '}
            <span key={rotIdx} className="text-gradient-animated inline-block">{ROTATING[rotIdx]}</span>
            <span className="caret" />
          </h1>

          <p className="text-base sm:text-lg text-slate-400 max-w-2xl mx-auto leading-relaxed mb-9 animate-slide-up">
            Describe the site or system you want. A local model plans the files, writes every
            section, then bundles and render-tests the result before showing you a live preview.
          </p>

          {/* ─── prompt box ─── */}
          <form onSubmit={handleSubmit} className="max-w-3xl mx-auto text-left">
            <div
              className={`${ui.panel} prompt-glow p-2.5 sm:p-3 transition-all duration-300 focus-within:border-violet-400/40`}
            >
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey || !e.shiftKey)) {
                    e.preventDefault();
                    handleSubmit(e as unknown as React.FormEvent);
                  }
                }}
                rows={2}
                placeholder={`Describe it… e.g. "A website for Hartwell & Sawyer, a boutique law firm, with practice areas, fees, attorneys and client outcomes"`}
                className="w-full resize-none bg-transparent px-3 pt-2.5 pb-1 text-[15px] leading-relaxed text-slate-100 placeholder-slate-500 outline-none max-h-44"
              />

              <div className="flex items-center gap-2 flex-wrap px-1.5 pb-1">
                <span className="text-[11px] text-slate-500 mr-1">Templates</span>
                {BUSINESS_TEMPLATES.slice(0, 4).map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => handleTemplateClick(t)}
                    className={`px-2.5 py-1 rounded-lg text-[11px] font-medium border transition-all duration-200 active:scale-[0.97] ${
                      selectedTemplate === t.id
                        ? 'border-violet-400/50 bg-violet-500/15 text-violet-200'
                        : 'border-white/[0.09] text-slate-500 hover:border-white/[0.18] hover:text-slate-300'
                    }`}
                  >
                    {t.name}
                  </button>
                ))}

                <div className="flex-1" />

                <button
                  type="submit"
                  disabled={!prompt.trim()}
                  className={`${ui.btnPrimary} px-5 py-2.5 text-sm`}
                >
                  Generate <ArrowRight className="w-4 h-4" />
                </button>
              </div>
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 px-1 text-[11px]">
              <button
                type="button"
                onClick={() => setShowBrand(v => !v)}
                className={`inline-flex items-center gap-1.5 transition-colors ${showBrand ? 'text-brand-300' : 'text-slate-500 hover:text-slate-300'}`}
              >
                <Sparkles className="w-3.5 h-3.5" /> {showBrand ? 'Hide brand setup' : 'Personalize your brand'}
              </button>
              <button
                type="button"
                onClick={() => setShowAssets(v => !v)}
                className={`inline-flex items-center gap-1.5 transition-colors ${showAssets ? 'text-brand-300' : 'text-slate-500 hover:text-slate-300'}`}
              >
                <Image className="w-3.5 h-3.5" /> {showAssets ? 'Hide assets' : 'Add your own images'}
                {uploadedAssets.length > 0 && (
                  <span className="ml-0.5 rounded-full bg-violet-500/15 px-1.5 py-0.5 text-[10px] text-violet-300">
                    {uploadedAssets.length}
                  </span>
                )}
              </button>
              <span className="ml-auto hidden sm:flex items-center gap-1.5 text-slate-600">
                <Zap className="w-3.5 h-3.5" /> Local & private
                <span className="text-slate-700">·</span>
                <Code2 className="w-3.5 h-3.5" /> React + Tailwind
                <span className="text-slate-700">·</span>
                <Shield className="w-3.5 h-3.5" /> Bundle-verified
              </span>
            </div>

            {/* ─── brand panel ─── */}
            {showBrand && (
              <div className={`${ui.panel} mt-4 p-4 animate-slide-up`}>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <input
                    value={brand.name}
                    onChange={e => setBrand(b => ({ ...b, name: e.target.value }))}
                    placeholder="Brand or product name"
                    className={ui.input}
                  />
                  <input
                    value={brand.website}
                    onChange={e => setBrand(b => ({ ...b, website: e.target.value }))}
                    placeholder="Your website (optional)"
                    className={ui.input}
                  />
                  <label className={`${ui.input} flex items-center gap-3 cursor-pointer`}>
                    <span className="text-slate-400">Primary colour</span>
                    <input
                      type="color"
                      value={brand.primary_color}
                      onChange={e => setBrand(b => ({ ...b, primary_color: e.target.value }))}
                      className="ml-auto h-6 w-9 rounded bg-transparent cursor-pointer"
                    />
                  </label>
                  <select
                    value={brand.logo_url}
                    onChange={e => setBrand(b => ({ ...b, logo_url: e.target.value }))}
                    className={`${ui.input} cursor-pointer`}
                  >
                    <option value="" className="bg-ink-900">Choose an uploaded logo (optional)</option>
                    {uploadedAssets.filter(a => a.mime_type.startsWith('image/')).map(a => (
                      <option key={a.id} value={a.url} className="bg-ink-900">{a.original_name}</option>
                    ))}
                  </select>
                </div>
                <p className="mt-3 text-[11px] text-slate-600">
                  The model applies this profile to colours, logo, labels and links in the generated app.
                </p>
              </div>
            )}

            {/* ─── assets panel ─── */}
            {showAssets && (
              <div className={`${ui.panel} mt-4 p-4 animate-slide-up`}>
                <AssetManager onAssetsChange={setUploadedAssets} />
              </div>
            )}

            {selectedTemplate && (
              <div className="mt-4 animate-slide-up">
                <textarea
                  value={customFeatures}
                  onChange={(e) => setCustomFeatures(e.target.value)}
                  placeholder="Any specific features or pages you want?"
                  className={`${ui.input} h-20 resize-none`}
                />
              </div>
            )}
          </form>
        </section>

        {/* ─── how it works ─── */}
        <section id="how" className="max-w-5xl mx-auto px-5 sm:px-6 py-16">
          <div className="text-center mb-10">
            <h2 className="text-2xl sm:text-3xl font-bold text-slate-100 tracking-tight mb-2">
              Not a wrapper around a chat box
            </h2>
            <p className="text-sm text-slate-500 max-w-xl mx-auto">
              Three stages run on every generation, and a failed one never reaches your preview.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 stagger">
            {STEPS.map((s, i) => (
              <div key={s.title} className={`${ui.panel} ${lift} card-glow p-5`}>
                <div className="flex items-center gap-3 mb-3">
                  <span className="w-9 h-9 rounded-xl flex items-center justify-center text-brand-300 bg-violet-500/12 border border-violet-400/20">
                    {s.icon}
                  </span>
                  <span className="text-[10px] font-mono text-slate-600">0{i + 1}</span>
                </div>
                <h3 className="text-sm font-semibold text-slate-100 mb-1">{s.title}</h3>
                <p className="text-[13px] text-slate-500 leading-relaxed">{s.body}</p>
              </div>
            ))}
          </div>
        </section>

        {/* ─── template grid ─── */}
        <section id="templates" className="max-w-5xl mx-auto px-5 sm:px-6 pb-16">
          <div className="text-center mb-10">
            <h2 className="text-2xl sm:text-3xl font-bold text-slate-100 tracking-tight mb-2">
              Start from a shape
            </h2>
            <p className="text-sm text-slate-500">
              Pick one to seed the prompt — or write your own description above.
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 stagger">
            {BUSINESS_TEMPLATES.map((t) => {
              const active = selectedTemplate === t.id;
              return (
                <button
                  key={t.id}
                  onClick={() => handleTemplateClick(t)}
                  className={`${ui.panel} ${lift} card-glow group relative text-left p-5 ${
                    active ? '!border-violet-400/45 !bg-violet-500/[0.07]' : ''
                  }`}
                >
                  <div className="flex items-start justify-between mb-3">
                    <span className={`w-10 h-10 rounded-xl flex items-center justify-center border transition-all duration-300 ${
                      active
                        ? 'bg-violet-500/20 border-violet-400/40 text-violet-200'
                        : 'bg-white/[0.04] border-white/[0.07] text-slate-400 group-hover:text-brand-300 group-hover:border-violet-400/25'
                    }`}>
                      {TEMPLATE_ICONS[t.icon] || <Briefcase className="w-5 h-5" />}
                    </span>
                    <ArrowRight className={`w-4 h-4 transition-all duration-300 ${
                      active ? 'text-violet-300' : 'text-slate-700 group-hover:text-slate-400 group-hover:translate-x-0.5'
                    }`} />
                  </div>
                  <h3 className="text-sm font-semibold text-slate-100 mb-1">{t.name}</h3>
                  <p className="text-xs text-slate-500 mb-3">{t.description}</p>
                  <div className="flex flex-wrap gap-1.5">
                    {t.features.slice(0, 3).map(f => (
                      <span key={f} className="rounded-md bg-white/[0.035] border border-white/[0.06] px-1.5 py-0.5 text-[10px] text-slate-500">
                        {f}
                      </span>
                    ))}
                  </div>
                </button>
              );
            })}
          </div>
        </section>

        {/* ─── closing CTA ─── */}
        <section className="max-w-4xl mx-auto px-5 sm:px-6 pb-20">
          <div className="relative overflow-hidden rounded-3xl border border-white/[0.08] bg-white/[0.025] backdrop-blur-xl p-9 sm:p-12 text-center card-glow">
            <div className="absolute -top-24 left-1/2 -translate-x-1/2 w-[420px] h-[420px] rounded-full blur-[110px]"
                 style={{ background: 'radial-gradient(circle, rgba(124,92,255,0.35), transparent 70%)' }} />
            <div className="relative">
              <LogoMark size={44} className="mx-auto mb-5 animate-float-slow drop-shadow-[0_10px_30px_rgba(124,92,255,0.5)]" />
              <h2 className="text-2xl sm:text-3xl font-bold tracking-tight text-slate-100 mb-2">
                Your idea is one prompt away
              </h2>
              <p className="text-sm text-slate-500 mb-7 max-w-md mx-auto">
                No API keys, no per-token bill, nothing uploaded. Just a model on your machine.
              </p>
              <div className="flex flex-wrap items-center justify-center gap-3">
                <button
                  onClick={() => { window.scrollTo({ top: 0, behavior: 'smooth' }); }}
                  className={`${ui.btnPrimary} px-6 py-3 text-sm`}
                >
                  {user ? 'Start building' : 'Try a prompt'} <ArrowRight className="w-4 h-4" />
                </button>
                {!user && (
                  <button onClick={() => navigate('/register')} className={`${ui.btnGhost} px-6 py-3 text-sm`}>
                    Create free account
                  </button>
                )}
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="relative z-10 border-t border-white/[0.05]">
        <div className="max-w-6xl mx-auto px-5 sm:px-6 py-7 flex flex-wrap items-center justify-between gap-3 text-[11px] text-slate-600">
          <div className="flex items-center gap-2.5">
            <LogoMark size={18} />
            <span>Terabit Studio — local-first AI app builder</span>
          </div>
          <div className="flex items-center gap-4">
            <span className="flex items-center gap-1.5">
              <Loader2 className="w-3 h-3 animate-spin text-violet-400/70" />
              Qwen 2.5 7B fine-tune
            </span>
            <span>llama.cpp · React · Tailwind</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
