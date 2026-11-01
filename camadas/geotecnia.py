"""Geotecnia: schema do furo de sondagem, validação e leitor de laudo (PDF) pelo texto.

O furo canônico (dict puro, nomes já em uso no projeto) está em `conceitos/geotecnia.json`:

    id, E, N (m, SIRGAS 2000/UTM), epsg, cota_boca (m), na_m (m a partir da boca; None = não atingido),
    profundidade_m, impenetravel, camadas [{de, ate, descricao, classe}] (m), nspt [[profundidade_m, golpes]], fonte

Heurística do leitor de laudo (`ler_laudo`), só pelo texto do PDF (pymupdf), sem OCR e sem inventar:

    (a) tabela de coordenadas: id de furo (`SP-?\\d+`, `SPT-?\\d+`, `F-?\\d+`) seguido de dois números, o de 6 dígitos
        inteiros (E) e o de 7 (N), e, se houver, a cota da boca; aceita ponto de milhar e vírgula decimal;
    (b) perfil por furo: o trecho começa numa linha que cita o id (com FURO/SONDAGEM/PERFIL, ou só o id) e vai até o
        próximo furo citado. Nele: NA por "N.A." / "NÍVEL D'ÁGUA" + número em m, ou "NÃO ATINGIDO"/"SECO" (= None);
        impenetrável por "IMPENETRÁVEL"; camadas por "de X a Y m descrição" ou "X,XX – Y,YY descrição"; NSPT por
        linhas "profundidade golpes".

Furo sem coordenada ou sem camadas vai para `nao_lidos` com o motivo. Todo furo lido passa por `validar_furos`.

    python -m camadas.geotecnia laudo.pdf [--saida sondagens.json]
"""

from __future__ import annotations

import argparse
import json
import math
import re
import unicodedata
from pathlib import Path

CONCEITOS = Path(__file__).resolve().parent.parent / "conceitos" / "geotecnia.json"
TOLERANCIA_PROFUNDIDADE_M = 0.01

_NUM = r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?"
_ID = r"(?:SPT|SP|F)-?\s?\d+"
_RE_ID = re.compile(rf"\b({_ID})\b", re.IGNORECASE)
_RE_NUM = re.compile(_NUM)
_RE_COORD = re.compile(
    rf"\b(?P<id>{_ID})\b(?P<resto>(?:\s+(?:{_NUM}))+)", re.IGNORECASE
)
# "N.A." com ponto, "NA" seguido de ':', '=' ou '(', ou a expressão por extenso; "NA" solto é a preposição "na" em
# maiúsculas ("ARGILA MOLE NA COTA 3,00") e não pode virar nível d'água (revisão do Fable, rodada 25)
_RE_NA = re.compile(r"\bN\.\s?A\.?|\bNA\b(?=\s*[:=(])|NIVEL\s+D['’`]?\s?AGUA|LENCOL\s+FREATICO")
_RE_SEM_NA = re.compile(r"NAO\s+ATINGID|\bSECO\b|NAO\s+ENCONTRAD|AUSENTE")
_RE_NUM_M = re.compile(rf"(?<![\d.,])({_NUM})(?:\s*m\b)?", re.IGNORECASE)
_RE_CAMADA = re.compile(
    rf"^\s*(?:de\s+)?({_NUM})\s*(?:m\s*)?(?:a|at[ée]|[–—-])\s*({_NUM})\s*m?\b\s*[:\-–—]?\s*(.*\S)\s*$",
    re.IGNORECASE,
)
_RE_NSPT = re.compile(
    rf"^\s*({_NUM})\s*(?:m\s+)?(\d{{1,3}})\s*(?:golpes)?\s*$", re.IGNORECASE
)
_RE_PROF = re.compile(
    rf"PROFUNDIDADE\s+(?:FINAL|TOTAL|ATINGIDA)[^\d\n]{{0,20}}({_NUM})"
)
_RE_COTA = re.compile(
    rf"COTA(?:\s+DA\s+BOCA|\s+DO\s+TERRENO|\s+DE\s+BOCA)?[^\d\n]{{0,20}}({_NUM})"
)


