"""Funções puras: ordenação, numeração, parsers de duração e estimativa de rounds."""
from parsers import _atleta_sort_key, assign_workout_numbers, assign_workout_numbers_global
from ai_rounds import _extrair_minutos, _estimar_rounds_algoritmico
from sumula_app import _resolve_logo


def test_resolve_logo_aceita_data_url():
    val = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg"
    assert _resolve_logo(val) == val


def test_resolve_logo_rejeita_caminho_de_arquivo():
    """Path traversal: POST com `logo_empresa: '/etc/passwd'` vazava o
    arquivo em base64 no HTML antes do v1.50.1. App público no Render.
    """
    assert _resolve_logo("/etc/passwd") == ""
    assert _resolve_logo(".env") == ""
    assert _resolve_logo("../../secret.txt") == ""
    assert _resolve_logo("logo.png") == ""


def test_resolve_logo_vazio_ou_none():
    assert _resolve_logo("") == ""
    assert _resolve_logo(None) == ""
    assert _resolve_logo(0) == ""


def test_atleta_sort_key_ordena_por_bateria_raia_numerica_nome(atletas_desordenados):
    ordered = sorted(atletas_desordenados, key=_atleta_sort_key)
    assert [a["nome"] for a in ordered] == ["Ana", "Diana", "Bruno", "Carlos"]
    # Ana(A,2) → Diana(A,3) → Bruno(B,1) → Carlos(B,10) — raia 10 vem depois de 2 (numérica)


def test_assign_workout_numbers_express_ocupa_dois_slots():
    workouts = [
        {"nome": "A", "tipo": "for_time"},
        {"nome": "B", "tipo": "express"},
        {"nome": "C", "tipo": "amrap"},
    ]
    assign_workout_numbers(workouts)
    assert workouts[0]["numero"] == 1
    assert workouts[1]["numero"] == 2
    assert workouts[1]["numero_f2"] == 3
    assert workouts[2]["numero"] == 4
    # workouts não-express não devem ter numero_f2
    assert "numero_f2" not in workouts[0]
    assert "numero_f2" not in workouts[2]


def test_assign_workout_numbers_global_continua_por_categoria_atraves_dias():
    """Elite Masc: 3 wkts na Sexta → 4,5 no Sábado → 6 no Domingo (contínuo).
    Rx Masc (categoria diferente) reinicia em 1."""
    dias = [
        {"label": "Sexta", "categorias": [
            {"nome": "Elite Masc", "workouts": [
                {"nome": "W1", "tipo": "for_time"},
                {"nome": "W2", "tipo": "amrap"},
                {"nome": "W3", "tipo": "for_load"},
            ]},
            {"nome": "Rx Masc", "workouts": [
                {"nome": "X1", "tipo": "for_time"},
            ]},
        ]},
        {"label": "Sábado", "categorias": [
            {"nome": "Elite Masc", "workouts": [
                {"nome": "W4", "tipo": "for_time"},
                {"nome": "W5", "tipo": "express"},
            ]},
        ]},
        {"label": "Domingo", "categorias": [
            {"nome": "Elite Masc", "workouts": [
                {"nome": "W7", "tipo": "for_time"},
            ]},
        ]},
    ]
    assign_workout_numbers_global(dias)
    # Sexta Elite
    assert [w["numero"] for w in dias[0]["categorias"][0]["workouts"]] == [1, 2, 3]
    # Sexta Rx — categoria distinta, reinicia
    assert dias[0]["categorias"][1]["workouts"][0]["numero"] == 1
    # Sábado Elite — continua após Sexta (3) → 4 e 5 (W5 é express → ocupa 5+6)
    assert dias[1]["categorias"][0]["workouts"][0]["numero"] == 4
    assert dias[1]["categorias"][0]["workouts"][1]["numero"] == 5
    assert dias[1]["categorias"][0]["workouts"][1]["numero_f2"] == 6
    # Domingo Elite — após Express ocupar 5+6, próximo é 7
    assert dias[2]["categorias"][0]["workouts"][0]["numero"] == 7


def test_extrair_minutos_aceita_formatos_comuns():
    assert _extrair_minutos("AMRAP 5 MIN") == 5
    assert _extrair_minutos("00:00 → 05:00 · AMRAP 5 MIN") == 5
    assert _extrair_minutos("AMRAP 12 minutos") == 12
    assert _extrair_minutos("") is None
    assert _extrair_minutos("sem minutos aqui") is None


def test_estimar_rounds_algoritmico_retorna_inteiro_razoavel():
    movs = [
        {"nome": "PULL-UPS", "reps": 10},
        {"nome": "THRUSTERS", "reps": 10},
    ]
    n = _estimar_rounds_algoritmico(movs, "AMRAP 5 MIN")
    assert isinstance(n, int)
    assert n >= 2  # mínimo de 2 linhas no scorecard


