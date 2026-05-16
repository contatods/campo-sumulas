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
    label: str
    chegada: bool       # marca a linha de chegada/finish (For Time)
    separador: str      # marca um "then..." entre blocos


class Formula(TypedDict, total=False):
    janela: str         # ex: "00:00 → 05:00  ·  AMRAP 5 MIN"
    descricao: list[str]
    movimentos: list[Movimento]
    n_rounds: int       # calculado por enriquecer_workouts


class Workout(TypedDict, total=False):
    numero: int
    numero_f2: int      # Express ocupa 2 slots (numero e numero_f2)
    nome: str
    tipo: str           # 'for_time' | 'amrap' | 'express' | 'for_load' (cf. WORKOUT_TIPOS)
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
    tentativas: int               # nº de tentativas (default 3)
    unidade: str                  # 'kg' | 'lb' (herda do evento)
    barra_masculina: float        # peso da barra M (default 20kg / 45lb)
    barra_feminina: float         # peso da barra F (default 15kg / 35lb)
    anilhas: list[float]          # pesos disponíveis (ordenados grande→pequeno)


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
