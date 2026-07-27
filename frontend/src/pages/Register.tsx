import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { Cpu, Mail, Lock, UserPlus, AlertCircle, Eye, EyeOff } from 'lucide-react';

export function Register() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const redirect = searchParams.get('redirect') || '/';
  const prompt = searchParams.get('prompt') || '';
  const template = searchParams.get('template') || '';
  const features = searchParams.get('features') || '';
  const assetsParam = searchParams.get('assets') || '';
  const savedAssets = assetsParam ? (() => { try { return JSON.parse(assetsParam); } catch { return null; } })() : null;

  const { register } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (password !== confirm) { setError('Passwords do not match'); return; }
    if (password.length < 6) { setError('Password must be at least 6 characters'); return; }
    setLoading(true);
    try {
      await register(email, password);
      navigate(redirect, {
        state: prompt ? { prompt, template: template || null, features, assets: savedAssets } : undefined,
      });
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Registration failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#030712] flex items-center justify-center p-6">
      <div className="fixed inset-0 pointer-events-none">
        <div className="absolute top-[-10%] left-[-5%] w-[500px] h-[500px] bg-violet-600/15 rounded-full blur-[120px]" />
        <div className="absolute bottom-[-10%] right-[-5%] w-[400px] h-[400px] bg-cyan-500/15 rounded-full blur-[100px]" />
      </div>
      <div className="relative w-full max-w-md">
        <div className="bg-white/[0.03] border border-white/[0.08] rounded-2xl p-8 backdrop-blur-xl shadow-2xl shadow-black/50">
          <div className="text-center mb-8">
            <div className="p-3 bg-gradient-to-br from-violet-600 via-fuchsia-500 to-cyan-500 rounded-xl inline-block mb-4 shadow-lg shadow-violet-500/20">
              <Cpu className="w-7 h-7 text-white" />
            </div>
            <h1 className="text-2xl font-bold text-gray-100">Create your account</h1>
            <p className="text-sm text-gray-500 mt-1">Start building with TerabitStudio</p>
            {prompt && (
              <p className="text-xs text-violet-400 mt-2 bg-violet-500/10 rounded-lg px-3 py-1.5 truncate max-w-full">
                Your prompt is saved: "{prompt.slice(0, 60)}..."
              </p>
            )}
          </div>

          {error && (
            <div className="flex items-center gap-2 p-3 mb-4 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm">
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1.5">Email</label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-600" />
                <input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@example.com" className="w-full bg-white/5 border border-white/10 rounded-xl pl-10 pr-4 py-3 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-violet-500/50" required />
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1.5">Password</label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-600" />
                <input type={showPassword ? 'text' : 'password'} value={password} onChange={e => setPassword(e.target.value)} placeholder="At least 6 characters" className="w-full bg-white/5 border border-white/10 rounded-xl pl-10 pr-10 py-3 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-violet-500/50" required minLength={6} />
                <button type="button" onClick={() => setShowPassword(!showPassword)} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-600 hover:text-gray-400">
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1.5">Confirm password</label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-600" />
                <input type="password" value={confirm} onChange={e => setConfirm(e.target.value)} placeholder="Repeat password" className="w-full bg-white/5 border border-white/10 rounded-xl pl-10 pr-4 py-3 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-violet-500/50" required />
              </div>
            </div>
            <button type="submit" disabled={loading} className="w-full py-3 bg-gradient-to-r from-violet-600 via-fuchsia-600 to-cyan-600 rounded-xl font-semibold text-white hover:shadow-xl hover:shadow-violet-500/20 transition-all flex items-center justify-center gap-2 disabled:opacity-50">
              {loading ? 'Creating account...' : <><UserPlus className="w-4 h-4" /> Create Account</>}
            </button>
          </form>

          <p className="text-center text-sm text-gray-600 mt-6">
            Already have an account?{' '}
            <Link to={`/login?redirect=${encodeURIComponent(redirect)}&prompt=${encodeURIComponent(prompt)}&template=${encodeURIComponent(template)}&features=${encodeURIComponent(features)}${assetsParam ? `&assets=${encodeURIComponent(assetsParam)}` : ''}`} className="text-violet-400 hover:text-violet-300 font-medium">Sign in</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
