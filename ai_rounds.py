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


def _carregar_env_local():
    """Lê um arquivo .env na raiz do projeto (se existir) e popula os.environ.

    Suporta linhas no formato `CHAVE=valor` e `CHAVE="valor com aspas"`.
    Comentários (`#`) e linhas vazias são ignoradas. Não sobrescreve variáveis
    já presentes no ambiente.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(here, '.env')
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            for raw in f:
                linha = raw.strip()
                if not linha or linha.startswith('#') or '=' not in linha:
                    continue
                k, _, v = linha.partition('=')
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass  # falha silenciosa — arquivo malformado não deve quebrar startup

_carregar_env_local()
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
    - For Load: garante 'tentativas' (estima se não veio do Excel)
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
        elif wkt.get('tipo') == 'for_load':
            if not wkt.get('tentativas'):
                wkt['tentativas'] = estimar_tentativas_for_load(wkt)
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


def estimar_tentativas_for_load(workout: Workout) -> int:
    """Estima quantas tentativas faz sentido pra um workout For Load.

    Heurística simples sem IA: 3 é o padrão CrossFit (máximo lift); workouts
    com 'max' ou 'establish' no nome confirmam isso. Se for clearly progressivo
    (com palavras como 'progression', 'wave'), pode ser 5.
    """
    nome = (workout.get('nome', '') or '').lower()
    desc = ' '.join(workout.get('descricao', []) or []).lower()
    full = nome + ' ' + desc
    if any(k in full for k in ('progression', 'wave', 'ladder', 'progressi')):
        return 5
    return 3


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
                elif tipo == 'for_load':
                    # For Load não tem movimentos; valida config específica
                    if not (wkt.get('anilhas') or []):
                        avisos.append({
                            'severidade': 'aviso',
                            'msg': f'For Load "{wkt.get("nome", "?")}" sem anilhas configuradas (usará default)',
                            'onde': f'{dlabel}/{cnome}',
                        })
                    if not (wkt.get('tentativas') or 0):
                        avisos.append({
                            'severidade': 'aviso',
                            'msg': f'For Load "{wkt.get("nome", "?")}" sem nº de tentativas (usará 3)',
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

    # 6) Cronograma: slot da bateria menor que a duração estimada do workout
    avisos.extend(_avisos_cronograma(dias))
    return avisos


def _hhmm_to_min(s: str) -> Optional[int]:
    """Converte 'HH:MM' (ou 'HH:MM:SS') em minutos desde 00:00."""
    if not s:
        return None
    m = re.match(r'^(\d{1,2}):(\d{2})', str(s))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def estimar_duracao_workout_min(wkt: Workout) -> int:
    """Estima duração de execução de um workout em minutos.

    For Time: usa time_cap se houver; senão estima por reps totais.
    AMRAP: usa time_cap (é literalmente a duração).
    Express: F1 duração + 1min descanso + F2 duração (ou time_cap geral).
    """
    tipo = wkt.get('tipo', 'for_time')
    if tipo == 'amrap':
        return _extrair_minutos(wkt.get('time_cap', '') or '') or 10

    if tipo == 'express':
        f1 = wkt.get('formula1', {}) or {}
        f2 = wkt.get('formula2', {}) or {}
        dur_f1 = _extrair_minutos(f1.get('janela', '') or '') or 5
        dur_f2 = _extrair_minutos(f2.get('janela', '') or '') or _extrair_minutos(wkt.get('time_cap', '') or '') or 7
        return dur_f1 + 1 + dur_f2

    if tipo == 'for_load':
        # ~2 min por tentativa (preparação + execução + setup) é uma boa heurística
        tentativas = wkt.get('tentativas') or 3
        return max(5, int(tentativas) * 2)

    # for_time: prefere time_cap; cai no estimar via reps
    tc = _extrair_minutos(wkt.get('time_cap', '') or '')
    if tc:
        return tc
    movs = [m for m in (wkt.get('movimentos') or [])
            if not m.get('separador') and not m.get('chegada')]
    total_reps = sum(int(m.get('reps', 0)) for m in movs
                     if str(m.get('reps', '')).isdigit())
    if not total_reps:
        return 10
    pace = 10 if total_reps < 50 else 7
    return max(5, int(total_reps / pace * 1.4))


def _avisos_cronograma(dias: list[dict]) -> list[dict]:
    """Compara duração estimada × slot disponível em cada bateria.

    Slot = horario_aquecimento da PRÓXIMA bateria menos horario_fila desta.
    Se a duração do workout > slot, flagga aviso.
    """
    avisos: list[dict] = []
    for di, dia in enumerate(dias):
        dlabel = dia.get('label', f'Dia {di+1}')
        for cat in dia.get('categorias', []) or []:
            cnome = cat.get('nome', '')
            workouts = cat.get('workouts', []) or []
            baterias = sorted(
                (cat.get('baterias', []) or []),
                key=lambda b: _hhmm_to_min(b.get('horario_aquecimento', '')) or 0,
            )
            for idx, b in enumerate(baterias):
                aq      = _hhmm_to_min(b.get('horario_aquecimento', ''))
                fila    = _hhmm_to_min(b.get('horario_fila', ''))
                proxima = baterias[idx + 1] if idx + 1 < len(baterias) else None
                aq_prox = _hhmm_to_min(proxima.get('horario_aquecimento', '')) if proxima else None
                if fila is None or aq_prox is None:
                    continue
                slot_min = aq_prox - fila
                if slot_min <= 0:
                    continue
                # Pega os workouts que rodam nesta bateria
                idxs_workouts = b.get('workouts_que_rodam') or []
                duracao_total = 0
                for wi in idxs_workouts:
                    if 1 <= wi <= len(workouts):
                        duracao_total += estimar_duracao_workout_min(workouts[wi - 1])
                if duracao_total > slot_min + 2:  # tolera 2 min de buffer
                    avisos.append({
                        'severidade': 'aviso',
                        'msg': f'Bateria {b.get("numero")} ({b.get("codigo_evento")}) precisa ~{duracao_total}min mas slot tem {slot_min}min',
                        'onde': f'{dlabel}/{cnome}',
                    })
    return avisos


# ── Chat assistente do evento (Claude responde com base no config carregado) ─
def chat_evento(mensagens: list[dict], config: dict) -> str:
    """Chat com Claude tendo o config do evento como contexto.

    `mensagens` é uma lista de turnos no formato Anthropic
    [{ role: 'user'|'assistant', content: '...' }, ...].
    Retorna a resposta textual.

    Levanta RuntimeError quando IA não está ativa (chave ausente / SDK ausente).
    """
    if not AI_ATIVO:
        raise RuntimeError('IA inativa — defina ANTHROPIC_API_KEY pra usar o chat.')
    import json as _json
    contexto = _json.dumps(config, ensure_ascii=False)
    if len(contexto) > 60000:
        # Truncate seguro: passa só nomes/baterias, não alocações detalhadas
        ev = config.get('evento', {})
        slim = {
            'evento': ev,
            'dias': [
                {
                    'label': d.get('label'),
                    'data':  d.get('data', ''),
                    'categorias': [
                        {
                            'nome': c.get('nome'),
                            'workouts': [{'nome': w.get('nome'), 'tipo': w.get('tipo'),
                                          'time_cap': w.get('time_cap', '')} for w in (c.get('workouts') or [])],
                            'baterias': [
                                {'numero': b.get('numero'), 'codigo_evento': b.get('codigo_evento'),
                                 'horario_aquecimento': b.get('horario_aquecimento'),
                                 'horario_fila': b.get('horario_fila'),
                                 'workouts_que_rodam': b.get('workouts_que_rodam'),
                                 'alocacoes': b.get('alocacoes', [])}
                                for b in (c.get('baterias') or [])
                            ],
                        }
                        for c in (d.get('categorias') or [])
                    ],
                }
                for d in (config.get('dias') or [])
            ],
        }
        contexto = _json.dumps(slim, ensure_ascii=False)

    system = (
        "Você é um assistente de organização de eventos de CrossFit. Responda em português brasileiro, "
        "objetivo, baseando-se exclusivamente no JSON do evento abaixo. Quando perguntarem por dados "
        "específicos (atleta, raia, bateria, horário), procure no JSON e responda com precisão. Se a "
        "informação não está no JSON, diga claramente que não está.\n\n"
        f"Estado atual do evento:\n{contexto}"
    )
    client = anthropic.Anthropic(api_key=AI_KEY, timeout=20.0)
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        system=system,
        messages=mensagens,
    )
    if not resp.content:
        return ""
    return resp.content[0].text or ""


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
