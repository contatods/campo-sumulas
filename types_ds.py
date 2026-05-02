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
    tipo: str           # 'for_time' | 'amrap' | 'express' (cf. WORKOUT_TIPOS)
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


class Evento(TypedDict, total=False):
    nome: str
    categoria: str
    data: str
    logo_empresa: str   # data:image/... base64 ou caminho local
    logo_evento: str    # idem
