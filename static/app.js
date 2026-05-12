// ═══════════════════════════════════════════════════════════════════
//  STATE
// ═══════════════════════════════════════════════════════════════════
// Shape novo (multi-dia):
//   config = {
//     evento: { nome, categoria, data, logo_empresa, logo_evento },
//     dias: [{ label, categorias: [{ nome, workouts, baterias }] }],
//     roster: [{ numero, nome, box }, ...]
//   }
// Modelo legado (categoria_grid, template) é convertido pelo backend pra esse
// mesmo shape no momento do import — frontend só conhece esse formato.
let config = {
  evento: { nome: "", categoria: "", data: "", logo_empresa: DS_LOGO_PADRAO, logo_evento: "" },
  dias: [],
  roster: [],
};
let diaAtual    = 0;       // índice na config.dias
let catSel      = 0;       // categoria selecionada (índice em dias[diaAtual].categorias)
let catListOpen = false;   // dropdown de seleção de categoria aberto?
let editingPath = null;    // {dia, cat, wkt} quando editando (criar = wkt = -1)
let previewPath = null;    // {dia, cat, wkt} do workout em preview

const STATE_KEY      = 'ds_sumulas_v2_state';
const IMPORT_KEY     = 'ds_sumulas_v2_import';
const LABEL_COL_KEY  = 'ds_sumulas_v2_show_label';
// Bump quando mudar shape de `config`. State antigo (v1) é descartado.
const SCHEMA_VERSION = 2;

const TIPO_LABEL = { for_time: 'For Time', amrap: 'AMRAP', express: 'Express' };

// Helpers de navegação
function diaCorrente() {
  return (config.dias && config.dias[diaAtual]) || null;
}
function categoriasDoDia() {
  const d = diaCorrente();
  return (d && d.categorias) || [];
}
function temDados() {
  return (config.dias || []).some(d => (d.categorias || []).length > 0);
}

// ═══════════════════════════════════════════════════════════════════
//  CONFIG MODAL (Evento + Dias + Importar — tudo num lugar só)
// ═══════════════════════════════════════════════════════════════════
function abrirConfig(tab) {
  document.getElementById('configModal').style.display = '';
  // Popula form do evento
  document.getElementById('evNome').value = config.evento.nome || '';
  document.getElementById('evCat').value  = config.evento.categoria || '';
  document.getElementById('evData').value = config.evento.data || '';
  // Logos
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
  renderDiasEditor();
  cfgTab(tab || 'evento');
}

function fecharConfig() {
  document.getElementById('configModal').style.display = 'none';
}

function cfgTab(tab) {
  document.querySelectorAll('.cfg-tab').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  ['evento','dias','importar'].forEach(t => {
    const pane = document.getElementById('cfgPane' + t.charAt(0).toUpperCase() + t.slice(1));
    if (pane) pane.style.display = (t === tab) ? '' : 'none';
  });
}

// Limpar tudo a partir do modal (chama a função existente e fecha o modal)
function limparTudoModal() {
  if (!confirm('Apagar evento, dias, categorias e workouts? Esta ação não pode ser desfeita.')) return;
  fecharConfig();
  // Reuso da limparTudo sem o seu confirm próprio (já confirmamos aqui)
  config = {
    evento: { nome: "", categoria: "", data: "", logo_empresa: DS_LOGO_PADRAO, logo_evento: "" },
    dias: [],
    roster: [],
  };
  diaAtual = 0;
  catSel = 0; catListOpen = false;
  previewPath = null;
  editingPath = null;
  clearState();
  ['evNome','evCat','evData'].forEach(id => { const el=document.getElementById(id); if(el) el.value=''; });
  ['logoEventoPreview','logoEmpresaPreview'].forEach(id => {
    const el=document.getElementById(id); if(el){el.src=''; el.style.display='none';}
  });
  ['logoEventoPlaceholder','logoEmpresaPlaceholder'].forEach(id => {
    const el=document.getElementById(id); if(el) el.style.display='';
  });
  document.getElementById('previewFrame').style.display = 'none';
  document.getElementById('pbName').textContent = '—';
  renderEventoDisplay();
  renderDiaTabs();
  renderCategoriasList();
  atualizarBotaoGerar();
  updateEmptyState();
  toast('Tudo limpo', 'ok');
}

// Banner pós-import
function dispensarBanner() {
  document.getElementById('postImportBanner').style.display = 'none';
}
function mostrarBannerPosImport(msg) {
  const banner = document.getElementById('postImportBanner');
  document.getElementById('pibMsg').textContent = msg;
  banner.style.display = '';
}

// ═══════════════════════════════════════════════════════════════════
//  IA / Helpers — sugestão de time cap, geração de descrição, validação
// ═══════════════════════════════════════════════════════════════════
function sugerirTimeCap() {
  const tipo = document.getElementById('edTipo').value;
  // Movimentos do contexto atual (main pra for_time/amrap; f1+f2 pra express)
  let movs = [];
  if (tipo === 'express') {
    movs = getMovTableArray('f1').concat(getMovTableArray('f2'));
  } else {
    movs = getMovTableArray('main');
  }
  fetch('/api/ai/sugerir-time-cap', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ movimentos: movs, tipo })
  }).then(r => r.json()).then(res => {
    if (res.error) throw new Error(res.error);
    document.getElementById('edTimeCap').value = res.time_cap;
    toast(`Time cap sugerido: ${res.time_cap}`, 'ok');
  }).catch(e => toast('Erro: ' + e.message, 'err'));
}

function gerarDescricao() {
  const tipo = document.getElementById('edTipo').value;
  const wkt = {
    nome: document.getElementById('edNome').value.trim(),
    tipo,
    time_cap: document.getElementById('edTimeCap').value.trim(),
    movimentos: tipo === 'express' ? [] : getMovTableArray('main'),
  };
  fetch('/api/ai/auto-descricao', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ workout: wkt })
  }).then(r => r.json()).then(res => {
    if (res.error) throw new Error(res.error);
    const linhas = res.descricao || [];
    document.getElementById('edDescricao').value = linhas.join('\n');
    toast(`${linhas.length} linha(s) gerada(s)`, 'ok');
  }).catch(e => toast('Erro: ' + e.message, 'err'));
}

