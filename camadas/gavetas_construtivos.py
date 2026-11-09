"""Elementos construtivos → gavetas (F2 da reconstrução, docs/RECONSTRUCAO.md §3).

Os 464 elementos de Foz (estacas, blocos, pilares, cavas, trechos de rede, manchas de etapa) saíam só em
`dados["construtivos"]`. Aqui cada elemento vira um objeto, com a geometria em UTM, os fatos dos atributos e a evidência
na página da prancha (retângulo em pt pela inversa da afim `M` da prancha). Nada é inventado e nada é descartado em
silêncio: atributo sem propriedade em `conceitos/gavetas.json`, prancha sem documento e prancha sem afim viram pendência.

    python -m camadas.gavetas_construtivos saida/foz/dados.json exemplos/foz/obra.json

Só lê; não grava em `saida/`.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

import numpy as np
from shapely import geometry as sg
from shapely import ops as so

from . import gavetas, geo
from .pdf_cad import CONCEITOS

# rótulo do atributo no elemento → (propriedade de gavetas.json, fator para a unidade da propriedade, natureza)
ROTULOS = {
    "Estacas": ("estacas_n", 1.0, "projetado"),
    "Face superior (cota, m)": ("cota_topo_m", 1.0, "projetado"),
    "Arrasamento (cota, m)": ("cota_arrasamento_m", 1.0, "projetado"),
    "Fundo (cota, m)": (
        "cota_fundo_m",
        1.0,
        "projetado",
    ),  # faixa "a a b" não é número: vira pendência
    "Diâmetro nominal (cm)": ("diametro_m", 0.01, "projetado"),
    "Comprimento (m)": ("comprimento_m", 1.0, "projetado"),
    "Área (m²)": ("area_planta_m2", 1.0, "projetado"),
    "Profundidade média (m)": ("prof_m", 1.0, "projetado"),
    "Diâmetro (mm)": ("dn_mm", 1.0, "projetado"),
    "Extensão estimada (m)": (
        "extensao_m",
        1.0,
        "inferido",
    ),  # repartida pela posição na janela da planta
    "Escavação (m³)": (
        "escavacao_m3",
        1.0,
        "inferido",
    ),  # calculada pela topografia (camadas.escavacao)
    "Reaterro (m³)": ("reaterro_m3", 1.0, "inferido"),
    "Item do contrato": (
        "material",
        1.0,
        "inferido",
    ),  # descrição do item de tubo casado no contrato: o material que a vala (MOS) lê
}
SUPERFICIES = {
    f"{v['nome']} (m)": classe
    for classe, v in json.loads((CONCEITOS / "valas.json").read_text(encoding="utf-8"))[
        "classes"
    ].items()
}
"""Rótulo do atributo de metros por superfície do trecho ('Pista (leito carroçável) (m)') → classe de `valas.json`;
os metros viram um fato só, `pavimentos` ({classe: m}), o que a vala lê."""
ATRIBUTOS_NA_GEOMETRIA = (
    "E (m)",
    "N (m)",
)  # a posição da estaca é a própria geometria do objeto
TOLERANCIA_AREA_M2 = (
    1.0  # área do atributo × geometria: acima disto e de 2 % vira pendência
)
TOLERANCIA_AREA_REL = 0.02
CRS_VERTICAL = "ortométrico"


def _chave_documento(nome: str) -> str:
    """Nome do arquivo sem a extensão .pdf (qualquer caixa) e normalizado: casa 'x.pdf', 'x.PDF' e 'x'."""
    return re.sub(
        r"\.pdf$",
        "",
        unicodedata.normalize("NFC", str(nome)).strip(),
        flags=re.IGNORECASE,
    )


def _matriz(afim) -> np.ndarray | None:
    """Afim pt → UTM como 3x3 a partir de 6 valores (linha a linha) ou 3x3/2x3; None se ausente ou singular."""
    if afim is None:
        return None
    v = np.asarray(afim, float)
    if v.size == 6:
        m = np.vstack([v.reshape(2, 3), [0.0, 0.0, 1.0]])
    elif v.size == 9:
        m = v.reshape(3, 3)
    else:
        return None
    return m if abs(np.linalg.det(m[:2, :2])) > 1e-18 else None


def _partes(geometria) -> list[np.ndarray]:
    """Todos os vértices (lon, lat) do GeoJSON como matrizes Nx2, uma por anel ou parte."""
    tipo, c = geometria["type"], geometria["coordinates"]
    if tipo == "Point":
        return [np.asarray([c], float)]
    if tipo == "LineString":
        return [np.asarray(c, float)]
    if tipo == "MultiLineString":
        return [np.asarray(p, float) for p in c]
    if tipo == "Polygon":
        return [np.asarray(a, float) for a in c]
    raise ValueError(f"geometria {tipo} não prevista")


def _utm(partes: list[np.ndarray], epsg: int) -> list[np.ndarray]:
    """Vértices lon/lat → UTM (E, N) em m, arredondados ao mm."""
    saida = []
    for p in partes:
        e, n = geo.para_utm(p[:, 0], p[:, 1], epsg)
        saida.append(np.round(np.column_stack([e, n]), 3))
    return saida


def _registro_geometria(
    objeto_id: str, geometria: dict, utm: list[np.ndarray], epsg: int
) -> tuple[dict, tuple | None]:
    """Registro da gaveta `geometria` e o aviso (motivo, detalhe) de perda. Multilinha: o contrato só tem uma linha, fica a mais longa."""
    tipo, base = (
        geometria["type"],
        {"objeto_id": objeto_id, "crs_h": f"EPSG:{epsg}", "datum_v": CRS_VERTICAL},
    )
    if tipo == "Point":
        return {**base, "tipo": "ponto", "coords": utm[0][0].tolist()}, None
    if tipo == "Polygon":
        aneis = [a.tolist() for a in utm]
        return {
            **base,
            "tipo": "poligono",
            "coords": aneis if len(aneis) > 1 else aneis[0],
        }, None
    partes = (
        so.linemerge(sg.MultiLineString([p.tolist() for p in utm]))
        if len(utm) > 1
        else sg.LineString(utm[0])
    )
    linhas = list(partes.geoms) if hasattr(partes, "geoms") else [partes]
    maior = max(linhas, key=lambda x: x.length)
    aviso = None
    if len(linhas) > 1:
        total = sum(x.length for x in linhas)
        aviso = (
            "geometria multipartes: o contrato guarda uma linha só e ficou a mais longa",
            f"{len(linhas)} linhas, {total:.1f} m no total; a mais longa tem {maior.length:.1f} m",
        )
    return {
        **base,
        "tipo": "linha",
        "coords": np.round(np.asarray(maior.coords), 3).tolist(),
    }, aviso


def _medidas(geometria: dict, utm: list[np.ndarray]) -> dict:
    """Medidas da geometria em UTM: área e perímetro (polígono, anel externo menos furos) e comprimento (linha, m)."""
    tipo = geometria["type"]
    if tipo == "Polygon":
        forma = sg.Polygon(utm[0], utm[1:])
        return {
            "area_planta_m2": round(forma.area, 6),
            "perimetro_m": round(forma.length, 6),
        }
    if tipo in ("LineString", "MultiLineString"):
        return {
            "comprimento_m": round(float(sum(sg.LineString(p).length for p in utm)), 6)
        }
    return {}


def _retangulo_pt(utm: list[np.ndarray], afim: np.ndarray) -> list[float]:
    """Caixa [x0, y0, x1, y1] (pt) dos vértices UTM pela inversa da afim pt → UTM da prancha."""
    pts = geo.aplicar(np.linalg.inv(afim), np.vstack(utm))
    x0, y0 = pts.min(axis=0)
    x1, y1 = pts.max(axis=0)
    return [round(float(v), 2) for v in (x0, y0, x1, y1)]


def _metodo(fonte: str) -> str:
    """Leitor citado na fonte do elemento (`camadas.prancha`, `camadas.escavacao`…) ou, sem ele, o construtivos."""
    achado = re.search(r"camadas\.\w+", fonte or "")
    return achado.group(0) if achado else "camadas.construtivos"


def _valor(propriedade: str, bruto, fator: float):
    """Valor na unidade da propriedade; (None, motivo) quando o tipo não confere (faixa de texto em número, por exemplo)."""
    if gavetas.REGRAS["propriedades"][propriedade]["tipo"] == "texto":
        return str(bruto), None
    if isinstance(bruto, bool):
        return None, "valor lógico em propriedade numérica"
    try:
        numero = (
            float(str(bruto).replace(",", "."))
            if isinstance(bruto, str)
            else float(bruto)
        )
    except (TypeError, ValueError):
        return None, "valor não numérico"
    return round(numero * fator, 6), None


def _prancha_por_documento(pranchas: list[dict]) -> dict[str, dict]:
    """{nome do PDF sem extensão: prancha} (a primeira de cada nome)."""
    saida: dict[str, dict] = {}
    for p in pranchas:
        if p.get("pdf"):
            saida.setdefault(_chave_documento(Path(str(p["pdf"])).name), p)
    return saida


def _evidencia(elemento: dict, localizador, documento: str) -> dict:
    return {
        "evidencia_id": f"EV-CO-{elemento['id']}",
        "classe": "projeto",
        "documento": documento,
        "localizador": localizador,
        "trecho": elemento.get("fonte"),
        "metodo": _metodo(elemento.get("fonte", "")),
        "executor": "código",
    }


def _localizar(
    elemento: dict, utm: list[np.ndarray], doc_ids: dict, pranchas: dict
) -> tuple[dict, list[tuple]]:
    """(evidência, [(motivo, detalhe)] de pendência) do elemento. Retângulo em pt só com documento registrado, prancha com afim e
    retângulo dentro da página; sem isso a evidência cai para a v1 (texto) ou para a página sem retângulo."""
    nome = _chave_documento(elemento.get("doc") or "")
    texto = f"prancha {nome or elemento.get('fonte')}; elemento {elemento.get('rotulo') or elemento['id']}"
    documento_id, prancha = doc_ids.get(nome), pranchas.get(nome)
    if not nome or documento_id is None:
        return _evidencia(elemento, texto, nome or str(elemento.get("fonte"))), [
            (
                "documento fora da gaveta documentos: evidência v1 (texto), sem página nem retângulo",
                nome,
            )
        ]
    if prancha is None:
        return _evidencia(elemento, texto, nome), [
            (
                "prancha fora das pranchas do build: página e retângulo desconhecidos, evidência v1 (texto)",
                nome,
            )
        ]
    afim = _matriz(prancha.get("M"))
    if afim is None:
        return _evidencia(elemento, {"pagina": 1}, documento_id), [
            ("prancha sem afim pt→UTM: só a página, sem retângulo", nome)
        ]
    ret = _retangulo_pt(utm, afim)
    largura, altura = prancha.get("largura"), prancha.get("altura")
    if (
        largura
        and altura
        and (ret[2] < 0 or ret[3] < 0 or ret[0] > largura or ret[1] > altura)
    ):
        return _evidencia(elemento, {"pagina": 1}, documento_id), [
            (
                "elemento fora da página da prancha: só a página, sem retângulo",
                f"{nome}; retângulo {ret}",
            )
        ]
    return _evidencia(elemento, {"pagina": 1, "retangulo_pt": ret}, documento_id), []


def _fato(
    objeto_id: str, propriedade: str, valor, natureza: str, evidencia_id: str
) -> dict:
    return {
        "fato_id": f"{objeto_id}.{propriedade}",
        "objeto_id": objeto_id,
        "propriedade": propriedade,
        "valor": valor,
        "natureza": natureza,
        "evidencia_id": evidencia_id,
    }


def _atributos_do_elemento(elemento: dict) -> list[tuple]:
    """Atributos lidos do elemento, mais etapa e origem da etapa quando o desenho não traz o rótulo "Etapa"."""
    atributos = [tuple(a) for a in elemento.get("atributos", [])]
    lidos = {r for r, _ in atributos}
    atributos += [
        (campo, elemento[campo])
        for campo in ("etapa", "origem_etapa")
        if elemento.get(campo) and "Etapa" not in lidos
    ]
    return atributos


def _incluir_atributos(atributos: list[tuple], fatos: dict, pendencias: list, incluir) -> None:
    """Passa cada atributo mapeado a fato; o que não vira propriedade, repete ou falha vira pendência."""
    for rotulo, bruto in atributos:
        if (
            rotulo in SUPERFICIES
            or rotulo in ATRIBUTOS_NA_GEOMETRIA
            or bruto in (None, "")
        ):
            continue
        if rotulo not in ROTULOS:
            pendencias.append(
                (f"atributo sem propriedade em gavetas.json: {rotulo}", None)
            )
            continue
        propriedade, fator, natureza = ROTULOS[rotulo]
        valor, falha = _valor(propriedade, bruto, fator)
        if falha:
            pendencias.append(
                (
                    f"atributo não vira a propriedade: {falha}",
                    f"{rotulo} → {propriedade}: {bruto!r}",
                )
            )
        elif propriedade in fatos:
            pendencias.append(
                (
                    "atributo repete uma propriedade já preenchida",
                    f"{rotulo} → {propriedade}",
                )
            )
        else:
            incluir(propriedade, valor, natureza)


def _pendencia_de_area(fatos: dict, area) -> list:
    """Pendência quando a área do atributo difere da geometria UTM além da tolerância."""
    pendencias = []
    area_atributo = fatos.get("area_planta_m2", {}).get("valor")
    if area_atributo is not None and area is not None:
        dif = abs(area_atributo - area)
        if dif > TOLERANCIA_AREA_M2 and dif > TOLERANCIA_AREA_REL * area:
            pendencias.append(
                (
                    "área do atributo difere da geometria UTM além da tolerância",
                    f"atributo {area_atributo:.1f} m², geometria {area:.1f} m²",
                )
            )
    return pendencias


def _fatos_do_elemento(
    elemento: dict, utm: list[np.ndarray], evidencia_id: str
) -> tuple[dict, list]:
    """({propriedade: fato}, [(motivo, detalhe)]) do elemento: rótulo, unidade, sistema, atributos mapeados e medidas."""
    objeto_id, fatos, pendencias = str(elemento["id"]), {}, []

    def incluir(propriedade, valor, natureza):
        fatos[propriedade] = _fato(
            objeto_id, propriedade, valor, natureza, evidencia_id
        )

    if elemento.get("rotulo"):
        incluir("rotulo", str(elemento["rotulo"]), "projetado")
    unidade, sistema = elemento.get("unidade"), elemento.get("sistema")
    if unidade:
        incluir("unidade", str(unidade), "inferido")
    if sistema:  # a chave de unidades_construtivas.json não leva o prefixo da unidade
        incluir("sistema", str(sistema).removeprefix(f"{unidade}-"), "inferido")
    atributos = _atributos_do_elemento(elemento)
    superficies = {
        SUPERFICIES[r]: float(v)
        for r, v in atributos
        if r in SUPERFICIES
        and isinstance(v, (int, float))
        and not isinstance(v, bool)
        and v > 0
    }
    if superficies:
        incluir("pavimentos", superficies, "inferido")
    if len(utm) > 1 and elemento["geometria"]["type"] == "MultiLineString":
        incluir("eixo_partes", [p.tolist() for p in utm], "projetado")
    _incluir_atributos(atributos, fatos, pendencias, incluir)
    medidas = _medidas(elemento["geometria"], utm)
    pendencias += _pendencia_de_area(fatos, medidas.get("area_planta_m2"))
    for propriedade, valor in medidas.items():
        # o traço desenhado não é o tubo (dois traços por tubo): vale o comprimento ou a extensão que o elemento declara
        declara_comprimento = propriedade == "comprimento_m" and (
            "extensao_m" in fatos or "comprimento_m" in fatos
        )
        if propriedade not in fatos and not declara_comprimento:
            incluir(propriedade, valor, "projetado")
    return fatos, pendencias


def de_construtivos(
    construtivos: dict, pranchas: list[dict], documentos: dict[str, str], epsg: int
) -> dict:
    """`dados["construtivos"]` → base `{gaveta: [registros]}`: um objeto por elemento, geometria UTM, fatos e evidência.

    `documentos`: {nome do PDF → documento_id}, com ou sem `.pdf` (qualquer caixa); a etapa de documentos monta com
    `gavetas.id_documento`. `pranchas`: as do build, cada uma com `pdf`, `M` (pt → UTM, 6 valores ou 3x3) e, se houver,
    `largura`/`altura` (pt). `epsg`: a zona UTM das coordenadas (as features estão em lon/lat).

    Atributos mapeados por `ROTULOS`; E e N da estaca são a própria geometria; os demais viram pendência. A área e o
    perímetro (polígono) e o comprimento (linha) da geometria entram como fatos `projetado` quando o atributo do
    elemento não traz a mesma propriedade (nunca dois fatos iguais); comprimento de linha não entra se o elemento já
    tem comprimento ou extensão. Área do atributo que difere da geometria vira pendência."""
    base = {gaveta: [] for gaveta in gavetas.GAVETAS}
    doc_ids = {_chave_documento(k): v for k, v in documentos.items()}
    por_documento = _prancha_por_documento(pranchas)
    for feature in construtivos["geojson"]["features"]:
        elemento = {**feature["properties"], "geometria": feature["geometry"]}
        objeto_id = str(elemento["id"])
        utm = _utm(_partes(feature["geometry"]), epsg)
        base["objetos"].append(
            {
                "objeto_id": objeto_id,
                "classe": elemento["classe"],
                "unidade": elemento.get("unidade"),
                "sistema": elemento.get("sistema"),
            }
        )
        registro, aviso = _registro_geometria(objeto_id, feature["geometry"], utm, epsg)
        base["geometria"].append(registro)
        evidencia, motivos = _localizar(elemento, utm, doc_ids, por_documento)
        base["evidencias"].append(evidencia)
        fatos, pendencias = _fatos_do_elemento(elemento, utm, evidencia["evidencia_id"])
        base["fatos"] += list(fatos.values())
        for motivo, detalhe in motivos + ([aviso] if aviso else []) + pendencias:
            base["pendencias"].append(
                {
                    "objeto_id": objeto_id,
                    "motivo": motivo,
                    **({"detalhe": detalhe} if detalhe else {}),
                }
            )
    return base


def resumo(base: dict) -> dict:
    """Objetos por classe, fatos por propriedade, elementos com página e retângulo, e pendências por motivo."""
    com_pagina = [
        e
        for e in base["evidencias"]
        if isinstance(e["localizador"], dict) and "pagina" in e["localizador"]
    ]
    return {
        "objetos": len(base["objetos"]),
        "objetos_por_classe": dict(
            sorted(Counter(o["classe"] for o in base["objetos"]).items())
        ),
        "fatos": len(base["fatos"]),
        "fatos_por_propriedade": dict(
            sorted(Counter(f["propriedade"] for f in base["fatos"]).items())
        ),
        "elementos_com_pagina": len(com_pagina),
        "elementos_com_pagina_e_retangulo": sum(
            "retangulo_pt" in e["localizador"] for e in com_pagina
        ),
        "pendencias": len(base["pendencias"]),
        "pendencias_por_motivo": dict(
            Counter(p["motivo"] for p in base["pendencias"]).most_common()
        ),
    }


def _raiz_de_dados(obra: dict, referencia: Path) -> Path:
    """Pasta `dados/<obra>` (as duas primeiras partes do caminho do primeiro PDF), relativa ao cwd ou à raiz do repositório."""
    partes = Path(next(p["pdf"] for p in obra["pranchas"] if p.get("pdf"))).parts[:2]
    for base in (Path.cwd(), *referencia.resolve().parents):
        if (base / Path(*partes)).is_dir():
            return base / Path(*partes)
    raise FileNotFoundError(
        f"pasta {Path(*partes)} não encontrada a partir de {Path.cwd()} nem de {referencia}"
    )


def _documentos_citados(construtivos: dict, raiz: Path) -> tuple[dict[str, str], dict]:
    """({nome do PDF: documento_id}, registros das gavetas `documentos` e `paginas`) dos PDFs citados pelos elementos,
    achados em `raiz` pelo nome; o id é o sha do conteúdo (`gavetas.id_documento`)."""
    import hashlib

    import pymupdf

    citados = {
        _chave_documento(f["properties"].get("doc") or "")
        for f in construtivos["geojson"]["features"]
    } - {""}
    achados = {
        _chave_documento(c.name): c
        for c in sorted(raiz.rglob("*"))
        if c.suffix.lower() == ".pdf"
    }
    ids, registros = {}, {"documentos": [], "paginas": []}
    for nome in sorted(citados & achados.keys()):
        caminho = achados[nome]
        documento_id = gavetas.id_documento(caminho)
        ids[nome] = documento_id
        with pymupdf.open(caminho) as pdf:
            tamanhos = [(p.rect.width, p.rect.height) for p in pdf]
        registros["documentos"].append(
            {
                "documento_id": documento_id,
                "arquivo": caminho.name,
                "extensao": ".pdf",
                "classe": "projeto",
                "sha256": hashlib.sha256(caminho.read_bytes()).hexdigest(),
                "paginas": len(tamanhos),
            }
        )
        registros["paginas"] += [
            {
                "pagina_id": gavetas.id_pagina(documento_id, i),
                "documento_id": documento_id,
                "pagina": i,
                "largura_pt": round(w, 2),
                "altura_pt": round(h, 2),
            }
            for i, (w, h) in enumerate(tamanhos, start=1)
        ]
    return ids, registros


def principal(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "dados", help="saida/<obra>/dados.json (construtivos, pranchas e crs)"
    )
    p.add_argument("obra", help="exemplos/<obra>/obra.json (caminho dos PDFs)")
    a = p.parse_args(argv)
    dados = json.loads(Path(a.dados).read_text(encoding="utf-8"))
    obra = json.loads(Path(a.obra).read_text(encoding="utf-8"))
    ids, registros = _documentos_citados(
        dados["construtivos"], _raiz_de_dados(obra, Path(a.obra))
    )
    base = de_construtivos(
        dados["construtivos"], dados["pranchas"], ids, dados["crs"]["epsg"]
    )
    base.update(registros)
    erros = gavetas.conferir_base(base)
    print(json.dumps(resumo(base), ensure_ascii=False, indent=1))
    for e in erros[:50]:
        print("ERRO", e)
    print(
        f"{len(base['documentos'])} documentos, {len(base['paginas'])} páginas, {len(erros)} erros de conferência"
    )


def metadados() -> dict:
    """Rastreabilidade do método (regra 9 do estilo)."""
    return {
        "modulo": "gavetas_construtivos",
        "descricao": "elementos construtivos (estacas, blocos, pilares, cavas, trechos, manchas) viram objetos, geometria "
        "UTM, fatos e evidência com página e retângulo em pt; o que não cabe vira pendência",
        "funcoes": ["de_construtivos", "resumo"],
        "conceitos": ["gavetas.json"],
        "rotulos": sorted(ROTULOS),
    }


if __name__ == "__main__":
    principal()
