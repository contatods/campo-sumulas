// ═══════════════════════════════════════════════════════════════════
//  STATE
// ═══════════════════════════════════════════════════════════════════
let config = {
  evento: { nome: "", categoria: "", data: "", logo_empresa: DS_LOGO_PADRAO, logo_evento: "" },
  workouts: [],
  atletas: []   // atletas da categoria atual (pode estar vazio)
};
let editingIdx  = -1;   // -1 = new workout
let previewIdx  = -1;
let importedData = null;  // resultado completo do último import (pra trocar categoria sem reimportar)
const STATE_KEY     = 'ds_sumulas_v1_state';
const IMPORT_KEY    = 'ds_sumulas_v1_import';
const LABEL_COL_KEY = 'ds_sumulas_v1_show_label';

// ═══════════════════════════════════════════════════════════════════
//  EVENTO
// ═══════════════════════════════════════════════════════════════════
function toggleEventoForm() {
  const form = document.getElementById('eventoForm');
  const disp = document.getElementById('eventoDisplay');
  const btn  = document.getElementById('btnToggleEvento');
  const open = form.style.display === 'none';
  form.style.display = open ? '' : 'none';
  btn.textContent    = open ? 'Fechar' : 'Editar';
  if (open) {
    document.getElementById('evNome').value = config.evento.nome || '';
    document.getElementById('evCat').value  = config.evento.categoria || '';
    document.getElementById('evData').value = config.evento.data || '';
    // Mostra preview da logo empresa se já estiver carregada (padrão DS)
    const empImg = document.getElementById('logoEmpresaPreview');
    const empPh  = document.getElementById('logoEmpresaPlaceholder');
    if (config.evento.logo_empresa) {
      empImg.src = config.evento.logo_empresa;
      empImg.style.display = '';
      empPh.style.display  = 'none';
    }
    const evtImg = document.getElementById('logoEventoPreview');
    const evtPh  = document.getElementById('logoEventoPlaceholder');
    if (config.evento.logo_evento) {
      evtImg.src = config.evento.logo_evento;
      evtImg.style.display = '';
      evtPh.style.display  = 'none';
    }
  }
}

function onEventoChange() {
  config.evento.nome      = document.getElementById('evNome').value.trim();
  config.evento.categoria = document.getElementById('evCat').value.trim();
  config.evento.data      = document.getElementById('evData').value.trim();
  renderEventoDisplay();
  atualizarBotaoGerar();
  refreshPreview();
  saveState();
}

function onLogoEvento(input) {
  if (!input.files || !input.files[0]) return;
  const reader = new FileReader();
  reader.onload = e => {
    config.evento.logo_evento = e.target.result;
    const img = document.getElementById('logoEventoPreview');
    const ph  = document.getElementById('logoEventoPlaceholder');
    img.src = e.target.result; img.style.display = '';
    ph.style.display = 'none';
    refreshPreview();
    saveState();
  };
  reader.readAsDataURL(input.files[0]);
}

function onLogoEmpresa(input) {
  if (!input.files || !input.files[0]) return;
  const reader = new FileReader();
  reader.onload = e => {
    config.evento.logo_empresa = e.target.result;
    const img = document.getElementById('logoEmpresaPreview');
    const ph  = document.getElementById('logoEmpresaPlaceholder');
    img.src = e.target.result; img.style.display = '';
    ph.style.display = 'none';
    refreshPreview();
    saveState();
  };
  reader.readAsDataURL(input.files[0]);
}

function refreshPreview() {
  if (previewIdx >= 0 && previewIdx < config.workouts.length) {
    previewWorkout(previewIdx);
  }
}

function renderEventoDisplay() {
  const d = document.getElementById('eventoDisplay');
  if (config.evento.nome) {
    d.innerHTML = `<div class="ev-nome">${esc(config.evento.nome)}</div>
      <div class="ev-meta">${esc(config.evento.categoria)}${config.evento.data ? ' · ' + esc(config.evento.data) : ''}</div>`;
  } else {
    d.innerHTML = '<div class="ev-empty">Clique para configurar o evento</div>';
  }
}

// ═══════════════════════════════════════════════════════════════════
//  WORKOUT LIST
// ═══════════════════════════════════════════════════════════════════
const TIPO_LABEL = { for_time: 'For Time', amrap: 'AMRAP', express: 'Express' };

