"""Testes de caracterização de `camadas/obra.py`: registram o que o código FAZ HOJE (não o que deveria fazer).

Servem para detectar mudança de comportamento sem querer antes de refatorar. Se um teste daqui falhar depois de uma
mudança intencional, a mudança precisa de justificativa no PR.

Dois tipos de resultado esperado:
- valores escritos no próprio teste (funções puras e de montagem, entradas pequenas e sintéticas);
- "golden" em `tests/golden_obra/*.json` (saída estruturada maior do pipeline completo, normalizada:
  caminhos temporários, datas, versão e blobs base64 viram marcadores; floats comparados com tolerância absoluta de
  1e-6 m).

Regenerar os golden (só com justificativa no PR; o diff do JSON é a prova do que mudou):

    ATUALIZAR_GOLDEN=1 uv run pytest tests/test_obra_caracterizacao.py -q

Nenhum teste acessa a rede, lê o relógio ou usa dados reais do repositório; a obra sintética cabe em `tmp_path`.
O que precisa de PyMuPDF ou rasterio usa `pytest.importorskip`.
"""

import gzip
import json
import os
import re
import zipfile
from pathlib import Path

import cv2
import numpy as np
import pytest

from camadas import VERSAO, geo, obra, sfm, visualizador

PASTA_GOLDEN = Path(__file__).parent / "golden_obra"
TOLERANCIA_GOLDEN_M = 1e-6
EXTENSAO_VOO = [745800.0, 7182880.0, 745840.0, 7182920.0]  # 40 m x 40 m, SIRGAS 2000 / UTM 21S (Foz do Iguaçu)
EPSG = 31981


# ---------------------------------------------------------------------------------------------------------------
# golden
def _normalizar(valor, tmp):
    """Cópia do resultado sem o que muda de máquina para máquina: caminhos, datas, versão, blobs, tempos."""
    if isinstance(valor, dict):
        return {k: _normalizar(v, tmp) for k, v in sorted(valor.items()) if k != "segundos"}
    if isinstance(valor, (list, tuple)):
        return [_normalizar(v, tmp) for v in valor]
    if isinstance(valor, float):
        return round(valor, 6)
    if isinstance(valor, str):
        if len(valor) > 200:
            return "<blob>"
        if valor.startswith("H4sI"):  # gzip em base64: o cabeçalho guarda a data
            return "<gzip>"
        texto = valor.replace(str(tmp), "<TMP>").replace(VERSAO, "<VERSAO>")
        return re.sub(r"\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2}", "<DATA>", texto)
    return valor


def _diferencas(esperado, atual, caminho="$"):
    """Lista de diferenças entre dois JSON normalizados; float com tolerância absoluta."""
    if isinstance(esperado, dict) and isinstance(atual, dict):
        if esperado.keys() != atual.keys():
            return [f"{caminho}: chaves {sorted(set(esperado) ^ set(atual))}"]
        return [d for k in esperado for d in _diferencas(esperado[k], atual[k], f"{caminho}.{k}")]
    if isinstance(esperado, list) and isinstance(atual, list):
        if len(esperado) != len(atual):
            return [f"{caminho}: {len(esperado)} itens esperados, {len(atual)} atuais"]
        return [d for i, (a, b) in enumerate(zip(esperado, atual)) for d in _diferencas(a, b, f"{caminho}[{i}]")]
    if isinstance(esperado, (int, float)) and isinstance(atual, (int, float)) and not isinstance(esperado, bool):
        return [] if abs(esperado - atual) <= TOLERANCIA_GOLDEN_M else [f"{caminho}: {esperado} != {atual}"]
    return [] if esperado == atual else [f"{caminho}: {esperado!r} != {atual!r}"]


DADOS_DE_OUTROS_MODULOS = ("construtivos", "eap", "eap_padrao", "eap_painel", "eap_gavetas", "eap_vista", "evidencias", "gavetas")