// ═══════════════════════════════════════════════════════════════════
//  Chat assistente
// ═══════════════════════════════════════════════════════════════════
let chatOpen = false;
let chatHistory = [];     // histórico {role: 'user'|'assistant', content: '...'}
let chatAIAtiva = false;  // sabido após /api/status

function toggleChat() {
  chatOpen = !chatOpen;
  document.getElementById('chatPanel').style.display = chatOpen ? '' : 'none';
  if (chatOpen) {
    if (!chatAIAtiva) {
      document.getElementById('chatFooterInfo').style.display = '';
      document.getElementById('chatInput').disabled = true;
      document.getElementById('chatSend').disabled = true;
    }
    document.getElementById('chatInput').focus();
  }
}

function enviarChat() {
  const input = document.getElementById('chatInput');
  const txt = input.value.trim();
  if (!txt) return;
  if (!chatAIAtiva) { toast('IA inativa — configure ANTHROPIC_API_KEY', 'err'); return; }
  appendChatMsg('user', txt);
  input.value = '';
  chatHistory.push({ role: 'user', content: txt });
  appendChatMsg('bot', 'pensando…', true);

  fetch('/api/ai/chat', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ messages: chatHistory, config })
  }).then(r => r.json()).then(res => {
    removerThinking();
    if (res.error) {
      appendChatMsg('bot', 'Erro: ' + res.error);
      return;
    }
    const resposta = res.resposta || '(sem resposta)';
    chatHistory.push({ role: 'assistant', content: resposta });
    appendChatMsg('bot', resposta);
  }).catch(e => {
    removerThinking();
    appendChatMsg('bot', 'Erro: ' + e.message);
  });
}

function appendChatMsg(quem, texto, thinking) {
  const msgs = document.getElementById('chatMsgs');
  const div = document.createElement('div');
  div.className = quem === 'user' ? 'chat-msg-user' : 'chat-msg-bot';
  if (thinking) div.classList.add('thinking');
  div.textContent = texto;
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
}

function removerThinking() {
  const msgs = document.getElementById('chatMsgs');
  const last = msgs.querySelector('.chat-msg-bot.thinking');
  if (last) last.remove();
}

function abrirValidacao() {
  document.getElementById('validModal').style.display = '';
  document.getElementById('validacaoStatus').textContent = 'Analisando…';
  document.getElementById('validacaoLista').innerHTML = '';
  fetch('/api/ai/validar-evento', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ config })
  }).then(r => r.json()).then(res => {
    if (res.error) throw new Error(res.error);
    const avisos = res.avisos || [];
    const status = document.getElementById('validacaoStatus');
    const lista  = document.getElementById('validacaoLista');
    if (!avisos.length) {
      status.innerHTML = '<strong style="color:var(--green)">✓ Nenhum problema encontrado.</strong>';
      lista.innerHTML = '';
      return;
    }
    const erros = avisos.filter(a => a.severidade === 'erro');
    const aviso = avisos.filter(a => a.severidade === 'aviso');
    status.innerHTML = `${erros.length} erro${erros.length !== 1 ? 's' : ''}, ${aviso.length} aviso${aviso.length !== 1 ? 's' : ''}.`;
    lista.innerHTML = avisos.map(a => `
      <div class="valid-row valid-${a.severidade}">
        <span class="valid-icon">${a.severidade === 'erro' ? '✗' : '⚠'}</span>
        <div class="valid-body">
          <div class="valid-msg">${esc(a.msg)}</div>
          <div class="valid-onde">${esc(a.onde || '')}</div>
        </div>
      </div>`).join('');
  }).catch(e => {
    document.getElementById('validacaoStatus').textContent = 'Erro: ' + e.message;
  });
}

function fecharValidacao() {
  document.getElementById('validModal').style.display = 'none';
}

// Atualiza o banner pós-import com resumo curto + botão validar
function atualizarBannerPosImport() {
  if (!temDados()) return;
  fetch('/api/ai/resumo-evento', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ config })
  }).then(r => r.json()).then(res => {
    if (res.resumo) document.getElementById('pibMsg').textContent = res.resumo + ' Configure as datas pra aparecerem nas súmulas.';
  }).catch(()=>{});
}

// Toggle de "outras opções" no rodapé
function toggleMaisOpcoes() {
  const wrap = document.getElementById('gerarMaisOpcoes');
  const btn  = document.getElementById('btnMaisOpcoes');
  const open = wrap.style.display === 'none';
  wrap.style.display = open ? '' : 'none';
  if (btn) btn.textContent = open ? 'menos escopos ▴' : 'outros escopos ▾';
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
  if (previewPath) previewWorkoutByPath(previewPath);
}

function renderDiasEditor() {
  const list = document.getElementById('diasEditorList');
  if (!list) return;
  const dias = config.dias || [];
  if (!dias.length) {
    list.innerHTML = '<p class="cfg-hint" style="font-style:italic">Nenhum dia configurado. Clique em <b>+ Adicionar dia</b> abaixo ou importe um Excel.</p>';
    return;
  }
  list.innerHTML = dias.map((d, i) => `
    <div class="dia-edit-row">
      <input class="dia-edit-label" type="text" placeholder="Rótulo (ex: Sexta)" value="${esc(d.label || '')}" oninput="onDiaLabelChange(${i}, this.value)">
      <input class="dia-edit-data" type="date" value="${esc(d.data_iso || '')}" oninput="onDiaDataChange(${i}, this.value)" title="Data do dia">
      <button class="icon-btn danger" onclick="removerDia(${i})" title="Remover dia">×</button>
    </div>`).join('');
}

function adicionarDia() {
  config.dias = config.dias || [];
  const n = config.dias.length + 1;
  config.dias.push({ label: `Dia ${n}`, data: '', data_iso: '', categorias: [] });
  renderDiasEditor();
  renderDiaTabs();
  renderCategoriasList();
  atualizarBotaoGerar();
  updateClearAllVisibility();
  saveState();
}

