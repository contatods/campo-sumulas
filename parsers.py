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
from movimentos import padronizar_workouts

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
    """Parser unificado de Excel.

    Sempre retorna shape `evento_multidia`. Os formatos legados (categoria_grid
    e template) são detectados e convertidos por adapters internos pra que o
    resto do sistema trabalhe num modelo único.
    """
    if not HAS_EXCEL:
        raise RuntimeError("openpyxl não disponível — instale com: pip install openpyxl")
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)

    # Formato multi-dia: aba `Workouts` + abas `<Dia>` e `<Dia> - Montagem`
    if _is_evento_multidia(wb):
        return parse_excel_multidia(wb)

    # Formato grades-por-modalidade: 1+ abas grade (ex: Individuais, Duplas, Times)
    # + abas <Dia> e <Dia> - Montagem (sem aba unificada Workouts)
    if _is_layout_grades_e_dias(wb):
        return parse_excel_grades_e_dias(wb)

    # Formato categoria_grid (modelo legado: 1 aba grade categoria × workout)
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
        return _adaptar_categoria_grid_para_multidia(
            evento_nome, todas_categorias, atletas_por_categoria,
        )

    # Fallback final: formato template (1 evento, lista plana de workouts)
    template_result = _parse_excel_template(wb)
    if not template_result.get('workouts') and not template_result.get('evento', {}).get('nome'):
        # Nenhum formato reconhecido: melhor erro explícito que estrutura
        # fantasma com "Único / Geral" vazia, que confunde a UI.
        return {'tipo': 'erro', 'erro': 'Excel sem dados reconhecíveis — esperava grade categoria×workout, formato multi-dia, ou template Evento+WKT.'}
    return _adaptar_template_para_multidia(template_result)


def _adaptar_categoria_grid_para_multidia(
    evento_nome: str,
    por_categoria: dict[str, list[Workout]],
    atletas_por_categoria: dict[str, list[Atleta]],
) -> dict[str, Any]:
    """Adapter: shape antigo categoria_grid → shape novo evento_multidia (1 dia 'Único')."""
    cats: list[dict[str, Any]] = []
    for workouts in por_categoria.values():
        padronizar_workouts(workouts)
    for cat_nome, workouts in por_categoria.items():
        atletas = atletas_por_categoria.get(cat_nome, [])
        baterias: list[dict[str, Any]] = []
        if atletas:
            baterias.append({
                'numero': '1',
                'codigo_evento': '',
                'horario_aquecimento': '',
                'horario_fila': '',
                'workouts_que_rodam': list(range(1, len(workouts) + 1)),
                'alocacoes': [
                    {
                        'raia':   a.get('raia', '') or str(i + 1),
                        'numero': a.get('numero', ''),
                        'nome':   a.get('nome', ''),
                        'box':    a.get('box', ''),
                    }
                    for i, a in enumerate(atletas)
                ],
            })
        cats.append({'nome': cat_nome, 'workouts': workouts, 'baterias': baterias})

    return {
        'tipo': 'evento_multidia',
        'evento_nome': evento_nome,
        'dias': [{'label': 'Único', 'categorias': cats}],
        'roster': [],
    }


def _adaptar_template_para_multidia(template_result: dict[str, Any]) -> dict[str, Any]:
    """Adapter: shape antigo template (1 evento, lista plana) → evento_multidia."""
    evento = template_result.get('evento', {}) or {}
    workouts = template_result.get('workouts', []) or []
    cat_nome = evento.get('categoria', '') or 'Geral'
    return {
        'tipo': 'evento_multidia',
        'evento_nome': evento.get('nome', ''),
        'dias': [{
            'label': 'Único',
            'categorias': [{
                'nome': cat_nome,
                'workouts': workouts,
                'baterias': [],
            }],
        }],
        'roster': [],
    }


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


