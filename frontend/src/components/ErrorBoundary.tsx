/**
 * A crash wall, not a crash.
 *
 * A local-first desktop app has no server-side error tracker: when a render
 * throws, the user sees a blank window and has nothing to send anyone. React
 * unmounts the whole tree on an uncaught render error, so this boundary is
 * the difference between "the app is broken" and "here is what happened,
 * reload, and the log is in the Help menu". The error text is copied to the
 * clipboard on request -- never uploaded.
 */
import { Component, ErrorInfo, ReactNode } from 'react';
import { AlertTriangle, RotateCw, Copy, Home } from 'lucide-react';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
  info: ErrorInfo | null;
  copied: boolean;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, info: null, copied: false };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    this.setState({ error, info });
    // Also to the console: in the desktop shell it is captured in the boot
    // log, which the user can open from Help -> Open Log Folder.
    console.error('[terabit] unhandled render error:', error, info.componentStack);
  }

  private report(): string {
    const { error, info } = this.state;
    return [
      'Terabit Studio -- client error report',
      `at: ${new Date().toISOString()}`,
      `url: ${typeof location !== 'undefined' ? location.href : 'n/a'}`,
      `version: ${import.meta.env.VITE_APP_VERSION || 'dev'}`,
      '',
      String(error?.stack || error),
      '',
      'component stack:',
      String(info?.componentStack || 'n/a'),
    ].join('\n');
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div
        role="alert"
        className="min-h-screen flex items-center justify-center px-6"
        style={{ background: '#07070d' }}
      >
        <div className="max-w-xl w-full rounded-2xl border border-rose-500/25 bg-rose-950/20 p-7">
          <div className="flex items-center gap-3 text-rose-300">
            <AlertTriangle className="w-6 h-6" />
            <h1 className="text-lg font-semibold">Something in this screen failed to render</h1>
          </div>
          <p className="mt-3 text-sm text-slate-300">
            Nothing was lost: your projects stay on disk. Reloading usually fixes
            it. If it happens again, copy the report and open the log folder
            (Help menu) — both stay on this machine.
          </p>
          <pre className="mt-4 max-h-40 overflow-auto rounded-lg bg-black/40 border border-white/10 p-3 text-[11.5px] text-rose-200/80 whitespace-pre-wrap">
            {String(error.message || error)}
          </pre>
          <div className="mt-5 flex flex-wrap gap-3">
            <button
              onClick={() => location.reload()}
              className="inline-flex items-center gap-2 rounded-lg bg-violet-600 hover:bg-violet-500 px-4 py-2 text-sm font-medium text-white"
            >
              <RotateCw className="w-4 h-4" /> Reload
            </button>
            <button
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(this.report());
                  this.setState({ copied: true });
                } catch { /* clipboard refused; nothing to do */ }
              }}
              className="inline-flex items-center gap-2 rounded-lg border border-white/15 hover:border-white/30 px-4 py-2 text-sm text-slate-200"
            >
              <Copy className="w-4 h-4" /> {this.state.copied ? 'Copied' : 'Copy report'}
            </button>
            <a
              href="/"
              className="inline-flex items-center gap-2 rounded-lg border border-white/15 hover:border-white/30 px-4 py-2 text-sm text-slate-200"
            >
              <Home className="w-4 h-4" /> Back to start
            </a>
          </div>
        </div>
      </div>
    );
  }
}
