#!/usr/bin/env python3
"""
sumula_app.py — Súmulas Digital Score  v1.0.0
Servidor web local. Sem dependências além de Jinja2 + fontes Lato.
Uso: python3 sumula_app.py   →  abre http://localhost:8765
"""

import json, os, io, zipfile, threading, webbrowser, sys, base64, re, signal, traceback
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from campo_generator import render_workout, render_workout_combined, load_fonts, img_b64, sanitize

PORT = int(os.environ.get('PORT', 8765))
# Render sempre define PORT via env — usa isso para detectar ambiente cloud
HOST = '0.0.0.0' if 'PORT' in os.environ else 'localhost'
IS_CLOUD = HOST == '0.0.0.0'

# Fonte única da versão. Atualize via `python3 bump_version.py [patch|minor|major]`.
VERSION = '1.2.7'

# Teto de body em POST (Excel + logos). 50 MB cobre o pior caso real do evento.
MAX_BODY_BYTES = 50 * 1024 * 1024

# Tipos de workout suportados (canônicos). Frontend e parsers só devem produzir
# valores deste conjunto; adicionar um novo tipo começa por aqui.
WORKOUT_TIPOS = frozenset({'for_time', 'amrap', 'express'})


class BadRequest(ValueError):
    """Payload inválido — handler devolve 400 com a mensagem."""
    pass


def _validate_workout_tipos(workouts):
    """Garante que cada workout tem 'tipo' válido. Levanta BadRequest se não."""
    for i, w in enumerate(workouts):
        tipo = (w or {}).get('tipo')
        if tipo not in WORKOUT_TIPOS:
            raise BadRequest(
                f"workouts[{i}].tipo inválido ({tipo!r}); use um de {sorted(WORKOUT_TIPOS)}"
            )

def _resolve_logo(value):
    """Retorna uma data-URL de logo.
    Se 'value' já é data-URL (upload do front), usa direto.
    Se é caminho de arquivo, converte com img_b64.
    """
    if not value:
        return ""
    if value.startswith("data:"):
        return value          # já é data-URL — upload via interface
    return img_b64(value)    # caminho local

# ── Imports dos módulos extraídos ──────────────────────────────────────────────
from parsers import parse_excel, parse_pdf, assign_workout_numbers, _atleta_sort_key
from ai_rounds import enriquecer_workouts, AI_ATIVO

# ── Carregar fontes na inicialização ────────────────────────────────────────────
_banner_inner = f"  Súmulas Digital Score  —  v{VERSION}"
print("╔══════════════════════════════════════════════╗")
print(f"║{_banner_inner:<46}║")
print("╚══════════════════════════════════════════════╝\n")
print("⏳ Carregando fontes e módulos...")
_fonts_raw = load_fonts()   # base64 puro

# Monta URLs completas para uso no browser (data:)
def _b64_url(b64, mime='font/truetype'):
    return f"data:{mime};base64,{b64}" if b64 else ""

FONTS = {
    "black": _b64_url(_fonts_raw["black"]),
    "bold":  _b64_url(_fonts_raw["bold"]),
    "reg":   _b64_url(_fonts_raw["reg"]),
    "light": _b64_url(_fonts_raw["light"]),
}

# ── Logo padrão Digital Score (carregada do arquivo ds_logo.png) ────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_LOGO_PATH = os.path.join(_HERE, 'ds_logo.png')
DS_LOGO_PADRAO = img_b64(_LOGO_PATH) if os.path.exists(_LOGO_PATH) else ""
if DS_LOGO_PADRAO:
    print("  ✓ Logo Digital Score carregada")
else:
    print("  ⚠  ds_logo.png não encontrada — header sem logo padrão")
if AI_ATIVO:
    print("  ✓ IA ativa (Anthropic Claude Haiku) — cálculo inteligente de rounds")
else:
    print("  ○  IA inativa (defina ANTHROPIC_API_KEY para ativar)")
print("  ✓ Saída: HTML (abrir no browser + Ctrl+P para PDF)")
print()



