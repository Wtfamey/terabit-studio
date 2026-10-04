import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { Mail, Lock, UserPlus, AlertCircle, Eye, EyeOff, Loader2, Check } from 'lucide-react';
import { AuthLayout, Notice } from '../components/AuthLayout';
import { ui } from '../theme';

export function Register() {
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
        state: prompt ? { prompt, template: template || null, features, assets: savedAssets, brand: savedBrand } : undefined,
      });
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Registration failed');
    } finally {
      setLoading(false);
    }
  };

  const carry = `&prompt=${encodeURIComponent(prompt)}&template=${encodeURIComponent(template)}&features=${encodeURIComponent(features)}` +
    `${assetsParam ? `&assets=${encodeURIComponent(assetsParam)}` : ''}` +
    `${brandParam ? `&brand=${encodeURIComponent(brandParam)}` : ''}`;

  const rules = [
    { ok: password.length >= 6, text: 'At least 6 characters' },
    { ok: confirm.length > 0 && confirm === password, text: 'Passwords match' },
  ];

  return (
    <AuthLayout
      title="Create your account"
      subtitle="Start building with Terabit Studio in seconds."
      notice={
        prompt ? (
          <Notice>
            <span className="font-medium">Your prompt is saved</span> — “{prompt.slice(0, 64)}
            {prompt.length > 64 ? '…' : ''}”
          </Notice>
        ) : undefined
      }
      footer={
        <p className="text-sm text-slate-500">
          Already have an account?{' '}
          <Link
            to={`/login?redirect=${encodeURIComponent(redirect)}${carry}`}
            className="font-medium text-brand-300 hover:text-brand-200 transition-colors"
          >
            Sign in
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
              id="email" type="email" value={email} onChange={e => setEmail(e.target.value)}
              placeholder="you@example.com" autoComplete="email"
              className={`${ui.input} pl-10`} required
            />
          </div>
        </div>

        <div>
          <label htmlFor="password" className={ui.label}>Password</label>
          <div className="relative mt-1.5 group">
            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 transition-colors group-focus-within:text-brand-300" />
            <input
              id="password" type={showPassword ? 'text' : 'password'} value={password}
              onChange={e => setPassword(e.target.value)} placeholder="At least 6 characters"
              autoComplete="new-password" className={`${ui.input} pl-10 pr-10`} required minLength={6}
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

        <div>
          <label htmlFor="confirm" className={ui.label}>Confirm password</label>
          <div className="relative mt-1.5 group">
            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 transition-colors group-focus-within:text-brand-300" />
            <input
              id="confirm" type="password" value={confirm} onChange={e => setConfirm(e.target.value)}
              placeholder="Repeat password" autoComplete="new-password"
              className={`${ui.input} pl-10`} required
            />
          </div>
        </div>

        {/* live rule checklist */}
        <ul className="space-y-1.5 pt-0.5">
          {rules.map(r => (
            <li key={r.text} className="flex items-center gap-2 text-[11px]">
              <span className={`w-3.5 h-3.5 rounded-full flex items-center justify-center transition-all duration-300 ${
                r.ok ? 'bg-emerald-400/20 text-emerald-300' : 'bg-white/[0.05] text-slate-600'
              }`}>
                <Check className="w-2.5 h-2.5" />
              </span>
              <span className={r.ok ? 'text-emerald-300/90' : 'text-slate-600'}>{r.text}</span>
            </li>
          ))}
        </ul>

        <button type="submit" disabled={loading} className={`${ui.btnPrimary} w-full py-3 text-sm`}>
          {loading ? (
            <><Loader2 className="w-4 h-4 animate-spin" /> Creating account…</>
          ) : (
            <><UserPlus className="w-4 h-4" /> Create account</>
          )}
        </button>
      </form>
    </AuthLayout>
  );
}