function computeWorkoutNumbers() {
  // Express ocupa 2 slots (N e N+1), demais 1 slot cada
  let counter = 1;
  config.workouts.forEach(w => {
    w.numero = counter;
    if (w.tipo === 'express') {
      w.numero_f2 = counter + 1;
      counter += 2;
    } else {
      delete w.numero_f2;
      counter += 1;
    }
  });
}

function renderWorkoutList() {
  computeWorkoutNumbers();
  const el = document.getElementById('workoutList');
  if (!config.workouts.length) {
    el.innerHTML = '<div class="wkt-empty">Nenhum workout ainda.<br>Clique em "+ Novo" para começar.</div>';
    return;
  }
  el.innerHTML = config.workouts.map((w, i) => {
    const numHtml = (w.tipo === 'express' && w.numero_f2 !== undefined)
      ? `<span style="font-size:10px;line-height:1.15">${w.numero}<span style="font-size:8px;opacity:.55">·${w.numero_f2}</span></span>`
      : w.numero;
    return `
    <div class="wkt-card${previewIdx === i ? ' active' : ''}" id="wcard${i}" onclick="selectWorkout(${i})">
      <div class="wkt-num">${numHtml}</div>
      <div class="wkt-info">
        <div class="wkt-name">${esc(w.nome)}</div>
        <div class="wkt-tags">
          <span class="tag ${w.tipo}">${TIPO_LABEL[w.tipo] || w.tipo}</span>
          ${w.time_cap ? `<span class="tag">${esc(w.time_cap)}</span>` : ''}
        </div>
      </div>
      <div class="wkt-actions">
        <button class="icon-btn" onclick="event.stopPropagation();editarWorkout(${i})" title="Editar">✎</button>
        <button class="icon-btn danger" onclick="event.stopPropagation();deletarWorkout(${i})" title="Excluir">×</button>
      </div>
    </div>`;
  }).join('');
}

function selectWorkout(idx) {
  previewIdx = idx;
  renderWorkoutList();
  previewWorkout(idx);
}

function atualizarBotaoGerar() {
  const btn = document.getElementById('btnGerar');
  const lbl = document.getElementById('btnGerarLabel');
  const sub = document.getElementById('btnGerarSub');
  const nWkt = config.workouts.length;
  const nAtl = config.atletas.length;
  btn.disabled = nWkt === 0;
  if (nWkt === 0) {
    lbl.textContent = 'Gerar súmulas';
    sub.textContent = 'Adicione um workout pra começar';
    return;
  }
  const total = nAtl ? nWkt * nAtl : nWkt;
  lbl.textContent = `Gerar ${total} súmula${total !== 1 ? 's' : ''}`;
  const evt  = config.evento.categoria || config.evento.nome;
  const meta = nAtl
    ? `${nAtl} atleta${nAtl !== 1 ? 's' : ''} × ${nWkt} workout${nWkt !== 1 ? 's' : ''}`
    : `${nWkt} workout${nWkt !== 1 ? 's' : ''}`;
  sub.textContent = evt ? `${evt} · ${meta}` : meta;
}

// ═══════════════════════════════════════════════════════════════════
//  EDITOR
// ═══════════════════════════════════════════════════════════════════
function novoWorkout() {
  editingIdx = -1;
  document.getElementById('edTitle').textContent = 'Novo Workout';
  document.getElementById('edNome').value = '';
  document.getElementById('edTipo').value = 'for_time';
  document.getElementById('edTimeCap').value = '';
  document.getElementById('edDescricao').value = '';
  setExpressJanela('f1', '', '');
  setExpressJanela('f2', '', '');
  setMovTableFromArray('main', []);
  setMovTableFromArray('f1', []);
  setMovTableFromArray('f2', []);
  switchExpressTab('f1');
  onTipoChange();
  abrirEditor();
}

function editarWorkout(idx) {
  editingIdx = idx;
  const w = config.workouts[idx];
  document.getElementById('edTitle').textContent = `Workout ${w.numero} — ${w.nome}`;
  document.getElementById('edNome').value = w.nome || '';
  document.getElementById('edTipo').value = w.tipo || 'for_time';
  document.getElementById('edTimeCap').value = w.time_cap || '';
  document.getElementById('edDescricao').value = (w.descricao || []).join('\n');
  if (w.tipo === 'express') {
    const j1 = parseJanela((w.formula1 || {}).janela);
    const j2 = parseJanela((w.formula2 || {}).janela);
    setExpressJanela('f1', j1.start, j1.end);
    setExpressJanela('f2', j2.start, j2.end);
    setMovTableFromArray('f1', (w.formula1 || {}).movimentos || []);
    setMovTableFromArray('f2', (w.formula2 || {}).movimentos || []);
    switchExpressTab('f1');
  } else {
    setMovTableFromArray('main', w.movimentos || []);
  }
  onTipoChange();
  abrirEditor();
}

