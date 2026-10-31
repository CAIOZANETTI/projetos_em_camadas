"""A régua da IA × código: quanto da obra sai do build (código) e quanto ainda depende de um agente (IA na obra).

A base é pdca/determinismo.json (cada etapa do processo com o executor e o número de itens da obra) e
pdca/licoes.jsonl (cada lição aprendida com o arquivo e o teste que a formalizam). O histórico mora em
pdca/determinismo.jsonl, uma linha por rodada registrada. Reprova: lição formalizada cujo arquivo ou teste não existe,
índice que piora contra a última rodada e rodada registrada sem lição nova (a regra: toda rodada com a IA deixa ao
menos uma lição em código).

    python scripts/determinismo.py [--registrar]
"""
import json
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def carregar(raiz=RAIZ):
    """Etapas, meta, lições e histórico, como estão no disco."""
    pdca = raiz / 'pdca'
    base = json.loads((pdca / 'determinismo.json').read_text(encoding='utf-8'))
    ler = lambda nome: [json.loads(l) for l in (pdca / nome).read_text(encoding='utf-8').splitlines() if l.strip()] \
        if (pdca / nome).exists() else []
    return base, ler('licoes.jsonl'), ler('determinismo.jsonl')


def indice(etapas):
    """Índice por etapas (o da meta) e por registros (informativo); a decisão humana fica fora dos dois."""
    conta = {e: [x for x in etapas if x['executor'] == e] for e in ('codigo', 'ia', 'humano')}
    n_etapas = {e: len(v) for e, v in conta.items()}
    n_itens = {e: sum(x['itens'] for x in v) for e, v in conta.items()}
    fracao = lambda n: round(n['codigo'] / max(n['codigo'] + n['ia'], 1), 3)
    return {'etapas': n_etapas, 'itens': n_itens, 'indice_etapas': fracao(n_etapas),
            'indice_registros': fracao(n_itens),
            'ia_por_papel': {p: sum(1 for x in conta['ia'] if x.get('papel') == p)
                             for p in sorted({x.get('papel') for x in conta['ia']})}}


def conferir_licoes(licoes, raiz=RAIZ):
    """Lição dada como formalizada aponta para um arquivo que existe e, se tem teste, para um teste que existe."""
    erros = []
    for l in licoes:
        if not l['estado'].startswith('formalizada'):
            continue
        arquivo = l['formalizada_em'].split(' ')[0]
        if not (raiz / arquivo).exists():
            erros.append(f"{l['id']}: {arquivo} não existe")
        if l.get('teste'):
            caminho, _, nome = l['teste'].partition('::')
            texto = (raiz / caminho).read_text(encoding='utf-8') if (raiz / caminho).exists() else ''
            if not texto or (nome and f'def {nome}(' not in texto):
                erros.append(f"{l['id']}: teste {l['teste']} não existe")
    return erros


def custo_agentes(raiz=RAIZ):
    """Tokens por modelo a partir de pdca/agentes.jsonl: quanto cada degrau da escada custa, para gastar o modelo
    grande só onde ele decide. Linha sem medição (sessão reiniciada) conta à parte, não como zero."""
    caminho = raiz / 'pdca' / 'agentes.jsonl'
    linhas = [json.loads(l) for l in caminho.read_text(encoding='utf-8').splitlines() if l.strip()] \
        if caminho.exists() else []
    por_modelo = {}
    for l in linhas:
        m = por_modelo.setdefault(l['modelo'], {'chamadas': 0, 'tokens': 0, 'sem_medicao': 0})
        m['chamadas'] += 1
        m['tokens'] += l['tokens'] or 0
        m['sem_medicao'] += l['tokens'] is None
    return por_modelo


def tendencia(atual, meta):
    """Rodadas até a meta no passo combinado (+5 p.p. por rodada), a partir do índice atual."""
    alvo, passo = meta['indice_etapas']['alvo'], meta['indice_etapas']['passo_por_rodada']
    falta = max(alvo - atual, 0.0)
    return {'alvo': alvo, 'falta_pp': round(falta * 100, 1), 'rodadas_ate_a_meta': int(-(-round(falta, 3) // passo))}


def julgar(medida, licoes, anterior, erros):
    """Os motivos de reprovação: lição sem arquivo ou teste, índice que piorou e rodada sem lição nova."""
    motivos = list(erros)
    if anterior and medida['indice_etapas'] < anterior['indice_etapas']:
        motivos.append(f"índice por etapas piorou: {anterior['indice_etapas']} → {medida['indice_etapas']}")
    if anterior and len(licoes) <= anterior['licoes']:
        motivos.append('rodada sem lição nova em pdca/licoes.jsonl')
    return motivos


def medir(raiz=RAIZ, registrar=False):
    """Mede, julga contra a última linha de pdca/determinismo.jsonl e, se pedido e aprovado, registra a rodada."""
    base, licoes, historico = carregar(raiz)
    medida = {'rodada': time.strftime('%Y-%m-%d %H:%M'), 'obra': base['obra'], **indice(base['etapas']),
              'licoes': len(licoes),
              'licoes_com_teste': sum(1 for l in licoes if l['estado'] == 'formalizada' and l.get('teste'))}
    medida['tendencia'] = tendencia(medida['indice_etapas'], base['meta'])
    medida['agentes'] = custo_agentes(raiz)
    motivos = julgar(medida, licoes, historico[-1] if historico else None, conferir_licoes(licoes, raiz))
    if registrar and not motivos:
        with (raiz / 'pdca' / 'determinismo.jsonl').open('a', encoding='utf-8') as arquivo:
            arquivo.write(json.dumps(medida, ensure_ascii=False) + '\n')
    return medida, motivos


if __name__ == '__main__':
    medida, motivos = medir(registrar='--registrar' in sys.argv)
    print(json.dumps(medida, ensure_ascii=False, indent=1))
    print('\n'.join(['REPROVADA:', *motivos]) if motivos else 'determinismo ok')
    sys.exit(1 if motivos else 0)
