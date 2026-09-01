(() => {
  const setupConnectivityBanner = () => {
    const banner = document.querySelector('[data-connectivity-banner]');
    if (!banner) return;

    const sync = () => {
      const offline = navigator.onLine === false;
      banner.hidden = !offline;
      document.documentElement.classList.toggle('is-offline', offline);
    };

    window.addEventListener('offline', sync);
    window.addEventListener('online', sync);
    sync();
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setupConnectivityBanner, { once: true });
  } else {
    setupConnectivityBanner();
  }
})();
