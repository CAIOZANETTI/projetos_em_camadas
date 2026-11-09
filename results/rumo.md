## Rumo do desenvolvimento

**Objetivo:** Reconstrução F4b (docs/RECONSTRUCAO.md §5.5): vala única pela vala_rede — os serviços da vala (demolição, escavação, escoramento, rebaixamento, berço, envoltória, reaterro, bota-fora, transporte, recomposição) saem de um só caminho, as redes de vala (RV-*) das gavetas; a vala do trecho e a vala refeita pelo contrato_211 deixam de existir; fecha o portão da F4 (0 caminho paralelo)

`▓▓▓▓▓▓▓▓▓▓ 100%`

**Tempo:** Início 09/11/2026 13:05 UTC · fim 09/11/2026 14:40 · 0,07 dias corridos (1,6 h de calendário) · IA trabalhando: 0,7 h de relógio · 0,9 h de agente · paralelismo 1,3×

| Etapa | Nome | Status | Agente | Est. min | Est. tokens | Real min | IA h | Real tokens | Razão |
|---|---|---|---|--:|--:|--:|--:|--:|--:|
| E1 | F4b: vala das gavetas pela rede_vala (gavetas_servicos e eap_preencher) | ✅ feito | sonnet | 60 | 300.000 | 63 | 0,4 | 246.004 | 1,1× |
| E2 | F4b: contrato_211 lê a vala das gavetas | ✅ feito | sonnet | 60 | 300.000 | 46 | 0,1 | 132.902 | 0,8× |
| E3 | F4b: build real, golden de propósito, três verdes, balanço, PR e merge | ✅ feito | opus | 60 | 150.000 | 38 | 0,3 | 115.817 | 0,8× |
| E1b | F4b: uma largura por rede (material do contrato e DN nominal nos três cálculos), CRS da obra nas gavetas e sistema pelo trecho do contrato (achados do build real) | ✅ feito | sonnet | 30 | 150.000 | 75 | 0,0 | 60.779 | 2,5× |

**Desvios (5)**
- feito sem prova: E1: marcada como feita à força: o único teste falhando é tests/test_lineares.py::test_ler_perfil_ocr, que já falha na main (tesseract do ambiente; tarefa separada sugerida); balanço SEM_GANHO sem piora; aferição ok; determinismo ok; build real: interface 331/0, 0 caminho paralelo, paridades 0, EAP única 37/37
- feito sem prova: E2: marcada como feita à força: o único teste falhando é tests/test_lineares.py::test_ler_perfil_ocr, que já falha na main (tesseract do ambiente; tarefa separada sugerida); balanço SEM_GANHO sem piora; aferição ok; determinismo ok; build real: interface 331/0, 0 caminho paralelo, paridades 0, EAP única 37/37
- feito sem prova: E3: marcada como feita à força: o único teste falhando é tests/test_lineares.py::test_ler_perfil_ocr, que já falha na main (tesseract do ambiente; tarefa separada sugerida); balanço SEM_GANHO sem piora; aferição ok; determinismo ok; build real: interface 331/0, 0 caminho paralelo, paridades 0, EAP única 37/37
- estouro: E1b: tempo real é 2,5× o estimado
- feito sem prova: E1b: marcada como feita à força: etapa registrada depois de feita: o build real mostrou três larguras para a mesma rede, o CRS 31982 fixo e 4 redes sem sistema; mesmo motivo do teste OCR

**Próxima etapa:** nenhuma disponível

Mudanças de objetivo: 37

### Correções sugeridas

| Prioridade | O quê | Por quê | Agente |
|---|---|---|---|
| média | dividir a etapa em partes menores ou recalibrar a estimativa | estouro: tempo real é 2,5× o estimado | opus |
| baixa | examinar o desvio com o humano | feito sem prova: marcada como feita à força: o único teste falhando é tests/test_lineares.py::test_ler_perfil_ocr, que já falha na main (tesseract do ambiente; tarefa separada sugerida); balanço SEM_GANHO sem piora; aferição ok; determinismo ok; build real: interface 331/0, 0 caminho paralelo, paridades 0, EAP única 37/37 | humano |
| baixa | examinar o desvio com o humano | feito sem prova: marcada como feita à força: o único teste falhando é tests/test_lineares.py::test_ler_perfil_ocr, que já falha na main (tesseract do ambiente; tarefa separada sugerida); balanço SEM_GANHO sem piora; aferição ok; determinismo ok; build real: interface 331/0, 0 caminho paralelo, paridades 0, EAP única 37/37 | humano |
| baixa | examinar o desvio com o humano | feito sem prova: marcada como feita à força: o único teste falhando é tests/test_lineares.py::test_ler_perfil_ocr, que já falha na main (tesseract do ambiente; tarefa separada sugerida); balanço SEM_GANHO sem piora; aferição ok; determinismo ok; build real: interface 331/0, 0 caminho paralelo, paridades 0, EAP única 37/37 | humano |
| baixa | examinar o desvio com o humano | feito sem prova: marcada como feita à força: etapa registrada depois de feita: o build real mostrou três larguras para a mesma rede, o CRS 31982 fixo e 4 redes sem sistema; mesmo motivo do teste OCR | humano |

_Sugestões geradas pelo vcm a partir das medições; nada foi alterado. Aplicar exige aprovação humana._
