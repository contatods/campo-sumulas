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
VERSION = '1.2.3'

# Teto de body em POST (Excel + logos). 50 MB cobre o pior caso real do evento.
MAX_BODY_BYTES = 50 * 1024 * 1024


class BadRequest(ValueError):
    """Payload inválido — handler devolve 400 com a mensagem."""
    pass

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

# ── Parsers opcionais ───────────────────────────────────────────────────────────
try:
    import openpyxl; HAS_EXCEL = True
except ImportError:
    HAS_EXCEL = False

try:
    import pdfplumber; HAS_PDF = True
except ImportError:
    HAS_PDF = False

# ── IA (Anthropic) — opcional ───────────────────────────────────────────────────
try:
    import anthropic; HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

AI_KEY   = os.environ.get('ANTHROPIC_API_KEY', '')
AI_ATIVO = HAS_ANTHROPIC and bool(AI_KEY)

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


# ── Parsers de texto de workout ─────────────────────────────────────────────────
BLOCK_LABELS = {1: "1º BLOCO", 2: "2º BLOCO", 3: "3º BLOCO", 4: "4º BLOCO", 5: "5º BLOCO"}

def _parse_mov_line(line):
    """Extrai (reps, nome_upper) de uma linha de movimento.
    O número inicial é SEMPRE tratado como reps — metros, calorias, etc.
    Ex: '20-metres Dumbbell Lunges' → reps=20, nome='20-METRES DUMBBELL LUNGES'
    Ex: '20 Pull-Ups'              → reps=20, nome='PULL-UPS'
    """
    m = re.match(r'^(\d{1,4})([-\s])(.+)$', line.strip())
    if not m: return None
    num_s, sep, rest = m.group(1), m.group(2), m.group(3).strip()
    try: num = int(num_s)
    except: return None
    if num >= 1000: return None  # evita anos
    # Se o separador é hífen (20-metres, 40-ft...), mantém o número no nome
    if sep == '-':
        nome = f"{num_s}-{rest}".upper()
    else:
        nome = rest.upper()
    return (num, nome)

def parse_workout_text(text, numero):
    """Converte o texto livre de uma célula/seção num dict de workout."""
    lines = [l.strip() for l in str(text).split('\n') if l.strip()]
    wkt = {"numero": numero, "nome": f"WKT {numero}", "tipo": "for_time",
           "modalidade": "individual", "time_cap": "", "movimentos": [], "descricao": []}

    # Nome: primeira linha entre aspas (simples, duplas, curvas)
    if lines:
        m = re.match(r'^["“‘](.+?)["”’]', lines[0])
        if m:
            wkt["nome"] = m.group(1).strip().upper()
        elif not re.match(r'^\d', lines[0]):
            wkt["nome"] = lines[0].strip('"“”').upper()[:40]

    # Detecta Express antes de qualquer outra coisa
    if any(re.search(r'express formula', l, re.I) for l in lines):
        return _parse_express(lines, wkt)

    # Tipo
    full = '\n'.join(lines).lower()
    if 'for time' in full or 'por tempo' in full:
        wkt["tipo"] = "for_time"
    elif 'amrap' in full or 'as many reps' in full:
        wkt["tipo"] = "amrap"

    # Movimentos, separadores, time cap
    movs = []
    block = 1
    has_seps = any(re.match(r'^then\.+$', l, re.I) for l in lines)
    skip_prefixes = ('for time', 'por tempo', 'amrap', 'as many reps', 'rest',
                     'atenção', 'atencao', 'obs', 'note', '"', '“')

    for line in lines:
        ll = line.lower()
        # Time cap
        tc = re.search(r'time\s*cap[:\s]+(\d+)\s*min', line, re.I)
        if tc: wkt["time_cap"] = f"{tc.group(1)} min"; continue
        # Separador
        if re.match(r'^then[\.\s]*$', line, re.I):
            if movs: movs.append({"separador": "then..."})
            block += 1; continue
        # Linhas de instrução a ignorar como movimentos
        if any(ll.startswith(p) for p in skip_prefixes): continue
        # Movimento
        parsed = _parse_mov_line(line)
        if parsed:
            reps, nome = parsed
            mov = {"nome": nome}
            if reps is not None: mov["reps"] = reps
            if has_seps and block in BLOCK_LABELS: mov["label"] = BLOCK_LABELS[block]
            movs.append(mov)

    if wkt["tipo"] == "for_time" and movs:
        movs.append({"chegada": True})
    wkt["movimentos"] = movs
    return wkt


