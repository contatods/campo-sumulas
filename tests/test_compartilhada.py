"""Versão compartilhada (compartilhada.py) com um GitHub de mentira."""
import base64
import json

import pytest

import compartilhada as cp


class GitHubFalso:
    def __init__(self):
        self.arquivos = {}   # caminho -> (texto, sha)
        self.n = 0
        self.puts = []
        self.forcar_status = None

    def __call__(self, metodo, caminho, corpo=None, aceitar='application/vnd.github+json'):
        if metodo == 'GET' and caminho.endswith('/contents/'):
            dirs = {c.split('/contents/')[1].split('/')[0] for c in self.arquivos}
            return 200, [{'name': d, 'type': 'dir'} for d in dirs] + [{'name': 'README.md', 'type': 'file'}]
        if metodo == 'GET':
            if caminho not in self.arquivos:
                return 404, {}
            texto, sha = self.arquivos[caminho]
            if aceitar.endswith('raw'):
                return 200, texto.encode()
            grande = len(texto) > 2000
            return 200, {'sha': sha, 'content': '' if grande else base64.b64encode(texto.encode()).decode()}
        if metodo == 'PUT':
            self.puts.append(corpo)
            if self.forcar_status:
                return self.forcar_status, {'message': 'conflict'}
            atual = self.arquivos.get(caminho)
            if atual and corpo.get('sha') != atual[1]:
                return 409, {'message': 'sha'}
            self.n += 1
            sha = f'sha{self.n}'
            self.arquivos[caminho] = (base64.b64decode(corpo['content']).decode(), sha)
            return 201 if not atual else 200, {'content': {'sha': sha}}
        raise AssertionError(metodo)


@pytest.fixture
def gh(monkeypatch):
    falso = GitHubFalso()
    monkeypatch.setattr(cp, '_pedir', falso)
    return falso


SNAP = {'version': 3, 'config': {'evento': {'nome': 'Sun Niterói'}, 'dias': [{'label': 'Sábado', 'categorias': [{'nome': 'RX'}]}]}, 'diaAtual': 0}


def test_desligada_sem_token_e_codigo(monkeypatch):
    monkeypatch.setattr(cp, 'TOKEN', '')
    monkeypatch.setattr(cp, 'CODIGO', 'abc')
    assert not cp.ligada()
    monkeypatch.setattr(cp, 'TOKEN', 't')
    assert cp.ligada()


def test_codigo_e_trava_depois_de_muito_erro(monkeypatch):
    monkeypatch.setattr(cp, 'CODIGO', 'segredo-do-evento')
    monkeypatch.setattr(cp, '_erros', [])
    assert cp.codigo_ok(' segredo-do-evento ')
    for _ in range(cp.MAX_ERROS):
        assert not cp.codigo_ok('chute')
    # travado: nem o certo passa até a janela acabar
    assert not cp.codigo_ok('segredo-do-evento')


def test_nome_do_evento():
    assert cp.validar_evento(' Sun-Niteroi-2027 ') == 'sun-niteroi-2027'
    for ruim in ('', 'a', '../etc', 'sun niteroi', 'x' * 61):
        with pytest.raises(ValueError):
            cp.validar_evento(ruim)


def test_cria_revisao_1_e_depois_2(gh):
    m, sha = cp.gravar('sun-niteroi-2027', SNAP, None, 'mac')
    assert (m['revisao'], m['por'], m['nome'], m['dias'], m['categorias']) == (1, 'mac', 'Sun Niterói', 1, 1)
    assert 'sha' not in gh.puts[0]
    snap, sha_lido = cp.ler('sun-niteroi-2027')
    assert sha_lido == sha and snap['compartilhada']['evento'] == 'sun-niteroi-2027'
    assert snap['config'] == SNAP['config']
    m2, _ = cp.gravar('sun-niteroi-2027', SNAP, sha, 'site', '2.27.0')
    assert m2['revisao'] == 2 and m2['versaoApp'] == '2.27.0'
    assert cp.listar() == ['sun-niteroi-2027']


def test_sha_velha_e_recusada_com_a_revisao_que_esta_la(gh):
    _, sha1 = cp.gravar('ev-2027', SNAP, None, 'mac')
    cp.gravar('ev-2027', SNAP, sha1, 'site')
    with pytest.raises(cp.Conflito) as e:
        cp.gravar('ev-2027', SNAP, sha1, 'mac')
    assert e.value.atual['revisao'] == 2 and e.value.atual['por'] == 'site'
    # criar de novo por cima de um que existe também é conflito
    with pytest.raises(cp.Conflito):
        cp.gravar('ev-2027', SNAP, None, 'mac')


def test_github_recusando_no_meio_vira_conflito(gh):
    _, sha = cp.gravar('ev-2027', SNAP, None, 'mac')
    gh.forcar_status = 409
    with pytest.raises(cp.Conflito):
        cp.gravar('ev-2027', SNAP, sha, 'site')


def test_arquivo_grande_vem_cru(gh):
    grande = json.loads(json.dumps(SNAP))
    grande['config']['evento']['logo_evento'] = 'data:image/png;base64,' + 'A' * 5000
    cp.gravar('ev-2027', grande, None, 'mac')
    snap, _ = cp.ler('ev-2027')
    assert snap['config']['evento']['logo_evento'].endswith('A' * 10)


def test_versao_sem_dias_nao_grava(gh):
    with pytest.raises(ValueError):
        cp.gravar('ev-2027', {'config': {}}, None, 'mac')
