export type Theme = 'dark' | 'light';

const THEME_KEY = 'cs-interview-theme';

export function getTheme(): Theme {
  try {
    const value = localStorage.getItem(THEME_KEY);
    return value === 'light' ? 'light' : 'dark';
  } catch {
    return 'dark';
  }
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    // localStorage 不可用时静默忽略
  }
  window.dispatchEvent(new CustomEvent('cs-theme-change', { detail: theme }));
}
