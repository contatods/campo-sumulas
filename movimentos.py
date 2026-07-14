"""movimentos.py — dicionário de movimentos canônicos do CrossFit + padronização.

A função pública `padronizar_movimento(nome)` recebe um nome possivelmente
escrito de várias formas e retorna a forma canônica usada nas súmulas.

A maioria dos eventos usa o mesmo conjunto de ~30-40 movimentos clássicos.
Esse dicionário cobre os mais frequentes; movimentos não cadastrados ficam
como vieram (não force).

Também há `padronizar_workouts(workouts)` pra aplicar in-place numa lista,
percorrendo os movimentos de for_time/amrap/express.
"""
from __future__ import annotations

import json
import os
import re
from typing import Iterable, Optional

# Mapa canonical → lista de aliases (case-insensitive). Inclui PT-BR e EN.
MOVIMENTOS_CANONICOS: dict[str, list[str]] = {
    # Ginástica
    'PULL-UPS':              ['pull-up', 'pull up', 'pullup', 'pull ups', 'pullups', 'barra fixa', 'barra'],
    'CHEST-TO-BAR PULL-UPS': ['chest to bar', 'c2b', 'ctb', 'chest-to-bar', 'chest to bar pull-up'],
    'BAR MUSCLE-UPS':        ['bar muscle up', 'bar muscle-up', 'bar mu', 'barra mu'],
    'RING MUSCLE-UPS':       ['ring muscle up', 'ring muscle-up', 'ring mu', 'argola mu', 'muscle-up nas argolas'],
    'MUSCLE-UPS':            ['muscle up', 'muscle-up', 'mu', 'muscleup'],
    'PUSH-UPS':              ['push up', 'push-up', 'pushup', 'push ups', 'flexão', 'flexao', 'flexões'],
    'HANDSTAND PUSH-UPS':    ['hspu', 'handstand push-up', 'handstand push up', 'flexão de cabeça pra baixo'],
    'WALL WALKS':            ['wall walk', 'wall-walk', 'caminhada na parede'],
    'TOES-TO-BAR':           ['toes to bar', 'toes-to-bar', 'ttb', 'pé na barra'],
    'KNEES-TO-ELBOWS':       ['knees to elbow', 'knees-to-elbows', 'k2e', 'joelho ao cotovelo'],
    'PISTOLS':               ['pistol', 'pistols', 'pistol squat'],
    'BURPEES':               ['burpee', 'burpees'],
    'BURPEE BOX JUMP-OVERS': ['burpee box jump over', 'burpee box jump', 'bbjo'],
    'BOX JUMPS':             ['box jump', 'boxjump', 'salto na caixa', 'salto no caixote'],
    'DOUBLE-UNDERS':         ['double under', 'double-unders', 'du', 'corda dupla', 'pula-corda dupla'],
    'SIT-UPS':               ['sit up', 'sit-up', 'situp', 'abdominal'],
    'AIR SQUATS':            ['air squat', 'agachamento livre'],
    'LUNGES':                ['lunge', 'afundo', 'avanço'],
    'ROPE CLIMBS':           ['rope climb', 'rope climbs', 'subida na corda'],

    # Levantamento de peso
    'THRUSTERS':             ['thruster', 'thrusters'],
    'WALL BALLS':            ['wall ball', 'wallball', 'wall-ball', 'medicine ball'],
    'KETTLEBELL SWINGS':     ['kettlebell swing', 'kb swing', 'swing'],
    'CLEANS':                ['clean'],
    'POWER CLEANS':          ['power clean'],
    'HANG CLEANS':           ['hang clean'],
    'SQUAT CLEANS':          ['squat clean'],
    'CLEAN AND JERKS':       ['clean and jerk', 'c&j', 'clean & jerk'],
    'JERKS':                 ['jerk'],
    'SNATCHES':              ['snatch', 'arranco'],
    'POWER SNATCHES':        ['power snatch'],
    'DEADLIFTS':             ['deadlift', 'levantamento terra'],
    'SUMO DEADLIFT HIGH PULLS': ['sdhp', 'sumo deadlift high pull'],
    'FRONT SQUATS':          ['front squat', 'agachamento frontal'],
    'BACK SQUATS':           ['back squat', 'agachamento costas'],
    'OVERHEAD SQUATS':       ['overhead squat', 'ohs', 'agachamento sobre cabeça'],
    'SQUATS':                ['squat', 'agachamento'],
    'PRESSES':               ['shoulder press', 'press'],
    'PUSH PRESSES':          ['push press'],
    'PUSH JERKS':            ['push jerk'],
    'DEVIL PRESSES':         ['devil press', "devil's press"],

    # Cardio
    'ROW (METERS)':          ['row', 'rowing', 'remo', 'remada'],
    'BIKE (CALORIES)':       ['assault bike', 'echo bike', 'bike erg'],
    'RUN':                   ['run', 'running', 'corrida'],
}

