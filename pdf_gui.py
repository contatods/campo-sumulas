#!/usr/bin/env python3
"""Interface local do gerador de PDFs por bateria.

Duplo clique (via "Gerar PDFs.command" / "Gerar PDFs.bat") sobe um servidor
local e abre a página no navegador: escolher ZIP + cronograma, acompanhar o
progresso ao vivo e abrir a pasta no final. Mesma stack do app de súmulas —
stdlib + HTML/CSS/JS puro, sem dependências.

A conversão em si é o gerar_pdfs.converter (Chrome/Edge headless).
"""

import base64
import json
import os
import subprocess
import sys
import shutil
import tempfile
import threading
import time
import webbrowser
import zipfile
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gerar_pdfs import (achar_chrome, converter, carregar_horarios,
                        carregar_horarios_excel, finais_do_excel,
                        arenas_do_excel)

PORTAS = range(8777, 8798)
MAX_BODY = 600 * 1024 * 1024          # ZIP de evento grande em base64
CHROME = achar_chrome()

# Pastas vasculhadas pra montar as listas de arquivos recentes
def _pastas_busca():
    home = Path.home()
    return [home / "Downloads", home / "Desktop", home / "Mesa"]


def _listar(globs, limite=15):
    achados = []
    for pasta in _pastas_busca():
        if not pasta.is_dir():
            continue
        for padrao in globs:
            for f in pasta.glob(padrao):
                if f.name.startswith("."):
                    continue
                try:
                    st = f.stat()
                except OSError:
                    continue
                achados.append({
                    "nome": f.name,
                    "caminho": str(f),
                    "mb": round(st.st_size / 1e6, 1),
                    "mtime": int(st.st_mtime),
                })
    achados.sort(key=lambda a: -a["mtime"])
    return achados[:limite]


def _abrir_pasta(caminho):
    if sys.platform == "darwin":
        subprocess.Popen(["open", caminho])
    elif sys.platform == "win32":
        os.startfile(caminho)                     # noqa — só existe no Windows
    else:
        subprocess.Popen(["xdg-open", caminho])


def _carregar_cronograma(caminho):
    """Excel ou JSON → mapa de horários (ou levanta RuntimeError)."""
    if caminho.lower().endswith(".json"):
        return carregar_horarios(caminho)
    return carregar_horarios_excel(caminho)


def _base_dir():
    """Pasta dos recursos (fontes, logo). Rodando normal = pasta deste
    arquivo; congelado num app (PyInstaller) = pasta de dados do bundle."""
    if getattr(sys, 'frozen', False):
        return Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def _font_data_uri(nome):
    """woff2 de fonts/ como data: URI — as MESMAS fontes self-hosted do site
    de eventos (Barlow Condensed 900 / IBM Plex Mono 600). Ausente → string
    vazia e o CSS cai no fallback de sistema."""
    f = _base_dir() / "fonts" / nome
    if f.exists():
        return "data:font/woff2;base64," + base64.b64encode(f.read_bytes()).decode()
    return ""


FONT_BARLOW = _font_data_uri("barlow-condensed-900-latin.woff2")
FONT_PLEX = _font_data_uri("ibm-plex-mono-600-latin.woff2")


PAGINA = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PDFs por Bateria — Digital Score</title>
<style>
/* Tokens herdados do design system do site de eventos (Equipe/tokens.css) */
{{FONT_FACES}}
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0a0a0a;--surface:rgba(255,255,255,.04);--surface-hi:rgba(255,255,255,.07);
  --bord:rgba(255,255,255,.1);--bord2:rgba(255,255,255,.2);
  --lar:#ed7601;--lar2:#ff9238;--lar-soft:rgba(237,118,1,.14);--lar-bord:rgba(237,118,1,.42);
  --cream:#f4f1ea;--tx:#c2bfb6;--mut:#95918a;--dim:#6d6a64;
  --ok:#58d68d;--okbg:rgba(88,214,141,.1);--okbd:rgba(88,214,141,.35);
}
.mono{font-family:'IBM Plex Mono','JetBrains Mono',ui-monospace,Menlo,monospace;
      text-transform:uppercase;letter-spacing:.28em;font-weight:600}
