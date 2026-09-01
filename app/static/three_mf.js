(() => {
  function esc(value) {
    return String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#039;','"':'&quot;'}[c]));
  }

  function plateCard(plate, index) {
    const minutes = Number(plate.print_minutes || 0);
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    const materials = (plate.filaments || [])
      .map(f => `${esc(f.type || 'Материал')} ${Number(f.used_g || 0).toFixed(1)} г`)
      .join(' · ');
    return `<div class="import-plate"><div><strong>Пластина ${Number(plate.index || index + 1)}</strong><small>${hours}ч ${mins}м · ${Number(plate.filament_total_g || 0).toFixed(1)} г</small><small>${materials}</small></div><button class="button small" type="button" data-import-plate="${index}">Подставить</button></div>`;
  }

  function appendMatchHint(row, text, kind = 'hint') {
    const node = document.createElement('div');
    node.className = `import-match-hint ${kind}`;
    node.textContent = text;
    row.appendChild(node);
  }

  function applyPlate(plate) {
    const form = document.getElementById('orderForm');
    const box = document.getElementById('materials');
    const tpl = document.getElementById('materialTemplate');
    if (!form || !box || !tpl) return;

    const minutes = Number(plate.print_minutes || 0);
    form.querySelector('input[name="print_hours"]').value = Math.floor(minutes / 60);
    form.querySelector('input[name="print_mins"]').value = minutes % 60;
    box.innerHTML = '';

    let matched = 0;
    let ambiguous = 0;
    let missing = 0;

    (plate.filaments || []).forEach(f => {
      const fragment = tpl.content.cloneNode(true);
      const row = fragment.querySelector('.material-row');
      const select = row.querySelector('select[name="filament_id"]');
      const candidates = Array.isArray(f.local_candidates) ? f.local_candidates : [];
      const autoId = f.auto_local_filament_id == null ? '' : String(f.auto_local_filament_id);

      select.value = '';
      row.querySelector('input[name="grams"]').value = Number(f.used_g || 0).toFixed(2);
      const type = f.type || 'Материал';
      const color = f.color || '';
      row.querySelector('input[name="manual_name"]').value = color ? `${type} ${color}` : type;
      row.querySelector('input[name="manual_material"]').value = type;
      row.querySelector('input[name="manual_price_per_g"]').value = '';
      row.querySelector('input[name="material_source"]').value = 'manual';
      row.querySelector('input[name="material_source_ref"]').value = '';
      row.querySelector('input[name="remaining_g"]').value = '';

      if (autoId && select.querySelector(`option[value="${autoId}"]`)) {
        select.value = autoId;
        row.querySelector('input[name="material_source"]').value = 'local';
        row.querySelector('input[name="material_source_ref"]').value = autoId;
        const chosen = candidates.find(candidate => String(candidate.id) === autoId);
        const reason = f.auto_local_match_reason === 'material+color' ? 'материал + цвет' : 'единственное совпадение материала';
        appendMatchHint(row, `✓ Автовыбор: ${chosen?.label || 'локальная катушка'} (${reason}).`);
        matched += 1;
      } else if (candidates.length > 1) {
        appendMatchHint(row, `Найдено ${candidates.length} локальных катушек ${type}. Выберите реальную катушку — автоматически не угадываю.`, 'warning-inline');
        ambiguous += 1;
      } else if (candidates.length === 1) {
        // Defensive fallback: the API should mark a unique material as auto-selectable.
        appendMatchHint(row, `Найдена локальная катушка ${candidates[0].label}, но автосопоставление не применено. Выберите её вручную.`, 'warning-inline');
        ambiguous += 1;
      } else {
        appendMatchHint(row, `Локальная катушка для ${type} не найдена. Выберите Spoolman или укажите фактическую цену вручную.`);
        missing += 1;
      }

      box.appendChild(fragment);
    });

    if (typeof window.refreshRemainingWarnings === 'function') window.refreshRemainingWarnings();
    if (typeof window.invalidatePreview === 'function') window.invalidatePreview();
    const result = document.getElementById('threeMfResult');
    if (result) {
      const parts = [`✓ Время и граммы подставлены`];
      if (matched) parts.push(`автоматически сопоставлено: ${matched}`);
      if (ambiguous) parts.push(`нужно выбрать катушку: ${ambiguous}`);
      if (missing) parts.push(`без локального совпадения: ${missing}`);
      result.insertAdjacentHTML('afterbegin', `<div class="import-success">${esc(parts.join(' · '))}</div>`);
    }
    form.scrollIntoView({behavior: 'smooth', block: 'start'});
  }

  const input = document.getElementById('threeMfFile');
  const output = document.getElementById('threeMfResult');
  if (!input || !output) return;

  input.addEventListener('change', async () => {
    const file = input.files && input.files[0];
    if (!file) return;
    output.textContent = 'Читаю данные Slice и сопоставляю локальные материалы…';
    const body = new FormData();
    body.append('file', file);
    try {
      const response = await fetch('/api/import/3mf', {method: 'POST', body});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Не удалось прочитать 3MF');
      const plates = data.plates || [];
      if (!plates.length) throw new Error('В файле нет нарезанных пластин');
      output.innerHTML = `<div class="import-plates">${plates.map(plateCard).join('')}</div>`;
      output.querySelectorAll('[data-import-plate]').forEach(button => {
        button.addEventListener('click', () => applyPlate(plates[Number(button.dataset.importPlate)]));
      });
    } catch (error) {
      output.innerHTML = `<div class="warning">${esc(error.message)}</div>`;
    } finally {
      input.value = '';
    }
  });
})();