# Mapa inverso: alias_lower → canonical
_ALIAS_TO_CANONICAL: dict[str, str] = {}
for canonical, aliases in MOVIMENTOS_CANONICOS.items():
    _ALIAS_TO_CANONICAL[canonical.lower()] = canonical
    for a in aliases:
        _ALIAS_TO_CANONICAL[a.lower()] = canonical


# Prefixos descritivos comuns que NÃO devem afetar o match
# ("Sync." de sincronizado, modificadores de movimento, etc.)
_PREFIX_SYNC = re.compile(r'^(sync\.?|synchronized|sincronizado|alternating|alt\.?)\s+', re.I)


def padronizar_movimento(nome: str) -> str:
    """Tenta encontrar o nome canônico de um movimento.

    Match exato (case-insensitive) primeiro. Se não casa, retorna o nome original.
    Preserva sufixos descritivos (ex: "Pull-Ups (Strict)" mantém "(Strict)").
    Preserva prefixos como "Sync." e "Alternating" no resultado.
    """
    if not nome:
        return nome
    s = str(nome).strip()
    if not s:
        return s

    # Captura prefixo de "Sync." / "Alternating" pra reaplicar depois
    m_pref = _PREFIX_SYNC.match(s)
    prefixo = m_pref.group(0) if m_pref else ''
    base = s[len(prefixo):] if prefixo else s

    # Captura sufixo entre parênteses (ex: "(Strict)", "(@ 32kg)")
    m_suf = re.search(r'\s*(\([^)]+\)|@\s*\S+.*)$', base)
    sufixo = m_suf.group(0) if m_suf else ''
    core = base[: len(base) - len(sufixo)].strip() if sufixo else base.strip()

    canonical = _ALIAS_TO_CANONICAL.get(core.lower())
    if not canonical:
        return s   # sem match, devolve original

    # Reconstrói: prefixo (preservado em caps title) + canônico + sufixo
    if prefixo:
        # padroniza "sync." → "Sync. " e "alternating" → "Alternating "
        pref_norm = prefixo.strip()
        if pref_norm.lower().startswith('sync'):
            pref_norm = 'Sync.'
        elif pref_norm.lower().startswith('alt'):
            pref_norm = 'Alternating'
        prefixo_out = pref_norm + ' '
    else:
        prefixo_out = ''
    sufixo_out = (' ' + sufixo.strip()) if sufixo else ''
    return f"{prefixo_out}{canonical}{sufixo_out}".strip()


def padronizar_workouts(workouts: Iterable[dict]) -> None:
    """Aplica `padronizar_movimento` em todos os movs (in-place).

    Cobre for_time/amrap (movimentos) e express (formula1/formula2.movimentos).
    """
    for wkt in (workouts or []):
        if not isinstance(wkt, dict):
            continue
        for m in (wkt.get('movimentos') or []):
            if isinstance(m, dict) and m.get('nome'):
                m['nome'] = padronizar_movimento(m['nome'])
        for chave in ('formula1', 'formula2'):
            f = wkt.get(chave)
            if isinstance(f, dict):
                for m in (f.get('movimentos') or []):
                    if isinstance(m, dict) and m.get('nome'):
                        m['nome'] = padronizar_movimento(m['nome'])


