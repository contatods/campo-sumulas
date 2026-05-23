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


# Separadores que marcam fim da prescrição "core" e início de
# regras/observações/regulamento que NÃO devem aparecer na súmula impressa.
# A súmula deve conter só o essencial pro atleta executar; o resto é regulamento
# e atleta/árbitro consultam à parte.
_DESC_CUT_RE = re.compile(
    r'^\s*(?:[─—–\-]+\s*)?'
    r'(?:notas?|observa[çc][õo]es?|pontua[çc][ãa]o|tiebreak|regras?|regulamento|crit[ée]rios?|score|scoring)'
    r'\s*(?:[─—–\-]+\s*)?\s*:?\s*$',
    re.IGNORECASE,
)


def _truncar_descricao_em_notas(lines: list[str]) -> list[str]:
    """Corta a lista de linhas no primeiro separador tipo `NOTAS`, `Observações`,
    `Pontuação`, etc. Tudo abaixo é regulamento e fica fora da súmula impressa.

    Mantém comportamento original quando não há separadores (lista intacta).
    """
    out: list[str] = []
    for line in lines:
        if _DESC_CUT_RE.match(line):
            break
        out.append(line)
    return out


# Palavras que indicam FRASE EXPLICATIVA (não-movimento). Linhas que começam
# com número seguido dessas palavras NÃO devem virar movimento. Cobre português
# e inglês — listas de "regras" e "divisão de funções" típicas em prescrições
# de eventos sofisticados (trios, duplas, etc).
_FRASE_NAO_MOVIMENTO_RE = re.compile(
    r'\b(?:atletas?|nadar(?:ão|emos|á|em)|executar(?:á|emos|ão|em)|'
    r'iniciar(?:á|emos|ão|em)|completar(?:á|emos|ão|em)|trocar(?:á|emos|ão|em)|'
    r'ser(?:á|ão|emos|ia)?|times?|equipes?|teams?|round\s+seguinte|'
    r'definid[ao]s?|alterad[ao]s?|escolher[áa]?|cada\s+\w+\s+executar|'
    r'minute[s]?\s*,?\s*for\s+\d+\s+rounds?|'
    r'rounds?\s+per\s+athletes?|rounds?\s+por\s+atleta|'
    r'sets?\s+per\s+athletes?|sets?\s+por\s+atleta)\b',
    re.IGNORECASE,
)


# Extrai carga no fim do nome do movimento. Dois formatos:
#   A) NUM UNIT (unidade obrigatória):  '50/35 lb', '20kg', '225/155 LB', '75#'
#   B) @NUM (unit opcional):             '@135/95', '@40lb'
# NÃO captura distâncias/calorias (cal, m, km) — esses ficam no nome
# (ex: '900M SKI ERG' permanece intacto).
_CARGA_END_RE = re.compile(
    r'\s*\(?\s*'
    r'(\d+(?:[\.,]\d+)?(?:/\d+(?:[\.,]\d+)?)?)\s*'   # número (ou par M/F)
    r'(kg|lb|lbs|#|pood)'                            # unidade DE PESO obrigatória
    r'\s*\)?\s*$',
    re.IGNORECASE,
)
_CARGA_AT_END_RE = re.compile(
    r'\s*\(?\s*@\s*'
    r'(\d+(?:[\.,]\d+)?(?:/\d+(?:[\.,]\d+)?)?)\s*'   # número após @
    r'(kg|lb|lbs|#|pood)?'                           # unidade opcional
    r'\s*\)?\s*$',
    re.IGNORECASE,
)


def _extrair_carga(nome: str) -> tuple[str, Optional[str]]:
    """Separa o nome do movimento da carga ao final, se houver.

    Retorna (nome_sem_carga, carga|None). Carga normalizada em uppercase
    ('50/35 LB', '20 KG', '@135/95'). Sem unidade quando o input usa só `@`.
    Genérico — usado em parser de qualquer tipo de workout.
    """
    m = _CARGA_END_RE.search(nome) or _CARGA_AT_END_RE.search(nome)
    if not m: return (nome, None)
    nome_limpo = nome[:m.start()].rstrip(' ,-()@').strip()
    if not nome_limpo: return (nome, None)   # não destrói nomes só-carga
    num = m.group(1)
    unit = (m.group(2) or '').upper()
    carga = f"{num} {unit}".strip() if unit else num
    return (nome_limpo, carga)


# ── Texto livre de workout ──────────────────────────────────────────────────────
def _parse_mov_line(line: str) -> Optional[tuple[int, str]]:
    """Extrai (reps, nome_upper) de uma linha de movimento.

    Suporta 3 formatos do número inicial:
      `20 Pull-Ups`            → reps=20, nome='PULL-UPS'
      `20-metres DB Lunges`    → reps=20, nome='20-METRES DB LUNGES'  (hífen)
      `900m Ski Erg`           → reps=900, nome='900M SKI ERG'        (unidade colada)
      `5km Run`                → reps=5, nome='5KM RUN'

    Rejeita linhas que parecem frase explicativa (`2 atletas nadarão...`)
    pra evitar que virem movimentos.
    """
    s = line.strip()
    # 4 formatos: NUM/NUM resto (gendered), NUM+unit+ESP, NUM-resto, NUM ESP resto
    m = re.match(r'^(\d{1,4})/(\d{1,4})\s+(.+)$', s)            # 30/24 cal Row
    if m:
        num_s, num_f, rest = m.group(1), m.group(2), m.group(3).strip()
        nome = f"{num_s}/{num_f} {rest}".upper()
    else:
        m = re.match(r'^(\d{1,4})([a-z]+)\s+(.+)$', s, re.I)    # 900m Ski Erg
        if m:
            num_s, unit, rest = m.group(1), m.group(2), m.group(3).strip()
            nome = f"{num_s}{unit} {rest}".upper()
        else:
            m = re.match(r'^(\d{1,4})([-\s])(.+)$', s)
            if not m: return None
            num_s, sep, rest = m.group(1), m.group(2), m.group(3).strip()
            if sep == '-':
                nome = f"{num_s}-{rest}".upper()
            else:
                nome = rest.upper()
    try: num = int(num_s)
    except ValueError: return None
    if num >= 1000: return None  # evita anos
    # Rejeita frases explicativas (`2 atletas nadarão`, `5 times escolherão`, etc)
    if _FRASE_NAO_MOVIMENTO_RE.search(nome):
        return None
    return (num, nome)


_FOR_LOAD_IGNORE_RE = re.compile(
    r'^(?:for\s+load|max\s+(?:lift|load)|carga\s+m[áa]xima|time\s+cap|tempo|'
    r'\d+\s+tentativas?|notas?|observa[çc][ãa]o|descanso|rest\b|entre\s+|'
    r'cada\s+atleta|cada\s+tentativa|score|pontua)',
    re.IGNORECASE,
)
_FOR_LOAD_BUYIN_RE = re.compile(
    r'^\s*(?:buy[\s-]?in|aquecimento|warm[\s-]?up)\s*[:\-]?\s*(.*)$',
    re.IGNORECASE,
)
_FOR_LOAD_THEN_RE = re.compile(
    r'^\s*(?:then|ent[ãa]o|depois|after|ap[óo]s|complex)\b[:\s\-,.]*\s*(.*)$',
    re.IGNORECASE,
)


