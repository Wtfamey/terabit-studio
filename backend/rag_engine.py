import os
import numpy as np
from duckduckgo_search import DDGS


FEW_SHOT_EXAMPLE = """
Example of the exact format I expect. This shows the STYLE and QUALITY level I need — every project should match this polish:

`package.json`
```json
{
  "name": "my-business-app",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": { "dev": "vite", "build": "vite build", "preview": "vite preview" },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^7.0.2",
    "lucide-react": "^0.464.0"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.3.4",
    "autoprefixer": "^10.4.20",
    "postcss": "^8.4.49",
    "tailwindcss": "^3.4.16",
    "vite": "^6.0.1"
  }
}
```

`vite.config.js`
```js
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({ plugins: [react()] });
```

`tailwind.config.js`
```js
export default { content: ['./index.html', './src/**/*.{js,jsx}'], theme: { extend: {} }, plugins: [] };
```

`postcss.config.js`
```js
export default { plugins: { tailwindcss: {}, autoprefixer: {} } };
```

`index.html`
```html
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0"/><title>My App</title></head><body><div id="root"></div><script type="module" src="/src/main.jsx"></script></body></html>
```

`src/main.jsx`
```jsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import './index.css';
ReactDOM.createRoot(document.getElementById('root')).render(<BrowserRouter><App /></BrowserRouter>);
```

`src/index.css`
```css
@tailwind base; @tailwind components; @tailwind utilities;
@keyframes fadeIn { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
@keyframes shimmer { 0% { background-position: -200% 0; } 100% { background-position: 200% 0; } }
@keyframes pulse-dot { 0%, 80%, 100% { transform: scale(0); } 40% { transform: scale(1); } }
@keyframes float { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-8px); } }
.animate-fade-in { animation: fadeIn 0.5s ease-out forwards; }
.animate-shimmer { background: linear-gradient(90deg, transparent, rgba(255,255,255,0.05), transparent); background-size: 200% 100%; animation: shimmer 2s infinite; }
.animate-float { animation: float 3s ease-in-out infinite; }
body { background: #030712; color: #e2e8f0; }
```

`src/App.jsx`
```jsx
import { Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import Home from './pages/Home';
import Dashboard from './pages/Dashboard';
export default function App() {
  return (<Layout><Routes><Route path="/" element={<Home />} /><Route path="/dashboard" element={<Dashboard />} /></Routes></Layout>);
}
```

`src/components/Layout.jsx`
```jsx
import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { LayoutDashboard, Home, Settings, BarChart3, Menu, X, Bell, Search } from 'lucide-react';
export default function Layout({ children }) {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const location = useLocation();
  const navItems = [
    { path: '/', icon: <Home size={20} />, label: 'Home' },
    { path: '/dashboard', icon: <LayoutDashboard size={20} />, label: 'Dashboard' },
    { path: '/analytics', icon: <BarChart3 size={20} />, label: 'Analytics' },
    { path: '/settings', icon: <Settings size={20} />, label: 'Settings' },
  ];
  return (
    <div className="flex h-screen bg-[#030712]">
      <aside className={`${sidebarOpen ? 'w-64' : 'w-20'} bg-gradient-to-b from-slate-900 to-slate-950 border-r border-white/5 transition-all duration-500 flex flex-col relative z-10`}>
        <div className="h-16 flex items-center justify-between px-4 border-b border-white/5">
          <div className={`flex items-center gap-2.5 ${sidebarOpen ? '' : 'justify-center w-full'}`}>
            <div className="p-1.5 bg-gradient-to-br from-violet-600 to-cyan-600 rounded-lg shadow-lg shadow-violet-500/20"><LayoutDashboard className="w-4 h-4 text-white" /></div>
            {sidebarOpen && <span className="font-bold text-sm text-white tracking-tight">MyApp</span>}
          </div>
          <button onClick={() => setSidebarOpen(!sidebarOpen)} className={`text-gray-500 hover:text-white hover:bg-white/5 p-1.5 rounded-lg transition-all ${sidebarOpen ? '' : 'hidden'}`}>{<X size={16} />}</button>
        </div>
        <nav className="flex-1 p-3 space-y-1">
          {navItems.map(item => (
            <Link key={item.path} to={item.path}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all duration-300 group ${
                location.pathname === item.path
                  ? 'bg-gradient-to-r from-violet-500/15 to-fuchsia-500/10 text-violet-300 shadow-sm shadow-violet-500/5 border border-violet-500/10'
                  : 'text-gray-500 hover:text-gray-200 hover:bg-white/[0.03]'
              } ${sidebarOpen ? '' : 'justify-center px-0'}`}>
              <span className={location.pathname === item.path ? 'text-violet-400' : 'text-gray-500 group-hover:text-gray-300 transition-colors'}>{item.icon}</span>
              {sidebarOpen && <span className="text-sm font-medium">{item.label}</span>}
              {sidebarOpen && location.pathname === item.path && <span className="ml-auto w-1.5 h-1.5 rounded-full bg-violet-400 animate-pulse" />}
            </Link>
          ))}
        </nav>
        <div className={`p-3 border-t border-white/5 ${sidebarOpen ? '' : 'flex justify-center'}`}>
          <div className={`flex items-center gap-2 ${sidebarOpen ? '' : 'flex-col'}`}>
            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-violet-500 to-cyan-500 flex items-center justify-center text-white text-xs font-bold shadow-lg">U</div>
            {sidebarOpen && <span className="text-xs text-gray-500">Admin User</span>}
          </div>
        </div>
      </aside>
      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-16 bg-slate-900/80 backdrop-blur-xl border-b border-white/5 flex items-center justify-between px-6 sticky top-0 z-20">
          <div className="relative w-72">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-600" />
            <input type="text" placeholder="Search..." className="w-full bg-white/5 border border-white/10 rounded-xl pl-10 pr-4 py-2 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-violet-500/50 transition-all" />
          </div>
          <button className="relative p-2 text-gray-500 hover:text-white hover:bg-white/5 rounded-lg transition-all">
            <Bell size={18} />
            <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-red-500 rounded-full"></span>
          </button>
        </header>
        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}
```

`src/pages/Dashboard.jsx`
```jsx
import { useState, useEffect } from 'react';
import { BarChart3, TrendingUp, Users, DollarSign, Activity, ArrowUpRight, ArrowDownRight, MoreHorizontal } from 'lucide-react';

function StatCard({ icon, label, value, change, positive }) {
  return (
    <div className="bg-white/[0.03] backdrop-blur-xl border border-white/[0.06] rounded-2xl p-5 hover:border-white/10 transition-all duration-300 hover:shadow-xl hover:shadow-violet-500/5 group hover:scale-[1.02]">
      <div className="flex items-center justify-between mb-3">
        <div className="p-2.5 bg-gradient-to-br from-violet-500/20 to-cyan-500/20 rounded-xl text-violet-400 group-hover:scale-110 transition-transform duration-300">{icon}</div>
        <span className={`flex items-center gap-1 text-xs font-medium ${positive ? 'text-emerald-400' : 'text-red-400'}`}>
          {change}% {positive ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
        </span>
      </div>
      <p className="text-2xl font-bold text-white mb-1">{value}</p>
      <p className="text-sm text-gray-500">{label}</p>
    </div>
  );
}

function ChartSkeleton() {
  return (
    <div className="space-y-3">
      {[1,2,3,4].map(i => <div key={i} className="h-4 bg-white/5 rounded-full animate-shimmer" style={{width: `${60 + i * 10}%`}} />)}
    </div>
  );
}

function ActivityItem({ icon, title, time, color }) {
  return (
    <div className="flex items-start gap-3 p-3 rounded-xl hover:bg-white/[0.02] transition-all group cursor-pointer">
      <div className={`p-2 rounded-lg ${color} transition-transform group-hover:scale-110`}>{icon}</div>
      <div className="flex-1 min-w-0">
        <p className="text-sm text-gray-200 truncate">{title}</p>
        <p className="text-xs text-gray-600 mt-0.5">{time}</p>
      </div>
      <MoreHorizontal size={14} className="text-gray-600 opacity-0 group-hover:opacity-100 transition-opacity" />
    </div>
  );
}

export default function Dashboard() {
  const [loading, setLoading] = useState(true);
  useEffect(() => { const t = setTimeout(() => setLoading(false), 1200); return () => clearTimeout(t); }, []);

  return (
    <div className="p-6 space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Dashboard</h1>
          <p className="text-sm text-gray-500 mt-1">Welcome back! Here is your overview.</p>
        </div>
        <button className="px-4 py-2 bg-gradient-to-r from-violet-600 to-cyan-600 rounded-xl text-sm font-medium text-white hover:shadow-xl hover:shadow-violet-500/25 transition-all hover:scale-[1.02] active:scale-[0.98]">Generate Report</button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {loading ? (
          <>
            {[1,2,3,4].map(i => <div key={i} className="bg-white/[0.03] border border-white/[0.06] rounded-2xl p-5"><ChartSkeleton /></div>)}
          </>
        ) : (
          <>
            <StatCard icon={<BarChart3 size={20} />} label="Total Revenue" value="$84,254" change="12.5" positive />
            <StatCard icon={<Users size={20} />} label="Active Users" value="2,847" change="8.2" positive />
            <StatCard icon={<Activity size={20} />} label="Conversion Rate" value="3.24%" change="2.1" positive />
            <StatCard icon={<DollarSign size={20} />} label="Avg. Order Value" value="$342" change="1.3" negative />
          </>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white/[0.03] backdrop-blur-xl border border-white/[0.06] rounded-2xl p-6">
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-lg font-semibold text-white">Revenue Overview</h2>
            <TrendingUp size={20} className="text-emerald-400" />
          </div>
          {loading ? <ChartSkeleton /> : (
            <div className="flex items-end gap-2 h-48">
              {[40, 65, 45, 80, 55, 90, 70, 85, 60, 95, 75, 88].map((h, i) => (
                <div key={i} className="flex-1 flex flex-col items-center gap-1 group">
                  <div className="w-full bg-gradient-to-t from-violet-500 to-cyan-500 rounded-t-lg transition-all duration-500 hover:from-violet-400 hover:to-cyan-400 cursor-pointer group-hover:scale-y-110 origin-bottom" style={{height: `${h}%`}} />
                  <span className="text-[10px] text-gray-600">{['J','F','M','A','M','J','J','A','S','O','N','D'][i]}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="bg-white/[0.03] backdrop-blur-xl border border-white/[0.06] rounded-2xl p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-white">Recent Activity</h2>
            <button className="text-xs text-violet-400 hover:text-violet-300 transition-colors">View all</button>
          </div>
          <div className="space-y-1">
            {loading ? (
              <div className="space-y-4">{[1,2,3,4].map(i => <div key={i} className="h-14 bg-white/5 rounded-xl animate-shimmer" />)}</div>
            ) : (
              <>
                <ActivityItem icon={<Users size={16} />} title="New user registered" time="2 minutes ago" color="bg-emerald-500/15 text-emerald-400" />
                <ActivityItem icon={<DollarSign size={16} />} title="Payment received - $2,450" time="15 minutes ago" color="bg-blue-500/15 text-blue-400" />
                <ActivityItem icon={<Activity size={16} />} title="Server health check passed" time="1 hour ago" color="bg-violet-500/15 text-violet-400" />
                <ActivityItem icon={<BarChart3 size={16} />} title="Report generated: Q3 Summary" time="3 hours ago" color="bg-amber-500/15 text-amber-400" />
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
```
"""


