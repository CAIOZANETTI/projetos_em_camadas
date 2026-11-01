"""A régua do código (skill estilo-caio-python, regra 17): lê o próprio código com `ast` e reprova a função órfã, a
duplicata e a PIORA do que já se tinha (função longa, funda, arquivo raso). O histórico mora em pdca/afericao.jsonl,
uma linha por rodada registrada; herdar não reprova, piorar reprova (17.1). Cópia de ialocal.gis.fontes/codigo/kit,
com as pastas deste repositório (tests/, saida/, exemplos/).

    python scripts/afericao.py [--registrar]
"""
import ast
import json
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def arvores(raiz):
    """Todo .py do repositório (código, scripts e testes), fora os ambientes e caches."""
    FORA = {'.venv', '.git', '.claude', '__pycache__', 'dados', 'saida', 'saidas', 'entrada', 'exemplos'}
    return {a: ast.parse(a.read_text(encoding='utf-8')) for a in sorted(raiz.rglob('*.py'))
            if not FORA & set(a.relative_to(raiz).parts)}


def citados(todas):
    """Todo nome, atributo e texto citado: a função despachada por registro (string) não vira falsa órfã."""
    return {no.id if isinstance(no, ast.Name) else no.attr if isinstance(no, ast.Attribute) else no.value
            for arvore in todas.values() for no in ast.walk(arvore)
            if isinstance(no, (ast.Name, ast.Attribute)) or (isinstance(no, ast.Constant) and isinstance(no.value, str))}


def fundo(no, nivel=0):
    """A indentação real: o elif é um If dentro do orelse e não indenta na tela."""
    filhos = [f for campo in ('body', 'orelse', 'finalbody', 'handlers') for f in getattr(no, campo, []) or []
              if not (campo == 'orelse' and isinstance(f, ast.If) and len(no.orelse) == 1)]
    return max([fundo(f, nivel + isinstance(f, (ast.If, ast.For, ast.While, ast.With, ast.Try))) for f in filhos],
               default=nivel)


def copias_do_kit(raiz):
    """Os arquivos de codigo/kit/ que são cópia verificada (listados em kit/HASHES): a origem testa as funções deles,
    então a cópia não acusa órfã pelo que o repositório não usa."""
    hashes = raiz / 'codigo' / 'kit' / 'HASHES'
    if not hashes.exists():
        return set()
    return {raiz / 'codigo' / 'kit' / linha.split()[1] for linha in hashes.read_text(encoding='utf-8').splitlines()
            if len(linha.split()) >= 2}


def medir(raiz=RAIZ):
    LIMITE = {'linhas': 60, 'quebra': 150, 'fundo': 4, 'raso': 5}
    ESPECIAIS = {'__init__', '__enter__', '__exit__', '__repr__', 'principal'}
    inicio = time.monotonic()
    todas = arvores(raiz)
    nomes = citados(todas)
    copias = copias_do_kit(raiz)
    funcoes = [(a, no) for a, arvore in todas.items() for no in ast.walk(arvore)
               if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef))]
    de_codigo = [(a, n) for a, n in funcoes if not {'testes', 'tests'} & set(a.relative_to(raiz).parts)]
    corpos = [ast.dump(ast.Module(body=n.body, type_ignores=[])) for _, n in de_codigo]
    tamanho = {f'{a.relative_to(raiz)}:{n.name}': n.end_lineno - n.lineno + 1 for a, n in de_codigo}
    por_modulo = {}
    for a, _ in de_codigo:
        por_modulo[a] = por_modulo.get(a, 0) + 1
    return {
        'rodada': time.strftime('%Y-%m-%d %H:%M'),
        'funcoes': len(de_codigo),
        'orfas': sorted(f'{a.relative_to(raiz)}:{n.name}' for a, n in de_codigo if a not in copias
                        and n.name not in nomes and n.name not in ESPECIAIS and not n.name.startswith('test_')),
        'duplicatas': len(corpos) - len(set(corpos)),
        'longas': sorted(k for k, v in tamanho.items() if v > LIMITE['linhas']),
        'quebrar': sorted(k for k, v in tamanho.items() if v > LIMITE['quebra']),
        'fundas': sorted(f'{a.relative_to(raiz)}:{n.name}' for a, n in de_codigo if fundo(n) > LIMITE['fundo']),
        'rasos': sorted(str(a.relative_to(raiz)) for a, q in por_modulo.items()
                        if q < LIMITE['raso'] and a.name != '__init__.py'),
        'segundos': round(time.monotonic() - inicio, 3),
    }


def julgar(medida, anterior):
    """Os motivos de reprovação: órfã, duplicata e função acima de 150 linhas sempre; longa, funda e rasa só se
    piorarem contra a última linha registrada."""
    motivos = [f'{len(medida["orfas"])} órfã(s)'] if medida['orfas'] else []
    motivos += [f'{medida["duplicatas"]} duplicata(s)'] if medida['duplicatas'] else []
    motivos += [f'função acima de 150 linhas: {medida["quebrar"]}'] if medida['quebrar'] else []
    for chave in ('longas', 'fundas', 'rasos'):
        if anterior and len(medida[chave]) > anterior.get(chave, 0):
            motivos.append(f'{chave} piorou: {anterior.get(chave, 0)} → {len(medida[chave])}')
    return motivos


def aferir(raiz=RAIZ, registrar=False):
    """Mede, julga contra a última linha de pdca/afericao.jsonl e, se pedido, registra a rodada (só contagens)."""
    historico = raiz / 'pdca' / 'afericao.jsonl'
    linhas = [json.loads(linha) for linha in historico.read_text(encoding='utf-8').splitlines() if linha.strip()] \
        if historico.exists() else []
    medida = medir(raiz)
    motivos = julgar(medida, linhas[-1] if linhas else None)
    if registrar and not motivos:
        resumo = {k: (len(v) if isinstance(v, list) else v) for k, v in medida.items()}
        historico.parent.mkdir(parents=True, exist_ok=True)
        with historico.open('a', encoding='utf-8') as arquivo:
            arquivo.write(json.dumps(resumo, ensure_ascii=False) + '\n')
    return medida, motivos


if __name__ == '__main__':
    medida, motivos = aferir(registrar='--registrar' in sys.argv)
    print(json.dumps({k: v for k, v in medida.items() if v}, ensure_ascii=False, indent=1))
    print('\n'.join(['REPROVADA:', *motivos]) if motivos else 'aferição ok')
    sys.exit(1 if motivos else 0)
