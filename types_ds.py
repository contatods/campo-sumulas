"""TypedDicts canônicos pra payloads do sistema.

Usados como anotação em parsers.py, ai_rounds.py e nos handlers — não impõem
runtime checks (é só hint pro editor / mypy / leitores). A validação de tipo
de workout é feita explicitamente em sumula_app._validate_workout_tipos.

Nome do módulo é `types_ds` (não `types`) para não colidir com o stdlib `types`.
"""
from __future__ import annotations
from typing import TypedDict, Union


class Atleta(TypedDict, total=False):
    nome: str
    box: str
    raia: str
    bateria: str
    numero: str
    categoria: str


class Movimento(TypedDict, total=False):
    nome: str
    reps: Union[int, str]
    carga: str          # peso (ex: '50/35 LB', '20 KG', '135 #') — extraído do nome
    label: str
    chegada: bool       # marca a linha de chegada/finish (For Time)
    separador: str      # marca um "then..." entre blocos
    secao: str          # header informativo (ex: 'PART 1 (00:00-06:00)') —
                        # renderiza como banner, não conta reps
    paralelo: bool      # executado simultaneamente com o próximo movimento
                        # (ex: SkiErg ‖ Double-Unders no Simple Dimension)
    progressivo: bool   # reps progridem por round (sufixo '*' no Excel)
    reps_por_round: list[Union[int, str]]   # progressão de reps (ex: [10,12,14,16,'MAX'])
    tiebreak: bool      # checkpoint inline — render insere linha 'TIEBREAK · ___'
                        # após este mov (For Time multi-checkpoint)
    posicao: bool       # movimento de chegada por CORRIDA ('Run to finish'):
                        # o juiz anota a POSIÇÃO em que o time cruzou a linha,
                        # não repetições
    max: bool           # linha 'Max <mov>' — sem reps prescritas, o juiz anota
                        # o acumulado (render dá caixa em vez de nº de reps)
    pontua: bool        # este movimento é o que gera pontuação do workout
    executantes: str    # quem do time executa ('A/B') — vem do sufixo
                        # '– Athletes A and B'. Render mostra como badge.


class Score(TypedDict, total=False):
    """Uma das pontuações independentes de um workout multi-score.

    Um workout pode valer mais de um score — o organizador declara cada um na
    seção Pontuação com um rótulo: `Fire Burning 1 (Score A): reps de thruster
    do Bloco 1 (100 pontos)`. Workout de pontuação única não tem `scores`.
    """
    label: str          # rótulo curto do score ('A', 'B', 'C')
    nome: str           # nome dado pelo organizador ('Fire Burning 1')
    tipo: str           # 'reps' | 'tempo' | 'carga' — o que o juiz anota
    descricao: str      # texto livre do critério, como escrito no Excel
    pontos: int         # peso do score no ranking (ex: 100, 200)


class Formula(TypedDict, total=False):
    janela: str         # ex: "00:00 → 05:00  ·  AMRAP 5 MIN"
    descricao: list[str]
    movimentos: list[Movimento]
    n_rounds: int       # calculado por enriquecer_workouts