USER_ASSETS_PROMPT = """

USER'S UPLOADED ASSETS — These are the user's own images and files. Use them in the generated code:
{assets_section}

You MUST:
- Use these assets in the code (e.g. `<img src="{asset_url_prefix}/..."/>`, CSS backgrounds, etc.)
- Reference them by their URL path
- If you need placeholder images in addition to user assets, keep using Unsplash as before
- Prefer showing the user's own brand assets where relevant (logos, team photos, product images)
"""

RICH_OUTPUT_PROMPT = """You are TerabitStudio, an elite full-stack developer and business systems architect.

Generate a complete, production-ready {business_type} system as a React + Vite + Tailwind CSS project.

REQUIRED FEATURES:
{feature_list}

{FEW_SHOT}

OUTPUT RULES — You MUST follow these exactly:
1. Output each file as: backtick path backtick newline triple-backtick code triple-backtick
2. File paths MUST be relative to project root (e.g. `src/pages/Home.jsx`)
3. Generate ALL files needed for a complete, runnable project
4. Every component must be fully implemented — no "..." or "// TODO" placeholders

PROFESSIONAL DESIGN REQUIREMENTS — Make the output look like a premium SaaS:
5. Use high-quality placeholder images from https://images.unsplash.com/photo-XXXXX?w=800&q=80 (use real Unsplash photo IDs like 1506744038136-46273834b3fb, 1517694712202-14dd9538aa97, 1551288049-bebda4e38f71, 1497366216548-37526070297c, 1556761175-b413da4baf72, 1504384308090-c894fdcc538d, 1522071820081-009f3b6b01b1, 1519389950473-47ba0277781c, 1454165804606-c3d57bc86b40, 1507003212552-3f11eab7bf6d)
6. Add gradient backgrounds using Tailwind: `bg-gradient-to-br from-indigo-500 via-purple-500 to-pink-500`, `bg-gradient-to-r from-cyan-500 to-blue-500`
7. Use glassmorphism effects: `backdrop-blur-xl bg-white/5 border border-white/10`
8. Add smooth animations: `transition-all duration-300`, `hover:scale-[1.02]`, `hover:shadow-xl`, CSS keyframe fade-in
9. Use lucide-react v0.464+ for ALL icons — every section, button, card, nav item
10. Professional color palette: indigo/cyan/violet primary, slate/gray neutrals, emerald for success, amber for warnings, rose for errors
11. Box shadows: `shadow-lg`, `shadow-xl`, `hover:shadow-2xl` with colored variants like `shadow-indigo-500/20`
12. Card-based layouts with `rounded-xl` or `rounded-2xl`, generous padding `p-6`
13. Dark theme: `bg-slate-900` or `bg-gray-950` background, `text-slate-100` text, `bg-slate-800` for cards
14. Responsive: mobile-first with `sm:` `md:` `lg:` breakpoints
15. Include charts/data viz using inline SVG (bar charts, line charts, donut charts with gradients)
16. Loading skeletons with `animate-pulse` for async content
17. Hero sections with full-width background images (`object-cover h-96`), gradient overlays, centered CTAs
18. Hover effects on all interactive elements: cards that lift, buttons with glow, links with underlines
19. Professional typography: font weights (font-light, font-normal, font-semibold, font-bold), proper line-height, letter-spacing for headings
20. Mobile-responsive with hamburger menu on small screens, sticky headers

CRITICAL — IMPORT CONSISTENCY:
21. For EVERY `import X from "./path/..."` statement you write, you MUST ALSO output the file at that path
22. Before writing code, plan the complete file list. Then write each file.
23. Never import a component you haven't created a file for
24. Double-check: every `from "./..."` import must resolve to a file in your output

SCOPE DISCIPLINE — you have a limited token budget, spend it wisely:
25. Prefer FEWER pages/components that are fully, beautifully finished over MANY pages that are half-written or generic
26. Fully finish the file you are currently writing before starting the next one - never leave a component truncated
27. If a feature list is long, implement the 3-4 most important screens exceptionally well rather than attempting all of them shallowly
{assets_section}
User request: {user_prompt}

Now generate the complete project files:"""


