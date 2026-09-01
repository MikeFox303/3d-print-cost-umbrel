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

  function applyPlate(plate) {
    const form = document.getElementById('orderForm');
    const box = document.getElementById('materials');
    const tpl = document.getElementById('materialTemplate');
    if (!form || !box || !tpl) return;

    const minutes = Number(plate.print_minutes || 0);
    form.querySelector('input[name="print_hours"]').value = Math.floor(minutes / 60);
    form.querySelector('input[name="print_mins"]').value = minutes % 60;
    box.innerHTML = '';

    (plate.filaments || []).forEach(f => {
      const fragment = tpl.content.cloneNode(true);
      const row = fragment.querySelector('.material-row');
      row.querySelector('select[name="filament_id"]').value = '';
      row.querySelector('input[name="grams"]').value = Number(f.used_g || 0).toFixed(2);
      const type = f.type || 'Материал';
      const color = f.color || '';
      row.querySelector('input[name="manual_name"]').value = color ? `${type} ${color}` : type;
      row.querySelector('input[name="manual_material"]').value = type;
      row.querySelector('input[name="manual_price_per_g"]').value = '';
      row.querySelector('input[name="material_source"]').value = 'manual';
      row.querySelector('input[name="material_source_ref"]').value = '';
      row.querySelector('input[name="remaining_g"]').value = '';
      box.appendChild(fragment);
    });

    if (typeof window.refreshRemainingWarnings === 'function') window.refreshRemainingWarnings();
    if (typeof window.invalidatePreview === 'function') window.invalidatePreview();
    const result = document.getElementById('threeMfResult');
    if (result) result.insertAdjacentHTML('afterbegin', '<div class="import-success">✓ Время и граммы подставлены. Теперь выберите реальные катушки/цены для каждого материала.</div>');
    form.scrollIntoView({behavior: 'smooth', block: 'start'});
  }

  const input = document.getElementById('threeMfFile');
  const output = document.getElementById('threeMfResult');
  if (!input || !output) return;

  input.addEventListener('change', async () => {
    const file = input.files && input.files[0];
    if (!file) return;
    output.textContent = 'Читаю данные Slice…';
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