class Workout(TypedDict, total=False):
    numero: int
    numero_f2: int      # Express ocupa 2 slots (numero e numero_f2)
    nome: str
    tipo: str           # 'for_time' | 'for_time_goal' | 'amrap' | 'express' |
                        # 'for_load' | 'composto' | 'eliminacao' (cf. WORKOUT_TIPOS)
    estilo: str         # alias de tipo, mantido por compat com template
    modalidade: str     # 'individual' | 'dupla' | 'time'
    time_cap: str
    descricao: list[str]
    movimentos: list[Movimento]   # for_time / amrap
    formula1: Formula             # express
    formula2: Formula             # express
    arena: str
    data: str
    n_rounds: int                 # calculado para AMRAP
    # For Load
    tentativas: int               # nº de tentativas (default 3) — POR ATLETA em team
    unidade: str                  # 'kg' | 'lb' (herda do evento)
    barra_masculina: float        # peso da barra M (default 20kg / 45lb)
    barra_feminina: float         # peso da barra F (default 15kg / 35lb)
    anilhas: list[float]          # pesos disponíveis (ordenados grande→pequeno)
    n_atletas_time: int           # override do default de modalidade (3 trio, 4 quarteto)
    # Relay / EMOM / Tiebreak
    rounds_per_atleta: int        # For Time relay (N rounds = N atletas em sequência)
    rounds_fixos: int             # 'X rounds for time' — atleta repete sequência X vezes
    emom_janela: str              # ex '2:30' — janela de cada round EMOM
    emom_rounds: int              # nº de rounds EMOM
    tiebreak_por_round: bool      # mostra campo de tiebreak em cada round
    paralelo: bool                # quando movimento é executado simultaneamente
    # For Time Goal (Simple Dimension / Simple Mind):
    goal_reps: int                # alvo total de reps acumuladas pra liberar chegada
    goal_movimento: str           # nome do movimento alvo (ex 'SNATCHES')
    goal_carga: str               # carga do movimento alvo (ex '75 LB', '75/55 LB')
    # Multi-score: workout que vale 2+ pontuações independentes (ver Score).
    # Ausente/vazio = pontuação única, e o render usa o score_box do tipo.
    scores: list[Score]
    # Eliminação ('5 rounds, every 3 minutes' + corte por round): cada round
    # tem janela própria e os últimos a cruzar a linha saem. O que pontua é a
    # ordem de chegada, e quem foi eliminado é classificado pelo round de saída.
    janela_round: str             # janela de cada round (ex: '3', '2:30')
    eliminados_por_round: int     # quantos times saem a cada round


class Evento(TypedDict, total=False):
    nome: str
    categoria: str
    data: str
    logo_empresa: str   # data:image/... base64 ou caminho local
    logo_evento: str    # idem
    unidade_default: str  # 'kg' | 'lb' — herdada pelos workouts For Load


# Defaults pra For Load (centralizados pra serem consistentes)
ANILHAS_KG_DEFAULT: list[float] = [25, 20, 15, 10, 5, 2.5, 1.25]
ANILHAS_LB_DEFAULT: list[float] = [55, 45, 35, 25, 15, 10, 5, 2.5]
BARRA_M_KG: float = 20
BARRA_F_KG: float = 15
BARRA_M_LB: float = 45
BARRA_F_LB: float = 35


def anilhas_default(unidade: str) -> list[float]:
    """Retorna lista padrão de anilhas (ordenadas grande→pequeno) pra unidade."""
    return ANILHAS_LB_DEFAULT if (unidade or '').lower() == 'lb' else ANILHAS_KG_DEFAULT


def barra_default(genero: str, unidade: str) -> float:
    """Retorna peso default da barra pra gênero ('M'|'F') e unidade ('kg'|'lb')."""
    u = (unidade or 'kg').lower()
    g = (genero or 'M').upper()
    if u == 'lb':
        return BARRA_F_LB if g == 'F' else BARRA_M_LB
    return BARRA_F_KG if g == 'F' else BARRA_M_KG


def detectar_genero_categoria(nome_categoria: str) -> str:
    """Retorna 'M', 'F' ou 'MISTO' a partir do nome da categoria.

    Heurística simples por palavras em PT-BR/EN. 'Misto' usa barra masculina
    como default (escolha conservadora — maior carga possível).
    """
    s = (nome_categoria or '').lower()
    if 'misto' in s or 'mixed' in s:
        return 'MISTO'
    if 'feminin' in s or 'female' in s or "women" in s:
        return 'F'
    if 'masculin' in s or 'male' in s or "men" in s:
        return 'M'
    return 'M'   # default conservador


def n_atletas_da_modalidade(modalidade: str) -> int:
    """Quantos atletas individuais cada 'time' tem nessa modalidade.

    Em For Load com modalidade dupla/trio/quarteto, cada atleta do time
    tem suas próprias tentativas (sub-blocos na súmula). Em 'time' genérico,
    default 3 (organizador pode sobrescrever via wkt.n_atletas_time).
    """
    return {
        'individual': 1,
        'dupla':      2,
        'trio':       3,
        'quarteto':   4,
        'time':       3,    # default — sobrescrevível por wkt.n_atletas_time
    }.get((modalidade or 'individual').lower(), 1)