.disp{font-family:'Barlow Condensed','Oswald','Arial Narrow',Impact,sans-serif;
      text-transform:uppercase;font-weight:900;letter-spacing:-0.02em}
body{
  background:repeating-linear-gradient(135deg,transparent 0 26px,rgba(237,118,1,.018) 26px 27px),var(--bg);
  color:var(--tx);font:15px/1.55 'Inter',-apple-system,'Segoe UI',Roboto,sans-serif;
  min-height:100vh;display:flex;flex-direction:column;align-items:center;
}
/* top status strip */
.strip{width:100%;border-bottom:1px solid var(--bord);background:rgba(0,0,0,.35)}
.strip-in{max-width:880px;margin:0 auto;padding:11px 24px;display:flex;justify-content:space-between;
  align-items:center;font-size:10px}
.strip-in .l{color:var(--mut)}
.strip-in .r{color:var(--lar);display:flex;align-items:center;gap:8px}
.dot{width:7px;height:7px;border-radius:50%;background:var(--lar);box-shadow:0 0 8px var(--lar);animation:pulse 2.2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
main{width:100%;max-width:880px;padding:34px 24px 40px;display:flex;flex-direction:column;gap:16px}
/* header */
header{display:flex;align-items:center;gap:20px;margin-bottom:10px}
header img{height:52px;border-radius:6px;flex-shrink:0}
.kick{font-size:0.72rem;color:var(--lar);display:flex;align-items:center;gap:12px;margin-bottom:8px}
.kick::before{content:"";width:26px;height:2px;background:var(--lar)}
header h1{font-size:clamp(38px,6vw,52px);line-height:.88;color:var(--cream)}
header h1 b{color:var(--lar);font-weight:900}
.sub{color:var(--mut);font-size:13px;margin-top:10px;max-width:52ch}
/* cards — mesmo desenho dos pdf-tile do site: surface translúcida, traço
   accent à esquerda e motif corner (hairlines mascaradas no canto) */
.card{background:var(--surface);border:1px solid var(--bord);border-left:3px solid var(--lar);
  border-radius:4px;padding:18px 20px;position:relative;overflow:hidden}
.card::after{content:"";position:absolute;top:0;right:0;width:120px;height:120px;pointer-events:none;
  background:repeating-linear-gradient(135deg,transparent 0 8px,rgba(237,118,1,.08) 8px 9px);
  -webkit-mask:linear-gradient(225deg,black 30%,transparent 75%);
  mask:linear-gradient(225deg,black 30%,transparent 75%)}
.card>*{position:relative;z-index:1}
.lbl{font-size:0.72rem;color:var(--lar);margin-bottom:13px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.lbl .n{color:var(--cream)}
.lbl .opt{color:var(--dim);letter-spacing:.02em;text-transform:none;font-weight:400;
  font-family:'Inter',-apple-system,'Segoe UI',sans-serif;font-size:11.5px}
.recarregar{margin-left:auto;color:var(--mut);font-size:9.5px;text-decoration:none;letter-spacing:.12em;
  font-family:'IBM Plex Mono',ui-monospace,monospace}
.recarregar:hover{color:var(--lar)}
select{width:100%;background:rgba(0,0,0,.45);color:var(--cream);border:1px solid var(--bord2);border-radius:4px;
  padding:11px 13px;font-size:13px;font-family:'IBM Plex Mono',ui-monospace,Menlo,monospace;
  letter-spacing:.02em;appearance:auto;cursor:pointer}
select:focus{outline:none;border-color:var(--lar-bord)}
.drop{margin-top:9px;border:1px dashed var(--bord2);border-radius:4px;padding:9px 12px;color:var(--mut);
  font-size:11.5px;text-align:center;cursor:pointer;transition:.18s}
.drop:hover,.drop.over{border-color:var(--lar-bord);color:var(--lar);background:var(--lar-soft)}
.drop input{display:none}
.escolhido{margin-top:9px;font-size:11.5px;color:var(--lar);word-break:break-all;
  font-family:'IBM Plex Mono',ui-monospace,monospace}
/* o que gerar (checkboxes no estilo do site) */
.saidas{display:flex;gap:10px;flex-wrap:wrap}
.saida{flex:1;min-width:180px;display:flex;align-items:flex-start;gap:10px;padding:11px 13px;
  background:rgba(0,0,0,.35);border:1px solid var(--bord);border-radius:4px;cursor:pointer;
  transition:.15s;user-select:none}
.saida:hover{border-color:var(--lar-bord)}
.saida input{appearance:none;width:15px;height:15px;margin-top:2px;flex-shrink:0;cursor:pointer;
  border:1.5px solid var(--bord2);border-radius:3px;background:transparent;position:relative;transition:.15s}
.saida input:checked{background:var(--lar);border-color:var(--lar)}
.saida input:checked::after{content:"";position:absolute;left:4px;top:1px;width:4px;height:8px;
  border:solid #0a0a0a;border-width:0 2px 2px 0;transform:rotate(45deg)}
.saida.off{opacity:.45}
.saida b{display:block;font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:11px;
  letter-spacing:.1em;text-transform:uppercase;color:var(--cream);font-weight:600}
.saida small{display:block;color:var(--mut);font-size:10.5px;line-height:1.4;margin-top:3px}
/* selo */
.selo{margin-top:10px;font-size:11.5px;display:none;padding:9px 12px;border-radius:4px;line-height:1.5;
  font-family:'IBM Plex Mono',ui-monospace,Menlo,monospace}
.selo.ok{display:block;color:var(--ok);background:var(--okbg);border:1px solid var(--okbd)}
.selo.warn{display:block;color:#f5b041;background:rgba(245,176,65,.09);border:1px solid rgba(245,176,65,.35)}
.selo.chk{display:block;color:var(--mut);background:var(--surface);border:1px solid var(--bord)}
/* generate */
#btnGerar{background:var(--lar);color:#0a0a0a;border:0;border-radius:6px;padding:15px;cursor:pointer;
  font-family:'Barlow Condensed','Oswald','Arial Narrow',Impact,sans-serif;text-transform:uppercase;
  font-weight:900;font-size:26px;letter-spacing:.08em;transition:.18s;margin-top:2px}
#btnGerar:hover{background:var(--lar2)}
#btnGerar:disabled{background:rgba(255,255,255,.08);color:var(--dim);cursor:default}
#aviso{background:rgba(231,76,60,.09);border:1px solid rgba(231,76,60,.4);color:#f0a297;border-radius:4px;
  padding:12px 14px;font-size:13px;display:none}
/* progress */
#prog{display:none}
.barra{height:8px;background:rgba(0,0,0,.5);border:1px solid var(--bord);border-radius:2px;overflow:hidden;margin:13px 0 9px}
.barra i{display:block;height:100%;width:0;background:var(--lar);transition:width .25s;box-shadow:0 0 10px var(--lar)}
#progTxt{font-size:11.5px;color:var(--mut);font-family:'IBM Plex Mono',ui-monospace,monospace;letter-spacing:.06em}
#log{background:rgba(0,0,0,.5);border:1px solid var(--bord);border-radius:4px;margin-top:12px;padding:11px 13px;
  font:11px/1.6 'IBM Plex Mono',ui-monospace,Menlo,monospace;color:var(--tx);max-height:170px;
  overflow-y:auto;white-space:pre-wrap;display:none}
/* done */
#fim{display:none;text-align:center}
#fim .big{font-size:34px;color:var(--cream);line-height:1}
#fim .big span{color:var(--ok)}
#fim .pasta{font-size:11px;color:var(--mut);word-break:break-all;margin:10px 0 17px;
  font-family:'IBM Plex Mono',ui-monospace,monospace}