function removerDia(idx) {
  if (!config.dias || idx < 0 || idx >= config.dias.length) return;
  const d = config.dias[idx];
  const totalCats = (d.categorias || []).length;
  const msg = totalCats
    ? `Remover dia "${d.label}" com ${totalCats} categoria(s)?`
    : `Remover dia "${d.label}"?`;
  if (!confirm(msg)) return;
  config.dias.splice(idx, 1);
  // Ajusta diaAtual se ficou fora do range
  if (diaAtual >= config.dias.length) diaAtual = Math.max(0, config.dias.length - 1);
  catSel = 0; catListOpen = false;
  previewPath = null;
  renderDiasEditor();
  renderDiaTabs();
  renderCategoriasList();
  atualizarBotaoGerar();
  updateClearAllVisibility();
  document.getElementById('previewFrame').style.display = 'none';
  document.getElementById('pbName').textContent = '—';
  updateEmptyState();
  saveState();
}

function onDiaLabelChange(i, val) {
  if (config.dias && config.dias[i]) {
    config.dias[i].label = val.trim();
    renderDiaTabs();
    saveState();
    refreshPreview();
  }
}

function onDiaDataChange(i, val) {
  if (config.dias && config.dias[i]) {
    // Input type=date entrega ISO (YYYY-MM-DD); guardamos as duas formas:
    //  data_iso → re-popular o picker; data → formato BR mostrado na súmula
    const iso = (val || '').trim();
    config.dias[i].data_iso = iso;
    config.dias[i].data = formatarDataBR(iso);
    saveState();
    refreshPreview();
  }
}

function formatarDataBR(iso) {
  if (!iso) return '';
  const m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})$/);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : iso;
}

function renderEventoDisplay() {
  // Atualiza o nome do evento no header (ao lado de "Digital Score")
  const hdr = document.getElementById('hdrEvento');
  if (hdr) {
    hdr.textContent = config.evento.nome
      ? `Digital Score · ${config.evento.nome}`
      : 'Digital Score';
  }
}

// ═══════════════════════════════════════════════════════════════════
//  DAY TABS (header)
// ═══════════════════════════════════════════════════════════════════
function renderDiaTabs() {
  const wrap = document.getElementById('diaTabs');
  if (!wrap) return;
  const dias = config.dias || [];
  // Botão "+" no header — sempre disponível quando o evento foi inicializado
  const btnAddDia = document.getElementById('hdrAddDia');
  if (btnAddDia) btnAddDia.classList.toggle('show', dias.length > 0);

  // Tabs só fazem sentido com 2+ dias
  if (dias.length < 2) {
    wrap.classList.remove('show');
    wrap.innerHTML = '';
    return;
  }
  wrap.classList.add('show');
  wrap.innerHTML = dias.map((d, i) => {
    const dataShort = d.data ? String(d.data).slice(0, 5) : '';
    return `<button class="dia-tab${i === diaAtual ? ' active' : ''}" onclick="selectDia(${i})">
      ${esc(d.label || `Dia ${i + 1}`)}${dataShort ? `<span class="dia-tab-date">${esc(dataShort)}</span>` : ''}
    </button>`;
  }).join('');
}

function selectDia(idx) {
  if (idx === diaAtual) return;
  diaAtual = idx;
  catSel = 0; catListOpen = false;
  previewPath = null;
  renderDiaTabs();
  renderCategoriasList();
  atualizarBotaoGerar();
  document.getElementById('previewFrame').style.display = 'none';
  document.getElementById('pbName').textContent = '—';
  updateEmptyState();
  saveState();
}

// ═══════════════════════════════════════════════════════════════════
//  CATEGORIAS (sidebar do dia atual)
// ═══════════════════════════════════════════════════════════════════
function renderCategoriasList() {
  const wrap   = document.getElementById('catSelWrap');
  const btnSel = document.getElementById('catSelBtn');
  const list   = document.getElementById('catSelList');
  const el     = document.getElementById('categoriasList');
  if (!el) return;
  const cats = categoriasDoDia();

  // Atualiza header da sidebar com nome do dia ativo
  const hdrTitle = document.getElementById('categoriasHdrTitle');
  if (hdrTitle) {
    const dia = diaCorrente();
    hdrTitle.textContent = dia
      ? `Categoria · ${dia.label || 'Dia'}${dia.data ? ' ' + String(dia.data).slice(0, 5) : ''}`
      : 'Categoria';
  }
  const btnAddCat = document.getElementById('btnAddCat');
  if (btnAddCat) btnAddCat.style.display = (config.dias && config.dias.length) ? '' : 'none';

  if (!cats.length) {
    if (wrap) wrap.style.display = 'none';
    el.innerHTML = '<div class="cat-empty">Sem categorias neste dia.<br>Importe um Excel ou clique no <b>+</b> acima pra adicionar.</div>';
    return;
  }

  // Garante que catSel é válido
  if (catSel < 0 || catSel >= cats.length) catSel = 0;
  const catAtiva = cats[catSel];

  // Header do seletor (sempre visível): nome + posição (i/N) + arrow
  if (wrap) wrap.style.display = '';
  if (btnSel) {
    btnSel.classList.toggle('open', catListOpen);
    const nWkts = (catAtiva.workouts || []).length;
    const nBat  = (catAtiva.baterias || []).length;
    const nAlocs = (catAtiva.baterias || []).reduce((s, b) => s + (b.alocacoes || []).length, 0);
    document.getElementById('catSelName').textContent = catAtiva.nome;
    // Indicador de posição: "1/9" só aparece quando há mais de 1 categoria
    const posicao = cats.length > 1 ? ` · ${catSel + 1}/${cats.length}` : '';
    const counts = `${nWkts} wkt${nWkts !== 1 ? 's' : ''}${nBat ? ` · ${nBat} bat · ${nAlocs} comp` : ''}`;
    document.getElementById('catSelMeta').textContent = counts + posicao;
  }

  // Dropdown: lista todas as categorias do dia (rola se for muita)
  if (list) {
    list.style.display = catListOpen ? '' : 'none';
    if (catListOpen) {
      list.innerHTML = cats.map((cat, ci) => {
        const nW = (cat.workouts || []).length;
        const nB = (cat.baterias || []).length;
        const nA = (cat.baterias || []).reduce((s, b) => s + (b.alocacoes || []).length, 0);
        return `
        <div class="cat-sel-item${ci === catSel ? ' selected' : ''}" onclick="selecionarCategoria(${ci})">
          <span class="cat-sel-item-nome">${esc(cat.nome)}</span>
          <span class="cat-sel-item-meta">${nW}w${nB ? ` · ${nA}c` : ''}</span>
          <button class="cat-sel-item-rm" onclick="event.stopPropagation();removerCategoria(${ci})" title="Remover">×</button>
        </div>`;
      }).join('');
    }
  }

  // Detalhe da categoria selecionada (workouts + baterias)
  el.innerHTML = `<div class="cat-detail">${renderCategoriaDetalhe(catAtiva, catSel)}</div>`;
}

