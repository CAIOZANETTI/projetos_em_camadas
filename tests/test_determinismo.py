import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import determinismo


def _pdca(tmp_path, etapas, licoes, historico=()):
    pdca = tmp_path / 'pdca'
    pdca.mkdir()
    meta = {'indice_etapas': {'alvo': 0.85, 'passo_por_rodada': 0.05}}
    (pdca / 'determinismo.json').write_text(json.dumps({'obra': 'x', 'meta': meta, 'etapas': etapas}), encoding='utf-8')
    (pdca / 'licoes.jsonl').write_text(''.join(json.dumps(l) + '\n' for l in licoes), encoding='utf-8')
    if historico:
        (pdca / 'determinismo.jsonl').write_text(''.join(json.dumps(h) + '\n' for h in historico), encoding='utf-8')
    return tmp_path


def test_indice_deixa_a_decisao_humana_fora():
    etapas = [{'executor': 'codigo', 'itens': 90}, {'executor': 'codigo', 'itens': 10},
              {'executor': 'ia', 'itens': 100, 'papel': 'leitura'}, {'executor': 'humano', 'itens': 1}]
    i = determinismo.indice(etapas)
    assert i['indice_etapas'] == 0.667 and i['indice_registros'] == 0.5
    assert i['etapas'] == {'codigo': 2, 'ia': 1, 'humano': 1} and i['ia_por_papel'] == {'leitura': 1}


def test_tendencia_conta_as_rodadas_ate_a_meta():
    meta = {'indice_etapas': {'alvo': 0.85, 'passo_por_rodada': 0.05}}
    assert determinismo.tendencia(0.571, meta) == {'alvo': 0.85, 'falta_pp': 27.9, 'rodadas_ate_a_meta': 6}
    assert determinismo.tendencia(0.9, meta)['rodadas_ate_a_meta'] == 0


def test_licao_sem_arquivo_ou_teste_reprova(tmp_path):
    (tmp_path / 'regra.json').write_text('{}', encoding='utf-8')
    licoes = [{'id': 'L1', 'estado': 'formalizada', 'formalizada_em': 'regra.json (chave)', 'teste': 'tests/t.py::test_a'},
              {'id': 'L2', 'estado': 'formalizada', 'formalizada_em': 'falta.json', 'teste': None},
              {'id': 'L3', 'estado': 'pendente', 'formalizada_em': 'nada', 'teste': None}]
    erros = determinismo.conferir_licoes(licoes, tmp_path)
    assert erros == ['L1: teste tests/t.py::test_a não existe', 'L2: falta.json não existe']


def test_rodada_sem_licao_nova_ou_com_indice_pior_reprova(tmp_path):
    etapas = [{'executor': 'codigo', 'itens': 1}, {'executor': 'ia', 'itens': 1}]
    licoes = [{'id': 'L1', 'estado': 'pendente', 'formalizada_em': '-', 'teste': None}]
    raiz = _pdca(tmp_path, etapas, licoes, historico=[{'indice_etapas': 0.6, 'licoes': 1}])
    medida, motivos = determinismo.medir(raiz, registrar=True)
    assert medida['indice_etapas'] == 0.5
    assert motivos == ['índice por etapas piorou: 0.6 → 0.5', 'rodada sem lição nova em pdca/licoes.jsonl']
    assert len((raiz / 'pdca' / 'determinismo.jsonl').read_text(encoding='utf-8').splitlines()) == 1


def test_base_do_repositorio_confere():
    medida, motivos = determinismo.medir()
    assert not [m for m in motivos if 'não existe' in m]
    assert 0 < medida['indice_etapas'] < 1


def test_cada_versao_desde_a_0_19_deixa_uma_licao():
    """A regra vale para qualquer sessão: versão nova no CHANGELOG sem lição em pdca/licoes.jsonl reprova."""
    import re
    raiz = Path(__file__).resolve().parents[1]
    versoes = re.findall(r"^## (\d+)\.(\d+)\.(\d+)", (raiz / 'CHANGELOG.md').read_text(encoding='utf-8'), re.MULTILINE)
    exigidas = {'.'.join(v) for v in versoes if tuple(map(int, v)) >= (0, 19, 0)}
    _, licoes, _ = determinismo.carregar(raiz)
    assert exigidas - {l.get('versao') for l in licoes} == set()
