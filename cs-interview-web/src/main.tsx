import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as monaco from 'monaco-editor';
import { loader } from '@monaco-editor/react';
import editorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker';
import { App } from './App';
import { applyTheme, getTheme } from './lib/theme';
import './index.css';

// Monaco 离线打包：worker 由 Vite 内联，不依赖 CDN
const environment: monaco.Environment = {
  getWorker: () => new editorWorker(),
};
self.MonacoEnvironment = environment;
loader.config({ monaco });

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 0,
    },
    mutations: {
      retry: 0,
    },
  },
});

applyTheme(getTheme());

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);
