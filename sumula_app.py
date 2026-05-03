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
VERSION = '1.3.0'

# Teto de body em POST (Excel + logos). 50 MB cobre o pior caso real do evento.
MAX_BODY_BYTES = 50 * 1024 * 1024

# Tipos de workout suportados (canônicos). Frontend e parsers só devem produzir
# valores deste conjunto; adicionar um novo tipo começa por aqui.
WORKOUT_TIPOS = frozenset({'for_time', 'amrap', 'express'})


class BadRequest(ValueError):
    """Payload inválido — handler devolve 400 com a mensagem."""
    pass


def _to_int_or_max(v) -> int:
    """Converte string/int em int pra ordenação. Não-numérico vai pro fim."""
    try:
        return int(str(v).strip())
    except (ValueError, AttributeError, TypeError):
        return 10**9


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
        """Renderiza a súmula de UM workout específico para o iframe de preview.

        Espera body com `dia_idx`, `cat_idx`, `wkt_idx` indicando coordenadas no
        modelo multi-dia. Renderiza em branco (sem alocação) — preview é só pra
        ver o layout do workout.
        """
        cfg = body.get('config')
        if not isinstance(cfg, dict):
            raise BadRequest("config (objeto) é obrigatório")
        dias = cfg.get('dias')
        if not isinstance(dias, list) or not dias:
            raise BadRequest("config.dias deve ser lista não-vazia")
        try:
            dia_idx = int(body.get('dia_idx', 0))
            cat_idx = int(body.get('cat_idx', 0))
            wkt_idx = int(body.get('wkt_idx', 0))
        except (TypeError, ValueError):
            raise BadRequest("índices inválidos (dia_idx/cat_idx/wkt_idx)")
        if not (0 <= dia_idx < len(dias)):
            raise BadRequest(f"dia_idx fora do range (0..{len(dias) - 1})")
        cats = dias[dia_idx].get('categorias', [])
        if not (0 <= cat_idx < len(cats)):
            raise BadRequest(f"cat_idx fora do range (0..{len(cats) - 1})")
        workouts = cats[cat_idx].get('workouts', [])
        if not (0 <= wkt_idx < len(workouts)):
            raise BadRequest(f"wkt_idx fora do range (0..{len(workouts) - 1})")
        _validate_workout_tipos(workouts)

        ev       = cfg.get('evento', {}) or {}
        assign_workout_numbers(workouts)   # recalcula slots Express
        enriquecer_workouts(workouts)      # calcula n_rounds (IA/algoritmo)
        wkt      = workouts[wkt_idx]
        logo     = _resolve_logo(ev.get('logo_empresa', ''))
        logo_evt = ev.get('logo_evento', '')
        # Sobrescreve categoria e data com os valores do dia/categoria selecionados
        # (a categoria global de evento é fallback)
        ev_local = {
            **ev,
            'categoria': cats[cat_idx].get('nome', '') or ev.get('categoria', ''),
            'data':      dias[dia_idx].get('data', '') or ev.get('data', ''),
        }
        html = render_workout(ev_local, wkt, FONTS, logo, logo_evt)
        self._send(200, 'text/html; charset=utf-8', html.encode('utf-8'))

    def _handle_generate(self, body):
        """Gera ZIP no shape multi-dia.

        Estrutura: Dia/Categoria/Workout_NN.html — cada arquivo combina todas
        as alocações de TODAS as baterias dessa categoria que rodam aquele
        workout (em ordem bateria → raia).

        Toggle `incluir_competidores` (default True): se False, gera súmula em
        branco (sem nome/número/box).

        Filtros opcionais: `dia_idx` (gera só esse dia). Sem filtro, gera tudo.
        """
        cfg = body.get('config')
        if not isinstance(cfg, dict):
            raise BadRequest("config (objeto) é obrigatório")
        dias = cfg.get('dias')
        if not isinstance(dias, list) or not dias:
            raise BadRequest("config.dias deve ser lista não-vazia")

        ev       = cfg.get('evento', {}) or {}
        logo     = _resolve_logo(ev.get('logo_empresa', ''))
        logo_evt = ev.get('logo_evento', '')
        incluir_competidores = bool(body.get('incluir_competidores', True))

        # Filtra dias se vier dia_idx
        dia_idx = body.get('dia_idx')
        if dia_idx is not None:
            try:
                dia_idx = int(dia_idx)
            except (TypeError, ValueError):
                raise BadRequest("dia_idx inválido")
            if not (0 <= dia_idx < len(dias)):
                raise BadRequest(f"dia_idx fora do range (0..{len(dias) - 1})")
            dias = [dias[dia_idx]]

        # Filtro adicional: cat_idx (precisa dia_idx). Gera só uma categoria.
        cat_idx = body.get('cat_idx')
        if cat_idx is not None:
            if dia_idx is None:
                raise BadRequest("cat_idx requer dia_idx")
            try:
                cat_idx = int(cat_idx)
            except (TypeError, ValueError):
                raise BadRequest("cat_idx inválido")
            cats_do_dia = dias[0].get('categorias', []) or []
            if not (0 <= cat_idx < len(cats_do_dia)):
                raise BadRequest(f"cat_idx fora do range (0..{len(cats_do_dia) - 1})")
            # Substitui as categorias do (único) dia restante por só a escolhida
            dias = [{**dias[0], 'categorias': [cats_do_dia[cat_idx]]}]

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for dia in dias:
                dia_label = dia.get('label', 'Dia')
                dia_data  = dia.get('data', '')
                dia_pasta = sanitize(dia_label)
                for cat in dia.get('categorias', []) or []:
                    cat_nome = cat.get('nome', 'Categoria')
                    cat_pasta = sanitize(cat_nome)
                    workouts = cat.get('workouts', []) or []
                    if not workouts:
                        continue
                    _validate_workout_tipos(workouts)
                    assign_workout_numbers(workouts)
                    enriquecer_workouts(workouts)
                    baterias = cat.get('baterias', []) or []

                    # Sobrescreve categoria e data: a súmula sempre carrega a
                    # categoria do workout e a data do dia em que ele roda.
                    ev_local = {
                        **ev,
                        'categoria': cat_nome,
                        'data':      dia_data or ev.get('data', ''),
                    }

                    for wkt_pos, wkt in enumerate(workouts, start=1):
                        # Junta todas as alocações de baterias que rodam este workout
                        # (workouts_que_rodam contém a posição 1-based do workout)
                        competidores: list[dict] = []
                        for b in baterias:
                            workouts_que_rodam = b.get('workouts_que_rodam') or []
                            if workouts_que_rodam and wkt_pos not in workouts_que_rodam:
                                continue
                            for aloc in b.get('alocacoes', []) or []:
                                competidores.append({
                                    'bateria_num': b.get('numero', ''),
                                    **aloc,
                                })
                        # Ordena por bateria → raia (numérica)
                        competidores.sort(key=lambda c: (
                            _to_int_or_max(c.get('bateria_num')),
                            _to_int_or_max(c.get('raia')),
                        ))

                        # Converte alocações em "atletas" (compatível com render_workout_combined)
                        atletas = [
                            {
                                'nome':    c.get('nome', ''),
                                'box':     c.get('box', ''),
                                'raia':    c.get('raia', ''),
                                'bateria': c.get('bateria_num', ''),
                                'numero':  c.get('numero', ''),
                            }
                            for c in competidores
                        ]

                        nome_arq = f"{wkt_pos:02d}_{sanitize(wkt.get('nome', 'wkt'))}.html"
                        caminho  = f"{dia_pasta}/{cat_pasta}/{nome_arq}"

                        if incluir_competidores and atletas:
                            html = render_workout_combined(ev_local, wkt, FONTS, logo, logo_evt, atletas)
                        else:
                            html = render_workout(ev_local, wkt, FONTS, logo, logo_evt)
                        zf.writestr(caminho, html.encode('utf-8'))

        nome_zip = sanitize(ev.get('nome', '') or 'sumulas') or 'sumulas'
        self._send(200, 'application/zip', buf.getvalue(),
                   {'Content-Disposition': f'attachment; filename="{nome_zip}.zip"'})

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
