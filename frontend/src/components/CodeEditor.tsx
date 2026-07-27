import Editor, { useMonaco } from '@monaco-editor/react';
import { FileItem } from '../types';
import { FileCode } from 'lucide-react';
import { useEffect } from 'react';

interface CodeEditorProps {
  file: FileItem | null;
}

function getLanguage(filename: string): string {
  const ext = filename.split('.').pop()?.toLowerCase();
  const map: Record<string, string> = {
    js: 'javascript', jsx: 'javascript', ts: 'typescript', tsx: 'typescript',
    html: 'html', css: 'css', json: 'json', md: 'markdown',
    py: 'python', rs: 'rust', go: 'go', java: 'java',
    yml: 'yaml', yaml: 'yaml', xml: 'xml', sql: 'sql',
    sh: 'shell', bash: 'shell', env: 'plaintext',
  };
  return map[ext || ''] || 'plaintext';
}

export function CodeEditor({ file }: CodeEditorProps) {
  const monaco = useMonaco();

  useEffect(() => {
    if (monaco) {
      monaco.editor.defineTheme('terabitstudio-dark', {
        base: 'vs-dark',
        inherit: true,
        rules: [
          { token: 'comment', foreground: '6c7086', fontStyle: 'italic' },
          { token: 'keyword', foreground: 'cba6f7' },
          { token: 'string', foreground: 'a6e3a1' },
          { token: 'number', foreground: 'fab387' },
          { token: 'type', foreground: 'f9e2af' },
          { token: 'function', foreground: '89b4fa' },
        ],
        colors: {
          'editor.background': '#0a0e1a',
          'editor.foreground': '#cdd6f4',
          'editor.lineHighlightBackground': '#1e1e2e',
          'editorCursor.foreground': '#cba6f7',
          'editor.selectionBackground': '#45475a',
        },
      });
    }
  }, [monaco]);

  if (!file) {
    return (
      <div className="h-full flex items-center justify-center text-gray-500">
        <div className="text-center">
          <FileCode className="w-12 h-12 mx-auto mb-3 opacity-30" />
          <p className="text-sm">Select a file to view</p>
        </div>
      </div>
    );
  }

  return (
    <Editor
      height="100%"
      language={getLanguage(file.name)}
      value={file.content || ''}
      theme="terabitstudio-dark"
      options={{
        readOnly: true,
        minimap: { enabled: false },
        fontSize: 13,
        fontFamily: "'JetBrains Mono', monospace",
        wordWrap: 'on',
        scrollBeyondLastLine: false,
        lineNumbers: 'on',
        renderLineHighlight: 'line',
        padding: { top: 16 },
      }}
    />
  );
}