function toggleCatList() {
  catListOpen = !catListOpen;
  renderCategoriasList();
}

function selecionarCategoria(ci) {
  catSel = ci;
  catListOpen = false;
  renderCategoriasList();
}

function adicionarCategoria() {
  const dia = diaCorrente();
  if (!dia) {
    if (!config.dias || !config.dias.length) {
      adicionarDia();
      // Tenta de novo após criar o dia
      return setTimeout(adicionarCategoria, 50);
    }
    return;
  }
  const nome = prompt('Nome da categoria:', '');
  if (!nome || !nome.trim()) return;
  dia.categorias = dia.categorias || [];
  dia.categorias.push({ nome: nome.trim(), workouts: [], baterias: [] });
  catSel = dia.categorias.length - 1; catListOpen = false;
  renderCategoriasList();
  atualizarBotaoGerar();
  updateClearAllVisibility();
  saveState();
}

function removerCategoria(ci) {
  const dia = diaCorrente();
  if (!dia || !dia.categorias || ci < 0 || ci >= dia.categorias.length) return;
  const cat = dia.categorias[ci];
  const nWkts = (cat.workouts || []).length;
  const nBat  = (cat.baterias || []).length;
  const detalhes = (nWkts || nBat) ? ` (${nWkts} workout${nWkts !== 1 ? 's' : ''}${nBat ? `, ${nBat} bateria${nBat !== 1 ? 's' : ''}` : ''})` : '';
  if (!confirm(`Remover categoria "${cat.nome}"${detalhes}?`)) return;
  dia.categorias.splice(ci, 1);
  catSel = 0; catListOpen = false;
  if (previewPath && previewPath.dia === diaAtual && previewPath.cat === ci) {
    previewPath = null;
    document.getElementById('previewFrame').style.display = 'none';
    document.getElementById('pbName').textContent = '—';
    updateEmptyState();
  }
  renderCategoriasList();
  atualizarBotaoGerar();
  updateClearAllVisibility();
  saveState();
}

function renderCategoriaDetalhe(cat, ci) {
  const workouts = cat.workouts || [];
  const baterias = cat.baterias || [];

  const workoutsHtml = workouts.length
    ? workouts.map((w, wi) => {
        const isActive = previewPath && previewPath.dia === diaAtual && previewPath.cat === ci && previewPath.wkt === wi;
        const tipoLabel = TIPO_LABEL[w.tipo] || w.tipo;
        return `
        <div class="wkt-row${isActive ? ' active' : ''}" onclick="selectWorkout(${ci}, ${wi})">
          <div class="wkt-row-num">${wi + 1}</div>
          <div class="wkt-row-info">
            <div class="wkt-row-nome">${esc(w.nome || '—')}</div>
            <div class="wkt-row-tags"><span class="tag ${w.tipo}">${esc(tipoLabel)}</span>${w.time_cap ? ` <span class="tag">${esc(w.time_cap)}</span>` : ''}${w.arena ? ` <span class="tag">${esc(w.arena)}</span>` : ''}</div>
          </div>
          <div class="wkt-row-actions">
            <button class="icon-btn" onclick="event.stopPropagation();editarWorkout(${ci}, ${wi})" title="Editar">✎</button>
            <button class="icon-btn danger" onclick="event.stopPropagation();deletarWorkout(${ci}, ${wi})" title="Excluir">×</button>
          </div>
        </div>`;
      }).join('')
    : '<div class="cat-empty-inner">Sem workouts nesta categoria.</div>';

  const bateriasHtml = baterias.length
    ? baterias.map(b => {
        const codigo = b.codigo_evento || '—';
        const aq = b.horario_aquecimento || '';
        const fila = b.horario_fila || '';
        const horarios = aq || fila ? `${aq}${aq && fila ? ' / ' : ''}${fila}` : '';
        const nAlocs = (b.alocacoes || []).length;
        return `
        <div class="bat-row">
          <div class="bat-row-num">#${esc(b.numero)}</div>
          <div class="bat-row-info">
            <div class="bat-row-codigo">${esc(codigo)}${horarios ? ' · ' + horarios : ''}</div>
            <div class="bat-row-meta">${nAlocs} competidor${nAlocs !== 1 ? 'es' : ''}${nAlocs ? ' · raias ' + (b.alocacoes || []).map(a => a.raia).join(', ') : ''}</div>
          </div>
        </div>`;
      }).join('')
    : '<div class="cat-empty-inner">Sem baterias.</div>';

  return `
    <div class="cat-body">
      <div class="cat-section-hdr">Workouts</div>
      ${workoutsHtml}
      <div class="cat-actions"><button class="btn-mov" onclick="novoWorkout(${ci})">+ Novo workout</button></div>
      ${baterias.length ? '<div class="cat-section-hdr" style="margin-top:10px">Baterias</div>' + bateriasHtml : ''}
    </div>`;
}