# ── Excel multi-dia (formato real do evento) ──────────────────────────────────
# Formato esperado:
#   - Aba `Workouts`: grade dia (col A) × categoria (cols B+); cada célula é
#     o texto livre do workout. Linha de header de categorias se repete.
#   - Aba `<Dia>` (ex: `Sexta`, `Sábado`, `Domingo`): cronograma de baterias
#     com colunas Eventos | Categoria | Bateria | Arbitragem | Quantidade |
#     Aquecimento | <em branco> | Fila.
#   - Aba `<Dia> - Montagem`: blocos por bateria com header em 3 linhas
#     (horário, código+categoria, "Raia | Número | Nome | Box") seguido das
#     linhas de raia. Raias com #N/A são vazias.
#   - Aba `Atletas` (opcional): roster informativo de individuais.
#
# Convenção de arena: linha `Arena: <nome>` em qualquer ponto do texto livre
# do workout (na aba `Workouts`). É extraída e mostrada no header da súmula.

_DIA_LABELS_VALIDOS = ("segunda", "terça", "terca", "quarta", "quinta",
                        "sexta", "sábado", "sabado", "domingo")


def _is_evento_multidia(wb) -> bool:
    """Detecta se o arquivo é um evento multi-dia.

    Critérios: existe uma aba chamada `Workouts` E pelo menos uma aba do tipo
    `<Dia> - Montagem` (qualquer dia da semana).
    """
    nomes_lower = [s.lower() for s in wb.sheetnames]
    if 'workouts' not in nomes_lower:
        return False
    return any(' - montagem' in n for n in nomes_lower)


def _extrair_arena(texto: str) -> tuple[str, str]:
    """Extrai a primeira linha `Arena: <nome>` do texto livre do workout.

    Retorna (arena, texto_sem_linha_de_arena). Case-insensitive. Se não houver
    linha de arena, retorna ("", texto_original).
    """
    if not texto:
        return "", texto or ""
    linhas = texto.split('\n')
    arena = ""
    out: list[str] = []
    for linha in linhas:
        if not arena:
            m = re.match(r'^\s*arena\s*:\s*(.+?)\s*$', linha, re.I)
            if m:
                arena = m.group(1).strip()
                continue   # remove a linha do texto
        out.append(linha)
    return arena, '\n'.join(out)


def _parse_workouts_grade_multidia(ws) -> dict[str, dict[str, dict[str, Any]]]:
    """Lê a aba `Workouts` e retorna mapa { dia → { categoria → workout_parsed } }.

    A aba tem linhas de header de categoria que se repetem; a coluna A traz
    o rótulo do dia (Sexta/Sábado/Domingo) — é "sticky", vale até o próximo
    rótulo. Cada célula é texto livre que entra em parse_workout_text.
    """
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return {}

    resultado: dict[str, dict[str, dict[str, Any]]] = {}
    categorias_atuais: list[str] = []
    dia_atual: str = ""
    contador_workout = 0

    for row in rows:
        if not row or all(c is None for c in row):
            continue
        col_a = str(row[0]).strip() if row[0] is not None else ""
        # Linha de header de categoria: col A vazia, cols B+ com strings de categoria
        cells_b_em_diante = [c for c in row[1:] if c is not None]
        eh_header_categorias = (
            not col_a
            and len(cells_b_em_diante) >= 2
            and all(isinstance(c, str) and '\n' not in c for c in cells_b_em_diante[:3])
        )
        if eh_header_categorias:
            categorias_atuais = [str(c).strip() if c else "" for c in row[1:]]
            continue

        # Linha de dia (rótulo na col A) ou linha de workout (col A vazia, dia sticky)
        if col_a.lower() in _DIA_LABELS_VALIDOS:
            dia_atual = col_a

        if not dia_atual or not categorias_atuais:
            continue

        # Cada célula B+ é o texto de workout daquela categoria
        contador_workout += 1
        if dia_atual not in resultado:
            resultado[dia_atual] = {}
        for idx, cat in enumerate(categorias_atuais):
            if not cat:
                continue
            cell = row[idx + 1] if idx + 1 < len(row) else None
            if cell is None or not str(cell).strip():
                continue
            arena, texto_limpo = _extrair_arena(str(cell))
            wkt = parse_workout_text(texto_limpo, contador_workout)
            if arena:
                wkt['arena'] = arena
            if cat not in resultado[dia_atual]:
                resultado[dia_atual][cat] = []
            resultado[dia_atual][cat].append(wkt)

    return resultado


