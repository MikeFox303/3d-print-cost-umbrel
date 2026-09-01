document.addEventListener('DOMContentLoaded', () => {
  setupMaterialRows();
  setupQuotePreview();
  setupSpoolmanPanels();
  setupSettingsForm();
  setupDetailsActions();
});

function setupMaterialRows() {
  const add = document.getElementById('addMaterial');
  const box = document.getElementById('materials');
  const tpl = document.getElementById('materialTemplate');
  if (!box) return;

  if (add && tpl) {
    add.addEventListener('click', () => {
      box.appendChild(tpl.content.cloneNode(true));
      refreshRemainingWarnings();
    });
  }
  box.addEventListener('click', e => {
    if (e.target.classList.contains('remove-row')) {
      e.target.closest('.material-row')?.remove();
      invalidatePreview();
    }
  });
  box.addEventListener('input', () => {
    refreshRemainingWarnings();
    invalidatePreview();
  });
  box.addEventListener('change', e => {
    const row = e.target.closest('.material-row');
    if (row && e.target.matches('select[name="filament_id"]') && e.target.value) {
      row.querySelector('input[name="material_source"]').value = 'local';
      row.querySelector('input[name="material_source_ref"]').value = e.target.value;
      row.querySelector('input[name="remaining_g"]').value = '';
    }
    refreshRemainingWarnings();
    invalidatePreview();
  });
  refreshRemainingWarnings();
}