function abrirEditor() {
  document.getElementById('editor').classList.add('open');
}

function fecharEditor() {
  document.getElementById('editor').classList.remove('open');
  editingIdx = -1;
}

function onTipoChange() {
  const t = document.getElementById('edTipo').value;
  document.getElementById('secMovimentos').style.display = t !== 'express' ? '' : 'none';
  document.getElementById('secExpress').style.display    = t === 'express' ? '' : 'none';
  document.getElementById('btnChegadaMain').style.display = t === 'amrap' ? 'none' : '';
  if (t === 'express') switchExpressTab('f1');
}

function switchExpressTab(tab) {
  ['f1','f2'].forEach(t => {
    const btn = document.querySelector(`.ex-tab[data-tab="${t}"]`);
    const pnl = document.getElementById('exPanel' + t.toUpperCase());
    if (btn) btn.classList.toggle('active', t === tab);
    if (pnl) pnl.style.display = (t === tab) ? '' : 'none';
  });
}

// ── Janela estruturada (start/end mm:ss) ↔ string canônica ──
function setExpressJanela(section, start, end) {
  const sId = section === 'f1' ? 'edF1Start' : 'edF2Start';
  const eId = section === 'f1' ? 'edF1End'   : 'edF2End';
  document.getElementById(sId).value = start || '';
  document.getElementById(eId).value = end   || '';
}

function parseJanela(janela) {
  const m = String(janela || '').match(/(\d{1,2}:\d{2})\s*[→\-]\s*(\d{1,2}:\d{2})/);
  return m ? { start: m[1], end: m[2] } : { start: '', end: '' };
}

function mmssToSec(mmss) {
  const m = String(mmss || '').match(/^(\d+):(\d{1,2})$/);
  if (!m) return null;
  return parseInt(m[1], 10) * 60 + parseInt(m[2], 10);
}

function buildJanelaAmrap(start, end) {
  if (!start && !end) return '';
  const ss = mmssToSec(start), es = mmssToSec(end);
  if (ss == null || es == null || es <= ss) return `${start} → ${end}  ·  AMRAP`;
  const dur = Math.round((es - ss) / 60);
  return `${start} → ${end}  ·  AMRAP ${dur} MIN`;
}

function buildJanelaForTime(start, end) {
  if (!start && !end) return '';
  return `${start} → ${end}  ·  FOR TIME`;
}

function salvarWorkout() {
  const nome = document.getElementById('edNome').value.trim().toUpperCase();
  if (!nome) { toast('Digite o nome do workout', 'err'); return; }
  const tipo = document.getElementById('edTipo').value;
  const timeCap = document.getElementById('edTimeCap').value.trim();
  const desc = document.getElementById('edDescricao').value.split('\n').map(s=>s.trim()).filter(Boolean);

  let wkt;
  if (editingIdx >= 0) {
    wkt = config.workouts[editingIdx];
  } else {
    wkt = { numero: 0, modalidade: 'individual' };
    config.workouts.push(wkt);
    editingIdx = config.workouts.length - 1;
  }

  wkt.nome     = nome;
  wkt.tipo     = tipo;
  wkt.estilo   = tipo;
  wkt.time_cap = timeCap;
  wkt.descricao = desc;

  if (tipo === 'express') {
    const f1Start = document.getElementById('edF1Start').value.trim();
    const f1End   = document.getElementById('edF1End').value.trim();
    const f2Start = document.getElementById('edF2Start').value.trim();
    const f2End   = document.getElementById('edF2End').value.trim();
    wkt.formula1 = {
      janela: buildJanelaAmrap(f1Start, f1End),
      descricao: [],
      movimentos: getMovTableArray('f1')
    };
    wkt.formula2 = {
      janela: buildJanelaForTime(f2Start, f2End),
      descricao: [],
      movimentos: getMovTableArray('f2')
    };
    delete wkt.movimentos;
  } else {
    wkt.movimentos = getMovTableArray('main');
    delete wkt.formula1;
    delete wkt.formula2;
  }

  previewIdx = editingIdx;
  fecharEditor();
  renderWorkoutList();
  atualizarBotaoGerar();
  updateClearAllVisibility();
  previewWorkout(previewIdx);
  saveState();
  toast('Workout salvo!', 'ok');
}

