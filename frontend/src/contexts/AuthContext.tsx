import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';
import axios from 'axios';
import { ENDPOINTS } from '../config';

interface User {
  id: number;
  email: string;
}

interface AuthContextType {
  user: User | null;
  token: string | null;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
  loading: boolean;
}

const AuthContext = createContext<AuthContextType>(null!);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(() => {
    // Dev/evidence helper: ?token=<jwt> bootstraps an authenticated session
    // (used by headless-Chrome screenshot capture). The param is stripped
    // from the URL immediately so it never persists in history or logs.
    const url = new URL(window.location.href);
    const t = url.searchParams.get('token');
    if (t) {
      localStorage.setItem('token', t);
      url.searchParams.delete('token');
      window.history.replaceState({}, '', url.pathname + url.search);
      return t;
    }
    return localStorage.getItem('token');
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (token) {
      axios.defaults.headers.common['Authorization'] = `Bearer ${token}`;
      axios.get(ENDPOINTS.me).then(r => {
        setUser(r.data);
      }).catch((err) => {
        // Only a real auth rejection invalidates the session. A backend
        // restart or transient 5xx must NOT silently log the user out
        // (as-user finding: one busy-backend blip wiped the session and
        // bounced Generate -> /login).
        if (err?.response?.status === 401) {
          localStorage.removeItem('token');
          setToken(null);
        }
      }).finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, [token]);

  const login = useCallback(async (email: string, password: string) => {
    const res = await axios.post(ENDPOINTS.login, { email, password });
    const { token: t, user: u } = res.data;
    localStorage.setItem('token', t);
    axios.defaults.headers.common['Authorization'] = `Bearer ${t}`;
    setToken(t);
    setUser(u);
  }, []);

  const register = useCallback(async (email: string, password: string) => {
    const res = await axios.post(ENDPOINTS.register, { email, password });
    const { token: t, user: u } = res.data;
    localStorage.setItem('token', t);
    axios.defaults.headers.common['Authorization'] = `Bearer ${t}`;
    setToken(t);
    setUser(u);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem('token');
    delete axios.defaults.headers.common['Authorization'];
    setToken(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, token, login, register, logout, loading }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