function selectWorkout(ci, wi) {
  previewPath = { dia: diaAtual, cat: ci, wkt: wi };
  renderCategoriasList();
  previewWorkoutByPath(previewPath);
}

function _contagemPaginas(escopo, competidoresOn) {
  const dias = config.dias || [];
  let total = 0;
  for (let i = 0; i < dias.length; i++) {
    if (escopo === 'dia' && i !== diaAtual) continue;
    if (escopo === 'cat' && i !== diaAtual) continue;
    const cats = dias[i].categorias || [];
    for (let ci = 0; ci < cats.length; ci++) {
      if (escopo === 'cat' && ci !== catSel) continue;
      const cat = cats[ci];
      const nW = (cat.workouts || []).length;
      const nA = (cat.baterias || []).reduce((s, b) => s + (b.alocacoes || []).length, 0);
      total += competidoresOn && nA ? nW * nA : nW;
    }
  }
  return total;
}

function atualizarBotaoGerar() {
  const btnEv  = document.getElementById('btnGerarEvento');
  const btnDi  = document.getElementById('btnGerarDia');
  const btnCt  = document.getElementById('btnGerarCat');
  const subEv  = document.getElementById('bgeSubEvento');
  const subDi  = document.getElementById('bgeSubDia');
  const subCt  = document.getElementById('bgeSubCat');
  if (!btnEv || !btnDi || !btnCt) return;

  const dias = config.dias || [];
  const totalWkts = dias.reduce((sum, d) =>
    sum + (d.categorias || []).reduce((s, c) => s + (c.workouts || []).length, 0), 0);
  const incluir = document.getElementById('chkIncluirCompetidores');
  const compOn = !incluir || incluir.checked;

  // Botão "Evento todo"
  btnEv.disabled = totalWkts === 0;
  const nEvt = _contagemPaginas('evento', compOn);
  subEv.textContent = totalWkts === 0
    ? 'importe um Excel pra começar'
    : `${nEvt} página${nEvt !== 1 ? 's' : ''} · ${dias.length} dia${dias.length !== 1 ? 's' : ''}${compOn ? '' : ' · sem competidores'}`;

  // Botão "Dia atual"
  const diaCur = dias[diaAtual];
  btnDi.disabled = !diaCur || (diaCur.categorias || []).length === 0;
  const nDia = _contagemPaginas('dia', compOn);
  subDi.textContent = !diaCur ? 'sem dia ativo'
    : `${nDia} página${nDia !== 1 ? 's' : ''} · ${diaCur.label || 'dia atual'}${compOn ? '' : ' · sem competidores'}`;

  // Botão "Categoria selecionada" (primário) — usa catSel atual
  const dia = dias[diaAtual];
  const cat = dia && (dia.categorias || [])[catSel];
  btnCt.disabled = !cat || (cat.workouts || []).length === 0;
  if (!cat) {
    subCt.textContent = 'sem categoria';
  } else {
    const nCat = _contagemPaginas('cat', compOn);
    subCt.textContent = `${nCat} página${nCat !== 1 ? 's' : ''} · ${cat.nome}${compOn ? '' : ' · sem competidores'}`;
  }
}