function deletarWorkout(idx) {
  if (!confirm(`Excluir workout "${config.workouts[idx].nome}"?`)) return;
  config.workouts.splice(idx, 1);
  computeWorkoutNumbers(); // Renumber with Express slot logic
  if (previewIdx >= config.workouts.length) previewIdx = config.workouts.length - 1;
  renderWorkoutList();
  atualizarBotaoGerar();
  updateClearAllVisibility();
  if (previewIdx >= 0) previewWorkout(previewIdx);
  else {
    document.getElementById('previewFrame').style.display = 'none';
    document.getElementById('pbName').textContent = '—';
    updateEmptyState();
  }
  saveState();
}

// ═══════════════════════════════════════════════════════════════════
//  MOVEMENTS TABLE
// ═══════════════════════════════════════════════════════════════════
// section: 'main' | 'f1' | 'f2'
const bodyId = s => s === 'main' ? 'movTableBody' : `movTable${s.toUpperCase()}Body`;

function setMovTableFromArray(section, movs) {
  const body = document.getElementById(bodyId(section));
  body.innerHTML = '';
  if (!movs.length) {
    body.innerHTML = '<div class="empty-table">Adicione movimentos abaixo</div>';
    return;
  }
  movs.forEach(m => appendMovRow(section, m));
}

function getMovTableArray(section) {
  const body = document.getElementById(bodyId(section));
  const rows = body.querySelectorAll('.mov-row');
  const arr = [];
  rows.forEach(row => {
    const t = row.dataset.type;
    if (t === 'sep') {
      arr.push({ separador: row.querySelector('.mi-sep-input').value.trim() || 'then...' });
    } else if (t === 'chegada') {
      arr.push({ chegada: true });
    } else {
      const nome = row.querySelector('.mi-nome').value.trim().toUpperCase();
      if (!nome) return;
      const mov = { nome };
      const repsEl = row.querySelector('.mi-reps');
      const reps = parseInt(repsEl.value);
      if (!isNaN(reps) && reps > 0) mov.reps = reps;
      else if (repsEl.value.trim()) mov.reps = repsEl.value.trim();
      const label = row.querySelector('.mi-label').value.trim();
      if (label) mov.label = label;
      arr.push(mov);
    }
  });
  return arr;
}

function appendMovRow(section, mov) {
  const body = document.getElementById(bodyId(section));
  // Remove empty placeholder
  const empty = body.querySelector('.empty-table');
  if (empty) empty.remove();

  const row = document.createElement('div');

  if (mov.chegada) {
    row.className = 'mov-row chegada-row';
    row.dataset.type = 'chegada';
    row.innerHTML = `<div class="mi-chegada">✓ Chegada / Finish</div>
      <div class="mi-ctrl">${ctrlBtns(section)}</div>`;
  } else if (mov.separador !== undefined) {
    row.className = 'mov-row sep-row';
    row.dataset.type = 'sep';
    row.innerHTML = `<input class="mi-sep-input" value="${esc(mov.separador || 'then...')}"
        placeholder="then..." style="flex:1;font-style:italic;color:var(--text3)">
      <div class="mi-ctrl">${ctrlBtns(section)}</div>`;
  } else {
    row.className = 'mov-row';
    row.dataset.type = 'normal';
    row.innerHTML = `
      <input class="mi-nome" value="${esc(mov.nome || '')}" placeholder="Nome do movimento">
      <div class="mi-reps-stepper">
        <button class="rs-btn" tabindex="-1" onclick="repsStep(this,-1)">−</button>
        <input class="mi-reps" type="text" inputmode="numeric" value="${mov.reps || ''}" placeholder="—">
        <button class="rs-btn" tabindex="-1" onclick="repsStep(this,+1)">+</button>
      </div>
      <input class="mi-label" value="${esc(mov.label || '')}" placeholder="Label" style="width:72px;font-size:10.5px">
      <div class="mi-ctrl">${ctrlBtns(section)}</div>`;
  }

  body.appendChild(row);
}

function ctrlBtns(section) {
  return `<button class="icon-btn" onclick="movUp(this)" title="Subir">↑</button>
    <button class="icon-btn danger" onclick="removeRow(this)" title="Remover">×</button>`;
}