def _parse_cronograma_dia(ws) -> list[dict[str, Any]]:
    """Lê uma aba de cronograma (`Sexta`, `Sábado`, `Domingo`).

    Retorna lista de baterias: cada uma com numero, codigo_evento (ex: '#1',
    '#2 & #3'), categoria, horario_aquecimento, horario_fila.
    """
    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 3:
        return []

    # Encontra a linha de header (aquela que contém "Categoria")
    header_idx = None
    for i, row in enumerate(rows[:5]):
        valores = [str(c).strip().lower() if c else "" for c in row]
        if 'categoria' in valores:
            header_idx = i
            break
    if header_idx is None:
        return []

    header = [str(c).strip().lower() if c else "" for c in rows[header_idx]]

    def col(*opcoes: str) -> int | None:
        for i, h in enumerate(header):
            if h in opcoes:
                return i
        return None

    col_eventos     = col('eventos')
    col_categoria   = col('categoria')
    col_bateria     = col('bateria')
    col_aquecimento = col('aquecimento')
    col_fila        = col('fila')

    if col_categoria is None or col_bateria is None:
        return []

    baterias: list[dict[str, Any]] = []
    codigo_atual = ""
    for row in rows[header_idx + 1:]:
        if not row or all(c is None for c in row):
            continue
        cat_val = row[col_categoria] if col_categoria < len(row) else None
        if not cat_val:
            continue
        bat_val = row[col_bateria] if col_bateria < len(row) else None
        if bat_val is None:
            continue

        # codigo_evento é "sticky" — vale até a próxima linha com algo na col Eventos
        if col_eventos is not None and col_eventos < len(row):
            ev_val = row[col_eventos]
            if ev_val:
                codigo_atual = str(ev_val).strip()

        baterias.append({
            'numero': str(bat_val).strip(),
            'codigo_evento': codigo_atual,
            'categoria': str(cat_val).strip(),
            'horario_aquecimento': _fmt_horario(row[col_aquecimento]) if col_aquecimento is not None and col_aquecimento < len(row) else "",
            'horario_fila': _fmt_horario(row[col_fila]) if col_fila is not None and col_fila < len(row) else "",
        })
    return baterias


def _fmt_horario(v: Any) -> str:
    """Converte célula de horário em string `HH:MM`. Aceita time, datetime ou string."""
    if v is None:
        return ""
    if hasattr(v, 'strftime'):
        try:
            return v.strftime('%H:%M')
        except Exception:
            return str(v)
    s = str(v).strip()
    # "18:20:00" → "18:20"
    m = re.match(r'^(\d{1,2}:\d{2})(:\d{2})?$', s)
    if m:
        return m.group(1)
    return s


