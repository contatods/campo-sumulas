#!/usr/bin/env python3
"""
sumula_app.py — Súmulas Digital Score  v1.0.0
Servidor web local. Sem dependências além de Jinja2 + fontes Lato.
Uso: python3 sumula_app.py   →  abre http://localhost:8765
"""

import json, os, io, zipfile, threading, webbrowser, sys, base64, re, signal, time, traceback
import pathlib, shutil, tempfile
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from campo_generator import render_workout, render_workout_combined, render_for_load_team_summary, render_grid, load_fonts, img_b64, sanitize

PORT = int(os.environ.get('PORT', 8765))
# Render sempre define PORT via env — usa isso para detectar ambiente cloud
HOST = '0.0.0.0' if 'PORT' in os.environ else 'localhost'
IS_CLOUD = HOST == '0.0.0.0'

# Fonte única da versão. Atualize via `python3 bump_version.py [patch|minor|major]`.
VERSION = '2.7.1'

# Teto de body em POST (Excel + logos). 50 MB cobre o pior caso real do evento.
MAX_BODY_BYTES = 50 * 1024 * 1024

# Tipos de workout suportados (canônicos). Frontend e parsers só devem produzir
# valores deste conjunto; adicionar um novo tipo começa por aqui.
WORKOUT_TIPOS = frozenset({'for_time', 'for_time_goal', 'amrap', 'express', 'for_load', 'composto'})


class BadRequest(ValueError):
    """Payload inválido — handler devolve 400 com a mensagem."""
    pass


# Rate limit dos endpoints /api/ai/* — single-instance, em memória.
# Janela deslizante de 60s, máx N chamadas globais. Protege contra:
#   - Loop acidental no front (custo da API Anthropic é por chamada)
#   - Abuso quando deployado em cloud público (URL exposta)
# Single-instance: rate limit não é distribuído. Em multi-worker no Render
# cada worker terá seu próprio contador (multiplicador implícito).
AI_RATE_LIMIT_MAX = 60          # chamadas/min — somatório de TODOS os /api/ai/*
AI_RATE_LIMIT_WINDOW_S = 60     # janela em segundos
_ai_calls: list[float] = []
_ai_calls_lock = threading.Lock()

# Token opcional pra proteger endpoints em deploy público. Quando setado em
# env, requests sem header 'X-Api-Token' válido recebem 401. Quando não
# setado, comportamento atual (público). Use:
#   export CAMPOSUMULAS_TOKEN=alguma-string-secreta
# E o front envia o header em cada chamada.
API_TOKEN = os.environ.get('CAMPOSUMULAS_TOKEN', '').strip()

# Timestamp de startup pra calcular uptime no /api/status
_STARTUP_TS = time.time()


def _ai_rate_limit_ok() -> tuple[bool, int]:
    """Retorna (allowed, retry_after_seconds). Limpa calls fora da janela.

    Compartilhado por todos os handlers /api/ai/* — o orçamento de 60/min
    cobre o uso real (poucas chamadas por sessão de usuário) e estanca
    abuso (loop ou ataque automatizado).
    """
    now = time.time()
    with _ai_calls_lock:
        _ai_calls[:] = [t for t in _ai_calls if now - t < AI_RATE_LIMIT_WINDOW_S]
        if len(_ai_calls) >= AI_RATE_LIMIT_MAX:
            mais_antiga = _ai_calls[0]
            return False, int(AI_RATE_LIMIT_WINDOW_S - (now - mais_antiga)) + 1
        _ai_calls.append(now)
        return True, 0


# Aliases pra compat com handlers antigos que usavam _chat_rate_limit_ok
_chat_rate_limit_ok = _ai_rate_limit_ok


def _mensagem_erro_ia(exc: Exception) -> str:
    """Mapeia exception do SDK Anthropic em mensagem útil em PT-BR.

    Permite que o usuário entenda se é problema de rede, quota, chave inválida
    ou outro — em vez de só ver 'IA falhou: TimeoutError'.
    """
    try:
        import anthropic
    except ImportError:
        return f'Erro inesperado: {exc.__class__.__name__}'
    if isinstance(exc, anthropic.AuthenticationError):
        return 'Chave da API rejeitada — confira ANTHROPIC_API_KEY no servidor.'
    if isinstance(exc, anthropic.PermissionDeniedError):
        return 'Sem permissão pra esse modelo — verifique o plano da conta Anthropic.'
    if isinstance(exc, anthropic.RateLimitError):
        return 'Limite da API atingido. Aguarde alguns segundos antes de mandar de novo.'
    if isinstance(exc, anthropic.APITimeoutError):
        return 'Timeout — a API demorou pra responder. Tente de novo.'
    if isinstance(exc, anthropic.APIConnectionError):
        return 'Sem conexão com a API da Anthropic. Verifique sua internet.'
    if isinstance(exc, anthropic.BadRequestError):
        return f'Pedido inválido: {exc}'
    if isinstance(exc, anthropic.InternalServerError):
        return 'A API da Anthropic está com problema. Tente de novo em alguns minutos.'
    if isinstance(exc, anthropic.APIError):
        return f'Erro da API ({exc.__class__.__name__}): {exc}'
    return f'Erro inesperado: {exc.__class__.__name__}'


def _to_int_or_max(v) -> int:
    """Converte string/int em int pra ordenação. Não-numérico vai pro fim."""
    try:
        return int(str(v).strip())
    except (ValueError, AttributeError, TypeError):
        return 10**9


FOR_LOAD_TENTATIVAS_MIN = 1
FOR_LOAD_TENTATIVAS_MAX = 12  # cap A4 — individual compact aguenta até ~12; team menos
FOR_LOAD_ANILHAS_MAX = 12     # cap horizontal pra régua não estourar A4 (~190mm)


