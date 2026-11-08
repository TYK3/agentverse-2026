// Light and dark mode for the operator screen. The choice is kept per browser;
// it starts dark, as rehearsed for the demo. The 3D view stays dark
// in both modes so map colours keep their meaning.
type Mode = 'light' | 'dark';
const KEY = 'aftershock-theme';

function saved(): Mode | null {
  try {
    const v = localStorage.getItem(KEY);
    return v === 'light' || v === 'dark' ? v : null;
  } catch {
    return null;
  }
}

function apply(mode: Mode, btn: HTMLButtonElement | null): void {
  document.documentElement.dataset.theme = mode;
  if (btn) {
    btn.textContent = mode === 'dark' ? 'Light mode' : 'Dark mode';
    btn.setAttribute('aria-pressed', String(mode === 'light'));
  }
}

export function setupThemeToggle(): void {
  const btn = document.querySelector<HTMLButtonElement>('#btn-theme');
  let mode: Mode = saved() ?? 'dark';
  apply(mode, btn);
  btn?.addEventListener('click', () => {
    mode = mode === 'dark' ? 'light' : 'dark';
    apply(mode, btn);
    try {
      localStorage.setItem(KEY, mode);
    } catch {
      /* private window: the choice just isn't remembered */
    }
  });
}