def _parse_montagem_dia(ws) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    """Lê uma aba `<Dia> - Montagem`.

    Estrutura repetida por bateria:
        L1: [horário, nº_bateria, ...]
        L2: [codigo_evento, categoria, ...]
        L3: ["Raia", "Número", "Nome", "Box", ...]
        L4..N: dados de raia

    Retorna dict mapeando (codigo_evento, categoria, numero_bateria) → lista de
    alocações (raia, numero, nome, box). Raias com nome `#N/A` são puladas.
    """
    rows = list(ws.iter_rows(values_only=True))
    resultado: dict[tuple[str, str, str], list[dict[str, Any]]] = {}

    i = 0
    while i < len(rows):
        row = rows[i]
        if not row or all(c is None for c in row):
            i += 1
            continue

        # Procura "Raia" + "Número" + "Nome" como header de bateria
        valores = [str(c).strip().lower() if c else "" for c in row]
        if 'raia' in valores and 'nome' in valores:
            # Encontrou um header. Volta 1-2 linhas pra pegar codigo+categoria.
            codigo = ""
            categoria = ""
            if i >= 1:
                prev = rows[i - 1]
                if prev:
                    codigo = str(prev[0]).strip() if prev[0] is not None else ""
                    if len(prev) > 1 and prev[1] is not None:
                        categoria = str(prev[1]).strip()
            # Bateria: 2 linhas atrás, segunda coluna
            numero_bat = ""
            if i >= 2:
                prev2 = rows[i - 2]
                if prev2 and len(prev2) > 1 and prev2[1] is not None:
                    numero_bat = str(prev2[1]).strip()
            # Mapeia colunas via header
            col_raia   = valores.index('raia')
            col_numero = valores.index('número') if 'número' in valores else (valores.index('numero') if 'numero' in valores else None)
            col_nome   = valores.index('nome')
            col_box    = valores.index('box') if 'box' in valores else None

            alocacoes: list[dict[str, Any]] = []
            j = i + 1
            while j < len(rows):
                r = rows[j]
                if not r or all(c is None for c in r):
                    break  # bloco acaba em linha vazia
                # Se a próxima linha for outro header de bateria, para
                vals_j = [str(c).strip().lower() if c else "" for c in r]
                if 'raia' in vals_j and 'nome' in vals_j:
                    break
                raia_v = r[col_raia] if col_raia < len(r) else None
                nome_v = r[col_nome] if col_nome is not None and col_nome < len(r) else None
                if raia_v is None or nome_v is None:
                    j += 1
                    continue
                nome_str = str(nome_v).strip()
                # Pula raias vazias (#N/A)
                if not nome_str or nome_str.upper() == '#N/A':
                    j += 1
                    continue
                aloc = {
                    'raia':   str(raia_v).strip(),
                    'numero': str(r[col_numero]).strip() if col_numero is not None and col_numero < len(r) and r[col_numero] is not None else "",
                    'nome':   nome_str,
                    'box':    str(r[col_box]).strip() if col_box is not None and col_box < len(r) and r[col_box] is not None else "",
                }
                alocacoes.append(aloc)
                j += 1

            if alocacoes:
                resultado[(codigo, categoria, numero_bat)] = alocacoes
            i = j
        else:
            i += 1

    return resultado


def _normalizar_categoria(s: str) -> str:
    """Normaliza nome de categoria pra comparação tolerante.

    Remove sufixos `(Heat N)`, `(Single Heat)`, etc., baixa caixa, comprime
    espaços, e tolera erros comuns de digitação como `begginer` → `beginner`.
    Retorna apenas o "core" da categoria pra match parcial via substring.
    """
    if not s:
        return ""
    # Pega só o trecho antes do primeiro `(` (corta sufixos de heat)
    core = s.split('(')[0]
    core = re.sub(r'\s+', ' ', core).strip().lower()
    # Normaliza variantes ortográficas comuns
    core = core.replace('begginer', 'beginner')
    return core


def _split_codigo_evento(codigo: str) -> list[str]:
    """Quebra um código tipo '#2 & #3' em ['#2', '#3']. Códigos simples viram [codigo]."""
    if not codigo:
        return []
    return [p.strip() for p in re.split(r'\s*&\s*', codigo) if p.strip()]


def _workout_numero_de_codigo(codigo: str) -> int | None:
    """Extrai o número do workout de '#1' → 1, '#02' → 2, 'Workout 04' → 4."""
    m = re.search(r'(\d+)', codigo)
    return int(m.group(1)) if m else None


def _roster_individuais(wb) -> list[dict[str, str]]:
    """Lê a aba `Atletas` (roster informativo): número, nome, box."""
    if 'Atletas' not in wb.sheetnames:
        return []
    ws = wb['Atletas']
    out: list[dict[str, str]] = []
    for row in ws.iter_rows(values_only=True):
        if not row or all(c is None for c in row):
            continue
        numero = str(row[0]).strip() if row[0] is not None else ""
        nome   = str(row[1]).strip() if len(row) > 1 and row[1] is not None else ""
        box    = str(row[2]).strip() if len(row) > 2 and row[2] is not None else ""
        if not nome:
            continue
        out.append({'numero': numero, 'nome': nome, 'box': box})
    return out