def _validate_workout_tipos(workouts):
    """Garante que cada workout tem 'tipo' válido. Levanta BadRequest se não.

    Pra For Load, valida também tentativas/anilhas/barras pra evitar súmula
    inutilizável (régua vazia, número absurdo de tentativas, peso negativo).
    """
    for i, w in enumerate(workouts):
        wkt = w or {}
        tipo = wkt.get('tipo')
        if tipo not in WORKOUT_TIPOS:
            raise BadRequest(
                f"workouts[{i}].tipo inválido ({tipo!r}); use um de {sorted(WORKOUT_TIPOS)}"
            )
        if tipo == 'for_load':
            _validate_for_load(wkt, i)


def _validate_for_load(wkt: dict, idx: int) -> None:
    """Valida campos específicos de For Load. Levanta BadRequest se ruim.

    Campos ausentes são tolerados — defaults são aplicados no render (3 tentativas,
    anilhas default kg/lb, barras 20/15 kg). Só rejeita valores explicitamente
    inválidos (string, negativo, fora do range).
    """
    tent = wkt.get('tentativas')
    if tent is not None:
        if not isinstance(tent, int) or not (FOR_LOAD_TENTATIVAS_MIN <= tent <= FOR_LOAD_TENTATIVAS_MAX):
            raise BadRequest(
                f"workouts[{idx}].tentativas inválido ({tent!r}); "
                f"use inteiro entre {FOR_LOAD_TENTATIVAS_MIN} e {FOR_LOAD_TENTATIVAS_MAX}"
            )
    anilhas = wkt.get('anilhas')
    if anilhas is not None:
        if not isinstance(anilhas, list) or not anilhas:
            raise BadRequest(f"workouts[{idx}].anilhas vazio ou inválido")
        if len(anilhas) > FOR_LOAD_ANILHAS_MAX:
            raise BadRequest(
                f"workouts[{idx}].anilhas tem {len(anilhas)} pesos; "
                f"máximo {FOR_LOAD_ANILHAS_MAX} (limite horizontal A4)"
            )
        for j, a in enumerate(anilhas):
            if not isinstance(a, (int, float)) or a <= 0:
                raise BadRequest(
                    f"workouts[{idx}].anilhas[{j}] inválido ({a!r}); use número positivo"
                )
    for campo in ('barra_masculina', 'barra_feminina'):
        v = wkt.get(campo)
        if v is None:
            continue   # default aplicado no render
        if not isinstance(v, (int, float)) or v <= 0:
            raise BadRequest(
                f"workouts[{idx}].{campo} inválido ({v!r}); use número positivo"
            )
    unidade = wkt.get('unidade')
    if unidade is not None:
        # Tolera case ('KG', 'Kg' etc) — normaliza in-place pra render usar lower
        if isinstance(unidade, str):
            wkt['unidade'] = unidade.strip().lower()
            unidade = wkt['unidade']
        if unidade not in ('kg', 'lb'):
            raise BadRequest(
                f"workouts[{idx}].unidade inválido ({unidade!r}); use 'kg' ou 'lb'"
            )

def _resolve_logo(value):
    """Retorna uma data-URL de logo.

    O front sempre envia data-URL (upload via FileReader). Qualquer outro
    valor é rejeitado pra fechar leitura arbitrária de arquivo via POST
    (`logo_empresa: '/etc/passwd'` antes vazava o arquivo em base64 dentro
    do HTML — app está público no Render).
    """
    if not value:
        return ""
    if isinstance(value, str) and value.startswith("data:"):
        return value
    return ""

# ── Imports dos módulos extraídos ──────────────────────────────────────────────
from parsers import parse_excel, parse_pdf, assign_workout_numbers, assign_workout_numbers_global, _atleta_sort_key
from gerar_pdfs import (achar_chrome, horarios_do_config,
                        converter as converter_pdfs)
from ai_rounds import (enriquecer_workouts, AI_ATIVO,
                       sugerir_time_cap, auto_descricao,
                       validar_evento, resumo_evento, chat_evento,
                       explicar_avisos_import, revisar_programacao_ia,
                       colapsar_avisos)
from ai_parser import revisar_leitura_ia

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
    # Fase 2 robustez: IA repara workouts que a regex lê errado (falham no schema).
    import parsers as _parsers
    import ai_parser as _ai_parser
    _parsers.registrar_reparador(_ai_parser.reparar_workout_ia)
    print("  ✓ IA como fallback de parsing (repara workouts fora do schema)")
else:
    print("  ○  IA inativa (defina ANTHROPIC_API_KEY para ativar)")
# PDFs por bateria: usa o Chrome headless da máquina (fidelidade do Ctrl+P).
# No Render não há Chrome → recurso desligado, frontend esconde o botão.
PDF_CHROME = achar_chrome()
if PDF_CHROME:
    print("  ✓ PDFs por bateria ativos (Chrome headless)")
else:
    print("  ○  PDFs por bateria inativos (Google Chrome não encontrado)")
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
class _ChunkedWriter:
    """File-like wrapper que codifica HTTP chunked encoding em cada write.
    Sem `seek` — força zipfile.ZipFile a usar data descriptors (streaming).
    Permite o navegador começar a baixar enquanto o servidor ainda gera."""
    def __init__(self, wfile):
        self.wfile = wfile
        self.pos = 0
    def write(self, data):
        if not data: return 0
        # Formato HTTP chunked: tamanho-hex\r\n + dados + \r\n
        self.wfile.write(f"{len(data):X}\r\n".encode('ascii'))
        self.wfile.write(data)
        self.wfile.write(b"\r\n")
        self.pos += len(data)
        return len(data)
    def tell(self):
        return self.pos
    def flush(self):
        try: self.wfile.flush()
        except Exception: pass
    def close_chunks(self):
        # Chunk de tamanho 0 marca o fim do corpo HTTP chunked
        self.wfile.write(b"0\r\n\r\n")
        try: self.wfile.flush()
        except Exception: pass