def rag_search(query: str, num_results: int = 20, top_k: int = 5):
    try:
        from sentence_transformers import SentenceTransformer
        from sklearn.metrics.pairwise import cosine_similarity
        embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
    except Exception as e:
        print(f"RAG deps not loaded: {e}")
        return None, []

    try:
        results = list(DDGS().text(query, max_results=num_results))
    except Exception:
        return None, []

    if not results:
        return None, []

    documents, meta = [], []
    for r in results:
        title = r.get('title', '')
        snippet = r.get('body', '')
        link = r.get('href', '')
        documents.append(f"{title}. {snippet}")
        meta.append({"title": title, "link": link})

    doc_embeddings = embedding_model.encode(documents)
    query_embedding = embedding_model.encode(query)
    similarities = cosine_similarity([query_embedding], doc_embeddings)[0]
    top_indices = similarities.argsort()[-top_k:][::-1]

    context = "\n\n".join([documents[i] for i in top_indices])
    return context, [meta[i] for i in top_indices]


def generate_business_system_prompt(business_type: str, features: list, user_prompt: str = "", assets: list | None = None) -> str:
    feature_list = "\n".join([f"- {f}" for f in features]) if features else "- As specified by the user"
    assets_section = ""
    if assets:
        lines = []
        for a in assets:
            ext = a.get("filename", "").rsplit(".", 1)[-1].lower() if "." in a.get("filename", "") else ""
            usage = {
                "jpg": "Use as background or content image", "jpeg": "Use as background or content image",
                "png": "Use as image (logo, icon, background)", "gif": "Use as animated image",
                "webp": "Use as web-optimized image", "svg": "Use as scalable icon/logo/graphic",
                "pdf": "Link as downloadable document", "csv": "Use as data source for tables/charts",
                "txt": "Reference content as needed",
            }.get(ext, "Use as needed")
            lines.append(f"- `{a['filename']}` ({ext.upper()}, {a['mime_type']}) — {usage}. URL: `{a['url']}`")
        asset_url_prefix = assets[0].get("url", "/uploads/").rsplit("/", 1)[0] if assets else "/uploads"
        assets_section = USER_ASSETS_PROMPT.format(
            assets_section="\n".join(lines),
            asset_url_prefix=asset_url_prefix,
        )
    return RICH_OUTPUT_PROMPT.format(
        business_type=business_type,
        feature_list=feature_list,
        FEW_SHOT=FEW_SHOT_EXAMPLE,
        assets_section=assets_section,
        user_prompt=user_prompt,
    )