#btnAbrir{background:transparent;color:var(--lar);border:1.5px solid var(--lar-bord);border-radius:6px;padding:12px 32px;
  font-family:'Barlow Condensed','Oswald','Arial Narrow',Impact,sans-serif;text-transform:uppercase;
  font-weight:800;font-size:19px;letter-spacing:.08em;cursor:pointer;transition:.18s}
#btnAbrir:hover{background:var(--lar);border-color:var(--lar);color:#0a0a0a}
footer{width:100%;max-width:880px;padding:20px 24px 30px;color:var(--dim);font-size:9.5px;
  border-top:1px solid var(--bord);margin-top:6px;display:flex;justify-content:space-between;gap:14px;flex-wrap:wrap}
</style>
</head>
<body>
<div class="strip"><div class="strip-in mono">
  <span class="l">Súmulas · Digital Score</span>
  <span class="r"><i class="dot"></i>Conversão Local</span>
</div></div>
<main>
  <header>
    <img src="/logo.png" alt="" onerror="this.style.display='none'">
    <div>
      <div class="kick mono">Área de Impressão</div>
      <h1 class="disp">PDFs por <b>Bateria</b></h1>
      <div class="sub">Converte as súmulas em PDF — um por bateria + o dia inteiro em ordem cronológica.</div>
    </div>
  </header>

  <div id="aviso"></div>

  <div class="card">
    <div class="lbl mono"><span class="n">01</span> · ZIP de Súmulas
      <a class="recarregar" href="#" onclick="carregar();return false">↻ Atualizar</a></div>
    <select id="selZip"></select>
    <label class="drop" id="dropZip">…ou clique / arraste o arquivo .zip aqui
      <input type="file" accept=".zip" onchange="upload(this,'zip')"></label>
    <div class="escolhido" id="escZip"></div>
  </div>

  <div class="card">
    <div class="lbl mono"><span class="n">02</span> · Cronograma
      <span class="opt">— Excel de programação ou backup JSON (opcional, ordena o dia completo por horário)</span></div>
    <select id="selCron" onchange="checarCron()"></select>
    <label class="drop" id="dropCron">…ou clique / arraste o .xlsx / .json aqui
      <input type="file" accept=".xlsx,.xlsm,.json" onchange="upload(this,'cron')"></label>
    <div class="escolhido" id="escCron"></div>
    <div class="selo" id="seloCron"></div>
  </div>

  <div class="card">
    <div class="lbl mono"><span class="n">03</span> · O que gerar</div>
    <div class="saidas">
      <label class="saida"><input type="checkbox" id="sBaterias" checked onchange="this.closest('.saida').classList.toggle('off',!this.checked)">
        <span><b>PDFs por bateria</b><small>um PDF por bateria, em pastas por categoria — o maço de cada head judge</small></span></label>
      <label class="saida"><input type="checkbox" id="sDia" checked onchange="this.closest('.saida').classList.toggle('off',!this.checked)">
        <span><b>Dia completo</b><small>tudo num PDF só, em ordem horário → bateria → raia (impressão em lote)</small></span></label>
      <label class="saida"><input type="checkbox" id="sFinais" checked onchange="this.closest('.saida').classList.toggle('off',!this.checked)">
        <span><b>Finais</b><small>00_FINAIS.pdf com as baterias "(Final Heat)" — precisa do Excel no passo 2</small></span></label>
      <label class="saida off"><input type="checkbox" id="sArenas" onchange="this.closest('.saida').classList.toggle('off',!this.checked)">
        <span><b>Por arena</b><small>evento multi-arena: uma pilha cronológica por arena (00_ARENA_*.pdf) — precisa do Excel no passo 2</small></span></label>
    </div>
  </div>

  <button id="btnGerar" onclick="gerar()">Gerar PDFs</button>

  <div class="card" id="prog">
    <div class="lbl mono"><span class="n">▶</span> Convertendo</div>
    <div class="barra"><i id="barra"></i></div>
    <div id="progTxt">preparando…</div>
    <div id="log"></div>
  </div>

  <div class="card" id="fim">
    <div class="big disp">PDFs <span>Prontos</span></div>
    <div class="pasta" id="fimPasta"></div>
    <button id="btnAbrir" onclick="abrirPasta()">Abrir pasta</button>
  </div>
