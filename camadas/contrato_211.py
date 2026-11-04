"""Linhas de serviço da aba CUSTO CIVIL da planilha do contrato Sanepar 211/2026, ligadas à EAP (sem preço).

    ler_custo_civil  = uma linha de serviço por dict, com a hierarquia unidade › UC › trecho › grupo e o projeto
    classificar      = acrescenta folha da EAP, regra, material, DN e estado (de-para `composicoes_sanepar.json`)
    resumo           = totais: linhas, declaradas, vazias e contagem por regra
    contexto_do_build, quantificar = a quantidade calculada de cada linha, com evidência e situação (E2)
    resumo_quantidades, para_html  = totais por situação e a lista enxuta para o HTML

**Sem preço.** A leitura toca só as colunas A a E (item, composição, descrição, unidade, quantidade) e I (projeto).
As colunas F e G (valor unitário e total), as abas de insumos e de composições nunca são abertas.

O de-para vive em `conceitos/composicoes_sanepar.json`, com o estado de cada regra (confirmado, premissa, calibrar).
Linha sem de-para recebe `regra="sem_regra"` e o `motivo`: nada é inventado.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from functools import cache
from pathlib import Path

import numpy as np
import openpyxl

from . import geotecnia as geo
from . import lineares

DE_PARA = json.loads(
    (
        Path(__file__).resolve().parent.parent
        / "conceitos"
        / "composicoes_sanepar.json"
    ).read_text(encoding="utf-8")
)

# serviços que a planilha escreve como título (sem unidade e sem composição), mas que se quantificam
_TITULO_SERVICO = re.compile(
    r"^(RECOMPOSICAO DE PAVIMENTO|BLOCOS? DE (APOIO|ANCORAGEM)|MEDIDORES? DE VAZ)"
)
_COLUNA_PROJETO = 9  # coluna I
_ULTIMA_COLUNA_DADOS = 5  # coluna E: F e G (valores) ficam de fora


def _sem_acento(texto: str) -> str:
    """Maiúsculas e sem acento, para comparar descrições."""
    base = unicodedata.normalize("NFD", texto.upper())
    return "".join(c for c in base if unicodedata.category(c) != "Mn")


def _texto(valor) -> str:
    """Texto aparado de uma célula; inteiro vindo como float não ganha '.0'."""
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return str(valor).strip()


def _numero(valor) -> float | None:
    """Quantidade numérica da célula, ou None se vazia ou não numérica."""
    if isinstance(valor, bool) or valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    try:
        return float(str(valor).strip().replace(",", "."))
    except ValueError:
        return None


def _linhas_de_dados(xlsx, aba: str) -> list[tuple]:
    """(linha, A, B, C, D, E, I) de cada linha da aba, lendo só as colunas A–E e, à parte, a I."""
    livro = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    try:
        if aba not in livro.sheetnames:
            raise ValueError(f"aba {aba!r} não existe na planilha")
        ws = livro[aba]
        dados = ws.iter_rows(
            min_row=1, min_col=1, max_col=_ULTIMA_COLUNA_DADOS, values_only=True
        )
        projetos = ws.iter_rows(
            min_row=1,
            min_col=_COLUNA_PROJETO,
            max_col=_COLUNA_PROJETO,
            values_only=True,
        )
        saida = []
        for numero, (linha, projeto) in enumerate(
            zip(dados, projetos, strict=False), start=1
        ):
            a, b, c, d, e = (list(linha) + [None] * 5)[:5]
            saida.append((numero, a, b, c, d, e, projeto[0] if projeto else None))
        return saida
    finally:
        livro.close()


def _linha_do_cabecalho(linhas: list) -> int:
    """Número da linha do cabeçalho 'ITEM' (nas 15 primeiras); ValueError se não houver."""
    inicio = next(
        (n for n, a, *_ in linhas[:15] if _texto(a).upper() == "ITEM"),
        None,
    )
    if inicio is None:
        raise ValueError(
            "cabeçalho 'ITEM' não encontrado nas 15 primeiras linhas da aba"
        )
    return inicio


def _registro_de_servico(aba, numero, hierarquia, linha, marcas) -> dict:
    """O dict de uma linha de serviço, com a hierarquia (unidade_obra, uc, trecho, trecho_linha, grupo)."""
    unidade_obra, uc, trecho, trecho_linha, grupo = hierarquia
    composicao, descricao, unidade, quantidade = linha
    projeto, titulo_servico, eh_trecho = marcas
    return {
        "aba": aba,
        "linha": numero,
        "unidade_obra": unidade_obra,
        "uc": uc,
        "trecho": trecho,
        "trecho_linha": trecho_linha,
        "grupo": grupo,
        "composicao": composicao or None,
        "descricao": descricao,
        "unidade": unidade or None,
        "quantidade_declarada": _numero(quantidade),
        "projeto": projeto,
        "titulo_servico": titulo_servico,
        "eh_trecho": eh_trecho,
    }


def ler_custo_civil(xlsx, aba: str = "CUSTO CIVIL") -> list[dict]:
    """Linhas de serviço da aba, cada uma com a sua hierarquia.

    Serviço é a linha com unidade em D (menos "SUBTOTAL:"), a linha de trecho (título em "M", sem composição) e os
    títulos que também se quantificam (recomposição de pavimento, blocos, medidores), com `titulo_servico=True`.
    Hierarquia: `unidade_obra` (A começa com UNIDADE), `uc` (A numérico e C texto), `trecho` (título em "M" sem
    composição), `grupo` (título sem composição e sem unidade; um trecho novo o zera). O `projeto` é o da própria
    linha ou o herdado do trecho ou do grupo, até o próximo trecho, grupo ou UC.
    """
    linhas = _linhas_de_dados(xlsx, aba)
    inicio = _linha_do_cabecalho(linhas)

    unidade_obra = uc = grupo = trecho = None
    trecho_linha = None
    projeto_contexto = None
    servicos = []
    for numero, a, b, c, d, e, i in linhas:
        if numero <= inicio:
            continue
        item, composicao, descricao, unidade = (
            _texto(a),
            _texto(b),
            _texto(c),
            _texto(d),
        )
        projeto_proprio = _texto(i) or None
        if item.upper().startswith("UNIDADE"):
            unidade_obra, uc, grupo, trecho, trecho_linha = item, None, None, None, None
            projeto_contexto = None
            continue
        if re.fullmatch(r"\d+", item) and descricao:
            uc = f"UC {item} - {descricao}"
            grupo = trecho = trecho_linha = projeto_contexto = None
            continue
        if unidade.upper() == "SUBTOTAL:" or not (composicao or descricao or unidade):
            continue
        eh_trecho = not composicao and unidade.upper() == "M"
        titulo_servico = (
            not composicao
            and not unidade
            and bool(_TITULO_SERVICO.match(_sem_acento(descricao)))
        )
        eh_servico = bool(unidade) or bool(composicao) or titulo_servico
        if eh_trecho:
            trecho, trecho_linha, projeto_contexto = descricao, numero, projeto_proprio
            grupo = None  # o trecho abre uma seção nova: o grupo anterior não vale mais
        elif not eh_servico:  # título de grupo
            grupo, trecho, trecho_linha = descricao, None, None
            projeto_contexto = projeto_proprio
            continue
        servicos.append(
            _registro_de_servico(
                aba,
                numero,
                (unidade_obra, uc, trecho, trecho_linha, grupo),
                (composicao, descricao, unidade, e),
                (projeto_proprio or projeto_contexto, titulo_servico, eh_trecho),
            )
        )
    return servicos


def _entrada_para_linha(linha: dict, de_para: dict) -> tuple[dict | None, dict]:
    """(entrada do de-para, campos extras: material e dn_mm) da linha, ou (None, {}) se não casar."""
    composicao = linha.get("composicao")
    if linha.get("eh_trecho"):
        return de_para["por_estrutura"]["titulo_de_trecho"], {}
    if composicao:
        if composicao in de_para["composicoes"]:
            return de_para["composicoes"][composicao], {}
        for padrao in de_para.get("padroes", []):
            achou = re.fullmatch(padrao["padrao"], composicao)
            if achou:
                return padrao, {
                    "material": padrao["materiais"][achou.group(1)],
                    "dn_mm": int(achou.group(2)),
                }
        return None, {}
    descricao = _sem_acento(linha.get("descricao") or "")
    for chave, entrada in de_para.get("por_descricao", {}).items():
        if descricao.startswith(chave):
            return entrada, {}
    return None, {}


def classificar(linhas: list[dict], de_para: dict | None = None) -> list[dict]:
    """Cópia das linhas com `folha_eap`, `regra`, `material`, `dn_mm`, `estado` (e `grandeza`, `motivo`).

    Linha sem de-para recebe `regra="sem_regra"` e o `motivo`; linha de `sem_regra` do próprio de-para leva o motivo
    escrito lá. `material` e `dn_mm` só existem nas composições por expressão (CVCA)."""
    de_para = DE_PARA if de_para is None else de_para
    saida = []
    for linha in linhas:
        entrada, extras = _entrada_para_linha(linha, de_para)
        nova = {**linha, "material": None, "dn_mm": None, **extras}
        if entrada is None:
            rotulo = linha.get("composicao") or linha.get("descricao")
            nova.update(
                folha_eap=None,
                regra="sem_regra",
                grandeza=None,
                estado=None,
                motivo=f"sem de-para para {rotulo!r} em composicoes_sanepar.json",
            )
        else:
            nova.update(
                folha_eap=entrada.get("folha_eap"),
                regra=entrada["regra"],
                grandeza=entrada.get("grandeza"),
                estado=entrada.get("estado"),
            )
            if entrada["regra"] == "sem_regra":
                nova["motivo"] = entrada.get("motivo", "regra não definida no de-para")
        saida.append(nova)
    return saida


def resumo(linhas: list[dict]) -> dict:
    """Totais: linhas, declaradas (com quantidade), vazias, títulos-serviço, por regra e linhas sem de-para."""
    por_regra: dict[str, int] = {}
    for linha in linhas:
        regra = linha.get("regra", "nao_classificada")
        por_regra[regra] = por_regra.get(regra, 0) + 1
    declaradas = sum(1 for linha in linhas if linha["quantidade_declarada"] is not None)
    return {
        "linhas": len(linhas),
        "declaradas": declaradas,
        "vazias": len(linhas) - declaradas,
        "com_unidade": sum(1 for linha in linhas if linha["unidade"]),
        "titulos_servico": sum(1 for linha in linhas if linha.get("titulo_servico")),
        "por_regra": dict(sorted(por_regra.items())),
        "sem_de_para": [
            {
                "linha": ln["linha"],
                "composicao": ln["composicao"],
                "descricao": ln["descricao"],
            }
            for ln in linhas
            if ln.get("regra") == "sem_regra"
            and ln.get("motivo", "").startswith("sem de-para")
        ],
    }


# ----------------------------------------------------------------------------------------------------------------
# E2: quantidades calculadas a partir das redes de vala, das sondagens e da urbanização do build
# ----------------------------------------------------------------------------------------------------------------

SITUACOES = (
    "calculada",
    "parcial",
    "declarada · confere",
    "declarada · diverge",
    "declarada",
    "verba",
    "a preencher",
)
_GRANDEZAS_COM_TOLERANCIA = ("comprimento", "area", "volume")
_CASAS_DECIMAIS = 3


def _furo_valido(furo: dict) -> bool:
    """Furo com E, N e cota da boca conhecidos (coordenada `null` fica fora, como em `escavacao._furos_da_obra`)."""
    return all(furo.get(chave) is not None for chave in ("E", "N", "cota_boca"))


def contexto_do_build(
    redes_vala: list[dict],
    furos: list[dict],
    supressao_por_uc: dict | None = None,
    urbanizacao: dict | None = None,
) -> dict:
    """Contexto de `quantificar`: o que o build já calculou, sem nenhum preço.

    `redes_vala` = redes de `valas.rede` (com `trecho_contrato`); `furos` = sondagens (id, E, N, cota_boca, na_m),
    sem os de coordenada `null`; `supressao_por_uc` = {uc: {arvores_m2, rasteira_m2}} (ver `supressao_por_uc`);
    `urbanizacao` = {nome: área em m²} (`valas.para_html` → `urbanizacao_m2`) ou {nome: geometria shapely}.
    Cada parte ausente deixa as regras que dependem dela "a preencher", com o motivo."""
    return {
        "redes_vala": list(redes_vala or []),
        "furos": [f for f in (furos or []) if _furo_valido(f)],
        "furos_sem_coordenada": [
            f.get("id") for f in (furos or []) if not _furo_valido(f)
        ],
        "supressao_por_uc": supressao_por_uc,
        "urbanizacao": urbanizacao,
    }


def _trechos_por_uc(linhas: list[dict]) -> dict[tuple, list[str]]:
    """{(unidade_obra, uc): trechos distintos, na ordem da planilha}."""
    saida: dict[tuple, list[str]] = {}
    for linha in linhas:
        if linha.get("uc") and linha.get("trecho"):
            lista = saida.setdefault((linha.get("unidade_obra"), linha["uc"]), [])
            if linha["trecho"] not in lista:
                lista.append(linha["trecho"])
    return saida


def supressao_por_uc(
    redes_vala: list[dict],
    ortofoto,
    mds_png,
    faixa_m: float,
    folga_m: float,
    linhas: list[dict],
) -> dict:
    """{uc: {arvores_m2, rasteira_m2, faixa_m, folga_m}} por `supressao.estimar`, uma "etapa" por UC.

    A faixa de cada UC é a das amostras (`pts`, a cada 1 m) das redes cujo `trecho_contrato` é um trecho da UC nas
    `linhas` classificadas; UC sem rede medida fica de fora (a regra devolve "a preencher"). Onde as faixas de duas
    UCs se sobrepõem, `estimar` dá a área à primeira UC listada (ordem das linhas)."""
    import shapely

    from . import supressao

    geoms_por_uc: dict[str, list] = {}
    for (_, uc), trechos in _trechos_por_uc(linhas).items():
        # faixa do trecho = buffer redondo das amostras (a cada 1 m); o buffer plano de `faixa_de_obra` em ponto é
        # vazio (área 0), por isso a faixa já vai pronta, como polígono, e sem folga
        geoms = [
            shapely.MultiPoint(np.asarray(rede["pts"], dtype=np.float64)).buffer(
                faixa_m / 2
            )
            for rede in redes_vala
            if rede.get("trecho_contrato") in trechos and len(rede.get("pts", ())) > 0
        ]
        if geoms:
            geoms_por_uc.setdefault(uc, []).extend(geoms)
    if not geoms_por_uc:
        return {}
    resumo_ = supressao.estimar(
        ortofoto,
        mds_png,
        geoms_por_uc,
        faixa_m=faixa_m,
        folga_unidades_m=0.0,
    )["resumo"]
    return {
        uc: {
            "arvores_m2": float(resumo_.get(uc, {}).get("supressao_m2", 0.0)),
            "rasteira_m2": float(resumo_.get(uc, {}).get("limpeza_m2", 0.0)),
            "faixa_m": faixa_m,
            "folga_m": folga_m,
        }
        for uc in geoms_por_uc
    }


@cache
def _vala_por_metro(
    classe: str, de_mm: float, material: str, dn_mm: float, profundidade_m: float
) -> tuple[float, float, float]:
    """(escavação, reaterro, bota-fora) em m³ por metro de vala, pelo dimensionador único (`lineares`)."""
    vala = lineares.dimensionar_vala(
        {
            "local": classe,
            "dn_mm": dn_mm,
            "de_mm": de_mm,
            "material": material,
            "prof_m": profundidade_m,
            "comp_m": 1.0,
            "metodo": "VCA",
        }
    )
    return vala["escavacao_m3"], vala["reaterro_m3"], vala["bota_fora_m3"]


def _evidencia_rede(rede: dict, valor: float, unidade: str, tipo: str) -> dict:
    return {
        "tipo": tipo,
        "id": rede.get("id"),
        "prancha": ", ".join(rede.get("pranchas") or []),
        "layer": ", ".join(rede.get("layers") or []),
        "valor": round(float(valor), _CASAS_DECIMAIS),
        "unidade": unidade,
    }


def _agregado_das_redes(redes: list[dict]) -> dict:
    """Grandezas da vala somadas sobre as classes do quadro das redes; um vetor NumPy por grandeza."""
    pares = [(rede, q) for rede in redes for q in rede.get("quadro", [])]
    extensao_m = np.array([q["extensao_m"] for _, q in pares], dtype=np.float64)
    largura_m = np.array([q["largura_m"] for _, q in pares], dtype=np.float64)
    profundidade_m = np.array([q["profundidade_m"] for _, q in pares], dtype=np.float64)
    escorado = np.array([bool(q["escorado"]) for _, q in pares], dtype=bool)
    recomposicao_m2 = np.array(
        [q.get("recomposicao_m2", 0.0) for _, q in pares], dtype=np.float64
    )
    por_metro = np.array(
        [
            _vala_por_metro(
                q["classe"],
                float(rede["de_mm"]),
                q.get("material") or rede.get("material"),
                float(q.get("dn_mm") or rede.get("dn_mm") or rede["de_mm"]),
                float(q["profundidade_m"]),
            )
            for rede, q in pares
        ],
        dtype=np.float64,
    ).reshape(-1, 3)
    return {
        "extensao_m": extensao_m,
        "largura_m": largura_m,
        "escavacao_m3": float(np.sum(extensao_m * por_metro[:, 0])),
        "reaterro_m3": float(np.sum(extensao_m * por_metro[:, 1])),
        "bota_fora_m3": float(np.sum(extensao_m * por_metro[:, 2])),
        "escorada_m": float(np.sum(extensao_m[escorado])),
        "profundidade_max_m": float(profundidade_m.max()) if len(pares) else 0.0,
        "recomposicao_m2": float(np.sum(recomposicao_m2)),
    }


class _Ambiente:
    """Tudo que as regras consultam: contexto, conceito e cache por trecho (uma instância por `quantificar`)."""

    def __init__(self, linhas: list[dict], contexto: dict, conceito: dict):
        self.contexto = contexto
        self.conceito = conceito
        self.trechos_da_uc = _trechos_por_uc(linhas)
        self._agregados: dict[str, dict | None] = {}

    def redes(self, trecho: str | None, dn_mm: int | None = None) -> list[dict]:
        if trecho is None:
            return []
        return [
            r
            for r in self.contexto.get("redes_vala", [])
            if r.get("trecho_contrato") == trecho
            and (dn_mm is None or r.get("dn_mm") == dn_mm)
        ]

    def agregado(self, trecho: str) -> dict | None:
        """Agregado de todas as redes do trecho (sem filtro de DN), ou None se não há rede."""
        if trecho not in self._agregados:
            redes = self.redes(trecho)
            self._agregados[trecho] = (
                {"redes": redes, **_agregado_das_redes(redes)} if redes else None
            )
        return self._agregados[trecho]

    def premissa(self, nome: str) -> dict:
        p = self.conceito["premissas"][nome]
        return {
            "nome": nome,
            "valor": p["valor"],
            "unidade": p["unidade"],
            "estado": p["estado"],
        }

    def valor(self, nome: str) -> float:
        return float(self.conceito["premissas"][nome]["valor"])


def _calculo(
    quantidade=None, motivo=None, parcial=False, evidencias=(), premissas=()
) -> dict:
    if quantidade is not None:
        quantidade = round(float(quantidade), _CASAS_DECIMAIS)
    return {
        "quantidade": quantidade,
        "motivo": motivo,
        "parcial": parcial,
        "evidencias": list(evidencias),
        "premissas": list(premissas),
    }


def _sem_rede(linha: dict, dn_mm=None) -> dict:
    extra = f" (DN {dn_mm})" if dn_mm else ""
    return _calculo(
        motivo=f"trecho sem rede medida na prancha{extra}: {linha['trecho']!r}"
    )


def _regra_comprimento_trecho(linha: dict, amb: _Ambiente) -> dict:
    if not linha.get("trecho"):
        return _calculo(motivo="linha fora de um trecho do contrato")
    redes = amb.redes(linha["trecho"], linha.get("dn_mm"))
    if not redes:
        return _sem_rede(linha, linha.get("dn_mm"))
    total = float(np.sum([r["extensao_m"] for r in redes], dtype=np.float64))
    return _calculo(
        total,
        evidencias=[
            _evidencia_rede(r, r["extensao_m"], "m", "rede_vala") for r in redes
        ],
    )


def _por_rede(linha: dict, amb: _Ambiente, chave: str, unidade: str, tipo: str):
    """(agregado do trecho, evidências por rede) para a grandeza `chave`; (None, cálculo vazio) se faltar o trecho."""
    if not linha.get("trecho"):
        return None, _calculo(motivo="linha fora de um trecho do contrato")
    agregado = amb.agregado(linha["trecho"])
    if agregado is None:
        return None, _sem_rede(linha)
    evidencias = [
        _evidencia_rede(r, _agregado_das_redes([r])[chave], unidade, tipo)
        for r in agregado["redes"]
    ]
    return agregado, evidencias


def _regra_volume(chave: str, tipo: str):
    def regra(linha: dict, amb: _Ambiente) -> dict:
        agregado, evidencias = _por_rede(linha, amb, chave, "m3", tipo)
        if agregado is None:
            return evidencias
        return _calculo(agregado[chave], evidencias=evidencias)

    return regra


def _regra_transporte(linha: dict, amb: _Ambiente) -> dict:
    agregado, evidencias = _por_rede(linha, amb, "bota_fora_m3", "m3", "bota_fora")
    if agregado is None:
        return evidencias
    return _calculo(
        agregado["bota_fora_m3"] * amb.valor("dmt_bota_fora_km"),
        evidencias=evidencias,
        premissas=[amb.premissa("dmt_bota_fora_km")],
    )


def _regra_recomposicao(linha: dict, amb: _Ambiente) -> dict:
    agregado, evidencias = _por_rede(
        linha, amb, "recomposicao_m2", "m2", "recomposicao"
    )
    if agregado is None:
        return evidencias
    return _calculo(agregado["recomposicao_m2"], evidencias=evidencias)


def _evidencia_furo(tipo: str, furo: dict, valor: float) -> dict:
    return {
        "tipo": tipo,
        "id": furo.get("id"),
        "furo": furo.get("id"),
        "valor": round(float(valor), _CASAS_DECIMAIS),
        "unidade": "m",
    }


def _regra_rebaixamento(linha: dict, amb: _Ambiente) -> dict:
    """1 se o NA do furo mais próximo do trecho fica acima do fundo da vala mais funda do trecho; 0 se não.

    Furo mais próximo = o de menor distância a qualquer amostra (`pts`) das redes do trecho. NA = `geotecnia.na_m`
    (profundidade a partir da boca, com a margem da premissa); fundo = cota da boca − maior profundidade do quadro.
    NA igual ao fundo não rebaixa. Furo sem NA registrado: "a preencher" (não se supõe seco nem molhado)."""
    agregado, falha = _por_rede(linha, amb, "escorada_m", "m", "")
    if agregado is None:
        return falha
    furos = amb.contexto.get("furos", [])
    if not furos:
        return _calculo(motivo="sem sondagem com coordenada e cota da boca no contexto")
    amostras = [
        np.asarray(r["pts"], dtype=np.float64).reshape(-1, 2)
        for r in agregado["redes"]
        if len(r.get("pts", ())) > 0
    ]
    if not amostras:
        return _calculo(
            motivo="redes do trecho sem amostras (pts) para medir a distância ao furo"
        )
    pontos = np.vstack(amostras)
    coordenadas = np.array([[f["E"], f["N"]] for f in furos], dtype=np.float64)
    distancia_por_furo_m = np.linalg.norm(
        pontos[:, None, :] - coordenadas[None, :, :], axis=2
    ).min(axis=0)
    furo = furos[int(np.argmin(distancia_por_furo_m))]
    distancia_m = float(distancia_por_furo_m.min())
    premissas = [
        {
            "nome": "margem_na_m",
            "valor": geo.MARGEM_NA_M,
            "unidade": "m",
            "estado": geo.PREMISSAS["margem_na_m"]["estado"],
        }
    ]
    evidencias = [_evidencia_furo("furo_mais_proximo", furo, distancia_m)]
    profundidade_na_m = geo.na_m(furo)
    if profundidade_na_m is None:
        return _calculo(
            motivo=f"furo {furo.get('id')} (o mais próximo, a {distancia_m:.0f} m) sem nível d'água registrado",
            evidencias=evidencias,
            premissas=premissas,
        )
    cota_na_m = float(furo["cota_boca"]) - profundidade_na_m
    cota_fundo_m = float(furo["cota_boca"]) - agregado["profundidade_max_m"]
    evidencias += [
        _evidencia_furo("cota_na", furo, cota_na_m),
        _evidencia_furo("cota_fundo_vala", furo, cota_fundo_m),
    ]
    return _calculo(
        1.0 if cota_na_m > cota_fundo_m else 0.0,
        evidencias=evidencias,
        premissas=premissas,
    )


def _resultado_da_uc(
    linha: dict, amb: _Ambiente, valor_das_redes, unidade, premissas=()
):
    """Soma `valor_das_redes(redes)` dos trechos da UC; parcial se faltar trecho, "a preencher" se faltarem todos."""
    trechos = amb.trechos_da_uc.get((linha.get("unidade_obra"), linha.get("uc")))
    if not linha.get("uc") or not trechos:
        return _calculo(motivo="linha sem UC ou UC sem trechos na planilha")
    medidos = [(t, amb.redes(t)) for t in trechos if amb.redes(t)]
    faltam = [t for t in trechos if not amb.redes(t)]
    if not medidos:
        return _calculo(
            motivo="nenhum trecho da UC tem rede medida na prancha: "
            + "; ".join(faltam)
        )
    valores = [float(valor_das_redes(redes)) for _, redes in medidos]
    evidencias = [
        {
            "tipo": "trecho_da_uc",
            "id": trecho,
            "prancha": ", ".join(
                sorted({p for r in redes for p in r.get("pranchas") or []})
            ),
            "layer": ", ".join(
                sorted({x for r in redes for x in r.get("layers") or []})
            ),
            "valor": round(valor, _CASAS_DECIMAIS),
            "unidade": unidade,
        }
        for (trecho, redes), valor in zip(medidos, valores, strict=True)
    ]
    return _calculo(
        np.sum(valores),
        motivo=("trechos sem rede medida na prancha: " + "; ".join(faltam))
        if faltam
        else None,
        parcial=bool(faltam),
        evidencias=evidencias,
        premissas=premissas,
    )


def _regra_soma_trechos(linha: dict, amb: _Ambiente) -> dict:
    return _resultado_da_uc(
        linha, amb, lambda redes: sum(r["extensao_m"] for r in redes), "m"
    )


def _regra_area_da_uc(linha: dict, amb: _Ambiente) -> dict:
    """Locação: extensão × (largura da vala + 2 × folga lateral) das classes dos trechos da UC."""
    folga_m = amb.valor("folga_locacao_lateral_m")

    def area_m2(redes):
        agregado = _agregado_das_redes(redes)
        return np.sum(agregado["extensao_m"] * (agregado["largura_m"] + 2 * folga_m))

    return _resultado_da_uc(
        linha, amb, area_m2, "m2", premissas=[amb.premissa("folga_locacao_lateral_m")]
    )


def _regra_supressao(chave: str):
    def regra(linha: dict, amb: _Ambiente) -> dict:
        por_uc = amb.contexto.get("supressao_por_uc")
        if por_uc is None:
            return _calculo(
                motivo="supressão não estimada neste build (sem ortofoto e MDS para a faixa das valas)"
            )
        dados = por_uc.get(linha.get("uc"))
        if dados is None or dados.get(chave) is None:
            return _calculo(motivo=f"UC sem supressão estimada: {linha.get('uc')!r}")
        premissas = (
            [
                {
                    "nome": "faixa_m",
                    "valor": dados["faixa_m"],
                    "unidade": "m",
                    "estado": "calibrar",
                }
            ]
            if dados.get("faixa_m") is not None
            else []
        )  # a folga não se aplica: a faixa dos trechos vai pronta
        evidencia = {
            "tipo": "supressao_ortofoto",
            "id": linha.get("uc"),
            "valor": round(float(dados[chave]), _CASAS_DECIMAIS),
            "unidade": "m2",
        }
        trechos = (
            amb.trechos_da_uc.get((linha.get("unidade_obra"), linha.get("uc"))) or []
        )
        faltam = [
            t for t in trechos if not amb.redes(t)
        ]  # a faixa só cobre os trechos medidos
        return _calculo(
            dados[chave],
            motivo=("faixa só dos trechos medidos; sem rede: " + "; ".join(faltam))
            if faltam
            else None,
            parcial=bool(faltam),
            evidencias=[evidencia],
            premissas=premissas,
        )

    return regra


def _regra_blocos(linha: dict, amb: _Ambiente) -> dict:
    return _calculo(
        motivo="ligar o balão do bloco ao trecho é da fase B (sem cálculo nesta rodada)"
    )


def _regra_declarada(linha: dict, amb: _Ambiente) -> dict:
    """Calcula, quando há como, o valor para conferir a declarada (urbanização: 100207, 100224, 100229)."""
    ligacao = amb.conceito.get("conferencia_declarada", {}).get(linha.get("composicao"))
    if ligacao is None:
        return _calculo(
            motivo="quantidade declarada pela Sanepar, sem cálculo no código"
        )
    urbanizacao = amb.contexto.get("urbanizacao")
    if not urbanizacao:
        return _calculo(
            motivo="sem urbanização no contexto do build para conferir a declarada"
        )
    chave = ligacao["chave_urbanizacao"]
    achados = [n for n in urbanizacao if chave in _sem_acento(n).lower()]
    if not achados:
        return _calculo(
            motivo=f"urbanização sem superfície {chave!r} para conferir a declarada ({ligacao['observacao']})"
        )
    valores = []
    for nome in achados:
        bruto = urbanizacao[nome]
        if hasattr(bruto, "area"):  # geometria shapely: área (m²) ou comprimento (m)
            bruto = bruto.area if ligacao["unidade"] == "m2" else bruto.length
        valores.append(float(bruto))
    evidencias = [
        {
            "tipo": "urbanizacao",
            "id": nome,
            "valor": round(v, _CASAS_DECIMAIS),
            "unidade": ligacao["unidade"],
        }
        for nome, v in zip(achados, valores, strict=True)
    ]
    return _calculo(np.sum(valores), evidencias=evidencias)


def _regra_verba(linha: dict, amb: _Ambiente) -> dict:
    return _calculo(motivo="VB: fora da quantificação")


def _regra_sem_regra(linha: dict, amb: _Ambiente) -> dict:
    return _calculo(motivo=linha.get("motivo") or "sem regra no de-para")


_REGRAS = {
    "comprimento_trecho": _regra_comprimento_trecho,
    "escavacao_trecho": _regra_volume("escavacao_m3", "vala_dimensionada"),
    "bota_fora_trecho": _regra_volume("bota_fora_m3", "bota_fora"),
    "transporte_m3km": _regra_transporte,
    "rebaixamento_vb": _regra_rebaixamento,
    "recomposicao_trecho": _regra_recomposicao,
    "soma_trechos": _regra_soma_trechos,
    "supressao_arvores": _regra_supressao("arvores_m2"),
    "supressao_rasteira": _regra_supressao("rasteira_m2"),
    "area_da_uc": _regra_area_da_uc,
    "contagem_blocos": _regra_blocos,
    "declarada": _regra_declarada,
    "verba": _regra_verba,
    "sem_regra": _regra_sem_regra,
}


def _conferir(
    calculada: float, declarada: float, grandeza: str | None, conceito: dict
) -> dict:
    """Diferença absoluta e em % da calculada contra a declarada, e se cabe na tolerância declarada no conceito."""
    tipo = grandeza if grandeza in _GRANDEZAS_COM_TOLERANCIA else "unidade"
    tolerancia_pct = float(conceito["tolerancias"][tipo])
    diferenca = calculada - declarada
    if declarada == 0:
        diferenca_pct = 0.0 if calculada == 0 else None
    else:
        diferenca_pct = diferenca / abs(declarada) * 100.0
    confere = diferenca_pct is not None and abs(diferenca_pct) <= tolerancia_pct
    return {
        "confere": bool(confere),
        "diferenca_abs": round(diferenca, _CASAS_DECIMAIS),
        "diferenca_pct": None if diferenca_pct is None else round(diferenca_pct, 2),
        "tolerancia_pct": tolerancia_pct,
    }


def _fechar(linha: dict, calculo: dict, conceito: dict) -> dict:
    """Situação final da linha: junta o cálculo da regra com a quantidade declarada."""
    declarada = linha.get("quantidade_declarada")
    quantidade, parcial, motivo = (
        calculo["quantidade"],
        calculo["parcial"],
        calculo["motivo"],
    )
    conferencia = None
    if linha.get("regra") == "verba":
        situacao, quantidade = "verba", None
    elif quantidade is not None and not parcial:
        if declarada is None:
            situacao = "calculada"
        else:
            conferencia = _conferir(
                quantidade, declarada, linha.get("grandeza"), conceito
            )
            situacao = (
                "declarada · confere"
                if conferencia["confere"]
                else "declarada · diverge"
            )
    elif declarada is not None:
        situacao = "declarada"
        motivo = motivo or "sem cálculo no código"
        if parcial:
            motivo = f"cálculo parcial, não comparável com a declarada ({motivo})"
    else:
        situacao = "parcial" if parcial else "a preencher"
    entrada, _ = _entrada_para_linha(linha, conceito)
    return {
        **linha,
        "quantidade_calculada": quantidade,
        "unidade_calculada": (entrada or {}).get("unidade")
        if quantidade is not None
        else None,
        "situacao": situacao,
        "motivo": motivo,
        "conferencia": conferencia,
        "evidencias": calculo["evidencias"],
        "premissas": calculo["premissas"],
    }


def quantificar(
    linhas: list[dict], contexto: dict, conceito: dict | None = None
) -> list[dict]:
    """Acrescenta a cada linha classificada (E1) a quantidade calculada, a evidência e a situação.

    Campos novos: `quantidade_calculada` (float ou None), `unidade_calculada`, `situacao` (uma de `SITUACOES`),
    `motivo` (sempre que não há cálculo completo), `conferencia` (diferença abs. e %, tolerância; só se a linha
    tem declarada e cálculo), `evidencias` e `premissas` ({nome, valor, unidade, estado}).
    Nada é inventado: sem rede, furo, supressão ou urbanização no contexto, a linha fica "a preencher" com o motivo.
    Determinístico: mesma entrada, mesma saída."""
    conceito = DE_PARA if conceito is None else conceito
    ambiente = _Ambiente(linhas, contexto, conceito)
    return [
        _fechar(
            linha,
            _REGRAS.get(linha.get("regra"), _regra_sem_regra)(linha, ambiente),
            conceito,
        )
        for linha in linhas
    ]


def resumo_quantidades(resultados: list[dict]) -> dict:
    """n por situação e o % das linhas vazias (sem declarada) que saíram "calculada"."""
    por_situacao = dict.fromkeys(SITUACOES, 0)
    for r in resultados:
        por_situacao[r["situacao"]] += 1
    vazias = [r for r in resultados if r.get("quantidade_declarada") is None]
    calculadas = sum(1 for r in vazias if r["situacao"] == "calculada")
    return {
        "linhas": len(resultados),
        "por_situacao": por_situacao,
        "vazias": len(vazias),
        "vazias_calculadas": calculadas,
        "pct_vazias_calculadas": round(100.0 * calculadas / len(vazias), 1)
        if vazias
        else 0.0,
    }


def _ptbr(valor: float | None, casas: int = 2) -> str:
    """Número em pt-BR (1.234,56); None vira texto vazio."""
    if valor is None:
        return ""
    return f"{valor:,.{casas}f}".replace(",", "\0").replace(".", ",").replace("\0", ".")


def _evidencia_curta(e: dict) -> str:
    partes = [
        e["tipo"],
        str(e.get("id") or ""),
        e.get("prancha") or e.get("furo") or "",
        f"{_ptbr(e['valor'])} {e['unidade']}",
    ]
    return " · ".join(p for p in partes if p)


_TIPOS_SEM_REDE = (
    "trecho_da_uc",
    "supressao_ortofoto",
    "urbanizacao",
)  # evidências cujo `id` não é de rede de vala


def _redes_e_pranchas(evidencias: list[dict]) -> tuple[list[str], list[str]]:
    """Ids das redes de vala e das pranchas citadas nas evidências originais (dicts), sem repetir, em ordem alfabética."""
    redes = {
        str(e["id"])
        for e in evidencias
        if e.get("id") and "furo" not in e and e.get("tipo") not in _TIPOS_SEM_REDE
    }
    pranchas = {
        p.strip()
        for e in evidencias
        for p in (e.get("prancha") or "").split(",")
        if p.strip()
    }
    return sorted(redes), sorted(pranchas)


def _id_da_linha(aba: str, linha: int) -> str:
    """`c211-custo-civil-15`: identificador estável da linha da planilha."""
    return (
        "c211-"
        + re.sub(r"[^a-z0-9]+", "-", _sem_acento(aba).lower()).strip("-")
        + f"-{linha}"
    )


def _linha_html(r: dict) -> dict:
    redes, pranchas = _redes_e_pranchas(r["evidencias"])
    return {
        "id": _id_da_linha(r["aba"], r["linha"]),
        "redes": redes,
        "pranchas": pranchas,
        "folha_eap": r.get("folha_eap"),
        "aba": r["aba"],
        "linha": r["linha"],
        "uc": r.get("uc"),
        "trecho": r.get("trecho"),
        "composicao": r.get("composicao"),
        "descricao": r["descricao"],
        "unidade": r.get("unidade"),
        "declarada": _ptbr(r.get("quantidade_declarada")),
        "calculada": _ptbr(r.get("quantidade_calculada")),
        "unidade_calculada": r.get("unidade_calculada"),
        "situacao": r["situacao"],
        "motivo": r.get("motivo"),
        "projeto": r.get("projeto"),
        "evidencias": [_evidencia_curta(e) for e in r["evidencias"]],
        "premissas": [
            f"{p['nome']} = {_ptbr(p['valor'])} {p['unidade']} ({p['estado']})"
            for p in r["premissas"]
        ],
    }


def para_html(resultados: list[dict]) -> list[dict]:
    """Lista enxuta para o HTML (agrupável por `folha_eap`), com os números já formatados em pt-BR.
    `id`, `redes` e `pranchas` saem das evidências originais (dicts), não do texto."""
    return [_linha_html(r) for r in resultados]


FUNCOES = (
    "ler_custo_civil",
    "classificar",
    "resumo",
    "contexto_do_build",
    "supressao_por_uc",
    "quantificar",
    "resumo_quantidades",
    "para_html",
    "metadados",
)


def metadados() -> dict:
    """Rastreabilidade do método e das premissas declaradas (regra 9 do estilo)."""
    meta = DE_PARA["metadata"]
    return {
        "modulo": "contrato_211",
        "descricao": "linhas de serviço da aba CUSTO CIVIL (colunas A–E e I, sem preço) ligadas à EAP padrão por "
        "composição",
        "funcoes": list(FUNCOES),
        "bibliografia": [],
        "premissas": [
            {
                "aplicacao": {"classificar": [f"composicoes.{codigo}"]},
                "fonte": meta["fonte"],
                "estado": entrada.get("estado", meta["estado"]),
            }
            for codigo, entrada in DE_PARA["composicoes"].items()
        ]
        + [
            {
                "aplicacao": {"classificar": [f"por_descricao.{chave}"]},
                "fonte": meta["fonte"],
                "estado": entrada.get("estado", meta["estado"]),
            }
            for chave, entrada in DE_PARA["por_descricao"].items()
        ]
        + [
            {
                "aplicacao": {"quantificar": [f"premissas.{nome}"]},
                "fonte": p["fonte"],
                "estado": p["estado"],
            }
            for nome, p in DE_PARA["premissas"].items()
        ],
        "ultima_revisao": meta["data_referencia"],
    }


def main(argv: list[str] | None = None) -> int:
    """CLI: `python -m camadas.contrato_211 PLANILHA.xlsx` imprime o resumo da classificação."""
    argumentos = sys.argv[1:] if argv is None else argv
    if len(argumentos) != 1:
        print("uso: python -m camadas.contrato_211 PLANILHA.xlsx", file=sys.stderr)
        return 2
    linhas = classificar(ler_custo_civil(argumentos[0]))
    print(json.dumps(resumo(linhas), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
