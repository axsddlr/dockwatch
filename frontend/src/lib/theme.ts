export type Theme = 'dark' | 'light'

const THEME_KEY = 'dockwatch:theme'

export function getTheme(): Theme {
  try {
    const stored = localStorage.getItem(THEME_KEY)
    if (stored === 'light' || stored === 'dark') return stored
  } catch {
    // ignore storage failures
  }
  return 'dark'
}

export function setTheme(theme: Theme) {
  document.documentElement.setAttribute('data-theme', theme)
  try {
    localStorage.setItem(THEME_KEY, theme)
  } catch {
    // ignore storage failures
  }
}

export function applyStoredTheme() {
  document.documentElement.setAttribute('data-theme', getTheme())
}