def parse_excel_multidia(wb) -> dict[str, Any]:
    """Parser do formato evento multi-dia (Workouts + cronograma + montagem).

    Retorna estrutura aninhada:
        { tipo: 'evento_multidia',
          evento_nome: str,
          dias: [
            { label: 'Sexta',
              categorias: [
                { nome: 'Trio Rx Misto',
                  workouts: [Workout, ...],
                  baterias: [
                    { numero: '1',
                      codigo_evento: '#1',
                      horario_aquecimento: '18:20',
                      horario_fila: '18:45',
                      workouts_que_rodam: [1],   # nº dos workouts (índices em workouts da categoria)
                      alocacoes: [{raia, numero, nome, box}, ...]
                    }
                  ]
                }
              ]
            }
          ],
          roster: [{numero, nome, box}, ...],
        }
    """
    # 1) Workouts: dia → categoria → [workouts]
    if 'Workouts' not in wb.sheetnames:
        return {'tipo': 'erro', 'erro': 'Aba Workouts ausente'}
    workouts_por_dia_cat = _parse_workouts_grade_multidia(wb['Workouts'])
    if not workouts_por_dia_cat:
        return {'tipo': 'erro', 'erro': 'Aba Workouts vazia ou ilegível'}

    # 2) Pra cada dia detectado em Workouts, lê cronograma + montagem
    nomes_lower = {s.lower(): s for s in wb.sheetnames}
    dias_resultado: list[dict[str, Any]] = []
    for dia_label in workouts_por_dia_cat.keys():
        sname = nomes_lower.get(dia_label.lower())
        montagem_sname = nomes_lower.get(f"{dia_label.lower()} - montagem")
        cronograma = _parse_cronograma_dia(wb[sname]) if sname else []
        montagem   = _parse_montagem_dia(wb[montagem_sname]) if montagem_sname else {}

        # Agrupa por categoria do dia
        cats_resultado: list[dict[str, Any]] = []
        for cat_nome, lista_workouts in workouts_por_dia_cat[dia_label].items():
            # Filtra baterias do cronograma cuja categoria casa (ignora sufixo "(Single Heat)" etc.)
            cat_norm = _normalizar_categoria(cat_nome)
            baterias_da_cat = [b for b in cronograma if cat_norm in _normalizar_categoria(b['categoria'])]
            # Para cada bateria, monta as alocações via montagem
            for b in baterias_da_cat:
                # codigo_evento pode estar vazio no cronograma; nesse caso usa a Montagem
                # como fonte primária do código.
                codigos_cronograma = set(_split_codigo_evento(b['codigo_evento']))
                aloc: list[dict[str, Any]] = []
                codigo_montagem = ""
                for chave, alocs in montagem.items():
                    chave_codigo, chave_cat, chave_bat = chave
                    if chave_bat != b['numero']:
                        continue
                    if cat_norm not in _normalizar_categoria(chave_cat):
                        continue
                    # Se cronograma trouxe códigos, exige interseção com os da montagem.
                    # Ambos podem ser compostos (ex: '#2 & #3'), então comparo conjuntos.
                    if codigos_cronograma:
                        codigos_chave = set(_split_codigo_evento(chave_codigo))
                        if not (codigos_cronograma & codigos_chave):
                            continue
                    aloc = alocs
                    codigo_montagem = chave_codigo
                    break
                # codigo final: o que veio do cronograma OU o que a montagem revelou
                codigo_final = b['codigo_evento'] or codigo_montagem
                codigos_finais = _split_codigo_evento(codigo_final) or ([codigo_final] if codigo_final else [])
                workouts_que_rodam = [n for n in (_workout_numero_de_codigo(c) for c in codigos_finais) if n is not None]
                b_full = {
                    **b,
                    'codigo_evento': codigo_final,
                    'workouts_que_rodam': workouts_que_rodam,
                    'alocacoes': aloc,
                }
                cat_existing = next((c for c in cats_resultado if c['nome'] == cat_nome), None)
                if cat_existing is None:
                    cat_existing = {'nome': cat_nome, 'workouts': lista_workouts, 'baterias': []}
                    cats_resultado.append(cat_existing)
                cat_existing['baterias'].append(b_full)

            # Categorias sem bateria no cronograma ainda entram (workouts mostrados, sem alocação)
            if not baterias_da_cat:
                cats_resultado.append({'nome': cat_nome, 'workouts': lista_workouts, 'baterias': []})

        dias_resultado.append({'label': dia_label, 'categorias': cats_resultado})

    # Padroniza nomes de movimentos (PT-BR/EN/case → forma canônica)
    for d in dias_resultado:
        for c in d.get('categorias', []) or []:
            padronizar_workouts(c.get('workouts', []) or [])

    return {
        'tipo': 'evento_multidia',
        'evento_nome': '',  # pode ser preenchido pela UI a partir do nome do arquivo ou config
        'dias': dias_resultado,
        'roster': _roster_individuais(wb),
    }


