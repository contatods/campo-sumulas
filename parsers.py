"""parsers.py — extração de workouts a partir de texto livre, Excel e PDF.

Funções públicas:
    parse_workout_text(text, numero) -> Workout
    parse_excel(data: bytes) -> dict   # categoria_grid OU template
    parse_pdf(data: bytes) -> dict
    assign_workout_numbers(workouts) -> list[Workout]   # mutates in-place
    _atleta_sort_key(a) -> tuple        # bateria → raia (numérica) → nome

Nada aqui depende do servidor HTTP ou da geração de HTML.
"""
from __future__ import annotations

import io
import re
from typing import Any, Optional

from types_ds import Atleta, Movimento, Workout

# Excel e PDF são opcionais (parsers respectivos só ativam se a lib estiver instalada)
try:
    import openpyxl
    HAS_EXCEL = True
except ImportError:
    HAS_EXCEL = False

try:
    import pdfplumber
    HAS_PDF = True
except ImportError:
    HAS_PDF = False


BLOCK_LABELS = {1: "1º BLOCO", 2: "2º BLOCO", 3: "3º BLOCO", 4: "4º BLOCO", 5: "5º BLOCO"}


# ── Texto livre de workout ──────────────────────────────────────────────────────
def _parse_mov_line(line: str) -> Optional[tuple[int, str]]:
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
    if sep == '-':
        nome = f"{num_s}-{rest}".upper()
    else:
        nome = rest.upper()
    return (num, nome)


def parse_workout_text(text: str, numero: int) -> Workout:
    """Converte o texto livre de uma célula/seção num dict de workout."""
    lines = [l.strip() for l in str(text).split('\n') if l.strip()]
    wkt: Workout = {"numero": numero, "nome": f"WKT {numero}", "tipo": "for_time",
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
    movs: list[Movimento] = []
    block = 1
    has_seps = any(re.match(r'^then\.+$', l, re.I) for l in lines)
    skip_prefixes = ('for time', 'por tempo', 'amrap', 'as many reps', 'rest',
                     'atenção', 'atencao', 'obs', 'note', '"', '“')

    for line in lines:
        ll = line.lower()
        tc = re.search(r'time\s*cap[:\s]+(\d+)\s*min', line, re.I)
        if tc: wkt["time_cap"] = f"{tc.group(1)} min"; continue
        if re.match(r'^then[\.\s]*$', line, re.I):
            if movs: movs.append({"separador": "then..."})
            block += 1; continue
        if any(ll.startswith(p) for p in skip_prefixes): continue
        parsed = _parse_mov_line(line)
        if parsed:
            reps, nome = parsed
            mov: Movimento = {"nome": nome}
            if reps is not None: mov["reps"] = reps
            if has_seps and block in BLOCK_LABELS: mov["label"] = BLOCK_LABELS[block]
            movs.append(mov)

    if wkt["tipo"] == "for_time" and movs:
        movs.append({"chegada": True})
    wkt["movimentos"] = movs
    return wkt


def _parse_express(lines: list[str], wkt: Workout) -> Workout:
    """Extrai fórmulas 1 e 2 de um workout Express."""
    wkt["tipo"] = "express"; wkt["estilo"] = "express"
    f1_lines: list[str] = []
    f2_lines: list[str] = []
    current = None
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

    def extract_movs(flines: list[str], add_chegada: bool = False) -> tuple[list[Movimento], str]:
        movs: list[Movimento] = []
        tc_val = ""
        for line in flines:
            tc = re.search(r'time\s*cap[:\s]+(\d+)\s*min', line, re.I)
            if tc: tc_val = f"{tc.group(1)} min"; continue
            if re.match(r'^then[\.\s]*$', line, re.I):
                if movs: movs.append({"separador": "then..."}); continue
            p = _parse_mov_line(line)
            if p:
                reps, nome = p
                mov: Movimento = {"nome": nome}
                if reps is not None: mov["reps"] = reps
                movs.append(mov)
        if add_chegada and movs: movs.append({"chegada": True})
        return movs, tc_val

    f1_movs, _     = extract_movs(f1_lines, False)
    f2_movs, tc    = extract_movs(f2_lines, True)
    if tc: wkt["time_cap"] = tc

    if re.search(r'\s+[12]$', wkt["nome"]):
        wkt["nome"] = re.sub(r'\s+[12]$', '', wkt["nome"]).strip()

    wkt["formula1"] = {"janela": f1_janela or "00:00 → 05:00  ·  AMRAP 5 MIN",
                       "descricao": [], "movimentos": f1_movs}
    wkt["formula2"] = {"janela": f2_janela or "06:00 → 12:00  ·  FOR TIME",
                       "descricao": [], "movimentos": f2_movs}
    return wkt


# ── Excel import ────────────────────────────────────────────────────────────────
def _is_categoria_grid(ws) -> bool:
    """Detecta se a aba tem formato grade (colunas=categorias, linhas=workouts)."""
    rows = list(ws.iter_rows(min_row=1, max_row=3, values_only=True))
    if len(rows) < 2: return False
    r1 = [c for c in rows[0] if c is not None]
    r2 = [c for c in rows[1] if c is not None]
    return (len(r1) >= 2
            and all(isinstance(v, str) for v in r1[:4])
            and r2 and isinstance(r2[0], str) and '\n' in r2[0])


def parse_excel(data: bytes) -> dict[str, Any]:
    if not HAS_EXCEL:
        raise RuntimeError("openpyxl não disponível — instale com: pip install openpyxl")
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)

    todas_categorias: dict[str, list[Workout]] = {}
    evento_nome = ""
    for sname in wb.sheetnames:
        ws = wb[sname]
        if _is_categoria_grid(ws):
            resultado = _parse_excel_grade(wb, sname)
            todas_categorias.update(resultado.get("por_categoria", {}))
            if not evento_nome:
                evento_nome = resultado.get("evento_nome", "")

    atletas_por_categoria = _parse_atletas(wb)

    if todas_categorias:
        return {
            "tipo": "categoria_grid",
            "evento_nome": evento_nome,
            "categorias": list(todas_categorias.keys()),
            "por_categoria": todas_categorias,
            "atletas_por_categoria": atletas_por_categoria,
        }

    return _parse_excel_template(wb)


