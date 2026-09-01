(() => {
  const PROBE_INTERVAL_MS = 15000;
  const PROBE_TIMEOUT_MS = 4000;

  const setupConnectivityBanner = () => {
    const banner = document.querySelector('[data-connectivity-banner]');
    const title = banner?.querySelector('[data-connectivity-title]');
    const message = banner?.querySelector('[data-connectivity-message]');
    if (!banner || !title || !message) return;

    let activeController = null;

    const setState = (state) => {
      const deviceOffline = state === 'device-offline';
      const umbrelUnavailable = state === 'umbrel-unavailable';
      const unavailable = deviceOffline || umbrelUnavailable;

      banner.hidden = !unavailable;
      document.documentElement.classList.toggle('is-offline', deviceOffline);
      document.documentElement.classList.toggle('is-umbrel-unavailable', umbrelUnavailable);

      if (deviceOffline) {
        title.textContent = 'Телефон офлайн.';
        message.textContent = 'Нет сетевого подключения — расчёт, сохранение и обновление данных возобновятся после подключения к сети.';
      } else if (umbrelUnavailable) {
        title.textContent = 'Umbrel недоступен.';
        message.textContent = 'Сеть на телефоне есть, но приложение не может связаться с Umbrel. Проверьте домашнюю сеть, VPN или Tailscale.';
      }
    };

    const abortProbe = () => {
      activeController?.abort();
      activeController = null;
    };

    const probeUmbrel = async () => {
      if (navigator.onLine === false) {
        abortProbe();
        setState('device-offline');
        return;
      }

      abortProbe();
      const controller = new AbortController();
      activeController = controller;
      const timeout = window.setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);

      try {
        const response = await fetch('/healthz', {
          method: 'GET',
          cache: 'no-store',
          headers: { Accept: 'application/json' },
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(`healthz ${response.status}`);
        const payload = await response.json();
        if (payload?.status !== 'ok') throw new Error('healthz payload');
        if (activeController !== controller) return;
        setState('online');
      } catch (_error) {
        if (activeController !== controller) return;
        setState(navigator.onLine === false ? 'device-offline' : 'umbrel-unavailable');
      } finally {
        window.clearTimeout(timeout);
        if (activeController === controller) activeController = null;
      }
    };

    const syncBrowserState = () => {
      if (navigator.onLine === false) {
        abortProbe();
        setState('device-offline');
        return;
      }
      setState('online');
      void probeUmbrel();
    };

    window.addEventListener('offline', syncBrowserState);
    window.addEventListener('online', syncBrowserState);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') void probeUmbrel();
    });

    window.setInterval(() => {
      if (document.visibilityState !== 'hidden') void probeUmbrel();
    }, PROBE_INTERVAL_MS);

    syncBrowserState();
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setupConnectivityBanner, { once: true });
  } else {
    setupConnectivityBanner();
  }
})();
