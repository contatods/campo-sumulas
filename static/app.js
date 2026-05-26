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

const STATE_KEY      = 'ds_sumulas_v2_state';        // legacy (1 evento) — só pra migração
const MULTI_STATE_KEY = 'ds_sumulas_v3_multi_state'; // novo: { activeId, events: {...} }
const IMPORT_KEY     = 'ds_sumulas_v2_import';
const LABEL_COL_KEY  = 'ds_sumulas_v2_show_label';
// Bump quando mudar shape de `config`. State antigo é descartado/migrado.
const SCHEMA_VERSION = 3;

// Evento ativo no momento. ID é gerado quando o evento é criado/migrado.
let eventoAtivoId = null;

const TIPO_LABEL = { for_time: 'For Time', amrap: 'AMRAP', express: 'Express', for_load: 'For Load' };

// API token opcional pra deploy público. Quando o backend tem
// CAMPOSUMULAS_TOKEN setado, ele exige header 'X-Api-Token' em todo POST.
// Front lê o token de localStorage e injeta automaticamente via apiFetch().
// Pra setar: no DevTools, localStorage.setItem('camposumulas_token', 'XXX').
// Pra limpar: localStorage.removeItem('camposumulas_token').
const TOKEN_KEY = 'camposumulas_token';
function apiFetch(url, opts = {}) {
  const token = (localStorage.getItem(TOKEN_KEY) || '').trim();
  if (token) {
    opts.headers = { ...(opts.headers || {}), 'X-Api-Token': token };
  }
  return fetch(url, opts);
}

// ── Acessibilidade: sync de display + aria-hidden + foco em modais ──────────
// Restaura o foco no elemento que abriu o modal quando ele fecha — padrão
// WCAG pra leitor de tela e navegação por teclado.
let _focoAnterior = null;
function setDialogOpen(id, isOpen, displayMode = '') {
  const el = document.getElementById(id);
  if (!el) return;
  if (isOpen) {
    _focoAnterior = document.activeElement;
    el.style.display = displayMode || 'block';
    el.setAttribute('aria-hidden', 'false');
    // Foca primeiro elemento focável após display aplicar (microtask delay)
    setTimeout(() => {
      const focusable = el.querySelector(
        'input:not([type=hidden]):not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );
      if (focusable) focusable.focus();
    }, 30);
  } else {
    el.style.display = 'none';
    el.setAttribute('aria-hidden', 'true');
    if (_focoAnterior && typeof _focoAnterior.focus === 'function') {
      try { _focoAnterior.focus(); } catch (e) {}
    }
  }
}

// Defaults For Load (espelham types_ds.py — manter sincronizado)
const ANILHAS_KG_DEFAULT = [25, 20, 15, 10, 5, 2.5, 1.25];
const ANILHAS_LB_DEFAULT = [55, 45, 35, 25, 15, 10, 5, 2.5];
function _anilhasDefault(unidade) {
  return (unidade || 'kg').toLowerCase() === 'lb' ? ANILHAS_LB_DEFAULT : ANILHAS_KG_DEFAULT;
}

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
  setDialogOpen('configModal', true);
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
  setDialogOpen('configModal', false);
}

// Numera workouts em sequência contínua por categoria atravessando dias.
// Mutação in-place em config.dias[*].categorias[*].workouts[*].numero (e
// numero_f2 pro Express). Mesma lógica do backend assign_workout_numbers_global.
function assignWorkoutNumbersGlobal() {
  const dias = (config && config.dias) || [];
  const counters = {};
  for (const dia of dias) {
    for (const cat of (dia.categorias || [])) {
      const nome = (cat.nome || '').trim();
      let counter = counters[nome] || 1;
      for (const wkt of (cat.workouts || [])) {
        wkt.numero = counter;
        if (wkt.tipo === 'express') {
          wkt.numero_f2 = counter + 1;
          counter += 2;
        } else {
          delete wkt.numero_f2;
          counter += 1;
        }
      }
      counters[nome] = counter;
    }
  }
}

// ─── Modal de ajuda / manual ────────────────────────────────────────────────
function abrirAjuda() {
  setDialogOpen('ajudaModal', true);
  ajudaTab('visao');
}
function fecharAjuda() {
  setDialogOpen('ajudaModal', false);
}
function ajudaTab(t) {
  document.querySelectorAll('[data-ajuda-tab]').forEach(b => {
    b.classList.toggle('active', b.dataset.ajudaTab === t);
  });
  ['visao','importar','editar','gerar','ia','eventos','backup','reset'].forEach(name => {
    const pane = document.getElementById('ajudaPane' + name.charAt(0).toUpperCase() + name.slice(1));
    if (pane) pane.style.display = (name === t) ? '' : 'none';
  });
}

// Reset completo: apaga TUDO do localStorage (todos eventos, prefs, cache).
// Pede confirmação dupla com contagem real do que vai ser apagado.
function resetCompleto() {
  const todos      = listarEventos(true);
  const ativos     = todos.filter(e => !e.archived).length;
  const arquivados = todos.filter(e => e.archived).length;
  const msg = `⚠ Vai apagar do navegador:\n\n` +
              `• ${ativos} evento(s) ativo(s)\n` +
              `• ${arquivados} evento(s) arquivado(s)\n` +
              `• Todas as preferências\n\n` +
              `Tem certeza?`;
  if (!confirm(msg)) return;
  if (!confirm('Última confirmação. Sem volta. Continuar?')) return;
  // Overlay enquanto roda + recarrega. Previne usuário clicar em outra
  // coisa e ver tela meio quebrada (sem state) antes do reload.
  const overlay = document.createElement('div');
  overlay.className = 'reset-overlay';
  overlay.innerHTML = '<div class="reset-overlay-inner">' +
    '<div class="reset-spinner">⏳</div>' +
    '<div class="reset-msg">Limpando estado do navegador…</div>' +
    '</div>';
  document.body.appendChild(overlay);
  // Delay mínimo pro browser pintar o overlay antes do trabalho síncrono
  setTimeout(() => {
    try {
      localStorage.clear();
    } catch (e) {
      overlay.remove();
      toast('Erro ao limpar: ' + e.message, 'err');
      return;
    }
    location.reload();
  }, 80);
}

// ─── Modal de eventos (multi-evento) ─────────────────────────────────────────
function abrirEventos() {
  // Garante que evento atual está salvo antes de listar
  if (eventoAtivoId) _persistNow();
  setDialogOpen('eventosModal', true);
  renderListaEventos();
}

function fecharEventos() {
  setDialogOpen('eventosModal', false);
}