function gerarZIPEscopo(escopo) {
  const totalWkts = (config.dias || []).reduce((sum, d) =>
    sum + (d.categorias || []).reduce((s, c) => s + (c.workouts || []).length, 0), 0);
  if (!totalWkts) return;

  const incluir = document.getElementById('chkIncluirCompetidores');
  const incluirOn = !incluir || incluir.checked;
  const payload = { config, incluir_competidores: incluirOn };
  if (escopo === 'dia') {
    payload.dia_idx = diaAtual;
  } else if (escopo === 'cat') {
    const dia = (config.dias || [])[diaAtual];
    if (!dia || !dia.categorias || !dia.categorias[catSel]) {
      toast('Sem categoria selecionada', 'err'); return;
    }
    payload.dia_idx = diaAtual;
    payload.cat_idx = catSel;
  }

  const btnId = escopo === 'evento' ? 'btnGerarEvento'
              : escopo === 'dia'    ? 'btnGerarDia'
              : 'btnGerarCat';
  const btn = document.getElementById(btnId);
  const subId = escopo === 'evento' ? 'bgeSubEvento'
              : escopo === 'dia'    ? 'bgeSubDia'
              : 'bgeSubCat';
  const subEl = document.getElementById(subId);
  const subTextOriginal = subEl ? subEl.textContent : '';
  ['btnGerarEvento','btnGerarDia','btnGerarCat'].forEach(id => {
    const b = document.getElementById(id); if (b) b.disabled = true;
  });
  if (subEl) subEl.textContent = 'gerando…';
  if (btn) btn.classList.add('generating');

  fetch('/api/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
  .then(r => { if (!r.ok) throw new Error('Falha na geração'); return r.blob(); })
  .then(blob => {
    const url = URL.createObjectURL(blob);
    const a   = document.createElement('a');
    a.href = url;
    const baseName = (config.evento.nome || 'sumulas').replace(/\s+/g, '_');
    let sufixo = '';
    if (escopo === 'dia') sufixo = `_${(config.dias[diaAtual] || {}).label || 'dia'}`;
    else if (escopo === 'cat') {
      const c = ((config.dias[diaAtual] || {}).categorias || [])[catSel];
      sufixo = c ? `_${c.nome.replace(/\s+/g, '_')}` : '';
    }
    a.download = `${baseName}${sufixo}.zip`;
    a.click();
    URL.revokeObjectURL(url);
    toast('ZIP gerado com sucesso!', 'ok');
  })
  .catch(e => toast('Erro: ' + e.message, 'err'))
  .finally(() => {
    if (btn) btn.classList.remove('generating');
    if (subEl) subEl.textContent = subTextOriginal;
    atualizarBotaoGerar();
  });
}

// Compat: gerarZIP() ainda existe pro botão antigo (caso ainda referenciado)
function gerarZIP() { gerarZIPEscopo('evento'); }

// ═══════════════════════════════════════════════════════════════════
//  EDITOR
// ═══════════════════════════════════════════════════════════════════
function populateEditorPathSelects(diaIdx, catIdx) {
  const dias = config.dias || [];
  const selDia = document.getElementById('edDia');
  const selCat = document.getElementById('edCat');
  selDia.innerHTML = dias.map((d, i) =>
    `<option value="${i}">${esc(d.label || `Dia ${i + 1}`)}</option>`
  ).join('') || '<option value="0">—</option>';
  selDia.value = String(diaIdx);
  populateEditorCatSelect(diaIdx, catIdx);
}

function populateEditorCatSelect(diaIdx, catIdx) {
  const dia = (config.dias || [])[diaIdx];
  const cats = (dia && dia.categorias) || [];
  const selCat = document.getElementById('edCat');
  selCat.innerHTML = cats.map((c, i) =>
    `<option value="${i}">${esc(c.nome)}</option>`
  ).join('') || '<option value="0">—</option>';
  if (catIdx !== undefined && catIdx !== null && catIdx >= 0 && catIdx < cats.length) {
    selCat.value = String(catIdx);
  }
}

function onEditorDiaChange() {
  const diaIdx = parseInt(document.getElementById('edDia').value, 10);
  populateEditorCatSelect(diaIdx, 0);
}

function novoWorkout(catIdx) {
  const cats = categoriasDoDia();
  if (catIdx === undefined || catIdx === null) {
    if (cats.length === 0) {
      toast('Crie ou importe uma categoria primeiro', 'err');
      return;
    }
    if (cats.length === 1) catIdx = 0;
    else { toast('Expanda uma categoria e clique em "+ Novo workout"', 'err'); return; }
  }
  editingPath = { dia: diaAtual, cat: catIdx, wkt: -1 };  // -1 = novo
  document.getElementById('edTitle').textContent = `Novo Workout · ${cats[catIdx].nome}`;
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
  populateEditorPathSelects(diaAtual, catIdx);
  onTipoChange();
  abrirEditor();
}

function editarWorkout(ci, wi) {
  const cats = categoriasDoDia();
  const w = cats[ci] && cats[ci].workouts[wi];
  if (!w) return;
  editingPath = { dia: diaAtual, cat: ci, wkt: wi };
  document.getElementById('edTitle').textContent = `Workout ${wi + 1} · ${esc(cats[ci].nome)}`;
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
  populateEditorPathSelects(diaAtual, ci);
  onTipoChange();
  abrirEditor();
}

function abrirEditor() {
  document.getElementById('editor').classList.add('open');
}

function fecharEditor() {
  document.getElementById('editor').classList.remove('open');
  editingPath = null;
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

// Janela estruturada (start/end mm:ss) ↔ string canônica
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
  if (!editingPath) return;
  const nome = document.getElementById('edNome').value.trim().toUpperCase();
  if (!nome) { toast('Digite o nome do workout', 'err'); return; }
  const tipo = document.getElementById('edTipo').value;
  const timeCap = document.getElementById('edTimeCap').value.trim();
  const desc = document.getElementById('edDescricao').value.split('\n').map(s=>s.trim()).filter(Boolean);

  // Path destino lido dos selects (pode ter mudado durante a edição)
  const novoDia = parseInt(document.getElementById('edDia').value, 10);
  const novaCat = parseInt(document.getElementById('edCat').value, 10);
  if (isNaN(novoDia) || isNaN(novaCat)) { toast('Selecione dia e categoria', 'err'); return; }
  const catDestino = (config.dias[novoDia] && config.dias[novoDia].categorias[novaCat]) || null;
  if (!catDestino) { toast('Categoria de destino inválida', 'err'); return; }
  catDestino.workouts = catDestino.workouts || [];

  let wkt;
  const moveu = editingPath.wkt >= 0
    && (editingPath.dia !== novoDia || editingPath.cat !== novaCat);

  if (editingPath.wkt >= 0 && !moveu) {
    // Edição in-place
    wkt = config.dias[editingPath.dia].categorias[editingPath.cat].workouts[editingPath.wkt];
  } else if (moveu) {
    // Move workout: tira da posição original e empurra na destino
    const origem = config.dias[editingPath.dia].categorias[editingPath.cat];
    wkt = origem.workouts.splice(editingPath.wkt, 1)[0];
    catDestino.workouts.push(wkt);
    editingPath = { dia: novoDia, cat: novaCat, wkt: catDestino.workouts.length - 1 };
  } else {
    // Workout novo
    wkt = { numero: 0, modalidade: 'individual' };
    catDestino.workouts.push(wkt);
    editingPath = { dia: novoDia, cat: novaCat, wkt: catDestino.workouts.length - 1 };
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
    wkt.formula1 = { janela: buildJanelaAmrap(f1Start, f1End), descricao: [], movimentos: getMovTableArray('f1') };
    wkt.formula2 = { janela: buildJanelaForTime(f2Start, f2End), descricao: [], movimentos: getMovTableArray('f2') };
    delete wkt.movimentos;
  } else {
    wkt.movimentos = getMovTableArray('main');
    delete wkt.formula1;
    delete wkt.formula2;
  }

  previewPath = { dia: editingPath.dia, cat: editingPath.cat, wkt: editingPath.wkt };
  fecharEditor();
  // Se mudou de dia, atualiza o dia ativo e expande a categoria destino
  if (diaAtual !== previewPath.dia) {
    diaAtual = previewPath.dia;
    catSel = 0; catListOpen = false;
    renderDiaTabs();
  }
  catSel = previewPath.cat; catListOpen = false;
  renderCategoriasList();
  atualizarBotaoGerar();
  updateClearAllVisibility();
  previewWorkoutByPath(previewPath);
  saveState();
  toast(moveu ? 'Workout movido!' : 'Workout salvo!', 'ok');
}

function deletarWorkout(ci, wi) {
  const cat = categoriasDoDia()[ci];
  if (!cat) return;
  const w = cat.workouts[wi];
  if (!w) return;
  if (!confirm(`Excluir workout "${w.nome}"?`)) return;
  cat.workouts.splice(wi, 1);
  if (previewPath && previewPath.cat === ci && previewPath.wkt === wi) {
    previewPath = null;
    document.getElementById('previewFrame').style.display = 'none';
    document.getElementById('pbName').textContent = '—';
    updateEmptyState();
  }
  renderCategoriasList();
  atualizarBotaoGerar();
  updateClearAllVisibility();
  saveState();
}

// ═══════════════════════════════════════════════════════════════════
//  MOVEMENTS TABLE
// ═══════════════════════════════════════════════════════════════════
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
      <input class="mi-label" value="${esc(mov.label || '')}" placeholder="Carga / variante" style="width:72px;font-size:10.5px">
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
  const body = document.getElementById(bodyId(section));
  const last = body.lastElementChild;
  if (last) { const inp = last.querySelector('input'); if (inp) inp.focus(); }
}