</main>
<footer>
  <span class="mono">Digital Score · Súmulas</span>
  <span class="mono">Chrome/Edge local · idêntico ao Ctrl+P · v{{VERSAO}}</span>
</footer>
<script>
let upZip = null, upCron = null, pastaFinal = '';

function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML}

function carregar(){
  fetch('/api/arquivos').then(r=>r.json()).then(d=>{
    if(!d.chrome){
      const a=document.getElementById('aviso');
      a.style.display='block';
      a.textContent='Navegador não encontrado: instale o Google Chrome (no Windows o Edge também serve) e recarregue a página.';
      document.getElementById('btnGerar').disabled=true;
    }
    const fill=(sel,itens,vazio)=>{
      sel.innerHTML='<option value="">'+vazio+'</option>'+itens.map(a=>
        `<option value="${esc(a.caminho)}">${esc(a.nome)}  ·  ${a.mb} MB</option>`).join('');
    };
    fill(document.getElementById('selZip'), d.zips, '— escolha o ZIP (recentes de Downloads/Mesa) —');
    fill(document.getElementById('selCron'), d.crons, '— sem cronograma —');
  });
}

function upload(inp, tipo){
  const f = inp.files[0];
  if(!f) return;
  const r = new FileReader();
  r.onload = () => {
    const b64 = r.result.split(',')[1];
    if(tipo==='zip'){ upZip={nome:f.name,b64}; document.getElementById('escZip').textContent='⬆ '+f.name; document.getElementById('selZip').value=''; }
    else { upCron={nome:f.name,b64}; document.getElementById('escCron').textContent='⬆ '+f.name; document.getElementById('selCron').value=''; checarCron(); }
  };
  r.readAsDataURL(f);
}