def _parse_atletas(wb) -> dict[str, list[Atleta]]:
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

    resultado: dict[str, list[Atleta]] = {}

    for sname in wb.sheetnames:
        ws = wb[sname]
        rows = list(ws.iter_rows(values_only=True))
        if len(rows) < 2: continue

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
        if col["nome"] is None: continue

        for row in rows[header_row_idx + 1:]:
            if not row or all(v is None for v in row): continue
            def cell(idx):
                if idx is None: return ""
                v = row[idx] if idx < len(row) else None
                return str(v).strip() if v is not None else ""

            nome = cell(col["nome"])
            if not nome: continue

            atleta: Atleta = {
                "nome":    nome,
                "box":     cell(col["box"]),
                "raia":    cell(col["raia"]),
                "bateria": cell(col["bateria"]),
                "numero":  cell(col["numero"]),
            }

            cat = cell(col["categoria"]) if col["categoria"] is not None else sname
            if not cat or cat.lower() in ("atletas", "inscritos", "participants", "athletes"):
                cat = sname

            if cat not in resultado:
                resultado[cat] = []
            resultado[cat].append(atleta)

    return resultado


def _parse_excel_grade(wb, sname: str) -> dict[str, Any]:
    """Parseia formato grade: col=categoria, linha=workout."""
    ws = wb[sname]
    rows = list(ws.iter_rows(values_only=True))
    if not rows: return {"erro": "Planilha vazia"}

    categorias: list[tuple[int, str]] = []
    for col_idx, val in enumerate(rows[0]):
        if val is not None:
            categorias.append((col_idx, str(val).strip()))

    por_categoria: dict[str, list[Workout]] = {}
    for cat_idx, cat_nome in categorias:
        workouts: list[Workout] = []
        for row_num, row in enumerate(rows[1:], 1):
            if cat_idx >= len(row) or row[cat_idx] is None: continue
            cell_text = str(row[cat_idx]).strip()
            if not cell_text: continue
            wkt = parse_workout_text(cell_text, row_num)
            workouts.append(wkt)
        if workouts:
            por_categoria[cat_nome] = workouts

    evento_nome = sname if sname.lower() not in ('individuais', 'duplas', 'equipamento') else ""

    return {
        "tipo": "categoria_grid",
        "evento_nome": evento_nome,
        "categorias": [c for _, c in categorias if c in por_categoria],
        "por_categoria": por_categoria,
    }