function repsStep(btn, delta) {
  const inp = btn.parentElement.querySelector('.mi-reps');
  let v = parseInt(inp.value, 10);
  if (isNaN(v)) v = 0;
  v = Math.max(1, Math.min(999, v + delta));
  inp.value = v;
  inp.dispatchEvent(new Event('input', { bubbles: true }));
}

function addMov(section) {
  appendMovRow(section, { nome: '', reps: '' });
  // Focus first input
  const body = document.getElementById(bodyId(section));
  const last = body.lastElementChild;
  if (last) { const inp = last.querySelector('input'); if (inp) inp.focus(); }
}

function addSep(section) { appendMovRow(section, { separador: 'then...' }); }

function addChegada(section) {
  // Only one chegada allowed
  const body = document.getElementById(bodyId(section));
  if (body.querySelector('.chegada-row')) { toast('Chegada já adicionada', 'err'); return; }
  appendMovRow(section, { chegada: true });
}

function removeRow(btn) {
  const row = btn.closest('.mov-row');
  const body = row.parentElement;
  row.remove();
  if (!body.querySelector('.mov-row')) {
    body.innerHTML = '<div class="empty-table">Adicione movimentos abaixo</div>';
  }
}

function movUp(btn) {
  const row = btn.closest('.mov-row');
  const prev = row.previousElementSibling;
  if (prev && prev.classList.contains('mov-row')) {
    row.parentElement.insertBefore(row, prev);
  }
}

// ═══════════════════════════════════════════════════════════════════
//  PREVIEW
// ═══════════════════════════════════════════════════════════════════
function previewWorkout(idx) {
  const wkt = config.workouts[idx];
  if (!wkt) return;
  document.getElementById('pbName').textContent = `${wkt.numero} — ${wkt.nome}`;
  document.getElementById('previewEmpty').style.display = 'none';
  // Show loading state
  const frame = document.getElementById('previewFrame');
  frame.style.display = 'block';

  fetch('/api/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config, workout_index: idx })
  })
  .then(r => { if (!r.ok) throw new Error('Erro ' + r.status); return r.text(); })
  .then(html => {
    const blob = new Blob([html], { type: 'text/html' });
    const old = frame.src;
    frame.src = URL.createObjectURL(blob);
    if (old && old.startsWith('blob:')) URL.revokeObjectURL(old);
  })
  .catch(e => { toast('Erro no preview: ' + e.message, 'err'); });
}

// ═══════════════════════════════════════════════════════════════════
//  GENERATE ZIP
// ═══════════════════════════════════════════════════════════════════
function gerarZIP() {
  if (!config.workouts.length) return;
  const btn = document.getElementById('btnGerar');
  const lbl = document.getElementById('btnGerarLabel');
  const sub = document.getElementById('btnGerarSub');
  btn.disabled = true;
  btn.classList.add('generating');
  lbl.textContent = 'Gerando…';
  sub.textContent = 'Aguarde, montando o ZIP';

  fetch('/api/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config })
  })
  .then(r => { if (!r.ok) throw new Error('Falha na geração'); return r.blob(); })
  .then(blob => {
    const url = URL.createObjectURL(blob);
    const a   = document.createElement('a');
    a.href = url;
    const cat = (config.evento.categoria || config.evento.nome || 'sumulas').replace(/\s+/g, '_');
    a.download = `${cat}.zip`;
    a.click();
    URL.revokeObjectURL(url);
    const n = config.atletas.length
      ? config.workouts.length * config.atletas.length
      : config.workouts.length;
    toast(`${n} súmula(s) gerada(s) com sucesso!`, 'ok');
  })
  .catch(e => toast('Erro: ' + e.message, 'err'))
  .finally(() => {
    btn.disabled = false;
    btn.classList.remove('generating');
    atualizarBotaoGerar();
  });
}

// ═══════════════════════════════════════════════════════════════════
//  IMPORT
// ═══════════════════════════════════════════════════════════════════
function triggerImport(type) {
  document.getElementById(type === 'excel' ? 'fileExcel' : 'filePDF').click();
}

