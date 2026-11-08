// Marks the story strip "tight" when its ten step names do not all fit on one
// line. Then only the current and waiting steps keep their names, the others
// fold to their number and open on hover (see theme.css). A wide screen shows
// every name with no motion.
export function setupStripFit(): void {
  const check = (strip: HTMLElement): void => {
    if (strip.matches(':hover')) return; // don't flip while the operator is pointing at it
    // Width the strip would need with every name in full (labels may be folded now).
    const phases = [...strip.querySelectorAll<HTMLElement>('.story-phase')];
    const gap = parseFloat(getComputedStyle(strip).columnGap) || 0;
    const need = phases.reduce((sum, ph) => {
      const label = ph.querySelector<HTMLElement>('.story-label');
      const extra = label ? label.scrollWidth - label.clientWidth : 0;
      return sum + ph.offsetWidth + extra;
    }, gap * Math.max(0, phases.length - 1));
    const was = strip.classList.contains('is-tight');
    // A little slack either way, so a width right at the limit cannot flicker.
    const tight = was ? need > strip.clientWidth - 12 : need > strip.clientWidth + 1;
    // Only write when it changes, so this observer does not trigger itself.
    if (was !== tight) strip.classList.toggle('is-tight', tight);
  };
  const attach = (): boolean => {
    const strip = document.querySelector<HTMLElement>('.story-strip');
    if (!strip) return false;
    const run = (): void => check(strip);
    new ResizeObserver(run).observe(strip);
    new MutationObserver(run).observe(strip, { attributes: true, subtree: true, childList: true });
    strip.addEventListener('mouseleave', run);
    run();
    return true;
  };
  if (!attach()) {
    const wait = new MutationObserver(() => { if (attach()) wait.disconnect(); });
    wait.observe(document.body, { childList: true, subtree: true });
  }
}