# ── Vocabulário canônico de movimentos (vendorizado da base Movimentos) ───────
# `movimentos_canonicos.json` é uma CÓPIA dos nomes de canonical_v2.json (produto
# Movimentos). Re-gerar quando aquela base mudar. Usado só pra RECONHECER
# movimento / achar typo — NÃO muda a normalização de display (padronizar_movimento).
def _carregar_vocab_canonico() -> dict[str, str]:
    """norm_key → nome canônico (1º que produz aquela chave). {} se ausente."""
    caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'movimentos_canonicos.json')
    try:
        with open(caminho, encoding='utf-8') as f:
            nomes = json.load(f).get('nomes') or []
    except (OSError, ValueError):
        return {}
    vocab: dict[str, str] = {}
    for n in nomes:
        k = _norm_mov(n)
        if k and k not in vocab:
            vocab[k] = n
    # Inclui também os canônicos internos (uppercase-plural) pra cobrir o que a
    # base externa não tem (Line-Facing Burpee não; mas PULL-UPS sim).
    for canonical in MOVIMENTOS_CANONICOS:
        k = _norm_mov(canonical)
        if k:
            vocab.setdefault(k, canonical.title())
    return vocab


def _norm_mov(nome: str) -> str:
    """Chave de comparação: sem parênteses, sem prefixo Sync./Alt., minúsculo,
    hífen/pontuação → espaço, cada palavra no singular. Simétrico pra vocab e
    movimento — 'Wall-Ball Shots' e 'Wall Ball Shot' produzem a MESMA chave."""
    if not nome:
        return ""
    s = re.sub(r'\s*\([^)]*\)', ' ', str(nome))            # remove (carga)/(2 athletes)
    s = _PREFIX_SYNC.sub('', s)                            # remove 'Sync.'/'Alternating'
    s = s.lower()
    s = re.sub(r'[^a-z0-9à-ÿ]+', ' ', s)                   # hífen/pontuação → espaço (mantém acento)
    palavras = []
    for w in s.split():
        if re.search(r'(ch|sh|x|z|ss)es$', w):            # snatches→snatch, boxes→box, presses→press
            w = w[:-2]
        elif w.endswith('s') and not w.endswith('ss'):    # shots→shot, burpees→burpee, raises→raise
            w = w[:-1]
        palavras.append(w)
    return ' '.join(palavras).strip()


def _levenshtein_mov(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


_VOCAB_MOV: dict[str, str] = _carregar_vocab_canonico()


def checar_movimento_typo(nome: str) -> Optional[tuple[str, str]]:
    """Se `nome` parece TYPO de um movimento conhecido, retorna (nome, sugestão).

    Conservador de propósito: movimento custom legítimo (Hay Bale Burpee, Fat Bar
    Thruster…) fica LONGE de qualquer canônico → não é flaggado. Só dispara em
    quase-igual (distância 1-2, mesmos 3 primeiros caracteres, tamanho parecido).
    Retorna None quando reconhecido OU quando é custom/desconhecido (não-typo).
    """
    core = _norm_mov(nome)
    if not core or len(core) < 4 or not _VOCAB_MOV:
        return None
    if core in _VOCAB_MOV:
        return None                                       # reconhecido
    melhor, melhor_d = None, 99
    for k in _VOCAB_MOV:
        if abs(len(k) - len(core)) > 2 or k[:3] != core[:3]:
            continue
        d = _levenshtein_mov(core, k)
        if d < melhor_d:
            melhor_d, melhor = d, k
    if melhor is not None and 1 <= melhor_d <= 2:
        return (nome, _VOCAB_MOV[melhor])
    return None