def _parse_express(lines, wkt):
    """Extrai fórmulas 1 e 2 de um workout Express."""
    wkt["tipo"] = "express"; wkt["estilo"] = "express"
    f1_lines, f2_lines, current = [], [], None
    f1_janela = f2_janela = ""

    for line in lines:
        m1 = re.search(r'Express Formula 1.{0,5}[([]?([0-9]{2}:[0-9]{2}[^)\]]*)', line, re.I)
        m2 = re.search(r'Express Formula 2.{0,5}[([]?([0-9]{2}:[0-9]{2}[^)\]]*)', line, re.I)
        if re.search(r'Express Formula 1', line, re.I):
            current = 'f1'
            if m1:
                j = m1.group(1).strip().strip(')').replace('-', ' -> ')
                f1_janela = j + '  .  AMRAP'
            continue
        if re.search(r'Express Formula 2', line, re.I):
            current = 'f2'
            if m2:
                j = m2.group(1).strip().strip(')').replace('-', ' -> ')
                f2_janela = j + '  .  FOR TIME'
            continue
        if current == 'f1': f1_lines.append(line)
        elif current == 'f2': f2_lines.append(line)

    def extract_movs(flines, add_chegada=False):
        movs, tc_val = [], ""
        for line in flines:
            tc = re.search(r'time\s*cap[:\s]+(\d+)\s*min', line, re.I)
            if tc: tc_val = f"{tc.group(1)} min"; continue
            if re.match(r'^then[\.\s]*$', line, re.I):
                if movs: movs.append({"separador": "then..."}); continue
            p = _parse_mov_line(line)
            if p:
                reps, nome = p
                mov = {"nome": nome}
                if reps is not None: mov["reps"] = reps
                movs.append(mov)
        if add_chegada and movs: movs.append({"chegada": True})
        return movs, tc_val

    f1_movs, _     = extract_movs(f1_lines, False)
    f2_movs, tc    = extract_movs(f2_lines, True)
    if tc: wkt["time_cap"] = tc

    # Corrige nome: "EXPRESS FORMULA 1" → "EXPRESS FORMULA"
    if re.search(r'\s+[12]$', wkt["nome"]):
        wkt["nome"] = re.sub(r'\s+[12]$', '', wkt["nome"]).strip()

    wkt["formula1"] = {"janela": f1_janela or "00:00 → 05:00  ·  AMRAP 5 MIN",
                       "descricao": [], "movimentos": f1_movs}
    wkt["formula2"] = {"janela": f2_janela or "06:00 → 12:00  ·  FOR TIME",
                       "descricao": [], "movimentos": f2_movs}
    return wkt


def _is_categoria_grid(ws):
    """Detecta se a aba tem formato grade (colunas=categorias, linhas=workouts)."""
    rows = list(ws.iter_rows(min_row=1, max_row=3, values_only=True))
    if len(rows) < 2: return False
    r1 = [c for c in rows[0] if c is not None]
    r2 = [c for c in rows[1] if c is not None]
    return (len(r1) >= 2
            and all(isinstance(v, str) for v in r1[:4])
            and r2 and isinstance(r2[0], str) and '\n' in r2[0])


# ── Excel import ────────────────────────────────────────────────────────────────
def parse_excel(data):
    if not HAS_EXCEL:
        raise RuntimeError("openpyxl não disponível — instale com: pip install openpyxl")
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)

    # Detecta formato grade em TODAS as abas e combina tudo
    todas_categorias = {}
    evento_nome = ""
    for sname in wb.sheetnames:
        ws = wb[sname]
        if _is_categoria_grid(ws):
            resultado = _parse_excel_grade(wb, sname)
            todas_categorias.update(resultado.get("por_categoria", {}))
            if not evento_nome:
                evento_nome = resultado.get("evento_nome", "")

    # Lê atletas de qualquer aba com a coluna "Nome" (ou "Atleta")
    atletas_por_categoria = _parse_atletas(wb)

    if todas_categorias:
        return {
            "tipo": "categoria_grid",
            "evento_nome": evento_nome,
            "categorias": list(todas_categorias.keys()),
            "por_categoria": todas_categorias,
            "atletas_por_categoria": atletas_por_categoria
        }

    # Fallback: formato template
    return _parse_excel_template(wb)


