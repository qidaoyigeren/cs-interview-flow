import { useEffect, useState } from 'react';
import { applyTheme, getTheme, type Theme } from '@/lib/theme';

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => getTheme());

  useEffect(() => {
    const handler = () => setTheme(getTheme());
    window.addEventListener('cs-theme-change', handler);
    return () => window.removeEventListener('cs-theme-change', handler);
  }, []);

  return {
    theme,
    isDark: theme === 'dark',
    toggle: () => applyTheme(theme === 'dark' ? 'light' : 'dark'),
  };
}
