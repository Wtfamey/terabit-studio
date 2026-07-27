import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { AssetManager } from '../components/AssetManager';
import {
  Sparkles, Globe, BarChart3, Users, ShoppingCart, Receipt, Briefcase,
  ArrowRight, Code2, Shield, Zap, Cpu, UserCircle, Image
} from 'lucide-react';
import { BUSINESS_TEMPLATES, BusinessType, UserAsset } from '../types';

const TEMPLATE_ICONS: Record<string, React.ReactNode> = {
  Globe: <Globe className="w-6 h-6" />,
  BarChart3: <BarChart3 className="w-6 h-6" />,
  Users: <Users className="w-6 h-6" />,
  ShoppingCart: <ShoppingCart className="w-6 h-6" />,
  Receipt: <Receipt className="w-6 h-6" />,
  Briefcase: <Briefcase className="w-6 h-6" />,
};

export function Home() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [prompt, setPrompt] = useState('');
  const [selectedTemplate, setSelectedTemplate] = useState<string | null>(null);
  const [customFeatures, setCustomFeatures] = useState('');
  const [uploadedAssets, setUploadedAssets] = useState<UserAsset[]>([]);
  const [showAssets, setShowAssets] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim()) return;
    const state = {
      prompt: prompt.trim(),
      template: selectedTemplate,
      features: customFeatures,
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
        assets: JSON.stringify(state.assets),
      });
      navigate(`/login?${params.toString()}`);
      return;
    }
    navigate('/builder', { state });
  };

  const handleTemplateClick = (t: BusinessType) => {
    setSelectedTemplate(t.id);
    if (!prompt) {
      setPrompt(`Build me a ${t.name.toLowerCase()} with ${t.features.slice(0, 3).join(', ')}`);
    }
  };

  return (
    <div className="min-h-screen bg-[#030712] relative overflow-hidden">
      {/* Ambient glow */}
      <div className="fixed inset-0 pointer-events-none">
        <div className="absolute top-[-15%] left-[-5%] w-[600px] h-[600px] bg-violet-600/15 rounded-full blur-[140px]" />
        <div className="absolute bottom-[-10%] right-[-5%] w-[500px] h-[500px] bg-cyan-500/15 rounded-full blur-[120px]" />
      </div>

      {/* Top bar */}
      <div className="relative z-10 flex items-center justify-between px-6 py-4 max-w-6xl mx-auto">
        <div className="flex items-center gap-2">
          <div className="p-1.5 bg-gradient-to-br from-violet-600 to-cyan-600 rounded-lg">
            <Cpu className="w-4 h-4 text-white" />
          </div>
          <span className="font-bold text-sm text-gray-100">TerabitStudio</span>
        </div>
        {user ? (
          <div className="flex items-center gap-2 text-xs text-gray-400">
            <UserCircle className="w-4 h-4" />
            {user.email}
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <button onClick={() => navigate('/login')} className="px-4 py-2 text-xs font-medium text-gray-400 hover:text-white transition-colors">Sign in</button>
            <button onClick={() => navigate('/register')} className="px-4 py-2 text-xs font-medium bg-violet-500/20 border border-violet-500/30 rounded-lg text-violet-300 hover:bg-violet-500/30 transition-all">
              Sign up free
            </button>
          </div>
        )}
      </div>

      <div className="relative z-10 max-w-6xl mx-auto px-6 py-8">
        <header className="text-center mb-12 pt-8">
          <h1 className="text-5xl md:text-7xl font-black mb-4 tracking-tight leading-tight">
            <span className="bg-gradient-to-r from-violet-400 via-fuchsia-400 to-cyan-400 bg-clip-text text-transparent">
              What will you build today?
            </span>
          </h1>
          <p className="text-lg text-gray-400 max-w-2xl mx-auto">
            Describe your idea and get a complete, production-ready SaaS or website — powered by your local AI.
          </p>
          <div className="flex items-center justify-center gap-6 mt-4 text-xs text-gray-600">
            <span className="flex items-center gap-1.5"><Zap className="w-3.5 h-3.5 text-violet-400" /> Local & Private</span>
            <span className="flex items-center gap-1.5"><Code2 className="w-3.5 h-3.5 text-fuchsia-400" /> React + Tailwind</span>
            <span className="flex items-center gap-1.5"><Shield className="w-3.5 h-3.5 text-cyan-400" /> Qwen 2.5 7B</span>
          </div>
        </header>

        <form onSubmit={handleSubmit} className="max-w-3xl mx-auto mb-12">
          <div className="bg-white/[0.03] border border-white/[0.08] rounded-2xl p-6 backdrop-blur-xl shadow-2xl shadow-black/50">
            <div className="flex gap-3">
              <input
                type="text"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="Describe your app... (e.g., 'Build a real estate CRM with lead tracking and a dashboard')"
                className="flex-1 bg-white/5 border border-white/10 rounded-xl px-5 py-3.5 text-base text-gray-100 placeholder-gray-600 focus:outline-none focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/20"
              />
              <button
                type="submit"
                className="px-6 py-3.5 bg-gradient-to-r from-violet-600 via-fuchsia-600 to-cyan-600 rounded-xl font-semibold text-white hover:shadow-xl hover:shadow-violet-500/25 transition-all flex items-center gap-2 hover:scale-[1.02] active:scale-[0.98] flex-shrink-0"
              >
                Generate <ArrowRight className="w-4 h-4" />
              </button>
            </div>

            <div className="mt-4 flex items-center gap-3">
              <span className="text-xs text-gray-600 font-medium">Templates:</span>
              <div className="flex flex-wrap gap-2">
                {BUSINESS_TEMPLATES.slice(0, 4).map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => handleTemplateClick(t)}
                    className={`px-3 py-1 rounded-lg text-xs font-medium border transition-all ${
                      selectedTemplate === t.id
                        ? 'border-violet-500 bg-violet-500/15 text-violet-300'
                        : 'border-white/10 text-gray-500 hover:border-white/20 hover:text-gray-300'
                    }`}
                  >
                    {t.name}
                  </button>
                ))}
              </div>
            </div>

            {selectedTemplate && (
              <div className="mt-3">
                <textarea
                  value={customFeatures}
                  onChange={(e) => setCustomFeatures(e.target.value)}
                  placeholder="Specific features you want..."
                  className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-violet-500/50 resize-none h-16"
                />
              </div>
            )}
          </div>
        </form>

        {/* ─── Assets ─── */}
        <div className="max-w-3xl mx-auto mb-6">
          <button
            onClick={() => setShowAssets(!showAssets)}
            className="flex items-center gap-2 text-xs text-gray-500 hover:text-gray-300 transition-colors mb-2"
          >
            <Image className="w-3.5 h-3.5" />
            {showAssets ? 'Hide' : 'Add your own images & assets'}
            {uploadedAssets.length > 0 && (
              <span className="text-[10px] text-violet-400 bg-violet-500/10 px-1.5 py-0.5 rounded-full">{uploadedAssets.length}</span>
            )}
          </button>
          {showAssets && (
            <div className="bg-white/[0.03] border border-white/[0.08] rounded-xl p-4 backdrop-blur-xl">
              <AssetManager
                onAssetsChange={setUploadedAssets}
              />
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-12">
          {BUSINESS_TEMPLATES.map((t) => (
            <button
              key={t.id}
              onClick={() => handleTemplateClick(t)}
              className={`text-left p-4 rounded-xl border transition-all group ${
                selectedTemplate === t.id
                  ? 'bg-violet-500/10 border-violet-500/40 shadow-lg shadow-violet-500/10'
                  : 'bg-white/[0.02] border-white/[0.06] hover:bg-white/[0.04] hover:border-white/10'
              }`}
            >
              <div className={`mb-2 transition-colors ${selectedTemplate === t.id ? 'text-violet-400' : 'text-gray-600 group-hover:text-gray-400'}`}>
                {TEMPLATE_ICONS[t.icon] || <Briefcase className="w-5 h-5" />}
              </div>
              <h3 className="font-semibold text-sm text-gray-200 mb-0.5">{t.name}</h3>
              <p className="text-xs text-gray-600">{t.description}</p>
            </button>
          ))}
        </div>

        <footer className="text-center text-gray-700 text-xs pb-6 border-t border-white/[0.03] pt-6">
          Powered by <span className="text-gray-500">Qwen 2.5 7B</span> · Built with llama.cpp · TerabitStudio
        </footer>
      </div>
    </div>
  );
}