def _parse_atletas(wb):
    """Lê atletas de qualquer aba que tenha as colunas: Nome/Atleta, Box, Raia, Bateria, Nº.
    Retorna dict { categoria: [ {nome, box, raia, bateria, numero}, ... ] }
    """
    CAMPOS = {
        "nome":    ["nome", "atleta", "name", "athlete"],
        "box":     ["box", "afiliacao", "afiliação", "affiliate", "team"],
        "raia":    ["raia", "lane"],
        "bateria": ["bateria", "heat", "bat"],
        "numero":  ["numero", "número", "nº", "no", "number", "id", "inscricao", "inscrição"],
        "categoria": ["categoria", "category", "cat"],
    }

    def encontrar_col(header_row, opcoes):
        for i, v in enumerate(header_row):
            if v and str(v).strip().lower() in opcoes:
                return i
        return None

    resultado = {}

    for sname in wb.sheetnames:
        ws = wb[sname]
        rows = list(ws.iter_rows(values_only=True))
        if len(rows) < 2: continue

        # Procura linha de cabeçalho (primeiras 3 linhas)
        header_row_idx = None
        header_row = None
        for ri in range(min(3, len(rows))):
            row = [str(v).strip().lower() if v else "" for v in rows[ri]]
            if any(op in row for op in CAMPOS["nome"]):
                header_row_idx = ri
                header_row = rows[ri]
                break
        if header_row is None: continue

        col = {k: encontrar_col(header_row, v) for k, v in CAMPOS.items()}
        if col["nome"] is None: continue  # sem coluna de nome, ignora

        for row in rows[header_row_idx + 1:]:
            if not row or all(v is None for v in row): continue
            def cell(idx):
                if idx is None: return ""
                v = row[idx] if idx < len(row) else None
                return str(v).strip() if v is not None else ""

            nome = cell(col["nome"])
            if not nome: continue

            atleta = {
                "nome":    nome,
                "box":     cell(col["box"]),
                "raia":    cell(col["raia"]),
                "bateria": cell(col["bateria"]),
                "numero":  cell(col["numero"]),
            }

            cat = cell(col["categoria"]) if col["categoria"] is not None else sname
            if not cat or cat.lower() in ("atletas","inscritos","participants","athletes"):
                cat = sname

            if cat not in resultado:
                resultado[cat] = []
            resultado[cat].append(atleta)

    return resultado


def _atleta_sort_key(a):
    """Chave de ordenação para impressão sequencial: bateria → raia → nome.
    Raia é tratada numericamente quando possível ("10" depois de "2")."""
    bateria  = str(a.get('bateria', '') or '').strip().upper()
    raia_raw = str(a.get('raia', '') or '').strip()
    m = re.match(r'^(\d+)', raia_raw)
    raia_num = int(m.group(1)) if m else 10**9
    nome = str(a.get('nome', '') or '').strip().lower()
    return (bateria, raia_num, raia_raw.lower(), nome)


def assign_workout_numbers(workouts):
    """Recalcula números de workouts considerando slots.
    Express Formula ocupa 2 slots (N e N+1). Outros ocupam 1 slot.
    Modifica a lista in-place e retorna ela.
    """
    counter = 1
    for wkt in workouts:
        wkt['numero'] = counter
        if wkt.get('tipo') == 'express':
            wkt['numero_f2'] = counter + 1
            counter += 2
        else:
            wkt.pop('numero_f2', None)
            counter += 1
    return workouts


# ── Rounds AMRAP: estimativa algorítmica e por IA ──────────────────────────────

