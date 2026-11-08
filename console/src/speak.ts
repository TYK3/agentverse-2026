import { on } from './bus';

// BROWSER-VOICE: the console speaks what the robots say to a casualty (`say`) out loud with the
// browser's own speechSynthesis: free, offline-capable, no Gemini. A mute button sits in the talk
// panel; muting stops what is being spoken now and the choice is remembered on this browser.

const MUTE_KEY = 'aftershock.voice.muted';
const MUTE_CSS = `
.talk-voice { float: right; margin: -0.2rem 0 0.4rem 0.5rem; font: inherit; font-size: 0.7rem; cursor: pointer;
  background: var(--panel, #0e1726); color: var(--text, #e2e8f0); border: 1px solid var(--border, #233754);
  border-radius: 0.35rem; padding: 0.2rem 0.5rem; }
.talk-voice[aria-pressed="true"] { color: var(--muted, #64748b); }
.talk-voice:disabled { cursor: not-allowed; opacity: 0.6; }
`;

function readMuted(): boolean {
  try { return localStorage.getItem(MUTE_KEY) === '1'; } catch { return false; }
}
function writeMuted(muted: boolean): void {
  try { localStorage.setItem(MUTE_KEY, muted ? '1' : '0'); } catch { /* storage blocked: keep it for this page */ }
}

export function setupSpeak(panel: HTMLElement): void {
  if (panel.querySelector('.talk-voice')) return;
  const synth: SpeechSynthesis | undefined = 'speechSynthesis' in window ? window.speechSynthesis : undefined;
  if (!document.getElementById('talk-voice-style')) {
    const style = document.createElement('style');
    style.id = 'talk-voice-style';
    style.textContent = MUTE_CSS;
    document.head.append(style);
  }

  let muted = readMuted();
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'talk-voice';
  const render = () => {
    button.setAttribute('aria-pressed', String(muted));
    button.textContent = !synth ? 'Voice unavailable' : muted ? 'Voice off' : 'Voice on';
    button.title = !synth ? 'This browser has no speech synthesis' : muted ? 'Unmute spoken lines' : 'Mute spoken lines';
  };
  button.setAttribute('aria-label', 'Mute robot voice');
  button.disabled = !synth;
  button.addEventListener('click', () => {
    muted = !muted;
    writeMuted(muted);
    if (muted) synth?.cancel();
    render();
  });
  render();
  panel.prepend(button);

  on('say', value => {
    if (muted || !synth) return;
    const data = value && typeof value === 'object' ? value as Record<string, unknown> : {};
    const line = String(data.text ?? '').trim();
    if (!line) return;
    const utterance = new SpeechSynthesisUtterance(line);
    const lang = typeof data.lang === 'string' && data.lang !== 'auto' ? data.lang : '';
    if (lang) utterance.lang = lang;
    synth.speak(utterance);
  });
}
