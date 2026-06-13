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
                        carregar_horarios_excel)

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
:root{--lar:#F95F02;--bg:#101114;--card:#1a1c21;--bord:#2a2d34;--tx:#e8e8e8;--mut:#9a9da6}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--tx);font:15px/1.45 -apple-system,'Segoe UI',Roboto,sans-serif;
     min-height:100vh;display:flex;flex-direction:column;align-items:center;padding:32px 16px}
header{display:flex;align-items:center;gap:14px;margin-bottom:26px}
header img{height:44px;border-radius:8px}
header h1{font-size:19px;font-weight:800;letter-spacing:.02em}
header small{display:block;color:var(--mut);font-weight:400;font-size:12px}
main{width:100%;max-width:680px;display:flex;flex-direction:column;gap:14px}
.card{background:var(--card);border:1px solid var(--bord);border-radius:14px;padding:18px 20px}
.card h2{font-size:11px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;
         color:var(--mut);margin-bottom:10px}
.card h2 .opt{color:#5c5f68;font-weight:400;letter-spacing:.04em;text-transform:none}
select{width:100%;background:#101114;color:var(--tx);border:1px solid var(--bord);
       border-radius:9px;padding:10px 12px;font-size:14px;appearance:auto}
.drop{margin-top:8px;border:1px dashed var(--bord);border-radius:9px;padding:8px 12px;
      color:var(--mut);font-size:12.5px;text-align:center;cursor:pointer;transition:.15s}
.drop.over{border-color:var(--lar);color:var(--lar)}
.drop input{display:none}
.escolhido{margin-top:8px;font-size:12.5px;color:var(--lar);word-break:break-all}
#btnGerar{background:var(--lar);color:#fff;border:0;border-radius:12px;padding:15px;
          font-size:16px;font-weight:800;cursor:pointer;letter-spacing:.02em;transition:.15s}
#btnGerar:hover{filter:brightness(1.08)}
#btnGerar:disabled{background:#3a3d44;color:#777;cursor:default}
#aviso{background:#3b1f12;border:1px solid #7a3a10;color:#ffb486;border-radius:10px;
       padding:12px 14px;font-size:13.5px;display:none}
#prog{display:none}
.barra{height:10px;background:#101114;border-radius:99px;overflow:hidden;margin:10px 0 6px}
.barra i{display:block;height:100%;width:0;background:var(--lar);border-radius:99px;transition:width .2s}
#progTxt{font-size:13px;color:var(--mut)}
#log{background:#0b0c0e;border:1px solid var(--bord);border-radius:9px;margin-top:10px;
     padding:10px 12px;font:11.5px/1.5 ui-monospace,Menlo,Consolas,monospace;color:#b8bbc4;
     max-height:180px;overflow-y:auto;white-space:pre-wrap;display:none}
#fim{display:none;text-align:center}
#fim .ok{font-size:17px;font-weight:800;color:#5ecb71;margin-bottom:4px}
#fim .pasta{font-size:12.5px;color:var(--mut);word-break:break-all;margin-bottom:14px}
#btnAbrir{background:transparent;color:var(--lar);border:2px solid var(--lar);border-radius:12px;
          padding:12px 26px;font-size:15px;font-weight:800;cursor:pointer}
#btnAbrir:hover{background:var(--lar);color:#fff}
footer{margin-top:auto;padding-top:28px;color:#5c5f68;font-size:11px}
a.recarregar{color:var(--mut);font-size:12px;text-decoration:none;float:right}
a.recarregar:hover{color:var(--lar)}
.selo{margin-top:9px;font-size:12.5px;display:none;padding:7px 11px;border-radius:8px;line-height:1.35}
.selo.ok{display:block;color:#7ee29a;background:#11271a;border:1px solid #1f5733}
.selo.warn{display:block;color:#ffb486;background:#2c1a10;border:1px solid #6e3812}
.selo.chk{display:block;color:var(--mut);background:#16181d;border:1px solid var(--bord)}
</style>
</head>
<body>
<header>
  <img src="/logo.png" alt="" onerror="this.style.display='none'">
  <h1>PDFs por Bateria<small>Súmulas Digital Score</small></h1>
</header>
<main>
  <div id="aviso"></div>

  <div class="card">
    <h2>1 · ZIP de súmulas <a class="recarregar" href="#" onclick="carregar();return false">↻ atualizar listas</a></h2>
    <select id="selZip"></select>
    <label class="drop" id="dropZip">…ou clique/arraste o arquivo .zip aqui
      <input type="file" accept=".zip" onchange="upload(this,'zip')"></label>
    <div class="escolhido" id="escZip"></div>
  </div>

  <div class="card">
    <h2>2 · Cronograma das baterias <span class="opt">— Excel de programação ou backup JSON (opcional, ordena o dia completo por horário)</span></h2>
    <select id="selCron" onchange="checarCron()"></select>
    <label class="drop" id="dropCron">…ou clique/arraste o .xlsx / .json aqui
      <input type="file" accept=".xlsx,.xlsm,.json" onchange="upload(this,'cron')"></label>
    <div class="escolhido" id="escCron"></div>
    <div class="selo" id="seloCron"></div>
  </div>

  <button id="btnGerar" onclick="gerar()">Gerar PDFs</button>

  <div class="card" id="prog">
    <h2>Convertendo…</h2>
    <div class="barra"><i id="barra"></i></div>
    <div id="progTxt">preparando…</div>
    <div id="log"></div>
  </div>

  <div class="card" id="fim">
    <div class="ok">✓ PDFs prontos!</div>
    <div class="pasta" id="fimPasta"></div>
    <button id="btnAbrir" onclick="abrirPasta()">Abrir pasta</button>
  </div>
</main>
<footer>Conversão local com o Chrome/Edge desta máquina — saída idêntica ao Ctrl+P · v{{VERSAO}}</footer>
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
    selo.textContent=`✓ ${d.total} horários de bateria carregados`+(d.exemplo?` (ex: ${d.exemplo})`:'');
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
            self._send(200, 'application/json',
                       json.dumps({"total": len(horarios),
                                   "exemplo": exemplo}).encode())
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
            horarios = {}
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

            self._chunk("⏳ descompactando ZIP…")
            raiz = tmp / 'html'
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(raiz)

            feitos, erros = converter(raiz, saida, horarios, CHROME,
                                      log=self._chunk)
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