def metadados() -> dict:
    """Rastreabilidade (regra 9 do estilo)."""
    premissas = json.loads(CONCEITOS.read_text(encoding="utf-8"))["premissas"]
    return {
        "modulo": "geotecnia",
        "descricao": "schema do furo de sondagem, validação e leitor de laudo em PDF pelo texto",
        "funcoes": ["validar_furos", "ler_laudo", "metadados", "main"],
        "bibliografia": [],
        "premissas": [
            {
                "aplicacao": {nome: [str(p.get("valor", p))]},
                "estado": p["estado"],
                "fonte": p["fonte"],
            }
            for nome, p in premissas.items()
        ],
    }


# --------------------------------------------------------------------------------------------------------------------
# Validação
# --------------------------------------------------------------------------------------------------------------------


def _numero(valor) -> bool:
    """Verdadeiro para número real finito (bool não conta)."""
    return (
        isinstance(valor, (int, float))
        and not isinstance(valor, bool)
        and math.isfinite(valor)
    )


def _motivos_camadas(furo: dict) -> list[str]:
    """Motivos de erro nas camadas: ordem e limites. Camada sem `de`/`ate` (None) é não confirmada e fica fora."""
    motivos, anterior_ate = [], None
    for i, c in enumerate(furo.get("camadas") or []):
        de, ate = c.get("de"), c.get("ate")
        if de is None or ate is None:
            continue
        if not (_numero(de) and _numero(ate)):
            motivos.append(f"camada {i + 1} com limite não numérico")
        elif ate <= de:
            motivos.append(f"camada {i + 1} com ate <= de ({de} a {ate})")
        elif anterior_ate is not None and de < anterior_ate - TOLERANCIA_PROFUNDIDADE_M:
            motivos.append(
                f"camada {i + 1} fora de ordem (de {de} antes do fim da anterior, {anterior_ate})"
            )
        if _numero(de) and _numero(ate) and ate > de:
            anterior_ate = ate
    return motivos


def _motivos_furo(furo) -> list[str]:
    """Todos os motivos pelos quais o furo não é válido (lista vazia = válido)."""
    if not isinstance(furo, dict):
        return ["furo não é um objeto"]
    motivos = []
    if not str(furo.get("id") or "").strip():
        motivos.append("sem id")
    for eixo in ("E", "N"):
        if not _numero(furo.get(eixo)):
            motivos.append(f"{eixo} ausente ou não numérico")
    na = furo.get("na_m")
    if na is not None and (not _numero(na) or na < 0):
        motivos.append(f"na_m inválido ({na})")
    motivos += _motivos_camadas(furo)
    ates = [c["ate"] for c in (furo.get("camadas") or []) if _numero(c.get("ate"))]
    prof = furo.get("profundidade_m")
    if ates and _numero(prof) and prof < max(ates) - TOLERANCIA_PROFUNDIDADE_M:
        motivos.append(
            f"profundidade_m ({prof}) menor que a última camada ({max(ates)})"
        )
    return motivos


def validar_furos(furos) -> tuple[list, list]:
    """Separa os furos válidos dos inválidos, sem alterar nomes nem valores.

    Aceita a lista de furos ou `{"meta": ..., "furos": [...]}`. Devolve (válidos, erros), com
    erros = [{"id", "motivo"}], um por motivo. Profundidade com tolerância absoluta de 0,01 m.
    """
    if isinstance(furos, dict):
        furos = furos.get("furos", [])
    validos, erros = [], []
    for furo in furos or []:
        motivos = _motivos_furo(furo)
        if not motivos:
            validos.append(furo)
            continue
        fid = furo.get("id") if isinstance(furo, dict) else None
        erros += [{"id": fid, "motivo": m} for m in motivos]
    return validos, erros


# --------------------------------------------------------------------------------------------------------------------
# Leitor de laudo
# --------------------------------------------------------------------------------------------------------------------


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )


