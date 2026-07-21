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
                        carregar_horarios_excel, finais_do_excel)

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


PAGINA = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PDFs por Bateria — Digital Score</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0F0F11;--card:#19191C;--bord:#2A2A30;--bord2:#3a3a42;
  --lar:#F2691C;--lar-soft:rgba(242,105,28,.13);
  --cream:#ECE6DB;--tx:#D5D6DA;--mut:#8A8D94;--dim:#5B5E67;
  --ok:#5ECB71;--okbg:#10271A;--okbd:#1F5733;
}
.mono{font-family:ui-monospace,'SF Mono',Menlo,Consolas,monospace;text-transform:uppercase;letter-spacing:.16em}
.disp{font-family:'Impact','Haettenschweiler','Arial Narrow',sans-serif;text-transform:uppercase;font-weight:400}
body{
  background:repeating-linear-gradient(135deg,transparent 0 24px,rgba(242,105,28,.02) 24px 25px),var(--bg);
  color:var(--tx);font:15px/1.5 -apple-system,'Segoe UI',Roboto,sans-serif;
  min-height:100vh;display:flex;flex-direction:column;align-items:center;
}
/* top status strip */
.strip{width:100%;border-bottom:1px solid var(--bord);background:rgba(0,0,0,.25)}
.strip-in{max-width:680px;margin:0 auto;padding:11px 20px;display:flex;justify-content:space-between;
  align-items:center;font-size:10px}
.strip-in .l{color:var(--mut)}
.strip-in .r{color:var(--lar);display:flex;align-items:center;gap:8px}
.dot{width:7px;height:7px;border-radius:50%;background:var(--lar);box-shadow:0 0 8px var(--lar);animation:pulse 2.2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
main{width:100%;max-width:680px;padding:30px 20px 36px;display:flex;flex-direction:column;gap:16px}
/* header */
header{display:flex;align-items:center;gap:18px;margin-bottom:8px}
header img{height:50px;border-radius:7px;flex-shrink:0}
.kick{font-size:10px;color:var(--lar);display:flex;align-items:center;gap:10px;margin-bottom:8px}
.kick::before{content:"";width:22px;height:2px;background:var(--lar)}
header h1{font-size:40px;line-height:.9;color:var(--cream);letter-spacing:.015em}
header h1 b{color:var(--lar);font-weight:400}
.sub{color:var(--mut);font-size:12.5px;margin-top:9px;max-width:46ch}
/* cards */
.card{background:var(--card);border:1px solid var(--bord);border-radius:8px;padding:18px 20px;position:relative;overflow:hidden}
.card::before{content:"";position:absolute;inset:0;pointer-events:none;
  background:repeating-linear-gradient(135deg,transparent 0 15px,rgba(255,255,255,.011) 15px 16px)}
.card>*{position:relative}
.lbl{font-size:10.5px;color:var(--lar);margin-bottom:13px;display:flex;align-items:center;gap:9px;flex-wrap:wrap}
.lbl .n{color:var(--cream);font-size:12px}
.lbl .opt{color:var(--dim);letter-spacing:.02em;text-transform:none;
  font-family:-apple-system,'Segoe UI',sans-serif;font-size:11px}
.recarregar{margin-left:auto;color:var(--mut);font-size:9.5px;text-decoration:none;letter-spacing:.12em;
  font-family:ui-monospace,Menlo,monospace}
.recarregar:hover{color:var(--lar)}
select{width:100%;background:#0F0F11;color:var(--tx);border:1px solid var(--bord2);border-radius:6px;
  padding:11px 13px;font-size:13.5px;font-family:ui-monospace,Menlo,Consolas,monospace;appearance:auto;cursor:pointer}
select:focus{outline:none;border-color:var(--lar)}
.drop{margin-top:9px;border:1px dashed var(--bord2);border-radius:6px;padding:9px 12px;color:var(--mut);
  font-size:11.5px;text-align:center;cursor:pointer;transition:.15s;letter-spacing:.02em}
.drop:hover,.drop.over{border-color:var(--lar);color:var(--lar);background:var(--lar-soft)}
.drop input{display:none}
.escolhido{margin-top:9px;font-size:11.5px;color:var(--lar);word-break:break-all;font-family:ui-monospace,Menlo,monospace}
/* selo */
.selo{margin-top:10px;font-size:11.5px;display:none;padding:9px 12px;border-radius:6px;line-height:1.45;
  font-family:ui-monospace,Menlo,Consolas,monospace}
.selo.ok{display:block;color:#8fe6a6;background:var(--okbg);border:1px solid var(--okbd)}
.selo.warn{display:block;color:#ffb486;background:#2c1a10;border:1px solid #6e3812}
.selo.chk{display:block;color:var(--mut);background:#141416;border:1px solid var(--bord)}
/* generate */
#btnGerar{background:var(--lar);color:#1a0f06;border:0;border-radius:8px;padding:16px;cursor:pointer;
  font-family:'Impact','Haettenschweiler','Arial Narrow',sans-serif;text-transform:uppercase;
  font-size:25px;letter-spacing:.04em;transition:.15s;margin-top:2px}
#btnGerar:hover{filter:brightness(1.09)}
#btnGerar:disabled{background:#2c2c31;color:#6b6e76;cursor:default}
#aviso{background:#2c1a10;border:1px solid #7a3a10;color:#ffb486;border-radius:8px;padding:12px 14px;
  font-size:13px;display:none}
/* progress */
#prog{display:none}
.barra{height:9px;background:#0F0F11;border:1px solid var(--bord);border-radius:3px;overflow:hidden;margin:13px 0 9px}
.barra i{display:block;height:100%;width:0;background:var(--lar);transition:width .25s;box-shadow:0 0 10px var(--lar)}
#progTxt{font-size:12px;color:var(--mut);font-family:ui-monospace,Menlo,Consolas,monospace;letter-spacing:.05em}
#log{background:#0A0A0C;border:1px solid var(--bord);border-radius:6px;margin-top:12px;padding:11px 13px;
  font:11px/1.6 ui-monospace,Menlo,Consolas,monospace;color:#9da0a8;max-height:170px;
  overflow-y:auto;white-space:pre-wrap;display:none}
/* done */
#fim{display:none;text-align:center}
#fim .big{font-family:'Impact','Haettenschweiler','Arial Narrow',sans-serif;text-transform:uppercase;
  font-size:32px;color:var(--cream);letter-spacing:.025em;line-height:1}
#fim .big span{color:var(--ok)}
#fim .pasta{font-size:11px;color:var(--mut);word-break:break-all;margin:10px 0 17px;
  font-family:ui-monospace,Menlo,Consolas,monospace}