function addSep(section) { appendMovRow(section, { separador: 'then...' }); }

function addChegada(section) {
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
function previewWorkoutByPath(path) {
  const dia = config.dias[path.dia];
  const cat = (dia || {}).categorias && dia.categorias[path.cat];
  const wkt = cat && cat.workouts && cat.workouts[path.wkt];
  if (!wkt) return;
  // Breadcrumb: Evento › Dia (data) › Categoria › N. Workout
  const dataShort = dia && dia.data ? ' ' + String(dia.data).slice(0, 5) : '';
  const breadcrumb = [
    config.evento.nome || 'Evento',
    `${dia.label || `Dia ${path.dia + 1}`}${dataShort}`,
    cat.nome,
    `${path.wkt + 1} — ${wkt.nome || '—'}`,
  ].join(' › ');
  document.getElementById('pbName').textContent = breadcrumb;
  document.getElementById('previewEmpty').style.display = 'none';
  const frame = document.getElementById('previewFrame');
  frame.style.display = 'block';

  fetch('/api/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config, dia_idx: path.dia, cat_idx: path.cat, wkt_idx: path.wkt })
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
  const totalWkts = (config.dias || []).reduce((sum, d) =>
    sum + (d.categorias || []).reduce((s, c) => s + (c.workouts || []).length, 0), 0);
  if (!totalWkts) return;

  const escopo = (document.getElementById('selEscopoGerar') || {}).value || 'evento';
  const incluirCheckbox = document.getElementById('chkIncluirCompetidores');
  const incluir = !incluirCheckbox || incluirCheckbox.checked;
  const payload = { config, incluir_competidores: incluir };
  if (escopo === 'dia') {
    payload.dia_idx = diaAtual;
  } else if (escopo === 'cat') {
    const dia = (config.dias || [])[diaAtual];
    if (!dia || !dia.categorias || !dia.categorias[catSel]) {
      toast('Sem categoria selecionada', 'err'); return;
    }
    payload.dia_idx = diaAtual;
    payload.cat_idx = catSel;
  }

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
    body: JSON.stringify(payload)
  })
  .then(r => { if (!r.ok) throw new Error('Falha na geração'); return r.blob(); })
  .then(blob => {
    const url = URL.createObjectURL(blob);
    const a   = document.createElement('a');
    a.href = url;
    const baseName = (config.evento.nome || 'sumulas').replace(/\s+/g, '_');
    const sufixo = escopo === 'dia' ? `_${(config.dias[diaAtual] || {}).label || 'dia'}` : '';
    a.download = `${baseName}${sufixo}.zip`;
    a.click();
    URL.revokeObjectURL(url);
    toast(`ZIP gerado com sucesso!`, 'ok');
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
      aplicarImport(result);
    })
    .catch(e => toast('Erro ao importar: ' + e.message, 'err'));
  };
  reader.readAsDataURL(file);
}

