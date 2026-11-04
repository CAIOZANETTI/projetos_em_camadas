"""Gavetas v2 (F0 da reconstrução, docs/RECONSTRUCAO.md §2.1): documentos, páginas e localizador com página."""
from camadas import gavetas


def _base(**extra):
    base = {
        "documentos": [{"documento_id": "d1", "arquivo": "f004.pdf", "sha256": "ab" * 32, "extensao": ".pdf",
                        "classe": "projeto", "paginas": 2}],
        "paginas": [{"pagina_id": "d1#p1", "documento_id": "d1", "pagina": 1, "largura_pt": 2384.0, "altura_pt": 1684.0}],
        "objetos": [{"objeto_id": "o1", "classe": "bloco"}],
        "evidencias": [{"evidencia_id": "e1", "classe": "projeto", "documento": "d1",
                        "localizador": {"pagina": 1, "retangulo_pt": [10, 10, 50, 50]}, "metodo": "camadas.prancha",
                        "executor": "código"}],
        "fatos": [{"fato_id": "f1", "objeto_id": "o1", "propriedade": "estacas_n", "valor": 4, "natureza": "projetado",
                   "evidencia_id": "e1"}],
    }
    base.update(extra)
    return base


def test_gavetas_novas_no_contrato():
    assert gavetas.GAVETAS[:2] == ["documentos", "paginas"]
    for prop in ("estacas_n", "cota_topo_m", "composicao", "quantidade", "folha_eap", "codigo_material"):
        assert prop in gavetas.REGRAS["propriedades"]


def test_base_v2_valida():
    assert gavetas.conferir_base(_base()) == []


def test_evidencia_de_documento_registrado_exige_pagina():
    sem_pagina = _base(evidencias=[{"evidencia_id": "e1", "classe": "projeto", "documento": "d1",
                                    "localizador": "prancha f004", "metodo": "x", "executor": "código"}])
    assert any("sem página" in e for e in gavetas.conferir_base(sem_pagina))


def test_planilha_vale_por_aba_e_linha():
    base = _base()
    base["documentos"].append({"documento_id": "d2", "arquivo": "211.xlsx", "sha256": "cd" * 32, "extensao": ".xlsx",
                               "classe": "planilha", "paginas": 1})
    base["evidencias"].append({"evidencia_id": "e2", "classe": "planilha", "documento": "d2",
                               "localizador": '{"aba": "CUSTO CIVIL", "linha": 16}', "metodo": "camadas.contrato_211",
                               "executor": "código"})
    assert gavetas.conferir_base(base) == []


def test_pagina_fora_do_documento():
    base = _base(paginas=[{"pagina_id": "d1#p3", "documento_id": "d1", "pagina": 3, "largura_pt": 1, "altura_pt": 1},
                          {"pagina_id": "x#p1", "documento_id": "x", "pagina": 1, "largura_pt": 1, "altura_pt": 1}])
    erros = gavetas.conferir_base(base)
    assert any("fora de 1..2" in e for e in erros) and any("não está em documentos" in e for e in erros)


def test_documento_fora_da_gaveta_segue_regra_v1():
    base = _base(documentos=[], paginas=[])
    base["evidencias"][0]["localizador"] = "prancha f004"
    assert gavetas.conferir_base(base) == []