def _extrair_minutos(texto):
    """Extrai duração em minutos de strings como:
       '10 min', 'AMRAP 5 MIN', '00:00 → 05:00', 'Time Cap: 8 min'
    """
    if not texto: return None
    t = str(texto)
    m = re.search(r'amrap\s+(\d+)\s*min', t, re.I)
    if m: return int(m.group(1))
    # "XX:XX → YY:YY" — extrai duração entre os dois horários
    m = re.search(r'(\d{1,2}):(\d{2})\s*[→\-]+\s*(\d{1,2}):(\d{2})', t)
    if m:
        s = int(m.group(1)) * 60 + int(m.group(2))
        e = int(m.group(3)) * 60 + int(m.group(4))
        return max(1, (e - s) // 60)
    m = re.search(r'(\d+)\s*min', t, re.I)
    if m: return int(m.group(1))
    return None


def _estimar_rounds_algoritmico(movimentos, duracao_str):
    """Estimativa de rounds baseada em reps totais e tempo disponível.
    Usa pace conservador de ~6-10 reps/min dependendo do volume.
    Retorna número de linhas a mostrar no scorecard (rounds esperados + buffer).
    """
    mins = _extrair_minutos(duracao_str or '')
    if not mins: return 4
    movs = [m for m in (movimentos or [])
            if not m.get('separador') and not m.get('chegada')]
    reps_round = sum(int(m['reps']) for m in movs if m.get('reps') and str(m['reps']).isdigit())
    if not reps_round: return 4
    # Pace: menos reps/min em workouts de alto volume (fadiga acumulada)
    pace = 6 if reps_round > 50 else 8 if reps_round > 25 else 10
    rounds_esperados = (mins * pace) / reps_round
    # Retorna rounds esperados + 2 para atletas mais rápidos
    return max(3, round(rounds_esperados) + 2)


def _estimar_rounds_ia(movimentos, duracao_str):
    """Usa Claude Haiku para estimar rounds esperados num AMRAP.
    Faz fallback algorítmico se IA não estiver disponível ou falhar.
    """
    if not AI_ATIVO:
        return _estimar_rounds_algoritmico(movimentos, duracao_str)
    mins = _extrair_minutos(duracao_str or '') or 5
    movs = [m for m in (movimentos or [])
            if not m.get('separador') and not m.get('chegada')]
    desc = ', '.join(f"{m.get('reps','')}x {m.get('nome','')}" for m in movs if m.get('nome'))
    if not desc:
        return _estimar_rounds_algoritmico(movimentos, duracao_str)
    try:
        # timeout=15s evita pendurar o handler quando a API está lenta.
        client = anthropic.Anthropic(api_key=AI_KEY, timeout=15.0)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=20,
            messages=[{
                "role": "user",
                "content": (
                    f"CrossFit AMRAP {mins} min: {desc}. "
                    "Quantos rounds completos um atleta intermediário faria? "
                    "Responda apenas com o número inteiro, sem mais texto."
                )
            }]
        )
        match = re.search(r'\d+', resp.content[0].text) if resp.content else None
        if not match:
            return _estimar_rounds_algoritmico(movimentos, duracao_str)
        n = int(match.group())
        return max(2, n + 2)   # n esperados + 2 linhas de buffer no scorecard
    except Exception as e:
        print(f"  ⚠  IA rounds: {e}")
        return _estimar_rounds_algoritmico(movimentos, duracao_str)


def enriquecer_workouts(workouts):
    """Calcula campos derivados para todos os workouts antes de renderizar.
    - AMRAP: adiciona 'n_rounds' (estimado por IA ou algoritmo)
    - Express F1: adiciona 'n_rounds' na formula1
    """
    for wkt in workouts:
        if wkt.get('tipo') == 'amrap':
            duracao = wkt.get('time_cap', '') or ''
            if 'n_rounds' not in wkt:
                wkt['n_rounds'] = _estimar_rounds_ia(wkt.get('movimentos', []), duracao)
        elif wkt.get('tipo') == 'express':
            f1 = wkt.get('formula1', {})
            if f1 and 'n_rounds' not in f1:
                f1['n_rounds'] = _estimar_rounds_ia(f1.get('movimentos', []), f1.get('janela', ''))
    return workouts


def _parse_excel_grade(wb, sname):
    """Parseia formato grade: col=categoria, linha=workout."""
    ws = wb[sname]
    rows = list(ws.iter_rows(values_only=True))
    if not rows: return {"erro": "Planilha vazia"}

    # Linha 0 = cabeçalhos de categoria
    categorias = []
    for col_idx, val in enumerate(rows[0]):
        if val is not None:
            categorias.append((col_idx, str(val).strip()))

    # Linhas 1+ = workouts
    por_categoria = {}
    for cat_idx, cat_nome in categorias:
        workouts = []
        for row_num, row in enumerate(rows[1:], 1):
            if cat_idx >= len(row) or row[cat_idx] is None: continue
            cell_text = str(row[cat_idx]).strip()
            if not cell_text: continue
            wkt = parse_workout_text(cell_text, row_num)
            workouts.append(wkt)
        if workouts:
            por_categoria[cat_nome] = workouts

    # Tentar extrair nome do evento do nome do arquivo ou da planilha
    evento_nome = sname if sname.lower() not in ('individuais','duplas','equipamento') else ""

    return {
        "tipo": "categoria_grid",
        "evento_nome": evento_nome,
        "categorias": [c for _, c in categorias if c in por_categoria],
        "por_categoria": por_categoria
    }


