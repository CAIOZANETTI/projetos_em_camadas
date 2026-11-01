"""Gavetas da memória espacial: cada fato extraído tem um lugar, com evidência; os serviços saem só dessas gavetas.

O fluxo é o de `docs/MEMORIA_ESPACIAL.md`, com os três de-para em `conceitos/`:

1. **documento → gaveta** (`de_para_extracao.json`): o que cada leitor pode gravar;
2. **gaveta → serviço** (`de_para_servicos.json`): de quais fatos cada regra depende;
3. **serviço → EAP** (`de_para_eap.json`): em que nó cada quantidade entra.

O contrato das gavetas (`gavetas.json`) é lógico. O formato físico é experimento: `gravar` e `ler` aceitam os
formatos de `formato.implementados`, e o resto do código não muda com a troca. A base em memória é um dict
`{gaveta: [registros]}`.

    python -m camadas.gavetas saida/<obra>/base      # confere a base e calcula os serviços
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import json
import re
import types
from pathlib import Path

import numpy as np

from . import obras_lineares as ol
from .pdf_cad import CONCEITOS


def _ler(nome: str) -> dict:
    return json.loads((CONCEITOS / f"{nome}.json").read_text(encoding="utf-8"))


REGRAS = _ler("gavetas")
EXTRACAO = _ler("de_para_extracao")
SERVICOS = _ler("de_para_servicos")
EAP = _ler("de_para_eap")
GAVETAS = list(REGRAS["gavetas"])


# --------------------------------------------------------------------------------------------------------------------
# Conferência: base e de-para
# --------------------------------------------------------------------------------------------------------------------

def validar(gaveta: str, registro: dict) -> list[str]:
    """Campos obrigatórios e valores permitidos de um registro."""
    g = REGRAS["gavetas"].get(gaveta)
    if g is None:
        return [f"gaveta {gaveta} não existe em conceitos/gavetas.json"]
    rotulo = registro.get(g["chave"]) if g["chave"] else registro.get("objeto_id")
    erros = [f"{gaveta} {rotulo}: falta {c}" for c in g["obrigatorios"] if registro.get(c) in (None, "")]
    regras = {("fatos", "natureza"): REGRAS["naturezas"], ("fatos", "propriedade"): list(REGRAS["propriedades"]),
              ("evidencias", "executor"): REGRAS["executores"], ("geometria", "tipo"): REGRAS["tipos_geometria"]}
    for (gav, campo), permitidos in regras.items():
        if gav == gaveta and registro.get(campo) not in (None, "") and registro[campo] not in permitidos:
            erros.append(f"{gaveta} {rotulo}: {campo} '{registro[campo]}' fora de {permitidos}")
    return erros


def conferir_base(base: dict) -> list[str]:
    """Todo registro válido; todo fato aponta para objeto e evidência existentes; chave sem repetição."""
    erros = [e for gav in GAVETAS for r in base.get(gav, []) for e in validar(gav, r)]
    erros += [f"gaveta {g} não existe em conceitos/gavetas.json" for g in base if g not in REGRAS["gavetas"]]
    objetos = {o["objeto_id"] for o in base.get("objetos", [])}
    evidencias = {e["evidencia_id"] for e in base.get("evidencias", [])}
    for f in base.get("fatos", []):
        if f.get("objeto_id") not in objetos:
            erros.append(f"fatos {f.get('fato_id')}: objeto {f.get('objeto_id')} não está em objetos")
        if f.get("evidencia_id") and f["evidencia_id"] not in evidencias:
            erros.append(f"fatos {f.get('fato_id')}: evidência {f['evidencia_id']} não existe")
    for gav, g in REGRAS["gavetas"].items():
        ids = [r.get(g["chave"]) for r in base.get(gav, [])] if g["chave"] else []
        erros += [f"{gav}: {g['chave']} {i} repetido" for i in sorted({i for i in ids if ids.count(i) > 1})]
    return erros


def conferir_de_para() -> list[str]:
    """Os três de-para só citam propriedades, gavetas, funções e nós que existem."""
    props = set(REGRAS["propriedades"])
    erros = [f"de_para_extracao: propriedade {p} não existe" for e in EXTRACAO["entradas"]
             for p in e["propriedades"] if p not in props]
    for nome, r in SERVICOS["regras"].items():
        erros += [f"de_para_servicos.{nome}: propriedade {p} não existe" for p in r["exige"] + r["opcionais"]
                  if p not in props]
        erros += [f"de_para_servicos.{nome}: saída {s} sem nó em de_para_eap" for s in r["saidas"]
                  if s not in EAP["saidas"]]
        modulo, _, funcao = r["funcao"].rpartition(".")
        if not hasattr(importlib.import_module(modulo), funcao):
            erros.append(f"de_para_servicos.{nome}: função {r['funcao']} não existe")
        objetos = {e["objeto"] for e in EXTRACAO["entradas"]}
        erros += [f"de_para_servicos.{nome}: nenhum leitor grava o objeto {o}"
                  for o in (r["objeto"], r.get("sondagens")) if o and o not in objetos]
    return erros


# --------------------------------------------------------------------------------------------------------------------
# Formato físico (experimento G05): o mesmo contrato em qualquer formato
# --------------------------------------------------------------------------------------------------------------------

def _gravar_jsonl(pasta: Path, base: dict) -> list[Path]:
    """`<gaveta>.jsonl`: um registro por linha."""
    feitos = []
    for gav in GAVETAS:
        arq = pasta / f"{gav}.jsonl"
        arq.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in base.get(gav, [])), encoding="utf-8")
        feitos.append(arq)
    return feitos


def _ler_jsonl(pasta: Path) -> dict:
    base = {}
    for gav in GAVETAS:
        arq = pasta / f"{gav}.jsonl"
        base[gav] = ([json.loads(l) for l in arq.read_text(encoding="utf-8").splitlines() if l.strip()]
                     if arq.exists() else [])
    return base


def _gravar_csv(pasta: Path, base: dict) -> list[Path]:
    """`<gaveta>.csv`: cabeçalho com a união das chaves, célula em JSON."""
    feitos = []
    for gav in GAVETAS:
        regs, arq = base.get(gav, []), pasta / f"{gav}.csv"
        colunas = list(dict.fromkeys(k for r in regs for k in r))
        with open(arq, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(colunas)
            w.writerows([[json.dumps(r.get(c), ensure_ascii=False) for c in colunas] for r in regs])
        feitos.append(arq)
    return feitos


def _ler_csv(pasta: Path) -> dict:
    base = {}
    for gav in GAVETAS:
        arq = pasta / f"{gav}.csv"
        if not arq.exists():
            base[gav] = []
            continue
        with open(arq, newline="", encoding="utf-8") as fh:
            linhas = list(csv.reader(fh, delimiter=";"))
        base[gav] = [{c: json.loads(v) for c, v in zip(linhas[0], l) if json.loads(v) is not None}
                     for l in linhas[1:]]
    return base


# Colunas em tabela arrow (parquet, geoparquet e duckdb): escalar homogêneo fica nativo, o resto vira texto JSON.

def _tipo_nativo(valores: list):
    """Tipo arrow da coluna se todos os valores presentes são do mesmo escalar (bool, int64, float, str); senão None."""
    import pyarrow as pa
    tipos = {type(v) for v in valores if v is not None}
    if len(tipos) != 1:
        return None
    t = tipos.pop()
    if t is int:
        return pa.int64() if all(-2**63 <= v < 2**63 for v in valores if v is not None) else None
    return {bool: pa.bool_(), float: pa.float64(), str: pa.string()}.get(t)


def _tabela(regs: list[dict]):
    """Tabela arrow de uma gaveta; os nomes das colunas em JSON ficam nos metadados do schema (`b"gavetas"`)."""
    import pyarrow as pa
    colunas = list(dict.fromkeys(k for r in regs for k in r))
    arrays, em_json = [], []
    for c in colunas:
        valores = [r.get(c) for r in regs]
        tipo = _tipo_nativo(valores)
        if tipo is None:
            em_json.append(c)
            valores = [None if v is None else json.dumps(v, ensure_ascii=False) for v in valores]
            tipo = pa.string()
        arrays.append(pa.array(valores, type=tipo))
    meta = {b"gavetas": json.dumps({"json": em_json}).encode()}
    return pa.table(arrays, schema=pa.schema([pa.field(c, a.type) for c, a in zip(colunas, arrays)], metadata=meta))


def _registros(tabela, em_json: list[str], descartar: tuple = ()) -> list[dict]:
    """Volta os registros: valor ausente não é recriado e as colunas em JSON são decodificadas."""
    return [{c: (json.loads(v) if c in em_json else v) for c, v in linha.items() if v is not None and c not in descartar}
            for linha in tabela.to_pylist()]


def _forma(g: dict):
    """Geometria shapely de um registro da gaveta `geometria` (`tipo` + `coords`); None se não montar."""
    from shapely import geometry as sg
    try:
        c = g["coords"]
        if g["tipo"] == "ponto":
            return sg.Point(c)
        if g["tipo"] == "linha":
            return sg.LineString(c)
        aneis = c if c and isinstance(c[0][0], (list, tuple)) else [c]
        return sg.Polygon(aneis[0], aneis[1:])
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def _meta_geo(geoms: list, crs_h: set) -> dict:
    """Metadados `geo` da especificação GeoParquet 1.1; `crs` em PROJJSON só se todos os registros têm o mesmo `crs_h`."""
    tipos = sorted({g.geom_type + (" Z" if g.has_z else "") for g in geoms if g is not None})
    coluna = {"encoding": "WKB", "geometry_types": tipos, "crs": None}
    if len(crs_h) == 1 and None not in crs_h:
        from pyproj import CRS
        coluna["crs"] = CRS.from_user_input(next(iter(crs_h))).to_json_dict()
    return {"version": "1.1.0", "primary_column": "geometry", "columns": {"geometry": coluna}}


def _com_geometria(tabela, regs: list[dict]):
    """Acrescenta a coluna `geometry` (WKB) e o metadado `geo` à tabela da gaveta `geometria`."""
    import pyarrow as pa
    import shapely
    geoms = [_forma(r) for r in regs]
    wkb = [None if g is None else shapely.to_wkb(g) for g in geoms]
    tabela = tabela.append_column("geometry", pa.array(wkb, type=pa.binary()))
    geo = _meta_geo(geoms, {r.get("crs_h") for r in regs})
    return tabela.replace_schema_metadata({**tabela.schema.metadata, b"geo": json.dumps(geo).encode()})


def _gravar_parquet(pasta: Path, base: dict, geo: bool = False) -> list[Path]:
    """`<gaveta>.parquet`; gaveta vazia não deixa arquivo (apaga o de uma gravação anterior)."""
    import pyarrow.parquet as pq
    feitos = []
    for gav in GAVETAS:
        regs, arq = base.get(gav, []), pasta / f"{gav}.parquet"
        if not regs:
            arq.unlink(missing_ok=True)
            continue
        tabela = _tabela(regs)
        pq.write_table(_com_geometria(tabela, regs) if geo and gav == "geometria" else tabela, arq)
        feitos.append(arq)
    return feitos


def _gravar_geoparquet(pasta: Path, base: dict) -> list[Path]:
    """Parquet com a coluna `geometry` em WKB e os metadados `geo` na gaveta `geometria`; `coords` segue guardado."""
    return _gravar_parquet(pasta, base, geo=True)


def _ler_parquet(pasta: Path, geo: bool = False) -> dict:
    import pyarrow.parquet as pq
    base = {}
    for gav in GAVETAS:
        arq = pasta / f"{gav}.parquet"
        if not arq.exists():
            base[gav] = []
            continue
        tabela = pq.read_table(arq)
        em_json = json.loads(tabela.schema.metadata[b"gavetas"])["json"]
        base[gav] = _registros(tabela, em_json, ("geometry",) if geo and gav == "geometria" else ())
    return base


def _ler_geoparquet(pasta: Path) -> dict:
    return _ler_parquet(pasta, geo=True)


def _tabela_sql(gaveta: str) -> str:
    """Nome de tabela seguro para o SQL: só gavetas de `conceitos/gavetas.json` (lista fechada, minúsculas e _)."""
    if gaveta not in REGRAS["gavetas"] or not re.fullmatch(r"[a-z_]+", gaveta):
        raise ValueError(f"gaveta {gaveta!r} não pode virar nome de tabela")
    return f'"{gaveta}"'


def _gravar_duckdb(pasta: Path, base: dict) -> list[Path]:
    """`base.duckdb`: uma tabela por gaveta (da mesma tabela arrow do parquet) e `_codificacao(gaveta, coluna)`."""
    import duckdb
    arq = pasta / "base.duckdb"
    con = duckdb.connect(str(arq))
    con.execute("DROP TABLE IF EXISTS _codificacao")
    con.execute("CREATE TABLE _codificacao (gaveta VARCHAR, coluna VARCHAR)")
    for gav in GAVETAS:
        con.execute(f"DROP TABLE IF EXISTS {_tabela_sql(gav)}")
        if not base.get(gav):
            continue
        tabela = _tabela(base[gav])
        con.register("_t", tabela)
        con.execute(f"CREATE TABLE {_tabela_sql(gav)} AS SELECT * FROM _t")  # nosec B608 — nome validado
        con.unregister("_t")
        em_json = json.loads(tabela.schema.metadata[b"gavetas"])["json"]
        for c in em_json:
            con.execute("INSERT INTO _codificacao VALUES (?, ?)", [gav, c])
    con.close()
    return [arq]


def _ler_duckdb(pasta: Path) -> dict:
    import duckdb
    arq = pasta / "base.duckdb"
    if not arq.exists():
        return {gav: [] for gav in GAVETAS}
    con = duckdb.connect(str(arq), read_only=True)
    existem = {t for (t,) in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    base = {}
    for gav in GAVETAS:
        if gav not in existem:
            base[gav] = []
            continue
        em_json = [c for (c,) in con.execute("SELECT coluna FROM _codificacao WHERE gaveta = ?", [gav]).fetchall()]
        consulta = f"SELECT * FROM {_tabela_sql(gav)} ORDER BY rowid"  # nosec B608 — nome validado por _tabela_sql
        base[gav] = _registros(con.sql(consulta).to_arrow_table(), em_json)
    con.close()
    return base


_GRAVAR = {"jsonl": _gravar_jsonl, "csv": _gravar_csv, "parquet": _gravar_parquet,
           "geoparquet": _gravar_geoparquet, "duckdb": _gravar_duckdb}
_LER = {"jsonl": _ler_jsonl, "csv": _ler_csv, "parquet": _ler_parquet,
        "geoparquet": _ler_geoparquet, "duckdb": _ler_duckdb}


def gravar(pasta, base: dict, formato: str | None = None) -> list[Path]:
    """Grava a base no formato (`formato.implementados`): um arquivo por gaveta, ou um `base.duckdb`. Devolve os arquivos."""
    formato = formato or REGRAS["formato"]["atual"]
    if formato not in REGRAS["formato"]["implementados"]:
        raise ValueError(f"formato {formato} não implementado: {REGRAS['formato']['implementados']}")
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    return _GRAVAR[formato](pasta, base)


def ler(pasta, formato: str | None = None) -> dict:
    """A base gravada por `gravar`; gaveta sem arquivo (ou sem tabela) volta vazia."""
    formato = formato or REGRAS["formato"]["atual"]
    pasta = Path(pasta)
    _conferir_formato_da_pasta(pasta, formato)
    return _LER[formato](pasta)


_EXTENSAO = {"jsonl": "*.jsonl", "csv": "*.csv", "parquet": "*.parquet", "geoparquet": "*.parquet", "duckdb": "base.duckdb"}


def _conferir_formato_da_pasta(pasta: Path, formato: str) -> None:
    """Pasta com gavetas de outro formato e nenhuma deste: erro, em vez de devolver a base vazia em silêncio."""
    if not pasta.is_dir() or any(pasta.glob(_EXTENSAO[formato])):
        return
    outros = sorted({f for f, padrao in _EXTENSAO.items() if any(pasta.glob(padrao))})
    if outros:
        raise ValueError(f"{pasta} não tem gavetas em {formato}, só em {', '.join(outros)}: passe o formato")


# --------------------------------------------------------------------------------------------------------------------
# Da gaveta ao serviço (de-para 2)
# --------------------------------------------------------------------------------------------------------------------

def fatos_do_objeto(base: dict, objeto_id: str) -> dict[str, dict]:
    """Um fato por propriedade: a natureza mais forte vence (decidido > observado > projetado > inferido)."""
    ordem = {n: i for i, n in enumerate(REGRAS["prioridade_natureza"])}
    escolhidos: dict[str, dict] = {}
    for f in base.get("fatos", []):
        if f["objeto_id"] != objeto_id:
            continue
        atual = escolhidos.get(f["propriedade"])
        if atual is None or ordem[f["natureza"]] <= ordem[atual["natureza"]]:
            escolhidos[f["propriedade"]] = f
    return escolhidos


def _geometria(base: dict, objeto_id: str) -> dict | None:
    return next((g for g in base.get("geometria", []) if g["objeto_id"] == objeto_id), None)


def furos(base: dict, classe: str) -> list[dict]:
    """Sondagens da classe no formato de `obras_lineares`: com ponto (E, N) ou sem geometria (E e N None, só pelo nome)."""
    saida = []
    for o in base.get("objetos", []):
        g = _geometria(base, o["objeto_id"])
        if o["classe"] != classe or (g and g["tipo"] != "ponto"):
            continue
        fatos = fatos_do_objeto(base, o["objeto_id"])
        xy = g["coords"][:2] if g else (None, None)           # sem geometria: só pelo nome citado (sem eixo)
        saida.append({"id": o["objeto_id"], "E": xy[0], "N": xy[1],
                      "na_m": fatos.get("na_m", {}).get("valor"), "camadas": fatos.get("camadas", {}).get("valor", []),
                      "fatos": [f["fato_id"] for f in fatos.values()]})
    return saida


def eixo(geometria: dict | None, passo_m: float = 1.0) -> np.ndarray | None:
    """Pontos do eixo a cada `passo_m` (meio de cada metro), em UTM; None sem linha."""
    if not geometria or geometria["tipo"] != "linha" or len(geometria["coords"]) < 2:
        return None
    xy = np.asarray(geometria["coords"], float)[:, :2]
    acum = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))])
    s = np.arange(passo_m / 2, acum[-1], passo_m)
    return np.column_stack([np.interp(s, acum, xy[:, 0]), np.interp(s, acum, xy[:, 1])])


def regra_de(classe: str, fatos: dict) -> str | None:
    """A regra do objeto pelo fato `metodo` (`quando`); sem o fato, a primeira regra da classe."""
    candidatas = [n for n, r in SERVICOS["regras"].items() if r["objeto"] == classe]
    metodo = ol.norm(fatos.get("metodo", {}).get("valor") or "")
    casou = [n for n in candidatas if metodo and ol.norm(SERVICOS["regras"][n]["quando"]["metodo"]) == metodo]
    return (casou or candidatas or [None])[0]


def entrada(base: dict, objeto: dict) -> dict:
    """Tudo o que a regra precisa, lido só das gavetas: dados, furos, eixo, fatos usados e o que falta."""
    fatos = fatos_do_objeto(base, objeto["objeto_id"])
    nome = regra_de(objeto["classe"], fatos)
    if nome is None:
        return {"regra": None}
    r = SERVICOS["regras"][nome]
    usados = [p for p in r["exige"] + r["opcionais"] if p in fatos]
    pts = eixo(_geometria(base, objeto["objeto_id"]))
    fs = furos(base, r["sondagens"]) if r.get("sondagens") else []
    dados = {"local": objeto["objeto_id"], **{p: fatos[p]["valor"] for p in usados}}
    if pts is not None:                          # com eixo: o furo mais próximo de cada metro
        perto = set(ol.furo_por_metro(pts, fs)) if fs else set()
        ids = {f["id"] for f in fs if f["id"] in perto}
    else:                                        # sem eixo: os furos citados em sond_ini/sond_fim (como `cobertura`)
        citados = {ol.id_furo(dados[p]) for p in ("sond_ini", "sond_fim") if dados.get(p)}
        ids = {f["id"] for f in fs if ol.id_furo(f["id"]) in citados}
    return {"regra": nome, "dados": dados, "furos": fs, "pts": pts, "furos_usados": [f for f in fs if f["id"] in ids],
            "faltam": [p for p in r["exige"] if p not in fatos],
            "fatos": [fatos[p]["fato_id"] for p in usados] + [i for f in fs if f["id"] in ids for i in f["fatos"]]}


def _servicos(objeto_id: str, nome: str, q: dict, fatos: list[str]) -> list[dict]:
    """Uma linha por saída da regra (dicionário abre uma linha por chave), com a memória de cálculo."""
    r, linhas = SERVICOS["regras"][nome], []
    for saida in r["saidas"]:
        valor = q.get(saida)
        partes = valor.items() if isinstance(valor, dict) else [(None, valor)]
        for chave, v in partes:
            if v is None:
                continue
            sid = ":".join(x for x in (objeto_id, nome, saida, chave) if x)
            linhas.append({"servico_id": sid, "objeto_id": objeto_id, "regra": nome, "versao_regra": r["versao"],
                           "saida": saida, **({"chave": chave} if chave else {}), "valor": v, "unidade": EAP["saidas"][saida]["unidade"],
                           "fatos": fatos})
    return linhas


def impressao_regra(regra: str) -> str:
    """sha1 curto do código do módulo da função da regra e das constantes dele (`REGRAS`, de `conceitos/`): mudar o
    empolamento, a Tabela I do MOS ou o próprio cálculo muda a chave, sem depender de alguém subir a `versao`."""
    if regra not in SERVICOS["regras"]:
        return ""
    modulo = importlib.import_module(SERVICOS["regras"][regra]["funcao"].rpartition(".")[0])
    # o módulo da regra e os módulos do projeto de que ele depende (ex.: obras_lineares → geotecnia, onde moram o
    # empolamento e as regras de solo desde a rodada 25): constante mudada em qualquer um deles muda a chave
    modulos = [modulo] + sorted((m for m in vars(modulo).values()
                                 if isinstance(m, types.ModuleType) and m.__name__.startswith("camadas.")),
                                key=lambda m: m.__name__)
    corpo = b"".join(Path(m.__file__).read_bytes() + json.dumps(
        [getattr(m, "REGRAS", None), getattr(m, "PREMISSAS", None)], sort_keys=True, default=str).encode("utf-8")
        for m in modulos)
    return hashlib.sha1(corpo, usedforsecurity=False).hexdigest()[:12]   # identidade do cálculo, não segurança


def chave_servico(regra: str, versao: str, dados: dict, fatos_usados: list[str], furos_usados: list[dict],
                  pts: np.ndarray | None = None, impressao: str | None = None) -> str:
    """sha1 curto (12 hex) de regra + versão + impressão da regra (código e constantes) + dados da regra + fato_id
    usados + furos usados (e os pontos do eixo)."""
    pontos = None if pts is None else np.round(np.asarray(pts, float), 3).tolist()
    corpo = {"regra": regra, "versao": versao, "impressao": impressao or impressao_regra(regra), "dados": dados,
             "fatos": list(fatos_usados), "furos": furos_usados, "pts": pontos}
    texto = json.dumps(corpo, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha1(texto, usedforsecurity=False).hexdigest()[:12]   # identidade do cálculo, não segurança


def _reaproveitavel(anterior: list[dict], objeto_id: str, regra: str, chave: str) -> list[dict] | None:
    """Serviços do `anterior` do mesmo objeto e regra, se todos têm a mesma chave; senão None."""
    antigos = [s for s in anterior if s["objeto_id"] == objeto_id and s["regra"] == regra]
    return antigos if antigos and all(s.get("chave_calculo") == chave for s in antigos) else None


def _calcular_objeto(o: dict, e: dict, chave: str) -> tuple[list[dict], list[dict]]:
    """Chama a função da regra; devolve os serviços (com `chave_calculo` e os alertas no 1º) e as pendências."""
    modulo, _, funcao = SERVICOS["regras"][e["regra"]]["funcao"].rpartition(".")
    q = getattr(importlib.import_module(modulo), funcao)(e["dados"], e["furos"], e["pts"])
    linhas = _servicos(o["objeto_id"], e["regra"], q, e["fatos"])
    alertas = list(q.get("alertas", []))
    for i, linha in enumerate(linhas):
        linha["chave_calculo"] = chave
        if alertas and i == 0:
            linha["alertas"] = alertas
    return linhas, [{"objeto_id": o["objeto_id"], "regra": e["regra"], "motivo": a} for a in alertas]


def calcular_incremental(base: dict, anterior: list[dict] | None = None) -> tuple[list[dict], list[dict], dict]:
    """Como `calcular`, mais {recalculados, reaproveitados} por objeto. Serviços do `anterior` com a mesma
    `chave_calculo` (e os alertas guardados no 1º serviço) voltam sem chamar a função da regra.
    O campo `chave` do serviço já é a subchave do dicionário (pavimento); o hash fica em `chave_calculo`."""
    servicos, pendencias, est = [], [], {"recalculados": 0, "reaproveitados": 0}
    impressoes = {r: impressao_regra(r) for r in SERVICOS["regras"]}      # uma leitura por regra e por cálculo
    for o in base.get("objetos", []):
        e = entrada(base, o)
        if e["regra"] is None:
            continue
        if e["faltam"]:
            pendencias.append({"objeto_id": o["objeto_id"], "regra": e["regra"],
                               "motivo": "faltam fatos obrigatórios: " + ", ".join(e["faltam"])})
            continue
        chave = chave_servico(e["regra"], SERVICOS["regras"][e["regra"]]["versao"], e["dados"], e["fatos"],
                              e["furos_usados"], e["pts"], impressoes[e["regra"]])
        antigos = _reaproveitavel(anterior or [], o["objeto_id"], e["regra"], chave)
        if antigos is not None:
            linhas = [dict(s) for s in antigos]
            pends = [{"objeto_id": o["objeto_id"], "regra": e["regra"], "motivo": a}
                     for s in linhas for a in s.get("alertas", [])]
            est["reaproveitados"] += 1
        else:
            linhas, pends = _calcular_objeto(o, e, chave)
            est["recalculados"] += 1
        servicos += linhas
        pendencias += pends
    return servicos, pendencias, est


def calcular(base: dict) -> tuple[list[dict], list[dict]]:
    """Serviços de todos os objetos com regra; faltou fato obrigatório: pendência e nenhum serviço do objeto."""
    return calcular_incremental(base)[:2]


def _achatar(saidas: dict, nomes: list[str]) -> dict[tuple, float]:
    """{(saída, chave): valor} das saídas pedidas; dicionário abre uma entrada por chave, None some."""
    plano = {}
    for saida in nomes:
        valor = saidas.get(saida)
        for chave, v in (valor.items() if isinstance(valor, dict) else [(None, valor)]):
            if v is not None:
                plano[(saida, chave)] = v
    return plano


GEOTECNIA = ["esgotamento_frac", "sem_sondagem_frac", "na_min_m", "categorias"]


def _diferencas(objeto_id: str, obtido: dict, esperado: dict, tol: float, prefixo: str = "") -> list[dict]:
    """Chaves em que os dois lados {(saída, chave): valor} diferem por mais de `tol` (lado ausente vem None)."""
    difs = []
    for saida, chave in sorted(set(esperado) | set(obtido), key=lambda k: (k[0], k[1] or "")):
        g, q = obtido.get((saida, chave)), esperado.get((saida, chave))
        if g is None or q is None or abs(g - q) > tol:
            difs.append({"objeto_id": objeto_id, "saida": prefixo + saida, "chave": chave, "gavetas": g, "obras_lineares": q})
    return difs


def _paridade_do_objeto(base: dict, o: dict, trecho: dict, furos: list[dict], obtido: dict, tol: float) -> list[dict]:
    """Um trecho: método, quantidades e geotecnia das gavetas contra o `quantificar` do trecho recebido."""
    e = entrada(base, o)
    if e["regra"] is None:
        return []
    metodo_regra = SERVICOS["regras"][e["regra"]]["quando"]["metodo"]
    metodo = trecho.get("metodo") or "VCA"
    q = ol.quantificar({**trecho, "metodo": metodo}, furos)
    difs = []
    if ol.norm(metodo) != ol.norm(metodo_regra):
        difs.append({"objeto_id": o["objeto_id"], "saida": "metodo", "chave": None, "gavetas": metodo_regra,
                     "obras_lineares": metodo})
    difs += _diferencas(o["objeto_id"], obtido, _achatar(q, SERVICOS["regras"][e["regra"]]["saidas"]), tol)
    if not e["faltam"]:                       # com fato obrigatório faltando as gavetas não calculam nada (há pendência)
        geo = ol.quantificar(e["dados"], e["furos"], e["pts"])["geotecnia"]
        difs += _diferencas(o["objeto_id"], _achatar(geo, GEOTECNIA), _achatar(q["geotecnia"], GEOTECNIA), tol,
                            "geotecnia.")
    return difs


def paridade(base: dict, trechos: list[dict], furos: list[dict], tol: float = 0.001,
             servicos: list[dict] | None = None) -> list[dict]:
    """Diferenças entre o cálculo das gavetas e o `obras_lineares.quantificar` dos trechos da planilha (`OL-<linha>`).

    O `quantificar` usa o `metodo` do trecho recebido (o aplicado, como no `obras_lineares.csv`); se ele difere do método
    da regra escolhida nas gavetas, sai a diferença `metodo`. Compara também a geotecnia (`geotecnia.<campo>`), com a
    `entrada` da base. Devolve só o que difere por mais de `tol`: {objeto_id, saida, chave, gavetas, obras_lineares}.
    `servicos`: os que foram gravados e vão para a EAP (inclusive os reaproveitados); sem eles, calcula a base.
    """
    servicos = calcular(base)[0] if servicos is None else servicos
    por_objeto: dict[str, dict] = {}
    for s in servicos:
        por_objeto.setdefault(s["objeto_id"], {})[(s["saida"], s.get("chave"))] = s["valor"]
    por_linha = {t["linha"]: t for t in trechos}
    difs = []
    for o in base.get("objetos", []):
        achou = re.fullmatch(r"OL-(\d+)", o["objeto_id"])
        trecho = por_linha.get(int(achou[1])) if achou and o["classe"] == "trecho_tubo" else None
        if trecho:
            difs += _paridade_do_objeto(base, o, trecho, furos, por_objeto.get(o["objeto_id"], {}), tol)
    return difs


# --------------------------------------------------------------------------------------------------------------------
# Do serviço à EAP (de-para 3)
# --------------------------------------------------------------------------------------------------------------------

def para_eap(servicos: list[dict]) -> list[dict]:
    """Soma por nó da EAP, com os serviços e objetos que a lastreiam (o caminho de volta até a evidência)."""
    nos: dict[str, dict] = {}
    for s in servicos:
        n = EAP["saidas"][s["saida"]]
        cod = f"{n['eap']}.{s['chave']}" if s.get("chave") else n["eap"]
        no = nos.setdefault(cod, {"eap": cod, "descricao": n["descricao"] + (f" — {s['chave']}" if s.get("chave") else ""),
                                  "unidade": n["unidade"], "valor": 0.0, "servicos": [], "objetos": []})
        no["valor"] = round(no["valor"] + s["valor"], 3)
        no["servicos"].append(s["servico_id"])
        no["objetos"] = list(dict.fromkeys(no["objetos"] + [s["objeto_id"]]))
    return [nos[k] for k in sorted(nos)]


def metadados() -> dict:
    """Rastreabilidade do método e das constantes (regra 9 do estilo)."""
    return {
        "modulo": "gavetas",
        "descricao": "memória espacial: gavetas com evidência, serviços calculados só a partir delas e EAP lastreada",
        "funcoes": ["validar", "conferir_base", "conferir_de_para", "gravar", "ler", "fatos_do_objeto", "furos",
                    "eixo", "regra_de", "entrada", "chave_servico", "calcular", "calcular_incremental", "paridade", "para_eap"],
        "conceitos": ["gavetas.json", "de_para_extracao.json", "de_para_servicos.json", "de_para_eap.json"],
        "formato": REGRAS["formato"]["atual"],
        "estado": REGRAS["metadata"]["estado"],
    }


def principal(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("pasta")
    p.add_argument("--formato", default=None)
    a = p.parse_args(argv)
    base = ler(a.pasta, a.formato)
    erros = conferir_base(base) + conferir_de_para()
    for e in erros:
        print("ERRO", e)
    servicos, pendencias = calcular(base)
    gravar(a.pasta, {**base, "servicos": servicos, "pendencias": base.get("pendencias", []) + pendencias}, a.formato)
    for no in para_eap(servicos):
        print(f"{no['eap']:<16} {no['descricao']:<55} {no['valor']:>12.3f} {no['unidade']}")
    print(f"{len(servicos)} serviços, {len(pendencias)} pendências, {len(erros)} erros")


if __name__ == "__main__":
    principal()