// Valida o cronograma escolhido (dropdown ou upload): confirma quantos
// horários foram lidos. Retorna o objeto {total, exemplo, ...} pra quem
// quiser decidir (o gerar() usa pra avisar antes de sair fora de ordem).
async function checarCron(){
  const sel = document.getElementById('selCron').value;
  const selo = document.getElementById('seloCron');
  let body = null;
  if(upCron) body = {cron_nome:upCron.nome, cron_b64:upCron.b64};
  else if(sel) body = {cron_caminho:sel};
  if(!body){ selo.className='selo'; selo.textContent=''; return {total:0, nenhum:true}; }
  selo.className='selo chk'; selo.textContent='conferindo o arquivo…';
  let d;
  try{
    const r = await fetch('/api/cronograma',{method:'POST',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    d = await r.json();
  }catch(e){ d = {total:0, erro:'falha ao ler'}; }
  if(d.total>0){
    selo.className='selo ok';
    selo.textContent=`✓ ${d.total} horários de bateria carregados`+(d.exemplo?` (ex: ${d.exemplo})`:'')
      +(d.finais?` · ${d.finais} baterias-final → 00_FINAIS.pdf`:'');
  } else {
    selo.className='selo warn';
    selo.textContent='⚠ nenhum horário reconhecido neste arquivo'
      +(d.erro?` — ${d.erro}`:'')+'. O dia completo sairá em ordem alfabética.';
  }
  return d;
}

['dropZip','dropCron'].forEach(id=>{
  const el=document.getElementById(id);
  el.addEventListener('dragover',e=>{e.preventDefault();el.classList.add('over')});
  el.addEventListener('dragleave',()=>el.classList.remove('over'));
  el.addEventListener('drop',e=>{
    e.preventDefault();el.classList.remove('over');
    const inp=el.querySelector('input');
    inp.files=e.dataTransfer.files;
    inp.dispatchEvent(new Event('change'));
  });
});

async function gerar(){
  const zipSel = document.getElementById('selZip').value;
  if(!zipSel && !upZip){ alert('Escolha o ZIP de súmulas primeiro.'); return; }

  const saidas = [];
  if(document.getElementById('sBaterias').checked) saidas.push('baterias');
  if(document.getElementById('sDia').checked) saidas.push('dia');
  if(document.getElementById('sFinais').checked) saidas.push('finais');
  if(document.getElementById('sArenas').checked) saidas.push('arenas');
  if(!saidas.length){ alert('Marque pelo menos uma opção em "O que gerar".'); return; }
  const soExigeExcel = saidas.every(s => s==='finais' || s==='arenas');
  if(soExigeExcel){
    const temCron = document.getElementById('selCron').value || upCron;
    if(!temCron){ alert('Gerar só Finais/Por arena exige o cronograma (Excel) no passo 2 — é ele que marca as finais e as arenas.'); return; }
  }

  // Rede de segurança: revalida o cronograma na hora de gerar. Sem horários
  // (campo vazio OU arquivo sem cronograma), o dia completo sai em ordem
  // alfabética — confirma antes pra ninguém gerar fora de ordem sem querer.
  const chk = await checarCron();
  if(!chk.total){
    const msg = chk.nenhum
      ? 'Você não escolheu um cronograma.\n\nSem ele, o PDF "00_DIA_COMPLETO" sairá em ordem ALFABÉTICA por categoria — não na ordem das baterias (horário → bateria → raia). Os PDFs por bateria saem certos de qualquer jeito.\n\nGerar mesmo assim?'
      : 'O arquivo de cronograma escolhido NÃO tem horários de bateria reconhecidos.\n\nO PDF "00_DIA_COMPLETO" sairá em ordem ALFABÉTICA por categoria. Confira se escolheu o Excel de programação certo (ou o backup JSON do app).\n\nGerar mesmo assim?';
    if(!confirm(msg)) return;
  }

  const body = {saidas};
  if(upZip){ body.zip_nome=upZip.nome; body.zip_b64=upZip.b64; } else body.zip_caminho=zipSel;
  const cronSel = document.getElementById('selCron').value;
  if(upCron){ body.cron_nome=upCron.nome; body.cron_b64=upCron.b64; } else if(cronSel) body.cron_caminho=cronSel;

  document.getElementById('btnGerar').disabled = true;
  document.getElementById('fim').style.display='none';
  document.getElementById('prog').style.display='block';
  const log=document.getElementById('log'); log.style.display='block'; log.textContent='';
  const barra=document.getElementById('barra'), txt=document.getElementById('progTxt');
  txt.textContent='enviando e preparando…'; barra.style.width='2%';

  try{
    const resp = await fetch('/api/converter',{method:'POST',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let resto='';
    while(true){
      const {done,value} = await reader.read();
      if(done) break;
      resto += dec.decode(value,{stream:true});
      const linhas = resto.split('\n'); resto = linhas.pop();
      for(const l of linhas){
        if(l.startsWith('FIM_OK\t')){
          pastaFinal = l.split('\t')[1];
          document.getElementById('prog').style.display='none';
          document.getElementById('fimPasta').textContent = pastaFinal;
          document.getElementById('fim').style.display='block';
        } else if(l.startsWith('FIM_ERRO\t')){
          txt.textContent='✗ '+l.split('\t')[1];
          txt.style.color='#ff8a8a';
        } else {
          log.textContent += l+'\n'; log.scrollTop = log.scrollHeight;
          const m = l.match(/\[(\d+)\/(\d+)\]/);
          if(m){ const p=100*m[1]/m[2];
            barra.style.width=p.toFixed(1)+'%';
            txt.textContent=`${m[1]} de ${m[2]} PDFs`; }
        }
      }
    }
  }catch(e){
    txt.textContent='✗ conexão perdida: '+e.message; txt.style.color='#ff8a8a';
  }
  document.getElementById('btnGerar').disabled=false;
}

function abrirPasta(){
  fetch('/api/abrir',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({caminho:pastaFinal})});
}
carregar();
</script>
</body>
</html>
"""


class GuiHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):                    # silencia o access log
        pass

    def _send(self, code, ctype, data, extra=None):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    # ── GET ──────────────────────────────────────────────────────────────
    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/':
            faces = ""
            if FONT_BARLOW:
                faces += ("@font-face{font-family:'Barlow Condensed';font-weight:900;"
                          f"font-display:swap;src:url('{FONT_BARLOW}') format('woff2')}}\n")
            if FONT_PLEX:
                faces += ("@font-face{font-family:'IBM Plex Mono';font-weight:600;"
                          f"font-display:swap;src:url('{FONT_PLEX}') format('woff2')}}\n")
            html = (PAGINA.replace('{{FONT_FACES}}', faces)
                          .replace('{{VERSAO}}', VERSAO))
            self._send(200, 'text/html; charset=utf-8', html.encode())
        elif path == '/logo.png':
            logo = _base_dir() / 'ds_logo.png'
            if logo.exists():
                self._send(200, 'image/png', logo.read_bytes())
            else:
                self._send(404, 'text/plain', b'')
        elif path == '/api/arquivos':
            payload = {
                "chrome": bool(CHROME),
                "zips":  [z for z in _listar(["*.zip"])
                          if not z["nome"].endswith("_PDFs.zip")],
                "crons": _listar(["*.xlsx", "*.xlsm", "*.json"]),
            }
            self._send(200, 'application/json; charset=utf-8',
                       json.dumps(payload).encode())
        else:
            self._send(404, 'text/plain', b'Not found')

    # ── POST ─────────────────────────────────────────────────────────────
    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            if length <= 0 or length > MAX_BODY:
                raise ValueError("body inválido")
            body = json.loads(self.rfile.read(length))
        except Exception:
            self._send(400, 'application/json', b'{"error":"body invalido"}')
            return
        if self.path == '/api/abrir':
            caminho = body.get('caminho', '')
            if caminho and os.path.isdir(caminho):
                _abrir_pasta(caminho)
                self._send(200, 'application/json', b'{"ok":true}')
            else:
                self._send(400, 'application/json', b'{"error":"pasta nao existe"}')
        elif self.path == '/api/cronograma':
            self._validar_cronograma(body)
        elif self.path == '/api/converter':
            self._converter(body)
        else:
            self._send(404, 'text/plain', b'Rota nao encontrada')

    def _validar_cronograma(self, body):
        """Lê o cronograma escolhido e responde quantos horários tem +
        um exemplo (o da bateria mais cedo). Frontend usa pro selo verde
        e pra decidir se avisa antes de gerar fora de ordem."""
        tmp = None
        try:
            if body.get('cron_caminho'):
                caminho = body['cron_caminho']
            elif body.get('cron_b64'):
                tmp = Path(tempfile.mkdtemp(prefix='cron_'))
                caminho = str(tmp / (body.get('cron_nome') or 'cron.json'))
                Path(caminho).write_bytes(base64.b64decode(body['cron_b64']))
            else:
                self._send(200, 'application/json', b'{"total":0}')
                return
            horarios = _carregar_cronograma(caminho)
            comhora = [(v, k[2]) for k, v in horarios.items() if v]
            exemplo = ""
            if comhora:
                v, num = min(comhora)
                exemplo = f"bat {num} = {v}"
            # Finais detectadas (só de Excel) — vira selo "+ N baterias-final"
            n_finais = 0
            if not caminho.lower().endswith('.json'):
                try:
                    fin = finais_do_excel(caminho)
                    n_finais = sum(len(d.get('bats', set())) for d in fin.values())
                except Exception:
                    n_finais = 0
            self._send(200, 'application/json',
                       json.dumps({"total": len(horarios),
                                   "exemplo": exemplo,
                                   "finais": n_finais}).encode())
        except Exception as e:
            self._send(200, 'application/json',
                       json.dumps({"total": 0, "erro": str(e)}).encode())
        finally:
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)

    def _chunk(self, texto):
        data = (texto + "\n").encode('utf-8')
        self.wfile.write(f"{len(data):X}\r\n".encode() + data + b"\r\n")

    def _converter(self, body):
        """Stream de progresso em chunked encoding: cada linha do log do
        converter vira uma linha no cliente; última linha é FIM_OK/FIM_ERRO."""
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Transfer-Encoding', 'chunked')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()

        tmp = Path(tempfile.mkdtemp(prefix='pdf_gui_'))
        try:
            # ── ZIP: caminho no disco ou upload base64 ────────────────────
            if body.get('zip_caminho'):
                zip_path = Path(body['zip_caminho'])
                if not zip_path.is_file():
                    raise RuntimeError(f"ZIP não encontrado: {zip_path}")
            elif body.get('zip_b64'):
                zip_path = tmp / (body.get('zip_nome') or 'sumulas.zip')
                zip_path.write_bytes(base64.b64decode(body['zip_b64']))
            else:
                raise RuntimeError("nenhum ZIP informado")

            # Quais produtos gerar (checkboxes do passo 03)
            from gerar_pdfs import SAIDAS_VALIDAS, SAIDAS_PADRAO
            saidas = (set(body.get('saidas') or []) & SAIDAS_VALIDAS
                      or set(SAIDAS_PADRAO))

            # Saída: ao lado do ZIP escolhido; uploads caem em ~/Downloads
            if body.get('zip_caminho'):
                saida = zip_path.parent / f"{zip_path.stem}_PDFs"
            else:
                saida = Path.home() / 'Downloads' / f"{zip_path.stem}_PDFs"
            # Limpa a geração velha SÓ quando gera o conjunto padrão inteiro
            # — regeração parcial (ex.: só as finais pós-balizamento, ou só
            # as pilhas por arena) preserva os PDFs anteriores e apenas
            # sobrescreve os arquivos que produzir.
            if (SAIDAS_PADRAO <= saidas and saida.is_dir()
                    and saida.name.endswith('_PDFs')):
                shutil.rmtree(saida, ignore_errors=True)

            # ── Cronograma (opcional): caminho ou upload ──────────────────
            horarios, finais, arenas = {}, {}, {}
            cron_path = None
            if body.get('cron_caminho'):
                cron_path = body['cron_caminho']
            elif body.get('cron_b64'):
                cron_path = str(tmp / (body.get('cron_nome') or 'cron.json'))
                Path(cron_path).write_bytes(base64.b64decode(body['cron_b64']))
            if cron_path:
                horarios = _carregar_cronograma(cron_path)
                if not horarios:
                    self._chunk("⚠  cronograma sem horários de bateria — ordem "
                                "do dia completo cai pra Categoria → Workout → Bateria")
                # Finais e arenas só saem de Excel (JSON não preserva
                # o '(Final Heat)' nem os blocos 'Arena:')
                if not cron_path.lower().endswith('.json'):
                    try:
                        finais = finais_do_excel(cron_path)
                    except Exception:
                        finais = {}
                    if 'arenas' in saidas:
                        try:
                            arenas = arenas_do_excel(cron_path)
                        except Exception:
                            arenas = {}

            self._chunk("⏳ descompactando ZIP…")
            raiz = tmp / 'html'
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(raiz)

            feitos, erros = converter(raiz, saida, horarios, CHROME,
                                      log=self._chunk, finais=finais,
                                      saidas=saidas, arenas=arenas)
            if erros:
                raise RuntimeError(f"{len(erros)} PDF(s) falharam — veja o log")
            if feitos == 0:
                raise RuntimeError(
                    "nada foi gerado com essa seleção — 'Finais' exige "
                    "cronograma com '(Final Heat)'; 'Por arena' exige blocos "
                    "'Arena:' no Excel E súmulas com bateria preenchida "
                    "(balizadas)")
            self._chunk(f"FIM_OK\t{saida}")
        except Exception as e:
            self._chunk(f"FIM_ERRO\t{e}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            self.wfile.write(b"0\r\n\r\n")


def _ler_versao():
    """Versão do app: sumula_app.py (repo) ou VERSION.txt (bundle do app)."""
    try:
        import re as _re
        src = (_base_dir() / 'sumula_app.py').read_text(encoding='utf-8')
        m = _re.search(r"VERSION\s*=\s*['\"]([^'\"]+)['\"]", src)
        if m:
            return m.group(1)
    except OSError:
        pass
    try:
        return (_base_dir() / 'VERSION.txt').read_text(encoding='utf-8').strip()
    except OSError:
        return "dev"


VERSAO = _ler_versao()


def criar_server():
    """Sobe o servidor local numa porta livre (ou None se todas ocupadas).
    Usado pelo main() (modo navegador) e pelo pdf_app.py (janela nativa)."""
    for porta in PORTAS:
        try:
            server = ThreadingHTTPServer(('127.0.0.1', porta), GuiHandler)
            server.daemon_threads = True
            return server
        except OSError:
            continue
    return None


def main():
    server = criar_server()
    if not server:
        sys.exit("✗ nenhuma porta livre entre 8777 e 8797")
    url = f"http://localhost:{server.server_address[1]}"
    print("╔══════════════════════════════════════════════╗")
    print("║   PDFs por Bateria — Súmulas Digital Score   ║")
    print("╚══════════════════════════════════════════════╝")
    print(f"\n✓ Interface em: {url}")
    print("  (feche esta janela ou Ctrl+C pra encerrar)\n")
    if not CHROME:
        print("⚠  Chrome/Edge não encontrado — a página vai avisar.\n")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n✓ Encerrado.")


if __name__ == '__main__':
    main()