def _parse_excel_template(wb):
    """Parseia formato template (Evento + Workouts + WKT1, WKT2...)."""
    config = {"evento": {"nome": "", "categoria": "", "data": ""}, "workouts": []}
    wkt_map = {}
    for sname in wb.sheetnames:
        sl = sname.strip().lower()
        if sl == "evento":
            ws = wb[sname]
            for row in ws.iter_rows(values_only=True):
                if not row or not row[0]: continue
                k = str(row[0]).strip().lower()
                v = str(row[1]).strip() if len(row) > 1 and row[1] is not None else ""
                if k in ("nome","name","evento"): config["evento"]["nome"] = v
                elif k in ("categoria","category"): config["evento"]["categoria"] = v
                elif k in ("data","date"): config["evento"]["data"] = v
        m = re.match(r'^(?:wkt|workout)\s*[-_]?\s*(\d+)$', sl)
        if not m: continue
        num = int(m.group(1))
        ws = wb[sname]; hdrs = None; movs = []
        for row in ws.iter_rows(values_only=True):
            if not any(row): continue
            if hdrs is None: hdrs = [str(c or "").strip().lower() for c in row]; continue
            first = str(row[0] or "").strip().lower()
            if first in ("then...","then","então","---"): movs.append({"separador":"then..."}); continue
            if first in ("chegada","finish","arrival"): movs.append({"chegada":True}); continue
            mov = {}
            for i, h in enumerate(hdrs):
                if i >= len(row) or row[i] is None: continue
                v = str(row[i]).strip()
                if not v: continue
                if h in ("movimento","exercise","movement","nome","name"): mov["nome"] = v.upper()
                elif h in ("reps","rep","repetições"):
                    try: mov["reps"] = int(float(v))
                    except: mov["reps"] = v
                elif h in ("label","bloco","grupo","block"): mov["label"] = v
            if "nome" in mov: movs.append(mov)
        wkt = {"numero": num, "nome": f"WKT {num}", "tipo": "for_time",
               "modalidade": "individual", "time_cap": "", "movimentos": movs}
        config["workouts"].append(wkt); wkt_map[num] = wkt
    config["workouts"].sort(key=lambda w: w.get("numero", 0))
    return config


# ── PDF import ──────────────────────────────────────────────────────────────────
def parse_pdf(data):
    if not HAS_PDF:
        raise RuntimeError("pdfplumber não disponível — instale com: pip install pdfplumber")
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    # Tenta dividir por seções de workout
    # Padrão: "Workout N" ou linha com nome entre aspas seguida de tipo
    sections = re.split(r'\n(?=(?:Workout|WKT)\s+\d+)', full_text, flags=re.I)

    config = {"evento": {"nome": "", "categoria": "", "data": ""}, "workouts": []}

    # Extrai nome do evento das primeiras linhas
    header_lines = [l.strip() for l in full_text.split('\n')[:8] if l.strip()]
    for line in header_lines:
        if len(line) > 4 and not re.match(r'^(workout|wkt|\d)', line, re.I):
            config["evento"]["nome"] = line
            break

    wkt_num = 0
    for sec in sections:
        sec = sec.strip()
        if not sec: continue
        # Detecta seção de workout
        has_wkt_hdr = re.match(r'^(?:Workout|WKT)\s+(\d+)', sec, re.I)
        has_quoted  = re.search(r'["“].+["”]', sec)
        has_movs    = re.search(r'^\d{1,3}\s+\w', sec, re.M)
        if not (has_wkt_hdr or (has_quoted and has_movs)): continue
        wkt_num += 1
        wkt = parse_workout_text(sec, wkt_num)
        config["workouts"].append(wkt)

    # Se não achou seções estruturadas, tenta parse linha a linha
    if not config["workouts"]:
        lines = [l.strip() for l in full_text.split('\n') if l.strip()]
        current = None
        for line in lines:
            tc = re.search(r'time\s*cap[:\s]+(\d+)\s*min', line, re.I)
            p = _parse_mov_line(line)
            m_name = re.match(r'^["“](.+?)["”]', line)
            if m_name and current is None:
                wkt_num += 1
                current = {"numero": wkt_num, "nome": m_name.group(1).upper(),
                           "tipo": "for_time", "modalidade": "individual",
                           "time_cap": "", "movimentos": [], "descricao": []}
                config["workouts"].append(current)
            elif current:
                if tc: current["time_cap"] = f"{tc.group(1)} min"
                elif p:
                    reps, nome = p
                    mov = {"nome": nome}
                    if reps is not None: mov["reps"] = reps
                    current["movimentos"].append(mov)
                elif re.match(r'^then[\.\s]*$', line, re.I):
                    current["movimentos"].append({"separador": "then..."})
        for wkt in config["workouts"]:
            if wkt.get("tipo") == "for_time" and wkt.get("movimentos"):
                wkt["movimentos"].append({"chegada": True})

    for wkt in config["workouts"]:
        if wkt.get("tipo") == "for_time" and wkt.get("movimentos"):
            if not any(m.get("chegada") for m in wkt["movimentos"]):
                wkt["movimentos"].append({"chegada": True})
    return config


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
