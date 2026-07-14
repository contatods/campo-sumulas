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

# ── Constantes de tuning ──────────────────────────────────────────────────────
# Timeouts da API: fast pra preview/cálculos, chat pra interações longas.
AI_TIMEOUT_FAST_S: float = 15.0   # rounds estimation, time-cap suggestion
AI_TIMEOUT_CHAT_S: float = 20.0   # chat / validar / resumo

# Pace algorítmico (reps/min) usado quando IA cai. Mais rápido pra AMRAPs
# curtos (< 50 reps/round), mais lento pra rounds pesados.
ROUNDS_PACE_LIGHT: int = 10       # reps/min em rounds leves (< 50 reps)
ROUNDS_PACE_HEAVY: int = 7        # reps/min em rounds pesados
ROUNDS_REPS_THRESHOLD: int = 50   # corte entre light/heavy

# Truncamento de contexto pro chat — Anthropic 200K tokens é caro, e
# eventos grandes podem produzir JSON de 100K+. 60K chars (~15K tokens)
# cobre uso real sem estourar.
AI_CONTEXT_MAX_CHARS: int = 60_000


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
        client = anthropic.Anthropic(api_key=AI_KEY, timeout=AI_TIMEOUT_FAST_S)
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
    - For Load: garante tentativas + anilhas + barras + unidade com defaults
      consistentes (evita ver None em export JSON, chat AI, validar_evento)
    Modifica a lista in-place e retorna ela.
    """
    # Import local pra evitar dependência circular caro
    from types_ds import anilhas_default, barra_default

    for wkt in workouts:
        tipo = wkt.get('tipo')
        if tipo == 'amrap':
            duracao = wkt.get('time_cap', '') or ''
            if 'n_rounds' not in wkt:
                wkt['n_rounds'] = _estimar_rounds_ia(wkt.get('movimentos', []), duracao)
        elif tipo == 'express':
            f1 = wkt.get('formula1', {})
            if f1 and 'n_rounds' not in f1:
                f1['n_rounds'] = _estimar_rounds_ia(f1.get('movimentos', []), f1.get('janela', ''))
        elif tipo == 'for_load':
            # tentativas: heurística (IA-like) se faltar
            if not wkt.get('tentativas'):
                wkt['tentativas'] = estimar_tentativas_for_load(wkt)
            # unidade default 'lb' (CrossFit BR + competições oficiais usam lb).
            # Caller pode sobrescrever via ev.unidade_default antes de chamar.
            unidade = (wkt.get('unidade') or 'lb').lower()
            wkt['unidade'] = unidade
            # anilhas, barras: aplica defaults da unidade
            if not wkt.get('anilhas'):
                wkt['anilhas'] = anilhas_default(unidade)
            if not wkt.get('barra_masculina'):
                wkt['barra_masculina'] = barra_default('M', unidade)
            if not wkt.get('barra_feminina'):
                wkt['barra_feminina'] = barra_default('F', unidade)
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
    pace = ROUNDS_PACE_LIGHT if total_reps < ROUNDS_REPS_THRESHOLD else ROUNDS_PACE_HEAVY
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

# Movimentos de barra que exigem carga. Se aparecem sem carga num workout onde
# OUTRO movimento de barra tem carga, provável carga esquecida (Rocket Master F:
# Deadlift 34kg + Hang Power Snatch/Overhead Squat sem carga).
_LIFTS_COM_CARGA = (
    'snatch', 'clean', 'jerk', 'deadlift', 'thruster',
    'overhead squat', 'front squat', 'back squat',
    'push press', 'shoulder press', 'strict press', 'shoulder-to-overhead',
)
# Palavras-chave de anotação (não-movimento) sujeitas a typo. 'atlhetes' cai aqui.
_KEYWORDS_ANOTACAO = ('athletes', 'athlete', 'atletas', 'atleta', 'sync', 'reps')


def _levenshtein(a: str, b: str) -> int:
    """Distância de edição simples (iterativa, O(len(a)*len(b)))."""
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _typo_de_anotacao(nome: str) -> Optional[tuple[str, str]]:
    """Procura um token quase-igual a uma palavra-chave de anotação (typo).

    Retorna (token_errado, palavra_certa) ou None. Conservador: só flagga
    tokens ≥5 letras, com mesmas 2 primeiras letras e distância 1-2 — evita
    falso-positivo com palavras curtas.
    """
    for tok in re.findall(r'[a-zA-ZÀ-ÿ]{5,}', nome.lower()):
        if tok in _KEYWORDS_ANOTACAO:
            continue   # é exatamente uma palavra-chave correta ('athletes' etc.)
        for kw in _KEYWORDS_ANOTACAO:
            if len(kw) < 5 or tok[:2] != kw[:2]:
                continue
            if 1 <= _levenshtein(tok, kw) <= 2:
                return tok, kw
    return None


def colapsar_avisos(avisos: list[dict], limite: int = 8) -> list[dict]:
    """Colapsa avisos repetitivos (mesmo padrão, ignorando números) num só quando
    passam de `limite` — evita o painel afogar (ex: '394× competidor em 2
    lugares' vira 1 linha). Preserva a ordem de 1ª aparição de cada grupo."""
    grupos: dict = {}
    ordem: list = []
    for a in avisos:
        chave = (a.get('severidade', 'aviso'), re.sub(r'\d+', '#', a.get('msg', '')))
        if chave not in grupos:
            grupos[chave] = []
            ordem.append(chave)
        grupos[chave].append(a)
    out: list[dict] = []
    for chave in ordem:
        itens = grupos[chave]
        if len(itens) <= limite:
            out.extend(itens)
        else:
            sev, pat = chave
            out.append({
                'severidade': sev,
                'msg': f'{len(itens)}× {pat.strip()}',
                'onde': f'{len(itens)} ocorrências (ex: {itens[0].get("msg", "")[:60]})',
                '_colapsado': len(itens),
            })
    return out


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

    # 2) Bateria com código mas sem alocação. SÓ vale se o evento tem roster em
    #    algum lugar — se está TODO sem alocação (fase de planejamento, sem
    #    montagem), avisar bateria-a-bateria é ruído (seriam 100+ avisos).
    tem_algum_atleta = any(
        (b.get('alocacoes') or [])
        for dia in dias for cat in (dia.get('categorias') or []) for b in (cat.get('baterias') or [])
    )
    if tem_algum_atleta:
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
                elif tipo == 'composto':
                    # Composto guarda movimentos em f1/f2 (Muscle Swim + 3k),
                    # não no topo — só avisa se AMBOS vierem vazios.
                    f1 = wkt.get('f1', {}) or {}
                    f2 = wkt.get('f2', {}) or {}
                    if not (f1.get('movimentos') or []) and not (f2.get('movimentos') or []):
                        avisos.append({
                            'severidade': 'aviso',
                            'msg': f'Composto "{wkt.get("nome", "?")}" sem movimentos em F1 nem F2',
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

    # Helper: movimentos de um workout, incluindo sub-workouts de composto.
    def _movs_do_workout(wkt: dict) -> list:
        if wkt.get('tipo') == 'composto':
            return ((wkt.get('f1', {}) or {}).get('movimentos') or []) \
                 + ((wkt.get('f2', {}) or {}).get('movimentos') or [])
        return wkt.get('movimentos') or []

    # 6) Carga faltando: levantamento de barra sem carga onde OUTRO levantamento
    #    do mesmo workout tem carga (Rocket Master F: DL 34kg + Snatch/OHS s/ carga).
    for di, dia in enumerate(dias):
        dlabel = dia.get('label', f'Dia {di+1}')
        for cat in dia.get('categorias', []) or []:
            cnome = cat.get('nome', '')
            for wkt in cat.get('workouts', []) or []:
                lifts = [m for m in _movs_do_workout(wkt)
                         if m.get('nome') and any(k in m['nome'].lower() for k in _LIFTS_COM_CARGA)]
                sem_carga = [m for m in lifts if not m.get('carga')]
                if lifts and any(m.get('carga') for m in lifts) and sem_carga:
                    nomes = ', '.join(m['nome'] for m in sem_carga)
                    avisos.append({
                        'severidade': 'aviso',
                        'msg': f'Workout "{wkt.get("nome","?")}": {nomes} sem carga '
                               f'(outros levantamentos têm) — carga esquecida?',
                        'onde': f'{dlabel}/{cnome}',
                    })

    # 7) Typo em palavra-chave de anotação (athletes/atletas/sync). Ex: 'atlhetes'
    #    em '(2 atlhetes)' — vai literal pra súmula. Dedupe global por token.
    vistos_typo: set = set()
    for di, dia in enumerate(dias):
        dlabel = dia.get('label', f'Dia {di+1}')
        for cat in dia.get('categorias', []) or []:
            cnome = cat.get('nome', '')
            for wkt in cat.get('workouts', []) or []:
                for m in _movs_do_workout(wkt):
                    t = _typo_de_anotacao(m.get('nome') or '')
                    if t and t[0] not in vistos_typo:
                        vistos_typo.add(t[0])
                        avisos.append({
                            'severidade': 'aviso',
                            'msg': f'Provável typo "{t[0]}" (seria "{t[1]}"?) — sai literal na súmula',
                            'onde': f'{dlabel}/{cnome}/{wkt.get("nome","?")}',
                        })

    # 8) Carga de dumbbell fora do rol de Equipamentos (ex: 16kg que não existe;
    #    disponíveis 10/15/22,5). Ancora a carga logo após 'dumbbell' pra NÃO
    #    pegar carga de barra em movimento composto ('Fat Bar (34kg) + DB (16kg)').
    dumbbells_ok = set((config.get('equipamento') or {}).get('dumbbells') or [])
    if dumbbells_ok:
        db_paren_re = re.compile(r'dumbbell[^()]*\(([^)]*)\)', re.I)
        kg_re = re.compile(r'(\d+(?:[.,]\d+)?)\s*kg', re.I)
        vistos_db: set = set()
        for di, dia in enumerate(dias):
            dlabel = dia.get('label', f'Dia {di+1}')
            for cat in dia.get('categorias', []) or []:
                cnome = cat.get('nome', '')
                for wkt in cat.get('workouts', []) or []:
                    for m in _movs_do_workout(wkt):
                        for grp in db_paren_re.findall(m.get('nome') or ''):
                            for num_s in kg_re.findall(grp):
                                peso = float(num_s.replace(',', '.'))
                                if peso in dumbbells_ok or (cnome, peso) in vistos_db:
                                    continue
                                vistos_db.add((cnome, peso))
                                disp = ', '.join(f'{d:g}' for d in sorted(dumbbells_ok))
                                avisos.append({
                                    'severidade': 'erro',
                                    'msg': f'Dumbbell de {peso:g}kg não existe no rol de '
                                           f'Equipamentos (disponíveis: {disp}kg)',
                                    'onde': f'{dlabel}/{cnome}/{wkt.get("nome","?")}',
                                })

    # 9) Movimento com provável typo NO NOME (ex: 'Thrustres'). Vocab canônico
    #    vendorizado; conservador — movimento custom (Hay Bale Burpee) NÃO é
    #    flaggado, só quase-igual a um conhecido.
    from movimentos import checar_movimento_typo
    vistos_mov: set = set()
    for di, dia in enumerate(dias):
        dlabel = dia.get('label', f'Dia {di+1}')
        for cat in dia.get('categorias', []) or []:
            cnome = cat.get('nome', '')
            for wkt in cat.get('workouts', []) or []:
                for m in _movs_do_workout(wkt):
                    t = checar_movimento_typo(m.get('nome') or '')
                    if t and t[0] not in vistos_mov:
                        vistos_mov.add(t[0])
                        avisos.append({
                            'severidade': 'aviso',
                            'msg': f'Movimento "{t[0]}" — provável typo de "{t[1]}"?',
                            'onde': f'{dlabel}/{cnome}/{wkt.get("nome","?")}',
                        })

    # 10) Cronograma: slot da bateria menor que a duração estimada do workout
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
    pace = ROUNDS_PACE_LIGHT if total_reps < ROUNDS_REPS_THRESHOLD else ROUNDS_PACE_HEAVY
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
    if len(contexto) > AI_CONTEXT_MAX_CHARS:
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
    client = anthropic.Anthropic(api_key=AI_KEY, timeout=AI_TIMEOUT_CHAT_S)
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        system=system,
        messages=mensagens,
    )
    if not resp.content:
        return ""
    return resp.content[0].text or ""


# ── Explicar avisos do import em linguagem humanizada ────────────────────────
def explicar_avisos_import(stats: dict, avisos: list[dict]) -> str:
    """Recebe estatísticas do evento + lista de avisos (do parser e do
    validar_evento) e retorna texto em PT-BR explicando o que aconteceu,
    voltado pra organizador de evento (não-técnico).

    Levanta RuntimeError quando IA não está ativa (caller deve fazer fallback
    pra mostrar avisos crus).
    """
    if not AI_ATIVO:
        raise RuntimeError('IA inativa — defina ANTHROPIC_API_KEY pra usar análise.')
    if not avisos:
        return ""   # sem avisos, sem necessidade de IA

    import json as _json
    # Trunca lista de avisos pra não estourar tokens — ~50 avisos é mais que
    # suficiente, organizador não vai ler 100 explicações.
    avisos_truncados = avisos[:50]
    contexto = _json.dumps({'stats': stats, 'avisos': avisos_truncados}, ensure_ascii=False)

    system = (
        "Você é assistente de organização de eventos de CrossFit ajudando quem "
        "acabou de importar um Excel pro sistema de súmulas. Seu papel é "
        "EXPLICAR os avisos do sistema em linguagem natural, voltada pra "
        "organizador (não-técnico). Regras:\n\n"
        "1. Comece com 1 frase de resumo do evento (use os stats fornecidos).\n"
        "2. Pra cada GRUPO de avisos relacionados, escreva 1 parágrafo curto "
        "   (2-3 frases) explicando o que aconteceu e o que fazer.\n"
        "3. Agrupe avisos similares (ex: várias baterias órfãs da mesma "
        "   categoria → 1 parágrafo só).\n"
        "4. Tom: direto, prático, sem jargão técnico (evite palavras como "
        "   'normalização', 'parser', 'chave'). Use 'cronograma', 'sorteio', "
        "   'alocação', 'inscritos', 'heat' que organizadores entendem.\n"
        "5. Sempre que possível, sugira CORREÇÃO concreta no Excel.\n"
        "6. Limite total: 300 palavras. Sem markdown elaborado, só texto "
        "   corrido com quebras de linha entre parágrafos.\n\n"
        f"Dados do import:\n{contexto}"
    )

    client = anthropic.Anthropic(api_key=AI_KEY, timeout=AI_TIMEOUT_CHAT_S)
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        system=system,
        messages=[{"role": "user", "content": "Explique o que aconteceu no import desse evento."}],
    )
    if not resp.content:
        return ""
    return resp.content[0].text or ""


# ── Review de PROGRAMAÇÃO por IA (Fase 2.0) ─────────────────────────────────
def _presc_movimentos(movs: list) -> list[str]:
    """Lista compacta 'Nx NOME @carga' dos movimentos de um workout."""
    out = []
    for m in movs or []:
        if not isinstance(m, dict) or not m.get('nome'):
            continue
        s = f"{m.get('reps', '?')}x {m['nome']}"
        if m.get('carga'):
            s += f" @{m['carga']}"
        out.append(s)
    return out


def _resumo_programacao_por_workout(config: dict) -> dict:
    """Agrupa a programação por NOME de workout → versões por categoria, com a
    prescrição compacta (movs/cargas). Deixa a IA comparar o escalonamento entre
    divisões (ex: Fat Bar 10kg numa divisão vs 34kg nas outras). Dedupe por
    (workout, categoria) — o mesmo workout repete entre dias."""
    grupos: dict[str, list] = {}
    vistos: set = set()
    for dia in config.get('dias', []) or []:
        for cat in dia.get('categorias', []) or []:
            cnome = cat.get('nome', '')
            for wkt in cat.get('workouts', []) or []:
                wn = wkt.get('nome', '?')
                if (wn, cnome) in vistos:
                    continue
                vistos.add((wn, cnome))
                if wkt.get('tipo') == 'composto':
                    presc = {
                        'F1': _presc_movimentos((wkt.get('f1') or {}).get('movimentos')),
                        'F2': _presc_movimentos((wkt.get('f2') or {}).get('movimentos')),
                    }
                elif wkt.get('tipo') == 'for_load':
                    seq = wkt.get('sequencia_movimentos') or {}
                    presc = {'for_load': [j.get('complex') for j in (seq.get('janelas') or [])]
                                         or [seq.get('complex')]}
                else:
                    presc = {'movs': _presc_movimentos(wkt.get('movimentos'))}
                grupos.setdefault(wn, []).append({'categoria': cnome, **presc})
    # Só workouts com 2+ divisões interessam pra comparação de escalonamento.
    return {k: v for k, v in grupos.items() if len(v) >= 2}


def _parse_findings_json(txt: str) -> list[dict]:
    """Extrai a lista JSON de findings da resposta da IA (tolera cerca ```json)."""
    import json as _json
    if not txt:
        return []
    m = re.search(r'\[.*\]', txt, re.S)   # primeiro array JSON no texto
    if not m:
        return []
    try:
        dados = _json.loads(m.group(0))
    except (ValueError, TypeError):
        return []
    out = []
    for d in dados if isinstance(dados, list) else []:
        if not isinstance(d, dict) or not d.get('msg'):
            continue
        sev = d.get('severidade')
        out.append({
            'severidade': sev if sev in ('erro', 'aviso') else 'aviso',
            'msg': str(d['msg'])[:300],
            'onde': str(d.get('onde', ''))[:120],
            'fonte': 'ia',
        })
    return out


def revisar_programacao_ia(config: dict) -> list[dict]:
    """Review de PROGRAMAÇÃO por IA — pega o que o linter determinístico NÃO vê:
    escalonamento invertido entre divisões, carga fora de padrão, sanidade
    cross-divisão, movimento estranho pro nível. Retorna lista de
    {severidade, msg, onde, fonte:'ia'}. RuntimeError se IA inativa.
    """
    if not AI_ATIVO:
        raise RuntimeError('IA inativa — defina ANTHROPIC_API_KEY pra usar a review.')
    import json as _json
    grupos = _resumo_programacao_por_workout(config)
    if not grupos:
        return []
    contexto = _json.dumps(grupos, ensure_ascii=False)[:AI_CONTEXT_MAX_CHARS]
    system = (
        "Você é revisor experiente de programação de CrossFit conferindo a "
        "planilha de um evento ANTES da impressão das súmulas. Recebe os workouts "
        "agrupados por nome, com a versão de cada categoria/divisão.\n\n"
        "Aponte APENAS problemas REAIS e acionáveis que um checador de regras não "
        "pega, priorizando:\n"
        "1. Escalonamento invertido/incoerente entre divisões (ex: carga menor "
        "   numa divisão mais forte, ou uma carga destoando das demais — tipo "
        "   uma barra a 10kg quando as outras versões usam 34kg).\n"
        "2. Carga/reps fora de padrão pro movimento ou pro nível.\n"
        "3. Movimento que não faz sentido pra divisão (ex: Rx fazendo scaled).\n"
        "4. Inconsistência entre versões que deveriam ser paralelas.\n\n"
        "NÃO aponte: falta de carga (já checado), typos, cronograma. Seja "
        "conservador — se não tem certeza, não inclua. Melhor 3 achados certeiros "
        "que 15 duvidosos.\n\n"
        "Responda SOMENTE com um array JSON (sem texto fora dele). Cada item:\n"
        '{"severidade":"aviso"|"erro","msg":"<problema + correção sugerida, 1 frase>",'
        '"onde":"<workout / categoria>"}\n'
        "Array vazio [] se nada relevante.\n\n"
        f"Programação:\n{contexto}"
    )
    client = anthropic.Anthropic(api_key=AI_KEY, timeout=AI_TIMEOUT_CHAT_S)
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1500,
        system=system,
        messages=[{"role": "user", "content": "Revise a programação e liste só os problemas reais em JSON."}],
    )
    txt = (resp.content[0].text if resp.content else "") or ""
    return _parse_findings_json(txt)


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