function handleImport(input, type) {
  const file = input.files[0];
  if (!file) return;
  input.value = '';
  toast('Importando…', 'info');

  const reader = new FileReader();
  reader.onload = e => {
    const b64 = e.target.result.split(',')[1];
    fetch('/api/import/' + type, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data: b64, filename: file.name })
    })
    .then(r => r.json())
    .then(result => {
      if (result.error) throw new Error(result.error);

      // ── Formato grade de categorias (Excel do evento real) ──
      if (result.tipo === 'categoria_grid') {
        mostrarSeletorCategoria(result); return;
      }

      // ── Formato simples ──
      aplicarImport(result);
    })
    .catch(e => toast('Erro ao importar: ' + e.message, 'err'));
  };
  reader.readAsDataURL(file);
}

function mostrarSeletorCategoria(data) {
  const cats = data.categorias || Object.keys(data.por_categoria || {});
  if (!cats.length) { toast('Nenhuma categoria encontrada no arquivo', 'err'); return; }

  // Cacheia o resultado pra permitir trocar de categoria depois sem reimportar.
  importedData = data;
  saveState();

  const sub = document.getElementById('catModalSub');
  sub.textContent = `${cats.length} categorias encontradas. Escolha qual gerar as súmulas:`;

  const grid = document.getElementById('catGrid');
  grid.innerHTML = '';
  cats.forEach(cat => {
    const btn = document.createElement('button');
    btn.className = 'cat-btn';
    const wkts = (data.por_categoria[cat] || []).length;
    const atl  = ((data.atletas_por_categoria || {})[cat] || []).length;
    const meta = atl ? `${wkts} wkt · ${atl} atl` : `${wkts} workout(s)`;
    btn.innerHTML = `<strong>${esc(cat)}</strong><br><span style="font-size:9px;opacity:.6">${meta}</span>`;
    btn.onclick = () => {
      document.getElementById('catModal').style.display = 'none';
      aplicarCategoria(cat);
    };
    grid.appendChild(btn);
  });
  document.getElementById('catModal').style.display = '';
}

function aplicarCategoria(cat) {
  if (!importedData) return;
  const workouts   = importedData.por_categoria[cat] || [];
  const atletasCat = (importedData.atletas_por_categoria || {})[cat] || [];
  config.evento.nome      = importedData.evento_nome || config.evento.nome || 'Sun2026';
  config.evento.categoria = cat;
  document.getElementById('evNome').value = config.evento.nome;
  document.getElementById('evCat').value  = cat;
  renderEventoDisplay();
  config.workouts = workouts;
  config.atletas  = atletasCat;
  previewIdx = workouts.length ? 0 : -1;
  renderWorkoutList();
  renderAtletasList();
  renderCategoriaSwitcher();
  atualizarBotaoGerar();
  updateClearAllVisibility();
  if (workouts.length) previewWorkout(0);
  else updateEmptyState();
  saveState();
  const msgAtletas = atletasCat.length ? ` · ${atletasCat.length} atleta(s)` : '';
  toast(`${cat} — ${workouts.length} workout(s)${msgAtletas}`, 'ok');
}

function reabrirSeletorCategoria() {
  if (!importedData) return;
  mostrarSeletorCategoria(importedData);
}

function aplicarImport(result) {
  if (result.evento && result.evento.nome) {
    config.evento = { ...config.evento, ...result.evento };
    document.getElementById('evNome').value = config.evento.nome || '';
    document.getElementById('evCat').value  = config.evento.categoria || '';
    document.getElementById('evData').value = config.evento.data || '';
    renderEventoDisplay();
  }
  if (result.workouts && result.workouts.length) {
    config.workouts = result.workouts;
    previewIdx = 0;
    renderWorkoutList();
    atualizarBotaoGerar();
    updateClearAllVisibility();
    previewWorkout(0);
    saveState();
    toast(`${result.workouts.length} workout(s) importado(s)`, 'ok');
  } else {
    toast('Nenhum workout encontrado no arquivo', 'err');
  }
}

