#!/usr/bin/env python3
"""
sumula_app.py — Súmulas Digital Score  v1.0.0
Servidor web local. Sem dependências além de Jinja2 + fontes Lato.
Uso: python3 sumula_app.py   →  abre http://localhost:8765
"""

import json, os, io, zipfile, threading, webbrowser, sys, base64, re
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from campo_generator import render_workout, load_fonts, img_b64, sanitize

PORT = int(os.environ.get('PORT', 8765))
# Render sempre define PORT via env — usa isso para detectar ambiente cloud
HOST = '0.0.0.0' if 'PORT' in os.environ else 'localhost'
IS_CLOUD = HOST == '0.0.0.0'

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

# ── PDF automático (WeasyPrint) — desativado (incompatibilidade de CSS com flexbox)
HAS_PDF_GEN = False
WP_HTML     = None

# ── Carregar fontes na inicialização ────────────────────────────────────────────
print("╔══════════════════════════════════════════════╗")
print("║  Súmulas Digital Score  —  v1.1.0            ║")
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
FONTS_PDF = {}
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
        client = anthropic.Anthropic(api_key=AI_KEY)
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
        n = int(re.search(r'\d+', resp.content[0].text).group())
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
HTML_INTERFACE = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Súmulas Digital Score — v1.1.0</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0D0D0D;--surface:#111;--surface2:#161616;--surface3:#1C1C1C;
  --border:#1E1E1E;--border2:#252525;--border3:#2E2E2E;
  --text:#D8D8D8;--text2:#888;--text3:#555;--text4:#333;
  --accent:#FFF;--green:#5A9;--red:#A55;--blue:#68A;
  --radius:3px;
}
body{background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,'Segoe UI',sans-serif;
  font-size:13px;height:100vh;display:flex;flex-direction:column;overflow:hidden}

/* ── Header ── */
.hdr{background:#0A0A0A;height:46px;display:flex;align-items:center;padding:0 18px;
  border-bottom:1px solid var(--border);flex-shrink:0;gap:12px}