function renderListaEventos() {
  const wrap = document.getElementById('listaEventos');
  if (!wrap) return;
  const ativos = listarEventos(false);
  const arquivados = listarEventos(true).filter(e => e.archived);
  if (!ativos.length && !arquivados.length) {
    wrap.innerHTML = '<p class="cfg-hint" style="font-style:italic">Nenhum evento salvo ainda.</p>';
    return;
  }
  const renderItem = (e) => {
    const data = e.atualizadoEm ? new Date(e.atualizadoEm).toLocaleString('pt-BR', {day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit'}) : '—';
    const ativoTag = e.ativo ? '<span class="evt-tag-ativo">ativo</span>' : '';
    if (e.archived) {
      return `
        <div class="evt-item evt-item-archived">
          <div class="evt-info">
            <div class="evt-nome">${esc(e.nome)}</div>
            <div class="evt-meta">${e.totalDias} dia(s) · ${e.totalCategorias} categoria(s) · arquivado em ${esc(data)}</div>
          </div>
          <div class="evt-actions">
            <button class="btn-mov" onclick="restaurarEvento('${e.id}')" title="Restaurar">↩</button>
            <button class="btn-mov" onclick="excluirDefinitivamente('${e.id}')" title="Excluir definitivamente">✕</button>
          </div>
        </div>
      `;
    }
    return `
      <div class="evt-item ${e.ativo ? 'evt-item-ativo' : ''}">
        <div class="evt-info">
          <div class="evt-nome">${esc(e.nome)} ${ativoTag}</div>
          <div class="evt-meta">${e.totalDias} dia(s) · ${e.totalCategorias} categoria(s) · atualizado ${esc(data)}</div>
        </div>
        <div class="evt-actions">
          ${e.ativo ? '' : `<button class="btn-mov" onclick="trocarEvento('${e.id}')" title="Abrir esse evento">Abrir</button>`}
          <button class="btn-mov" onclick="duplicarEvento('${e.id}')" title="Duplicar">⎘</button>
          <button class="btn-mov" onclick="renomearEvento('${e.id}')" title="Renomear">✎</button>
          <button class="btn-mov" onclick="arquivarEvento('${e.id}')" title="Arquivar (pode restaurar depois)">🗑</button>
        </div>
      </div>
    `;
  };
  const ativosHtml = ativos.length
    ? ativos.map(renderItem).join('')
    : '<p class="cfg-hint" style="font-style:italic">Nenhum evento ativo.</p>';
  const arqToggle = arquivados.length
    ? `<button class="btn-mov" style="width:100%;margin-top:12px" onclick="toggleArquivados()">
         ${_mostrarArquivados ? '▼' : '▶'} Arquivados (${arquivados.length})
       </button>`
    : '';
  const arqHtml = (_mostrarArquivados && arquivados.length)
    ? `<div style="margin-top:8px">${arquivados.map(renderItem).join('')}</div>`
    : '';
  wrap.innerHTML = ativosHtml + arqToggle + arqHtml;
}

function cfgTab(tab) {
  // Escopa em #configModal pra não afetar tabs do modal de Ajuda (que também
  // usam .cfg-tab mas com data-ajuda-tab em vez de data-tab).
  document.querySelectorAll('#configModal .cfg-tab').forEach(b =>
    b.classList.toggle('active', b.dataset.tab === tab));
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
  document.getElementById('pibAIBox').style.display = 'none';
  document.getElementById('pibAIBtn').style.display = 'none';
}
function mostrarBannerPosImport(msg) {
  const banner = document.getElementById('postImportBanner');
  document.getElementById('pibMsg').textContent = msg;
  banner.style.display = '';
}

// Avisos do último import (preenchido em aplicarImport). Usado pela IA pra
// explicar o que aconteceu.
let _ultimosAvisos = [];
let _ultimosStats = null;

function explicarComIA() {
  if (!chatAIAtiva) {
    toast('IA inativa — configure ANTHROPIC_API_KEY no servidor', 'err');
    return;
  }
  if (!_ultimosAvisos.length) {
    toast('Sem avisos pra explicar', 'info');
    return;
  }
  // Cache: hash simples do JSON dos avisos pra evitar pagar 2× pelo mesmo
  const chave = 'ai_avisos:' + _hashStr(JSON.stringify({s: _ultimosStats, a: _ultimosAvisos}));
  const cached = sessionStorage.getItem(chave);
  if (cached) {
    _renderExplicacaoIA(cached);
    return;
  }
  const btn = document.getElementById('pibAIBtn');
  const box = document.getElementById('pibAIBox');
  btn.disabled = true;
  btn.textContent = '🤖 Pensando…';
  apiFetch('/api/ai/explicar-avisos', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ stats: _ultimosStats, avisos: _ultimosAvisos }),
  }).then(r => r.json()).then(res => {
    btn.disabled = false;
    btn.textContent = '🤖 Explicar com IA';
    if (res.error) {
      box.textContent = 'Erro: ' + res.error;
      box.style.display = '';
      return;
    }
    const texto = res.texto || '(sem resposta)';
    try { sessionStorage.setItem(chave, texto); } catch (e) {}
    _renderExplicacaoIA(texto);
  }).catch(e => {
    btn.disabled = false;
    btn.textContent = '🤖 Explicar com IA';
    box.textContent = 'Erro: ' + e.message;
    box.style.display = '';
  });
}

function _renderExplicacaoIA(texto) {
  const box = document.getElementById('pibAIBox');
  // texto vem com quebras de linha — preserva via white-space pre-wrap
  box.textContent = texto;
  box.style.display = '';
}