#btnAbrir{background:transparent;color:var(--lar);border:1.5px solid var(--lar);border-radius:7px;padding:12px 30px;
  font-family:'Impact','Haettenschweiler','Arial Narrow',sans-serif;text-transform:uppercase;
  font-size:18px;letter-spacing:.05em;cursor:pointer}
#btnAbrir:hover{background:var(--lar);color:#1a0f06}
footer{width:100%;max-width:680px;padding:20px 20px 30px;color:var(--dim);font-size:9.5px;
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

  const body = {};
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
            html = PAGINA.replace('{{VERSAO}}', VERSAO)
            self._send(200, 'text/html; charset=utf-8', html.encode())
        elif path == '/logo.png':
            logo = Path(__file__).parent / 'ds_logo.png'
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

            # Saída: ao lado do ZIP escolhido; uploads caem em ~/Downloads
            if body.get('zip_caminho'):
                saida = zip_path.parent / f"{zip_path.stem}_PDFs"
            else:
                saida = Path.home() / 'Downloads' / f"{zip_path.stem}_PDFs"
            if saida.is_dir() and saida.name.endswith('_PDFs'):
                shutil.rmtree(saida, ignore_errors=True)   # limpa geração velha

            # ── Cronograma (opcional): caminho ou upload ──────────────────
            horarios, finais = {}, {}
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
                # Finais só saem de Excel (o '(Final Heat)' não sobrevive no JSON)
                if not cron_path.lower().endswith('.json'):
                    try:
                        finais = finais_do_excel(cron_path)
                    except Exception:
                        finais = {}

            self._chunk("⏳ descompactando ZIP…")
            raiz = tmp / 'html'
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(raiz)

            feitos, erros = converter(raiz, saida, horarios, CHROME,
                                      log=self._chunk, finais=finais)
            if erros:
                raise RuntimeError(f"{len(erros)} PDF(s) falharam — veja o log")
            self._chunk(f"FIM_OK\t{saida}")
        except Exception as e:
            self._chunk(f"FIM_ERRO\t{e}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            self.wfile.write(b"0\r\n\r\n")


def _ler_versao():
    """Versão do app (sumula_app.py define VERSION) sem importar o app inteiro."""
    try:
        import re as _re
        src = (Path(__file__).parent / 'sumula_app.py').read_text(encoding='utf-8')
        m = _re.search(r"VERSION\s*=\s*['\"]([^'\"]+)['\"]", src)
        return m.group(1) if m else "dev"
    except OSError:
        return "dev"


VERSAO = _ler_versao()


def main():
    server = None
    for porta in PORTAS:
        try:
            server = ThreadingHTTPServer(('127.0.0.1', porta), GuiHandler)
            break
        except OSError:
            continue
    if not server:
        sys.exit("✗ nenhuma porta livre entre 8777 e 8797")
    server.daemon_threads = True
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
