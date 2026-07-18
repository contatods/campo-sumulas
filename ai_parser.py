"""Fase 2 da robustez de leitura: IA como REPARADOR de parsing.

A regex (`parse_workout_text`) faz a 1ª passada. Quando o resultado FALHA no
schema canônico (`validar_workout_schema`), o app chama `reparar_workout_ia`:
a IA estrutura o texto cru num JSON limpo (contrato estável), que um conversor
determinístico transforma no dict interno. Resultado:

  - só workouts que a regex não deu conta chamam a IA (85%+ nunca tocam a API);
  - **cache por hash do texto** → re-importar é grátis e determinístico;
  - o app só aceita o reparo se ele passar no schema (nunca fica pior que regex).

O conversor (`_ia_json_para_workout`) é puro e testável sem API. A chamada da
API fica isolada em `_chamar_reparo_ia`, fácil de mockar.
"""
import hashlib
import json
import re
from typing import Optional

import ai_rounds  # AI_ATIVO, AI_KEY, timeouts, anthropic

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None

_MODEL = "claude-haiku-4-5-20251001"

# Contrato que a IA deve devolver (JSON). Estável e simples — desacopla a IA dos
# detalhes internos do render. O conversor abaixo mapeia pro dict interno.
_SYSTEM_PROMPT = (
    "Você estrutura UM workout de CrossFit (texto livre de uma planilha de "
    "evento) num JSON. A regex do sistema não conseguiu ler direito; sua tarefa "
    "é devolver a estrutura correta.\n\n"
    "Responda SOMENTE com um objeto JSON (nada fora dele), neste formato:\n"
    "{\n"
    '  "nome": "<nome do workout, sem aspas>",\n'
    '  "tipo": "for_time" | "for_time_goal" | "amrap",\n'
    '  "time_cap": "<ex: 14 min ou 12:30 min>" | null,\n'
    '  "score_regra": "<o que pontua, 1 frase>" | null,\n'
    '  "janelas": [   // use QUANDO houver 2+ blocos de tempo (AMRAP/Parts) com descanso\n'
    '    {"titulo":"AMRAP 4 minutes","rest_depois":"Rest 1 minute" | null,\n'
    '     "movimentos":[{"nome":"...","reps":30 | null,"max":false,"pontua":true}]}\n'
    "  ] | null,\n"
    '  "movimentos": [   // use QUANDO for janela única\n'
    '    {"nome":"...","reps":21 | null,"carga":"43kg" | null,"goal":false}\n'
    "  ] | null,\n"
    '  "goal_reps": <int> | null,\n'
    '  "goal_movimento": "<nome>" | null\n'
    "}\n\n"
    "Regras:\n"
    "- 'max':true numa linha 'Max ...' (reps ilimitadas até o tempo acabar) — é o "
    "que pontua; marque 'pontua':true nela.\n"
    "- Reps prescritas fixas que NÃO contam pontuação: 'pontua':false.\n"
    "- Preserve carga entre parênteses (34kg, 14lb) no nome ou no campo carga.\n"
    "- Não invente movimentos nem reps. Se não sabe, use null.\n"
    "- Se o texto disser que a chegada não conta, não a inclua."
)


def _hash(txt: str) -> str:
    return hashlib.md5(txt.encode("utf-8")).hexdigest()


# Cache de reparo por hash do texto cru → JSON da IA (ou None se falhou/indisponível).
_CACHE_REPARO: dict[str, Optional[dict]] = {}


def limpar_cache() -> None:
    _CACHE_REPARO.clear()


