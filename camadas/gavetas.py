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
import io
import json
import re
import types
import zipfile
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
              ("evidencias", "executor"): REGRAS["executores"], ("geometria", "tipo"): REGRAS["tipos_geometria"],
              ("superficies", "tipo"): REGRAS["tipos_superficie"]}
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
    erros += [f"superficies {s.get('superficie_id')}: evidência {s['evidencia_id']} não existe"
              for s in base.get("superficies", []) if s.get("evidencia_id") and s["evidencia_id"] not in evidencias]
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


# Superfícies (rodada 5): a grade do terreno não cabe em fato; vai para um .npz ao lado da base, com o sha256 no registro.

CHAVES_SUPERFICIE = ("terreno", "valido", "edificacao", "res", "e0", "n1", "forma")
_DATA_FIXA_ZIP = (1980, 1, 1, 0, 0, 0)          # data fixa das entradas do zip: os bytes não dependem do relógio


def _bytes_da_superficie(grade: dict) -> bytes:
    """`.npz` determinístico: entradas sem compressão, na ordem de `CHAVES_SUPERFICIE`, com data e atributos fixos
    (o `np.savez` grava a hora do relógio em cada entrada, e dois `gravar` dariam bytes diferentes)."""
    valores = {"terreno": np.ascontiguousarray(grade["terreno"]), "valido": np.ascontiguousarray(grade["valido"], bool),
               "edificacao": np.ascontiguousarray(grade["edificacao"], bool),
               "res": np.asarray(grade["res"], np.float64), "e0": np.asarray(grade["e0"], np.float64),
               "n1": np.asarray(grade["n1"], np.float64), "forma": np.asarray(grade["forma"], np.int64)}
    pacote = io.BytesIO()
    with zipfile.ZipFile(pacote, "w", zipfile.ZIP_STORED) as arquivo:
        for chave in CHAVES_SUPERFICIE:
            corpo = io.BytesIO()
            np.lib.format.write_array(corpo, valores[chave], allow_pickle=False)
            entrada_zip = zipfile.ZipInfo(f"{chave}.npy", date_time=_DATA_FIXA_ZIP)
            entrada_zip.compress_type, entrada_zip.create_system, entrada_zip.external_attr = zipfile.ZIP_STORED, 3, 0o600 << 16
            arquivo.writestr(entrada_zip, corpo.getvalue())
    return pacote.getvalue()


