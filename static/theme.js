(() => {
  const root = document.documentElement;
  let theme = 'dark';
  try {
    const saved = localStorage.getItem('onair-theme');
    if (saved === 'light' || saved === 'dark') theme = saved;
    else if (window.matchMedia('(prefers-color-scheme: light)').matches) theme = 'light';
  } catch { /* The switch also works when browser storage is unavailable. */ }
  root.dataset.theme = theme;

  document.addEventListener('DOMContentLoaded', () => {
    const button = document.getElementById('theme-toggle');
    function updateButton() {
      const light = root.dataset.theme === 'light';
      button.textContent = light ? 'Darkmode' : 'Lightmode';
      button.setAttribute('aria-label', light ? 'Darkmode einschalten' : 'Lightmode einschalten');
      button.setAttribute('aria-pressed', String(light));
    }
    updateButton();
    button.addEventListener('click', () => {
      root.dataset.theme = root.dataset.theme === 'light' ? 'dark' : 'light';
      try { localStorage.setItem('onair-theme', root.dataset.theme); } catch { /* Optional persistence. */ }
      updateButton();
    });
  });
})();
