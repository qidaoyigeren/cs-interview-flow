/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ['selector', '[data-theme="dark"]'],
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      borderColor: {
        DEFAULT: 'var(--line)',
      },
      colors: {
        app: 'var(--bg-app)',
        content: 'var(--bg-content)',
        surface: 'var(--bg-surface)',
        hover: 'var(--bg-hover)',
        overlay: 'var(--bg-overlay)',
        ink: 'var(--ink)',
        'ink-secondary': 'var(--ink-secondary)',
        'ink-tertiary': 'var(--ink-tertiary)',
        'ink-inverse': 'var(--ink-inverse)',
        line: 'var(--line)',
        'line-strong': 'var(--line-strong)',
        accent: 'var(--accent)',
        'accent-dim': 'var(--accent-dim)',
        ok: 'var(--ok)',
        'ok-dim': 'var(--ok-dim)',
        warn: 'var(--warn)',
        'warn-dim': 'var(--warn-dim)',
        err: 'var(--err)',
        'err-dim': 'var(--err-dim)',
      },
      fontFamily: {
        sans: [
          '"IBM Plex Sans SC"',
          '"Noto Sans SC"',
          '"PingFang SC"',
          '"Microsoft YaHei"',
          'system-ui',
          'sans-serif',
        ],
        mono: ['"JetBrains Mono"', 'Cascadia Mono', 'Consolas', 'monospace'],
      },
      borderRadius: {
        DEFAULT: '4px',
        lg: '6px',
        xl: '8px',
      },
      fontSize: {
        '2xs': ['10px', '14px'],
      },
      boxShadow: {
        float: '0 1px 3px rgba(0,0,0,0.35)',
      },
    },
  },
  plugins: [],
};