function setupQuotePreview() {
  const form = document.getElementById('orderForm');
  const button = document.getElementById('previewQuote');
  const panel = document.getElementById('quotePreview');
  if (!form || !button || !panel) return;

  form.addEventListener('input', invalidatePreview);
  form.addEventListener('change', invalidatePreview);

  const calculate = async () => {
    button.disabled = true;
    button.textContent = 'Считаю…';
    try {
      const response = await fetch('/api/quotes/economics-preview', { method: 'POST', body: new FormData(form) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || data.error || 'Ошибка расчёта');
      document.getElementById('previewMinimum').textContent = money(data.minimum_price);
      document.getElementById('previewRecommended').textContent = money(data.recommended_price);
      const b = data.breakdown || {};
      document.getElementById('previewBreakdown').innerHTML = [
        ['Материалы', b.material], ['Электричество', b.electricity], ['Обслуживание', b.maintenance],
        ['Ручной труд', b.labor], ['Упаковка', b.packaging], ['Себестоимость с риском', b.production_cost],
        ['Окупаемость по плану', b.planned_payback], ['Ставка окупаемости', b.payback_rate, ' грн/ч']
      ].map(([label, value, suffix]) => `<div><span>${label}</span><b>${Number(value || 0).toFixed(2)}${suffix || ' грн'}</b></div>`).join('');

      const e = data.customer_economics || {};
      const state = document.getElementById('previewCustomerState');
      if (state) {
        state.className = 'customer-price-state ' + (e.meets_recommended_price ? 'good' : (e.meets_minimum_price ? 'warn' : 'bad'));
        if (e.meets_recommended_price) {
          state.textContent = `Цена ${money(e.customer_price)} покрывает рекомендуемый уровень.`;
        } else if (e.meets_minimum_price) {
          state.textContent = `Цена ${money(e.customer_price)} выше минимальной, но ниже рекомендуемой.`;
        } else {
          state.textContent = `Цена ${money(e.customer_price)} ниже минимальной устойчивой цены.`;
        }
      }
      const econBox = document.getElementById('previewCustomerEconomics');
      if (econBox) {
        econBox.innerHTML = [
          ['Цена клиенту', e.customer_price],
          ['Налог', e.tax],
          ['Комиссия площадки', e.platform_fee],
          ['После налога и комиссии', e.net_revenue],
          ['Результат после базовых затрат', e.operating_result],
          ['Вклад в окупаемость', e.payback_contribution],
          ['Прибыль после окупаемости', e.profit_after_payback],
          ['Маржа после окупаемости', Number(e.profit_margin_after_payback || 0) * 100, '%']
        ].map(([label, value, suffix]) => `<div><span>${label}</span><b>${Number(value || 0).toFixed(2)}${suffix || ' грн'}</b></div>`).join('');
      }

      const warnings = data.warnings || [];
      document.getElementById('previewWarnings').innerHTML = warnings.map(x => `<div class="warning">⚠ ${escapeHtml(x)}</div>`).join('');
      panel.dataset.recommended = String(data.recommended_rounded || data.recommended_price || '');
      panel.classList.remove('hidden');
      panel.classList.remove('stale');
      await refreshPreviewClientQuote(form);
    } catch (err) {
      panel.classList.remove('hidden');
      panel.classList.remove('stale');
      const warningBox = document.getElementById('previewWarnings');
      if (warningBox) warningBox.innerHTML = `<div class="warning">Не удалось рассчитать: ${escapeHtml(err.message)}</div>`;
    } finally {
      button.disabled = false;
      button.textContent = 'Пересчитать цену';
    }
  };

  button.addEventListener('click', calculate);

  document.getElementById('useRecommended')?.addEventListener('click', async () => {
    const price = Number(panel.dataset.recommended || 0);
    if (!price) return;
    document.getElementById('finalPrice').value = Math.ceil(price);
    invalidatePreview();
    await calculate();
  });

  document.getElementById('copyPreviewClientQuote')?.addEventListener('click', async () => {
    const textarea = document.getElementById('previewClientQuoteText');
    const status = document.getElementById('previewClientQuoteStatus');
    const text = textarea?.value || '';
    if (!text) {
      if (status) status.textContent = 'Сначала рассчитайте заказ.';
      return;
    }
    const copied = await copyText(text);
    if (status) status.textContent = copied ? 'Скопировано.' : 'Не удалось скопировать автоматически — выделите текст вручную.';
  });
}

async function refreshPreviewClientQuote(form) {
  const textarea = document.getElementById('previewClientQuoteText');
  const status = document.getElementById('previewClientQuoteStatus');
  if (!textarea) return;
  textarea.value = 'Формирую сообщение…';
  if (status) status.textContent = '';
  try {
    const response = await fetch('/api/quotes/client-message', { method: 'POST', body: new FormData(form) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || data.error || 'Ошибка сообщения для клиента');
    textarea.value = data.text || '';
    textarea.dataset.customerPrice = String(data.customer_price || '');
    if (status) status.textContent = 'Готово к отправке клиенту. Внутренние расчёты в текст не включаются.';
  } catch (error) {
    textarea.value = '';
    if (status) status.textContent = `Не удалось сформировать сообщение: ${error.message}`;
  }
}

function setupSpoolmanPanels() {
  const genericBtn = document.getElementById('loadSpoolman');
  const genericOut = document.getElementById('spoolmanResult');
  if (genericBtn && genericOut) {
    genericBtn.addEventListener('click', async () => {
      genericBtn.disabled = true; genericOut.textContent = 'Читаю Spoolman…';
      try {
        const data = await fetchSpools();
        const active = data.spools.filter(s => !s.archived);
        genericOut.innerHTML = active.length ? active.slice(0, 30).map(spoolDisplayRow).join('') : 'Катушки не найдены.';
      } catch (e) { genericOut.textContent = 'Ошибка: ' + e.message; }
      finally { genericBtn.disabled = false; }
    });
  }

  const orderBtn = document.getElementById('loadSpoolmanForOrder');
  const orderOut = document.getElementById('spoolmanOrderResult');
  if (orderBtn && orderOut) {
    orderBtn.addEventListener('click', async () => {
      orderBtn.disabled = true; orderOut.textContent = 'Читаю Spoolman…';
      try {
        const data = await fetchSpools();
        const active = data.spools.filter(s => !s.archived);
        orderOut.innerHTML = active.length ? `<div class="spool-picker">${active.map(spoolChoice).join('')}</div>` : 'Катушки не найдены.';
      } catch (e) { orderOut.textContent = 'Ошибка: ' + e.message; }
      finally { orderBtn.disabled = false; }
    });
    orderOut.addEventListener('click', e => {
      const btn = e.target.closest('[data-use-spool]');
      if (!btn) return;
      insertSpoolmanMaterial(JSON.parse(btn.dataset.spool));
    });
  }
}

function setupSettingsForm() {
  const form = document.querySelector('[data-settings-form]');
  const dirtyBar = document.querySelector('[data-dirty-save]');
  if (!form || !dirtyBar) return;
  let dirty = false;
  const markDirty = () => {
    if (dirty) return;
    dirty = true;
    dirtyBar.hidden = false;
    form.classList.add('is-dirty');
  };
  form.addEventListener('input', markDirty);
  form.addEventListener('change', markDirty);
  form.addEventListener('submit', () => {
    dirtyBar.hidden = true;
    form.classList.remove('is-dirty');
  });
}

function setupDetailsActions() {
  const mobile = window.matchMedia('(max-width: 900px)').matches;
  document.querySelectorAll('details[data-mobile-collapsible]').forEach(details => {
    if (mobile) details.open = details.hasAttribute('data-mobile-open');
  });
  document.querySelectorAll('[data-open-details]').forEach(button => {
    button.addEventListener('click', () => {
      const target = document.querySelector(button.dataset.openDetails || '');
      if (!target) return;
      target.open = true;
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      window.setTimeout(() => target.querySelector('input,select,textarea')?.focus({ preventScroll: true }), 350);
    });
  });
}

async function fetchSpools() {
  const response = await fetch('/api/spoolman/spools');
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Ошибка Spoolman');
  if (!data.enabled) throw new Error('Spoolman отключён в настройках');
  return data;
}

function spoolDisplayRow(s) {
  return `<div class="material-line"><div><strong>${escapeHtml(((s.vendor || '')+' '+(s.name || '')).trim())}</strong><small>${escapeHtml(s.material || '')}${s.location ? ' · '+escapeHtml(s.location) : ''}</small></div><div>${s.remaining_weight == null ? '—' : Number(s.remaining_weight).toFixed(0)+' г'}${s.price_per_g != null ? '<br><small>'+Number(s.price_per_g).toFixed(3)+' грн/г</small>' : ''}</div></div>`;
}

function spoolChoice(s) {
  const data = escapeHtml(JSON.stringify(s));
  const ppg = s.price_per_g == null ? 'цена не задана' : `${Number(s.price_per_g).toFixed(3)} грн/г`;
  const remaining = s.remaining_weight == null ? 'остаток —' : `остаток ${Number(s.remaining_weight).toFixed(0)} г`;
  return `<div class="spool-choice"><div><strong>${escapeHtml(((s.vendor || '')+' '+(s.name || '')).trim())}</strong><small>${escapeHtml(s.material || '')} · ${remaining} · ${ppg}</small></div><button type="button" class="button small" data-use-spool data-spool="${data}" ${s.price_per_g == null ? 'disabled title="В Spoolman нет цены/веса для расчёта"' : ''}>Подставить</button></div>`;
}

function insertSpoolmanMaterial(s) {
  const box = document.getElementById('materials');
  const tpl = document.getElementById('materialTemplate');
  if (!box || !tpl) return;
  const fragment = tpl.content.cloneNode(true);
  const row = fragment.querySelector('.material-row');
  row.querySelector('select[name="filament_id"]').value = '';
  row.querySelector('input[name="manual_name"]').value = ((s.vendor || '')+' '+(s.name || '')).trim();
  row.querySelector('input[name="manual_material"]').value = s.material || '';
  row.querySelector('input[name="manual_price_per_g"]').value = s.price_per_g == null ? '' : Number(s.price_per_g).toFixed(6);
  row.querySelector('input[name="material_source"]').value = 'spoolman';
  row.querySelector('input[name="material_source_ref"]').value = String(s.id || '');
  row.querySelector('input[name="remaining_g"]').value = s.remaining_weight == null ? '' : String(s.remaining_weight);
  row.querySelector('input[name="grams"]').focus();
  box.appendChild(fragment);
  refreshRemainingWarnings();
  invalidatePreview();
}

function refreshRemainingWarnings() {
  document.querySelectorAll('.material-row').forEach(row => {
    const grams = Number(row.querySelector('input[name="grams"]')?.value || 0);
    const remInput = row.querySelector('input[name="remaining_g"]');
    const remaining = remInput && remInput.value !== '' ? Number(remInput.value) : null;
    const hint = row.querySelector('.remaining-hint');
    if (!hint) return;
    if (remaining != null) {
      hint.textContent = `Spoolman: ${remaining.toFixed(0)} г осталось`;
      hint.className = 'remaining-hint' + (grams > remaining ? ' warning-inline' : '');
      if (grams > remaining) hint.textContent += ` · не хватает ${(grams-remaining).toFixed(1)} г`;
    } else {
      hint.textContent = '';
      hint.className = 'remaining-hint';
    }
  });
}

function invalidatePreview() {
  const panel = document.getElementById('quotePreview');
  if (panel && !panel.classList.contains('hidden')) panel.classList.add('stale');
}

async function copyText(text) {
  const value = String(text || '');
  if (!value) return false;
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(value);
      return true;
    } catch (_error) {
      // Local umbrelOS installs are often plain HTTP, so keep the legacy copy fallback.
    }
  }
  const textarea = document.createElement('textarea');
  textarea.value = value;
  textarea.style.position = 'fixed';
  textarea.style.left = '-9999px';
  textarea.style.top = '0';
  textarea.style.fontSize = '16px';
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  textarea.setSelectionRange(0, textarea.value.length);
  let copied = false;
  try { copied = document.execCommand('copy'); } catch (_error) { copied = false; }
  textarea.remove();
  return copied;
}

// Page-specific scripts (for example the Bambu 3MF importer) may replace
// material rows after the main DOM setup has run. Expose only these UI helpers;
// no business logic or external-write capability is exported.
window.refreshRemainingWarnings = refreshRemainingWarnings;
window.invalidatePreview = invalidatePreview;
window.copyText = copyText;

function money(v) { return `${Math.round(Number(v || 0))} грн`; }
function escapeHtml(v){return String(v).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#039;','"':'&quot;'}[c]));}
