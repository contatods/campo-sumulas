"""ai_rounds.py — estimativa de rounds esperados num AMRAP.

Funções públicas:
    enriquecer_workouts(workouts) -> mutates list
    _extrair_minutos(texto) -> int | None
    _estimar_rounds_algoritmico(movs, duracao_str) -> int   (sem deps externas)
    _estimar_rounds_ia(movs, duracao_str) -> int            (usa Anthropic se ANTHROPIC_API_KEY)

A IA cai no fallback algorítmico se: a key não está setada, o SDK não está
instalado, a chamada estoura timeout ou a resposta é malformada.
"""
from __future__ import annotations

import os
import re
from typing import Optional

from types_ds import Movimento, Workout

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

AI_KEY: str = os.environ.get('ANTHROPIC_API_KEY', '')
AI_ATIVO: bool = HAS_ANTHROPIC and bool(AI_KEY)


def _extrair_minutos(texto: str) -> Optional[int]:
    """Extrai duração em minutos de strings como:
       '10 min', 'AMRAP 5 MIN', '00:00 → 05:00', 'Time Cap: 8 min'
    """
    if not texto: return None
    t = str(texto)
    m = re.search(r'amrap\s+(\d+)\s*min', t, re.I)
    if m: return int(m.group(1))
    m = re.search(r'(\d{1,2}):(\d{2})\s*[→\-]+\s*(\d{1,2}):(\d{2})', t)
    if m:
        s = int(m.group(1)) * 60 + int(m.group(2))
        e = int(m.group(3)) * 60 + int(m.group(4))
        return max(1, (e - s) // 60)
    m = re.search(r'(\d+)\s*min', t, re.I)
    if m: return int(m.group(1))
    return None


def _estimar_rounds_algoritmico(movimentos: list[Movimento], duracao_str: str) -> int:
    """Estimativa baseada em reps totais e tempo disponível (pace 6-10 reps/min).
    Retorna número de linhas a mostrar no scorecard (rounds esperados + buffer).
    """
    mins = _extrair_minutos(duracao_str or '')
    if not mins: return 4
    movs = [m for m in (movimentos or [])
            if not m.get('separador') and not m.get('chegada')]
    reps_round = sum(int(m['reps']) for m in movs if m.get('reps') and str(m['reps']).isdigit())
    if not reps_round: return 4
    pace = 6 if reps_round > 50 else 8 if reps_round > 25 else 10
    rounds_esperados = (mins * pace) / reps_round
    return max(3, round(rounds_esperados) + 2)


def _estimar_rounds_ia(movimentos: list[Movimento], duracao_str: str) -> int:
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


def enriquecer_workouts(workouts: list[Workout]) -> list[Workout]:
    """Calcula campos derivados antes de renderizar.
    - AMRAP: adiciona 'n_rounds' (estimado por IA ou algoritmo)
    - Express F1 (que é AMRAP): idem na formula1
    Modifica a lista in-place e retorna ela.
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