// ═══════════════════════════════════════════════════════════════════
//  ATLETAS
// ═══════════════════════════════════════════════════════════════════
function renderAtletasList() {
  const sec  = document.getElementById('secAtletas');
  const list = document.getElementById('atletasList');
  const cnt  = document.getElementById('atlCount');
  const n = config.atletas.length;
  cnt.textContent = n;
  if (!n) {
    sec.style.display = 'none';
    list.innerHTML = '';
    return;
  }
  sec.style.display = '';

  // Agrupa por bateria (mantém ordem original — já vem ordenada do backend)
  const groups = {};
  const order  = [];
  config.atletas.forEach((a, i) => {
    const bat = (a.bateria || '—').toString().trim() || '—';
    if (!groups[bat]) { groups[bat] = []; order.push(bat); }
    groups[bat].push({ a, i });
  });

  list.innerHTML = order.map(bat => {
    const items = groups[bat];
    const rows = items.map(({ a, i }) => `
      <div class="atl-card">
        <span class="atl-raia">${esc(a.raia || '—')}</span>
        <span class="atl-nome" title="${esc((a.box || '') + (a.numero ? ' · #' + a.numero : ''))}">${esc(a.nome || '')}</span>
        <button class="atl-rm" onclick="removerAtleta(${i})" title="Remover atleta">×</button>
      </div>`).join('');
    return `
      <div class="atl-bat-group">
        <div class="atl-bat-hdr" onclick="toggleAtlGroup(this)">
          <span class="atl-bat-toggle">▾</span>
          <span class="atl-bat-name">Bateria ${esc(bat)}</span>
          <span class="atl-bat-count">${items.length}</span>
        </div>
        <div class="atl-bat-body">${rows}</div>
      </div>`;
  }).join('') + `<div class="atl-order-hint">Ordem de impressão: bateria → raia → nome</div>`;
}

function toggleAtlGroup(hdrEl) {
  hdrEl.parentElement.classList.toggle('collapsed');
}

function removerAtleta(idx) {
  const a = config.atletas[idx];
  if (!a) return;
  config.atletas.splice(idx, 1);
  renderAtletasList();
  atualizarBotaoGerar();
  saveState();
}

function limparAtletas() {
  if (!config.atletas.length) return;
  if (!confirm(`Remover todos os ${config.atletas.length} atletas?`)) return;
  config.atletas = [];
  renderAtletasList();
  atualizarBotaoGerar();
  saveState();
  toast('Atletas removidos', 'ok');
}

// ═══════════════════════════════════════════════════════════════════
//  CATEGORIA SWITCHER
// ═══════════════════════════════════════════════════════════════════
function renderCategoriaSwitcher() {
  const el = document.getElementById('catSwitcher');
  if (!importedData || !(importedData.categorias || []).length) {
    el.classList.remove('show');
    return;
  }
  const cats = importedData.categorias || Object.keys(importedData.por_categoria || {});
  if (cats.length < 2) {
    // Com 1 categoria só, switcher não agrega valor
    el.classList.remove('show');
    return;
  }
  document.getElementById('csName').textContent = config.evento.categoria || cats[0];
  document.getElementById('csMeta').textContent = `${cats.length} cat`;
  el.classList.add('show');
}

// ═══════════════════════════════════════════════════════════════════
//  EMPTY STATE / CLEAR
// ═══════════════════════════════════════════════════════════════════
function updateEmptyState() {
  const wrap     = document.getElementById('previewEmpty');
  const onboard  = document.getElementById('emptyOnboarding');
  const noSelect = document.getElementById('emptyNoSelection');
  const frame    = document.getElementById('previewFrame');
  // Se tem workout selecionado e iframe visível, não toca em nada
  if (frame.style.display === 'block') return;
  wrap.style.display = '';
  if (config.workouts.length === 0) {
    onboard.style.display  = 'flex';
    noSelect.style.display = 'none';
  } else {
    onboard.style.display  = 'none';
    noSelect.style.display = 'flex';
  }
}

function updateClearAllVisibility() {
  const btn = document.getElementById('btnClearAll');
  const hasData = config.workouts.length || config.atletas.length
    || config.evento.nome || importedData;
  btn.style.display = hasData ? '' : 'none';
}

function limparTudo() {
  if (!confirm('Apagar evento, workouts, atletas e categorias importadas?\nEsta ação não pode ser desfeita.')) return;
  config = {
    evento: { nome: "", categoria: "", data: "", logo_empresa: DS_LOGO_PADRAO, logo_evento: "" },
    workouts: [],
    atletas: []
  };
  importedData = null;
  previewIdx = -1;
  editingIdx = -1;
  clearState();
  // Reseta inputs do form de evento
  ['evNome','evCat','evData'].forEach(id => { const el=document.getElementById(id); if(el) el.value=''; });
  ['logoEventoPreview','logoEmpresaPreview'].forEach(id => {
    const el=document.getElementById(id); if(el){el.src=''; el.style.display='none';}
  });
  ['logoEventoPlaceholder','logoEmpresaPlaceholder'].forEach(id => {
    const el=document.getElementById(id); if(el) el.style.display='';
  });
  document.getElementById('eventoForm').style.display = 'none';
  document.getElementById('btnToggleEvento').textContent = 'Editar';
  document.getElementById('previewFrame').style.display = 'none';
  document.getElementById('pbName').textContent = '—';
  renderEventoDisplay();
  renderWorkoutList();
  renderAtletasList();
  renderCategoriaSwitcher();
  atualizarBotaoGerar();
  updateClearAllVisibility();
  updateEmptyState();
  toast('Tudo limpo', 'ok');
}