# ── Layout grades-por-modalidade + dias com Montagem ──────────────────────────
# Caso de uso: planilhas com workouts em abas separadas por modalidade
# (ex: `Individuais` + `Duplas`, ou `Times` + `Solo`, etc.) e cronograma +
# montagem por dia (`<Dia>` + `<Dia> - Montagem`). Sem aba unificada `Workouts`.

def _is_layout_grades_e_dias(wb) -> bool:
    nomes_lower = [s.lower() for s in wb.sheetnames]
    if 'workouts' in nomes_lower:
        return False  # se tem Workouts, o detector multidia clássico cuida disso
    tem_grade    = any(_is_categoria_grid(wb[s]) for s in wb.sheetnames)
    tem_montagem = any(' - montagem' in n for n in nomes_lower)
    return tem_grade and tem_montagem


def _quebrar_categoria_composta(s: str) -> list[str]:
    """'A (Heat 1) & B (Heat 2)' → ['a', 'b'] (cada parte normalizada).

    Diferente de `_normalizar_categoria`, que perde tudo depois do primeiro `(`
    e portanto descarta a segunda categoria de baterias mistas.
    """
    if not s:
        return []
    return [_normalizar_categoria(p) for p in re.split(r'\s+&\s+', s) if p.strip()]


def _bateria_casa_categoria(bateria_categoria: str, cat_grade_norm: str) -> bool:
    """Match exato (após normalização e quebra de '&').

    Substring causa falso positivo entre 'Rx Masculino' (Sábado) e 'Dupla Rx
    Masculino' (Domingo) — categorias diferentes que rodam em dias diferentes.
    """
    return cat_grade_norm in _quebrar_categoria_composta(bateria_categoria)


def _propagar_codigos_da_montagem(
    cronograma: list[dict[str, Any]],
    montagem: dict[tuple[str, str, str], list[dict[str, Any]]],
) -> None:
    """Quando o cronograma vem sem códigos de evento (`#1`, `#2 & #3`, etc),
    procura o código correspondente na montagem pelo número da bateria.

    Mutates `cronograma` in-place, preenchendo `codigo_evento`.
    """
    if any(b.get('codigo_evento') for b in cronograma):
        return  # cronograma já tem códigos — não interfere
    cods_por_bat: dict[str, str] = {}
    for (cod, _cat, bat), _ in montagem.items():
        if cod and bat:
            cods_por_bat.setdefault(bat, cod)
    for b in cronograma:
        if not b.get('codigo_evento'):
            b['codigo_evento'] = cods_por_bat.get(b.get('numero', ''), '')


def _roster_de_abas_atletas(wb) -> list[dict[str, str]]:
    """Lê abas tipo `Atleta - X` / `Atletas - X` sem header.

    Estrutura esperada: col A = número, col B = nome, col C = box.
    Concatena tudo num único roster.
    """
    out: list[dict[str, str]] = []
    for sname in wb.sheetnames:
        sl = sname.lower().strip()
        if not (sl.startswith('atleta - ') or sl.startswith('atletas - ')):
            continue
        ws = wb[sname]
        for row in ws.iter_rows(values_only=True):
            if not row or all(c is None for c in row):
                continue
            numero = str(row[0]).strip() if row[0] is not None else ""
            nome   = str(row[1]).strip() if len(row) > 1 and row[1] is not None else ""
            box    = str(row[2]).strip() if len(row) > 2 and row[2] is not None else ""
            if not nome or nome.upper() == '#N/A':
                continue
            out.append({'numero': numero, 'nome': nome, 'box': box})
    return out