def _para_float(token: str) -> float:
    """'654.321,50' -> 654321.5; '12,30' -> 12.3; '654321.50' -> 654321.5."""
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", token):
        token = token.replace(".", "")
    return float(token.replace(",", "."))


def _chave(identificador: str) -> str:
    """Chave comparável do id: 'SP-01', 'SP01' e 'SPT-1' são o mesmo furo."""
    t = re.sub(r"[^A-Z0-9]", "", identificador.upper()).replace("SPT", "SP")
    return re.sub(r"(?<=[A-Z])0+(?=\d)", "", t)


def _id_limpo(identificador: str) -> str:
    return re.sub(r"\s+", "", identificador.upper())


def _coordenadas(texto: str) -> dict[str, dict]:
    """Tabela de coordenadas: {chave: {id, E, N, cota_boca?}}; vale a primeira ocorrência de cada furo."""
    achados = {}
    plano = re.sub(r"\s+", " ", texto)
    for m in _RE_COORD.finditer(plano):
        valores = [_para_float(t) for t in _RE_NUM.findall(m.group("resto"))]
        este = next((i for i, v in enumerate(valores) if 1e5 <= v < 1e6), None)
        if (
            este is None
            or este + 1 >= len(valores)
            or not 1e6 <= valores[este + 1] < 1e7
        ):
            continue
        item = {
            "id": _id_limpo(m.group("id")),
            "E": valores[este],
            "N": valores[este + 1],
        }
        if este + 2 < len(valores) and 0 <= valores[este + 2] < 1e4:
            item["cota_boca"] = valores[este + 2]
        achados.setdefault(_chave(m.group("id")), item)
    return achados


def _trechos_por_furo(texto: str) -> dict[str, dict]:
    """Divide o texto em trechos por furo citado: {chave: {id, linhas}}. Cada trecho vai até o próximo furo."""
    trechos, atual = {}, None
    for linha in texto.splitlines():
        m = _RE_ID.search(linha)
        cabecalho = (
            m
            and not re.search(r"\d{6,}", linha.replace(".", "").replace(",", ""))
            and (
                re.search(r"FURO|SONDAGEM|PERFIL", _sem_acento(linha).upper())
                or linha.strip() == m.group(1)
            )
        )
        if cabecalho:
            atual = trechos.setdefault(
                _chave(m.group(1)), {"id": _id_limpo(m.group(1)), "linhas": []}
            )
        elif atual is not None:
            atual["linhas"].append(linha)
    return trechos


def _nivel_dagua(linhas: list[str]):
    """(achou, na_m): NA em m, ou None se 'não atingido'/'seco'. achou=False se o laudo não cita o NA."""
    for i, linha in enumerate(linhas):
        norm = _sem_acento(linha).upper()
        m = _RE_NA.search(norm)
        if not m:
            continue
        resto = norm[m.end() :] or (
            _sem_acento(linhas[i + 1]).upper() if i + 1 < len(linhas) else ""
        )
        sem, num = _RE_SEM_NA.search(resto), _RE_NUM_M.search(resto)
        if num and (not sem or num.start() < sem.start()):
            return True, _para_float(num.group(1))
        if sem:
            return True, None
    return False, None


def _perfil(linhas: list[str]) -> dict:
    """Camadas, NSPT, profundidade e cota do trecho de um furo."""
    camadas, nspt = [], []
    for linha in linhas:
        c, n = _RE_CAMADA.match(linha), _RE_NSPT.match(linha)
        if c:
            camadas.append(
                {
                    "de": _para_float(c.group(1)),
                    "ate": _para_float(c.group(2)),
                    "descricao": c.group(3).strip(),
                }
            )
        elif n and _para_float(n.group(1)) <= 60:
            nspt.append([_para_float(n.group(1)), int(n.group(2))])
    texto = _sem_acento("\n".join(linhas)).upper()
    prof, cota = _RE_PROF.search(texto), _RE_COTA.search(texto)
    return {
        "camadas": camadas,
        "nspt": nspt,
        "impenetravel": "IMPENETRAVEL" in texto,
        "profundidade_m": _para_float(prof.group(1))
        if prof
        else (camadas[-1]["ate"] if camadas else None),
        "cota_boca": _para_float(cota.group(1)) if cota else None,
    }