# ── Estimativa de rounds: simulação round a round ───────────────────────────
def test_pace_diferencia_movimentos():
    """Um pace único pra tudo trata 30 double-unders como 30 strict HSPU e erra
    por ordens de grandeza. O custo por rep tem que refletir o movimento."""
    from ai_rounds import _segundos_do_movimento as seg
    du = seg({'nome': 'DOUBLE UNDERS', 'reps': 30})
    hspu = seg({'nome': 'STRICT HANDSTAND PUSH-UPS', 'reps': 20})
    assert hspu > du * 5, f'strict HSPU ({hspu}s) deveria custar muito mais que DU ({du}s)'
    # variante específica ganha da genérica
    assert (seg({'nome': 'LEGLESS ROPE CLIMBS', 'reps': 2})
            > seg({'nome': 'ROPE CLIMBS', 'reps': 2}))
    assert (seg({'nome': 'STRICT HANDSTAND PUSH-UPS', 'reps': 10})
            > seg({'nome': 'HANDSTAND PUSH-UPS', 'reps': 10}))
    # distância cobra por metro, não por "rep"
    assert seg({'nome': '900M SKI ERG', 'reps': 900}) > 0
    assert (seg({'nome': '20M HANDSTAND WALK', 'reps': 20})
            > seg({'nome': '20M RUN', 'reps': 20}))
    # sem reps mensuráveis não gera tempo
    assert seg({'nome': 'MAX PULL-UPS'}) == 0.0
    assert seg({'nome': 'X', 'reps': 0}) == 0.0


def test_reps_do_round_aplica_progressao():
    """A simulação precisa das reps DAQUELE round — com progressão, o round 6
    é mais longo que o round 1."""
    from ai_rounds import _reps_do_round
    mov = {'nome': 'WALL-BALL', 'reps': 30, 'reps_delta': 10,
           'reps_por_round': [30, 40, 50]}
    assert _reps_do_round(mov, 0) == 30
    assert _reps_do_round(mov, 2) == 50
    # além da lista pré-computada, extrapola pelo passo
    assert _reps_do_round(mov, 5) == 80
    # movimento sem progressão devolve a base em qualquer round
    fixo = {'nome': 'PULL-UPS', 'reps': 10}
    assert _reps_do_round(fixo, 0) == _reps_do_round(fixo, 7) == 10
    assert _reps_do_round({'nome': 'MAX X'}, 0) is None


def test_estimar_rounds_realista_por_peso_do_round():
    """Round pesado dá poucos rounds; round leve dá muitos. O modelo antigo
    (reps ÷ pace fixo) projetava 18 rounds do Fast Relay, em que cabem ~3."""
    fast_relay = [
        {'nome': 'LEGLESS ROPE CLIMBS (15 FT)', 'reps': 2},
        {'nome': 'DOUBLE UNDERS', 'reps': 30},
        {'nome': 'STRICT HANDSTAND PUSH-UPS', 'reps': 20},
        {'nome': 'WALL-BALL SHOTS', 'reps': 30, 'reps_delta': 10,
         'reps_por_round': [30, 40, 50, 60, 70]},
    ]
    n = _estimar_rounds_algoritmico(fast_relay, '16 min')
    assert 4 <= n <= 9, f'{n} linhas — fora da faixa plausível pro Fast Relay'

    # Cindy (5 pull-ups / 10 push-ups / 15 air squats em 20') roda ~20 rounds
    cindy = [{'nome': 'PULL-UPS', 'reps': 5}, {'nome': 'PUSH-UPS', 'reps': 10},
             {'nome': 'AIR SQUATS', 'reps': 15}]
    n_cindy = _estimar_rounds_algoritmico(cindy, '20 min')
    assert n_cindy > n, 'round leve tem que render mais rounds que round pesado'
    assert 12 <= n_cindy <= 30, n_cindy


def test_estimar_rounds_conta_a_progressao():
    """Com progressão cada round demora mais — a projeção tem que ser MENOR
    que a do mesmo workout sem progressão."""
    base = [{'nome': 'WALL-BALL SHOTS', 'reps': 30}]
    prog = [{'nome': 'WALL-BALL SHOTS', 'reps': 30, 'reps_delta': 20}]
    assert (_estimar_rounds_algoritmico(prog, '15 min')
            < _estimar_rounds_algoritmico(base, '15 min'))


def test_estimar_rounds_fallbacks():
    """Sem duração ou sem movimentos mensuráveis, cai num mínimo seguro."""
    from ai_rounds import ROUNDS_MIN_LINHAS, ROUNDS_MAX_LINHAS
    movs = [{'nome': 'PULL-UPS', 'reps': 5}]
    assert _estimar_rounds_algoritmico(movs, '') == ROUNDS_MIN_LINHAS
    assert _estimar_rounds_algoritmico([], '10 min') == ROUNDS_MIN_LINHAS
    assert _estimar_rounds_algoritmico([{'nome': 'MAX BURPEES'}], '10 min') == ROUNDS_MIN_LINHAS
    # prescrição degenerada (round quase instantâneo) não explode a página
    leve = [{'nome': 'SINGLE UNDERS', 'reps': 1}]
    assert _estimar_rounds_algoritmico(leve, '60 min') <= ROUNDS_MAX_LINHAS