// ─── Export/Import JSON (backup explícito do estado em arquivo) ──────────────
function exportarJSON() {
  const snapshot = { version: SCHEMA_VERSION, config, diaAtual, exportedAt: new Date().toISOString() };
  const blob = new Blob([JSON.stringify(snapshot, null, 2)], { type: 'application/json' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  const slug = (config.evento.nome || 'sumulas').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'sumulas';
  const ts   = new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-');
  a.href = url;
  a.download = `${slug}-${ts}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  toast('Backup exportado', 'ok');
}

function importarJSON(input) {
  const file = input.files[0];
  if (!file) return;
  input.value = '';
  const reader = new FileReader();
  reader.onload = e => {
    try {
      const snap = JSON.parse(e.target.result);
      if (!snap || typeof snap !== 'object' || !snap.config || !Array.isArray(snap.config.dias)) {
        throw new Error('arquivo não parece um backup válido');
      }
      if (snap.version !== SCHEMA_VERSION) {
        if (!confirm(`Backup está em schema v${snap.version} (atual é v${SCHEMA_VERSION}). Tentar importar mesmo assim?`)) return;
      }
      const temAtual = temDados() || config.evento.nome;
      if (temAtual && !confirm('Importar vai substituir o evento atual. Continuar?')) return;
      if (!snap.config.evento.logo_empresa) snap.config.evento.logo_empresa = DS_LOGO_PADRAO;
      config = { ...config, ...snap.config };
      diaAtual = typeof snap.diaAtual === 'number' ? snap.diaAtual : 0;
      catSel = 0; catListOpen = false;
      previewPath = null;
      // sincroniza inputs do formulário
      document.getElementById('evNome').value = config.evento.nome || '';
      document.getElementById('evCat').value  = config.evento.categoria || '';
      document.getElementById('evData').value = config.evento.data || '';
      renderEventoDisplay();
      renderDiaTabs();
      renderCategoriasList();
      atualizarBotaoGerar();
      updateClearAllVisibility();
      updateEmptyState();
      saveState();
      fecharConfig();
      toast('Backup restaurado', 'ok');
    } catch (err) {
      toast('Erro ao importar: ' + err.message, 'err');
    }
  };
  reader.readAsText(file);
}

function aplicarImport(result) {
  if (!result || !result.dias) {
    toast('Resposta sem dias — formato inesperado', 'err');
    return;
  }
  config.dias = result.dias;
  config.roster = result.roster || [];
  if (result.evento_nome && !config.evento.nome) {
    config.evento.nome = result.evento_nome;
    document.getElementById('evNome').value = result.evento_nome;
  }
  diaAtual    = 0;
  catSel = 0; catListOpen = false;
  previewPath = null;
  renderEventoDisplay();
  renderDiaTabs();
  renderCategoriasList();
  atualizarBotaoGerar();
  updateClearAllVisibility();
  document.getElementById('previewFrame').style.display = 'none';
  document.getElementById('pbName').textContent = '—';
  updateEmptyState();
  saveState();

  const totalCats = result.dias.reduce((s, d) => s + (d.categorias || []).length, 0);
  // Mensagem inicial (depois é substituída pelo resumo via IA/algoritmo)
  mostrarBannerPosImport(`${result.dias.length} dia(s), ${totalCats} categoria(s) importadas. Configure as datas pra aparecerem nas súmulas.`);
  atualizarBannerPosImport();  // busca resumo formatado
  toast(`${result.dias.length} dia(s), ${totalCats} categoria(s) importadas`, 'ok');
}

// ═══════════════════════════════════════════════════════════════════
//  EMPTY STATE / CLEAR
// ═══════════════════════════════════════════════════════════════════
function updateEmptyState() {
  const wrap     = document.getElementById('previewEmpty');
  const onboard  = document.getElementById('emptyOnboarding');
  const noSelect = document.getElementById('emptyNoSelection');
  const frame    = document.getElementById('previewFrame');
  if (frame.style.display === 'block') return;
  wrap.style.display = '';
  if (!temDados()) {
    onboard.style.display  = 'flex';
    noSelect.style.display = 'none';
  } else {
    onboard.style.display  = 'none';
    noSelect.style.display = 'flex';
  }
}

function updateClearAllVisibility() {
  const btn = document.getElementById('btnClearAll');
  const hasData = temDados() || config.evento.nome;
  btn.style.display = hasData ? '' : 'none';
}

function limparTudo() {
  if (!confirm('Apagar evento, dias, categorias e workouts importados?\nEsta ação não pode ser desfeita.')) return;
  config = {
    evento: { nome: "", categoria: "", data: "", logo_empresa: DS_LOGO_PADRAO, logo_evento: "" },
    dias: [],
    roster: [],
  };
  diaAtual    = 0;
  catSel = 0; catListOpen = false;
  previewPath = null;
  editingPath = null;
  clearState();
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
  renderDiaTabs();
  renderCategoriasList();
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
  setSaveIndicator('saving');
  clearTimeout(_saveTimer);
  _saveTimer = setTimeout(_persistNow, 400);
}

function _persistNow() {
  const snapshot = { version: SCHEMA_VERSION, config, diaAtual };
  let ok = false;
  try {
    localStorage.setItem(STATE_KEY, JSON.stringify(snapshot));
    ok = true;
  } catch (e) {
    try {
      const lite = JSON.parse(JSON.stringify(snapshot));
      lite.config.evento.logo_evento = '';
      lite.config.evento.logo_empresa = '';
      localStorage.setItem(STATE_KEY, JSON.stringify(lite));
      console.warn('Persistência sem logos (cota cheia):', e.message);
      ok = true;
    } catch (e2) {
      console.error('Falha ao persistir:', e2);
    }
  }
  updateClearAllVisibility();
  setSaveIndicator(ok ? 'saved' : 'error');
}

function setSaveIndicator(state) {
  const el = document.getElementById('saveIndicator');
  if (!el) return;
  if (state === 'saving') {
    el.textContent = 'salvando…';
    el.className = 'hdr-save saving';
  } else if (state === 'saved') {
    el.textContent = '✓ salvo ' + new Date().toLocaleTimeString('pt-BR', {hour:'2-digit', minute:'2-digit'});
    el.className = 'hdr-save saved';
  } else if (state === 'error') {
    el.textContent = '⚠ falha ao salvar';
    el.className = 'hdr-save';
    el.style.color = '#D66';
  } else {
    el.textContent = '';
    el.className = 'hdr-save';
  }
}

function loadState() {
  try {
    const raw = localStorage.getItem(STATE_KEY);
    if (!raw) return;
    const snap = JSON.parse(raw);
    if (snap && snap.version !== SCHEMA_VERSION) {
      console.info(`localStorage state schema antigo (v${snap.version}); descartando.`);
      clearState();
      return;
    }
    if (snap && snap.config) {
      if (!snap.config.evento.logo_empresa) snap.config.evento.logo_empresa = DS_LOGO_PADRAO;
      config = { ...config, ...snap.config };
      if (typeof snap.diaAtual === 'number') diaAtual = snap.diaAtual;
      setSaveIndicator('saved');  // sinaliza visualmente que algo foi restaurado
    }
  } catch (e) {
    console.warn('Falha ao restaurar estado:', e);
  }
}

function clearState() {
  try {
    localStorage.removeItem(STATE_KEY);
    localStorage.removeItem(IMPORT_KEY);
  } catch (e) { /* ignore */ }
  setSaveIndicator(null);
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

// Atualiza label do botão Gerar quando muda escopo / toggle
function onGerarOptChange() {
  atualizarBotaoGerar();
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
    chatAIAtiva = !!s.ai_ativo;
    if (s.ai_ativo) document.getElementById('aiBadge').style.display = '';
  }).catch(()=>{});
  loadState();
  applyLabelColPref();
  // Ajusta diaAtual se ficou fora do range (caso state tenha mais dias do que config carregada)
  if (diaAtual >= (config.dias || []).length) diaAtual = 0;
  renderEventoDisplay();
  renderDiaTabs();
  renderCategoriasList();
  updateClearAllVisibility();
  atualizarBotaoGerar();
  updateEmptyState();
})();
