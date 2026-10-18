"""Versão compartilhada das súmulas de um evento (decisão de 18/10/2026).

O site de súmulas guarda cada evento no navegador de quem usa. Pra o site e o
Cadastrador do Mac trabalharem na MESMA versão, cada evento pode ter um
arquivo no repositório privado contatods/sumulas: <evento>/sumulas.json, no
mesmo formato do "Exportar JSON" ({version, config, diaAtual, exportedAt}),
mais o bloco "compartilhada" ({evento, revisao, gravadoEm, por, versaoApp}).

Quem grava manda a sha da versão que tinha (a que buscou por último). Se
alguém gravou no meio, a sha não bate e a gravação é recusada (Conflito, com
a revisão que está lá): nada se perde sem aviso.

Desligado até existirem, no Render, SUMULAS_GITHUB_TOKEN (token do GitHub só
com "Contents: read and write" no contatods/sumulas) e SUMULAS_CODIGO (o
código que quem usa digita no site). Gerar súmula continua aberto: só esta
parte pede o código. O Cadastrador não passa por aqui: grava direto pelo
GitHub com o login do Mac.
"""
import base64
import hmac
import json
import os
import re
import ssl
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

REPO = os.environ.get('SUMULAS_REPO', 'contatods/sumulas').strip()
TOKEN = os.environ.get('SUMULAS_GITHUB_TOKEN', '').strip()
CODIGO = os.environ.get('SUMULAS_CODIGO', '').strip()
EVENTO = re.compile(r'^[a-z0-9][a-z0-9-]{1,59}$')
API = 'https://api.github.com'


def _contexto_ssl():
    # O Python do python.org no Mac vem sem os certificados do sistema; o
    # certifi (que já vem com o SDK da Anthropic) resolve lá e no Render.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


_SSL = _contexto_ssl()


class Conflito(Exception):
    """Alguém gravou outra revisão depois da que a pessoa tinha."""
    def __init__(self, atual):
        super().__init__('versão desatualizada')
        self.atual = atual


class Desligada(Exception):
    pass


def ligada():
    return bool(TOKEN and CODIGO)


# Código errado demais em pouco tempo trava por um tempo (tentativa no chute).
_erros = []
_erros_lock = threading.Lock()
MAX_ERROS = 20
JANELA_S = 600


def codigo_ok(recebido):
    agora = time.time()
    with _erros_lock:
        _erros[:] = [t for t in _erros if agora - t < JANELA_S]
        if len(_erros) >= MAX_ERROS:
            return False
        ok = bool(CODIGO) and hmac.compare_digest(str(recebido or '').strip().encode(), CODIGO.encode())
        if not ok:
            _erros.append(agora)
        return ok


def validar_evento(evento):
    evento = str(evento or '').strip().lower()
    if not EVENTO.match(evento):
        raise ValueError('nome do evento inválido: use letras minúsculas, números e hífen (ex.: sun-niteroi-2027)')
    return evento


def _pedir(metodo, caminho, corpo=None, aceitar='application/vnd.github+json'):
    if not TOKEN:
        raise Desligada()
    req = urllib.request.Request(f'{API}{caminho}', method=metodo, data=json.dumps(corpo).encode() if corpo is not None else None, headers={
        'Authorization': f'Bearer {TOKEN}', 'Accept': aceitar, 'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'campo-sumulas', **({'Content-Type': 'application/json'} if corpo is not None else {}),
    })
    try:
        with urllib.request.urlopen(req, timeout=20, context=_SSL) as r:
            dados = r.read()
            return r.status, (json.loads(dados) if aceitar.endswith('+json') and dados else dados)
    except urllib.error.HTTPError as e:
        try:
            dados = json.loads(e.read() or b'{}')
        except ValueError:
            dados = {}
        return e.code, dados


def _caminho(evento):
    return f'/repos/{REPO}/contents/{evento}/sumulas.json'


def meta(snap):
    c = (snap or {}).get('compartilhada') or {}
    cfg = (snap or {}).get('config') or {}
    dias = cfg.get('dias') or []
    return {
        'evento': c.get('evento', ''), 'revisao': c.get('revisao', 0), 'gravadoEm': c.get('gravadoEm', ''),
        'por': c.get('por', ''), 'versaoApp': c.get('versaoApp', ''),
        'nome': (cfg.get('evento') or {}).get('nome', ''),
        'dias': len(dias), 'categorias': sum(len(d.get('categorias') or []) for d in dias),
    }


def ler(evento):
    """(snapshot, sha) ou (None, None) se o evento não tem versão compartilhada."""
    evento = validar_evento(evento)
    status, dados = _pedir('GET', _caminho(evento))
    if status == 404:
        return None, None
    if status != 200:
        raise RuntimeError(f'GitHub respondeu {status}: {dados.get("message", "") if isinstance(dados, dict) else ""}')
    sha = dados.get('sha')
    if dados.get('content'):
        texto = base64.b64decode(dados['content']).decode('utf-8')
    else:
        # acima de 1 MB a API não manda o conteúdo junto: busca cru
        status, cru = _pedir('GET', _caminho(evento), aceitar='application/vnd.github.raw')
        if status != 200:
            raise RuntimeError(f'GitHub respondeu {status} ao buscar o arquivo')
        texto = cru.decode('utf-8')
    return json.loads(texto), sha


def listar():
    status, dados = _pedir('GET', f'/repos/{REPO}/contents/')
    if status == 404:
        return []
    if status != 200:
        raise RuntimeError(f'GitHub respondeu {status}')
    return sorted(i['name'] for i in dados if i.get('type') == 'dir' and EVENTO.match(i.get('name', '')))


def gravar(evento, snap, sha_base, por, versao_app=''):
    """Grava a próxima revisão. sha_base: a sha da versão que a pessoa tinha
    (None pra criar). Devolve (meta, sha nova); Conflito se a sha não bate."""
    evento = validar_evento(evento)
    if not isinstance(snap, dict) or not isinstance((snap.get('config') or {}).get('dias'), list):
        raise ValueError('versão sem config.dias')
    atual, sha_atual = ler(evento)
    if sha_atual != (sha_base or None):
        raise Conflito(meta(atual) if atual else None)
    revisao = (meta(atual)['revisao'] if atual else 0) + 1
    novo = {
        'version': snap.get('version', 3), 'config': snap['config'], 'diaAtual': snap.get('diaAtual', 0),
        'exportedAt': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'compartilhada': {'evento': evento, 'revisao': revisao, 'gravadoEm': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                          'por': por, 'versaoApp': versao_app},
    }
    texto = json.dumps(novo, ensure_ascii=False, indent=1) + '\n'
    corpo = {'message': f'{evento}: revisão {revisao} ({por})', 'content': base64.b64encode(texto.encode('utf-8')).decode('ascii')}
    if sha_atual:
        corpo['sha'] = sha_atual
    status, dados = _pedir('PUT', _caminho(evento), corpo)
    if status in (409, 422):
        atual, _ = ler(evento)
        raise Conflito(meta(atual) if atual else None)
    if status not in (200, 201):
        raise RuntimeError(f'GitHub respondeu {status}: {dados.get("message", "") if isinstance(dados, dict) else ""}')
    return meta(novo), dados['content']['sha']