def _extrair_json_obj(txt: str) -> Optional[dict]:
    """Extrai o 1º objeto JSON da resposta (tolera cerca ```json)."""
    if not txt:
        return None
    m = re.search(r'\{.*\}', txt, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except (ValueError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


def _int_ou_none(v):
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _mov_ia(m: dict) -> Optional[dict]:
    nome = str(m.get("nome") or "").strip().upper()
    if not nome:
        return None
    mv: dict = {"nome": nome}
    r = _int_ou_none(m.get("reps"))
    if r is not None:
        mv["reps"] = r
    if m.get("carga"):
        mv["carga"] = str(m["carga"]).upper()
    return mv


def _ia_json_para_workout(js: dict, numero: int) -> Optional[dict]:
    """Converte o JSON da IA no dict interno de workout. Puro/determinístico.
    Retorna None se o JSON for inválido ou de um tipo não suportado pelo reparo."""
    if not isinstance(js, dict):
        return None
    tipo = js.get("tipo")
    if tipo not in ("for_time", "for_time_goal", "amrap"):
        return None
    nome = str(js.get("nome") or "").strip()
    if not nome:
        return None
    wkt: dict = {
        "numero": numero, "nome": nome.upper(), "tipo": tipo,
        "modalidade": "individual", "time_cap": str(js.get("time_cap") or ""),
        "movimentos": [], "descricao": [],
    }
    if js.get("score_regra"):
        wkt["score_regra"] = str(js["score_regra"])

    janelas = js.get("janelas")
    if isinstance(janelas, list) and len(janelas) >= 2:
        out = []
        for j in janelas:
            if not isinstance(j, dict):
                continue
            movs = []
            for m in (j.get("movimentos") or []):
                mv = _mov_ia(m) if isinstance(m, dict) else None
                if not mv:
                    continue
                if m.get("max"):
                    mv["max"] = True
                    mv["pontua"] = True
                else:
                    mv["pontua"] = bool(m.get("pontua", True))
                movs.append(mv)
            if not movs:
                continue
            jan = {"titulo": str(j.get("titulo") or "AMRAP"), "movimentos": movs}
            if j.get("rest_depois"):
                jan["rest_depois"] = str(j["rest_depois"])
            out.append(jan)
        if len(out) < 2:
            return None
        wkt["tipo"] = "amrap"
        wkt["janelas"] = out
        wkt["rest_entre"] = next((j["rest_depois"] for j in out if j.get("rest_depois")), "")
        # sem nenhuma linha Max → AMRAP normal (tudo conta)
        if not any(m.get("max") for jj in out for m in jj["movimentos"]):
            for jj in out:
                for m in jj["movimentos"]:
                    m["pontua"] = True
        return wkt

    # janela única
    movs = []
    for m in (js.get("movimentos") or []):
        mv = _mov_ia(m) if isinstance(m, dict) else None
        if not mv:
            continue
        if m.get("goal"):
            mv["goal"] = True
        movs.append(mv)
    if not movs:
        return None
    wkt["movimentos"] = movs
    goal = _int_ou_none(js.get("goal_reps"))
    if goal:
        wkt["tipo"] = "for_time_goal"
        wkt["goal_reps"] = goal
        if js.get("goal_movimento"):
            wkt["goal_movimento"] = str(js["goal_movimento"])
    return wkt


def _chamar_reparo_ia(raw: str) -> Optional[dict]:
    """Chama a IA pra estruturar o workout. Retorna o JSON (dict) ou None.
    Isolada pra facilitar mock nos testes."""
    if not ai_rounds.AI_ATIVO or anthropic is None:
        return None
    try:
        client = anthropic.Anthropic(api_key=ai_rounds.AI_KEY,
                                     timeout=ai_rounds.AI_TIMEOUT_CHAT_S)
        resp = client.messages.create(
            model=_MODEL, max_tokens=1500, system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": raw[:8000]}],
        )
        txt = (resp.content[0].text if resp.content else "") or ""
    except Exception:
        return None
    return _extrair_json_obj(txt)


def reparar_workout_ia(raw: str, numero: int, wkt_regex=None, problemas=None):
    """Reparador registrado no parser (Fase 2). Retorna um workout reparado ou
    None. Cacheado por hash do texto cru → re-import é grátis e determinístico."""
    key = _hash(raw)
    if key in _CACHE_REPARO:
        js = _CACHE_REPARO[key]
    else:
        js = _chamar_reparo_ia(raw)
        if js is not None:            # cacheia só sucesso (falha pode ser transitória)
            _CACHE_REPARO[key] = js
    return _ia_json_para_workout(js, numero) if js else None


# ── Fase 3: revisão de FIDELIDADE (parse vs texto do Excel) ──────────────────
def _mov_resumo(m: dict) -> str:
    """Uma linha compacta de movimento pro resumo do parse (o que a IA compara)."""
    if m.get("chegada"):
        return "chegada (+1 rep)"
    if m.get("secao"):
        return f"[seção: {m['secao']}]"
    if m.get("separador"):
        return "[then…]"
    s = m.get("nome") or "?"
    if m.get("reps") is not None:
        s = f"{m['reps']} {s}"
    if m.get("max"):
        s = f"MAX {s}"
    if m.get("goal"):
        s = f"GOAL {s}"
    if m.get("pontua") is False:
        s += " (não pontua)"
    return s


def _resumo_parse_fidelidade(wkt: dict) -> dict:
    """Resumo estrutural de COMO o sistema leu o workout — pra IA comparar com o
    texto cru. Cobre os campos onde a leitura costuma errar."""
    tipo = wkt.get("tipo")
    d: dict = {"tipo": tipo, "time_cap": wkt.get("time_cap") or None}
    if wkt.get("janelas"):
        d["janelas"] = [{"titulo": j.get("titulo"),
                         "movs": [_mov_resumo(m) for m in j.get("movimentos", [])]}
                        for j in wkt["janelas"]]
        if wkt.get("score_regra"):
            d["pontuacao"] = wkt["score_regra"]
    elif tipo == "composto":
        d["f1"] = [_mov_resumo(m) for m in (wkt.get("f1") or {}).get("movimentos", [])]
        d["f2"] = [_mov_resumo(m) for m in (wkt.get("f2") or {}).get("movimentos", [])]
    elif tipo == "express":
        d["formula1"] = [_mov_resumo(m) for m in (wkt.get("formula1") or {}).get("movimentos", [])]
        d["formula2"] = [_mov_resumo(m) for m in (wkt.get("formula2") or {}).get("movimentos", [])]
    elif tipo == "for_load":
        seq = wkt.get("sequencia_movimentos") or {}
        d["for_load"] = [j.get("complex") for j in (seq.get("janelas") or [])] or [seq.get("complex")]
        d["tentativas"] = wkt.get("tentativas")
    else:
        d["movs"] = [_mov_resumo(m) for m in wkt.get("movimentos", [])]
    for k in ("rounds_fixos", "rounds_bloco", "goal_reps", "goal_movimento"):
        if wkt.get(k):
            d[k] = wkt[k]
    return d


_SYSTEM_FIDELIDADE = (
    "Você confere a LEITURA AUTOMÁTICA de workouts de CrossFit antes de imprimir "
    "as súmulas. Para cada workout recebe:\n"
    "- 'texto_excel': o texto ORIGINAL da planilha (fonte da verdade)\n"
    "- 'parse': como o sistema LEU (tipo, movimentos, reps, rounds, pontuação, "
    "time cap)\n\n"
    "Aponte APENAS divergências REAIS entre o parse e o texto original:\n"
    "- movimento faltando ou sobrando; reps/carga erradas;\n"
    "- tipo errado (ex: era AMRAP de 2 janelas e leu como for time simples);\n"
    "- rounds não detectados; pontuação/score lido errado (ex: perdeu a linha "
    "  'Max' que conta pontos, ou contou reps que não pontuam);\n"
    "- time cap errado; chegada indevida ou faltando.\n\n"
    "IGNORE: diferenças de maiúsculas/formatação, ordem de metadados, notas de "
    "regulamento. Seja conservador — se está fiel, não reporte. Melhor 2 achados "
    "certos que 10 duvidosos.\n\n"
    "Responda SOMENTE com um array JSON (nada fora dele). Cada item:\n"
    '{"severidade":"erro"|"aviso","msg":"<o que divergiu + como deveria ser, 1 frase>",'
    '"onde":"<nome do workout>"}\n'
    "Array vazio [] se tudo fiel."
)


def revisar_leitura_ia(config: dict, client=None) -> list[dict]:
    """Revisão de FIDELIDADE (Fase 3): compara o parse de cada workout com o
    texto cru do Excel (`_raw`) e devolve divergências. Dedupe por hash do texto
    (o mesmo workout repete entre categorias/dias). RuntimeError se IA inativa.
    """
    if not ai_rounds.AI_ATIVO and client is None:
        raise RuntimeError('IA inativa — defina ANTHROPIC_API_KEY pra revisar a leitura.')
    itens = []
    vistos = set()
    for dia in config.get('dias', []) or []:
        for cat in dia.get('categorias', []) or []:
            for wkt in cat.get('workouts', []) or []:
                raw = wkt.get('_raw')
                if not raw:
                    continue
                h = _hash(raw)
                if h in vistos:
                    continue
                vistos.add(h)
                itens.append({
                    'nome': wkt.get('nome') or '?',
                    'texto_excel': str(raw)[:1500],
                    'parse': _resumo_parse_fidelidade(wkt),
                })
    if not itens:
        return []
    contexto = json.dumps(itens, ensure_ascii=False)[:ai_rounds.AI_CONTEXT_MAX_CHARS]
    system = _SYSTEM_FIDELIDADE + "\n\nWorkouts:\n" + contexto
    client = client or anthropic.Anthropic(api_key=ai_rounds.AI_KEY,
                                            timeout=ai_rounds.AI_TIMEOUT_CHAT_S)
    resp = client.messages.create(
        model=_MODEL, max_tokens=1800, system=system,
        messages=[{"role": "user",
                   "content": "Confira a leitura e liste só as divergências reais em JSON."}],
    )
    txt = (resp.content[0].text if resp.content else "") or ""
    return ai_rounds._parse_findings_json(txt)