def _extrair_sequencia_for_load(lines: list[str], nome: str) -> dict:
    """Extrai sequência pro lembrete do árbitro em For Load.

    Retorna `{'buy_in': str|None, 'complex': str|None}` — duas strings
    enxutas. Só o que importa pro árbitro: o que aquece (buy-in) e o que
    vale carga (complex).

    Estratégia (ordem):
      1. Trunca em NOTAS / OBSERVAÇÕES / ─── (regulamento fora do escopo).
      2. Se houver marcador `COMPLEX:` em alguma linha, usa só o que vem
         APÓS como complex; o que vem antes (cal/cal Air Bike, Row, etc)
         vira buy-in.
      3. Senão, busca marcadores 'Buy-in:' / 'Then:' explícitos.
      4. Pula linhas duplicadas tipo 'ATHLETE 2 ... (MESMO PADRÃO)' — todos
         atletas fazem a mesma sequência, descrita só uma vez.
    """
    # 1) Trunca em NOTAS — regulamento fora do escopo da súmula impressa
    lines = _truncar_descricao_em_notas(lines)

    # 2) Procura linha com 'COMPLEX:' (1-RM Complex, Squat Complex, etc)
    complex_re = re.compile(r'^(.*?)\b(?:1[-\s]?rep[-\s]?max\s+complex|complex)\s*:\s*(.+)$', re.I)
    skip_re = re.compile(
        r'mesmo\s+padr[ãa]o|same\s+as|mesma\s+sequ[êe]ncia|'
        r'atleta\s*\d+\s*\(|athlete\s*\d+\s*\(',
        re.I,
    )
    for ln in lines:
        s = ln.strip()
        if not s: continue
        if _FOR_LOAD_IGNORE_RE.match(s): continue
        m = complex_re.match(s)
        if not m: continue
        antes = m.group(1).strip()
        depois = m.group(2).strip()
        # buy-in = caloric/distance work antes do COMPLEX (12-cal Air Bike, 200m Row)
        buy_in = _extrair_buyin_caloric(antes)
        # complex = parte após 'COMPLEX:' — normaliza separadores
        complex_ = _normalizar_complex(depois)
        return {'buy_in': buy_in, 'complex': complex_}

    # 3) Sem COMPLEX explícito: usa marcadores Buy-in / Then
    buy_in_parts: list[str] = []
    complex_parts: list[str] = []
    is_buyin = False
    for ln in lines:
        s = ln.strip()
        if not s: continue
        if s.startswith('"') or s.startswith('“') or s.startswith('‘'): continue
        if _FOR_LOAD_IGNORE_RE.match(s): continue
        if skip_re.search(s): continue   # pula 'ATHLETE 2 (mesmo padrão)'
        m_buyin = _FOR_LOAD_BUYIN_RE.match(s)
        if m_buyin:
            is_buyin = True
            resto = m_buyin.group(1).strip()
            if resto: buy_in_parts.append(resto)
            continue
        m_then = _FOR_LOAD_THEN_RE.match(s)
        if m_then:
            is_buyin = False
            resto = m_then.group(1).strip()
            if resto: complex_parts.append(resto)
            continue
        (buy_in_parts if is_buyin else complex_parts).append(s)
    buy_in = ' '.join(buy_in_parts).strip().upper() or None
    complex_ = ' '.join(complex_parts).strip().upper() or None
    # 4) Fallback: nome do workout (limpo de 'MAX' / 'CARGA MÁXIMA')
    if not complex_ and nome:
        complex_ = re.sub(r'^(?:max\s+|carga\s+m[áa]xima\s+(?:de\s+)?)',
                          '', nome, flags=re.I).strip().upper() or None
    return {'buy_in': buy_in, 'complex': complex_}


def _extrair_buyin_caloric(texto: str) -> Optional[str]:
    """Pega o trecho do tipo 'N-cal Air Bike', 'N cal Row', 'Nm Run' do início.

    Usado pra capturar buy-in que vem antes de 'COMPLEX:' na mesma linha.
    Strip prefixos tipo 'ATHLETE 1 (0:00-4:00)'.
    """
    s = texto.strip()
    # Remove 'ATHLETE N (window)' do início
    s = re.sub(r'^\s*(?:athlete|atleta)\s*\d+\s*\([^)]*\)\s*', '', s, flags=re.I).strip()
    if not s: return None
    m = re.search(
        r'(\d+[-\s]?(?:cal|calorie|calorias?|m|metres?|metros?|km|mi)\b[^,.;:]*?'
        r'(?:bike|row|ski|run|swim|jump|rope|ergometer|erg)?[^,.;:]*)',
        s, re.I,
    )
    if not m: return s.upper() or None
    return m.group(1).strip().upper()