function _hashStr(s) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  return h.toString(36);
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
  apiFetch('/api/ai/sugerir-time-cap', {
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
  apiFetch('/api/ai/auto-descricao', {
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
  const panel = document.getElementById('chatPanel');
  panel.style.display = chatOpen ? '' : 'none';
  panel.setAttribute('aria-hidden', chatOpen ? 'false' : 'true');
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

  apiFetch('/api/ai/chat', {
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
  setDialogOpen('validModal', true);
  document.getElementById('validacaoStatus').textContent = 'Analisando…';
  document.getElementById('validacaoLista').innerHTML = '';
  apiFetch('/api/ai/validar-evento', {
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
  setDialogOpen('validModal', false);
}

// Atualiza o banner pós-import com resumo curto + botão validar
function atualizarBannerPosImport() {
  if (!temDados()) return;
  apiFetch('/api/ai/resumo-evento', {
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
      <button class="icon-btn danger" onclick="removerDia(${i})" title="Remover dia" aria-label="Remover dia ${esc(d.label || '')}">×</button>
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
  // Garante que numero global (contínuo na categoria atravessando dias) está
  // atualizado antes de renderizar — barato e idempotente.
  assignWorkoutNumbersGlobal();
  const workouts = cat.workouts || [];
  const baterias = cat.baterias || [];

  const workoutsHtml = workouts.length
    ? workouts.map((w, wi) => {
        const isActive = previewPath && previewPath.dia === diaAtual && previewPath.cat === ci && previewPath.wkt === wi;
        const tipoLabel = TIPO_LABEL[w.tipo] || w.tipo;
        const numDisplay = w.numero || (wi + 1);
        const numStr = (w.tipo === 'express' && w.numero_f2) ? `${numDisplay}-${w.numero_f2}` : String(numDisplay);
        return `
        <div class="wkt-row${isActive ? ' active' : ''}" onclick="selectWorkout(${ci}, ${wi})">
          <div class="wkt-row-num">${numStr}</div>
          <div class="wkt-row-info">
            <div class="wkt-row-nome">${esc(w.nome || '—')}</div>
            <div class="wkt-row-tags"><span class="tag ${w.tipo}">${esc(tipoLabel)}</span>${w.time_cap ? ` <span class="tag">${esc(w.time_cap)}</span>` : ''}${w.arena ? ` <span class="tag">${esc(w.arena)}</span>` : ''}</div>
          </div>
          <div class="wkt-row-actions">
            <button class="icon-btn" onclick="event.stopPropagation();editarWorkout(${ci}, ${wi})" title="Editar" aria-label="Editar workout ${esc(w.nome || '')}">✎</button>
            <button class="icon-btn danger" onclick="event.stopPropagation();deletarWorkout(${ci}, ${wi})" title="Excluir" aria-label="Excluir workout ${esc(w.nome || '')}">×</button>
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

  // Botão "Pré-evento" — atletas no roster sem bateria
  const btnPre = document.getElementById('btnGerarPreEvento');
  const subPre = document.getElementById('bgeSubPreEvento');
  if (btnPre && subPre) {
    const stats = _statsPreEvento();
    btnPre.disabled = stats.total === 0;
    subPre.textContent = stats.total === 0
      ? (stats.semCategoria ? `${stats.semCategoria} no roster sem categoria definida` : 'todos do roster já estão alocados')
      : `${stats.total} não alocado${stats.total !== 1 ? 's' : ''} em ${stats.cats} categoria${stats.cats !== 1 ? 's' : ''}`;
  }
}

function _statsPreEvento() {
  // Calcula quantos atletas do roster ainda não têm bateria/raia, agrupados
  // por categoria. Só conta os que têm 'categoria' atribuída (via faixa
  // Inscritos do Excel).
  const roster = config.roster || [];
  const dias = config.dias || [];
  if (!roster.length) return {total: 0, cats: 0, semCategoria: 0};
  // Mapa: categoria → set de números alocados
  const alocadosPorCat = {};
  for (const d of dias) {
    for (const c of d.categorias || []) {
      const set = alocadosPorCat[c.nome] || (alocadosPorCat[c.nome] = new Set());
      for (const b of c.baterias || []) {
        for (const a of b.alocacoes || []) {
          const n = String(a.numero || '').trim();
          if (n) set.add(n);
        }
      }
    }
  }
  let total = 0, semCategoria = 0;
  const cats = new Set();
  for (const a of roster) {
    const cat = (a.categoria || '').trim();
    if (!cat) { semCategoria++; continue; }
    const num = String(a.numero || '').trim();
    if (!num) continue;
    const set = alocadosPorCat[cat];
    if (!set || !set.has(num)) {
      total++;
      cats.add(cat);
    }
  }
  return {total, cats: cats.size, semCategoria};
}

// ─── Helpers compartilhados pelos botões de gerar ZIP ─────────────────────────
// Dispara download de um blob como arquivo. Revoga URL ao final pra evitar leak.
function _downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// Desabilita botões + mostra 'gerando…'. Retorna closure pra restaurar estado.
function _gerarBtnsBusy(btnIds, activeBtnId, subId) {
  btnIds.forEach(id => { const b = document.getElementById(id); if (b) b.disabled = true; });
  const btn = activeBtnId ? document.getElementById(activeBtnId) : null;
  if (btn) btn.classList.add('generating');
  const sub = subId ? document.getElementById(subId) : null;
  const subOriginal = sub ? sub.textContent : '';
  if (sub) sub.textContent = 'gerando…';
  return () => {
    if (btn) btn.classList.remove('generating');
    if (sub) sub.textContent = subOriginal;
    atualizarBotaoGerar();
  };
}

function gerarPreEvento() {
  const stats = _statsPreEvento();
  if (stats.total === 0) {
    toast('Nada a gerar — todos do roster já estão alocados', 'warn');
    return;
  }
  const restore = _gerarBtnsBusy(['btnGerarPreEvento'], 'btnGerarPreEvento', 'bgeSubPreEvento');
  apiFetch('/api/generate/pre-evento', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config })
  })
  .then(r => { if (!r.ok) return r.json().then(j => { throw new Error(j.error || 'falha na geração'); }); return r.blob(); })
  .then(blob => {
    const baseName = (config.evento.nome || 'sumulas').replace(/\s+/g, '_');
    _downloadBlob(blob, `${baseName}_pre-evento.zip`);
    toast(`Pré-evento gerado — ${stats.total} atletas/times em ${stats.cats} categoria${stats.cats !== 1 ? 's' : ''}`, 'ok');
  })
  .catch(e => toast('Erro: ' + e.message, 'err'))
  .finally(restore);
}

function _buildPayloadGerar(escopo) {
  const incluir = document.getElementById('chkIncluirCompetidores');
  const incluirOn = !incluir || incluir.checked;
  const payload = { config, incluir_competidores: incluirOn };
  if (escopo === 'dia') {
    payload.dia_idx = diaAtual;
  } else if (escopo === 'cat') {
    const dia = (config.dias || [])[diaAtual];
    if (!dia || !dia.categorias || !dia.categorias[catSel]) {
      toast('Sem categoria selecionada', 'err'); return null;
    }
    payload.dia_idx = diaAtual;
    payload.cat_idx = catSel;
  }
  return payload;
}

function _nomeArquivoZip(escopo) {
  const baseName = (config.evento.nome || 'sumulas').replace(/\s+/g, '_');
  if (escopo === 'dia') {
    const label = (config.dias[diaAtual] || {}).label || 'dia';
    return `${baseName}_${label}.zip`;
  }
  if (escopo === 'cat') {
    const c = ((config.dias[diaAtual] || {}).categorias || [])[catSel];
    return c ? `${baseName}_${c.nome.replace(/\s+/g, '_')}.zip` : `${baseName}.zip`;
  }
  return `${baseName}.zip`;
}

function gerarZIPEscopo(escopo) {
  const totalWkts = (config.dias || []).reduce((sum, d) =>
    sum + (d.categorias || []).reduce((s, c) => s + (c.workouts || []).length, 0), 0);
  if (!totalWkts) return;
  // Eventos grandes (evento/dia) podem estourar timeout do servidor cloud e
  // gerar um ZIP que o navegador não consegue baixar. Confirma com o usuário
  // pra evitar "parecer que o download falhou".
  if (escopo !== 'cat') {
    const incluir = document.getElementById('chkIncluirCompetidores');
    const compOn = !incluir || incluir.checked;
    const nPag = _contagemPaginas(escopo, compOn);
    if (nPag > 1500) {
      const ok = confirm(
        `Este escopo gera ~${nPag.toLocaleString('pt-BR')} páginas. ` +
        `Em servidor cloud pode estourar o tempo limite ou criar um ZIP grande ` +
        `demais pro navegador baixar.\n\nRecomendamos gerar por categoria.\n\nContinuar mesmo assim?`
      );
      if (!ok) return;
    }
  }
  const payload = _buildPayloadGerar(escopo);
  if (!payload) return;
  const btnIdMap = { evento: 'btnGerarEvento', dia: 'btnGerarDia', cat: 'btnGerarCat' };
  const subIdMap = { evento: 'bgeSubEvento',   dia: 'bgeSubDia',   cat: 'bgeSubCat' };
  const restore = _gerarBtnsBusy(Object.values(btnIdMap), btnIdMap[escopo], subIdMap[escopo]);
  apiFetch('/api/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
  .then(r => { if (!r.ok) throw new Error('Falha na geração'); return r.blob(); })
  .then(blob => {
    _downloadBlob(blob, _nomeArquivoZip(escopo));
    toast('ZIP gerado com sucesso!', 'ok');
  })
  .catch(e => toast('Erro: ' + e.message, 'err'))
  .finally(restore);
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
  document.getElementById('edTiebreak').value = '';
  document.getElementById('edTiebreakPorRound').checked = false;
  document.getElementById('edRepsDeltaPorRound').value = 0;
  document.getElementById('edUltimoRoundMax').checked = false;
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
  assignWorkoutNumbersGlobal();
  const wNum = w.numero || (wi + 1);
  const wNumStr = (w.tipo === 'express' && w.numero_f2) ? `${wNum}-${w.numero_f2}` : String(wNum);
  document.getElementById('edTitle').textContent = `Workout ${wNumStr} · ${esc(cats[ci].nome)}`;
  document.getElementById('edNome').value = w.nome || '';
  document.getElementById('edTipo').value = w.tipo || 'for_time';
  document.getElementById('edTimeCap').value = w.time_cap || '';
  // Tiebreak: por round (AMRAP) salvo em wkt.tiebreak_por_round + descrição
  // opcional em wkt.tiebreak. For Time só usa wkt.tiebreak.
  document.getElementById('edTiebreak').value = w.tiebreak || '';
  document.getElementById('edTiebreakPorRound').checked = !!w.tiebreak_por_round;
  // Progressão (AMRAP/EMOM): delta + último round MAX
  document.getElementById('edRepsDeltaPorRound').value = w.reps_delta_por_round || 0;
  document.getElementById('edUltimoRoundMax').checked = !!w.ultimo_round_max;
  document.getElementById('edDescricao').value = (w.descricao || []).join('\n');
  if (w.tipo === 'express') {
    const j1 = parseJanela((w.formula1 || {}).janela);
    const j2 = parseJanela((w.formula2 || {}).janela);
    setExpressJanela('f1', j1.start, j1.end);
    setExpressJanela('f2', j2.start, j2.end);
    setMovTableFromArray('f1', (w.formula1 || {}).movimentos || []);
    setMovTableFromArray('f2', (w.formula2 || {}).movimentos || []);
    switchExpressTab('f1');
  } else if (w.tipo === 'for_load') {
    // Default lb pra eventos novos (CrossFit BR + competições oficiais usam lb).
    // Eventos antigos mantêm o que foi salvo (w.unidade já populada).
    const unidWkt = w.unidade || 'lb';
    document.getElementById('edFlTentativas').value = w.tentativas || 3;
    document.getElementById('edFlUnidade').value    = unidWkt;
    document.getElementById('edFlBarraM').value     = w.barra_masculina || (unidWkt === 'lb' ? 45 : 20);
    document.getElementById('edFlBarraF').value     = w.barra_feminina  || (unidWkt === 'lb' ? 35 : 15);
    document.getElementById('edFlAnilhas').value    = (w.anilhas || _anilhasDefault(unidWkt)).join(', ');
  } else {
    setMovTableFromArray('main', w.movimentos || []);
  }
  populateEditorPathSelects(diaAtual, ci);
  onTipoChange();
  abrirEditor();
}

function abrirEditor() {
  const ed = document.getElementById('editor');
  _focoAnterior = document.activeElement;
  ed.classList.add('open');
  ed.setAttribute('aria-hidden', 'false');
  setTimeout(() => {
    const focusable = ed.querySelector('input:not([type=hidden]):not([disabled])');
    if (focusable) focusable.focus();
  }, 30);
}

function fecharEditor() {
  const ed = document.getElementById('editor');
  ed.classList.remove('open');
  ed.setAttribute('aria-hidden', 'true');
  editingPath = null;
  if (_focoAnterior && typeof _focoAnterior.focus === 'function') {
    try { _focoAnterior.focus(); } catch (e) {}
  }
}

function onTipoChange() {
  const t = document.getElementById('edTipo').value;
  // For Load não tem movimentos — esconde a seção de movimentos
  document.getElementById('secMovimentos').style.display = (t !== 'express' && t !== 'for_load') ? '' : 'none';
  document.getElementById('secExpress').style.display    = t === 'express' ? '' : 'none';
  document.getElementById('secForLoad').style.display    = t === 'for_load' ? '' : 'none';
  document.getElementById('btnChegadaMain').style.display = t === 'amrap' ? 'none' : '';
  // Time cap não faz sentido pra For Load
  const tcWrap = document.getElementById('edTimeCap').closest('.field');
  if (tcWrap) tcWrap.style.display = t === 'for_load' ? 'none' : '';
  // Tiebreak: esconde linha inteira em For Load. Checkbox 'por round' só em AMRAP.
  const tbRow = document.getElementById('edTbRow');
  if (tbRow) tbRow.style.display = t === 'for_load' ? 'none' : '';
  const tbPorRoundField = document.getElementById('edTbPorRoundField');
  if (tbPorRoundField) tbPorRoundField.style.display = t === 'amrap' ? '' : 'none';
  // Progressão: SÓ AMRAP/EMOM (For Time não tem rounds)
  const progRow = document.getElementById('edProgRow');
  if (progRow) progRow.style.display = t === 'amrap' ? '' : 'none';
  if (t === 'express') switchExpressTab('f1');
  // Quando vai pra For Load, popula defaults se vazio
  if (t === 'for_load') _preencherDefaultsForLoad();
}

function _preencherDefaultsForLoad() {
  const unidade = document.getElementById('edFlUnidade').value || 'lb';
  const anilhasInp = document.getElementById('edFlAnilhas');
  if (!anilhasInp.value.trim()) {
    anilhasInp.value = _anilhasDefault(unidade).join(', ');
  }
  const tent = document.getElementById('edFlTentativas');
  if (!tent.value) tent.value = 3;
  const barraM = document.getElementById('edFlBarraM');
  if (!barraM.value) barraM.value = unidade === 'lb' ? 45 : 20;
  const barraF = document.getElementById('edFlBarraF');
  if (!barraF.value) barraF.value = unidade === 'lb' ? 35 : 15;
}

// Trocar unidade kg↔lb sugere atualizar anilhas+barras pro default da unidade.
// Pergunta antes de sobrescrever pra não perder customização do usuário.
function onForLoadUnidadeChange() {
  const unidade = document.getElementById('edFlUnidade').value || 'lb';
  const anilhasInp = document.getElementById('edFlAnilhas');
  const barraM = document.getElementById('edFlBarraM');
  const barraF = document.getElementById('edFlBarraF');
  const novoDefAnilhas = _anilhasDefault(unidade).join(', ');
  const novoBarraM = unidade === 'lb' ? 45 : 20;
  const novoBarraF = unidade === 'lb' ? 35 : 15;
  // Só ofere troca se valores atuais estão nos defaults da outra unidade
  // (heurística: usuário não personalizou, é só troca de unidade).
  const outraUnidade = unidade === 'lb' ? 'kg' : 'lb';
  const defOutra = _anilhasDefault(outraUnidade).join(', ');
  const barraOutraM = outraUnidade === 'lb' ? 45 : 20;
  const barraOutraF = outraUnidade === 'lb' ? 35 : 15;
  if (anilhasInp.value.trim() === defOutra) anilhasInp.value = novoDefAnilhas;
  if (parseFloat(barraM.value) === barraOutraM) barraM.value = novoBarraM;
  if (parseFloat(barraF.value) === barraOutraF) barraF.value = novoBarraF;
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

// ─── salvarWorkout: pipeline orquestrado ──────────────────────────────────────
// Splits da função original (86 linhas): leitura do form, resolução do path
// destino, obter/mover/criar wkt, popular campos por tipo, atualizar UI.
// Pipeline: lê form → resolve destino → wkt = obter/mover/criar →
// popular campos genéricos → popular por tipo → atualizar UI + persist.
function salvarWorkout() {
  if (!editingPath) return;
  const form = _lerFormWorkout();
  if (!form) return;   // validação já mostrou toast
  const destino = _resolverDestinoWorkout(form);
  if (!destino) return;
  invalidatePreviewCache();   // workout mudou — invalida cache do iframe
  const { wkt, moveu } = _obterOuCriarWorkout(destino);
  _popularCamposGenericos(wkt, form);
  _popularCamposPorTipo(wkt, form.tipo);
  _aplicarProgressaoReps(wkt);   // computa mov.reps_por_round nos PG-marcados
  _aposSalvarWorkout(moveu);
}

function _lerFormWorkout() {
  const nome = document.getElementById('edNome').value.trim().toUpperCase();
  if (!nome) { toast('Digite o nome do workout', 'err'); return null; }
  return {
    nome,
    tipo:    document.getElementById('edTipo').value,
    timeCap: document.getElementById('edTimeCap').value.trim(),
    desc:    document.getElementById('edDescricao').value.split('\n').map(s=>s.trim()).filter(Boolean),
    tiebreak: document.getElementById('edTiebreak').value.trim(),
    tiebreakPorRound: document.getElementById('edTiebreakPorRound').checked,
    repsDelta:        parseInt(document.getElementById('edRepsDeltaPorRound').value, 10) || 0,
    ultimoRoundMax:   document.getElementById('edUltimoRoundMax').checked,
  };
}

function _resolverDestinoWorkout() {
  // Path destino lido dos selects (pode ter mudado durante a edição)
  const novoDia = parseInt(document.getElementById('edDia').value, 10);
  const novaCat = parseInt(document.getElementById('edCat').value, 10);
  if (isNaN(novoDia) || isNaN(novaCat)) { toast('Selecione dia e categoria', 'err'); return null; }
  const catDestino = (config.dias[novoDia] && config.dias[novoDia].categorias[novaCat]) || null;
  if (!catDestino) { toast('Categoria de destino inválida', 'err'); return null; }
  catDestino.workouts = catDestino.workouts || [];
  return { novoDia, novaCat, catDestino };
}

function _obterOuCriarWorkout(destino) {
  const { novoDia, novaCat, catDestino } = destino;
  const moveu = editingPath.wkt >= 0
    && (editingPath.dia !== novoDia || editingPath.cat !== novaCat);
  let wkt;
  if (editingPath.wkt >= 0 && !moveu) {
    // Edição in-place — mantém referência do mesmo objeto
    wkt = config.dias[editingPath.dia].categorias[editingPath.cat].workouts[editingPath.wkt];
  } else if (moveu) {
    // Move workout entre categorias (splice de origem, push no destino)
    const origem = config.dias[editingPath.dia].categorias[editingPath.cat];
    wkt = origem.workouts.splice(editingPath.wkt, 1)[0];
    catDestino.workouts.push(wkt);
    editingPath = { dia: novoDia, cat: novaCat, wkt: catDestino.workouts.length - 1 };
  } else {
    wkt = { numero: 0, modalidade: 'individual' };
    catDestino.workouts.push(wkt);
    editingPath = { dia: novoDia, cat: novaCat, wkt: catDestino.workouts.length - 1 };
  }
  return { wkt, moveu };
}

function _popularCamposGenericos(wkt, form) {
  wkt.nome      = form.nome;
  wkt.tipo      = form.tipo;
  wkt.estilo    = form.tipo;
  wkt.time_cap  = form.timeCap;
  wkt.descricao = form.desc;
  // Tiebreak: campo livre + flag 'por round' (AMRAP/EMOM apenas).
  // For Load NUNCA usa tiebreak — limpa qualquer resíduo.
  if (form.tipo === 'for_load') {
    delete wkt.tiebreak;
    delete wkt.tiebreak_por_round;
  } else {
    if (form.tiebreak) wkt.tiebreak = form.tiebreak;
    else delete wkt.tiebreak;
    // Por round só pra amrap (EMOM é tipo='amrap' com emom_janela)
    if (form.tipo === 'amrap' && form.tiebreakPorRound) {
      wkt.tiebreak_por_round = true;
    } else {
      delete wkt.tiebreak_por_round;
    }
  }
  // Progressão de reps por round — só AMRAP/EMOM, e só se delta > 0.
  // reps_por_round de cada mov é computado DEPOIS em _aplicarProgressaoReps
  // (movimentos só são populados em _popularCamposPorTipo).
  if (form.tipo === 'amrap' && form.repsDelta > 0) {
    wkt.reps_delta_por_round = form.repsDelta;
    if (form.ultimoRoundMax) wkt.ultimo_round_max = true;
    else delete wkt.ultimo_round_max;
  } else {
    delete wkt.reps_delta_por_round;
    delete wkt.ultimo_round_max;
  }
}

function _aplicarProgressaoReps(wkt) {
  // Pre-computa mov.reps_por_round dos movs com progressivo=true. Espelha
  // o cálculo do parser Python (_aplicar_progressao_reps em parsers.py).
  if (!Array.isArray(wkt.movimentos)) return;
  const delta = wkt.reps_delta_por_round || 0;
  if (!delta) {
    wkt.movimentos.forEach(m => { delete m.reps_por_round; });
    return;
  }
  const ultimoMax = !!wkt.ultimo_round_max;
  const nRounds = wkt.emom_rounds || wkt.n_rounds || 5;
  wkt.movimentos.forEach(m => {
    if (m.chegada || m.separador) return;
    if (!m.progressivo) { delete m.reps_por_round; return; }
    const base = parseInt(m.reps, 10);
    if (isNaN(base)) return;
    const seq = [];
    for (let i = 0; i < nRounds; i++) seq.push(base + i * delta);
    if (ultimoMax && seq.length) seq[seq.length - 1] = 'MAX';
    m.reps_por_round = seq;
  });
}

function _popularCamposPorTipo(wkt, tipo) {
  if (tipo === 'express') {
    const f1Start = document.getElementById('edF1Start').value.trim();
    const f1End   = document.getElementById('edF1End').value.trim();
    const f2Start = document.getElementById('edF2Start').value.trim();
    const f2End   = document.getElementById('edF2End').value.trim();
    wkt.formula1 = { janela: buildJanelaAmrap(f1Start, f1End), descricao: [], movimentos: getMovTableArray('f1') };
    wkt.formula2 = { janela: buildJanelaForTime(f2Start, f2End), descricao: [], movimentos: getMovTableArray('f2') };
    delete wkt.movimentos;
  } else if (tipo === 'for_load') {
    wkt.tentativas = parseInt(document.getElementById('edFlTentativas').value, 10) || 3;
    wkt.unidade = document.getElementById('edFlUnidade').value || 'lb';
    // Defaults barras alinhados com a unidade: lb=45/35, kg=20/15
    const isLb = wkt.unidade === 'lb';
    wkt.barra_masculina = parseFloat(document.getElementById('edFlBarraM').value) || (isLb ? 45 : 20);
    wkt.barra_feminina  = parseFloat(document.getElementById('edFlBarraF').value) || (isLb ? 35 : 15);
    const anilhasInp = document.getElementById('edFlAnilhas').value
      .split(',').map(s => parseFloat(s.trim())).filter(n => !isNaN(n) && n > 0);
    wkt.anilhas = [...new Set(anilhasInp)].sort((a, b) => b - a);   // dedup + grande → pequeno
    if (!wkt.anilhas.length) wkt.anilhas = _anilhasDefault(wkt.unidade);
    wkt.movimentos = [];
    wkt.time_cap = '';
    delete wkt.formula1;
    delete wkt.formula2;
  } else {
    wkt.movimentos = getMovTableArray('main');
    delete wkt.formula1;
    delete wkt.formula2;
  }
}

function _aposSalvarWorkout(moveu) {
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
  invalidatePreviewCache();
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
    } else if (t === 'secao') {
      const txt = row.querySelector('.mi-secao-input').value.trim();
      if (txt) arr.push({ secao: txt.toUpperCase() });
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
      // Tiebreak: checkbox 'TB' marca o mov como checkpoint inline
      const tbBox = row.querySelector('.mi-tb');
      if (tbBox && tbBox.checked) mov.tiebreak = true;
      // Progressivo: checkbox 'PG' marca mov pra ter reps crescentes por round
      const pgBox = row.querySelector('.mi-pg');
      if (pgBox && pgBox.checked) mov.progressivo = true;
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
  } else if (mov.secao !== undefined) {
    row.className = 'mov-row secao-row';
    row.dataset.type = 'secao';
    row.innerHTML = `<span class="mi-secao-mark">§</span>
      <input class="mi-secao-input" value="${esc(mov.secao || '')}"
        placeholder="Ex: PART 1 (00:00-06:00)"
        style="flex:1;font-weight:700;letter-spacing:.05em;text-transform:uppercase">
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
      <label class="mi-tb-wrap" title="Tiebreak: insere campo escrevível após este movimento" aria-label="Tiebreak após este movimento">
        <input type="checkbox" class="mi-tb" ${mov.tiebreak ? 'checked' : ''}>
        <span>TB</span>
      </label>
      <label class="mi-tb-wrap mi-pg-wrap" title="Progressivo: reps deste movimento crescem por round (AMRAP/EMOM)" aria-label="Movimento progressivo">
        <input type="checkbox" class="mi-pg" ${mov.progressivo ? 'checked' : ''}>
        <span>PG</span>
      </label>
      <div class="mi-ctrl">${ctrlBtns(section)}</div>`;
  }
  body.appendChild(row);
}

function ctrlBtns(section) {
  return `<button class="icon-btn" onclick="movUp(this)" title="Subir" aria-label="Mover movimento pra cima">↑</button>
    <button class="icon-btn danger" onclick="removeRow(this)" title="Remover" aria-label="Remover movimento">×</button>`;
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

function addSecao(section) {
  appendMovRow(section, { secao: 'PART 1 (00:00-06:00)' });
  // Foca o campo recém-adicionado pra editar
  const body = document.getElementById(bodyId(section));
  const last = body.lastElementChild;
  if (last) { const inp = last.querySelector('.mi-secao-input'); if (inp) { inp.focus(); inp.select(); } }
}

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
// Cache de preview por path+hash do workout. Evita refazer fetch quando o
// usuário alterna entre workouts sem ter editado nada. Limpa quando o user
// edita um workout (invalidatePreviewCache chamado em salvarWorkout).
let _previewCache = new Map();   // key = JSON da chave → blob URL
let _previewPending = null;       // AbortController da request em voo
let _previewDebounce = null;      // timer pra cancelar requests rapidas

function _previewCacheKey(path, wkt) {
  // Hash leve: tipo + nome + nº movs + tempo + cargas. Não precisa ser perfeito —
  // só evitar refetch quando NADA mudou. Se houver miss, faz fetch (sem custo).
  const movs = (wkt.movimentos || []).length;
  const f1Movs = (wkt.formula1 && wkt.formula1.movimentos || []).length;
  return `${path.dia}|${path.cat}|${path.wkt}|${wkt.tipo}|${wkt.nome}|${movs}+${f1Movs}|${wkt.time_cap || ''}`;
}

function invalidatePreviewCache() {
  // Limpa todos os blob URLs e o cache. Chamado quando workouts mudam.
  for (const url of _previewCache.values()) {
    if (url && url.startsWith('blob:')) URL.revokeObjectURL(url);
  }
  _previewCache.clear();
}

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
  const pbName = document.getElementById('pbName');
  if (pbName) pbName.textContent = breadcrumb;
  const empty = document.getElementById('previewEmpty');
  if (empty) empty.style.display = 'none';
  const frame = document.getElementById('previewFrame');
  if (!frame) return;
  frame.style.display = 'block';

  // Cache hit: serve direto do blob salvo (instantâneo)
  const key = _previewCacheKey(path, wkt);
  if (_previewCache.has(key)) {
    frame.src = _previewCache.get(key);
    return;
  }

  // Debounce 150ms: rapid switches entre workouts cancelam request anterior
  if (_previewDebounce) clearTimeout(_previewDebounce);
  if (_previewPending) { try { _previewPending.abort(); } catch (e) {} }
  _previewDebounce = setTimeout(() => {
    _previewPending = new AbortController();
    apiFetch('/api/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config, dia_idx: path.dia, cat_idx: path.cat, wkt_idx: path.wkt }),
      signal: _previewPending.signal,
    })
    .then(r => { if (!r.ok) throw new Error('Erro ' + r.status); return r.text(); })
    .then(html => {
      const blob = new Blob([html], { type: 'text/html' });
      const url = URL.createObjectURL(blob);
      const old = frame.src;
      frame.src = url;
      _previewCache.set(key, url);
      if (old && old.startsWith('blob:') && !Array.from(_previewCache.values()).includes(old)) {
        URL.revokeObjectURL(old);
      }
    })
    .catch(e => {
      if (e.name === 'AbortError') return;   // user clicou outro workout — OK
      toast('Erro no preview: ' + e.message, 'err');
    });
  }, 150);
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

  apiFetch('/api/generate', {
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
    apiFetch('/api/import/' + type, {
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
  // Logos em base64 são responsáveis pela maior parte do tamanho. Se passarem
  // de ~500KB no total, oferece exportar sem logos (arquivo mais leve, com
  // custo de precisar reupload depois).
  const logoEvt = config.evento.logo_evento  || '';
  const logoEmp = config.evento.logo_empresa || '';
  const logosBytes = (logoEvt.length + logoEmp.length);
  let snapshot = { version: SCHEMA_VERSION, config, diaAtual, exportedAt: new Date().toISOString() };
  if (logosBytes > 500 * 1024) {
    const mb = (logosBytes / 1024 / 1024).toFixed(1);
    const incluir = confirm(
      `Logos somam ${mb} MB. Incluir no backup?\n\n` +
      `OK = incluir logos (arquivo maior)\n` +
      `Cancelar = sem logos (você precisa reupload ao restaurar)`
    );
    if (!incluir) {
      snapshot = JSON.parse(JSON.stringify(snapshot));   // clona pra não mexer no config vivo
      snapshot.config.evento.logo_evento  = '';
      snapshot.config.evento.logo_empresa = '';
    }
  }
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
  invalidatePreviewCache();   // dados novos — cache antigo é inválido
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

  // Avisos do parser (ex: atletas descartados por número fora da faixa) +
  // avisos do validar_evento. IA pode explicar tudo num parágrafo só se o
  // usuário pedir (botão "Explicar com IA" no banner — opt-in pra economizar).
  const avisos = result.avisos_import || [];
  _ultimosAvisos = avisos.slice();
  _ultimosStats = {
    dias: result.dias.length,
    categorias: totalCats,
    workouts: result.dias.reduce((s, d) =>
      s + (d.categorias || []).reduce((s2, c) => s2 + (c.workouts || []).length, 0), 0),
    atletas: result.dias.reduce((s, d) =>
      s + (d.categorias || []).reduce((s2, c) =>
        s2 + (c.baterias || []).reduce((s3, b) => s3 + (b.alocacoes || []).length, 0), 0), 0),
    roster: (result.roster || []).length,
  };
  const aiBtn = document.getElementById('pibAIBtn');
  if (aiBtn) aiBtn.style.display = (avisos.length && chatAIAtiva) ? '' : 'none';
  if (avisos.length) {
    console.warn(`Import com ${avisos.length} aviso(s):`, avisos);
    const msgToast = chatAIAtiva
      ? `${avisos.length} aviso(s) — clique "🤖 Explicar com IA" pra detalhes`
      : `${avisos.length} aviso(s) — veja console (F12) ou rode Validar`;
    toast(msgToast, 'warn');
  }
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
  if (!btn) return;   // elemento opcional — não derruba o import se ausente
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
  // Garante que sempre existe um evento ativo (cria 1 se for primeiro save)
  if (!eventoAtivoId) eventoAtivoId = _gerarIdEvento(config.evento.nome);
  const multi = _carregarMultiState() || { version: SCHEMA_VERSION, activeId: eventoAtivoId, events: {} };
  multi.activeId = eventoAtivoId;
  multi.version  = SCHEMA_VERSION;
  multi.events[eventoAtivoId] = {
    config, diaAtual,
    nome: config.evento.nome || multi.events[eventoAtivoId]?.nome || 'Evento sem nome',
    atualizadoEm: new Date().toISOString(),
  };
  let ok = false;
  try {
    localStorage.setItem(MULTI_STATE_KEY, JSON.stringify(multi));
    ok = true;
  } catch (e) {
    try {
      // Cota cheia: tenta sem logos do evento ativo
      const lite = JSON.parse(JSON.stringify(multi));
      lite.events[eventoAtivoId].config.evento.logo_evento = '';
      lite.events[eventoAtivoId].config.evento.logo_empresa = '';
      localStorage.setItem(MULTI_STATE_KEY, JSON.stringify(lite));
      console.warn('Persistência sem logos (cota cheia):', e.message);
      ok = true;
    } catch (e2) {
      console.error('Falha ao persistir:', e2);
    }
  }
  updateClearAllVisibility();
  setSaveIndicator(ok ? 'saved' : 'error');
}

// Setter de multi-state com feedback. Retorna true se gravou, false e mostra
// toast se falhou (tipicamente cota cheia: 5MB de localStorage).
function _salvarMultiState(multi, contexto = 'salvar') {
  try {
    localStorage.setItem(MULTI_STATE_KEY, JSON.stringify(multi));
    return true;
  } catch (e) {
    console.error(`Falha ao ${contexto}:`, e);
    toast(`Falha ao ${contexto} (cota do navegador cheia?). Exporte JSON pra preservar`, 'err');
    return false;
  }
}

function _carregarMultiState() {
  try {
    const raw = localStorage.getItem(MULTI_STATE_KEY);
    if (!raw) return null;
    const m = JSON.parse(raw);
    if (!m || typeof m !== 'object' || m.version !== SCHEMA_VERSION) return null;
    return m;
  } catch (e) { return null; }
}

function _gerarIdEvento(nome) {
  const slug = (nome || 'evento').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'evento';
  // Sufixo: timestamp + 4 chars aleatórios pra evitar colisão em chamadas
  // muito rápidas (raras em uso humano mas possíveis em scripts/migração)
  const rand = Math.random().toString(36).slice(2, 6);
  return `${slug}-${Date.now().toString(36)}-${rand}`;
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
  // 1) Tenta carregar formato v3 (multi-evento)
  const multi = _carregarMultiState();
  if (multi && multi.activeId && multi.events[multi.activeId]) {
    _carregarEventoAtivo(multi, multi.activeId);
    return;
  }

  // 2) Migração v2 → v3: state antigo é convertido pra primeiro evento
  try {
    const rawLegado = localStorage.getItem(STATE_KEY);
    if (rawLegado) {
      const v2 = JSON.parse(rawLegado);
      if (v2 && v2.config) {
        eventoAtivoId = _gerarIdEvento(v2.config?.evento?.nome);
        if (!v2.config.evento.logo_empresa) v2.config.evento.logo_empresa = DS_LOGO_PADRAO;
        config = { ...config, ...v2.config };
        if (typeof v2.diaAtual === 'number') diaAtual = v2.diaAtual;
        _persistNow();   // grava no formato novo
        localStorage.removeItem(STATE_KEY);   // descarta legado
        setSaveIndicator('saved');
        console.info('localStorage migrado v2 → v3 (multi-evento).');
        return;
      }
    }
  } catch (e) {
    console.warn('Falha ao migrar state v2:', e);
  }
}

function _carregarEventoAtivo(multi, id) {
  const ev = multi.events[id];
  if (!ev || !ev.config) return;
  eventoAtivoId = id;
  if (!ev.config.evento.logo_empresa) ev.config.evento.logo_empresa = DS_LOGO_PADRAO;
  config = { ...config, ...ev.config };
  diaAtual = typeof ev.diaAtual === 'number' ? ev.diaAtual : 0;
  catSel = 0; catListOpen = false;
  previewPath = null;
  setSaveIndicator('saved');
}

function clearState() {
  // Remove SÓ o evento ativo (mantém os outros)
  if (!eventoAtivoId) {
    try {
      localStorage.removeItem(MULTI_STATE_KEY);
      localStorage.removeItem(STATE_KEY);
      localStorage.removeItem(IMPORT_KEY);
    } catch (e) { /* ignore */ }
    setSaveIndicator(null);
    return;
  }
  const multi = _carregarMultiState();
  if (multi && multi.events[eventoAtivoId]) {
    delete multi.events[eventoAtivoId];
    // Pega o próximo evento existente como ativo, ou zera
    const restantes = Object.keys(multi.events);
    multi.activeId = restantes[0] || null;
    if (multi.activeId) {
      _salvarMultiState(multi, 'apagar evento');
    } else {
      try { localStorage.removeItem(MULTI_STATE_KEY); } catch (e) { /* remove não estoura cota */ }
    }
  }
  eventoAtivoId = null;
  try { localStorage.removeItem(IMPORT_KEY); } catch (e) {}
  setSaveIndicator(null);
}

// ─── API pública multi-evento ───────────────────────────────────────────────
// Lista eventos: por default só ativos (flag archived !== true). Passa
// `incluirArquivados=true` pra ver arquivados também.
function listarEventos(incluirArquivados = false) {
  const m = _carregarMultiState();
  if (!m) return [];
  return Object.entries(m.events)
    .filter(([_, ev]) => incluirArquivados || !ev.archived)
    .map(([id, ev]) => ({
      id,
      nome: ev.nome || ev.config?.evento?.nome || 'Sem nome',
      totalDias: (ev.config?.dias || []).length,
      totalCategorias: (ev.config?.dias || []).reduce((s, d) => s + (d.categorias || []).length, 0),
      atualizadoEm: ev.atualizadoEm,
      ativo: id === m.activeId,
      archived: !!ev.archived,
    }))
    .sort((a, b) => (b.atualizadoEm || '').localeCompare(a.atualizadoEm || ''));
}

function trocarEvento(id) {
  const m = _carregarMultiState();
  if (!m || !m.events[id]) { toast('Evento não encontrado', 'err'); return; }
  // Garante que o estado atual está salvo antes de trocar
  if (eventoAtivoId && eventoAtivoId !== id) _persistNow();
  _carregarEventoAtivo(m, id);
  // Sincroniza inputs e re-renderiza
  document.getElementById('evNome').value = config.evento.nome || '';
  document.getElementById('evCat').value  = config.evento.categoria || '';
  document.getElementById('evData').value = config.evento.data || '';
  renderEventoDisplay();
  renderDiaTabs();
  renderCategoriasList();
  atualizarBotaoGerar();
  updateClearAllVisibility();
  updateEmptyState();
  document.getElementById('previewFrame').style.display = 'none';
  document.getElementById('pbName').textContent = '—';
  // Atualiza no localStorage (muda activeId)
  m.activeId = id;
  _salvarMultiState(m, 'trocar evento');
  fecharEventos();
  toast(`Evento "${m.events[id].nome}" carregado`, 'ok');
}

function novoEvento() {
  const nome = prompt('Nome do novo evento:');
  if (nome === null) return;
  const nomeFinal = (nome || '').trim();
  if (!nomeFinal) { toast('Nome obrigatório', 'err'); return; }
  // Salva o estado atual antes de criar novo
  if (eventoAtivoId) _persistNow();
  eventoAtivoId = _gerarIdEvento(nomeFinal);
  config = {
    evento: { nome: nomeFinal, categoria: '', data: '', logo_empresa: DS_LOGO_PADRAO, logo_evento: '' },
    dias: [], roster: [],
  };
  diaAtual = 0; catSel = 0; catListOpen = false;
  previewPath = null; editingPath = null;
  ['evNome','evCat','evData'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = id === 'evNome' ? nomeFinal : '';
  });
  renderEventoDisplay();
  renderDiaTabs();
  renderCategoriasList();
  atualizarBotaoGerar();
  updateClearAllVisibility();
  updateEmptyState();
  document.getElementById('previewFrame').style.display = 'none';
  document.getElementById('pbName').textContent = '—';
  saveState();
  fecharEventos();
  toast(`Evento "${nomeFinal}" criado`, 'ok');
}

function duplicarEvento(id) {
  const m = _carregarMultiState();
  if (!m || !m.events[id]) return;
  const novoNome = prompt('Nome do evento duplicado:', `${m.events[id].nome} (cópia)`);
  if (novoNome === null) return;
  const nomeFinal = (novoNome || '').trim();
  if (!nomeFinal) { toast('Nome obrigatório', 'err'); return; }
  const novoId = _gerarIdEvento(nomeFinal);
  const clone = JSON.parse(JSON.stringify(m.events[id]));
  clone.nome = nomeFinal;
  clone.config.evento.nome = nomeFinal;
  clone.atualizadoEm = new Date().toISOString();
  m.events[novoId] = clone;
  if (!_salvarMultiState(m, 'duplicar')) return;
  renderListaEventos();
  toast(`Evento duplicado como "${nomeFinal}"`, 'ok');
}

function renomearEvento(id) {
  const m = _carregarMultiState();
  if (!m || !m.events[id]) return;
  const novoNome = prompt('Novo nome:', m.events[id].nome);
  if (novoNome === null) return;
  const nomeFinal = (novoNome || '').trim();
  if (!nomeFinal) { toast('Nome obrigatório', 'err'); return; }
  // Recria ID pra que o slug acompanhe o nome novo (afeta export JSON e
  // futuras URLs de compartilhamento). Move o evento sob chave nova,
  // remove antiga, ajusta activeId/eventoAtivoId se necessário.
  const novoId = _gerarIdEvento(nomeFinal);
  m.events[novoId] = m.events[id];
  m.events[novoId].nome = nomeFinal;
  m.events[novoId].config.evento.nome = nomeFinal;
  m.events[novoId].atualizadoEm = new Date().toISOString();
  delete m.events[id];
  if (m.activeId === id) m.activeId = novoId;
  if (eventoAtivoId === id) eventoAtivoId = novoId;
  if (!_salvarMultiState(m, 'renomear')) return;
  if (eventoAtivoId === novoId) {
    config.evento.nome = nomeFinal;
    document.getElementById('evNome').value = nomeFinal;
    renderEventoDisplay();
  }
  renderListaEventos();
  toast('Renomeado', 'ok');
}

function arquivarEvento(id) {
  const m = _carregarMultiState();
  if (!m || !m.events[id]) return;
  if (!confirm(`Arquivar "${m.events[id].nome}"?\nPode restaurar depois em "Ver arquivados".`)) return;
  m.events[id].archived = true;
  // Se arquivou o ativo, escolhe outro ativo entre os não-arquivados
  if (m.activeId === id) {
    const restantes = Object.entries(m.events).filter(([_, ev]) => !ev.archived);
    m.activeId = restantes.length ? restantes[0][0] : null;
  }
  if (!_salvarMultiState(m, 'arquivar')) return;
  // Se arquivou o ativo, troca pra outro (ou limpa)
  if (id === eventoAtivoId) {
    if (m.activeId) {
      trocarEvento(m.activeId);
      return;
    }
    eventoAtivoId = null;
    limparTudo();
    return;
  }
  renderListaEventos();
  toast('Evento arquivado', 'ok');
}

function restaurarEvento(id) {
  const m = _carregarMultiState();
  if (!m || !m.events[id]) return;
  m.events[id].archived = false;
  m.events[id].atualizadoEm = new Date().toISOString();
  if (!_salvarMultiState(m, 'restaurar')) return;
  renderListaEventos();
  toast('Evento restaurado', 'ok');
}

function excluirDefinitivamente(id) {
  const m = _carregarMultiState();
  if (!m || !m.events[id]) return;
  if (!confirm(`Excluir DEFINITIVAMENTE "${m.events[id].nome}"?\nEsta ação não pode ser desfeita.`)) return;
  delete m.events[id];
  if (m.activeId === id) m.activeId = null;
  if (!_salvarMultiState(m, 'excluir')) return;
  renderListaEventos();
  toast('Evento excluído', 'ok');
}

// Estado da UI: mostrar arquivados na listagem?
let _mostrarArquivados = false;
function toggleArquivados() {
  _mostrarArquivados = !_mostrarArquivados;
  renderListaEventos();
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
  apiFetch('/api/status').then(r=>r.json()).then(s => {
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

  // Sincronização entre abas do mesmo navegador: se outra aba mudar o
  // localStorage (criar/trocar/arquivar evento), avisa pra recarregar pra
  // evitar conflito (cada aba tem `eventoAtivoId` próprio em memória, e
  // _persistNow sobrescreveria o mapa inteiro).
  window.addEventListener('storage', (e) => {
    if (e.key !== MULTI_STATE_KEY) return;
    toast('Outra aba alterou o estado. Recarregando…', 'warn');
    setTimeout(() => location.reload(), 1500);
  });

  // Esc fecha o modal mais "em cima" (último aberto vence). Ordem reflete
  // hierarquia visual: Ajuda > Eventos > Configurar > Validação > Chat.
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    const aberto = (id) => {
      const el = document.getElementById(id);
      return el && el.style.display && el.style.display !== 'none';
    };
    if (aberto('ajudaModal'))   { fecharAjuda();    return; }
    if (aberto('eventosModal')) { fecharEventos();  return; }
    if (aberto('configModal'))  { fecharConfig();   return; }
    if (aberto('validModal'))   { fecharValidacao(); return; }
    if (aberto('chatPanel'))    { toggleChat();     return; }
  });
})();