.hdr-logo{font-size:11px;font-weight:900;letter-spacing:.25em;color:#FFF;text-transform:uppercase}
.hdr-divider{width:1px;height:16px;background:var(--border3)}
.hdr-title{font-size:11px;font-weight:400;color:var(--text3);letter-spacing:.08em}
.hdr-right{margin-left:auto;display:flex;align-items:center;gap:10px}
.hdr-version{font-size:9px;font-weight:700;color:var(--accent);letter-spacing:.1em;
  background:rgba(229,93,0,.12);border:1px solid rgba(229,93,0,.25);
  padding:2px 7px;border-radius:10px;text-transform:uppercase}
.hdr-brand{font-size:10px;color:var(--text4);letter-spacing:.05em}

/* ── Layout ── */
.layout{flex:1;display:flex;overflow:hidden}

/* ── Sidebar ── */
.sidebar{width:280px;flex-shrink:0;background:var(--surface);border-right:1px solid var(--border);
  display:flex;flex-direction:column;overflow:hidden}
.sidebar-scroll{flex:1;overflow-y:auto;padding-bottom:4px}
.sidebar-scroll::-webkit-scrollbar{width:3px}
.sidebar-scroll::-webkit-scrollbar-thumb{background:#222;border-radius:2px}
.sidebar-footer{padding:12px;border-top:1px solid var(--border);flex-shrink:0}

/* ── Sections ── */
.sec{border-bottom:1px solid var(--border)}
.sec-hdr{display:flex;align-items:center;padding:10px 14px 8px;gap:8px}
.sec-title{font-size:9px;font-weight:700;letter-spacing:.22em;text-transform:uppercase;color:var(--text3);flex:1}
.sec-action{background:none;border:1px solid var(--border3);color:var(--text3);cursor:pointer;
  font-size:9px;font-weight:700;letter-spacing:.1em;padding:3px 7px;border-radius:var(--radius);
  transition:border-color .15s,color .15s}
.sec-action:hover{border-color:#444;color:var(--text2)}
.sec-body{padding:0 14px 12px}

/* ── Event display ── */
.ev-display{padding:8px 10px;background:var(--surface2);border-radius:var(--radius);cursor:pointer;
  transition:background .15s}
.ev-display:hover{background:var(--surface3)}
.ev-nome{font-size:12px;font-weight:700;color:var(--text);letter-spacing:.04em;text-transform:uppercase}
.ev-meta{font-size:9px;color:var(--text3);letter-spacing:.1em;text-transform:uppercase;margin-top:2px}
.ev-empty{font-size:11px;color:var(--text3);font-style:italic}

/* ── Forms ── */
.field{display:flex;flex-direction:column;gap:4px;margin-bottom:10px}
.field:last-child{margin-bottom:0}
.field label{font-size:9px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:var(--text3)}
.field input,.field select,.field textarea{
  background:var(--surface2);border:1px solid var(--border3);color:var(--text);
  padding:7px 9px;border-radius:var(--radius);font-size:12px;font-family:inherit;
  transition:border-color .15s,background .15s;outline:none;width:100%}
.field input:focus,.field select:focus,.field textarea:focus{
  border-color:#3A3A3A;background:var(--surface3)}
.field select{cursor:pointer}
.field textarea{resize:vertical;min-height:72px;line-height:1.5}
.field input::placeholder,.field textarea::placeholder{color:var(--text4)}
.field-row{display:flex;gap:8px}
.field-row .field{flex:1}
.field-row .field.w80{flex:0 0 80px}
.field-row .field.w100{flex:0 0 100px}
.logo-upload-wrap{
  border:1.5px dashed var(--border);border-radius:6px;
  padding:8px 10px;cursor:pointer;min-height:44px;
  display:flex;align-items:center;justify-content:center;gap:8px;
  transition:border-color .2s,background .2s;
}
.logo-upload-wrap:hover{border-color:var(--accent);background:rgba(229,93,0,.06)}
.logo-upload-wrap span{font-size:10px;color:var(--text3);pointer-events:none}

/* ── Workout list ── */
.wkt-empty{padding:14px;font-size:11px;color:var(--text4);text-align:center;font-style:italic}
.wkt-card{display:flex;align-items:center;padding:9px 14px;gap:10px;cursor:pointer;
  border-bottom:1px solid var(--border);transition:background .1s}
.wkt-card:hover{background:var(--surface2)}
.wkt-card.active{background:var(--surface2);border-left:3px solid var(--text2)}
.wkt-num{font-size:17px;font-weight:900;color:var(--border3);width:22px;
  flex-shrink:0;text-align:center;line-height:1}
.wkt-card.active .wkt-num{color:var(--text2)}
.wkt-info{flex:1;min-width:0}
.wkt-name{font-size:11.5px;font-weight:700;color:var(--text2);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1}
.wkt-card.active .wkt-name{color:var(--text)}
.wkt-tags{display:flex;gap:5px;margin-top:3px;align-items:center}
.tag{font-size:8px;font-weight:700;letter-spacing:.1em;padding:1px 5px;
  border-radius:2px;text-transform:uppercase;background:var(--surface3);color:var(--text3)}
.tag.for_time{color:#7AB}
.tag.amrap{color:#9A7}
.tag.express{color:#BA7}
.wkt-actions{display:flex;gap:4px;flex-shrink:0}
.icon-btn{background:none;border:none;color:var(--text4);cursor:pointer;padding:3px 5px;
  font-size:11px;border-radius:var(--radius);transition:color .12s,background .12s}
.icon-btn:hover{color:var(--text2);background:var(--surface3)}
.icon-btn.danger:hover{color:var(--red)}

/* ── Import buttons ── */
.import-btns{display:flex;gap:8px}
.btn-import{flex:1;padding:8px 6px;background:var(--surface2);border:1px solid var(--border3);
  color:var(--text2);cursor:pointer;font-size:10px;font-weight:700;letter-spacing:.1em;
  border-radius:var(--radius);transition:background .15s,color .15s,border-color .15s;text-align:center}
.btn-import:hover{background:var(--surface3);border-color:#3A3A3A;color:var(--text)}
.import-hint{font-size:9.5px;color:var(--text4);margin-top:7px;line-height:1.5;text-align:center}

/* ── Generate button ── */
.btn-generate{width:100%;padding:11px;background:#FFF;color:#000;font-size:10px;
  font-weight:700;letter-spacing:.18em;text-transform:uppercase;border:none;cursor:pointer;
  border-radius:var(--radius);transition:background .15s;display:flex;align-items:center;
  justify-content:center;gap:8px}
.btn-generate:hover{background:#E8E8E8}
.btn-generate:disabled{background:var(--surface3);color:var(--text4);cursor:default}
.spinner{display:none;width:11px;height:11px;border:2px solid #333;
  border-top-color:#000;border-radius:50%;animation:spin .7s linear infinite}
.generating .spinner{display:block}
@keyframes spin{to{transform:rotate(360deg)}}

/* ── Editor panel ── */
.editor{width:400px;flex-shrink:0;display:none;flex-direction:column;
  background:var(--surface);border-right:1px solid var(--border);overflow:hidden}
.editor.open{display:flex}
.ed-hdr{display:flex;align-items:center;padding:12px 16px;border-bottom:1px solid var(--border);
  gap:10px;flex-shrink:0}
.ed-hdr-title{font-size:10px;font-weight:700;letter-spacing:.18em;text-transform:uppercase;
  color:var(--text2);flex:1}
.ed-close{background:none;border:none;color:var(--text3);cursor:pointer;font-size:16px;
  line-height:1;padding:2px 4px;border-radius:var(--radius);transition:color .12s}
.ed-close:hover{color:var(--text)}
.ed-body{flex:1;overflow-y:auto;padding:16px}
.ed-body::-webkit-scrollbar{width:3px}
.ed-body::-webkit-scrollbar-thumb{background:#222;border-radius:2px}
.ed-footer{padding:12px 16px;border-top:1px solid var(--border);
  display:flex;gap:8px;flex-shrink:0}

/* ── Movements editor ── */
.mov-section-hdr{font-size:9px;font-weight:700;letter-spacing:.18em;text-transform:uppercase;
  color:var(--text3);margin-bottom:8px}
.mov-table{border:1px solid var(--border3);border-radius:var(--radius);overflow:hidden;margin-bottom:8px}
.mov-table-hdr{display:flex;background:var(--surface3);padding:4px 8px;gap:6px}
.mov-table-hdr span{font-size:8px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--text4)}
.mth-nome{flex:1}
.mth-reps{width:52px;text-align:center}
.mth-label{width:72px}
.mth-ctrl{width:52px;text-align:center}
.mov-row{display:flex;align-items:center;gap:6px;padding:5px 8px;
  border-top:1px solid var(--border);background:var(--surface)}
.mov-row:first-child{border-top:none}
.mov-row.sep-row{background:var(--surface2)}
.mov-row.chegada-row{background:#0A1A0A;border-top:2px solid #1A3A1A}
.mov-row input{background:var(--surface3);border:1px solid var(--border3);color:var(--text);
  padding:4px 6px;border-radius:var(--radius);font-size:11.5px;font-family:inherit;outline:none;
  transition:border-color .12s;width:100%}
.mov-row input:focus{border-color:#3A3A3A}
.mov-row .mi-nome{flex:1}
.mov-row .mi-reps{width:52px;text-align:center}
.mov-row .mi-label{width:72px;font-size:10.5px}
.mov-row .mi-sep{flex:1;color:var(--text3);font-style:italic;font-size:11px}
.mov-row .mi-chegada{flex:1;font-size:10px;font-weight:700;letter-spacing:.12em;
  text-transform:uppercase;color:#3A7;padding:2px 0}
.mov-row .mi-ctrl{width:52px;display:flex;justify-content:center;gap:2px}
.empty-table{padding:12px;text-align:center;font-size:11px;color:var(--text4);font-style:italic}
.mov-actions{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:16px}
.btn-mov{padding:5px 10px;background:var(--surface3);border:1px solid var(--border3);
  color:var(--text2);cursor:pointer;font-size:10px;font-weight:700;letter-spacing:.08em;
  border-radius:var(--radius);transition:background .12s,color .12s}
.btn-mov:hover{background:#1E2A1E;border-color:#2A402A;color:#8C8}

/* ── Express sections ── */
.express-section{border:1px solid var(--border3);border-radius:var(--radius);
  margin-bottom:14px;overflow:hidden}
.express-hdr{background:var(--surface3);padding:8px 12px;display:flex;align-items:center;gap:10px}
.express-hdr-title{font-size:9px;font-weight:700;letter-spacing:.18em;text-transform:uppercase;
  color:var(--text2);flex:1}
.express-body{padding:12px}

/* ── Divider ── */
.divider{border:none;border-top:1px solid var(--border);margin:14px 0}

/* ── Preview panel ── */
.preview{flex:1;display:flex;flex-direction:column;background:#333;overflow:hidden}
.preview-bar{background:#0A0A0A;height:38px;display:flex;align-items:center;
  padding:0 16px;border-bottom:1px solid var(--border);flex-shrink:0;gap:10px}
.pb-label{font-size:8.5px;font-weight:700;letter-spacing:.2em;text-transform:uppercase;color:var(--text4)}
.pb-name{font-size:11px;font-weight:700;color:var(--text2);flex:1;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pb-hint{font-size:9px;color:var(--text4);letter-spacing:.04em;flex-shrink:0}
.preview-empty{flex:1;display:flex;flex-direction:column;align-items:center;
  justify-content:center;gap:12px;background:var(--bg)}
.pe-icon{font-size:28px;color:var(--border3)}
.pe-text{font-size:10px;letter-spacing:.2em;text-transform:uppercase;color:var(--text4)}
.pe-sub{font-size:10px;color:var(--text4);max-width:260px;text-align:center;line-height:1.6}
.preview-frame{flex:1;border:none;width:100%;display:none;background:#FFF}

/* ── Buttons ── */
.btn-primary{flex:1;padding:9px 14px;background:#FFF;color:#000;font-size:10px;
  font-weight:700;letter-spacing:.14em;text-transform:uppercase;border:none;cursor:pointer;
  border-radius:var(--radius);transition:background .15s}
.btn-primary:hover{background:#E8E8E8}
.btn-secondary{padding:9px 14px;background:none;color:var(--text3);font-size:10px;
  font-weight:700;letter-spacing:.14em;text-transform:uppercase;
  border:1px solid var(--border3);cursor:pointer;border-radius:var(--radius);transition:all .15s}
.btn-secondary:hover{border-color:#3A3A3A;color:var(--text2)}

/* ── Status ── */
.status-bar{padding:6px 14px;font-size:9.5px;min-height:28px;letter-spacing:.04em}
.status-bar.ok{color:var(--green)}
.status-bar.err{color:var(--red)}
.status-bar.info{color:var(--text2)}

/* ── Toast ── */
.toast{position:fixed;bottom:20px;right:20px;padding:10px 16px;border-radius:var(--radius);
  font-size:11px;font-weight:700;letter-spacing:.08em;opacity:0;
  transition:opacity .25s;pointer-events:none;z-index:999}
.toast.show{opacity:1}
.toast.ok{background:#1A3A1A;color:#6C6;border:1px solid #2A4A2A}
.toast.err{background:#3A1A1A;color:#C66;border:1px solid #4A2A2A}

/* ── Modal de categoria ── */
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.75);display:flex;
  align-items:center;justify-content:center;z-index:100}
.modal{background:#141414;border:1px solid var(--border3);border-radius:4px;
  padding:24px;width:440px;max-width:90vw;max-height:80vh;overflow-y:auto}
.modal-title{font-size:11px;font-weight:700;letter-spacing:.2em;text-transform:uppercase;
  color:var(--text2);margin-bottom:6px}
.modal-sub{font-size:11px;color:var(--text3);margin-bottom:18px;line-height:1.5}
.cat-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:16px}
.cat-btn{padding:9px 10px;background:var(--surface2);border:1px solid var(--border3);
  color:var(--text2);cursor:pointer;font-size:10.5px;font-weight:600;text-align:left;
  border-radius:var(--radius);transition:all .12s;line-height:1.3}
.cat-btn:hover{background:var(--surface3);border-color:#3A3A3A;color:var(--text)}
.modal-cancel{background:none;border:none;color:var(--text4);cursor:pointer;
  font-size:10px;letter-spacing:.1em;text-transform:uppercase;padding:4px}
</style>
</head>
<body>

<!-- ══ Header ═══════════════════════════════════════════════════════════════ -->
<header class="hdr">
  <span class="hdr-logo">Súmulas</span>
  <div class="hdr-divider"></div>
  <span class="hdr-title">Digital Score</span>
  <div class="hdr-right">
    <span class="hdr-version">v1.1.0</span>
    <span id="aiBadge" style="display:none;font-size:9px;font-weight:700;color:#5A9;letter-spacing:.1em;
      background:rgba(90,153,90,.12);border:1px solid rgba(90,153,90,.3);
      padding:2px 7px;border-radius:10px;text-transform:uppercase">IA</span>
    <span id="pdfBadge" style="display:none;font-size:9px;font-weight:700;color:#68A;letter-spacing:.1em;
      background:rgba(102,136,170,.12);border:1px solid rgba(102,136,170,.3);
      padding:2px 7px;border-radius:10px;text-transform:uppercase">PDF</span>
    <span class="hdr-brand">© Digital Score</span>
  </div>
</header>

<!-- ══ Main layout ══════════════════════════════════════════════════════════ -->
<div class="layout">

  <!-- ── Sidebar ──────────────────────────────────────────────────────────── -->
  <aside class="sidebar">
    <div class="sidebar-scroll">

      <!-- Evento -->
      <div class="sec">
        <div class="sec-hdr">
          <span class="sec-title">Evento</span>
          <button class="sec-action" id="btnToggleEvento" onclick="toggleEventoForm()">Editar</button>
        </div>
        <div class="sec-body">
          <div id="eventoDisplay" class="ev-display" onclick="toggleEventoForm()">
            <div class="ev-empty">Clique para configurar o evento</div>
          </div>
          <div id="eventoForm" style="display:none;padding-top:10px">
            <div class="field">
              <label>Nome do Evento</label>
              <input id="evNome" type="text" placeholder="Ex: SUN 2026" oninput="onEventoChange()">
            </div>
            <div class="field-row">
              <div class="field">
                <label>Categoria</label>
                <input id="evCat" type="text" placeholder="Ex: RX MASCULINO" oninput="onEventoChange()">
              </div>
              <div class="field w80">
                <label>Data</label>
                <input id="evData" type="text" placeholder="2026" oninput="onEventoChange()">
              </div>
            </div>
            <div class="field-row" style="margin-top:6px">
              <div class="field">
                <label>Logo do Evento <span style="font-size:9px;opacity:.6">(JPG/PNG — aparece no header)</span></label>
                <div class="logo-upload-wrap" id="logoEventoWrap" onclick="document.getElementById('inputLogoEvento').click()">
                  <img id="logoEventoPreview" style="display:none;height:28px;object-fit:contain">
                  <span id="logoEventoPlaceholder">Clique para selecionar</span>
                </div>
                <input id="inputLogoEvento" type="file" accept="image/*" style="display:none" onchange="onLogoEvento(this)">
              </div>
              <div class="field">
                <label>Logo Digital Score <span style="font-size:9px;opacity:.6">(aparece no header)</span></label>
                <div class="logo-upload-wrap" id="logoEmpresaWrap" onclick="document.getElementById('inputLogoEmpresa').click()">
                  <img id="logoEmpresaPreview" style="display:none;height:28px;object-fit:contain">
                  <span id="logoEmpresaPlaceholder">Clique para selecionar</span>
                </div>
                <input id="inputLogoEmpresa" type="file" accept="image/*" style="display:none" onchange="onLogoEmpresa(this)">
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Workouts -->
      <div class="sec">
        <div class="sec-hdr">
          <span class="sec-title">Workouts</span>
          <button class="sec-action" onclick="novoWorkout()">+ Novo</button>
        </div>
        <div id="workoutList">
          <div class="wkt-empty">Nenhum workout ainda.<br>Clique em "+ Novo" para começar.</div>
        </div>
        <div class="status-bar" id="wktStatus"></div>
      </div>

      <!-- Importar -->
      <div class="sec">
        <div class="sec-hdr">
          <span class="sec-title">Importar</span>
        </div>
        <div class="sec-body">
          <div class="import-btns">
            <button class="btn-import" onclick="triggerImport('excel')">📊 Importar Excel (.xlsx)</button>
          </div>
          <div class="import-hint">Importe todas as categorias e workouts<br>a partir do seu arquivo Excel</div>
        </div>
      </div>

    </div>

    <!-- Generate -->
    <div class="sidebar-footer">
      <button class="btn-generate" id="btnGerar" onclick="gerarZIP()" disabled>
        <div class="spinner"></div>
        <span id="btnGerarLabel">⬇&nbsp;&nbsp;Gerar Súmulas (ZIP)</span>
      </button>
    </div>
  </aside>

  <!-- ── Editor panel (slides in) ─────────────────────────────────────────── -->
  <div class="editor" id="editor">
    <div class="ed-hdr">
      <span class="ed-hdr-title" id="edTitle">Novo Workout</span>
      <button class="ed-close" onclick="fecharEditor()" title="Fechar">×</button>
    </div>
    <div class="ed-body">

      <!-- Campos básicos -->
      <div class="field">
        <label>Nome do Workout</label>
        <input id="edNome" type="text" placeholder="Ex: TWENTIES">
      </div>
      <div class="field-row">
        <div class="field">
          <label>Tipo</label>
          <select id="edTipo" onchange="onTipoChange()">
            <option value="for_time">For Time</option>
            <option value="amrap">AMRAP</option>
            <option value="express">Express (2 fases)</option>
          </select>
        </div>
        <div class="field w100">
          <label>Time Cap</label>
          <input id="edTimeCap" type="text" placeholder="Ex: 10 min">
        </div>
      </div>

      <hr class="divider">

      <!-- Movimentos (for_time / amrap) -->
      <div id="secMovimentos">
        <div class="mov-section-hdr">Movimentos</div>
        <div class="mov-table" id="movTable">
          <div class="mov-table-hdr">
            <span class="mth-nome">Movimento</span>
            <span class="mth-reps">Reps</span>
            <span class="mth-label">Label</span>
            <span class="mth-ctrl">Ações</span>
          </div>
          <div id="movTableBody">
            <div class="empty-table">Adicione movimentos abaixo</div>
          </div>
        </div>
        <div class="mov-actions">
          <button class="btn-mov" onclick="addMov('main')">+ Movimento</button>
          <button class="btn-mov" onclick="addSep('main')">⁝ Separador</button>
          <button class="btn-mov" onclick="addChegada('main')" id="btnChegadaMain">✓ Chegada</button>
        </div>
      </div>

      <!-- Express (2 fórmulas) -->
      <div id="secExpress" style="display:none">
        <!-- Fórmula 1 -->
        <div class="express-section">
          <div class="express-hdr">
            <span class="express-hdr-title">Fórmula 1</span>
          </div>
          <div class="express-body">
            <div class="field">
              <label>Janela de Tempo</label>
              <input id="edF1Janela" type="text" placeholder="Ex: 00:00 → 05:00  ·  AMRAP 5 MIN">
            </div>
            <div class="mov-table" id="movTableF1">
              <div class="mov-table-hdr">
                <span class="mth-nome">Movimento</span>
                <span class="mth-reps">Reps</span>
                <span class="mth-label">Label</span>
                <span class="mth-ctrl">Ações</span>
              </div>
              <div id="movTableF1Body">
                <div class="empty-table">Adicione movimentos abaixo</div>
              </div>
            </div>
            <div class="mov-actions">
              <button class="btn-mov" onclick="addMov('f1')">+ Movimento</button>
              <button class="btn-mov" onclick="addSep('f1')">⁝ Separador</button>
            </div>
          </div>
        </div>
        <!-- Fórmula 2 -->
        <div class="express-section">
          <div class="express-hdr">
            <span class="express-hdr-title">Fórmula 2</span>
          </div>
          <div class="express-body">
            <div class="field">
              <label>Janela de Tempo</label>
              <input id="edF2Janela" type="text" placeholder="Ex: 06:00 → 12:00  ·  FOR TIME">
            </div>
            <div class="mov-table" id="movTableF2">
              <div class="mov-table-hdr">
                <span class="mth-nome">Movimento</span>
                <span class="mth-reps">Reps</span>
                <span class="mth-label">Label</span>
                <span class="mth-ctrl">Ações</span>
              </div>
              <div id="movTableF2Body">
                <div class="empty-table">Adicione movimentos abaixo</div>
              </div>
            </div>
            <div class="mov-actions">
              <button class="btn-mov" onclick="addMov('f2')">+ Movimento</button>
              <button class="btn-mov" onclick="addSep('f2')">⁝ Separador</button>
              <button class="btn-mov" onclick="addChegada('f2')">✓ Chegada</button>
            </div>
          </div>
        </div>
      </div>

      <hr class="divider">

      <!-- Descrição -->
      <div class="field">
        <label>Descrição (texto da súmula — uma linha por item)</label>
        <textarea id="edDescricao" placeholder="For time:&#10;20 Chest-to-Bar Pull-Ups&#10;20 Devil's Presses (22,5kg)&#10;Time cap: 10 minutos"></textarea>
      </div>

    </div>
    <div class="ed-footer">
      <button class="btn-primary" onclick="salvarWorkout()">Salvar e Visualizar</button>
      <button class="btn-secondary" onclick="fecharEditor()">Cancelar</button>
    </div>
  </div>

  <!-- ── Preview panel ─────────────────────────────────────────────────────── -->
  <div class="preview" id="preview">
    <div class="preview-bar">
      <span class="pb-label">Visualização</span>
      <span class="pb-name" id="pbName">—</span>
      <span class="pb-hint">Ctrl+P para imprimir / salvar como PDF</span>
    </div>
    <div class="preview-empty" id="previewEmpty">
      <div class="pe-icon">◻</div>
      <div class="pe-text">Nenhum workout selecionado</div>
      <div class="pe-sub">Crie ou selecione um workout para ver a súmula aqui</div>
    </div>
    <iframe id="previewFrame" class="preview-frame"></iframe>
  </div>

</div><!-- /layout -->

<!-- Hidden file inputs -->
<input type="file" id="fileExcel" accept=".xlsx,.xls" style="display:none" onchange="handleImport(this,'excel')">

<!-- Modal: seletor de categoria -->
<div id="catModal" style="display:none">
  <div class="modal-overlay">
    <div class="modal">
      <div class="modal-title">Selecionar Categoria</div>
      <div class="modal-sub" id="catModalSub">Escolha a categoria para gerar as súmulas:</div>
      <div class="cat-grid" id="catGrid"></div>
      <button class="modal-cancel" onclick="document.getElementById('catModal').style.display='none'">Cancelar</button>
    </div>
  </div>
</div>

<!-- Toast -->
<div class="toast" id="toast"></div>

<script>
// ═══════════════════════════════════════════════════════════════════
//  INIT
// ═══════════════════════════════════════════════════════════════════
(function initApp() {
  fetch('/api/status').then(r=>r.json()).then(s => {
    if (s.ai_ativo)  document.getElementById('aiBadge').style.display  = '';
    if (s.pdf_ativo) document.getElementById('pdfBadge').style.display = '';
    window.PDF_ATIVO = !!s.pdf_ativo;
    atualizarBotaoGerar();
  }).catch(()=>{ window.PDF_ATIVO = false; });
})();

// ═══════════════════════════════════════════════════════════════════
//  STATE
// ═══════════════════════════════════════════════════════════════════
let config = {
  evento: { nome: "", categoria: "", data: "", logo_empresa: DS_LOGO_PADRAO, logo_evento: "" },
  workouts: [],
  atletas: []   // atletas da categoria atual (pode estar vazio)
};
let editingIdx = -1;   // -1 = new workout
let previewIdx  = -1;

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
  }
}

function onEventoChange() {
  config.evento.nome      = document.getElementById('evNome').value.trim();
  config.evento.categoria = document.getElementById('evCat').value.trim();
  config.evento.data      = document.getElementById('evData').value.trim();
  renderEventoDisplay();
  atualizarBotaoGerar();
  refreshPreview();
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
  const nWkt = config.workouts.length;
  const nAtl = config.atletas.length;
  const fmt  = window.PDF_ATIVO ? 'PDF' : 'HTML';
  btn.disabled = nWkt === 0;
  if (nWkt === 0) {
    lbl.innerHTML = `&#x2B07;&nbsp;&nbsp;Gerar Súmulas ${fmt} (ZIP)`;
  } else {
    const cat = config.evento.categoria || config.evento.nome || '';
    const catLabel = cat ? esc(cat) + ' — ' : '';
    if (nAtl > 0) {
      const total = nWkt * nAtl;
      lbl.innerHTML = `&#x2B07;&nbsp;&nbsp;Gerar ${catLabel}${total} súmulas ${fmt} (${nAtl} × ${nWkt} WKTs)`;
    } else {
      lbl.innerHTML = `&#x2B07;&nbsp;&nbsp;Gerar ${catLabel}${nWkt} súmula${nWkt !== 1 ? 's' : ''} ${fmt}`;
    }
  }
}

// ═══════════════════════════════════════════════════════════════════
//  EDITOR
// ═══════════════════════════════════════════════════════════════════
function novoWorkout() {
  editingIdx = -1;
  const n = config.workouts.length + 1;
  document.getElementById('edTitle').textContent = 'Novo Workout';
  document.getElementById('edNome').value = '';
  document.getElementById('edTipo').value = 'for_time';
  document.getElementById('edTimeCap').value = '';
  document.getElementById('edDescricao').value = '';
  document.getElementById('edF1Janela').value = '';
  document.getElementById('edF2Janela').value = '';
  setMovTableFromArray('main', []);
  setMovTableFromArray('f1', []);
  setMovTableFromArray('f2', []);
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
    document.getElementById('edF1Janela').value = (w.formula1 || {}).janela || '';
    document.getElementById('edF2Janela').value = (w.formula2 || {}).janela || '';
    setMovTableFromArray('f1', (w.formula1 || {}).movimentos || []);
    setMovTableFromArray('f2', (w.formula2 || {}).movimentos || []);
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
    wkt.formula1 = {
      janela: document.getElementById('edF1Janela').value.trim(),
      descricao: [],
      movimentos: getMovTableArray('f1')
    };
    wkt.formula2 = {
      janela: document.getElementById('edF2Janela').value.trim(),
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
  previewWorkout(previewIdx);
  toast('Workout salvo!', 'ok');
}

function deletarWorkout(idx) {
  if (!confirm(`Excluir workout "${config.workouts[idx].nome}"?`)) return;
  config.workouts.splice(idx, 1);
  computeWorkoutNumbers(); // Renumber with Express slot logic
  if (previewIdx >= config.workouts.length) previewIdx = config.workouts.length - 1;
  renderWorkoutList();
  atualizarBotaoGerar();
  if (previewIdx >= 0) previewWorkout(previewIdx);
  else {
    document.getElementById('previewEmpty').style.display = '';
    document.getElementById('previewFrame').style.display = 'none';
    document.getElementById('pbName').textContent = '—';
  }
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
      <input class="mi-reps" type="number" min="1" value="${mov.reps || ''}" placeholder="—" style="width:52px;text-align:center">
      <input class="mi-label" value="${esc(mov.label || '')}" placeholder="Label" style="width:72px;font-size:10.5px">
      <div class="mi-ctrl">${ctrlBtns(section)}</div>`;
  }

  body.appendChild(row);
}

function ctrlBtns(section) {
  return `<button class="icon-btn" onclick="movUp(this)" title="Subir">↑</button>
    <button class="icon-btn danger" onclick="removeRow(this)" title="Remover">×</button>`;
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
  btn.disabled = true;
  btn.classList.add('generating');
  lbl.textContent = 'Gerando…';

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

  const sub = document.getElementById('catModalSub');
  sub.textContent = `${cats.length} categorias encontradas. Escolha qual gerar as súmulas:`;

  const grid = document.getElementById('catGrid');
  grid.innerHTML = '';
  cats.forEach(cat => {
    const btn = document.createElement('button');
    btn.className = 'cat-btn';
    const wkts = (data.por_categoria[cat] || []).length;
    btn.innerHTML = `<strong>${esc(cat)}</strong><br><span style="font-size:9px;opacity:.6">${wkts} workout(s)</span>`;
    btn.onclick = () => {
      document.getElementById('catModal').style.display = 'none';
      const workouts = data.por_categoria[cat] || [];
      const atletasCat = (data.atletas_por_categoria || {})[cat] || [];
      config.evento.nome      = data.evento_nome || config.evento.nome || 'Sun2026';
      config.evento.categoria = cat;
      document.getElementById('evNome').value = config.evento.nome;
      document.getElementById('evCat').value  = cat;
      renderEventoDisplay();
      config.workouts = workouts;
      config.atletas  = atletasCat;
      previewIdx = 0;
      renderWorkoutList();
      atualizarBotaoGerar();
      if (workouts.length) previewWorkout(0);
      const msgAtletas = atletasCat.length ? ` · ${atletasCat.length} atleta(s)` : '';
      toast(`${cat} — ${workouts.length} workout(s)${msgAtletas} importado(s)`, 'ok');
    };
    grid.appendChild(btn);
  });
  document.getElementById('catModal').style.display = '';
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
    previewWorkout(0);
    toast(`${result.workouts.length} workout(s) importado(s)`, 'ok');
  } else {
    toast('Nenhum workout encontrado no arquivo', 'err');
  }
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
</script>
</body>
</html>"""


# ── HTTP Handler ────────────────────────────────────────────────────────────────
class SumulaHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass  # silencia log

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            html = HTML_INTERFACE.replace('DS_LOGO_PADRAO', f'"{DS_LOGO_PADRAO}"')
            self._send(200, 'text/html; charset=utf-8', html.encode('utf-8'))
        elif self.path == '/api/status':
            payload = json.dumps({
                "ai_ativo":    AI_ATIVO,
                "ai_provider": "Anthropic Claude Haiku" if AI_ATIVO else None,
                "pdf_ativo":   HAS_PDF_GEN,
                "versao":      "1.1.0"
            })
            self._send(200, 'application/json; charset=utf-8', payload.encode())
        else:
            self._send(404, 'text/plain', b'Not found')

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            body   = json.loads(self.rfile.read(length))
            routes = {
                '/api/preview':        self._handle_preview,
                '/api/generate':       self._handle_generate,
                '/api/import/excel':   self._handle_import_excel,
                '/api/import/pdf':     self._handle_import_pdf,
            }
            handler = routes.get(self.path)
            if handler: handler(body)
            else: self._send(404, 'text/plain', b'Rota nao encontrada')
        except Exception as e:
            import traceback; traceback.print_exc()
            self._send(500, 'application/json',
                       json.dumps({"error": str(e)}).encode('utf-8'))

    def _handle_preview(self, body):
        cfg      = body['config']
        idx      = int(body['workout_index'])
        ev       = cfg.get('evento', {})
        workouts = cfg['workouts']
        assign_workout_numbers(workouts)   # recalcula com slots Express
        enriquecer_workouts(workouts)      # calcula n_rounds por IA/algoritmo
        wkt      = workouts[idx]
        logo     = _resolve_logo(ev.get('logo_empresa', ''))
        logo_evt = ev.get('logo_evento', '')   # data-URL vinda do front
        html = render_workout(ev, wkt, FONTS, logo, logo_evt)
        self._send(200, 'text/html; charset=utf-8', html.encode('utf-8'))

    def _handle_generate(self, body):
        cfg      = body['config']
        ev       = cfg.get('evento', {})
        logo     = _resolve_logo(ev.get('logo_empresa', ''))
        logo_evt = ev.get('logo_evento', '')
        atletas  = cfg.get('atletas', [])
        workouts = cfg['workouts']
        assign_workout_numbers(workouts)
        enriquecer_workouts(workouts)

        # Escolhe fontes: file:// para PDF (rápido), data: para HTML
        use_pdf  = HAS_PDF_GEN and bool(FONTS_PDF)
        fonts    = FONTS_PDF if use_pdf else FONTS
        ext      = '.pdf'  if use_pdf else '.html'

        def _render(wkt, atleta=None):
            return render_workout(ev, wkt, fonts, logo, logo_evt, atleta)

        def _to_bytes(html):
            if use_pdf:
                try:
                    return WP_HTML(string=html).write_pdf()
                except Exception as e:
                    print(f"  ⚠  PDF falhou ({e})")
                    # Fallback: gera HTML com fontes data: para não perder o arquivo
                    return render_workout(ev, wkt, FONTS, logo, logo_evt,
                                         atleta if 'atleta' in dir() else None
                                         ).encode('utf-8')
            return html.encode('utf-8')

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            if atletas:
                for wkt in workouts:
                    num_w  = wkt.get('numero', 1)
                    nome_w = wkt.get('nome', 'wkt')
                    pasta  = f"WKT{num_w:02d}_{sanitize(nome_w)}"
                    for atleta in atletas:
                        nome_a  = atleta.get('nome', 'atleta')
                        num_a   = atleta.get('numero', '')
                        prefixo = f"{sanitize(num_a)}_" if num_a else ""
                        html    = render_workout(ev, wkt, fonts, logo, logo_evt, atleta)
                        zf.writestr(f"{pasta}/{prefixo}{sanitize(nome_a)}{ext}",
                                    _to_bytes(html))
            else:
                for wkt in workouts:
                    num  = wkt.get('numero', 1)
                    nome = wkt.get('nome', 'wkt')
                    html = render_workout(ev, wkt, fonts, logo, logo_evt)
                    zf.writestr(f"{num:02d}_{sanitize(nome)}{ext}", _to_bytes(html))

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
        server = HTTPServer((HOST, PORT), SumulaHandler)
    except OSError:
        print(f"⚠  Porta {PORT} em uso.")
        sys.exit(1)

    if IS_CLOUD:
        print(f"✓ Servidor em: http://0.0.0.0:{PORT}")
        print("  Sumulas Digital Score v1.0.0 online \u2014 pronto para receber conexoes\n")
    else:
        url = f'http://localhost:{PORT}'
        print(f"✓ Servidor em: {url}")
        print("  Pressione Ctrl+C para encerrar\n")
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n✓ Encerrado.")


if __name__ == '__main__':
    main()