def _parse_excel_template(wb) -> dict[str, Any]:
    """Parseia formato template (Evento + Workouts + WKT1, WKT2...)."""
    config: dict[str, Any] = {"evento": {"nome": "", "categoria": "", "data": ""}, "workouts": []}
    wkt_map: dict[int, Workout] = {}
    for sname in wb.sheetnames:
        sl = sname.strip().lower()
        if sl == "evento":
            ws = wb[sname]
            for row in ws.iter_rows(values_only=True):
                if not row or not row[0]: continue
                k = str(row[0]).strip().lower()
                v = str(row[1]).strip() if len(row) > 1 and row[1] is not None else ""
                if k in ("nome", "name", "evento"): config["evento"]["nome"] = v
                elif k in ("categoria", "category"): config["evento"]["categoria"] = v
                elif k in ("data", "date"): config["evento"]["data"] = v
        m = re.match(r'^(?:wkt|workout)\s*[-_]?\s*(\d+)$', sl)
        if not m: continue
        num = int(m.group(1))
        ws = wb[sname]; hdrs = None; movs: list[Movimento] = []
        for row in ws.iter_rows(values_only=True):
            if not any(row): continue
            if hdrs is None: hdrs = [str(c or "").strip().lower() for c in row]; continue
            first = str(row[0] or "").strip().lower()
            if first in ("then...", "then", "então", "---"): movs.append({"separador": "then..."}); continue
            if first in ("chegada", "finish", "arrival"): movs.append({"chegada": True}); continue
            mov: Movimento = {}
            for i, h in enumerate(hdrs):
                if i >= len(row) or row[i] is None: continue
                v = str(row[i]).strip()
                if not v: continue
                if h in ("movimento", "exercise", "movement", "nome", "name"): mov["nome"] = v.upper()
                elif h in ("reps", "rep", "repetições"):
                    try: mov["reps"] = int(float(v))
                    except: mov["reps"] = v
                elif h in ("label", "bloco", "grupo", "block"): mov["label"] = v
            if "nome" in mov: movs.append(mov)
        wkt: Workout = {"numero": num, "nome": f"WKT {num}", "tipo": "for_time",
                        "modalidade": "individual", "time_cap": "", "movimentos": movs}
        config["workouts"].append(wkt); wkt_map[num] = wkt
    config["workouts"].sort(key=lambda w: w.get("numero", 0))
    return config


# ── PDF import ──────────────────────────────────────────────────────────────────
def parse_pdf(data: bytes) -> dict[str, Any]:
    if not HAS_PDF:
        raise RuntimeError("pdfplumber não disponível — instale com: pip install pdfplumber")
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    sections = re.split(r'\n(?=(?:Workout|WKT)\s+\d+)', full_text, flags=re.I)

    config: dict[str, Any] = {"evento": {"nome": "", "categoria": "", "data": ""}, "workouts": []}

    header_lines = [l.strip() for l in full_text.split('\n')[:8] if l.strip()]
    for line in header_lines:
        if len(line) > 4 and not re.match(r'^(workout|wkt|\d)', line, re.I):
            config["evento"]["nome"] = line
            break

    wkt_num = 0
    for sec in sections:
        sec = sec.strip()
        if not sec: continue
        has_wkt_hdr = re.match(r'^(?:Workout|WKT)\s+(\d+)', sec, re.I)
        has_quoted  = re.search(r'["“].+["”]', sec)
        has_movs    = re.search(r'^\d{1,3}\s+\w', sec, re.M)
        if not (has_wkt_hdr or (has_quoted and has_movs)): continue
        wkt_num += 1
        wkt = parse_workout_text(sec, wkt_num)
        config["workouts"].append(wkt)

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


# ── Helpers de ordenação e numeração ────────────────────────────────────────────
def _atleta_sort_key(a: Atleta) -> tuple:
    """Chave de ordenação para impressão sequencial: bateria → raia → nome.
    Raia é tratada numericamente quando possível ("10" depois de "2")."""
    bateria  = str(a.get('bateria', '') or '').strip().upper()
    raia_raw = str(a.get('raia', '') or '').strip()
    m = re.match(r'^(\d+)', raia_raw)
    raia_num = int(m.group(1)) if m else 10**9
    nome = str(a.get('nome', '') or '').strip().lower()
    return (bateria, raia_num, raia_raw.lower(), nome)


def assign_workout_numbers(workouts: list[Workout]) -> list[Workout]:
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