def gravar_superficie(pasta, superficie_id: str, grade: dict) -> dict:
    """Grava `superficies/<superficie_id>.npz` na pasta da base e devolve o registro da gaveta `superficies`.
    `grade`: terreno, valido, edificacao (matrizes), res, e0, n1, forma e epsg (o CRS horizontal). Duas gravações da
    mesma grade dão o mesmo sha256."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", superficie_id):
        raise ValueError(f"superficie_id {superficie_id!r} não serve de nome de arquivo")
    corpo = _bytes_da_superficie(grade)
    relativo = f"superficies/{superficie_id}.npz"
    destino = Path(pasta) / relativo
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(corpo)
    epsg = grade.get("epsg")
    return {"superficie_id": superficie_id, "tipo": "mds", "arquivo": relativo, "sha256": hashlib.sha256(corpo).hexdigest(),
            "crs_h": f"EPSG:{epsg}" if epsg else None, "datum_v": "ortométrico", "res_m": float(grade["res"]),
            "evidencia_id": f"EV-{superficie_id}"}


def ler_superficie(pasta, registro: dict) -> dict:
    """Carrega a grade de um registro da gaveta `superficies` e confere o sha256: `ValueError` se o arquivo mudou
    (ou sai da pasta da base); `FileNotFoundError` se não existe."""
    raiz = Path(pasta).resolve()
    arquivo = (raiz / registro["arquivo"]).resolve()
    if raiz not in arquivo.parents:
        raise ValueError(f"superfície {registro.get('superficie_id')}: arquivo {registro['arquivo']} fora da pasta da base")
    corpo = arquivo.read_bytes()
    if hashlib.sha256(corpo).hexdigest() != registro["sha256"]:
        raise ValueError(f"superfície {registro.get('superficie_id')}: sha256 de {registro['arquivo']} difere do registrado")
    with np.load(io.BytesIO(corpo), allow_pickle=False) as npz:
        grade = {chave: npz[chave] for chave in CHAVES_SUPERFICIE}
    return {**grade, "res": float(grade["res"]), "e0": float(grade["e0"]), "n1": float(grade["n1"]),
            "forma": tuple(int(x) for x in grade["forma"])}


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

def _evidencia_de_ia(evidencia: dict) -> bool:
    """Evidência de IA = método "IA" (a IA leu o documento). O executor não serve de critério: "Sonnet" ou "Haiku"
    também rodam leitores de código (método "json", "planilha", "geometria"), e esses fatos são determinísticos."""
    return evidencia.get("metodo") == "IA"


def evidencias_de_ia(base: dict) -> frozenset[str]:
    """Ids das evidências de IA da base."""
    return frozenset(e["evidencia_id"] for e in base.get("evidencias", []) if _evidencia_de_ia(e))


def _fato_de_ia(fato: dict, ia: frozenset[str] | set[str]) -> bool:
    """Fato apoiado em evidência de IA."""
    return fato["evidencia_id"] in ia


def _vencedores(fatos: list[dict], ia: frozenset[str] | set[str] = frozenset()) -> dict[str, dict]:
    """Um fato por propriedade: a natureza mais forte vence; em empate, o fato de código vence o de IA (`ia`: ids das
    evidências de IA) em qualquer ordem da lista, e entre iguais o último da lista."""
    ordem = {n: i for i, n in enumerate(REGRAS["prioridade_natureza"])}
    escolhidos: dict[str, dict] = {}
    for f in fatos:
        atual = escolhidos.get(f["propriedade"])
        if atual is None:
            escolhidos[f["propriedade"]] = f
            continue
        a, b = (ordem[f["natureza"]], _fato_de_ia(f, ia)), (ordem[atual["natureza"]], _fato_de_ia(atual, ia))
        if a <= b:                       # natureza mais forte; no empate, False (código) < True (IA)
            escolhidos[f["propriedade"]] = f
    return escolhidos


def _furo_do_objeto(o: dict, g: dict | None, fatos: dict) -> dict:
    xy = g["coords"][:2] if g else (None, None)           # sem geometria: só pelo nome citado (sem eixo)
    return {"id": o["objeto_id"], "E": xy[0], "N": xy[1],
            "na_m": fatos.get("na_m", {}).get("valor"), "camadas": fatos.get("camadas", {}).get("valor", []),
            "fatos": [f["fato_id"] for f in fatos.values()]}


def indice(base: dict) -> dict:
    """Monta uma vez o que `entrada` consulta por objeto: {"fatos": {objeto_id: vencedores por propriedade, de todos
    os fatos}, "fatos_codigo": {objeto_id: vencedores sem os fatos de IA, os que alimentam as regras}, "geometria":
    {objeto_id: 1ª geometria}, "furos": {classe: furos no formato de `furos`, só com fatos de código}, "furos_xy":
    {classe: `ol.furos_com_xy` dos furos}}. Passe-o como `ind`
    a `fatos_do_objeto`, `furos`, `entrada` e `paridade`: o resultado é o mesmo, sem varrer a base a cada objeto.
    Atenção: as listas e dicionários devolvidos com o índice são compartilhados, não cópias; não os altere."""
    ia = evidencias_de_ia(base)
    por_objeto: dict[str, list[dict]] = {}
    for f in base.get("fatos", []):
        por_objeto.setdefault(f["objeto_id"], []).append(f)
    fatos, codigo = {}, {}
    for oid, lista in por_objeto.items():
        fatos[oid] = _vencedores(lista, ia)
        de_codigo = [f for f in lista if not _fato_de_ia(f, ia)]
        codigo[oid] = fatos[oid] if len(de_codigo) == len(lista) else _vencedores(de_codigo, ia)
    geometria: dict[str, dict] = {}
    for g in base.get("geometria", []):
        geometria.setdefault(g["objeto_id"], g)
    por_classe: dict[str, list[dict]] = {}
    for o in base.get("objetos", []):
        g, de_codigo = geometria.get(o["objeto_id"]), codigo.get(o["objeto_id"], {})
        if (g and g["tipo"] != "ponto") or not (g or de_codigo):     # objeto só de IA não é insumo de regra
            continue
        por_classe.setdefault(o["classe"], []).append(_furo_do_objeto(o, g, de_codigo))
    return {"fatos": fatos, "fatos_codigo": codigo, "geometria": geometria, "furos": por_classe,
            "furos_xy": {c: ol.furos_com_xy(lista) for c, lista in por_classe.items()}}


def fatos_do_objeto(base: dict, objeto_id: str, ind: dict | None = None) -> dict[str, dict]:
    """Um fato por propriedade: a natureza mais forte vence (decidido > observado > projetado > inferido; em empate,
    o de código vence o de IA). Inclui os fatos de IA: eles ficam visíveis, mas não alimentam regra (`entrada`)."""
    if ind is not None:
        return ind["fatos"].get(objeto_id, {})
    return _vencedores([f for f in base.get("fatos", []) if f["objeto_id"] == objeto_id], evidencias_de_ia(base))


def fatos_de_codigo(base: dict, objeto_id: str, ind: dict | None = None) -> dict[str, dict]:
    """Como `fatos_do_objeto`, sem os fatos de IA: o que as regras podem usar (a IA só vira fato de regra depois de
    conferida por código ou por você, com outra evidência)."""
    if ind is not None:
        return ind["fatos_codigo"].get(objeto_id, {})
    ia = evidencias_de_ia(base)
    return _vencedores([f for f in base.get("fatos", []) if f["objeto_id"] == objeto_id and not _fato_de_ia(f, ia)], ia)


def _geometria(base: dict, objeto_id: str, ind: dict | None = None) -> dict | None:
    if ind is not None:
        return ind["geometria"].get(objeto_id)
    return next((g for g in base.get("geometria", []) if g["objeto_id"] == objeto_id), None)


def furos(base: dict, classe: str, ind: dict | None = None) -> list[dict]:
    """Sondagens da classe no formato de `obras_lineares`: com ponto (E, N) ou sem geometria (E e N None, só pelo nome).
    Objeto sem geometria e sem nenhum fato de código (criado só pela IA) não entra: não é insumo de regra."""
    if ind is not None:
        return ind["furos"].get(classe, [])
    saida = []
    for o in base.get("objetos", []):
        g = _geometria(base, o["objeto_id"])
        de_codigo = fatos_de_codigo(base, o["objeto_id"]) if o["classe"] == classe else {}
        if o["classe"] != classe or (g and g["tipo"] != "ponto") or not (g or de_codigo):   # só de IA: fora
            continue
        saida.append(_furo_do_objeto(o, g, de_codigo))
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
    casou = [n for n in candidatas if metodo and ol.norm(SERVICOS["regras"][n].get("quando", {}).get("metodo") or "") == metodo]
    return (casou or candidatas or [None])[0]


def _com_superficie(e: dict, base: dict, pasta_base) -> dict:
    """Regra que exige `superficie_id` (cavas): acha o registro na gaveta `superficies`, carrega a grade de
    `pasta_base/<arquivo>` (`ler_superficie`, que confere o sha256) e põe em `dados["superficie"]`. A chave do cálculo
    usa o sha256 e não a grade (`e["chave_dados"]`). Superfície ausente, ilegível ou adulterada: `e["erro"]` (pendência)."""
    sid = e["dados"]["superficie_id"]
    registro = next((s for s in base.get("superficies", []) if s.get("superficie_id") == sid), None)
    if registro is None:
        return {**e, "erro": f"superfície {sid} não está na gaveta superficies"}
    if pasta_base is None:
        return {**e, "erro": f"superfície {sid}: pasta da base não informada para ler {registro['arquivo']}"}
    try:
        grade = ler_superficie(pasta_base, registro)
    except (OSError, ValueError, KeyError) as erro:
        return {**e, "erro": f"superfície {sid} não pôde ser lida: {erro}"}
    return {**e, "dados": {**e["dados"], "superficie": grade},
            "chave_dados": {**e["dados"], "superficie_sha256": registro["sha256"]}}


def entrada(base: dict, objeto: dict, ind: dict | None = None, pasta_base=None) -> dict:
    """Tudo o que a regra precisa, lido só das gavetas: dados, furos, eixo, fatos usados e o que falta.
    `ind`: o `indice(base)`, para não varrer a base a cada objeto. `pasta_base`: a pasta da base gravada, de onde saem
    os arquivos da gaveta `superficies` (só as regras com `superficie_id` leem; sem ela a regra vira pendência)."""
    fatos = fatos_de_codigo(base, objeto["objeto_id"], ind)                  # fato de IA não alimenta regra
    nome = regra_de(objeto["classe"], fatos)
    if nome is None:
        return {"regra": None}
    r = SERVICOS["regras"][nome]
    usados = [p for p in r["exige"] + r["opcionais"] if p in fatos]
    pts = eixo(_geometria(base, objeto["objeto_id"], ind))
    fs = furos(base, r["sondagens"], ind) if r.get("sondagens") else []
    dados = {"local": objeto["objeto_id"], **{p: fatos[p]["valor"] for p in usados}}
    if pts is not None:                          # com eixo: o furo mais próximo de cada metro
        prep = ind["furos_xy"].get(r["sondagens"]) if ind is not None else None
        perto = set(ol.furo_por_metro(pts, fs, prep)) if fs else set()
        ids = {f["id"] for f in fs if f["id"] in perto}
    else:                                        # sem eixo: os furos citados em sond_ini/sond_fim (como `cobertura`)
        citados = {ol.id_furo(dados[p]) for p in ("sond_ini", "sond_fim") if dados.get(p)}
        ids = {f["id"] for f in fs if ol.id_furo(f["id"]) in citados}
    faltam = [p for p in r["exige"] if p not in fatos]
    so_ia = [p for p in faltam if p in fatos_do_objeto(base, objeto["objeto_id"], ind)]    # existe, mas só como IA
    e = {"regra": nome, "dados": dados, "furos": fs, "pts": pts, "furos_usados": [f for f in fs if f["id"] in ids],
         "faltam": faltam, "depende_de_ia": so_ia,
         "fatos": [fatos[p]["fato_id"] for p in usados] + [i for f in fs if f["id"] in ids for i in f["fatos"]]}
    return _com_superficie(e, base, pasta_base) if "superficie_id" in dados and not faltam else e


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
                           "fatos": fatos, **({"ponto": q["pontos"][chave]} if chave in (q.get("pontos") or {}) else {})})
    return linhas


def impressao_regra(regra: str) -> str:
    """sha1 curto do código e das constantes (`REGRAS`, `PREMISSAS`, de `conceitos/`) do módulo da função da regra e
    de todos os módulos `camadas.*` de que ele depende, direta ou indiretamente (fecho transitivo dos módulos
    importados no topo e dos declarados em `DEPENDENCIAS`, com conjunto de visitados, em ordem de nome): mudar o empolamento, a Tabela I do MOS, uma
    premissa do dimensionador ou o próprio cálculo muda a chave, sem depender de alguém subir a `versao`."""
    if regra not in SERVICOS["regras"]:
        return ""
    # o grafo de módulos do projeto (ex.: obras_lineares → lineares → geotecnia; obras_lineares → valas → geo):
    # constante mudada em qualquer um deles, a qualquer distância, muda a chave
    visitados: dict[str, types.ModuleType] = {}
    pendentes = [importlib.import_module(SERVICOS["regras"][regra]["funcao"].rpartition(".")[0])]
    while pendentes:
        modulo = pendentes.pop()
        if modulo.__name__ in visitados:
            continue
        visitados[modulo.__name__] = modulo
        pendentes += [m for m in vars(modulo).values()
                      if isinstance(m, types.ModuleType) and m.__name__.startswith("camadas.")]
        # os importados só dentro das funções (ex.: lineares → obras_lineares), declarados em DEPENDENCIAS
        pendentes += [importlib.import_module(nome) for nome in getattr(modulo, "DEPENDENCIAS", ())]
    modulos = [visitados[nome] for nome in sorted(visitados)]
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


def _indexar_anterior(anterior: list[dict]) -> dict[tuple, list[dict]]:
    """Serviços do `anterior` agrupados por (objeto_id, regra), na ordem original."""
    grupos: dict[tuple, list[dict]] = {}
    for s in anterior:
        grupos.setdefault((s["objeto_id"], s["regra"]), []).append(s)
    return grupos


def _reaproveitavel(anterior: dict[tuple, list[dict]], objeto_id: str, regra: str, chave: str) -> list[dict] | None:
    """Serviços do `anterior` (de `_indexar_anterior`) do mesmo objeto e regra, se todos têm a mesma chave; senão None."""
    antigos = anterior.get((objeto_id, regra), [])
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


def _pendencias_de_falta(objeto_id: str, e: dict) -> list[dict]:
    """Pendências de um objeto sem todos os obrigatórios: os ausentes de verdade e os que só existem como fato de IA
    (esses não são ausentes, mas também não foram conferidos)."""
    ausentes = [p for p in e["faltam"] if p not in e["depende_de_ia"]]
    motivos = ([f"faltam fatos obrigatórios: {', '.join(ausentes)}"] if ausentes else []) + (
        [f"depende de fato de IA não conferido: {', '.join(e['depende_de_ia'])}"] if e["depende_de_ia"] else [])
    return [{"objeto_id": objeto_id, "regra": e["regra"], "motivo": m} for m in motivos]


def calcular_incremental(base: dict, anterior: list[dict] | None = None,
                         pasta_base=None) -> tuple[list[dict], list[dict], dict]:
    """Como `calcular`, mais {recalculados, reaproveitados} por objeto. Serviços do `anterior` com a mesma
    `chave_calculo` (e os alertas guardados no 1º serviço) voltam sem chamar a função da regra.
    O campo `chave` do serviço já é a subchave do dicionário (pavimento); o hash fica em `chave_calculo`.
    `pasta_base`: onde estão os arquivos das superfícies (regra `cavas`); a chave leva o sha256 da superfície."""
    servicos, pendencias, est = [], [], {"recalculados": 0, "reaproveitados": 0}
    impressoes = {r: impressao_regra(r) for r in SERVICOS["regras"]}      # uma leitura por regra e por cálculo
    ind, antigos_por_chave = indice(base), _indexar_anterior(anterior or [])
    for o in base.get("objetos", []):
        e = entrada(base, o, ind, pasta_base)
        if e["regra"] is None:
            continue
        if e["faltam"]:
            pendencias += _pendencias_de_falta(o["objeto_id"], e)
            continue
        if e.get("erro"):                         # superfície ausente ou adulterada: pendência, nenhum serviço
            pendencias.append({"objeto_id": o["objeto_id"], "regra": e["regra"], "motivo": e["erro"]})
            continue
        chave = chave_servico(e["regra"], SERVICOS["regras"][e["regra"]]["versao"], e.get("chave_dados", e["dados"]), e["fatos"],
                              e["furos_usados"], e["pts"], impressoes[e["regra"]])
        antigos = _reaproveitavel(antigos_por_chave, o["objeto_id"], e["regra"], chave)
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


def calcular(base: dict, pasta_base=None) -> tuple[list[dict], list[dict]]:
    """Serviços de todos os objetos com regra; faltou fato obrigatório: pendência e nenhum serviço do objeto."""
    return calcular_incremental(base, pasta_base=pasta_base)[:2]


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


def _paridade_do_objeto(base: dict, o: dict, trecho: dict, furos: list[dict], obtido: dict, tol: float,
                        ind: dict | None = None) -> list[dict]:
    """Um trecho: método, quantidades e geotecnia das gavetas contra o `quantificar` do trecho recebido."""
    e = entrada(base, o, ind)
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
    difs, ind = [], indice(base)
    for o in base.get("objetos", []):
        achou = re.fullmatch(r"OL-(\d+)", o["objeto_id"])
        trecho = por_linha.get(int(achou[1])) if achou and o["classe"] == "trecho_tubo" else None
        if trecho:
            difs += _paridade_do_objeto(base, o, trecho, furos, por_objeto.get(o["objeto_id"], {}), tol, ind)
    return difs


# --------------------------------------------------------------------------------------------------------------------
# Do serviço à EAP (de-para 3)
# --------------------------------------------------------------------------------------------------------------------

def para_eap(servicos: list[dict]) -> list[dict]:
    """Soma por nó da EAP, com os serviços e objetos que a lastreiam (o caminho de volta até a evidência)."""
    nos: dict[str, dict] = {}
    vistos: dict[str, set] = {}                    # objetos já listados por nó (ordem da 1ª aparição)
    for s in servicos:
        n = EAP["saidas"][s["saida"]]
        cod = f"{n['eap']}.{s['chave']}" if s.get("chave") else n["eap"]
        no = nos.setdefault(cod, {"eap": cod, "descricao": n["descricao"] + (f" — {s['chave']}" if s.get("chave") else ""),
                                  "unidade": n["unidade"], "valor": 0.0, "servicos": [], "objetos": []})
        no["valor"] = round(no["valor"] + s["valor"], 3)
        no["servicos"].append(s["servico_id"])
        if s["objeto_id"] not in vistos.setdefault(cod, set()):
            vistos[cod].add(s["objeto_id"])
            no["objetos"].append(s["objeto_id"])
    return [nos[k] for k in sorted(nos)]


# --------------------------------------------------------------------------------------------------------------------
# Setores da obra localizada (rodada 5): organiza a consulta e a EAP; não muda nenhuma quantidade
# --------------------------------------------------------------------------------------------------------------------

TOLERANCIA_SOMA_SETORES = 0.005         # unidade do nó: os totais são arredondados a 3 casas passo a passo


def _ponto_representativo(forma):
    """Ponto: ele mesmo; linha: o meio do comprimento; polígono: `representative_point`."""
    if forma.geom_type == "Point":
        return forma
    if forma.geom_type == "LineString":
        return forma.interpolate(0.5, normalized=True)
    return forma.representative_point()


def _formas_dos_setores(base: dict, geometrias: dict) -> dict:
    """{setor_id: polígono shapely} dos objetos de classe `setor` com geometria válida, na ordem da base."""
    formas = {}
    for o in base.get("objetos", []):
        g = geometrias.get(o["objeto_id"])
        forma = _forma(g) if o["classe"] == "setor" and g else None
        if forma is not None and forma.geom_type == "Polygon" and forma.is_valid and not forma.is_empty:
            formas[o["objeto_id"]] = forma
    return formas


def _setor_do_ponto(ponto, setores: dict) -> tuple[str | None, list[str]]:
    """(setor, sobrepostos). Dentro (`contains`) de um setor só: ele. Dentro de dois ou mais: None e a sobreposição.
    Só na divisa (`covers` sem `contains`, comum entre setores vizinhos): o 1º declarado no obra.json, sem pendência."""
    dentro = [sid for sid, poligono in setores.items() if poligono.contains(ponto)]
    if len(dentro) > 1:
        return None, dentro
    if dentro:
        return dentro[0], []
    na_divisa = [sid for sid, poligono in setores.items() if poligono.covers(ponto)]
    return (na_divisa[0] if na_divisa else None), []


def setor_de(base: dict, ind: dict | None = None) -> tuple[dict[str, str | None], list[dict]]:
    """Setor de cada objeto com geometria que não é `setor`, pelo ponto representativo (ponto, meio da linha,
    `representative_point`). Fora de todos os setores: None. Em dois ou mais: None e pendência "setores sobrepostos".
    Objeto sem geometria não aparece. Determinístico, na ordem dos objetos."""
    from shapely import geometry as sg
    if ind is not None:
        geometrias = ind["geometria"]
    else:
        geometrias = {}
        for g in base.get("geometria", []):
            geometrias.setdefault(g["objeto_id"], g)
    setores = _formas_dos_setores(base, geometrias)
    mapa: dict[str, str | None] = {}
    pendencias: list[dict] = []
    for o in base.get("objetos", []):
        g = geometrias.get(o["objeto_id"])
        forma = _forma(g) if g and o["classe"] != "setor" else None
        if forma is None or forma.is_empty:
            continue
        sid, sobrepostos = _setor_do_ponto(sg.Point(_ponto_representativo(forma).coords[0]), setores)
        mapa[o["objeto_id"]] = sid
        if sobrepostos:
            pendencias.append({"objeto_id": o["objeto_id"], "motivo": f"setores sobrepostos: {', '.join(sobrepostos)}"})
    return mapa, pendencias


def setor_dos_servicos(base: dict, servicos: list[dict]) -> tuple[dict[str, str | None], list[dict]]:
    """Setor de cada serviço que tem `ponto` (ex.: cada cava de um `conjunto_cavas`, que é um objeto só): o serviço
    cai no setor que contém o seu ponto. Mesma regra de `setor_de` (sobreposição: None e pendência). Chave: servico_id."""
    from shapely import geometry as sg
    geometrias = {}
    for g in base.get("geometria", []):
        geometrias.setdefault(g["objeto_id"], g)
    setores = _formas_dos_setores(base, geometrias)
    mapa: dict[str, str | None] = {}
    pendencias: list[dict] = []
    for s in servicos:
        if not s.get("ponto"):
            continue
        sid, sobrepostos = _setor_do_ponto(sg.Point(s["ponto"]), setores)
        mapa[s["servico_id"]] = sid
        if sobrepostos:
            pendencias.append({"objeto_id": s["servico_id"], "motivo": f"setores sobrepostos: {', '.join(sobrepostos)}"})
    return mapa, pendencias


def para_eap_por_setor(servicos: list[dict], setor_por_objeto: dict[str, str | None],
                       ordem_setores: list[str] | None = None) -> list[dict]:
    """EAP somada por setor: [{setor_id, nos: [{eap, descricao, unidade, valor, n_servicos}]}], na ordem dos
    setores (`ordem_setores`; sem ela, a da 1ª aparição no mapa) e por fim o "fora dos setores" (setor_id None, que
    também recebe o objeto sem geometria). Todo serviço cai em exatamente um grupo."""
    ordem = list(ordem_setores) if ordem_setores is not None else []
    for sid in setor_por_objeto.values():
        if sid is not None and sid not in ordem:
            ordem.append(sid)
    grupos: dict[str | None, list[dict]] = {sid: [] for sid in ordem} | {None: []}
    for s in servicos:
        sid = setor_por_objeto.get(s["servico_id"], setor_por_objeto.get(s["objeto_id"]))   # o do serviço vence
        grupos[sid if sid in grupos else None].append(s)
    return [{"setor_id": sid, "nos": [{"eap": n["eap"], "descricao": n["descricao"], "unidade": n["unidade"],
                                       "valor": n["valor"], "n_servicos": len(n["servicos"])} for n in para_eap(lista)]}
            for sid, lista in grupos.items()]


# --------------------------------------------------------------------------------------------------------------------
# Código completo da EAP codificada (rodada 6): UNIDADE.SISTEMA.DISCIPLINA.PACOTE.ITEM em cada serviço
# --------------------------------------------------------------------------------------------------------------------

UNIDADES_CONSTRUTIVAS = _ler("unidades_construtivas")


def _no_eap(servico: dict) -> dict | None:
    """`codigo_eap` do de-para 3 da saída do serviço (item, por_chave, servicos); None = sem item na EAP codificada."""
    return EAP["saidas"][servico["saida"]].get("codigo_eap")


def _item_eap(servico: dict) -> str | None:
    """Item `DISCIPLINA.PACOTE.ITEM` do serviço: `por_chave` troca o item pela chave (vale o prefixo antes de '/')."""
    no = _no_eap(servico)
    if not no:
        return None
    prefixo = str(servico.get("chave") or "").split("/", 1)[0]
    return no.get("por_chave", {}).get(prefixo, no["item"])


def codigo_eap(servico: dict, unidade: str | None, sistema: str | None) -> str | None:
    """Código completo `UNIDADE.SISTEMA.ITEM`, o mesmo formato de `eap.estrutura` (unidade em maiúsculas, sistema como
    em `unidades_construtivas.json`; ex.: `U1.AB_ENTRADA.GEO.MOV.VAL`). None se a saída não tem item na EAP codificada
    ou se falta a unidade ou o sistema (quem chama distingue os dois casos)."""
    item = _item_eap(servico)
    return f"{unidade.upper()}.{sistema}.{item}" if item and unidade and sistema else None


def _motivo_do_par(unidade: str, sistema: str) -> str | None:
    """Motivo da pendência se o sistema não existe em `unidades_construtivas.json` ou não é da unidade; senão None."""
    cadastro = UNIDADES_CONSTRUTIVAS["sistemas"].get(sistema)
    if cadastro is None:
        return f"sistema {sistema} não existe em unidades_construtivas"
    if str(unidade).lower() != cadastro["unidade"]:
        return f"sistema {sistema} não pertence à unidade {unidade}"
    return None


def _sistemas_do_local(local: str) -> list[str]:
    """Sistemas cujas `chaves` o texto do `local` cita (a regra de `escopo_obra`, com a chave ambígua e o `exclui`)."""
    from . import escopo_obra
    texto = escopo_obra._norm(str(local))
    return [c for c in UNIDADES_CONSTRUTIVAS["sistemas"] if escopo_obra._casa(c, texto)]


def _par_do_objeto(fatos: dict, fatos_setor: dict, padrao: dict | None) -> tuple[tuple[str, str] | None, str | None]:
    """((unidade, sistema), None) ou (None, motivo). Ordem: (a) fatos do setor, (b) `local` com as chaves,
    (c) padrão do obra.json. Achado o par em uma fonte, as seguintes não são consultadas."""
    if fatos_setor.get("unidade") and fatos_setor.get("sistema"):
        par = (str(fatos_setor["unidade"]["valor"]), str(fatos_setor["sistema"]["valor"]))
    elif "local" in fatos and (achados := _sistemas_do_local(fatos["local"]["valor"])):
        if len(achados) > 1:
            return None, f"mais de um sistema pelo local: {', '.join(achados)}"
        par = (UNIDADES_CONSTRUTIVAS["sistemas"][achados[0]]["unidade"], achados[0])
    elif padrao and padrao.get("unidade") and padrao.get("sistema"):
        par = (str(padrao["unidade"]), str(padrao["sistema"]))
    else:
        return None, "unidade e sistema não definidos"
    motivo = _motivo_do_par(*par)
    return (None, motivo) if motivo else (par, None)


def unidade_sistema(base: dict, ind: dict | None, cfg: dict, setor_por_servico: dict | None = None,
                    servicos: list[dict] | None = None) -> tuple[dict, list[dict]]:
    """({objeto_id: (unidade, sistema)}, pendências) dos objetos com regra de serviço (fora os `setor`). Busca: (a) fatos
    `unidade` e `sistema` do setor do objeto (`setor_de`), (b) `local` casado com as `chaves` de
    `unidades_construtivas.json`, (c) `cfg["gavetas"]["unidade_sistema_padrao"]`. Sem nenhuma, com mais de um sistema
    pelo local ou com sistema de outra unidade: pendência, sem par. Com `servicos` e `setor_por_servico`
    (`setor_dos_servicos`), o serviço com `ponto` cujo setor declara unidade e sistema entra no mapa pelo seu
    `servico_id`, que vale mais que o do objeto."""
    ind = ind or indice(base)
    padrao = (cfg.get("gavetas") or {}).get("unidade_sistema_padrao")
    setor_por_objeto, _ = setor_de(base, ind)
    mapa, pendencias = {}, []
    for o in base.get("objetos", []):
        fatos = ind["fatos"].get(o["objeto_id"], {})
        if o["classe"] == "setor" or regra_de(o["classe"], fatos) is None:
            continue
        setor = setor_por_objeto.get(o["objeto_id"])
        par, motivo = _par_do_objeto(fatos, ind["fatos"].get(setor, {}) if setor else {}, padrao)
        if par:
            mapa[o["objeto_id"]] = par
        else:
            pendencias.append({"objeto_id": o["objeto_id"], "regra": regra_de(o["classe"], fatos), "motivo": motivo})
    for s in servicos or []:
        fatos_setor = ind["fatos"].get((setor_por_servico or {}).get(s["servico_id"]) or "", {})
        if fatos_setor.get("unidade") and fatos_setor.get("sistema"):
            par, motivo = _par_do_objeto({}, fatos_setor, None)
            if par:
                mapa[s["servico_id"]] = par
            else:
                pendencias.append({"objeto_id": s["servico_id"], "regra": s["regra"], "motivo": motivo})
    return mapa, pendencias


def anotar_codigo_eap(servicos: list[dict], mapa: dict, pendencias: list[dict]) -> tuple[dict, list[dict]]:
    """Grava `codigo_eap` (completo ou None) e `servicos_eap` (os serviços da EAP codificada) em cada serviço; é anotação,
    não entra na chave do incremental. Devolve ({saída: n} dos serviços sem item na EAP codificada, pendências de
    quem tem item mas não tem unidade e sistema, e de quem teria um código fora de `eap.estrutura`: o item não vale
    para o tipo de obra ou o escopo da unidade, e o código não é gravado)."""
    from . import eap  # a estrutura instanciada: só os itens do tipo de obra da unidade
    validos = {n["codigo"] for n in eap.estrutura() if n["nivel"] == "item"}
    sem_codigo: dict[str, int] = {}
    sem_par: set[str] = set()
    fora: dict[str, dict] = {}
    for s in servicos:
        no = _no_eap(s)
        par = mapa.get(s["servico_id"]) or mapa.get(s["objeto_id"])
        s["servicos_eap"] = list(no["servicos"]) if no else []
        s["codigo_eap"] = codigo_eap(s, *par) if par else None
        if s["codigo_eap"] and s["codigo_eap"] not in validos:   # ex.: cava (obra localizada) numa unidade linear
            fora.setdefault(s["objeto_id"], {"objeto_id": s["objeto_id"], "motivo": (
                f"item não pertence à unidade: {s['codigo_eap']} não existe na EAP codificada (tipo de obra ou escopo)")})
            s["codigo_eap"] = None
        if no is None:
            sem_codigo[s["saida"]] = sem_codigo.get(s["saida"], 0) + 1
        elif par is None:
            sem_par |= {s["servico_id"], s["objeto_id"]}
    return sem_codigo, [p for p in pendencias if p["objeto_id"] in sem_par] + list(fora.values())


def conciliar_eap(servicos: list[dict], quantidades_codificada: list[dict], tol: float = 0.01) -> list[dict]:
    """Confronta, por (código completo, unidade), a soma das gavetas com a quantidade da EAP codificada
    (`dados["eap"]["quantidades"]`). Situação: "confere" (diferença absoluta até `tol`, na unidade), "difere",
    "só nas gavetas", "só na EAP codificada" (item que as gavetas medem) ou "fora das gavetas" (item que elas não
    medem, ex.: estacas). Só entra a saída marcada `mede` no de-para 3 (a medida do item), para não somar serviços
    diferentes do mesmo código. Unidades diferentes nunca se misturam. Ordem: código, unidade."""
    medida = {saida for saida, n in EAP["saidas"].items() if (n.get("codigo_eap") or {}).get("mede")}
    itens = {(n["codigo_eap"]["item"]) for n in EAP["saidas"].values() if (n.get("codigo_eap") or {}).get("mede")}
    tocados = {s["codigo_eap"].split(".", 2)[-1] for s in servicos if s.get("codigo_eap")}
    gavetas_: dict[tuple, float] = {}
    for s in servicos:
        if s.get("codigo_eap") and s["saida"] in medida:          # só a medida do item (`mede`), nada somado de fora
            chave = (s["codigo_eap"], s["unidade"])
            gavetas_[chave] = gavetas_.get(chave, 0.0) + float(s["valor"])
    codificada: dict[tuple, float] = {}
    for q in quantidades_codificada:
        chave = (q["codigo"], q["unidade"])
        codificada[chave] = codificada.get(chave, 0.0) + float(q["quantidade"])
    linhas = []
    for chave in sorted(gavetas_.keys() | codificada.keys()):
        g, c = gavetas_.get(chave), codificada.get(chave)
        dif = None if g is None or c is None else g - c
        item = chave[0].split(".", 2)[-1]
        coberto = item in itens                                     # o item é medido pelas gavetas (`mede`)?
        sem_medida = item in tocados and not coberto                # as gavetas têm o item, mas sem medida declarada
        situacao = ("não conciliado (sem medida declarada)" if g is None and sem_medida
                    else "fora das gavetas" if g is None and not coberto else "só na EAP codificada" if g is None
                    else "só nas gavetas" if c is None else "confere" if abs(dif) <= tol else "difere")
        linhas.append({"codigo": chave[0], "unidade": chave[1], "gavetas": g, "codificada": c, "diferenca": dif,
                       "situacao": situacao})
    return linhas


def metadados() -> dict:
    """Rastreabilidade do método e das constantes (regra 9 do estilo)."""
    return {
        "modulo": "gavetas",
        "descricao": "memória espacial: gavetas com evidência, serviços calculados só a partir delas e EAP lastreada",
        "funcoes": ["validar", "conferir_base", "conferir_de_para", "gravar", "ler", "gravar_superficie", "ler_superficie",
                    "fatos_do_objeto", "furos", "eixo", "regra_de", "entrada", "chave_servico", "calcular",
                    "calcular_incremental", "paridade", "para_eap", "setor_de", "setor_dos_servicos",
                    "para_eap_por_setor", "codigo_eap", "unidade_sistema", "anotar_codigo_eap", "conciliar_eap"],
        "conceitos": ["gavetas.json", "de_para_extracao.json", "de_para_servicos.json", "de_para_eap.json",
                      "unidades_construtivas.json"],
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
    servicos, pendencias = calcular(base, a.pasta)
    gravar(a.pasta, {**base, "servicos": servicos, "pendencias": base.get("pendencias", []) + pendencias}, a.formato)
    for no in para_eap(servicos):
        print(f"{no['eap']:<16} {no['descricao']:<55} {no['valor']:>12.3f} {no['unidade']}")
    print(f"{len(servicos)} serviços, {len(pendencias)} pendências, {len(erros)} erros")


if __name__ == "__main__":
    principal()
