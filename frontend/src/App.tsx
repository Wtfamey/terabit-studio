import { useEffect } from 'react';
import { Routes, Route, useLocation } from 'react-router-dom';
import { AuthProvider } from './contexts/AuthContext';
import { ErrorBoundary } from './components/ErrorBoundary';
import { Home } from './pages/Home';
import { Builder } from './pages/Builder';
import { Workspace } from './pages/Workspace';
import { Login } from './pages/Login';
import { Register } from './pages/Register';
import { FineTune } from './pages/FineTune';
import { Settings } from './pages/Settings';

const TITLES: Record<string, string> = {
  '/': 'Terabit Studio — local-first AI website & app builder',
  '/builder': 'Builder — Terabit Studio',
  '/workspace': 'Workspace — Terabit Studio',
  '/finetune': 'Fine-tune — Terabit Studio',
  '/settings': 'Settings — Terabit Studio',
  '/login': 'Sign in — Terabit Studio',
  '/register': 'Create account — Terabit Studio',
};

/** One title per screen: a desktop window and its taskbar entry are how users
 *  find the app again, and a single static title loses that. */
function DocumentTitle() {
  const { pathname } = useLocation();
  useEffect(() => {
    document.title = TITLES[pathname] || 'Terabit Studio';
  }, [pathname]);
  return null;
}

/** Scroll the window to top on navigation: with two long pages open, landing
 *  half-way down a new route reads as a broken link. */
function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'auto' });
  }, [pathname]);
  return null;
}

function App() {
  return (
    <ErrorBoundary>
      <AuthProvider>
        <DocumentTitle />
        <ScrollToTop />
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-lg focus:bg-violet-600 focus:px-4 focus:py-2 focus:text-sm focus:text-white"
        >
          Skip to content
        </a>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/builder" element={<Builder />} />
          <Route path="/workspace" element={<Workspace />} />
          <Route path="/finetune" element={<FineTune />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="*" element={<Home />} />
        </Routes>
      </AuthProvider>
    </ErrorBoundary>
  );
}

export default App;
