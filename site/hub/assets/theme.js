(() => {
  'use strict';

  const STORAGE_KEY = 'quant-research-theme';
  const LEGACY_STORAGE_KEYS = [
    'quant-dashboard-theme',
    'quant-calm-theme',
    'dram-price-theme',
    'etf-tracking-theme',
    'momentum-factor-theme',
    'sox-theme',
  ];
  const root = document.documentElement;

  function isTheme(value) {
    return value === 'light' || value === 'dark';
  }

  function readTheme(key) {
    try {
      const value = window.localStorage?.getItem(key);
      return isTheme(value) ? value : null;
    } catch (error) {
      return null;
    }
  }

  function storedTheme() {
    const current = readTheme(STORAGE_KEY);
    const legacy = LEGACY_STORAGE_KEYS.map(readTheme).find(Boolean) || null;
    const theme = current || legacy;

    try {
      if (theme && current !== theme) window.localStorage?.setItem(STORAGE_KEY, theme);
      LEGACY_STORAGE_KEYS.forEach((key) => window.localStorage?.removeItem(key));
    } catch (error) {
      // Theme persistence and migration are optional.
    }

    return theme;
  }

  function requestedTheme() {
    try {
      const requested = new URLSearchParams(window.location?.search || '').get('theme');
      return isTheme(requested) ? requested : null;
    } catch (error) {
      return null;
    }
  }

  function systemTheme() {
    try {
      return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    } catch (error) {
      return null;
    }
  }

  function saveTheme(theme) {
    try {
      window.localStorage?.setItem(STORAGE_KEY, theme);
      LEGACY_STORAGE_KEYS.forEach((key) => window.localStorage?.removeItem(key));
    } catch (error) {
      // Theme persistence is optional.
    }
  }

  function currentTheme() {
    return root.dataset.theme === 'dark' ? 'dark' : 'light';
  }

  function applyTheme(theme) {
    const normalized = theme === 'dark' ? 'dark' : 'light';
    root.dataset.theme = normalized;
    root.style.colorScheme = normalized;
    const button = document.querySelector('#theme-toggle');
    if (!button) return;
    const isDark = normalized === 'dark';
    button.setAttribute('aria-pressed', String(isDark));
    button.setAttribute('aria-label', isDark ? '라이트 모드로 전환' : '다크 모드로 전환');
    const label = button.querySelector('.theme-toggle-text');
    if (label) label.textContent = isDark ? '라이트 모드' : '다크 모드';
  }

  function bindThemeToggle() {
    applyTheme(currentTheme());
    const button = document.querySelector('#theme-toggle');
    if (!button) return;
    button.addEventListener('click', () => {
      const nextTheme = currentTheme() === 'dark' ? 'light' : 'dark';
      applyTheme(nextTheme);
      saveTheme(nextTheme);
    });
  }

  const initialStoredTheme = storedTheme();
  applyTheme(requestedTheme() || initialStoredTheme || systemTheme() || currentTheme());

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindThemeToggle, { once: true });
  } else {
    bindThemeToggle();
  }
})();