// ═══════════════════════════════════════════════════════════════════
//  PERSISTÊNCIA (localStorage)
// ═══════════════════════════════════════════════════════════════════
let _saveTimer = null;
function saveState() {
  clearTimeout(_saveTimer);
  _saveTimer = setTimeout(_persistNow, 400);
}

function _persistNow() {
  const snapshot = { config, previewIdx };
  try {
    localStorage.setItem(STATE_KEY, JSON.stringify(snapshot));
    if (importedData) localStorage.setItem(IMPORT_KEY, JSON.stringify(importedData));
    else              localStorage.removeItem(IMPORT_KEY);
  } catch (e) {
    // QuotaExceededError → tenta sem logos do evento (geralmente o mais pesado)
    try {
      const lite = JSON.parse(JSON.stringify(snapshot));
      lite.config.evento.logo_evento = '';
      lite.config.evento.logo_empresa = '';
      localStorage.setItem(STATE_KEY, JSON.stringify(lite));
      if (importedData) localStorage.setItem(IMPORT_KEY, JSON.stringify(importedData));
      console.warn('Persistência sem logos (cota cheia):', e.message);
    } catch (e2) {
      console.error('Falha ao persistir:', e2);
    }
  }
  updateClearAllVisibility();
}

function loadState() {
  try {
    const raw = localStorage.getItem(STATE_KEY);
    if (raw) {
      const snap = JSON.parse(raw);
      if (snap && snap.config) {
        // Garante que logo padrão DS sobrevive ao restaurar config sem logo
        if (!snap.config.evento.logo_empresa) snap.config.evento.logo_empresa = DS_LOGO_PADRAO;
        config = snap.config;
        previewIdx = (typeof snap.previewIdx === 'number') ? snap.previewIdx : -1;
      }
    }
    const rawImp = localStorage.getItem(IMPORT_KEY);
    if (rawImp) importedData = JSON.parse(rawImp);
  } catch (e) {
    console.warn('Falha ao restaurar estado:', e);
  }
}

function clearState() {
  try {
    localStorage.removeItem(STATE_KEY);
    localStorage.removeItem(IMPORT_KEY);
  } catch (e) { /* ignore */ }
}

// ═══════════════════════════════════════════════════════════════════
//  PREFERÊNCIAS DO EDITOR (coluna Label)
// ═══════════════════════════════════════════════════════════════════
function applyLabelColPref() {
  const show = localStorage.getItem(LABEL_COL_KEY) === '1';
  const chk  = document.getElementById('chkLabel');
  if (chk) chk.checked = show;
  document.getElementById('editor').classList.toggle('show-labels', show);
}

function toggleLabelCol() {
  const show = document.getElementById('chkLabel').checked;
  document.getElementById('editor').classList.toggle('show-labels', show);
  try { localStorage.setItem(LABEL_COL_KEY, show ? '1' : '0'); } catch (e) {}
}

// ═══════════════════════════════════════════════════════════════════
//  HELPERS
// ═══════════════════════════════════════════════════════════════════
function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function toast(msg, type = 'ok') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = `toast show ${type}`;
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('show'), 3000);
}

// ═══════════════════════════════════════════════════════════════════
//  INIT (no FIM do arquivo: garante que todos os `let`/`const` já foram
//  inicializados antes de loadState() / renderXxx() acessá-los)
// ═══════════════════════════════════════════════════════════════════
(function initApp() {
  fetch('/api/status').then(r=>r.json()).then(s => {
    if (s.ai_ativo) document.getElementById('aiBadge').style.display = '';
  }).catch(()=>{});
  loadState();
  applyLabelColPref();
  renderEventoDisplay();
  renderWorkoutList();
  renderAtletasList();
  renderCategoriaSwitcher();
  updateClearAllVisibility();
  atualizarBotaoGerar();
  updateEmptyState();
  // Se restaurou um workout selecionado, renderiza preview
  if (previewIdx >= 0 && previewIdx < config.workouts.length) {
    previewWorkout(previewIdx);
  }
})();