def _normalizar_complex(texto: str) -> str:
    """Normaliza '1 X 1 Y 1 Z' → '1 X + 1 Y + 1 Z' (separador visual).

    Preserva combos já com '+' / 'e' / 'and' / '&'. Limita tamanho da string.
    """
    s = texto.strip()
    # Se já tem separador, só uppercase
    if re.search(r'[+&]|\be\b|\band\b', s, re.I):
        return s.upper()
    # Inserir ' + ' entre partes 'N <palavras> N <palavras>'
    s = re.sub(r'(\d+\s+[A-Za-zÀ-ú\-]+(?:\s+[A-Za-zÀ-ú\-]+){0,3})\s+(?=\d+\s+[A-Za-zÀ-ú])',
               r'\1 + ', s)
    return s.upper()


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
    if 'for load' in full or 'max lift' in full or 'max load' in full or \
       re.search(r'\bcarga m[áa]xima\b', full):
        wkt["tipo"] = "for_load"
        # Tentativas explícitas no texto (ex: "5 tentativas")
        m_tent = re.search(r'(\d+)\s*tentativas?', full)
        if m_tent:
            try: wkt["tentativas"] = int(m_tent.group(1))
            except ValueError: pass
        # Texto livre fica em descricao; trunca em separadores tipo NOTAS
        # pra não bagunçar a súmula com regulamento que estoura A4.
        wkt["descricao"] = _truncar_descricao_em_notas(lines)
        wkt["movimentos"] = []
        # Extrai sequência de movimentos pro árbitro (lembrete visual).
        # Aceita combos com '+' ('1 Squat Clean + 1 Push Jerk + 1 Split Jerk'),
        # listas linha a linha, ou movimento embutido no nome do workout.
        wkt["sequencia_movimentos"] = _extrair_sequencia_for_load(lines, wkt.get("nome", ""))
        return wkt
    if 'for time' in full or 'por tempo' in full:
        wkt["tipo"] = "for_time"
    elif 'amrap' in full or 'as many reps' in full:
        wkt["tipo"] = "amrap"

    # Detecta relay 'N round(s) per athlete' (For Time típico em trios).
    # Marca wkt['rounds_per_atleta'] pra que o renderer gere sub-blocos.
    m_relay = re.search(r'(\d+)\s+rounds?\s+per\s+athletes?', full, re.I) \
              or re.search(r'(\d+)\s+rounds?\s+por\s+atleta', full, re.I)
    if m_relay:
        try: wkt["rounds_per_atleta"] = int(m_relay.group(1))
        except ValueError: pass

    # Detecta EMOM (`every X minutes, for Y rounds`) e marca como AMRAP-rounds.
    m_emom = re.search(r'every\s+(\d+(?::\d+)?)\s*minutes?\s*,?\s*for\s+(\d+)\s+rounds?', full, re.I)
    if m_emom:
        wkt["tipo"] = "amrap"   # ainda usa scorecard AMRAP
        wkt["emom_janela"] = m_emom.group(1)
        try: wkt["emom_rounds"] = int(m_emom.group(2))
        except ValueError: pass

    # Detecta tie-break por round — phrasings comuns PT/EN:
    #   'Tiebreak: tempo no final de cada round'
    #   'Tie-break: tempo ao final de cada rodada'
    #   'Tiebreak: time at the end of each round'
    #   'TB por round', 'TB cada round', 'tie-break por round'
    #   'desempate: tempo ao fim de cada round'
    if re.search(r'(?:tie[\s-]?break|tb|desempate)[:\s-]*'
                 r'(?:tempo|time)?[^.\n]{0,40}'
                 r'(?:final|fim|end)\s+(?:de|of)?\s*(?:the\s+)?(?:cada|each)\s+(?:round|rodada)', full, re.I) \
       or re.search(r'(?:tie[\s-]?break|tb|desempate)\s+(?:por|per|each|a\s+cada)\s+(?:round|rodada)', full, re.I):
        wkt["tiebreak_por_round"] = True
    # Tiebreak geral (não por round): For Time típico — 'Tiebreak: tempo ao fim
    # das 21 pull-ups'. Marca flag pro score box criar campo de tempo extra.
    if not wkt.get("tiebreak_por_round"):
        for ln in lines:
            m_tb = re.match(r'\s*(?:tie[\s-]?break|tb|desempate)\s*[:\-]\s*(.+)$', ln, re.I)
            if m_tb:
                wkt["tiebreak"] = m_tb.group(1).strip()
                break

    # Detecta progressão de reps por round: '*Add N reps each round' /
    # '*Acrescentar N reps a cada round' / '+N reps por round'.
    # Movimentos marcados com '*' sufixo progridem; sem markers, aplica geral.
    m_prog = (re.search(r'\*\s*(?:add|acrescent[ae]r?|adicione)\s+(\d+)\s+reps?\s+(?:each|a\s+cada|por)\s+round', full, re.I)
              or re.search(r'\*\s*\+\s*(\d+)\s+reps?\s+(?:each|a\s+cada|por)\s+round', full, re.I)
              or re.search(r'(?:add|acrescent[ae]r?|adicione)\s+(\d+)\s+reps?\s+(?:each|a\s+cada|por)\s+round', full, re.I))
    if m_prog:
        try: wkt["reps_delta_por_round"] = int(m_prog.group(1))
        except ValueError: pass
    # Diretriz adicional: último round vira MAX / AMRAP.
    # Ex: 'last round max', 'último round MAX', 'final round AMRAP', 'last MAX'.
    if re.search(r'(?:last|[úu]ltimo|final)\s+round\s+(?:is\s+)?(?:max|amrap)', full, re.I) \
       or re.search(r'(?:last|[úu]ltimo|final)\s+(?:round\s+)?(?:max|amrap)\s+reps?', full, re.I) \
       or re.search(r'(?:round|rd)\s*\d+\s*[:=]\s*(?:max|amrap)', full, re.I):
        wkt["ultimo_round_max"] = True

    # Movimentos, separadores, time cap
    movs: list[Movimento] = []
    block = 1
    has_seps = any(re.match(r'^then\.+$', l, re.I) for l in lines)
    skip_prefixes = ('for time', 'por tempo', 'amrap', 'as many reps', 'rest',
                     'atenção', 'atencao', 'obs', 'note', '"', '“')
    # 'Simultaneous buy-in:' marca início de bloco paralelo (vários movimentos
    # executados ao mesmo tempo por atletas diferentes). 'After both' / 'then...'
    # encerram o bloco paralelo.
    in_paralelo = False
    paralelo_re = re.compile(r'^\s*(?:simultaneous(?:ly)?|paralelo|simultaneamente|'
                              r'simultane[oa])\b.*:\s*$', re.I)
    fim_paralelo_re = re.compile(r'^\s*(?:after\s+both|after\s+all|then|ap[óo]s\s+(?:os\s+)?'
                                  r'(?:dois|todos|ambos))\b', re.I)

    for line in lines:
        ll = line.lower()
        tc = re.search(r'time\s*cap[:\s]+(\d+)\s*min', line, re.I)
        if tc: wkt["time_cap"] = f"{tc.group(1)} min"; continue
        if re.match(r'^then[\.\s]*$', line, re.I):
            if movs: movs.append({"separador": "then..."})
            block += 1
            in_paralelo = False
            continue
        # Inicio de bloco paralelo: marca movs seguintes como paralelo
        if paralelo_re.match(line):
            in_paralelo = True
            continue
        # Fim de paralelo (mas mantém na lista de movs — só sai do modo)
        if fim_paralelo_re.match(line):
            in_paralelo = False
            # Não consome a linha — pode ter movimento depois "After both: 21 Pull-Ups"
        if any(ll.startswith(p) for p in skip_prefixes): continue
        # Marca movimento progressivo. Aceita vários markers comuns:
        #   sufixo no fim:           '10 Burpees*'
        #   antes do (athletes):     '10 Burpees* (2 athletes)'
        #   após o (athletes):       '10 Burpees (2 athletes)*'
        #   inline:                  '10 Burpees (prog)'
        # Símbolos aceitos: '*', '★', '↑', '↗' (Excel pode autocorrigir '*')
        s_strip = line.strip()
        # Marker no fim, opcionalmente seguido de (texto) no fim
        end_marker = re.search(r'[*★↑↗](?:\s*\([^)*]*\))?\s*$', s_strip)
        inline_marker = re.search(r'\((?:prog|progressivo|progressive|\+)\)\s*$', s_strip, re.I)
        is_progressivo = bool(end_marker) or bool(inline_marker)
        # Remove o marker antes do parse_mov_line (não polui o nome).
        # Cuidado: '*Add 2 reps each round' começa com '*' — só remove markers
        # que NÃO estão no início (esses são directives).
        line_clean = line
        if not line_clean.lstrip().startswith(('*', '★', '↑', '↗')):
            line_clean = re.sub(r'[*★↑↗](?=\s|\(|$)', '', line_clean)
        line_clean = re.sub(r'\((?:prog|progressivo|progressive|\+)\)\s*$', '', line_clean, flags=re.I).rstrip()
        # Pula a linha-diretriz `*Add N reps each round` (já capturada acima)
        if re.match(r'^\s*\*?\s*(?:add|acrescent[ae]r?|adicione|\+)\s+\d+\s+reps?\s+(?:each|a\s+cada|por)\s+round', line_clean, re.I):
            continue
        parsed = _parse_mov_line(line_clean)
        if parsed:
            reps, nome = parsed
            # Extrai carga (peso) se vier no fim do nome — aplica a qualquer tipo
            nome_limpo, carga = _extrair_carga(nome)
            mov: Movimento = {"nome": nome_limpo}
            if reps is not None: mov["reps"] = reps
            if carga: mov["carga"] = carga
            if has_seps and block in BLOCK_LABELS: mov["label"] = BLOCK_LABELS[block]
            if in_paralelo: mov["paralelo"] = True
            if is_progressivo: mov["progressivo"] = True
            movs.append(mov)

    if wkt["tipo"] == "for_time" and movs:
        movs.append({"chegada": True})
    wkt["movimentos"] = movs

    # Aplica progressão de reps APENAS aos movs com '*' explícito.
    # Sem markers, a directive '*Add N reps each round' é ignorada — evita
    # progredir Swim/Thrusters quando só Burpees tem '*' (Monstar Recap).
    delta = wkt.get("reps_delta_por_round", 0)
    ultimo_max = wkt.get("ultimo_round_max", False)
    if delta and movs:
        n_rounds = wkt.get("emom_rounds") or wkt.get("n_rounds") or 5
        for m in movs:
            if m.get("chegada") or m.get("separador"): continue
            if not m.get("progressivo"): continue   # strict: só os marcados
            base = m.get("reps")
            if not isinstance(base, int): continue
            seq: list = [base + i * delta for i in range(n_rounds)]
            if ultimo_max and seq: seq[-1] = 'MAX'
            m["reps_por_round"] = seq
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
def _inferir_modalidade(nome_categoria: str) -> str:
    """Infere a modalidade ('individual'|'dupla'|'trio'|'quarteto'|'time') a
    partir do nome da categoria. Usado pelo renderer pra escolher labels
    ('Nome do Atleta' vs 'Nome do Trio' etc).

    Heurística por palavra-chave em PT-BR e EN. Ordem importa — checa
    palavras mais específicas antes (quarteto antes de time/equipe).
    """
    s = (nome_categoria or '').lower()
    if 'quarteto' in s or 'quartet' in s:    return 'quarteto'
    if 'trio' in s:                          return 'trio'
    if 'dupla' in s or ' pair' in s or 'pairs' in s: return 'dupla'
    if 'time' in s or 'team' in s or 'equipe' in s:  return 'time'
    return 'individual'


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

    Quando há aba `Equipamento(s)`/`Equipment`, aplica as anilhas + unidade
    globais a todos os workouts For Load do evento.
    """
    if not HAS_EXCEL:
        raise RuntimeError("openpyxl não disponível — instale com: pip install openpyxl")
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)

    # Formato multi-dia: aba `Workouts` + abas `<Dia>` e `<Dia> - Montagem`
    if _is_evento_multidia(wb):
        result = parse_excel_multidia(wb)
    elif _is_layout_grades_e_dias(wb):
        # Grades-por-modalidade: 1+ abas grade (ex: Individuais, Duplas, Times)
        # + abas <Dia> e <Dia> - Montagem (sem aba unificada Workouts)
        result = parse_excel_grades_e_dias(wb)
    else:
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
            result = _adaptar_categoria_grid_para_multidia(
                evento_nome, todas_categorias, atletas_por_categoria,
            )
        else:
            # Fallback final: formato template (1 evento, lista plana de workouts)
            template_result = _parse_excel_template(wb)
            if not template_result.get('workouts') and not template_result.get('evento', {}).get('nome'):
                # Nenhum formato reconhecido: erro explícito é melhor que
                # estrutura fantasma "Único / Geral" que confunde a UI.
                return {'tipo': 'erro', 'erro': 'Excel sem dados reconhecíveis — esperava grade categoria×workout, formato multi-dia, ou template Evento+WKT.'}
            result = _adaptar_template_para_multidia(template_result)

    # Aba Equipamento: aplica anilhas + unidade globais a todos os For Load
    equip = _parse_equipamento(wb)
    if equip:
        result['equipamento'] = equip
        result['unidade_default'] = equip['unidade']
        _aplicar_equipamento_a_for_load(result, equip)
    return result


def _aplicar_equipamento_a_for_load(result: dict[str, Any], equip: dict[str, Any]) -> None:
    """Itera dias→categorias→workouts e injeta anilhas + unidade nos For Load.

    Só seta se o workout ainda não tiver valor explícito — config manual
    posterior (no front) sobrescreve.
    """
    anilhas = equip['anilhas']
    unidade = equip['unidade']
    for dia in result.get('dias', []) or []:
        for cat in dia.get('categorias', []) or []:
            for wkt in cat.get('workouts', []) or []:
                if wkt.get('tipo') != 'for_load': continue
                wkt.setdefault('anilhas', anilhas)
                wkt.setdefault('unidade', unidade)


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
    """Lê atletas de abas dedicadas (Atleta(s), Inscritos, Athletes, Participants).

    Antes varria toda aba procurando coluna 'Nome' — frágil, pegava header
    'Nome' da Montagem (que tem N blocos repetidos) e contaminava o roster.
    Agora filtra por nome de aba pra ser explícito sobre intenção do usuário.

    Retorna dict { categoria: [ {nome, box, raia, bateria, numero}, ... ] }.
    """
    # Prefixos/substrings que indicam aba de atletas. Tolera variações como
    # 'Atletas - Individuais', 'Inscritos', 'Athletes (RX)', etc.
    ATLETA_SHEET_KEYWORDS = (
        'atleta', 'atletas', 'inscritos', 'athletes', 'participants', 'participantes',
    )

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

    def eh_aba_de_atletas(sname: str) -> bool:
        sl = sname.strip().lower()
        return any(kw in sl for kw in ATLETA_SHEET_KEYWORDS)

    resultado: dict[str, list[Atleta]] = {}

    for sname in wb.sheetnames:
        if not eh_aba_de_atletas(sname):
            continue
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
        modalidade = _inferir_modalidade(cat_nome)
        workouts: list[Workout] = []
        for row_num, row in enumerate(rows[1:], 1):
            if cat_idx >= len(row) or row[cat_idx] is None: continue
            cell_text = str(row[cat_idx]).strip()
            if not cell_text: continue
            # Extrai 'Arena: <nome>' antes de parsear pra evitar que vire o nome
            # do workout. parse_workout_text pega a primeira linha como nome —
            # se a 1ª linha for 'Arena: HeleFitness', sem essa extração o nome
            # vira 'ARENA: HELEFITNESS' em vez do nome real (próxima linha).
            arena, texto_limpo = _extrair_arena(cell_text)
            wkt = parse_workout_text(texto_limpo, row_num)
            if arena:
                wkt['arena'] = arena
            wkt['modalidade'] = modalidade   # inferido do nome da categoria
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
                    except (ValueError, TypeError): mov["reps"] = v
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


def _detectar_blocos_cronograma(header_row: list[str]) -> list[dict[str, int | None]]:
    """Procura TODAS as ocorrências de 'categoria' numa linha de header.

    Cada ocorrência define um bloco (arena). Pra cada bloco, identifica colunas
    auxiliares (eventos, bateria, aquecimento, fila) à esquerda e direita
    delimitadas pela próxima 'categoria' (se houver).
    """
    cat_cols = [i for i, h in enumerate(header_row) if h == 'categoria']
    if not cat_cols:
        return []
    blocos: list[dict[str, int | None]] = []
    for k, col_cat in enumerate(cat_cols):
        # Limites do bloco: do próximo 'categoria' anterior (ou 0) até o próximo (ou fim)
        lo = cat_cols[k - 1] + 1 if k > 0 else 0
        hi = cat_cols[k + 1] if k + 1 < len(cat_cols) else len(header_row)
        # Procura colunas auxiliares dentro do range [lo, hi)
        sub = header_row[lo:hi]

        def _find_in_sub(*names: str) -> int | None:
            for off, h in enumerate(sub):
                if h in names:
                    return lo + off
            return None

        blocos.append({
            'eventos':     _find_in_sub('eventos'),
            'categoria':   col_cat,
            'bateria':     _find_in_sub('bateria'),
            'aquecimento': _find_in_sub('aquecimento'),
            'fila':        _find_in_sub('fila'),
        })
    return blocos


def _parse_cronograma_dia(ws) -> list[dict[str, Any]]:
    """Lê uma aba de cronograma (`Sexta`, `Sábado`, `Domingo`).

    Suporta N arenas em colunas paralelas no mesmo dia. Cada arena tem seu
    próprio conjunto de colunas `Eventos | Categoria | Bateria | Aquecimento | Fila`.

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
    blocos = _detectar_blocos_cronograma(header)
    if not blocos:
        return []

    baterias: list[dict[str, Any]] = []
    # Cada bloco tem seu próprio 'codigo_atual' sticky (arenas não compartilham)
    codigo_atual_por_bloco = [""] * len(blocos)

    for row in rows[header_idx + 1:]:
        if not row:
            continue
        for bidx, bloco in enumerate(blocos):
            col_cat = bloco['categoria']
            col_bat = bloco['bateria']
            if col_cat is None or col_bat is None:
                continue
            cat_val = row[col_cat] if col_cat < len(row) else None
            bat_val = row[col_bat] if col_bat < len(row) else None
            if not cat_val or bat_val is None:
                continue

            # codigo sticky por bloco
            col_ev = bloco['eventos']
            if col_ev is not None and col_ev < len(row):
                ev_val = row[col_ev]
                if ev_val:
                    codigo_atual_por_bloco[bidx] = str(ev_val).strip()

            col_aq = bloco['aquecimento']
            col_fl = bloco['fila']
            baterias.append({
                'numero': str(bat_val).strip(),
                'codigo_evento': codigo_atual_por_bloco[bidx],
                'categoria': str(cat_val).strip(),
                'horario_aquecimento': _fmt_horario(row[col_aq]) if col_aq is not None and col_aq < len(row) else "",
                'horario_fila': _fmt_horario(row[col_fl]) if col_fl is not None and col_fl < len(row) else "",
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


def _detectar_blocos_montagem(valores_linha: list[str]) -> list[dict[str, int | None]]:
    """Procura TODAS as ocorrências de 'raia' numa linha e identifica colunas
    relacionadas (numero, nome, box) à direita de cada uma.

    Suporta arenas paralelas (múltiplos blocos lado a lado na mesma aba).
    Retorna lista de dicts {'raia', 'numero', 'nome', 'box'} com posições.
    """
    blocos: list[dict[str, int | None]] = []
    n = len(valores_linha)
    for col_raia, v in enumerate(valores_linha):
        if v != 'raia':
            continue
        # 'nome' deve aparecer até 4 colunas à direita de 'raia'
        col_nome = None
        for off in range(1, min(5, n - col_raia)):
            if valores_linha[col_raia + off] == 'nome':
                col_nome = col_raia + off
                break
        if col_nome is None:
            continue
        col_numero = None
        for off in range(1, col_nome - col_raia):
            if valores_linha[col_raia + off] in ('número', 'numero'):
                col_numero = col_raia + off
                break
        col_box = None
        for off in range(1, min(4, n - col_nome)):
            if valores_linha[col_nome + off] == 'box':
                col_box = col_nome + off
                break
        blocos.append({'raia': col_raia, 'numero': col_numero,
                       'nome': col_nome, 'box': col_box})
    return blocos


def _parse_montagem_dia(ws) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    """Lê uma aba `<Dia> - Montagem`. Suporta N arenas paralelas (blocos lado a lado).

    Estrutura repetida por bateria (1+ blocos por linha):
        L1: [horário, nº_bateria, ...]    L1: [horário_arena2, nº_bat2, ...]
        L2: [codigo, categoria, ...]      L2: [codigo_arena2, categoria_arena2, ...]
        L3: ["Raia", "Número", "Nome", "Box"]   L3: ["Raia", ..., "Box"]
        L4..N: dados de raia              L4..N: dados de raia

    Retorna dict mapeando (codigo_evento, categoria, numero_bateria) → lista de
    alocações (raia, numero, nome, box). Raias com nome `#N/A` são puladas.
    """
    rows = list(ws.iter_rows(values_only=True))
    resultado: dict[tuple[str, str, str], list[dict[str, Any]]] = {}

    i = 0
    while i < len(rows):
        row = rows[i]
        if not row:
            i += 1
            continue
        valores = [str(c).strip().lower() if c else "" for c in row]
        blocos = _detectar_blocos_montagem(valores)
        if not blocos:
            i += 1
            continue

        # Pra cada bloco detectado nessa linha, lê metadata 1-2 linhas acima
        # e processa as alocações abaixo. Suporta 2 layouts:
        #   Layout A (Sun Challenge):
        #     L-2: [horário, nº_bateria]
        #     L-1: [#N (código de evento), categoria]
        #   Layout B (Monstar — sem código de evento, com arena+workout no topo):
        #     L-3: [Arena: ...]
        #     L-2: [horário, nome_workout]
        #     L-1: [nº_bateria, categoria]
        # Detecção: se L-1 col[col_raia] começa com '#' → Layout A.
        for bloco in blocos:
            col_raia = bloco['raia']
            col_numero = bloco['numero']
            col_nome = bloco['nome']
            col_box = bloco['box']

            def _cell(r, c):
                return r[c] if (r is not None and c is not None and c < len(r)) else None

            prev = rows[i - 1] if i >= 1 else None
            prev2 = rows[i - 2] if i >= 2 else None
            v_acima_0 = _cell(prev, col_raia)
            v_acima_1 = _cell(prev, col_raia + 1)
            v_acima2_0 = _cell(prev2, col_raia)
            v_acima2_1 = _cell(prev2, col_raia + 1)

            s_acima_0 = str(v_acima_0).strip() if v_acima_0 is not None else ""
            eh_layout_sun = s_acima_0.startswith('#') or re.match(r'^(?:wkt|workout)\b', s_acima_0, re.I)

            if eh_layout_sun:
                # Sun: L-1 = (codigo, categoria), L-2 = (_, bateria)
                codigo    = s_acima_0
                categoria = str(v_acima_1).strip() if v_acima_1 is not None else ""
                numero_bat = str(v_acima2_1).strip() if v_acima2_1 is not None else ""
            else:
                # Monstar: L-1 = (bateria, categoria), L-2 = (_, workout_name)
                # Usa o nome do workout como 'codigo' (sem '#') pra fins de matching.
                numero_bat = s_acima_0
                categoria  = str(v_acima_1).strip() if v_acima_1 is not None else ""
                codigo     = str(v_acima2_1).strip() if v_acima2_1 is not None else ""

            alocacoes: list[dict[str, Any]] = []
            j = i + 1
            while j < len(rows):
                r = rows[j]
                if r is None:
                    break
                raia_v = _cell(r, col_raia)
                # Bloco acaba quando a coluna raia fica vazia nesse bloco
                if raia_v is None:
                    break
                # Ou quando aparece novo header (raia/nome) nessa coluna
                vals_j = [str(c).strip().lower() if c else "" for c in r]
                if col_raia < len(vals_j) and vals_j[col_raia] == 'raia':
                    break
                nome_v = _cell(r, col_nome)
                if nome_v is None:
                    j += 1
                    continue
                nome_str = str(nome_v).strip()
                if not nome_str or nome_str.upper() == '#N/A':
                    j += 1
                    continue
                num_v = _cell(r, col_numero)
                box_v = _cell(r, col_box)
                alocacoes.append({
                    'raia':   str(raia_v).strip(),
                    'numero': str(num_v).strip() if num_v is not None else "",
                    'nome':   nome_str,
                    'box':    str(box_v).strip() if box_v is not None else "",
                })
                j += 1

            if alocacoes:
                resultado[(codigo, categoria, numero_bat)] = alocacoes

        i += 1   # avança 1; loop natural pula linhas já processadas (col raia já não é 'raia')

    return resultado


# Parênteses que rotulam bateria/heat — removidos na normalização estrita.
# Cobre: '(Heat 1)', '(Heat 2-3)', '(Heats)', '(Single Heat)', '(Final Heat)'.
_HEAT_PAREN_RE = re.compile(
    r'\s*\((?:single heat|final heat|heat\s*[\d\-/]*|heats?)\)\s*',
    re.I,
)


def _normalizar_categoria(s: str) -> str:
    """Normaliza nome de categoria pra comparação — remove sufixos de bateria.

    Tira só `(Heat N)`, `(Single Heat)`, `(Final Heat)` etc. — parênteses que
    rotulam bateria no cronograma mas não fazem parte do nome da categoria.
    Preserva descritores livres como `(identico ao amador)` ou `(Iniciante)`
    que diferenciam categorias distintas dentro do mesmo evento.
    """
    if not s:
        return ""
    s = _HEAT_PAREN_RE.sub(' ', s)
    s = re.sub(r'\s+', ' ', s).strip().lower()
    s = s.replace('begginer', 'beginner')
    return s


def _normalizar_categoria_relaxada(s: str) -> str:
    """Versão relaxada: remove TODOS os parênteses, não só os de heat.

    Usada como fallback no match. Útil quando a grade tem descritor extra
    (ex: 'Master 35-39 (identico ao amador)') que o cronograma não repete.
    Só deve ser aplicada quando não há ambiguidade — duas categorias da grade
    com mesma versão relaxada precisam ser desambiguadas pelo nome cheio.
    """
    if not s:
        return ""
    s = re.sub(r'\s*\([^)]*\)\s*', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip().lower()
    s = s.replace('begginer', 'beginner')
    return s


def _split_codigo_evento(codigo: str) -> list[str]:
    """Quebra um código tipo '#2 & #3' em ['#2', '#3']. Códigos simples viram [codigo]."""
    if not codigo:
        return []
    return [p.strip() for p in re.split(r'\s*&\s*', codigo) if p.strip()]


def _workout_numero_de_codigo(codigo: str) -> int | None:
    """Extrai o número do workout. Aceita '#1', '#02', 'WKT 4', 'Workout 04'.

    Exige prefixo explícito ('#', 'WKT' ou 'Workout') pra evitar pegar dígito
    de texto qualquer (ex: 'Bat 12' não deve virar workout 12).
    """
    m = re.match(r'^\s*(?:#|wkt|workout)\s*(\d+)\s*$', codigo, re.I)
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


def _bateria_casa_categoria(
    bateria_categoria: str,
    cat_grade_norm: str,
    cat_grade_relaxada: str | None = None,
    permite_relaxado: bool = False,
) -> bool:
    """Match exato (após normalização e quebra de '&').

    Substring causa falso positivo entre 'Rx Masculino' (Sábado) e 'Dupla Rx
    Masculino' (Domingo) — categorias diferentes que rodam em dias diferentes.

    Fallback relaxado (sem parênteses) só roda quando `permite_relaxado=True`,
    o que o caller deve passar apenas se a categoria não colide com outra.
    """
    partes = _quebrar_categoria_composta(bateria_categoria)
    if cat_grade_norm in partes:
        return True
    if permite_relaxado and cat_grade_relaxada:
        partes_relax = [_normalizar_categoria_relaxada(p)
                        for p in re.split(r'\s+&\s+', bateria_categoria) if p.strip()]
        if cat_grade_relaxada in partes_relax:
            return True
    return False


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
    """Lê abas com lista de atletas/duplas/trios.

    Aceita 3 padrões de nome:
      - `Atletas` ou `Atleta` (puro)
      - `Atleta - X` / `Atletas - X` (Sun Challenge style: separado por tipo)
      - `Athletes` / `Athlete` (inglês)

    Estrutura esperada: col A = número, col B = nome, col C = box. Sem header.
    """
    out: list[dict[str, str]] = []
    for sname in wb.sheetnames:
        sl = sname.lower().strip()
        eh_atletas = (
            sl in ('atleta', 'atletas', 'athlete', 'athletes')
            or sl.startswith('atleta - ')
            or sl.startswith('atletas - ')
            or sl.startswith('athlete - ')
            or sl.startswith('athletes - ')
        )
        if not eh_atletas:
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


def _parse_equipamento(wb) -> Optional[dict[str, Any]]:
    """Lê aba `Equipamento(s)` / `Equipment` (se houver) → dict com anilhas + unidade.

    Estrutura esperada: header com `Anilha | Peso | Qtd` (ordem livre). Cada
    linha lista um tipo de anilha disponível no evento. O peso pode vir como
    número puro (assume kg) ou com unidade colada/separada (`25kg`, `25 kg`,
    `45lb`, `45 lb`).

    Retorna `{anilhas: [pesos únicos ordenados desc], unidade: 'kg'|'lb'}`
    ou None se a aba não existe ou está vazia. Detecta unidade global do
    evento: se qualquer célula tem 'lb', evento inteiro é lb (assume coerência).
    """
    sname = next((s for s in wb.sheetnames
                  if s.strip().lower() in ('equipamento', 'equipamentos', 'equipment')),
                 None)
    if not sname:
        return None
    ws = wb[sname]
    pesos: set[float] = set()
    unidade = 'kg'
    col_peso_idx: Optional[int] = None
    # Procura header: a linha que tem 'peso' em alguma célula
    header_row: Optional[int] = None
    for ri, row in enumerate(ws.iter_rows(values_only=True)):
        if ri > 10: break
        for ci, c in enumerate(row):
            if c and str(c).strip().lower() == 'peso':
                col_peso_idx = ci
                header_row = ri
                break
        if col_peso_idx is not None: break
    if col_peso_idx is None:
        # Fallback: assume Anilha=A, Peso=B, Qtd=C e tenta a partir da linha 2
        col_peso_idx = 1
        header_row = 0
    # Lê valores da coluna Peso a partir da linha seguinte ao header
    for ri, row in enumerate(ws.iter_rows(values_only=True)):
        if ri <= header_row: continue
        if col_peso_idx >= len(row): continue
        cell = row[col_peso_idx]
        if cell is None or cell == '': continue
        s = str(cell).strip().lower()
        if 'lb' in s: unidade = 'lb'
        # Extrai número (aceita '25', '25kg', '25 kg', '2,5', '2.5kg')
        m = re.match(r'^([\d]+(?:[\.,]\d+)?)', s)
        if not m: continue
        try:
            peso = float(m.group(1).replace(',', '.'))
        except ValueError:
            continue
        if peso > 0:
            pesos.add(peso)
    if not pesos:
        return None
    # Heurística: se a unidade não veio explícita ('45', '35'), tenta inferir.
    # 45 e 55 são anilhas icônicas em lb (não existem em kg padrão).
    # 1.25 e 2.5 são fracionárias típicas de kg.
    if unidade == 'kg':   # default — só re-avalia se ninguém escreveu 'kg'/'lb'
        tem_lb_typical = any(p in (45, 55) for p in pesos)
        tem_kg_typical = any(p in (1.25, 2.5) for p in pesos)
        if tem_lb_typical and not tem_kg_typical:
            unidade = 'lb'
    return {
        'anilhas': sorted(pesos, reverse=True),
        'unidade': unidade,
    }


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
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Particiona alocações: as que caem em [ini, fim] vs as que ficam fora.

    Retorna (mantidas, descartadas). Alocações sem `numero` numérico vão pra
    descartadas — não há como saber a qual categoria pertencem.
    """
    ini, fim = faixa
    mantidas: list[dict[str, Any]] = []
    descartadas: list[dict[str, Any]] = []
    for a in alocs:
        try:
            n = int(str(a.get('numero', '')).strip())
        except (ValueError, AttributeError):
            descartadas.append(a)
            continue
        if ini <= n <= fim:
            mantidas.append(a)
        else:
            descartadas.append(a)
    return mantidas, descartadas


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

    # Detecta categorias da grade com mesma "relaxada" — match relaxado é
    # ambíguo nesse caso e não pode ser usado como fallback. Ex: se aparecer
    # 'Rx Misto (Iniciante)' e 'Rx Misto (Avançado)' na mesma grade, as duas
    # têm relaxada 'rx misto' → match relaxado proibido pra essas.
    cats_grade_relaxadas = {cat: _normalizar_categoria_relaxada(cat)
                            for cat in grade_por_categoria}
    _contagem_relaxada: dict[str, int] = {}
    for r in cats_grade_relaxadas.values():
        _contagem_relaxada[r] = _contagem_relaxada.get(r, 0) + 1
    cats_ambiguas = {cat for cat, r in cats_grade_relaxadas.items()
                     if _contagem_relaxada[r] > 1}

    # 2) Dias detectados — em ordem de preferência:
    #    (a) abas <Dia> que TÊM par <Dia> - Montagem (atletas alocados)
    #    (b) abas <Dia> sozinhas (planejamento; gera súmulas em branco)
    # Aceita dias da semana em PT-BR ou EN, ou qualquer nome de aba que não
    # seja meta (Inscritos, Atletas, Heats, etc).
    nomes_lower = {s.lower(): s for s in wb.sheetnames}
    META_SHEETS = {
        'inscritos', 'categorias', 'atletas', 'atleta', 'athletes', 'athlete',
        'heats', 'time caps', 'timecaps', 'equipamento', 'equipamentos',
    }
    dias_com_montagem: list[str] = []
    for sname in wb.sheetnames:
        sl = sname.lower()
        if sl.endswith(' - montagem'):
            dia_sl = sl[: -len(' - montagem')]
            if dia_sl in nomes_lower:
                dias_com_montagem.append(nomes_lower[dia_sl])
    # Dias sem montagem: qualquer aba que pareça ser um dia mas não tem par
    dias_sem_montagem: list[str] = []
    for sname in wb.sheetnames:
        sl = sname.lower().strip()
        if sl in META_SHEETS: continue
        if sl.endswith(' - montagem'): continue
        if any(p in sl for p in ('workouts', 'inscritos', 'roster')): continue
        if nomes_lower.get(sname.lower()) in dias_com_montagem: continue
        # Heurística: aba é dia se tem cronograma de baterias — header precisa
        # ter tanto 'categoria' QUANTO 'bateria' nas primeiras linhas. Evita
        # falso positivo com abas tipo 'Finalistas' (Categoria + Place + Number).
        ws = wb[sname]
        for ri, r in enumerate(ws.iter_rows(values_only=True)):
            if ri >= 5: break
            valores = [str(c).strip().lower() if c else "" for c in r]
            if 'categoria' in valores and 'bateria' in valores:
                dias_sem_montagem.append(sname)
                break
    dias_detectados = dias_com_montagem + dias_sem_montagem
    if not dias_detectados:
        return {'tipo': 'erro', 'erro': 'Nenhum dia encontrado — esperava aba <Dia> com cronograma (coluna Categoria) ou par <Dia> + <Dia> - Montagem'}

    # 3-4) Pra cada dia, lê e agrupa categorias presentes
    dias_resultado: list[dict[str, Any]] = []
    avisos_import: list[dict[str, str]] = []
    for dia_label in dias_detectados:
        sname_dia = nomes_lower[dia_label.lower()]
        sname_mont = nomes_lower.get(f"{dia_label.lower()} - montagem")
        cronograma = _parse_cronograma_dia(wb[sname_dia])
        montagem   = _parse_montagem_dia(wb[sname_mont]) if sname_mont else {}
        _propagar_codigos_da_montagem(cronograma, montagem)

        # Conjunto de categorias (normalizadas) presentes neste dia — coleta as
        # duas formas pra suportar match estrito ou relaxado.
        cats_no_dia_norm: set[str] = set()
        cats_no_dia_relax: set[str] = set()
        for b in cronograma:
            cat_str = b.get('categoria', '')
            cats_no_dia_norm.update(_quebrar_categoria_composta(cat_str))
            cats_no_dia_relax.update(
                _normalizar_categoria_relaxada(p)
                for p in re.split(r'\s+&\s+', cat_str) if p.strip()
            )

        cats_resultado: list[dict[str, Any]] = []
        # Tracker de chaves da montagem que foram consumidas via cronograma.
        # As que sobrarem são promovidas a baterias extras no fim do loop —
        # cobre Heat órfão (cronograma incompleto mas montagem com alocação).
        chaves_consumidas: set[tuple] = set()
        for cat_grade, workouts in grade_por_categoria.items():
            cat_grade_norm = _normalizar_categoria(cat_grade)
            cat_grade_relax = cats_grade_relaxadas[cat_grade]
            permite_relax = cat_grade not in cats_ambiguas
            # Só anexa categoria se ela aparece em alguma bateria deste dia
            # (match estrito sempre, relaxado só se categoria não-ambígua)
            if cat_grade_norm not in cats_no_dia_norm and not (
                permite_relax and cat_grade_relax in cats_no_dia_relax
            ):
                continue

            baterias_da_cat = [
                b for b in cronograma
                if _bateria_casa_categoria(b.get('categoria', ''), cat_grade_norm,
                                           cat_grade_relax, permite_relax)
            ]

            baterias_full: list[dict[str, Any]] = []
            for b in baterias_da_cat:
                codigos_b = set(_split_codigo_evento(b.get('codigo_evento', '')))
                bat_cat_exata = b.get('categoria', '')
                # 1ª passada: match estrito (bat + cat + interseção de códigos).
                # 2ª passada: match relaxado (só bat + cat) — só vale quando há um
                #             único candidato (sem ambiguidade).
                # 3ª passada: match por (codigo + categoria exata), ignorando bateria
                #             — pra eventos multi-arena onde cronograma usa bateria
                #             local por arena e montagem usa bateria global. Só vale
                #             quando há único candidato pra essa categoria+código.
                # Cada candidato carrega a chave completa (cod, cat, bat) pra
                # poder marcar como consumida no tracker.
                candidatos_estrito: list[tuple] = []
                candidatos_relaxado: list[tuple] = []
                candidatos_sem_bat: list[tuple] = []
                for chave, alocs in montagem.items():
                    chave_cod, chave_cat, chave_bat = chave
                    cat_bate = _bateria_casa_categoria(
                        chave_cat, cat_grade_norm, cat_grade_relax, permite_relax,
                    )
                    if not cat_bate:
                        continue
                    cat_exata_bate = (
                        chave_cat.strip().lower() == bat_cat_exata.strip().lower()
                    )
                    if chave_bat == b['numero']:
                        candidatos_relaxado.append((chave, alocs))
                        if codigos_b:
                            codigos_chave = set(_split_codigo_evento(chave_cod))
                            if codigos_b & codigos_chave:
                                candidatos_estrito.append((chave, alocs))
                    elif cat_exata_bate and codigos_b:
                        codigos_chave = set(_split_codigo_evento(chave_cod))
                        if codigos_b & codigos_chave:
                            candidatos_sem_bat.append((chave, alocs))
                escolhido = (
                    candidatos_estrito[0] if candidatos_estrito
                    else (candidatos_relaxado[0] if len(candidatos_relaxado) == 1
                          else (candidatos_sem_bat[0] if len(candidatos_sem_bat) == 1 else None))
                )
                if escolhido:
                    chave_escolhida, aloc = escolhido
                    codigo_montagem = chave_escolhida[0]
                    chaves_consumidas.add(chave_escolhida)
                else:
                    codigo_montagem, aloc = "", []

                # Bateria mista (`X & Y`): a Montagem traz atletas das duas
                # categorias juntos. Se temos faixa de número da categoria
                # atual (via Inscritos), filtra pra não vazar atletas da outra.
                if aloc and len(_quebrar_categoria_composta(b.get('categoria', ''))) > 1:
                    # Lookup da faixa: tenta chave estrita (com descritores) e
                    # depois relaxada — Inscritos pode ter nome sem descritor
                    # (ex: 'Master 35-39 Feminino') enquanto a grade tem o
                    # nome completo ('Master 35-39 Feminino (identico ao amador)').
                    faixa = inscritos_faixas.get(cat_grade_norm) or (
                        inscritos_faixas.get(cat_grade_relax) if permite_relax else None
                    )
                    if faixa:
                        aloc, descartados = _filtrar_alocacoes_por_faixa(aloc, faixa)
                        # Aviso só pra atletas que NÃO caem em NENHUMA faixa
                        # conhecida — esses são erros reais (typo no Excel ou
                        # atleta fora da numeração). Atletas descartados que
                        # pertencem a outra categoria conhecida estão no lugar
                        # certo, só não é a categoria sendo processada agora.
                        for d in descartados:
                            n_str = str(d.get('numero', '')).strip()
                            try:
                                n_int = int(n_str)
                            except ValueError:
                                continue   # número inválido — outro problema
                            if any(lo <= n_int <= hi for lo, hi in inscritos_faixas.values()):
                                continue   # pertence a outra categoria conhecida
                            nome = (d.get('nome') or '?').strip() or '?'
                            avisos_import.append({
                                'nivel': 'aviso',
                                'msg':   f'Atleta #{n_str} ({nome}) com número fora de toda faixa do Inscritos — não foi atribuído a nenhuma categoria',
                                'onde':  f'{dia_label}/Bat {b.get("numero", "?")}',
                            })

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

        # Promoção de baterias órfãs: chaves da montagem que ficaram sem match
        # via cronograma (ex: organizador esqueceu de adicionar Heat 2 no
        # cronograma mas registrou as alocações na Montagem). Cada chave órfã
        # vira bateria extra na categoria correspondente da grade.
        for chave, alocs in montagem.items():
            if chave in chaves_consumidas:
                continue
            chave_cod, chave_cat, chave_bat = chave
            partes = _quebrar_categoria_composta(chave_cat)
            # Acha categoria da grade que case com alguma parte dessa chave.
            cat_correspondente = None
            for cat_grade in grade_por_categoria:
                cat_grade_norm = _normalizar_categoria(cat_grade)
                if cat_grade_norm in partes:
                    cat_correspondente = cat_grade
                    break
            if not cat_correspondente:
                continue
            # Pega ou cria a entrada de categoria no resultado
            cat_entry = next((c for c in cats_resultado if c['nome'] == cat_correspondente), None)
            if cat_entry is None:
                cat_entry = {
                    'nome':      cat_correspondente,
                    'workouts':  grade_por_categoria[cat_correspondente],
                    'baterias':  [],
                }
                cats_resultado.append(cat_entry)
            # Filtra alocações se bateria mista + faixa Inscritos disponível
            aloc_final = alocs
            if len(partes) > 1:
                cat_norm = _normalizar_categoria(cat_correspondente)
                faixa = inscritos_faixas.get(cat_norm) or inscritos_faixas.get(
                    _normalizar_categoria_relaxada(cat_correspondente)
                )
                if faixa:
                    aloc_final, _ = _filtrar_alocacoes_por_faixa(alocs, faixa)
            codigos_finais = _split_codigo_evento(chave_cod) or ([chave_cod] if chave_cod else [])
            workouts_que_rodam = [
                n for n in (_workout_numero_de_codigo(c) for c in codigos_finais) if n is not None
            ]
            cat_entry['baterias'].append({
                'numero':              chave_bat,
                'codigo_evento':       chave_cod,
                'categoria':           chave_cat,
                'horario_aquecimento': '',
                'horario_fila':        '',
                'workouts_que_rodam':  workouts_que_rodam,
                'alocacoes':           aloc_final,
            })
            avisos_import.append({
                'nivel': 'aviso',
                'msg':   f'Bateria {chave_bat} ({chave_cat}) tem alocações na Montagem mas não está no cronograma — promovida como bateria extra',
                'onde':  f'{dia_label}/{cat_correspondente}',
            })

        dias_resultado.append({'label': dia_label, 'categorias': cats_resultado})

    return {
        'tipo':         'evento_multidia',
        'evento_nome':  '',
        'dias':         dias_resultado,
        'roster':       _roster_de_abas_atletas(wb),
        'avisos_import': avisos_import,
    }
