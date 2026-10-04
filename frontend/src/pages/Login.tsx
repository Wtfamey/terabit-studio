import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { Mail, Lock, LogIn, AlertCircle, Eye, EyeOff, Loader2 } from 'lucide-react';
import { AuthLayout, Notice } from '../components/AuthLayout';
import { ui } from '../theme';

export function Login() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const redirect = searchParams.get('redirect') || '/';
  const prompt = searchParams.get('prompt') || '';
  const template = searchParams.get('template') || '';
  const features = searchParams.get('features') || '';
  const assetsParam = searchParams.get('assets') || '';
  const brandParam = searchParams.get('brand') || '';
  const savedAssets = assetsParam ? (() => { try { return JSON.parse(assetsParam); } catch { return null; } })() : null;
  const savedBrand = brandParam ? (() => { try { return JSON.parse(brandParam); } catch { return undefined; } })() : undefined;

  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(email, password);
      navigate(redirect, {
        state: prompt ? { prompt, template: template || null, features, assets: savedAssets, brand: savedBrand } : undefined,
      });
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Invalid email or password');
    } finally {
      setLoading(false);
    }
  };

  const carry = `&prompt=${encodeURIComponent(prompt)}&template=${encodeURIComponent(template)}&features=${encodeURIComponent(features)}` +
    `${assetsParam ? `&assets=${encodeURIComponent(assetsParam)}` : ''}` +
    `${brandParam ? `&brand=${encodeURIComponent(brandParam)}` : ''}`;

  return (
    <AuthLayout
      title="Welcome back"
      subtitle="Sign in to continue building with Terabit Studio."
      notice={
        <>
          {prompt && (
            <Notice>
              <span className="font-medium">Prompt saved</span> — “{prompt.slice(0, 64)}
              {prompt.length > 64 ? '…' : ''}”
            </Notice>
          )}
          {savedAssets && savedAssets.length > 0 && (
            <Notice tone="success">
              {savedAssets.length} asset{savedAssets.length !== 1 ? 's' : ''} attached to this build
            </Notice>
          )}
        </>
      }
      footer={
        <p className="text-sm text-slate-500">
          No account?{' '}
          <Link
            to={`/register?redirect=${encodeURIComponent(redirect)}${carry}`}
            className="font-medium text-brand-300 hover:text-brand-200 transition-colors"
          >
            Create one
          </Link>
        </p>
      }
    >
      {error && (
        <div className="flex items-center gap-2 mb-4 rounded-xl border border-red-500/25 bg-red-500/10 px-3 py-2.5 text-sm text-red-300 animate-slide-up">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="email" className={ui.label}>Email</label>
          <div className="relative mt-1.5 group">
            <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 transition-colors group-focus-within:text-brand-300" />
            <input
              id="email"
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="you@example.com"
              autoComplete="email"
              className={`${ui.input} pl-10`}
              required
            />
          </div>
        </div>

        <div>
          <label htmlFor="password" className={ui.label}>Password</label>
          <div className="relative mt-1.5 group">
            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 transition-colors group-focus-within:text-brand-300" />
            <input
              id="password"
              type={showPassword ? 'text' : 'password'}
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete="current-password"
              className={`${ui.input} pl-10 pr-10`}
              required
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              aria-label={showPassword ? 'Hide password' : 'Show password'}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition-colors"
            >
              {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>
        </div>

        <button type="submit" disabled={loading} className={`${ui.btnPrimary} w-full py-3 text-sm`}>
          {loading ? (
            <><Loader2 className="w-4 h-4 animate-spin" /> Signing in…</>
          ) : (
            <><LogIn className="w-4 h-4" /> Sign in</>
          )}
        </button>
      </form>
    </AuthLayout>
  );
}
