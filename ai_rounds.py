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


# ── Sugestão de Time Cap ───────────────────────────────────────────────────
def sugerir_time_cap(movimentos: list[Movimento], tipo: str = 'for_time') -> str:
    """Sugere um time cap razoável baseado nos movimentos.

    Heurística simples (sem IA): soma o total de reps; aplica pace típico.
    Para AMRAP, retorna duração comum (ex: '15 min').
    """
    if tipo == 'amrap':
        # AMRAP comum: 5-15 min. Default 10.
        return '10 min'
    # For Time / Express: estima por volume de reps
    movs = [m for m in (movimentos or []) if not m.get('separador') and not m.get('chegada')]
    total_reps = sum(int(m.get('reps', 0)) for m in movs
                     if str(m.get('reps', '')).isdigit())
    if not total_reps:
        return '10 min'
    # Pace ~10 reps/min em workouts curtos, ~7 em longos. Add 50% de buffer.
    pace = 10 if total_reps < 50 else 7
    minutos = max(5, int((total_reps / pace) * 1.5))
    # Arredonda pra múltiplos de 5 (cleaner)
    minutos = ((minutos + 2) // 5) * 5 or 5
    return f'{minutos} min'


# ── Geração automática de "Notas adicionais" a partir da tabela ─────────────
def auto_descricao(workout: Workout) -> list[str]:
    """Gera linhas pra `descricao` (notas adicionais) a partir da tabela.

    Não chama IA — é puramente formatação. Resultado é uma lista de strings,
    cada uma vira uma linha no header da súmula.
    """
    tipo = workout.get('tipo', 'for_time')
    linhas: list[str] = []
    if tipo == 'for_time':
        linhas.append('For Time:')
    elif tipo == 'amrap':
        mins = _extrair_minutos(workout.get('time_cap', '') or '') or 10
        linhas.append(f'AMRAP {mins} minutos:')
    # express usa formula1.descricao e formula2.descricao separados; pular aqui
    movs = workout.get('movimentos', []) or []
    for m in movs:
        if m.get('separador'):
            linhas.append(str(m.get('separador') or 'then...').strip() or 'then...')
        elif m.get('chegada'):
            continue  # chegada não vira linha de descrição
        else:
            reps = m.get('reps', '')
            nome = m.get('nome', '').strip()
            label = m.get('label', '').strip()
            linha = f"{reps} {nome}".strip()
            if label:
                linha = f"{linha} ({label})"
            linhas.append(linha)
    tc = workout.get('time_cap', '').strip()
    if tc and tipo == 'for_time':
        linhas.append(f'Time cap: {tc}')
    return linhas


# ── Validação algorítmica de evento ────────────────────────────────────────
def validar_evento(config: dict) -> list[dict]:
    """Detecta problemas pré-evento sem precisar de IA.

    Retorna lista de avisos, cada um com:
      { 'severidade': 'erro'|'aviso', 'msg': str, 'onde': str }

    Cobertura:
      - Atleta/time aparecendo em raias diferentes (duplicado)
      - Bateria com código de evento mas sem alocação
      - Categoria sem workouts
      - Workout sem movimentos
      - Time cap suspeito (muito curto ou vazio em For Time)
    """
    avisos: list[dict] = []
    dias = config.get('dias', []) or []

    # 1) Detectar competidores (por número) em múltiplos lugares
    onde_aparece: dict[str, list[str]] = {}
    for di, dia in enumerate(dias):
        dlabel = dia.get('label', f'Dia {di+1}')
        for ci, cat in enumerate(dia.get('categorias', []) or []):
            cnome = cat.get('nome', f'Cat {ci+1}')
            for b in cat.get('baterias', []) or []:
                for aloc in b.get('alocacoes', []) or []:
                    num = (aloc.get('numero') or '').strip()
                    if not num:
                        continue
                    chave = f"{cnome}#{num}"  # mesma cat + mesmo número = mesmo time
                    pos = f"{dlabel}/{cnome}/Bat{b.get('numero','?')}/raia{aloc.get('raia','?')}"
                    onde_aparece.setdefault(chave, []).append(pos)
    for chave, posicoes in onde_aparece.items():
        if len(posicoes) > 1:
            cat_nome, num = chave.rsplit('#', 1)
            avisos.append({
                'severidade': 'aviso',
                'msg': f'Competidor #{num} aparece em {len(posicoes)} lugares',
                'onde': f'{cat_nome}: {", ".join(posicoes)}',
            })

    # 2) Bateria com código mas sem alocação
    for di, dia in enumerate(dias):
        dlabel = dia.get('label', f'Dia {di+1}')
        for cat in dia.get('categorias', []) or []:
            cnome = cat.get('nome', '')
            for b in cat.get('baterias', []) or []:
                if b.get('codigo_evento') and not (b.get('alocacoes') or []):
                    avisos.append({
                        'severidade': 'aviso',
                        'msg': f'Bateria {b.get("numero")} ({b.get("codigo_evento")}) sem alocações',
                        'onde': f'{dlabel}/{cnome}',
                    })

    # 3) Categoria sem workouts
    for di, dia in enumerate(dias):
        dlabel = dia.get('label', f'Dia {di+1}')
        for cat in dia.get('categorias', []) or []:
            if not (cat.get('workouts') or []):
                avisos.append({
                    'severidade': 'erro',
                    'msg': f'Categoria "{cat.get("nome", "?")}" sem workouts',
                    'onde': dlabel,
                })

    # 4) Workout sem movimentos
    for di, dia in enumerate(dias):
        dlabel = dia.get('label', f'Dia {di+1}')
        for cat in dia.get('categorias', []) or []:
            cnome = cat.get('nome', '')
            for wi, wkt in enumerate(cat.get('workouts', []) or []):
                tipo = wkt.get('tipo', '')
                if tipo == 'express':
                    f1 = wkt.get('formula1', {}) or {}
                    f2 = wkt.get('formula2', {}) or {}
                    if not (f1.get('movimentos') or []) and not (f2.get('movimentos') or []):
                        avisos.append({
                            'severidade': 'aviso',
                            'msg': f'Express "{wkt.get("nome", "?")}" sem movimentos em F1 nem F2',
                            'onde': f'{dlabel}/{cnome}',
                        })
                elif not (wkt.get('movimentos') or []):
                    avisos.append({
                        'severidade': 'aviso',
                        'msg': f'Workout "{wkt.get("nome", "?")}" sem movimentos',
                        'onde': f'{dlabel}/{cnome}',
                    })

    # 5) Time cap suspeito em For Time
    for di, dia in enumerate(dias):
        dlabel = dia.get('label', f'Dia {di+1}')
        for cat in dia.get('categorias', []) or []:
            cnome = cat.get('nome', '')
            for wkt in cat.get('workouts', []) or []:
                if wkt.get('tipo') == 'for_time' and not (wkt.get('time_cap') or '').strip():
                    avisos.append({
                        'severidade': 'aviso',
                        'msg': f'Workout "{wkt.get("nome", "?")}" (For Time) sem time cap',
                        'onde': f'{dlabel}/{cnome}',
                    })
    return avisos


# ── Resumo natural do evento (curto, conciso) ───────────────────────────────
def resumo_evento(config: dict) -> str:
    """Retorna 1-2 frases descrevendo o evento importado.

    Sem IA — só formatação pura. Útil pra mostrar no banner pós-import.
    """
    dias = config.get('dias', []) or []
    if not dias:
        return ''
    n_dias = len(dias)
    cats_set = set()
    n_workouts = 0
    n_competidores = 0
    for d in dias:
        for c in d.get('categorias', []) or []:
            cats_set.add(c.get('nome', ''))
            n_workouts += len(c.get('workouts', []) or [])
            for b in c.get('baterias', []) or []:
                n_competidores += len(b.get('alocacoes', []) or [])
    parts = [f"{n_dias} dia{'s' if n_dias != 1 else ''}",
             f"{len(cats_set)} categoria{'s' if len(cats_set) != 1 else ''}",
             f"{n_workouts} workout{'s' if n_workouts != 1 else ''}"]
    if n_competidores:
        parts.append(f"{n_competidores} competidor{'es' if n_competidores != 1 else ''}")
    return f"Evento com {' · '.join(parts)}."