def _parse_inscritos(wb) -> dict[str, tuple[int, int]]:
    """Lê aba `Inscritos` (se houver) → mapa categoria_normalizada → (n_ini, n_fim).

    Estrutura esperada: header com `Nome` + colunas que contenham `inicial` e
    `final`. Múltiplos blocos (separados por linhas vazias) são suportados —
    típico quando há Individuais e Duplas no mesmo evento. Retorna `{}` se a
    aba não existir ou estiver fora do padrão.

    Usado pra desambiguar alocações de baterias mistas (atletas de duas
    categorias rodando juntos): a faixa de número diz quem pertence a qual.
    """
    sname = next((s for s in wb.sheetnames if s.strip().lower() == 'inscritos'), None)
    if not sname:
        return {}
    ws = wb[sname]

    resultado: dict[str, tuple[int, int]] = {}
    col_nome = col_ini = col_fim = None
    for row in ws.iter_rows(values_only=True):
        if not row or all(c is None for c in row):
            col_nome = col_ini = col_fim = None  # quebra de bloco: re-detecta header
            continue
        vals = [str(c).strip().lower() if c else '' for c in row]
        # Header novo: precisa ter coluna 'nome' + uma 'inicial' + uma 'final'
        if 'nome' in vals and any('inicial' in v for v in vals) and any('final' in v for v in vals):
            col_nome = vals.index('nome')
            col_ini  = next(i for i, v in enumerate(vals) if 'inicial' in v)
            col_fim  = next(i for i, v in enumerate(vals) if 'final' in v)
            continue
        if col_nome is None:
            continue
        nome = row[col_nome] if col_nome < len(row) else None
        ini  = row[col_ini]  if col_ini  < len(row) else None
        fim  = row[col_fim]  if col_fim  < len(row) else None
        if not nome or ini is None or fim is None:
            continue
        try:
            ini_int, fim_int = int(ini), int(fim)
        except (TypeError, ValueError):
            continue
        if ini_int > fim_int:
            continue
        resultado[_normalizar_categoria(str(nome))] = (ini_int, fim_int)
    return resultado


def _filtrar_alocacoes_por_faixa(
    alocs: list[dict[str, Any]], faixa: tuple[int, int]
) -> list[dict[str, Any]]:
    """Mantém só alocações cuja `numero` cai em [ini, fim].

    Alocações sem `numero` numérico são removidas — não há como saber a qual
    categoria pertencem. Usado pra desambiguar baterias mistas.
    """
    ini, fim = faixa
    out: list[dict[str, Any]] = []
    for a in alocs:
        try:
            n = int(str(a.get('numero', '')).strip())
        except (ValueError, AttributeError):
            continue
        if ini <= n <= fim:
            out.append(a)
    return out