def _montar_furo(coord: dict | None, trecho: dict | None, fonte: str) -> dict:
    perfil = _perfil(trecho["linhas"]) if trecho else {"camadas": [], "nspt": []}
    achou_na, na = _nivel_dagua(trecho["linhas"]) if trecho else (False, None)
    furo = {"id": (coord or trecho)["id"], "E": coord["E"], "N": coord["N"]}
    cota = coord.get("cota_boca", perfil.get("cota_boca"))
    if cota is not None:
        furo["cota_boca"] = cota
    furo["na_m"] = na if achou_na else None
    for campo in ("profundidade_m", "impenetravel", "camadas", "nspt"):
        if perfil.get(campo) not in (None, []):
            furo[campo] = perfil[campo]
    furo["fonte"] = fonte
    return furo


def ler_laudo(caminho_pdf) -> dict:
    """Lê um laudo de sondagem em PDF pelo texto.

    Devolve {"furos": [...], "nao_lidos": [{"id", "motivo"}], "paginas_lidas": n}. Nada é inventado: furo sem
    coordenada, sem camadas ou reprovado em `validar_furos` vai para `nao_lidos` com o motivo.
    """
    import pymupdf

    caminho = Path(caminho_pdf)
    with pymupdf.open(caminho) as doc:
        texto = "\n".join(pagina.get_text() for pagina in doc)
        paginas = len(doc)
    coordenadas, trechos = _coordenadas(texto), _trechos_por_furo(texto)
    candidatos, nao_lidos = [], []
    for chave in sorted(set(coordenadas) | set(trechos)):
        coord, trecho = coordenadas.get(chave), trechos.get(chave)
        rotulo = (coord or trecho)["id"]
        if coord is None:
            nao_lidos.append(
                {
                    "id": rotulo,
                    "motivo": "sem coordenada (E/N) na tabela de coordenadas",
                }
            )
        elif not trecho or not _perfil(trecho["linhas"])["camadas"]:
            nao_lidos.append({"id": rotulo, "motivo": "sem camadas no perfil"})
        else:
            candidatos.append(_montar_furo(coord, trecho, caminho.name))
    furos, erros = validar_furos(candidatos)
    nao_lidos += [
        {"id": e["id"], "motivo": f"reprovado na validação: {e['motivo']}"}
        for e in erros
    ]
    return {"furos": furos, "nao_lidos": nao_lidos, "paginas_lidas": paginas}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Lê um laudo de sondagem (PDF) e devolve os furos no schema canônico"
    )
    ap.add_argument("laudo")
    ap.add_argument(
        "--saida", help="grava {meta, furos} neste JSON (formato de sondagens.json)"
    )
    a = ap.parse_args(argv)
    r = ler_laudo(a.laudo)
    print(
        f"{len(r['furos'])} furos lidos, {len(r['nao_lidos'])} não lidos, {r['paginas_lidas']} páginas"
    )
    for f in r["furos"]:
        na = (
            "NA não atingido"
            if f["na_m"] is None
            else f"NA {f['na_m']:.2f} m".replace(".", ",")
        )
        print(
            f"  {f['id']}: E={f['E']:.2f} N={f['N']:.2f}, {len(f.get('camadas', []))} camadas, {na}"
        )
    for n in r["nao_lidos"]:
        print(f"  NÃO LIDO {n['id']}: {n['motivo']}")
    if a.saida:
        meta = {
            "fonte": Path(a.laudo).name,
            "nao_lidos": r["nao_lidos"],
            "paginas_lidas": r["paginas_lidas"],
        }
        Path(a.saida).write_text(
            json.dumps(
                {"meta": meta, "furos": r["furos"]}, ensure_ascii=False, indent=1
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