def _conferir_golden(nome, resultado, tmp):
    """Golden só do que `obra.py` monta; o que outros módulos calculam tem teste e golden próprios."""
    resultado = {k: v for k, v in resultado.items() if k not in DADOS_DE_OUTROS_MODULOS}
    arquivo = PASTA_GOLDEN / f"{nome}.json"
    atual = _normalizar(resultado, tmp)
    if os.environ.get("ATUALIZAR_GOLDEN") == "1":
        PASTA_GOLDEN.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(json.dumps(atual, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    esperado = json.loads(arquivo.read_text(encoding="utf-8"))
    assert _diferencas(esperado, atual) == []


# ---------------------------------------------------------------------------------------------------------------
# obra sintética em tmp_path
def _escrever_nuvem(pasta_sfm):
    """Terreno plano inclinado (z = 2 + 0,002 dE + 0,001 dN), grade de 25 cm em 40 m x 40 m."""
    g = np.arange(0, 40, 0.25)
    e, n = np.meshgrid(745800.0 + g, 7182880.0 + g)
    xyz = np.c_[e.ravel(), n.ravel(), 2.0 + 0.002 * (e.ravel() - 745800.0) + 0.001 * (n.ravel() - 7182880.0)]
    rgb = np.full((len(xyz), 3), 90, np.uint8)
    np.savez(pasta_sfm / "nuvem.npz", xyz=xyz, rgb=rgb)


def _escrever_sfm(raiz):
    """Cache de `etapa_sfm`: sfm.json, ortofoto georreferenciada 0,1 m/px, nuvem e duas fotos (sem rodar o SfM)."""
    pasta_sfm = raiz / "saida" / "sfm"
    pasta_sfm.mkdir(parents=True)
    fotos = raiz / "fotos"
    fotos.mkdir()
    for nome in ("a.jpg", "b.jpg"):
        cv2.imwrite(str(fotos / nome), np.full((40, 60, 3), 120, np.uint8))
    cameras = [
        {
            "nome": "a.jpg",
            "tipo": "nadir",
            "centro": [745810.0, 7182910.0, 60.04],
            "eixo": [0, 0, -1],
            "angulo_vertical": 90.0,
        },
        {
            "nome": "b.jpg",
            "tipo": "obliqua",
            "centro": [745830.0, 7182890.0, 50.0],
            "eixo": [3, 4, -1],
            "angulo_vertical": 45.0,
        },
    ]
    (pasta_sfm / "sfm.json").write_text(
        json.dumps(
            {
                "epsg": EPSG,
                "alt_decolagem_m": 700.0,
                "reprojecao_px": 0.8,
                "rmse_gps_m": 1.5,
                "n_pontos": 25600,
                "cameras": cameras,
            }
        )
    )
    cv2.imwrite(str(pasta_sfm / "ortofoto.jpg"), np.full((400, 400, 3), 100, np.uint8))
    geo.salvar_georef(pasta_sfm / "ortofoto.jpg", 745800.0, 7182920.0, 0.1, EPSG, {"extensao_utm": EXTENSAO_VOO})
    _escrever_nuvem(pasta_sfm)
    return fotos


def _cfg_base(raiz, fotos, **extras):
    return {
        "id": "mini",
        "titulo": "Obra mínima",
        "saida": str(raiz / "saida"),
        "fotos": str(fotos),
        "sig": False,
        "res_html": 0.5,
        **extras,
    }


def _gravar_cfg(raiz, cfg):
    caminho = raiz / "obra.json"
    caminho.write_text(json.dumps(cfg))
    return caminho


def _furos_sinteticos(raiz):
    """Sete furos em grade; cota de boca = terreno da nuvem + 100 m (o plano vertical deve recuperar o offset)."""
    furos = []
    for k in range(7):
        e, n = 745805.0 + 5 * (k % 4), 7182885.0 + 8 * (k // 4)
        cota = 102.0 + 0.002 * (e - 745800.0) + 0.001 * (n - 7182880.0)
        furos.append(
            {
                "id": f"SP{k + 1}",
                "E": e,
                "N": n,
                "cota_boca": round(cota, 3),
                "profundidade_m": 6.0,
                "na_m": 2.0,
                "camadas": [{"de": 0.0, "ate": 3.0, "classe": "argila", "descricao": "Argila"}],
            }
        )
    caminho = raiz / "sondagens.json"
    caminho.write_text(json.dumps({"meta": {}, "furos": furos}))
    return caminho


def _estacas_sinteticas(raiz):
    caminho = raiz / "estacas.csv"
    caminho.write_text(
        "id;E;N;diametro_cm;cota_arrasamento;comprimento_m;estrutura;desenho_origem\n"
        "E1;745806,0;7182886,0;40;101,5;12;B1;FUND-01-R1.pdf\nE2;;;40;;;B2;FUND-01-R1.pdf\n",
        encoding="utf-8",
    )
    return caminho


def _kmz_de_marcos(pasta):
    pasta.mkdir()
    lon, lat = geo.para_lonlat(745850.0, 7182900.0, EPSG)
    bloco = (
        f"<Placemark><name>MRRN1</name><description><![CDATA[<table><tr><td>CLASSIFICAÇÃO</td><td>MRRN</td>"
        f"</tr></table>]]></description><Point><coordinates> {lon},{lat},0</coordinates></Point></Placemark>"
    )
    with zipfile.ZipFile(pasta / "REDE_DE_REFERENCIA_CADASTRAL_SANEPAR_FEV_2026.kmz", "w") as z:
        z.writestr("doc.kml", f"<kml><Document>{bloco}</Document></kml>")
    return pasta


def _pdf_de_pranchas(caminho):
    """Folha 400 x 300 pt com um retângulo azul de 1ª etapa (layer _PROJETADOS) e duas linhas de tubo (EXIST_TUBO)."""
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    pagina = doc.new_page(width=400, height=300)
    projetado, tubo = doc.add_ocg("_PROJETADOS"), doc.add_ocg("EXIST_TUBO")
    pagina.draw_rect((100, 100, 200, 160), color=None, fill=(0.0, 0.43, 0.87), oc=projetado)
    pagina.draw_polyline([(50, 50), (350, 50)], color=(0, 0, 0), width=1, oc=tubo)
    pagina.draw_polyline([(50, 60), (350, 60), (350, 260)], color=(0, 0, 0), width=1, oc=tubo)
    doc.save(caminho)
    return caminho


def _prancha_cfg(pdf, **extras):
    """0,1 m por pt: o retângulo azul (100 x 60 pt) vira 10 m x 6 m no canto (745815 E, 7182905 N) do voo."""
    return {
        "id": "P1",
        "nome": "Planta 1",
        "pdf": str(pdf),
        "regras": "etapa_sanepar",
        "manchas_etapa": True,
        "layer_tubo": "EXIST_TUBO",
        "M_absoluta": [[0.1, 0, 745805.0], [0, -0.1, 7182915.0]],
        **extras,
    }


# ---------------------------------------------------------------------------------------------------------------
# funções puras do escopo
def test_quantidade_da_planilha_e_serial_de_data_do_excel():
    assert obra._qtd_da_planilha(float("nan")) == (0.0, None)
    assert obra._qtd_da_planilha(3.5) == (3.5, None)
    assert obra._qtd_da_planilha(45000) == (0.0, "quantidade na planilha parece data do Excel (45000)")
    assert obra._qtd_da_planilha(45000.5) == (45000.5, None)  # só inteiro entre 40000 e 50000 é "data"
    assert obra._qtd_da_planilha(50001) == (50001.0, None)


def test_mesma_unidade_usa_sinonimos():
    assert obra._mesma_unidade("PÇ", "un") and obra._mesma_unidade("ml", "M") and obra._mesma_unidade(" cj ", "CONJ")
    assert not obra._mesma_unidade("m", "m2")


def test_regras_da_prancha_pelo_nome_da_convencao():
    assert obra._regras({"regras": "etapa_sanepar"})[0]["classe"] == "1ª etapa"
    assert obra._regras({})[0]["classe"] == "Projetado"  # sem convenção: classes genéricas de layer


class _Linha:
    """Linha da relação de materiais (o que `DataFrame.itertuples` entrega)."""

    def __init__(self, **campos):
        padrao = {
            "codigo": "12345.0",
            "qtd_etapa1": 10.0,
            "qtd_etapa2": 0.0,
            "tabela": "T1",
            "item": "1",
            "unidade": "PÇ",
            "nome_tabela": "Tab um",
            "descricao": "Joelho",
            "etapa": float("nan"),
            "material_base": "PVC",
            "local": "ETA",
        }
        self.__dict__.update(padrao | campos)


def test_item_do_escopo_acumula_alertas_na_ordem():
    cadastro = {
        "12345": {
            "descricao": "JOELHO",
            "unidade_medida": "UN",
            "situacao": "4 - bloqueado",
            "familia": "conexao",
            "campo_ignorado": 1,
        }
    }
    item = obra._item_do_escopo(_Linha(qtd_etapa2=45000), {("T1", "1", "12345"): ("m", 7.0)}, cadastro)
    assert item["codigo"] == "12345" and item["q1"] == 10.0 and item["q2"] == 0.0
    assert item["alerta"] == (
        "quantidade na planilha parece data do Excel (45000); unidade diverge do orçamento "
        "(PÇ × m 7.0); situação no cadastro: 4 - bloqueado"
    )
    assert item["etapa"] == ""  # NaN vira texto vazio
    assert item["cadastro"] == {
        "descricao": "JOELHO",
        "unidade_medida": "UN",
        "situacao": "4 - bloqueado",
        "familia": "conexao",
    }


def test_item_do_escopo_sem_codigo_e_fora_do_cadastro():
    sem_codigo = obra._item_do_escopo(_Linha(codigo="ABC", etapa="1ª"), {}, {"1": {}})
    assert sem_codigo["alerta"] == "item sem código de material Sanepar" and sem_codigo["etapa"] == "1ª"
    assert sem_codigo["cadastro"] is None
    fora = obra._item_do_escopo(_Linha(codigo="999"), {}, {"1": {}})
    assert fora["alerta"] == "código 999 fora do cadastro de materiais Sanepar"
    sem_catalogo = obra._item_do_escopo(_Linha(codigo="ABC"), {}, {})
    assert sem_catalogo["alerta"] is None  # sem cadastro nenhum, não há o que conferir


def test_resumo_do_escopo_conta_por_tabela_e_totais():
    itens = [
        obra._item_do_escopo(_Linha(), {}, {"12345": {"unidade_medida": "UN"}}),
        obra._item_do_escopo(
            _Linha(tabela="T2", nome_tabela="Tab dois", qtd_etapa1=0.0, qtd_etapa2=2.0), {}, {"1": {}}
        ),
    ]
    por_tabela, totais = obra._resumo_escopo(itens)
    assert por_tabela == {
        "T1": {"nome": "Tab um", "n": 1, "n_q1": 1, "n_q2": 0, "n_alerta": 0},
        "T2": {"nome": "Tab dois", "n": 1, "n_q1": 0, "n_q2": 1, "n_alerta": 1},
    }
    assert totais == {"itens": 2, "itens_q1": 1, "itens_q2": 1, "com_alerta": 1, "no_cadastro": 1}


def _escopo_em_disco(raiz):
    (raiz / "rel.csv").write_text(
        "tabela;item;codigo;qtd_etapa1;qtd_etapa2;unidade;nome_tabela;descricao;etapa;material_base;local\n"
        "T1;1;1001;120,5;30;M;Tubulação;Tubo PVC DN200;1ª etapa;PVC;ETA\n"
        "T1;2;1002;2;;UN;Tubulação;Joelho 90;;PVC;ETA\n"
        "T2;1;9999;45000;1;PÇ;Válvulas;Registro;2ª etapa;FoFo;ETA\n",
        encoding="utf-8-sig",
    )
    (raiz / "itens.csv").write_text(
        "tabela;item;codigo;descricao;unidade;quantidade;projeto_desenho;unidade_obra;aba;linha_origem\n"
        "T1;1;1001;Tubo PVC DN200;M;150;DES-001-R1.pdf;UNIDADE 1;Orçamento;10\n"
        "T1;2;1002;Joelho 90;UN;2;DES-001-R1.pdf;UNIDADE 1;Orçamento;11\n"
        "T2;1;9999;Registro;UN;1;;UNIDADE 2;Orçamento;12\n",
        encoding="utf-8-sig",
    )
    with gzip.open(raiz / "catalogo.jsonl.gz", "wt", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "seq_estoque": "1001",
                    "descricao": "TUBO PVC DN200",
                    "unidade_medida": "M",
                    "situacao": "1 - licitável",
                    "familia": "tubo",
                    "dn": 200,
                }
            )
            + "\n"
        )
        f.write(
            json.dumps(
                {
                    "seq_estoque": "1002",
                    "descricao": "JOELHO",
                    "unidade_medida": "UN",
                    "situacao": "6",
                    "familia": "conexao",
                }
            )
            + "\n"
        )
    return {
        "escopo": {
            "relacao_csv": str(raiz / "rel.csv"),
            "itens_csv": str(raiz / "itens.csv"),
            "catalogo": str(raiz / "catalogo.jsonl.gz"),
            "fonte": "teste",
        }
    }


def test_etapa_escopo_le_csv_cruza_itens_e_catalogo(tmp_path):
    escopo = obra.etapa_escopo(_escopo_em_disco(tmp_path))
    assert [i["codigo"] for i in escopo["itens"]] == ["1001", "1002", "9999"]
    assert [(i["q1"], i["q2"]) for i in escopo["itens"]] == [(120.5, 30.0), (2.0, 0.0), (0.0, 1.0)]
    alerta_do_registro = (
        "quantidade na planilha parece data do Excel (45000); código 9999 fora do cadastro de materiais Sanepar"
    )
    assert [i["alerta"] for i in escopo["itens"]] == [None, None, alerta_do_registro]
    assert escopo["itens"][0]["cadastro"] == {
        "descricao": "TUBO PVC DN200",
        "unidade_medida": "M",
        "situacao": "1 - licitável",
        "familia": "tubo",
        "dn": 200,
    }
    assert escopo["totais"] == {"itens": 3, "itens_q1": 2, "itens_q2": 2, "com_alerta": 1, "no_cadastro": 2}
    assert escopo["desenhos_por_tabela"] == {"T1": "DES-001-R1.pdf"}  # T2 tem desenho vazio: fica de fora
    assert escopo["fonte"] == "teste" and escopo["fonte_cadastro"].startswith("cadastro de materiais Sanepar")


def test_etapa_escopo_sem_itens_nem_catalogo_e_sem_escopo(tmp_path):
    cfg = _escopo_em_disco(tmp_path)
    simples = obra.etapa_escopo({"escopo": {"relacao_csv": cfg["escopo"]["relacao_csv"]}})
    assert simples["desenhos_por_tabela"] == {} and simples["fonte_cadastro"] is None and simples["fonte"] == ""
    assert simples["totais"]["no_cadastro"] == 0
    assert obra.etapa_escopo({}) is None
    assert obra.etapa_escopo({"escopo": {"relacao_csv": str(tmp_path / "nao_existe.csv")}}) is None


def _pranchas_do_tubo(medido_m, eixo_faixa_m=None, georreferenciada=True):
    return [
        {
            "id": "P1",
            "nome": "Planta 1",
            "pdf": "DES-001-R2.pdf",
            "M": np.eye(3) if georreferenciada else None,
            "quantitativos": [{"layer": "TUBO", "comprimento_m": medido_m, "eixo_faixa_m": eixo_faixa_m}],
        }
    ]


def test_tubo_contrato_x_desenho_compara_metros(tmp_path):
    escopo = obra.etapa_escopo(_escopo_em_disco(tmp_path))
    cfg = {"pranchas": [{"id": "P1", "layer_tubo": "TUBO"}]}
    linhas = obra.tubo_contrato_x_desenho(escopo, _pranchas_do_tubo(140.0), cfg)
    assert linhas == [
        {
            "prancha": "P1",
            "nome": "Planta 1",
            "tabelas": ["T1"],
            "codigo": "1001",
            "descricao": "Tubo PVC DN200",
            "contrato_m": 150.5,
            "desenho_m": 140.0,
            "diferenca_pct": -7.0,
        }
    ]
    assert escopo["itens"][0]["desenho"] == {"prancha": "P1", "medido_m": 140.0, "diferenca_pct": -7.0}
    assert "desenho" not in escopo["itens"][1]  # joelho (UN) não é tubo em metros
    faixa = obra.tubo_contrato_x_desenho(
        obra.etapa_escopo(_escopo_em_disco(tmp_path)), _pranchas_do_tubo(140.0, eixo_faixa_m=151.2), cfg
    )
    assert (faixa[0]["desenho_m"], faixa[0]["diferenca_pct"]) == (151.2, 0.5)  # eixo da faixa tem prioridade


def test_tubo_contrato_x_desenho_ignora_prancha_sem_layer_ou_sem_georreferencia(tmp_path):
    escopo = obra.etapa_escopo(_escopo_em_disco(tmp_path))
    assert obra.tubo_contrato_x_desenho(escopo, _pranchas_do_tubo(140.0), {"pranchas": [{"id": "P1"}]}) == []
    cfg = {"pranchas": [{"id": "P1", "layer_tubo": "TUBO"}]}
    assert obra.tubo_contrato_x_desenho(escopo, _pranchas_do_tubo(140.0, georreferenciada=False), cfg) == []


# ---------------------------------------------------------------------------------------------------------------
# sondagens, estacas, câmeras
def _furos_para_3d():
    return [
        {
            "id": "SP1",
            "E": 745810.0,
            "N": 7182900.0,
            "cota_boca": 100.0,
            "profundidade_m": 6.0,
            "na_m": 2.5,
            "impenetravel": 1,
            "camadas": [
                {"de": 0, "ate": 2.0, "classe": "argila", "descricao": "Argila"},
                {"de": 2.0, "ate": 4.0, "classe": "areia", "descricao": "Areia"},
                {"de": None, "ate": None, "descricao": "Rocha alterada"},
            ],
        },
        {"id": "SP2", "E": None, "cota_boca": 1.0, "profundidade_m": 1.0},
        {"id": "SP3", "E": 745820.0, "N": 7182900.0, "cota_boca": 99.0, "profundidade_m": 0},
    ]


def test_sondagens_3d_em_cota_relativa_a_origem():
    perfis = obra.sondagens_3d(_furos_para_3d(), (745800.0, 7182890.0))
    assert len(perfis) == 1  # sem E, ou sem profundidade: descartados
    p = perfis[0]
    assert (p["id"], p["x"], p["y"], p["z_boca"], p["z_fundo"], p["z_na"], p["impenetravel"]) == (
        "SP1",
        10.0,
        10.0,
        100.0,
        94.0,
        97.5,
        True,
    )
    assert p["segmentos"] == [
        {"z_topo": 100.0, "z_base": 98.0, "classe": "argila", "descricao": "Argila", "confirmado": True},
        {"z_topo": 98.0, "z_base": 96.0, "classe": "areia", "descricao": "Areia", "confirmado": True},
        {"z_topo": 96.0, "z_base": 94.0, "classe": None, "descricao": "Rocha alterada", "confirmado": False},
    ]


def test_sondagens_3d_furo_sem_camadas_vira_um_segmento_nao_confirmado():
    furo = {"id": "SP9", "E": 745800.0, "N": 7182890.0, "cota_boca": 50.0, "profundidade_m": 3.0}
    p = obra.sondagens_3d([furo], (745800.0, 7182890.0))[0]
    assert p["z_na"] is None and p["impenetravel"] is False
    assert p["segmentos"] == [
        {"z_topo": 50.0, "z_base": 47.0, "classe": None, "descricao": "sem descrição", "confirmado": False}
    ]


def test_sondagens_le_dict_ou_lista_e_acrescenta_lon_lat(tmp_path):
    (tmp_path / "dict.json").write_text(
        json.dumps(
            {"meta": {}, "furos": [{"id": "SP1", "E": 745810.0, "N": 7182900.0, "cota_boca": 100.0}, {"id": "SP2"}]}
        )
    )
    furos = obra.sondagens({"sondagens": str(tmp_path / "dict.json")}, EPSG)
    assert (furos[0]["lon"], furos[0]["lat"]) == (-54.55553844, -25.45061966)
    assert "lon" not in furos[1]  # sem E/N não ganha coordenada
    (tmp_path / "lista.json").write_text(json.dumps([{"id": "SP1", "E": 745810.0, "N": 7182900.0, "epsg": 31982}]))
    assert (
        obra.sondagens({"sondagens": str(tmp_path / "lista.json")}, EPSG)[0]["lon"] == -48.55553844
    )  # EPSG do furo vence
    assert obra.sondagens({}, EPSG) == [] and obra.sondagens({"sondagens": str(tmp_path / "nao.json")}, EPSG) == []


def test_estacas_em_geojson_e_linhas_do_csv(tmp_path):
    cfg = {"estacas": str(_estacas_sinteticas(tmp_path))}
    vetor = obra.estacas(cfg, EPSG)
    assert vetor["nome"] == "Estacas hélice contínua (1)"  # a estaca sem E/N sai do mapa
    assert (vetor["grupo"], vetor["subgrupo"], vetor["visivel"], vetor["estacas"]) == (
        "Civil",
        "Geotecnia e fundação",
        False,
        True,
    )
    feicao = vetor["geojson"]["features"][0]
    assert feicao["properties"] == {
        "id": "E1",
        "E": 745806.0,
        "N": 7182886.0,
        "diametro_cm": 40.0,
        "cota_arrasamento": 101.5,
        "comprimento_m": 12.0,
        "estrutura": "B1",
        "desenho_origem": "FUND-01-R1.pdf",
        "tipo": "estaca",
    }
    lon, lat = feicao["geometry"]["coordinates"]
    assert (lon, lat) == pytest.approx((-54.5555, -25.4507), abs=1e-3)
    linhas = obra._estacas_do_csv(cfg)  # o CSV inteiro, inclusive sem coordenada
    assert [l["id"] for l in linhas] == ["E1", "E2"] and linhas[1]["E"] is None and linhas[1]["N"] is None
    assert obra.estacas({}, EPSG) is None and obra._estacas_do_csv({}) == []


def test_estacas_com_coluna_execucao_dao_o_nome_da_camada(tmp_path):
    csv = tmp_path / "estacas.csv"
    csv.write_text("id;E;N;diametro_cm;cota_arrasamento;comprimento_m;estrutura;execucao\n"
                   "EEB09-P1-1;745806,0;7182886,0;40;800,05;9,00;EEB09;escavada\n")
    vetor = obra.estacas({"estacas": str(csv)}, EPSG)
    assert vetor["nome"] == "Estacas escavada (1)"
    assert vetor["geojson"]["features"][0]["properties"]["execucao"] == "escavada"


def test_vetores_das_cameras_com_seta_de_15_m_na_obliqua_e_3_m_na_nadir():
    rel = {
        "cameras": [
            {
                "nome": "a.jpg",
                "tipo": "nadir",
                "centro": [745810.0, 7182910.0, 60.04],
                "eixo": [0, 0, -1],
                "angulo_vertical": 90.0,
            },
            {
                "nome": "b.jpg",
                "tipo": "obliqua",
                "centro": [745830.0, 7182890.0, 50.0],
                "eixo": [3, 4, -1],
                "angulo_vertical": 45.0,
            },
        ]
    }
    feicoes = obra.vetores_cameras(rel, EPSG)["features"]
    assert [f["properties"] for f in feicoes] == [
        {"nome": "a.jpg", "tipo": "nadir", "foto": "a.jpg", "angulo_vertical": 90.0, "altura_m": 60.0},
        {"nome": "b.jpg", "tipo": "obliqua", "foto": "b.jpg", "angulo_vertical": 45.0, "altura_m": 50.0},
    ]
    nadir, obliqua = (np.array(f["geometry"]["coordinates"]) for f in feicoes)
    assert np.allclose(nadir[0], nadir[1])  # comportamento atual: eixo vertical -> seta de comprimento 0
    e0, n0 = geo.para_utm(*obliqua[0], EPSG)
    e1, n1 = geo.para_utm(*obliqua[1], EPSG)
    assert (e0, n0) == pytest.approx((745830.0, 7182890.0), abs=0.01)
    assert (e1 - e0, n1 - n0) == pytest.approx((9.0, 12.0), abs=0.01)  # 15 m na direção (3, 4)/5


# ---------------------------------------------------------------------------------------------------------------
# vetores de intervenção
def test_vetor_escavacao_so_embrulha_o_geojson():
    assert obra.vetor_escavacao(None) is None
    esc = {"cavas": [1, 2, 3], "geojson": {"type": "FeatureCollection", "features": []}}
    vetor = obra.vetor_escavacao(esc)
    assert vetor == {
        "id": "escavacao",
        "nome": "Escavação calculada (3 cavas)",
        "grupo": "Intervenções",
        "subgrupo": "Movimento de terra",
        "visivel": False,
        "geojson": esc["geojson"],
        "estilo": {"color": "#92400e", "weight": 2, "fillOpacity": 0.3},
    }


def test_vetor_marcos_dentro_do_raio_e_ausencias(tmp_path, capsys):
    cfg = {"referencias_geodesicas": {"pasta": str(_kmz_de_marcos(tmp_path / "marcos")), "raio_m": 500}}
    vetor = obra.vetor_marcos(cfg, EPSG, (745800.0, 7182900.0))
    assert vetor["nome"] == "Marcos geodésicos (1)" and vetor["visivel"] is True
    propriedades = vetor["geojson"]["features"][0]["properties"]
    assert (propriedades["nome"], propriedades["rede"], propriedades["distancia_m"]) == ("MRRN1", "Sanepar", 50.0)
    assert "Marcos geodésicos a até 500 m: 1 (mais próximo: MRRN1)" in capsys.readouterr().out
    assert obra.vetor_marcos({}, EPSG, (0, 0)) is None
    assert obra.vetor_marcos({"referencias_geodesicas": {"pasta": str(tmp_path / "nao")}}, EPSG, (0, 0)) is None


def test_vetor_supressao_sem_configuracao_ou_sem_prancha_georreferenciada(tmp_path):
    assert obra.vetor_supressao({}, tmp_path, []) is None
    pytest.importorskip("rasterio")
    cfg = {"supressao": {}}
    assert obra.vetor_supressao(cfg, tmp_path, [{"M": None, "regras": "etapa_sanepar"}]) is None
    assert obra.vetor_supressao(cfg, tmp_path, [{"M": np.eye(3), "regras": ""}]) is None


# ---------------------------------------------------------------------------------------------------------------
# área da obra, limites e ortofoto
def _anel_lonlat_10_m():
    """Quadrado de 10 m (745810..745820 E, 7182890..7182900 N) como anel lon/lat."""
    e, n = (
        np.array([745810.0, 745820.0, 745820.0, 745810.0, 745810.0]),
        np.array([7182890.0] * 2 + [7182900.0] * 2 + [7182890.0]),
    )
    lon, lat = geo.para_lonlat(e, n, EPSG)
    return np.c_[lon, lat].tolist()


def _vetores_com_vala():
    poligono = {"type": "Polygon", "coordinates": [_anel_lonlat_10_m()]}
    return [
        {"id": "valas-1", "geojson": {"features": [{"geometry": poligono}]}},
        {"id": "outro", "geojson": {"features": []}},
    ]


def test_area_da_obra_envoltoria_das_fontes_mais_margem():
    crs = visualizador.crs_info(EPSG, EXTENSAO_VOO, 700.0)
    cfg = {"area_obra": {"fontes": ["^valas"], "margem_m": 5.0, "fonte": "teste"}}
    area = obra.area_da_obra(cfg, _vetores_com_vala(), EXTENSAO_VOO, crs)
    assert area.bounds == pytest.approx((745805.0, 7182885.0, 745825.0, 7182905.0), abs=0.01)
    assert area.area == pytest.approx(
        10 * 10 + 4 * 10 * 5 + np.pi * 25, abs=0.5
    )  # quadrado + faixas + 4 quartos de círculo
    assert obra.area_da_obra({}, _vetores_com_vala(), EXTENSAO_VOO, crs) is None
    assert obra.area_da_obra(cfg, _vetores_com_vala()[1:], EXTENSAO_VOO, crs) is None  # nenhuma fonte com geometria
    fora = [745900.0, 7183000.0, 745940.0, 7183040.0]
    assert obra.area_da_obra(cfg, _vetores_com_vala(), fora, crs) is None  # intervenção fora do voo


def test_resumo_e_vetor_da_area_da_obra():
    crs = visualizador.crs_info(EPSG, EXTENSAO_VOO, 700.0)
    cfg = {"area_obra": {"fontes": ["^valas"], "margem_m": 5.0, "fonte": "teste"}}
    area = obra.area_da_obra(cfg, _vetores_com_vala(), EXTENSAO_VOO, crs)
    resumo = obra._resumo_area(area, EXTENSAO_VOO, cfg)
    assert (resumo["area_m2"], resumo["fracao_do_voo"], resumo["margem_m"], resumo["fontes"], resumo["fonte"]) == (
        378,
        0.237,
        5.0,
        ["^valas"],
        "teste",
    )
    assert len(resumo["utm"]) == len(area.exterior.coords) and obra._resumo_area(None, EXTENSAO_VOO, cfg) is None
    vetor = obra._vetor_area(area, EPSG)
    assert (vetor["id"], vetor["visivel"], vetor["geojson"]["features"][0]["properties"]) == (
        "area_obra",
        False,
        {"tipo": "Área da obra", "area_m2": 378},
    )


def test_limites_da_obra_voo_mais_prancha_mais_margem():
    sem_prancha = obra.limites_da_obra([{"M": None}], EXTENSAO_VOO, EPSG, margem_m=100.0)
    prancha = {"M": [1, 0, 745700.0, 0, -1, 7182900.0], "clip_mapa": [0, 0, 100, 50], "largura": 200, "altura": 100}
    com_prancha = obra.limites_da_obra([prancha], EXTENSAO_VOO, EPSG, margem_m=100.0)
    # sem prancha: só o voo (E 745800..745840, N 7182880..7182920) + 100 m de margem
    assert _limites_em_utm(sem_prancha) == pytest.approx((745700.0, 7182780.0, 745940.0, 7183020.0), abs=0.2)
    # a prancha cobre E 745700..745800 e N 7182850..7182900 e se soma ao voo
    assert _limites_em_utm(com_prancha) == pytest.approx((745600.0, 7182750.0, 745940.0, 7183020.0), abs=0.2)


def _limites_em_utm(limites):
    """[[lat_s, lon_o], [lat_n, lon_l]] -> (E_o, N_s, E_l, N_n)."""
    (lat_s, lon_o), (lat_n, lon_l) = limites
    return (*geo.para_utm(lon_o, lat_s, EPSG), *geo.para_utm(lon_l, lat_n, EPSG))


def test_ortofoto_html_reduz_resolucao_e_marca_o_vazio_como_transparente(tmp_path):
    (tmp_path / "sfm").mkdir()
    imagem = np.full((400, 400, 3), 100, np.uint8)
    imagem[:, 200:] = 255  # metade direita sem foto (>= 250)
    cv2.imwrite(str(tmp_path / "sfm" / "ortofoto.jpg"), imagem)
    orto = {"extensao_utm": EXTENSAO_VOO, "res_m_px": 0.1}
    pacote = obra._ortofoto_html(tmp_path, orto, 0.5)
    assert (pacote["w"], pacote["h"]) == (80, 80) and pacote["m"] == [0.5, 0, 745800.0, 0, -0.5, 7182920.0]
    assert pacote["src"].startswith("data:image/webp;base64,")
    alfa = cv2.imdecode(np.frombuffer(visualizador_base64(pacote["src"]), np.uint8), cv2.IMREAD_UNCHANGED)[:, :, 3]
    assert alfa[:, :38].min() == 255 and alfa[:, 42:].max() == 0


def visualizador_base64(data_url):
    import base64

    return base64.b64decode(data_url.split(",", 1)[1])


def test_ortofoto_html_recortada_pela_area_da_obra(tmp_path):
    from shapely.geometry import box

    (tmp_path / "sfm").mkdir()
    cv2.imwrite(str(tmp_path / "sfm" / "ortofoto.jpg"), np.full((400, 400, 3), 100, np.uint8))
    orto = {"extensao_utm": EXTENSAO_VOO, "res_m_px": 0.1}
    pacote = obra._ortofoto_html(tmp_path, orto, 0.5, box(745810.0, 7182890.0, 745820.0, 7182900.0))
    assert (pacote["w"], pacote["h"]) == (21, 21)  # 10 m / 0,5 m + o pixel da borda
    assert pacote["m"] == [0.5, 0, 745810.0, 0, -0.5, 7182900.0]  # canto superior esquerdo da área


# ---------------------------------------------------------------------------------------------------------------
# sondagens x nuvem e conferências
def _vertical_de_teste():
    return {
        "offset_m": 100.0,
        "inclinacao_e": 0.0,
        "inclinacao_n": 0.0,
        "centro": [0.0, 0.0],
        "pontos": [
            {"id": "SP1", "E": 745805.0, "N": 7182885.0, "cota": 102.0, "z_nuvem": 2.0},
            {"id": "SP2", "E": 745810.0, "N": 7182885.0, "cota": 102.0, "z_nuvem": None},
            {"id": "SP3", "E": 745815.0, "N": 7182885.0, "cota": 110.0, "z_nuvem": 1.0, "descartado": True},
        ],
    }


def test_furos_x_nuvem_classifica_usado_descartado_e_sem_nuvem():
    furos = [{"id": "SP1"}, {"id": "SP1A"}, {"id": "SP2"}, {"id": "SP3"}, {"id": "SP9"}]
    saida = obra._furos_x_nuvem(furos, _vertical_de_teste())
    assert [f.get("controle_vertical") for f in saida] == [
        {"situacao": "usado", "terreno_m": 102.0, "diferenca_m": 0.0},
        {"situacao": "usado", "terreno_m": 102.0, "diferenca_m": 0.0},  # SP1A herda o ponto SP1
        {"situacao": "sem nuvem", "terreno_m": None, "diferenca_m": None},
        {"situacao": "descartado", "terreno_m": 101.0, "diferenca_m": 9.0},
        None,
    ]  # SP9 não está no ajuste
    assert obra._furos_x_nuvem([{"id": "SP1"}], None) == [{"id": "SP1"}]


def test_terreno_dos_furos_so_com_terreno_conhecido():
    furos = obra._furos_x_nuvem([{"id": "SP1"}, {"id": "SP2"}, {"id": "SP9"}], _vertical_de_teste())
    assert obra._terreno_dos_furos(furos) == [{"id": "SP1", "terreno_m": 102.0}]


def _cava_geojson():
    anel = _anel_lonlat_10_m()
    return {
        "geojson": {
            "features": [
                {
                    "properties": {"id": "C1", "fundo_m": [96.5, 97.2]},
                    "geometry": {"type": "Polygon", "coordinates": [anel]},
                },
                {"properties": {"id": "C2", "fundo_m": []}, "geometry": {"type": "Polygon", "coordinates": [anel]}},
            ]
        }
    }


def test_cavas_para_conferir_centro_em_utm_e_fundo_mais_baixo():
    cavas = obra._cavas_para_conferir(_cava_geojson(), EPSG)
    assert [c["id"] for c in cavas] == ["C1"]  # cava sem fundo calculado fica de fora
    assert (cavas[0]["E_m"], cavas[0]["N_m"]) == pytest.approx((745815.0, 7182895.0), abs=0.05)
    assert cavas[0]["cota_fundo_m"] == 96.5
    assert obra._cavas_para_conferir(None, EPSG) == []


def test_conferencias_geotecnia_resume_por_tipo():
    furos = [{"id": "SP1", "E": 745815.0, "N": 7182895.0, "cota_boca": 100.0, "na_m": 2.0}]
    cavas = obra._cavas_para_conferir(_cava_geojson(), EPSG)
    estacas = [{"id": "E2", "E": None, "N": None}]
    dados = obra._conferencias_geotecnia(furos, estacas, cavas, [{"id": "SP1", "terreno_m": 101.0}])
    assert dados["resumo"] == {"cava_x_na": 1, "sem_coordenada": 1, "boca_x_terreno": 1}
    assert [(o["tipo"], o["objeto_id"]) for o in dados["conferencias"]] == [
        ("sem_coordenada", "E2"),
        ("cava_x_na", "C1"),
        ("boca_x_terreno", "SP1"),
    ]
    assert dados["conferencias"][1]["valores"] == {"cota_fundo_m": 96.5, "cota_na_m": 98.0, "diferenca_m": 1.5}
    assert obra._conferencias_geotecnia([], estacas, cavas, []) is None  # sem sondagem não há o que conferir


# ---------------------------------------------------------------------------------------------------------------
# painel de informações e nome do HTML
def _rel_para_info():
    return {
        "cameras": [{"tipo": "nadir"}, {"tipo": "obliqua"}, {"tipo": "obliqua"}],
        "reprojecao_px": 0.8,
        "rmse_gps_m": 1.5,
        "n_pontos": 25600,
    }


def _crs_para_info():
    return {"epsg": EPSG, "nome": "SIRGAS 2000 / UTM zone 21S"}


def test_info_sem_correcao_nem_vertical():
    info = obra._info({}, _crs_para_info(), _rel_para_info(), np.zeros(2), {"res_m_px": 0.04}, None, [])
    assert info[0][0] == "Versão" and info[0][1].startswith(f"projetos_em_camadas {VERSAO} · gerado em ")
    assert info[1:] == [
        ["Sistema", "SIRGAS 2000 / UTM zone 21S (EPSG:31981)"],
        ["Levantamento", "3 fotos (2 oblíquas), SfM com reprojeção 0.80 px"],
        ["Posição absoluta", "GPS do drone (RMSE 1.5 m) — sem pontos de controle em campo"],
        ["Ortofoto", "verdadeira (MDS da nuvem), 4 cm/px; embutida a 6 cm/px"],
        ["Nuvem 3D", "25.600 pontos (Z = altura sobre a decolagem)"],
    ]


def test_info_com_correcao_vertical_e_pranchas():
    cfg = {"controle_absoluto": {"fonte": "topografia"}, "res_html": 0.1}
    vertical = {"usados": 7, "fonte": "SPT", "rms_validacao_cruzada_m": 0.123, "descartados": ["SP4"]}
    lista = [
        {"id": "P1", "M": [1], "georef": {"motivo": "afim absoluta", "residuo_mediano_m": 0.126}},
        {"id": "P2", "M": None, "georef": {"motivo": "x", "residuo_mediano_m": None}},
    ]
    info = obra._info(
        cfg, _crs_para_info(), _rel_para_info(), np.array([1.5, -2.0]), {"res_m_px": 0.04}, vertical, lista
    )
    assert info[3] == [
        "Posição absoluta",
        ("GPS do drone (RMSE 1.5 m); corrigida -1.50 m E / +2.00 m N pelo controle topográfico (topografia)"),
    ]
    assert info[4][1].endswith("embutida a 10 cm/px") and info[5][1] == "25.600 pontos (Z em cota)"
    assert info[6] == [
        "Cotas",
        ("plano ajustado a 7 furos SPT (SPT); validação cruzada 0.12 m; descartados (copa/edificação) SP4"),
    ]
    assert info[7:] == [["Prancha P1", "afim absoluta; resíduo 13 cm"]]  # prancha sem georreferência não aparece


def test_nome_html_padrao_e_personalizado():
    assert obra.nome_html({"id": "foz"}, "2026-10-29") == f"foz_camadas_v{VERSAO}_2026-10-29.html"
    assert (
        obra.nome_html({"id": "foz", "nome_html": "{id}-{data}-{versao}"}, "2026-10-29")
        == f"foz-2026-10-29-{VERSAO}.html"
    )
    assert re.fullmatch(
        rf"foz_camadas_v{re.escape(VERSAO)}_\d{{4}}-\d{{2}}-\d{{2}}\.html", obra.nome_html({"id": "foz"})
    )


# ---------------------------------------------------------------------------------------------------------------
# etapas com cache: sfm, controle absoluto e vertical
def test_etapa_sfm_usa_o_cache_e_so_refaz_quando_pedido(tmp_path, monkeypatch):
    fotos = _escrever_sfm(tmp_path)
    cfg = _cfg_base(tmp_path, fotos)
    chamadas = []
    monkeypatch.setattr(sfm, "executar", lambda *a, **k: chamadas.append((a, k)))
    rel = obra.etapa_sfm(cfg, tmp_path / "saida", refazer=False)
    assert rel["epsg"] == EPSG and len(rel["cameras"]) == 2 and chamadas == []
    obra.etapa_sfm({**cfg, "sfm": {"denso": False, "orto_res": 0.1}}, tmp_path / "saida", refazer=True)
    ((args, kwargs),) = chamadas
    assert args == (str(fotos), tmp_path / "saida" / "sfm") and kwargs["denso"] is False and kwargs["orto_res"] == 0.1
    (tmp_path / "saida" / "sfm" / "ortofoto.jpg").unlink()  # cache incompleto também refaz
    obra.etapa_sfm(cfg, tmp_path / "saida", refazer=False)
    assert len(chamadas) == 2 and chamadas[1][1] == {"denso": True, "orto_res": 0.04, "log": obra._log}


def test_controle_absoluto_sem_configuracao_nao_desloca(tmp_path):
    assert obra.etapa_controle_absoluto({}, tmp_path, False).tolist() == [0.0, 0.0]


def test_controle_absoluto_em_cache_desloca_a_ortofoto_uma_so_vez(tmp_path):
    _escrever_sfm(tmp_path)
    out = tmp_path / "saida"
    (out / "sfm" / "ajuste_absoluto.json").write_text(json.dumps({"deslocamento_m": [1.5, -2.0]}))
    cfg = {"controle_absoluto": {"pdf": "nao_usado.pdf", "afim_pt_utm": [[1, 0, 0], [0, 1, 0]]}}
    desloc = obra.etapa_controle_absoluto(cfg, out, refazer=False)
    assert desloc.tolist() == [1.5, -2.0]
    meta = json.loads((out / "sfm" / "ortofoto.json").read_text())
    assert meta["canto_sup_esq"] == [745798.5, 7182922.0]  # ortofoto - viés = posição absoluta
    assert meta["extensao_utm"] == [745798.5, 7182882.0, 745838.5, 7182922.0]
    assert meta["ajuste_absoluto_m"] == [1.5, -2.0] and meta["epsg"] == EPSG
    obra.etapa_controle_absoluto(cfg, out, refazer=False)  # idempotente: não desloca de novo
    assert json.loads((out / "sfm" / "ortofoto.json").read_text())["canto_sup_esq"] == [745798.5, 7182922.0]
    assert (out / "sfm" / "ortofoto.jgw").read_text().split("\n")[4:6] == ["745798.5500", "7182921.9500"]


def test_controle_vertical_ajusta_plano_pelas_bocas_dos_furos(tmp_path, capsys):
    _escrever_sfm(tmp_path)
    cfg = _cfg_base(
        tmp_path,
        tmp_path / "fotos",
        sondagens=str(_furos_sinteticos(tmp_path)),
        controle_vertical={"fonte": "bocas de SPT"},
    )
    assert obra.etapa_controle_vertical({}, tmp_path / "saida", np.zeros(2), EPSG) is None
    ajuste = obra.etapa_controle_vertical(cfg, tmp_path / "saida", np.zeros(2), EPSG)
    assert (ajuste["ok"], ajuste["modelo"], ajuste["usados"], ajuste["descartados"], ajuste["fonte"]) == (
        True,
        "plano",
        7,
        [],
        "bocas de SPT",
    )
    assert ajuste["offset_m"] == pytest.approx(100.0, abs=0.01)  # a boca está 100 m acima da cota da nuvem
    assert abs(ajuste["inclinacao_e"]) < 1e-3 and abs(ajuste["rms_validacao_cruzada_m"]) < 1e-3
    assert json.loads((tmp_path / "saida" / "sfm" / "ajuste_vertical.json").read_text())["usados"] == 7
    assert "Controle vertical: plano em 7 pontos" in capsys.readouterr().out


def test_controle_vertical_sem_nuvem_perto_devolve_none(tmp_path):
    _escrever_sfm(tmp_path)
    cfg = _cfg_base(
        tmp_path,
        tmp_path / "fotos",
        sondagens=str(_furos_sinteticos(tmp_path)),
        controle_vertical={"campo_cota": "cota_boca"},
    )
    ajuste = obra.etapa_controle_vertical(
        cfg, tmp_path / "saida", np.array([500.0, 0.0]), EPSG
    )  # nuvem deslocada 500 m
    assert ajuste is None
    gravado = json.loads((tmp_path / "saida" / "sfm" / "ajuste_vertical.json").read_text())
    assert gravado["ok"] is False and gravado["motivo"] == "nenhum ponto com nuvem em volta"


def test_modelo3d_em_altura_ou_em_cota(tmp_path):
    _escrever_sfm(tmp_path)
    rel = json.loads((tmp_path / "saida" / "sfm" / "sfm.json").read_text())
    pacote = obra.modelo3d(tmp_path / "saida", rel, max_pontos=100_000)
    assert pacote["referencia_z"] == "altura sobre a decolagem (m)"
    assert pacote["origem"] == [745819.0, 7182899.0, 0.0]  # piso da média, z = 0
    vertical = {"offset_m": 100.0, "inclinacao_e": 0.0, "inclinacao_n": 0.0, "centro": [0.0, 0.0]}
    em_cota = obra.modelo3d(tmp_path / "saida", rel, 100_000, desloc=(1.0, 2.0), vertical=vertical)
    assert em_cota["referencia_z"] == "cota (m), plano ajustado às sondagens"
    assert em_cota["origem"] == [745818.0, 7182897.0, 0.0]  # nuvem deslocada (1, 2) m
    assert [c["centro"][2] for c in em_cota["cameras"]] == pytest.approx([160.04, 150.0])
    so_offset = obra.modelo3d(tmp_path / "saida", rel, 100_000, vertical={**vertical, "modelo": "offset"})
    assert so_offset["referencia_z"] == "cota (m), deslocamento ajustado aos pontos de controle"


# ---------------------------------------------------------------------------------------------------------------
# pranchas (PyMuPDF)
def test_etapa_pranchas_afim_absoluta_grava_cache_e_relê(tmp_path, capsys):
    pdf = _pdf_de_pranchas(tmp_path / "p1.pdf")
    (tmp_path / "saida" / "sfm").mkdir(parents=True)
    cfg = {"pranchas": [_prancha_cfg(pdf)]}
    feitas = obra.etapa_pranchas(cfg, tmp_path / "saida", refazer=False)
    assert [(p["id"], p["ok"], p["motivo"]) for p in feitas] == [
        ("P1", True, "afim absoluta (coordenadas topográficas)")
    ]
    assert feitas[0]["M"].tolist() == [[0.1, 0.0, 745805.0], [0.0, -0.1, 7182915.0], [0.0, 0.0, 1.0]]
    assert "Prancha P1: OK (afim absoluta (coordenadas topográficas))" in capsys.readouterr().out
    cache = json.loads((tmp_path / "saida" / "pranchas" / "P1.json").read_text())
    assert (cache["ok"], cache["residuo_mediano_m"], cache["frac_05m"]) == (True, None, None)
    (tmp_path / "p1.pdf").unlink()  # com cache, o PDF nem é aberto
    relida = obra.etapa_pranchas(cfg, tmp_path / "saida", refazer=False)
    assert relida[0]["ok"] is True and relida[0]["M"].tolist() == feitas[0]["M"].tolist()


def test_etapa_pranchas_pontos_de_controle_poucos_pontos_sem_icp(tmp_path):
    pdf = _pdf_de_pranchas(tmp_path / "p1.pdf")
    (tmp_path / "saida" / "sfm").mkdir(parents=True)
    controle = {
        "pt": [[0, 0], [100, 0], [0, 100]],
        "utm": [[745805.0, 7182915.0], [745815.0, 7182915.0], [745805.0, 7182905.0]],
    }
    p = {
        "id": "P2",
        "nome": "Planta 2",
        "pdf": str(pdf),
        "pontos_controle": controle,
        "layers_referencia": "SEM_LAYER_ASSIM",
    }
    (feita,) = obra.etapa_pranchas({"pranchas": [p]}, tmp_path / "saida", False)
    assert (feita["ok"], feita["motivo"]) == (True, "pontos de controle")  # menos de 200 pontos: não roda o ICP
    assert np.asarray(feita["M"])[:2].round(6).tolist() == [[0.1, 0.0, 745805.0], [0.0, -0.1, 7182915.0]]


def test_etapa_pranchas_sem_referencia_fica_pendente(tmp_path, capsys):
    pdf = _pdf_de_pranchas(tmp_path / "p1.pdf")
    (tmp_path / "saida" / "sfm").mkdir(parents=True)
    (feita,) = obra.etapa_pranchas(
        {"pranchas": [{"id": "P3", "nome": "Planta 3", "pdf": str(pdf)}]}, tmp_path / "saida", False
    )
    assert (feita["ok"], feita["M"], feita["motivo"]) == (False, None, "sem pontos de controle nem prancha irmã")
    assert "Prancha P3: PENDENTE" in capsys.readouterr().out
    assert json.loads((tmp_path / "saida" / "pranchas" / "P3.json").read_text())["M"] is None


def test_prancha_vetorial_georreferenciada_com_quantitativos(tmp_path):
    pdf = _pdf_de_pranchas(tmp_path / "p1.pdf")
    p = {
        **_prancha_cfg(pdf),
        "M": np.array([[0.1, 0, 745805.0], [0, -0.1, 7182915.0], [0, 0, 1.0]]),
        "ok": True,
        "motivo": "afim absoluta",
    }
    pv = obra.prancha_vetorial(p, EXTENSAO_VOO)
    assert (pv["id"], pv["pdf"], pv["largura"], pv["altura"], pv["n_partes"]) == ("P1", "p1.pdf", 400.0, 300.0, 3)
    assert (pv["disciplina"], pv["grupo"], pv["subgrupo"]) == ("Geral", "Geral", "Base / outros")
    assert pv["M"] == [0.1, 0.0, 745805.0, 0.0, -0.1, 7182915.0] and pv["escala_m_pt"] == pytest.approx(0.1)
    assert pv["clip_mapa"] == pytest.approx([0.0, 0.0, 400.0, 300.0])  # voo + 25 m de margem cobre a folha toda
    assert pv["georef"] == {
        "ok": True,
        "motivo": "afim absoluta",
        "residuo_mediano_m": None,
        "frac_05m": None,
        "residuo_max_m": None,
    }
    por_layer = {q["layer"]: q for q in pv["quantitativos"]}
    assert por_layer["EXIST_TUBO"]["comprimento_m"] == pytest.approx(80.0)  # (300 + 300 + 200) pt x 0,1 m/pt
    assert por_layer["_PROJETADOS"]["area_m2"] == pytest.approx(60.0)  # 100 x 60 pt x 0,01 m²/pt²
    assert por_layer["_PROJETADOS"]["classe"] == "1ª etapa" and por_layer["EXIST_TUBO"]["classe"] is None


def test_prancha_vetorial_sem_georreferencia_nao_tem_quantitativos(tmp_path):
    pdf = _pdf_de_pranchas(tmp_path / "p1.pdf")
    pv = obra.prancha_vetorial(
        {"id": "P9", "nome": "Sem M", "pdf": str(pdf), "grupo": "Hidráulica", "subgrupo": "Tubos"}
    )
    assert pv["M"] is None and pv["escala_m_pt"] is None and pv["clip_mapa"] is None
    assert "quantitativos" not in pv and (pv["grupo"], pv["subgrupo"]) == ("Hidráulica", "Tubos")


def test_manchas_de_etapa_geram_poligono_com_area(tmp_path):
    pdf = _pdf_de_pranchas(tmp_path / "p1.pdf")
    p = {**_prancha_cfg(pdf), "M": np.array([[0.1, 0, 745805.0], [0, -0.1, 7182915.0], [0, 0, 1.0]])}
    vetores = obra.manchas_etapa(p, EPSG)
    assert [(v["id"], v["nome"], v["grupo"], v["etapa"], v["visivel"]) for v in vetores] == [
        ("P1-1ª etapa", "Projetado — 1ª etapa (áreas)", "Etapas", "1ª etapa", True)
    ]
    propriedades = vetores[0]["geojson"]["features"][0]["properties"]
    assert propriedades["area_m2"] == pytest.approx(60.0, abs=0.5) and propriedades["prancha"] == "Planta 1"
    assert vetores[0]["estilo"] == {"color": "#0b6fde", "weight": 2, "fillOpacity": 0.25}


def test_pranchas_no_mapa_separa_pendentes_e_manchas(tmp_path):
    pdf = _pdf_de_pranchas(tmp_path / "p1.pdf")
    ok = {**_prancha_cfg(pdf), "M": np.array([[0.1, 0, 745805.0], [0, -0.1, 7182915.0], [0, 0, 1.0]])}
    pendente = {
        "id": "P2",
        "nome": "Planta 2",
        "pdf": str(pdf),
        "M": None,
        "motivo": "sem malha",
        "disciplina": "Elétrica",
    }
    cfg = {"pendentes": {"Elétrica": ["Planta 9 — não entregue"], "Civil": ["Planta 8 — não entregue"]}}
    lista, vetores, pendentes = obra._pranchas_no_mapa(cfg, [ok, pendente], EXTENSAO_VOO, EPSG)
    assert [p["id"] for p in lista] == ["P1", "P2"] and [v["id"] for v in vetores] == ["P1-1ª etapa"]
    assert pendentes == {
        "Elétrica": ["Planta 2 — sem georreferência (sem malha); veja na aba Pranchas", "Planta 9 — não entregue"],
        "Civil": ["Planta 8 — não entregue"],
    }


def test_referencia_cad_desenha_as_linhas_de_referencia_em_raster_georreferenciado(tmp_path):
    pdf = _pdf_de_pranchas(tmp_path / "p1.pdf")
    base = {
        "id": "P1",
        "pdf": str(pdf),
        "M": np.array([[0.1, 0, 745805.0], [0, -0.1, 7182915.0], [0, 0, 1.0]]),
        "epsg": EPSG,
    }
    caminho = obra.referencia_cad(base, tmp_path, "EXIST", res=0.5)
    assert caminho.name.startswith("_ref_P1_") and caminho.suffix == ".png"
    img = cv2.imread(str(caminho))
    assert img.shape == (
        int((21 + 40) / 0.5) + 1,
        int((30 + 40) / 0.5) + 1,
        3,
    )  # linhas 30 m x 21 m + 20 m de folga por lado
    assert img.min() == 0 and img.max() == 230  # traço preto sobre fundo cinza 230
    meta = json.loads(caminho.with_suffix(".json").read_text())
    assert (meta["epsg"], meta["res_m_px"], meta["origem"]) == (EPSG, 0.5, "P1")
    assert meta["canto_sup_esq"] == pytest.approx([745790.0, 7182930.0], abs=0.01)
    assert obra.referencia_cad(base, tmp_path, "EXIST", res=0.5) == caminho  # segunda chamada reaproveita


def test_malha_por_continuidade_sem_vizinha_georreferenciada(tmp_path):
    p = {"continuidade": {"vizinha": "P0", "layer": "TUBO"}}
    r = obra._malha_por_continuidade(p, [], {"P0": {"M": None}}, "malha não fecha")
    assert r == {"M": None, "ok": False, "motivo": "malha não fecha; vizinha P0 sem georreferência"}
    r2 = obra._malha_por_continuidade(p, [], {}, "outro motivo")
    assert r2["ok"] is False and r2["motivo"] == "outro motivo; vizinha P0 sem georreferência"


# ---------------------------------------------------------------------------------------------------------------
# pipeline completo (construir) sobre a obra sintética: golden
def _construir_e_ler(raiz, cfg):
    html = obra.construir(_gravar_cfg(raiz, cfg))
    return html, json.loads((raiz / "saida" / "dados.json").read_text())


def _cfg_completa(raiz, fotos, **extras):
    return _cfg_base(
        raiz,
        fotos,
        sondagens=str(_furos_sinteticos(raiz)),
        estacas=str(_estacas_sinteticas(raiz)),
        controle_vertical={"fonte": "bocas de SPT"},
        **extras,
    )


def test_construir_obra_minima_sem_dependencias_opcionais(tmp_path):
    fotos = _escrever_sfm(tmp_path)
    html, dados = _construir_e_ler(tmp_path, _cfg_base(tmp_path, fotos, subtitulo="teste"))
    assert html.name == obra.nome_html({"id": "mini"}) and html.read_text(encoding="utf-8").lstrip().lower().startswith(
        "<!doctype"
    )
    assert (dados["id"], dados["titulo_curto"], dados["subtitulo"]) == ("mini", "Obra mínima", "teste")
    assert [b["id"] for b in dados["bases"]] == ["orto"] and dados["bases"][0][
        "nome"
    ] == "Ortofoto drone (1 fotos nadirais)"
    assert [v["id"] for v in dados["vetores"]] == ["cameras"]  # só as câmeras: nada mais configurado
    assert dados["pranchas"] == [] and dados["escopo"] is None and dados["vertical"] is None
    assert dados["geotecnia"] is None and dados["area_obra"] is None and sorted(dados["fotos"]) == ["a.jpg", "b.jpg"]
    assert not (tmp_path / "saida" / "sig").exists()  # "sig": false


def test_construir_golden_com_sondagens_estacas_vertical_marcos_e_area(tmp_path):
    pytest.importorskip("pymupdf")  # com estacas, a aba Obra (escopo_obra) lê o corpus de PDFs com PyMuPDF
    fotos = _escrever_sfm(tmp_path)
    cfg = _cfg_completa(
        tmp_path,
        fotos,
        referencias_geodesicas={"pasta": str(_kmz_de_marcos(tmp_path / "marcos"))},
        escopo=_escopo_em_disco(tmp_path)["escopo"],
        area_obra={"fontes": ["^cameras"], "margem_m": 8.0},
        artifact=True,
        etapas=[{"id": "1ª etapa", "cor": "#0b6fde"}],
    )
    html, dados = _construir_e_ler(tmp_path, cfg)
    assert [v["id"] for v in dados["vetores"]] == ["cameras", "estacas", "marcos", "area_obra"]
    assert dados["area_obra"]["fontes"] == ["^cameras"] and dados["bases"][0]["w"] < 80  # ortofoto recortada na área
    assert dados["vertical"]["ok"] and dados["vertical"]["usados"] == 7
    assert dados["modelo3d"]["referencia_z"] == "cota (m), plano ajustado às sondagens"
    assert [s["id"] for s in dados["modelo3d"]["sondagens"]] == [f"SP{k}" for k in range(1, 8)]
    assert (tmp_path / "saida" / (html.stem + "_artifact.html")).exists()
    _conferir_golden("construir_sondagens_estacas", dados, tmp_path)


def test_construir_golden_com_prancha_pdf_manchas_e_escopo(tmp_path):
    fotos = _escrever_sfm(tmp_path)
    pdf = _pdf_de_pranchas(tmp_path / "DES-001-R2.pdf")
    cfg = _cfg_base(
        tmp_path,
        fotos,
        pranchas=[_prancha_cfg(pdf)],
        escopo=_escopo_em_disco(tmp_path)["escopo"],
        area_obra={"fontes": ["^P1-"], "margem_m": 5.0, "fonte": "manchas de etapa"},
    )
    _, dados = _construir_e_ler(tmp_path, cfg)
    assert [v["id"] for v in dados["vetores"]] == ["P1-1ª etapa", "cameras", "area_obra"]
    assert [p["id"] for p in dados["pranchas"]] == ["P1"] and dados["area_obra"]["fonte"] == "manchas de etapa"
    assert dados["escopo"]["tubo_x_desenho"][0]["prancha"] == "P1"
    _conferir_golden("construir_prancha_pdf", dados, tmp_path)


def test_construir_refazer_so_repete_as_etapas_pedidas(tmp_path, monkeypatch):
    fotos = _escrever_sfm(tmp_path)
    caminho = _gravar_cfg(tmp_path, _cfg_base(tmp_path, fotos))
    chamadas = []
    monkeypatch.setattr(sfm, "executar", lambda *a, **k: chamadas.append(1))
    obra.construir(caminho)
    assert chamadas == []
    obra.construir(caminho, {"sfm"})
    assert chamadas == [1]


def test_main_converte_refazer_em_conjunto(monkeypatch):
    chamadas = []
    monkeypatch.setattr(obra, "construir", lambda caminho, refazer: chamadas.append((caminho, refazer)))
    obra.main(["obra.json", "--refazer", "sfm,pranchas"])
    obra.main(["outra.json"])
    assert chamadas == [("obra.json", {"sfm", "pranchas"}), ("outra.json", set())]


# ---------------------------------------------------------------------------------------------------------------
# pacote SIG (rasterio)
def test_etapa_sig_grava_geotiff_geopackage_e_pontos_qgis(tmp_path):
    pytest.importorskip("rasterio")
    pytest.importorskip("geopandas")
    pdf = _pdf_de_pranchas(tmp_path / "DES-001-R2.pdf")
    fotos = _escrever_sfm(tmp_path)
    cv2.imwrite(str(tmp_path / "saida" / "sfm" / "ortofoto_mds.png"), np.zeros((400, 400), np.uint16))
    geo.salvar_georef(
        tmp_path / "saida" / "sfm" / "ortofoto_mds.png",
        745800.0,
        7182920.0,
        0.1,
        EPSG,
        {"extensao_utm": EXTENSAO_VOO, "z_min_m": 0.0},
    )
    cfg = _cfg_base(
        tmp_path, fotos, pranchas=[_prancha_cfg(pdf)], sig=True, area_obra={"fontes": ["^P1-"], "margem_m": 5.0}
    )
    obra.construir(_gravar_cfg(tmp_path, cfg))
    sig = tmp_path / "saida" / "sig"
    assert sorted(p.name for p in sig.iterdir()) == [
        "camadas.txt",
        "mds.tif",
        "mds_obra.tif",
        "obra.gpkg",
        "ortofoto.tif",
        "ortofoto_obra.tif",
        "pontos",
    ]
    assert [p.name for p in (sig / "pontos").iterdir()] == ["P1.points"]


def test_ajustar_vertical_so_offset_nao_inclina_com_pontos_concentrados():
    rng = np.random.default_rng(0)
    xyz = np.c_[rng.uniform(0, 20, 20000), rng.uniform(0, 20, 20000), np.zeros(20000)]
    xyz[:, 2] = 0.01 * xyz[:, 0]                       # nuvem levemente inclinada
    pontos = [{"id": f"m{i}", "E": 8 + i % 3, "N": 8 + i // 3, "cota": 804.0} for i in range(8)]
    livre = sfm.ajustar_vertical(xyz, pontos)
    fixo = sfm.ajustar_vertical(xyz, pontos, so_offset=True)
    assert livre["modelo"] == "plano" and fixo["modelo"] == "offset"
    assert fixo["inclinacao_e"] == fixo["inclinacao_n"] == 0.0
    assert fixo["offset_m"] == pytest.approx(804.0 - 0.09, abs=0.03)


def test_controle_vertical_por_arquivo_de_pontos_e_solidos_de_arquivos(tmp_path):
    (tmp_path / "sfm").mkdir()
    rng = np.random.default_rng(1)
    xyz = np.c_[rng.uniform(0, 20, 20000), rng.uniform(0, 20, 20000), np.full(20000, -7.9)]
    np.savez(tmp_path / "sfm" / "nuvem.npz", xyz=xyz)
    pts = tmp_path / "pontos.json"
    pts.write_text(json.dumps({"pontos": [{"id": f"m{i}", "E": 5.0 + 2 * i, "N": 10.0, "cota": 804.05} for i in range(6)]}))
    cfg = {"controle_vertical": {"pontos": str(pts), "modelo": "offset"}}
    ajuste = obra.etapa_controle_vertical(cfg, tmp_path, np.zeros(2), EPSG)
    assert ajuste["ok"] and ajuste["modelo"] == "offset" and ajuste["usados"] == 6
    assert ajuste["offset_m"] == pytest.approx(811.95, abs=0.01)
    bl = tmp_path / "blocos.json"
    bl.write_text(json.dumps({"estrutura": "EEB10", "blocos": [
        {"rotulo": "P1", "contorno_utm": [[10, 20], [11, 20], [11, 21], [10, 21], [10, 20]], "fundo": 804.55, "face_superior": 805.30}]}))
    s = obra.solidos_de_arquivos({"solidos": [str(bl)]}, np.array([10.0, 20.0, 0.0]))
    assert s == [{"id": "EEB10-P1", "xy": [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]], "z0": 804.55, "z1": 805.30}]
    el = tmp_path / "estrutura.json"
    el.write_text(json.dumps({"estrutura": "EEB10", "elementos": [
        {"rotulo": "parede 1", "tipo": "parede", "contorno_utm": [[10, 20], [12, 20], [12, 20.2], [10, 20.2], [10, 20]], "z0": 804.05, "z1": 809.2}]}))
    s = obra.solidos_de_arquivos({"solidos": [str(bl), str(el)]}, np.array([10.0, 20.0, 0.0]))
    assert [(x["id"], x["z0"], x["z1"]) for x in s] == [("EEB10-P1", 804.55, 805.30), ("EEB10-parede 1", 804.05, 809.2)]


# --- estruturas_3d: sólidos e estacas pela chave declarativa do obra.json ---

VERMELHO_PILAR = (1.0, 0.0, 0.0)
AZUL_PAREDE = (0.0, 0.0, 1.0)
BLOCOS_PT = {"P1": (100, 100, 160, 140), "P2": (300, 100, 360, 140), "P3": (100, 300, 160, 340), "P4": (320, 300, 380, 340)}
ESTACAS_PT = [(115, 120), (145, 120), (315, 120), (345, 120), (130, 320), (350, 320)]
PAREDES_PT = [(100, 100, 360, 110), (100, 300, 380, 310)]   # na folha de fundação; a de paredes está deslocada de (40, 30)
M_PRANCHA = [[0.02, 0.0, 500000.0], [0.0, -0.02, 7000000.0]]    # pt -> UTM (0,02 m/pt, y para baixo)


def _utm_pt(x, y):
    """UTM de um ponto da folha 016 (translação 10, 5 pt até a prancha), na conta à mão."""
    return 500000.0 + 0.02 * (x + 10), 7000000.0 - 0.02 * (y + 5)


def _pdf_estrutura(caminho, formas):
    import pymupdf
    doc = pymupdf.open()
    pagina = doc.new_page(width=600, height=600)
    xrefs = {l: doc.add_ocg(l) for l in {f[0] for f in formas}}
    for layer, tipo, dados, cor in formas:
        forma = pagina.new_shape()
        if tipo == "circulo":
            forma.draw_circle(pymupdf.Point(*dados[0]), dados[1])
            forma.finish(color=(0, 0, 0), closePath=True, oc=xrefs[layer])
        else:
            x0, y0, x1, y1 = dados
            forma.draw_polyline([pymupdf.Point(*p) for p in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]])
            forma.finish(fill=cor if tipo == "preenchido" else None, color=None if tipo == "preenchido" else (0, 0, 0),
                         closePath=True, oc=xrefs[layer])
        forma.commit()
    doc.save(caminho)
    return str(caminho)


def _pilares_pt(deslocamento=(0, 0)):
    cx = [(130, 120), (330, 120), (130, 320), (350, 320)]
    return [("12", "preenchido", (x - 6 - deslocamento[0], y - 6 - deslocamento[1], x + 6 - deslocamento[0], y + 6 - deslocamento[1]), VERMELHO_PILAR) for x, y in cx]


def _pdfs_da_estrutura(raiz):
    fundacao = [("3", "contorno", b, None) for b in BLOCOS_PT.values()] + [("2", "circulo", (c, 11.5), None) for c in ESTACAS_PT]
    paredes = [("12", "preenchido", (x0 - 40, y0 - 30, x1 - 40, y1 - 30), AZUL_PAREDE) for x0, y0, x1, y1 in PAREDES_PT]
    return (_pdf_estrutura(raiz / "fund.pdf", fundacao + _pilares_pt()),
            _pdf_estrutura(raiz / "paredes.pdf", paredes + _pilares_pt((40, 30))))


def _estrutura_3d(id_estrutura, pdf_fundacao, pdf_paredes, translacao_paredes=(40, 30)):
    regiao = [0, 0, 600, 600]
    return {
        "id": id_estrutura,
        "folhas": {
            "016": {"pdf": pdf_fundacao, "transformacao": {"prancha": "eeb", "translacao_pt": [10, 5]}},
            "018": {"pdf": pdf_paredes, "transformacao": {"folha": "016", "translacao_pt": list(translacao_paredes)},
                    "conferencia": {"chave": ["12", list(VERMELHO_PILAR)], "regiao_pt": regiao, "tol_pt": 0.5}},
        },
        "fundacao": {
            "folha": "016", "regiao_pt": regiao, "estacas": {"layer": "2", "diametro_pt": [22, 23.5]},
            "blocos": {"layer": "3", "area_min_pt2": 200},
            "rotulos_pt": {"P4": [352, 322], "P2": [327, 123], "P1": [133, 118], "P3": [127, 318]},
            "niveis": {"P1": {"face_superior": 800.75, "arrasamento": 800.05}, "P2": {"face_superior": 800.55, "arrasamento": 799.85},
                       "P3": {"face_superior": 800.90, "arrasamento": 800.20}, "P4": {"face_superior": 800.60, "arrasamento": 799.90}},
            "altura_bloco_m": 0.75, "estaca": {"diametro_cm": 40, "comprimento_m": 9.0, "execucao": "escavada"},
        },
        "elementos": [
            {"tipo": "preenchido", "folha": "018", "chave": ["12", list(AZUL_PAREDE)], "regiao_pt": regiao, "elemento": "parede",
             "z0": 800.0, "z1": 808.65, "zonas": [{"regiao_pt": [200, 0, 600, 600], "z1": 809.2}], "z0_pelos_blocos": "minimo"},
            {"tipo": "retangulo", "folha": "018", "rotulo": "P1", "centro_bloco": "P1", "dimensoes_m": [0.6, 0.3],
             "z0_pelos_blocos": "minimo", "z1": 802.0, "elemento": "pilar"},
        ],
    }


def _cfg_estruturas(raiz, *estruturas):
    return {"pranchas": [{"id": "eeb", "pdf": "x.pdf", "M_absoluta": M_PRANCHA}], "estruturas_3d": list(estruturas)}


def test_estruturas_3d_gera_blocos_estacas_e_elementos_pela_conta_a_mao(tmp_path):
    fund, par = _pdfs_da_estrutura(tmp_path)
    cfg = _cfg_estruturas(tmp_path, _estrutura_3d("EEB09", fund, par))
    saida = obra.etapa_estruturas_3d(cfg, tmp_path / "saida")
    d = json.loads(Path(saida["arquivos"][0]).read_text())
    assert saida["estruturas"] == {"EEB09": True} and d["estrutura"] == "EEB09"
    assert d["metadata"]["conferencias"]["018"]["ok"] and d["metadata"]["conferencias"]["018"]["casados"] == 4
    blocos = {b["rotulo"]: b for b in d["blocos"]}
    assert sorted(blocos) == ["P1", "P2", "P3", "P4"] and [blocos[r]["estacas"] for r in sorted(blocos)] == [2, 2, 1, 1]
    p1 = np.array(blocos["P1"]["contorno_utm"])                       # bloco 100..160 x 100..140 pt
    (e0, n1), (e1, n0) = _utm_pt(100, 100), _utm_pt(160, 140)
    assert (p1[:, 0].min(), p1[:, 0].max(), p1[:, 1].min(), p1[:, 1].max()) == pytest.approx((e0, e1, n0, n1), abs=0.01)
    assert (blocos["P1"]["fundo"], blocos["P1"]["face_superior"], blocos["P1"]["arrasamento"]) == (800.0, 800.75, 800.05)
    paredes = sorted((e for e in d["elementos"] if e["tipo"] == "parede"), key=lambda e: (-np.array(e["contorno_utm"])[:, 1].mean(), np.array(e["contorno_utm"])[:, 0].mean()))
    assert [(e["z0"], e["z1"]) for e in paredes] == [(800.75, 808.65), (800.55, 809.2), (800.9, 808.65), (800.6, 809.2)]   # junto de P1, P2, P3, P4
    p = np.array(paredes[0]["contorno_utm"])                          # parede 1 esquerda: x 100..240 pt, y 100..110
    assert (p[:, 0].min(), p[:, 0].max()) == pytest.approx((_utm_pt(100, 0)[0], _utm_pt(240, 0)[0]), abs=0.01)
    pilar = next(e for e in d["elementos"] if e["tipo"] == "pilar")
    q = np.array(pilar["contorno_utm"])
    centro = _utm_pt(130, 120)
    assert (q[:, 0].max() - q[:, 0].min(), q[:, 1].max() - q[:, 1].min()) == pytest.approx((0.6, 0.3), abs=0.01)
    assert q[:4].mean(axis=0) == pytest.approx(centro, abs=0.01) and (pilar["z0"], pilar["z1"]) == (800.75, 802.0)
    import pandas as pd
    t = pd.read_csv(saida["estacas_csv"], sep=";", decimal=",", dtype={"id": str})
    assert list(t.columns) == ["id", "E", "N", "diametro_cm", "cota_arrasamento", "comprimento_m", "estrutura", "bloco", "execucao", "desenho_origem"]
    assert list(t["id"]) == ["EEB09-P1-1", "EEB09-P1-2", "EEB09-P2-1", "EEB09-P2-2", "EEB09-P3-1", "EEB09-P4-1"]
    for linha, (x, y) in zip(t.itertuples(), [ESTACAS_PT[i] for i in (0, 1, 2, 3, 4, 5)]):
        assert (linha.E, linha.N) == pytest.approx(_utm_pt(x, y), abs=0.01)
    assert t.loc[0, ["diametro_cm", "cota_arrasamento", "comprimento_m", "bloco", "execucao", "desenho_origem"]].tolist() == [40, 800.05, 9.0, "P1", "escavada", "fund.pdf"]


def test_estruturas_3d_conferencia_fora_da_tolerancia_tira_a_estrutura_sem_derrubar(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(obra, "AVISOS_DO_BUILD", [])
    fund, par = _pdfs_da_estrutura(tmp_path)
    cfg = _cfg_estruturas(tmp_path, _estrutura_3d("EEB09", fund, par), _estrutura_3d("EEB99", fund, par, translacao_paredes=(43, 30)))
    saida = obra.etapa_estruturas_3d(cfg, tmp_path / "saida")
    assert saida["estruturas"] == {"EEB09": True, "EEB99": False}
    assert [Path(a).name for a in saida["arquivos"]] == ["EEB09.json"]
    ruim = json.loads((tmp_path / "saida" / "estrutura" / "EEB99.json").read_text())
    assert ruim["blocos"] == [] and ruim["elementos"] == []
    c = ruim["metadata"]["conferencias"]["018"]
    assert not c["ok"] and c["diferenca_pt"] == pytest.approx(3, abs=0.1) and c["casados"] == 4
    assert "NÃO GERADA — conferência" in capsys.readouterr().out and any("EEB99" in a for a in obra.AVISOS_DO_BUILD)
    assert len(Path(saida["estacas_csv"]).read_text().splitlines()) == 1 + 6   # só as estacas da estrutura que passou


def test_estruturas_3d_alimenta_solidos_e_estacas_do_build(tmp_path):
    fund, par = _pdfs_da_estrutura(tmp_path)
    cfg = {**_cfg_estruturas(tmp_path, _estrutura_3d("EEB09", fund, par)), "solidos": ["antigo.json"]}
    obra._aplicar_estruturas_3d(cfg, tmp_path / "saida")
    assert cfg["solidos"][0] == "antigo.json" and cfg["solidos"][1].endswith("EEB09.json")
    assert cfg["estacas"].endswith("estacas.csv") and len(obra._estacas_do_csv(cfg)) == 6
    solidos = obra.solidos_de_arquivos({"solidos": cfg["solidos"][1:]}, np.array([500000.0, 7000000.0, 0.0]))
    assert {s["id"] for s in solidos} >= {"EEB09-P1", "EEB09-parede 1", "EEB09-pilar P1"}
    declarado = {**_cfg_estruturas(tmp_path, _estrutura_3d("EEB09", fund, par)), "estacas": "meu.csv"}
    obra._aplicar_estruturas_3d(declarado, tmp_path / "saida2")
    assert declarado["estacas"] == "meu.csv"                          # o obra.json manda
    sem = {"pranchas": []}
    obra._aplicar_estruturas_3d(sem, tmp_path / "saida3")
    assert sem == {"pranchas": []} and not (tmp_path / "saida3").exists()   # obra sem a chave não muda