def parse_excel_grades_e_dias(wb) -> dict[str, Any]:
    """Parser para layout: grades de workout por modalidade + dias com Montagem.

    Estratégia:
      1. Lê todas as abas grade (Individuais, Duplas, ...) → categoria → workouts.
      2. Detecta pares `<Dia>` + `<Dia> - Montagem`.
      3. Pra cada dia, lê cronograma + montagem. Se cronograma vem sem códigos,
         puxa código da montagem pela bateria.
      4. Pra cada categoria da grade, anexa ao dia onde aparece no cronograma.
      5. Roster lido das abas `Atleta(s) - X`.
    """
    # 1) Grades — junta todas
    grade_por_categoria: dict[str, list[Workout]] = {}
    for sname in wb.sheetnames:
        ws = wb[sname]
        if not _is_categoria_grid(ws):
            continue
        r = _parse_excel_grade(wb, sname)
        # Não sobrescreve: categorias com mesmo nome em grades diferentes mantêm
        # a primeira ocorrência (raro — modelagem do usuário deve evitar).
        for cat, wkts in r.get('por_categoria', {}).items():
            grade_por_categoria.setdefault(cat, wkts)
    if not grade_por_categoria:
        return {'tipo': 'erro', 'erro': 'Nenhuma grade categoria×workout detectada'}

    for workouts in grade_por_categoria.values():
        padronizar_workouts(workouts)

    # Faixas de número por categoria — desambigua atletas em baterias mistas
    inscritos_faixas = _parse_inscritos(wb)

    # 2) Dias detectados a partir de `<Dia> - Montagem`
    nomes_lower = {s.lower(): s for s in wb.sheetnames}
    dias_detectados: list[str] = []
    for sname in wb.sheetnames:
        sl = sname.lower()
        if sl.endswith(' - montagem'):
            dia_sl = sl[: -len(' - montagem')]
            if dia_sl in nomes_lower:
                dias_detectados.append(nomes_lower[dia_sl])  # nome original (com acentos)
    if not dias_detectados:
        return {'tipo': 'erro', 'erro': 'Nenhum par <Dia> + <Dia> - Montagem encontrado'}

    # 3-4) Pra cada dia, lê e agrupa categorias presentes
    dias_resultado: list[dict[str, Any]] = []
    for dia_label in dias_detectados:
        sname_dia = nomes_lower[dia_label.lower()]
        sname_mont = nomes_lower[f"{dia_label.lower()} - montagem"]
        cronograma = _parse_cronograma_dia(wb[sname_dia])
        montagem   = _parse_montagem_dia(wb[sname_mont])
        _propagar_codigos_da_montagem(cronograma, montagem)

        # Conjunto de categorias (normalizadas) presentes neste dia
        cats_no_dia_norm: list[str] = []
        for b in cronograma:
            cats_no_dia_norm.extend(_quebrar_categoria_composta(b.get('categoria', '')))

        cats_resultado: list[dict[str, Any]] = []
        for cat_grade, workouts in grade_por_categoria.items():
            cat_grade_norm = _normalizar_categoria(cat_grade)
            # Só anexa categoria se ela aparece em alguma bateria deste dia
            if cat_grade_norm not in cats_no_dia_norm:
                continue

            baterias_da_cat = [
                b for b in cronograma
                if _bateria_casa_categoria(b.get('categoria', ''), cat_grade_norm)
            ]

            baterias_full: list[dict[str, Any]] = []
            for b in baterias_da_cat:
                codigos_b = set(_split_codigo_evento(b.get('codigo_evento', '')))
                # 1ª passada: match estrito (bat + cat + interseção de códigos).
                # 2ª passada: match relaxado (só bat + cat) — só vale quando há um
                # único candidato (sem ambiguidade). Cobre casos em que o código
                # no cronograma e na montagem divergem, mas a categoria/bateria
                # identificam unicamente a alocação.
                candidatos_estrito: list[tuple] = []
                candidatos_relaxado: list[tuple] = []
                for (chave_cod, chave_cat, chave_bat), alocs in montagem.items():
                    if chave_bat != b['numero']:
                        continue
                    if not _bateria_casa_categoria(chave_cat, cat_grade_norm):
                        continue
                    candidatos_relaxado.append((chave_cod, alocs))
                    if codigos_b:
                        codigos_chave = set(_split_codigo_evento(chave_cod))
                        if codigos_b & codigos_chave:
                            candidatos_estrito.append((chave_cod, alocs))
                escolhido = candidatos_estrito[0] if candidatos_estrito else (
                    candidatos_relaxado[0] if len(candidatos_relaxado) == 1 else None
                )
                codigo_montagem, aloc = escolhido if escolhido else ("", [])

                # Bateria mista (`X & Y`): a Montagem traz atletas das duas
                # categorias juntos. Se temos faixa de número da categoria
                # atual (via Inscritos), filtra pra não vazar atletas da outra.
                if aloc and len(_quebrar_categoria_composta(b.get('categoria', ''))) > 1:
                    faixa = inscritos_faixas.get(cat_grade_norm)
                    if faixa:
                        aloc = _filtrar_alocacoes_por_faixa(aloc, faixa)

                codigo_final = b.get('codigo_evento') or codigo_montagem
                codigos_finais = _split_codigo_evento(codigo_final) or (
                    [codigo_final] if codigo_final else []
                )
                workouts_que_rodam = [
                    n for n in (_workout_numero_de_codigo(c) for c in codigos_finais)
                    if n is not None
                ]
                baterias_full.append({
                    **b,
                    'codigo_evento': codigo_final,
                    'workouts_que_rodam': workouts_que_rodam,
                    'alocacoes': aloc,
                })

            cats_resultado.append({
                'nome':      cat_grade,
                'workouts':  workouts,
                'baterias':  baterias_full,
            })

        dias_resultado.append({'label': dia_label, 'categorias': cats_resultado})

    return {
        'tipo':         'evento_multidia',
        'evento_nome':  '',
        'dias':         dias_resultado,
        'roster':       _roster_de_abas_atletas(wb),
    }
