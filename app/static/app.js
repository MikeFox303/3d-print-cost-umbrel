document.addEventListener('DOMContentLoaded', () => {
  const add = document.getElementById('addMaterial');
  const box = document.getElementById('materials');
  const tpl = document.getElementById('materialTemplate');
  if (add && box && tpl) {
    add.addEventListener('click', () => box.appendChild(tpl.content.cloneNode(true)));
    box.addEventListener('click', e => {
      if (e.target.classList.contains('remove-row')) e.target.closest('.material-row')?.remove();
    });
  }

  const spoolBtn = document.getElementById('loadSpoolman');
  const spoolOut = document.getElementById('spoolmanResult');
  if (spoolBtn && spoolOut) {
    spoolBtn.addEventListener('click', async () => {
      spoolBtn.disabled = true; spoolOut.textContent = 'Читаю Spoolman…';
      try {
        const r = await fetch('/api/spoolman/spools');
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'Ошибка Spoolman');
        const active = (data.spools || []).filter(s => !s.archived);
        spoolOut.innerHTML = active.length ? active.slice(0, 20).map(s => `<div class="material-line"><div><strong>${escapeHtml((s.vendor+' '+s.name).trim())}</strong><small>${escapeHtml(s.material || '')}${s.location ? ' · '+escapeHtml(s.location) : ''}</small></div><div>${s.remaining_weight == null ? '—' : Number(s.remaining_weight).toFixed(0)+' г'}${s.price_per_g ? '<br><small>'+Number(s.price_per_g).toFixed(3)+' грн/г</small>' : ''}</div></div>`).join('') : 'Катушки не найдены.';
      } catch (e) { spoolOut.textContent = 'Ошибка: ' + e.message; }
      finally { spoolBtn.disabled = false; }
    });
  }
});
function escapeHtml(v){return String(v).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#039;','"':'&quot;'}[c]));}