class SumulaHandler(BaseHTTPRequestHandler):
    # HTTP/1.1 é necessário pra Transfer-Encoding: chunked (streaming do ZIP).
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args): pass  # silencia log

    def do_GET(self):
        # Strip query string: '/?_=123' (cache buster) e '/api/status?x=1' devem
        # bater com a rota base.
        path = urlsplit(self.path).path
        if path in ('/', '/index.html'):
            html = (INDEX_HTML
                    .replace('{{DS_LOGO_PADRAO_B64}}', DS_LOGO_PADRAO)
                    .replace('{{VERSION}}', VERSION))
            self._send(200, 'text/html; charset=utf-8', html.encode('utf-8'))
        elif path == '/app.css':
            self._send(200, 'text/css; charset=utf-8', APP_CSS.encode('utf-8'))
        elif path == '/app.js':
            self._send(200, 'application/javascript; charset=utf-8', APP_JS.encode('utf-8'))
        elif path == '/api/status':
            payload = json.dumps({
                "ai_ativo":    AI_ATIVO,
                "ai_provider": "Anthropic Claude Haiku" if AI_ATIVO else None,
                "versao":      VERSION,
                "uptime_s":    int(time.time() - _STARTUP_TS),
                "python":      sys.version.split()[0],
                "ambiente":    "cloud" if IS_CLOUD else "local",
                "pdf_ativo":   bool(PDF_CHROME),
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
                '/api/preview':            self._handle_preview,
                '/api/preview/grid':       self._handle_preview_grid,
                '/api/generate':           self._handle_generate,
                '/api/gerar-pdfs':         self._handle_generate_pdfs,
                '/api/generate/pre-evento': self._handle_generate_pre_evento,
                '/api/import/excel':       self._handle_import_excel,
                '/api/import/pdf':         self._handle_import_pdf,
                '/api/ai/sugerir-time-cap': self._handle_sugerir_time_cap,
                '/api/ai/auto-descricao':  self._handle_auto_descricao,
                '/api/ai/validar-evento':  self._handle_validar_evento,
                '/api/ai/resumo-evento':   self._handle_resumo_evento,
                '/api/ai/explicar-avisos': self._handle_explicar_avisos,
                '/api/ai/revisar-programacao': self._handle_revisar_programacao,
                '/api/ai/revisar-leitura': self._handle_revisar_leitura,
                '/api/ai/chat':            self._handle_chat,
            }
            handler = routes.get(self.path)
            if not handler:
                self._send(404, 'text/plain', b'Rota nao encontrada')
                return
            # Gate de auth opcional: se CAMPOSUMULAS_TOKEN setado, exige header
            # X-Api-Token correspondente. Aplica a TODOS POST endpoints.
            if API_TOKEN:
                token_recebido = (self.headers.get('X-Api-Token') or '').strip()
                if token_recebido != API_TOKEN:
                    self._send(401, 'application/json',
                               json.dumps({"error": "token inválido ou ausente — header X-Api-Token"}).encode('utf-8'))
                    return
            # Gate de rate limit: aplica a TODOS endpoints /api/ai/* — protege
            # quota Anthropic contra loops e abuso quando deployado público.
            if self.path.startswith('/api/ai/'):
                ok, retry = _ai_rate_limit_ok()
                if not ok:
                    self._send(429, 'application/json',
                               json.dumps({"error": f"rate limit atingido — aguarde {retry}s",
                                           "retry_after": retry}).encode('utf-8'),
                               {'Retry-After': str(retry)})
                    return
            handler(body)
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
        # Numeração CONTÍNUA por categoria através dos dias (mesma do import/ZIP),
        # não per-dia — senão a súmula mostra número diferente da sidebar.
        assign_workout_numbers_global(dias)
        # Preview rápido: pré-popula n_rounds via algoritmo pra QUALQUER AMRAP
        # sem n_rounds já setado. Isso evita a chamada IA dentro de
        # enriquecer_workouts() (que tem timeout 15s e é o gargalo do preview).
        # Para o ZIP final, o usuário usa /api/generate que SIM chama a IA.
        from ai_rounds import _estimar_rounds_algoritmico
        for w in workouts:
            if w.get('tipo') == 'amrap' and 'n_rounds' not in w:
                w['n_rounds'] = _estimar_rounds_algoritmico(
                    w.get('movimentos', []), w.get('time_cap', '') or '')
            elif w.get('tipo') == 'express':
                f1 = w.get('formula1') or {}
                if f1 and 'n_rounds' not in f1:
                    f1['n_rounds'] = _estimar_rounds_algoritmico(
                        f1.get('movimentos', []), f1.get('janela', ''))
        enriquecer_workouts(workouts)      # n_rounds já set → não chama IA
        wkt      = workouts[wkt_idx]
        logo     = _resolve_logo(ev.get('logo_empresa', ''))
        logo_evt = _resolve_logo(ev.get('logo_evento', ''))
        # Sobrescreve categoria e data com os valores do dia/categoria selecionados
        # (a categoria global de evento é fallback)
        ev_local = {
            **ev,
            'categoria': cats[cat_idx].get('nome', '') or ev.get('categoria', ''),
            'data':      dias[dia_idx].get('data', '') or ev.get('data', ''),
        }
        html = render_workout(ev_local, wkt, FONTS, logo, logo_evt)
        self._send(200, 'text/html; charset=utf-8', html.encode('utf-8'))

    def _handle_preview_grid(self, body):
        """Preview em GRADE: renderiza todas as súmulas (em branco) de um dia — ou
        do evento todo se `dia_idx` ausente — num HTML só, pra revisão visual
        antes do ZIP. Respeita workouts_que_rodam (só o que roda por categoria) e
        embute fontes uma vez. Sem IA: n_rounds de AMRAP vem do algoritmo.
        """
        cfg = body.get('config')
        if not isinstance(cfg, dict):
            raise BadRequest("config (objeto) é obrigatório")
        dias = cfg.get('dias')
        if not isinstance(dias, list) or not dias:
            raise BadRequest("config.dias deve ser lista não-vazia")
        dia_idx = body.get('dia_idx')
        if dia_idx is not None:
            try:
                dia_idx = int(dia_idx)
            except (TypeError, ValueError):
                raise BadRequest("dia_idx inválido")
            if not (0 <= dia_idx < len(dias)):
                raise BadRequest(f"dia_idx fora do range (0..{len(dias) - 1})")
            dias_sel = [dias[dia_idx]]
        else:
            dias_sel = dias

        ev       = cfg.get('evento', {}) or {}
        logo     = _resolve_logo(ev.get('logo_empresa', ''))
        logo_evt = _resolve_logo(ev.get('logo_evento', ''))
        from ai_rounds import _estimar_rounds_algoritmico
        # Numeração contínua por categoria sobre TODOS os dias (não per-dia, e não
        # só o dia filtrado) — pra o preview bater com a sidebar/ZIP.
        assign_workout_numbers_global(dias)
        itens: list[tuple[dict, dict]] = []
        for dia in dias_sel:
            for cat in dia.get('categorias', []) or []:
                workouts = cat.get('workouts', []) or []
                if not workouts:
                    continue
                _validate_workout_tipos(workouts)
                # Pré-popula n_rounds (algoritmo) pra enriquecer_workouts não bater na IA.
                for w in workouts:
                    if w.get('tipo') == 'amrap' and 'n_rounds' not in w:
                        w['n_rounds'] = _estimar_rounds_algoritmico(
                            w.get('movimentos', []), w.get('time_cap', '') or '')
                enriquecer_workouts(workouts)
                baterias       = cat.get('baterias', []) or []
                bat_com_cron   = [b for b in baterias if b.get('workouts_que_rodam')]
                algum_sem_cron = any(not b.get('workouts_que_rodam') for b in baterias)
                ev_local = {
                    **ev,
                    'categoria': cat.get('nome', '') or ev.get('categoria', ''),
                    'data':      dia.get('data', '') or ev.get('data', ''),
                }
                for wp, wkt in enumerate(workouts, start=1):
                    roda = algum_sem_cron or any(
                        wp in (b.get('workouts_que_rodam') or []) for b in bat_com_cron)
                    if baterias and not roda:
                        continue
                    itens.append((ev_local, wkt))
        if not itens:
            raise BadRequest("nenhuma súmula pra pré-visualizar")
        html = render_grid(itens, FONTS, logo, logo_evt)
        self._send(200, 'text/html; charset=utf-8', html.encode('utf-8'))

    def _handle_generate(self, body):
        """Gera ZIP de HTMLs no shape multi-dia (ver _preparar_fill_zip)."""
        fill_zip, nome_zip, _dias = self._preparar_fill_zip(body)
        # Streaming: navegador inicia o download imediatamente. Servidor
        # gera as súmulas em paralelo ao envio. Cancela o efeito "demora
        # pra começar" mesmo em ZIPs grandes (~80MB Sábado completo).
        self._send_zip_streaming(nome_zip + '.zip', fill_zip)

    def _preparar_fill_zip(self, body):
        """Valida o body e monta a geração de súmulas multi-dia.

        Estrutura: Dia/Categoria/Workout_NN.html — cada arquivo combina todas
        as alocações de TODAS as baterias dessa categoria que rodam aquele
        workout (em ordem bateria → raia).

        Toggle `incluir_competidores` (default True): se False, gera súmula em
        branco (sem nome/número/box).

        Filtros opcionais: `dia_idx` (gera só esse dia). Sem filtro, gera tudo.

        Retorna (fill_zip, nome_base, dias): fill_zip recebe qualquer objeto
        com .writestr(caminho, bytes) — o ZipFile do download de HTMLs ou o
        escritor em disco do gerador de PDFs; dias é a lista já filtrada
        (fonte dos horários de bateria pro PDF do dia completo).
        """
        cfg = body.get('config')
        if not isinstance(cfg, dict):
            raise BadRequest("config (objeto) é obrigatório")
        dias = cfg.get('dias')
        if not isinstance(dias, list) or not dias:
            raise BadRequest("config.dias deve ser lista não-vazia")

        ev       = cfg.get('evento', {}) or {}
        roster   = cfg.get('roster') or []
        logo     = _resolve_logo(ev.get('logo_empresa', ''))
        logo_evt = _resolve_logo(ev.get('logo_evento', ''))
        incluir_competidores = bool(body.get('incluir_competidores', True))

        # Numeração contínua por categoria ATRAVÉS dos dias (Elite Masc:
        # Sexta 1,2,3 → Sábado 4,5 → Domingo 6,7). Roda ANTES de filtrar por
        # dia_idx/cat_idx pra ver a sequência inteira; workouts são mutados in-
        # place, então filtros depois mantêm os números corretos.
        assign_workout_numbers_global(dias)

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

        # Filtro adicional: wkt_idx (precisa dia_idx). Gera só UM workout do dia,
        # atravessando todas as categorias. Útil pra reimprimir material de um
        # workout específico em campo (perdeu/molhou/rasgou súmula). Composto
        # ocupa 1 índice na lista (não 2) — quem escolhe 'BARBELLS+RUN' recebe
        # a súmula composta inteira (badge dual no header). Categorias que NÃO
        # têm esse índice de workout (ex: Iniciante com 2 workouts em vez de 3)
        # ficam fora silenciosamente.
        wkt_idx = body.get('wkt_idx')
        if wkt_idx is not None:
            if dia_idx is None:
                raise BadRequest("wkt_idx requer dia_idx")
            try:
                wkt_idx = int(wkt_idx)
            except (TypeError, ValueError):
                raise BadRequest("wkt_idx inválido")
            if wkt_idx < 0:
                raise BadRequest("wkt_idx deve ser >= 0")

        # Roster fill em "aguardando balizamento": habilitado quando qualquer
        # filtro (dia ou categoria) está ativo. Em escopo dia ainda pode gerar
        # muitas páginas (Monstar Sábado: ~1300 páginas / ~80MB / ~2min) mas é
        # o que o juiz pede quando marca 'incluir competidores'. Frontend já
        # mostra confirm dialog acima de 1500 páginas. Evento inteiro continua
        # bloqueado (3000+ páginas estouram timeout do Render).
        roster_fill_aguardando = dia_idx is not None or cat_idx is not None or wkt_idx is not None

        def _fill_zip(zf):
            # Closure sobre dias, ev, logo, logo_evt, incluir_competidores,
            # roster, roster_fill_aguardando — todos do enclosing scope.
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
                    # Numeração: já feita globalmente por categoria via
                    # assign_workout_numbers_global() lá em cima.
                    enriquecer_workouts(workouts)
                    baterias = cat.get('baterias', []) or []

                    # Sobrescreve categoria e data: a súmula sempre carrega a
                    # categoria do workout e a data/dia em que ele roda.
                    # Header mostra '{dia.label} {data}' quando os dois existem,
                    # garantindo que organizador veja em qual dia o workout
                    # está (ex: 'SÁBADO 30/05/2026').
                    data_combinada = ' '.join(
                        filter(None, [dia_label, dia_data or ev.get('data', '')])
                    ).strip()
                    ev_local = {
                        **ev,
                        'categoria': cat_nome,
                        'data':      data_combinada,
                    }
                    # Pre-calcula: alguma bateria deste DIA roda este workout?
                    # Se baterias têm cronograma definido e NENHUMA roda este wkt,
                    # significa que o workout não acontece neste dia — pula em vez
                    # de gerar súmula em branco que confunde o organizador.
                    baterias_com_cron = [b for b in baterias if b.get('workouts_que_rodam')]
                    algum_sem_cron = len(baterias_com_cron) < len(baterias)

                    # Ordem cronológica do prefixo do filename: workouts que rodam
                    # hoje, ordenados pelo horário do PRIMEIRO heat de cada um.
                    # Resolve confusão multi-arena (bat #45 às 10h vs bat #21 às
                    # 15h — numeração de bateria é por arena, não por tempo).
                    # Badge dentro da súmula segue wkt.numero global por categoria.
                    def _hor_primeiro_heat(wp):
                        hs = []
                        for b in baterias:
                            wqr = b.get('workouts_que_rodam') or []
                            if wqr and wp not in wqr: continue
                            h = (b.get('horario_aquecimento')
                                 or b.get('horario_fila') or '')
                            if h:
                                # zero-pad "9:30" → "09:30" pra ordenar string
                                hs.append(h.zfill(5) if len(h) == 4 else h)
                        return min(hs) if hs else 'zz:zz'
                    wkts_pos_hoje = []
                    for wp in range(1, len(workouts) + 1):
                        if not baterias:
                            wkts_pos_hoje.append(wp)
                            continue
                        if algum_sem_cron or any(wp in b['workouts_que_rodam']
                                                  for b in baterias_com_cron):
                            wkts_pos_hoje.append(wp)
                    wkts_ordenados = sorted(wkts_pos_hoje, key=_hor_primeiro_heat)
                    ordem_cron = {p: i + 1 for i, p in enumerate(wkts_ordenados)}

                    for wkt_pos, wkt in enumerate(workouts, start=1):
                        # Filtro wkt_idx: gera só esse workout (índice 0-based).
                        # Categorias sem esse índice ficam fora silenciosamente.
                        if wkt_idx is not None and (wkt_pos - 1) != wkt_idx:
                            continue
                        # Skip se cronograma definido e nenhuma bateria do dia roda
                        # este wkt. Baterias sem cronograma rodam tudo (compat).
                        roda_este_wkt = (
                            algum_sem_cron
                            or any(wkt_pos in b['workouts_que_rodam']
                                   for b in baterias_com_cron)
                        )
                        if baterias and not roda_este_wkt:
                            continue
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

                        # Prefixo do filename = ordem cronológica do dia (multi-arena
                        # safe). Badge dentro da súmula continua mostrando numero
                        # global por categoria (wkt.numero).
                        prefixo = ordem_cron.get(wkt_pos, wkt_pos)
                        nome_arq = f"{prefixo:02d}_{sanitize(wkt.get('nome', 'wkt'))}.html"
                        caminho  = f"{dia_pasta}/{cat_pasta}/{nome_arq}"

                        # Detecta "aguardando balizamento": existem baterias que
                        # rodam este wkt MAS nenhuma tem atleta alocado ainda.
                        # Caso típico do Domingo no Monstar — balizamento depende
                        # do resultado do dia anterior.
                        bat_que_rodam = [
                            b for b in baterias
                            if not b.get('workouts_que_rodam')
                            or wkt_pos in b.get('workouts_que_rodam', [])
                        ]
                        aguardando = (
                            bool(bat_que_rodam) and not atletas
                            and any(b.get('workouts_que_rodam') for b in bat_que_rodam)
                        )
                        # Aguardando balizamento: SEMPRE popula atletas do roster da
                        # categoria (com raia/bateria em branco pro juiz preencher),
                        # independente do toggle 'Incluir competidores'. O toggle
                        # serve pra gerar súmulas em branco com atletas alocados
                        # (uso de fotocópia); em categoria aguardando não há atleta
                        # alocado pra ocultar — sem o roster, a súmula sai inútil.
                        roster_fill_ativo = (
                            aguardando and roster and roster_fill_aguardando
                        )
                        if roster_fill_ativo:
                            atletas = [
                                {'nome': r.get('nome', ''), 'box': r.get('box', ''),
                                 'raia': '', 'bateria': '', 'numero': r.get('numero', '')}
                                for r in roster
                                if (r.get('categoria') or '').strip() == cat_nome.strip()
                            ]
                        ev_render = {**ev_local, 'aguardando_balizamento': aguardando} if aguardando else ev_local

                        # Combined renderiza atletas; render simples = página em branco.
                        # roster_fill_ativo bypassa o toggle pra preservar os nomes
                        # da regra "aguardando".
                        if atletas and (incluir_competidores or roster_fill_ativo):
                            html = render_workout_combined(ev_render, wkt, FONTS, logo, logo_evt, atletas)
                        else:
                            html = render_workout(ev_render, wkt, FONTS, logo, logo_evt)
                        zf.writestr(caminho, html.encode('utf-8'))
                        # 'render_for_load_team_summary' fica disponível mas
                        # não é auto-acionado: no modelo atual dupla/time = 1
                        # entrada no Excel (cada alocação já É o time inteiro).
                        # Se um dia houver agrupamento por time_id de atletas
                        # individuais, esta é a hora de chamar o resumo.

        nome_base = sanitize(ev.get('nome', '') or 'sumulas') or 'sumulas'
        return _fill_zip, nome_base, dias

    def _handle_generate_pdfs(self, body):
        """Gera ZIP de PDFs organizados por bateria (local only).

        Mesmo body do /api/generate. Gera os MESMOS HTMLs (via
        _preparar_fill_zip, byte-idêntico ao ZIP de HTMLs), converte com o
        Chrome headless da máquina (gerar_pdfs.converter) e devolve ZIP com:
          Dia/Categoria/Workout/Bateria_NN.pdf  +  Dia/00_DIA_COMPLETO.pdf
        (dia completo em ordem horário → bateria → raia).

        No Render não há Chrome → endpoint responde 400 e o frontend nem
        mostra o botão (status.pdf_ativo == false).
        """
        if not PDF_CHROME:
            raise BadRequest("geração de PDF indisponível — Google Chrome não "
                             "encontrado nesta máquina (recurso local)")
        fill_zip, nome_base, dias = self._preparar_fill_zip(body)
        horarios = horarios_do_config({'dias': dias})

        tmp = tempfile.mkdtemp(prefix='sumulas_app_pdf_')
        try:
            raiz  = os.path.join(tmp, 'html')
            saida = os.path.join(tmp, 'pdf')

            class _DiskWriter:
                """Duck-type do ZipFile: fill_zip só usa .writestr()."""
                def writestr(self, caminho, data):
                    destino = os.path.join(raiz, caminho)
                    os.makedirs(os.path.dirname(destino), exist_ok=True)
                    with open(destino, 'wb') as f:
                        f.write(data)

            fill_zip(_DiskWriter())
            feitos, erros = converter_pdfs(raiz, saida, horarios, PDF_CHROME)
            if erros:
                raise RuntimeError(f"{len(erros)} PDF(s) falharam: {erros[0]}")

            def _fill(zf):
                base = pathlib.Path(saida)
                for pdf in sorted(base.rglob('*.pdf')):
                    zf.writestr(str(pdf.relative_to(base)), pdf.read_bytes())
            self._send_zip_streaming(f'{nome_base}_PDFs.zip', _fill)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _handle_generate_pre_evento(self, body):
        """Gera ZIP de súmulas 'pré-evento' — para atletas/times inscritos no
        roster mas ainda SEM bateria/raia alocada.

        Estrutura: Categoria/Workout_NN.html — N páginas (1 por não-alocado).
        Sem dia (atleta ainda não tem cronograma definido). Todos os workouts
        da categoria são gerados, agregando de todos os dias em que ela aparece.

        Cada página tem nome + box do atleta, mas raia, bateria e número
        (do atleta na bateria) ficam em branco — juiz preenche à mão depois.
        """
        cfg = body.get('config')
        if not isinstance(cfg, dict):
            raise BadRequest("config (objeto) é obrigatório")
        dias = cfg.get('dias') or []
        roster = cfg.get('roster') or []
        if not roster:
            raise BadRequest("roster vazio — não há atletas inscritos")

        ev       = cfg.get('evento', {}) or {}
        logo     = _resolve_logo(ev.get('logo_empresa', ''))
        logo_evt = _resolve_logo(ev.get('logo_evento', ''))

        # Junta workouts por categoria (de todos os dias) + identifica alocados
        # Estrutura: {categoria_nome: {'workouts':[...], 'alocados_nums': set}}
        cats_agg: dict[str, dict] = {}
        for dia in dias:
            for cat in dia.get('categorias', []) or []:
                cnome = cat.get('nome', '')
                if not cnome: continue
                bucket = cats_agg.setdefault(cnome, {'workouts': [], 'alocados_nums': set()})
                # Agrega workouts (evita duplicar pela posição/nome)
                for w in cat.get('workouts', []) or []:
                    bucket['workouts'].append(w)
                # Coleta números alocados em qualquer bateria desta categoria
                for b in cat.get('baterias', []) or []:
                    for aloc in b.get('alocacoes', []) or []:
                        num = str(aloc.get('numero', '')).strip()
                        if num: bucket['alocados_nums'].add(num)

        # Pra cada entrada do roster, identifica categoria e filtra os não-alocados
        nao_alocados_por_cat: dict[str, list[dict]] = {}
        for atl in roster:
            cat_nome = atl.get('categoria', '') or ''
            if not cat_nome: continue
            num = str(atl.get('numero', '')).strip()
            if not num: continue
            bucket = cats_agg.get(cat_nome)
            if not bucket: continue   # categoria do roster não existe nos dias
            if num in bucket['alocados_nums']: continue   # já tem bateria/raia
            nao_alocados_por_cat.setdefault(cat_nome, []).append(atl)

        if not nao_alocados_por_cat:
            raise BadRequest(
                "Nenhum atleta/time inscrito está sem bateria — "
                "todos do roster já estão alocados."
            )

        def _fill_zip(zf):
            for cat_nome, nao_alocados in nao_alocados_por_cat.items():
                workouts = cats_agg[cat_nome]['workouts']
                if not workouts: continue
                _validate_workout_tipos(workouts)
                assign_workout_numbers(workouts)
                enriquecer_workouts(workouts)
                cat_pasta = sanitize(cat_nome)
                ev_local = {**ev, 'categoria': cat_nome, 'data': ev.get('data', '')}

                # Converte roster em "atletas" (raia/bateria vazias)
                atletas = [
                    {
                        'nome':    a.get('nome', ''),
                        'box':     a.get('box', ''),
                        'raia':    '',
                        'bateria': '',
                        'numero':  a.get('numero', ''),
                    }
                    for a in nao_alocados
                ]
                for wkt_pos, wkt in enumerate(workouts, start=1):
                    nome_arq = f"{wkt_pos:02d}_{sanitize(wkt.get('nome', 'wkt'))}.html"
                    caminho  = f"Pre-Evento/{cat_pasta}/{nome_arq}"
                    html = render_workout_combined(ev_local, wkt, FONTS, logo, logo_evt, atletas)
                    zf.writestr(caminho, html.encode('utf-8'))

        nome_zip = (sanitize(ev.get('nome', '') or 'sumulas') or 'sumulas') + '_pre-evento.zip'
        self._send_zip_streaming(nome_zip, _fill_zip)

    def _handle_import_excel(self, body):
        data_b64 = body.get('data')
        if not data_b64:
            raise BadRequest("campo 'data' (Excel em base64) é obrigatório")
        try:
            data = base64.b64decode(data_b64)
        except (ValueError, TypeError) as e:
            raise BadRequest(f"base64 inválido: {e}")
        try:
            result = parse_excel(data)
        except Exception as e:
            # Excel corrompido / formato desconhecido — input ruim, 400
            self._send(400, 'application/json; charset=utf-8',
                       json.dumps({"error": f"falha ao parsear Excel: {e}"}).encode('utf-8'))
            return
        if result.get('tipo') == 'erro':
            self._send(400, 'application/json; charset=utf-8',
                       json.dumps({"error": result.get('erro', 'formato não reconhecido')}).encode('utf-8'))
            return
        # Numeração contínua por categoria atravessando dias — já vem assignada
        # pro frontend usar na sidebar e no editor, sem precisar recomputar.
        assign_workout_numbers_global(result.get('dias') or [])
        # Linter 2.0: unifica avisos do parser (avisos_import, chave legada
        # 'nivel') com os do validar_evento (chave 'severidade') numa lista só,
        # pro frontend mostrar tudo num painel antes de gerar.
        avisos_parser = []
        for a in (result.get('avisos_import') or []):
            a = dict(a)
            a.setdefault('severidade', a.get('nivel', 'aviso'))
            avisos_parser.append(a)
        try:
            avisos_valid = validar_evento(result)
        except Exception:
            avisos_valid = []
        # Colapsa repetitivos (ex: 394× 'competidor em 2 lugares') pro painel não afogar.
        result['avisos_import'] = colapsar_avisos(avisos_parser + avisos_valid)
        self._send(200, 'application/json; charset=utf-8',
                   json.dumps(result, ensure_ascii=False).encode('utf-8'))

    def _handle_sugerir_time_cap(self, body):
        """Sugere um time cap baseado nos movimentos. Body: {movimentos, tipo}."""
        movimentos = body.get('movimentos', [])
        if not isinstance(movimentos, list):
            raise BadRequest("movimentos deve ser lista")
        tipo = body.get('tipo', 'for_time')
        sugestao = sugerir_time_cap(movimentos, tipo)
        self._send(200, 'application/json; charset=utf-8',
                   json.dumps({'time_cap': sugestao}).encode('utf-8'))

    def _handle_auto_descricao(self, body):
        """Gera linhas de descrição (notas) a partir do workout. Body: {workout}."""
        workout = body.get('workout', {})
        if not isinstance(workout, dict):
            raise BadRequest("workout deve ser objeto")
        linhas = auto_descricao(workout)
        self._send(200, 'application/json; charset=utf-8',
                   json.dumps({'descricao': linhas}, ensure_ascii=False).encode('utf-8'))

    def _handle_validar_evento(self, body):
        """Detecta erros pré-evento. Body: {config}."""
        cfg = body.get('config')
        if not isinstance(cfg, dict):
            raise BadRequest("config (objeto) é obrigatório")
        avisos = colapsar_avisos(validar_evento(cfg))
        self._send(200, 'application/json; charset=utf-8',
                   json.dumps({'avisos': avisos}, ensure_ascii=False).encode('utf-8'))

    def _handle_resumo_evento(self, body):
        """Resumo curto do evento. Body: {config}."""
        cfg = body.get('config')
        if not isinstance(cfg, dict):
            raise BadRequest("config (objeto) é obrigatório")
        resumo = resumo_evento(cfg)
        self._send(200, 'application/json; charset=utf-8',
                   json.dumps({'resumo': resumo}, ensure_ascii=False).encode('utf-8'))

    def _handle_explicar_avisos(self, body):
        """Explica avisos do import em linguagem humanizada via IA.

        Body: {stats: {...}, avisos: [...]}
        Rate limit já aplicado no dispatch (gate /api/ai/*).
        """
        if not AI_ATIVO:
            self._send(200, 'application/json; charset=utf-8',
                       json.dumps({'error': 'IA inativa', 'ai_ativo': False},
                                  ensure_ascii=False).encode('utf-8'))
            return
        stats = body.get('stats') or {}
        avisos = body.get('avisos') or []
        if not isinstance(avisos, list):
            raise BadRequest("avisos deve ser lista")
        try:
            texto = explicar_avisos_import(stats, avisos)
        except Exception as e:
            traceback.print_exc()
            self._send(200, 'application/json; charset=utf-8',
                       json.dumps({'error': _mensagem_erro_ia(e), 'ai_ativo': True},
                                  ensure_ascii=False).encode('utf-8'))
            return
        self._send(200, 'application/json; charset=utf-8',
                   json.dumps({'texto': texto}, ensure_ascii=False).encode('utf-8'))

    def _handle_revisar_programacao(self, body):
        """Review de PROGRAMAÇÃO por IA — escalonamento invertido, sanidade de
        carga cross-divisão etc. (o que o linter determinístico não pega).
        Body: {config}. Rate limit já aplicado no gate /api/ai/*.
        """
        if not AI_ATIVO:
            self._send(200, 'application/json; charset=utf-8',
                       json.dumps({'error': 'IA inativa', 'ai_ativo': False},
                                  ensure_ascii=False).encode('utf-8'))
            return
        cfg = body.get('config')
        if not isinstance(cfg, dict):
            raise BadRequest("config (objeto) é obrigatório")
        try:
            avisos = revisar_programacao_ia(cfg)
        except Exception as e:
            traceback.print_exc()
            self._send(200, 'application/json; charset=utf-8',
                       json.dumps({'error': _mensagem_erro_ia(e), 'ai_ativo': True},
                                  ensure_ascii=False).encode('utf-8'))
            return
        self._send(200, 'application/json; charset=utf-8',
                   json.dumps({'avisos': avisos}, ensure_ascii=False).encode('utf-8'))

    def _handle_revisar_leitura(self, body):
        """Fase 3: IA confere a FIDELIDADE da leitura (parse vs texto do Excel) e
        aponta divergências antes da impressão. Body: {config}. Requer que os
        workouts carreguem '_raw' (anexado na importação).
        """
        if not AI_ATIVO:
            self._send(200, 'application/json; charset=utf-8',
                       json.dumps({'error': 'IA inativa', 'ai_ativo': False},
                                  ensure_ascii=False).encode('utf-8'))
            return
        cfg = body.get('config')
        if not isinstance(cfg, dict):
            raise BadRequest("config (objeto) é obrigatório")
        try:
            avisos = revisar_leitura_ia(cfg)
        except Exception as e:
            traceback.print_exc()
            self._send(200, 'application/json; charset=utf-8',
                       json.dumps({'error': _mensagem_erro_ia(e), 'ai_ativo': True},
                                  ensure_ascii=False).encode('utf-8'))
            return
        self._send(200, 'application/json; charset=utf-8',
                   json.dumps({'avisos': avisos}, ensure_ascii=False).encode('utf-8'))

    def _handle_chat(self, body):
        """Chat com Claude tendo o config como contexto. Body: {messages, config}.
        Rate limit já aplicado no dispatch (gate /api/ai/*)."""
        if not AI_ATIVO:
            self._send(200, 'application/json; charset=utf-8',
                       json.dumps({'error': 'IA inativa', 'ai_ativo': False}, ensure_ascii=False).encode('utf-8'))
            return
        mensagens = body.get('messages')
        if not isinstance(mensagens, list) or not mensagens:
            raise BadRequest("messages deve ser lista não-vazia")
        cfg = body.get('config') or {}
        try:
            resposta = chat_evento(mensagens, cfg)
        except Exception as e:
            traceback.print_exc()   # stack completo no log do servidor
            self._send(200, 'application/json; charset=utf-8',
                       json.dumps({'error': _mensagem_erro_ia(e), 'ai_ativo': True},
                                  ensure_ascii=False).encode('utf-8'))
            return
        self._send(200, 'application/json; charset=utf-8',
                   json.dumps({'resposta': resposta}, ensure_ascii=False).encode('utf-8'))

    def _handle_import_pdf(self, body):
        data_b64 = body.get('data')
        if not data_b64:
            raise BadRequest("campo 'data' (PDF em base64) é obrigatório")
        try:
            data = base64.b64decode(data_b64)
        except (ValueError, TypeError) as e:
            raise BadRequest(f"base64 inválido: {e}")
        try:
            result = parse_pdf(data)
        except Exception as e:
            self._send(400, 'application/json; charset=utf-8',
                       json.dumps({"error": f"falha ao parsear PDF: {e}"}).encode('utf-8'))
            return
        self._send(200, 'application/json; charset=utf-8',
                   json.dumps(result, ensure_ascii=False).encode('utf-8'))

    def _send(self, code, content_type, data, extra=None):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Connection', 'close')   # encerra conexão (evita keep-alive)
        # Em dev local: CORS aberto pra facilitar (pode chamar API de outro port).
        # Em cloud: omite o header — same-origin já basta (frontend e API mesma origem)
        # e evita expor /api/* pra qualquer site cross-origin.
        if not IS_CLOUD:
            self.send_header('Access-Control-Allow-Origin', '*')
        if extra:
            for k, v in extra.items(): self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _send_zip_streaming(self, filename, fill_zip_callback):
        """Envia ZIP em chunked encoding — browser inicia download imediatamente,
        antes mesmo do servidor terminar de gerar tudo. fill_zip_callback recebe
        o ZipFile aberto e escreve os arquivos com zf.writestr(path, data).
        Compressão nível 1 (rápida; ZIP só ~10% maior que default 6)."""
        self.send_response(200)
        self.send_header('Content-Type', 'application/zip')
        self.send_header('Transfer-Encoding', 'chunked')
        self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.send_header('Connection', 'close')
        if not IS_CLOUD:
            self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        cw = _ChunkedWriter(self.wfile)
        try:
            with zipfile.ZipFile(cw, 'w', zipfile.ZIP_DEFLATED,
                                 allowZip64=True, compresslevel=1) as zf:
                fill_zip_callback(zf)
        finally:
            cw.close_chunks()


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