# ── HTML Interface ──────────────────────────────────────────────────────────────
# ── Static frontend (HTML/CSS/JS em arquivos próprios em static/) ──────────────
# Cacheado no startup. Edits requerem restart do servidor (mesma regra do .py).
_STATIC_DIR = os.path.join(_HERE, 'static')

def _load_static(name):
    path = os.path.join(_STATIC_DIR, name)
    if not os.path.exists(path):
        return ''
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

INDEX_HTML = _load_static('index.html')
APP_CSS    = _load_static('app.css')
APP_JS     = _load_static('app.js')


# ── HTTP Handler ────────────────────────────────────────────────────────────────
class SumulaHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass  # silencia log

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            html = (INDEX_HTML
                    .replace('{{DS_LOGO_PADRAO_B64}}', DS_LOGO_PADRAO)
                    .replace('{{VERSION}}', VERSION))
            self._send(200, 'text/html; charset=utf-8', html.encode('utf-8'))
        elif self.path == '/app.css':
            self._send(200, 'text/css; charset=utf-8', APP_CSS.encode('utf-8'))
        elif self.path == '/app.js':
            self._send(200, 'application/javascript; charset=utf-8', APP_JS.encode('utf-8'))
        elif self.path == '/api/status':
            payload = json.dumps({
                "ai_ativo":    AI_ATIVO,
                "ai_provider": "Anthropic Claude Haiku" if AI_ATIVO else None,
                "versao":      VERSION
            })
            self._send(200, 'application/json; charset=utf-8', payload.encode())
        else:
            self._send(404, 'text/plain', b'Not found')

    def do_POST(self):
        try:
            try:
                length = int(self.headers.get('Content-Length', 0))
            except ValueError:
                raise BadRequest("Content-Length inválido")
            if length <= 0:
                raise BadRequest("body vazio")
            if length > MAX_BODY_BYTES:
                self._send(413, 'application/json',
                           json.dumps({"error": f"body acima de {MAX_BODY_BYTES // (1024*1024)} MB"}).encode('utf-8'))
                return
            try:
                body = json.loads(self.rfile.read(length))
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise BadRequest("body não é JSON válido")
            if not isinstance(body, dict):
                raise BadRequest("body precisa ser objeto JSON")
            routes = {
                '/api/preview':        self._handle_preview,
                '/api/generate':       self._handle_generate,
                '/api/import/excel':   self._handle_import_excel,
                '/api/import/pdf':     self._handle_import_pdf,
            }
            handler = routes.get(self.path)
            if handler: handler(body)
            else: self._send(404, 'text/plain', b'Rota nao encontrada')
        except BadRequest as e:
            self._send(400, 'application/json',
                       json.dumps({"error": str(e)}).encode('utf-8'))
        except Exception:
            # Loga stack completo no servidor; cliente recebe mensagem genérica.
            traceback.print_exc()
            self._send(500, 'application/json',
                       json.dumps({"error": "erro interno — confira os logs"}).encode('utf-8'))

    def _handle_preview(self, body):
        cfg = body.get('config')
        if not isinstance(cfg, dict):
            raise BadRequest("config (objeto) é obrigatório")
        workouts = cfg.get('workouts')
        if not isinstance(workouts, list) or not workouts:
            raise BadRequest("config.workouts deve ser lista não-vazia")
        _validate_workout_tipos(workouts)
        try:
            idx = int(body.get('workout_index', 0))
        except (TypeError, ValueError):
            raise BadRequest("workout_index inválido")
        if idx < 0 or idx >= len(workouts):
            raise BadRequest(f"workout_index fora do range (0..{len(workouts) - 1})")
        ev       = cfg.get('evento', {}) or {}
        assign_workout_numbers(workouts)   # recalcula com slots Express
        enriquecer_workouts(workouts)      # calcula n_rounds por IA/algoritmo
        wkt      = workouts[idx]
        logo     = _resolve_logo(ev.get('logo_empresa', ''))
        logo_evt = ev.get('logo_evento', '')   # data-URL vinda do front
        html = render_workout(ev, wkt, FONTS, logo, logo_evt)
        self._send(200, 'text/html; charset=utf-8', html.encode('utf-8'))

    def _handle_generate(self, body):
        cfg = body.get('config')
        if not isinstance(cfg, dict):
            raise BadRequest("config (objeto) é obrigatório")
        workouts = cfg.get('workouts')
        if not isinstance(workouts, list) or not workouts:
            raise BadRequest("config.workouts deve ser lista não-vazia")
        _validate_workout_tipos(workouts)
        ev       = cfg.get('evento', {}) or {}
        atletas  = cfg.get('atletas', []) or []
        logo     = _resolve_logo(ev.get('logo_empresa', ''))
        logo_evt = ev.get('logo_evento', '')
        assign_workout_numbers(workouts)
        enriquecer_workouts(workouts)

        if atletas:
            atletas = sorted(atletas, key=_atleta_sort_key)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            if atletas:
                # Um HTML combinado por workout (todos atletas como páginas A4 sequenciais).
                # Ctrl+P no browser gera o PDF da categoria inteira de uma vez.
                for wkt in workouts:
                    num  = wkt.get('numero', 1)
                    nome = wkt.get('nome', 'wkt')
                    html = render_workout_combined(ev, wkt, FONTS, logo, logo_evt, atletas)
                    zf.writestr(f"{num:02d}_{sanitize(nome)}.html",
                                html.encode('utf-8'))
            else:
                for wkt in workouts:
                    num  = wkt.get('numero', 1)
                    nome = wkt.get('nome', 'wkt')
                    html = render_workout(ev, wkt, FONTS, logo, logo_evt)
                    zf.writestr(f"{num:02d}_{sanitize(nome)}.html", html.encode('utf-8'))

        cat = sanitize(ev.get('categoria', '') or ev.get('nome', 'sumulas'))
        self._send(200, 'application/zip', buf.getvalue(),
                   {'Content-Disposition': f'attachment; filename="{cat}.zip"'})

    def _handle_import_excel(self, body):
        try:
            data   = base64.b64decode(body['data'])
            result = parse_excel(data)
            self._send(200, 'application/json; charset=utf-8',
                       json.dumps(result, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            self._send(200, 'application/json',
                       json.dumps({"error": str(e)}).encode('utf-8'))

    def _handle_import_pdf(self, body):
        try:
            data   = base64.b64decode(body['data'])
            result = parse_pdf(data)
            self._send(200, 'application/json; charset=utf-8',
                       json.dumps(result, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            self._send(200, 'application/json',
                       json.dumps({"error": str(e)}).encode('utf-8'))

    def _send(self, code, content_type, data, extra=None):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Access-Control-Allow-Origin', '*')
        if extra:
            for k, v in extra.items(): self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)


# ── Startup ──────────────────────────────────────────────────────────────────────
def main():
    try:
        # ThreadingHTTPServer: cada request roda numa thread, não bloqueia outras.
        # Importante porque a chamada à IA e a geração de ZIP grande são lentas.
        server = ThreadingHTTPServer((HOST, PORT), SumulaHandler)
        server.daemon_threads = True
    except OSError:
        print(f"⚠  Porta {PORT} em uso.")
        sys.exit(1)

    if IS_CLOUD:
        print(f"✓ Servidor em: http://0.0.0.0:{PORT}")
        print(f"  S\u00famulas Digital Score v{VERSION} online \u2014 pronto para receber conex\u00f5es\n")
    else:
        url = f'http://localhost:{PORT}'
        print(f"✓ Servidor em: {url}")
        print("  Pressione Ctrl+C para encerrar\n")
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    # Render envia SIGTERM ao reiniciar/redeployar; sem handler o processo morre
    # duro e qualquer geração em andamento perde os arquivos. Ctrl+C continua via KeyboardInterrupt.
    def _on_sigterm(_signo, _frame):
        print("\n✓ Recebido SIGTERM, encerrando…")
        # shutdown() precisa rodar fora da thread principal (que está em serve_forever).
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, _on_sigterm)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n✓ Encerrado (Ctrl+C).")
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