# ── Ordenação com par de raias ('1–2') ──────────────────────────────────────
def test_ordenacao_de_impressao_aceita_par_de_raias():
    """As três camadas que ordenam raia têm que concordar. `_to_int_or_max`
    (app: bateria → raia) e `chave_num` (PDF do dia) exigiam string toda
    numérica, então '1–2' ia pro fim e a ordem de impressão saía embaralhada
    justamente no evento em que cada time ocupa duas raias.
    """
    from sumula_app import _to_int_or_max
    from gerar_pdfs import chave_num
    from parsers import _primeira_raia

    pares = ['9–10', '1–2', '7–8', '3–4', '5–6', '10', '2']
    esperado = ['1–2', '2', '3–4', '5–6', '7–8', '9–10', '10']
    for nome, chave in (('_to_int_or_max', _to_int_or_max),
                        ('chave_num', chave_num),
                        ('_primeira_raia', _primeira_raia)):
        assert sorted(pares, key=chave) == esperado, nome

    # não-numérico continua indo pro fim
    assert sorted(['Final', '1–2'], key=chave_num) == ['1–2', 'Final']
    assert _to_int_or_max('Final') == 10**9
    assert _to_int_or_max(None) == 10**9
    # raia simples (um atleta por raia) não regrediu
    assert sorted(['10', '2', '1'], key=chave_num) == ['1', '2', '10']


def test_validacao_for_load_aceita_peso_repetido():
    """O backend não pode recusar '20, 20, 15': duas anilhas do mesmo peso no
    mesmo lado é montagem legítima de barra."""
    from sumula_app import _validate_for_load, FOR_LOAD_ANILHAS_MAX
    _validate_for_load({'tipo': 'for_load', 'unidade': 'kg',
                        'anilhas': [20, 20, 15, 10, 5, 2.5, 1]}, 0)
    _validate_for_load({'tipo': 'for_load', 'unidade': 'kg',
                        'anilhas': [20, 20, 20, 15]}, 0)
    # o cap horizontal do A4 continua valendo
    import pytest
    from sumula_app import BadRequest
    with pytest.raises(BadRequest):
        _validate_for_load({'tipo': 'for_load', 'unidade': 'kg',
                            'anilhas': [20] * (FOR_LOAD_ANILHAS_MAX + 1)}, 0)


# ── Preview e geração final têm que dar o MESMO número de rounds ────────────
class _FakeResp:
    def __init__(self, texto):
        self.content = [type('C', (), {'text': texto})()]


def _fake_anthropic(resposta):
    """Cliente Anthropic de mentira que sempre devolve `resposta`."""
    class _Client:
        def __init__(self, **kw):
            self.messages = self
        def create(self, **kw):
            return _FakeResp(resposta)
    return type('A', (), {'Anthropic': _Client})


def test_estimativa_final_nunca_fica_abaixo_do_preview(monkeypatch):
    """O preview usa só a simulação (pra não pagar o timeout da IA) e a geração
    final passava pela IA. Quando a IA devolvia menos, a súmula saía com MENOS
    linhas do que o preview mostrou — no Fast Relay do BFO, 6 viraram 4, e o
    juiz ficava sem onde anotar os rounds extras.
    """
    import ai_rounds
    from ai_rounds import _estimar_rounds_algoritmico, _estimar_rounds_ia

    movs = [{'nome': 'LEGLESS ROPE CLIMBS', 'reps': 2},
            {'nome': 'DOUBLE UNDERS', 'reps': 30},
            {'nome': 'STRICT HANDSTAND PUSH-UPS', 'reps': 20},
            {'nome': 'WALL-BALL SHOTS', 'reps': 30, 'reps_delta': 10,
             'reps_por_round': [30, 40, 50, 60, 70]}]
    preview = _estimar_rounds_algoritmico(movs, '16 min')

    monkeypatch.setattr(ai_rounds, 'AI_ATIVO', True)
    monkeypatch.setattr(ai_rounds, 'AI_KEY', 'fake')

    # IA subestimando: prevalece a simulação
    monkeypatch.setattr(ai_rounds, 'anthropic', _fake_anthropic('2'))
    assert _estimar_rounds_ia(movs, '16 min') == preview

    # IA pedindo mais: o maior vence (faltar linha é pior que sobrar)
    monkeypatch.setattr(ai_rounds, 'anthropic', _fake_anthropic('9'))
    assert _estimar_rounds_ia(movs, '16 min') == 11        # 9 + 2 de buffer

    # resposta ilegível cai no algoritmo
    monkeypatch.setattr(ai_rounds, 'anthropic', _fake_anthropic('sei lá'))
    assert _estimar_rounds_ia(movs, '16 min') == preview


def test_estimativa_final_sem_ia_usa_a_simulacao(monkeypatch):
    """Sem chave de API, os dois caminhos já coincidiam — não pode regredir."""
    import ai_rounds
    from ai_rounds import _estimar_rounds_algoritmico, _estimar_rounds_ia
    monkeypatch.setattr(ai_rounds, 'AI_ATIVO', False)
    movs = [{'nome': 'PULL-UPS', 'reps': 5}, {'nome': 'AIR SQUATS', 'reps': 15}]
    assert (_estimar_rounds_ia(movs, '20 min')
            == _estimar_rounds_algoritmico(movs, '20 min'))
