## Rumo do desenvolvimento

**Objetivo:** Reconstrução F5b (docs/RECONSTRUCAO.md §3, F5): fechar as 20 folhas obrigatórias que travam o portão EAP completa pela escada — código primeiro (contrato e Relação de Materiais nas folhas, quantidades calculadas do contrato), depois IA com citação conferida sobre um roteiro limpo, e o que sobrar vai ao Caio como ausente do projeto

`▓▓▓▓▓▓▓▓▓▓ 100%`

**Tempo:** Início 17/11/2026 13:33 UTC · fim 18/11/2026 20:49 · 1,30 dias corridos (31,3 h de calendário) · IA trabalhando: 0,7 h de relógio · 1,2 h de agente · paralelismo 1,7×

| Etapa | Nome | Status | Agente | Est. min | Est. tokens | Real min | IA h | Real tokens | Razão |
|---|---|---|---|--:|--:|--:|--:|--:|--:|
| E1 | F5b: contrato e Relação de Materiais nas folhas da EAP única (código) | ✅ feito | sonnet | 60 | 300.000 | 1.876 | 0,2 | 321.974 | 31,3× |
| E2 | F5b: roteiro limpo (termos genéricos fora, unidade admitida pela folha) | ✅ feito | sonnet | 45 | 200.000 | 1.876 | 0,3 | 323.153 | 41,7× |
| E3 | F5b: ponte IA conferida → gavetas → EAP única (declarada por documento) | ✅ feito | sonnet | 45 | 250.000 | 1.862 | 0,1 | 207.120 | 41,4× |
| E4 | F5b: leitura de IA das folhas que travam, com citação conferida | ✅ feito | sonnet | 60 | 400.000 | 1.848 | 0,0 | 180.857 | 30,8× |
| E5 | F5b: build real, portão, lista ao Caio, três verdes, balanço, PR e merge | ✅ feito | opus | 60 | 150.000 | 0 | 0,0 | 0 | 0,0× |

**Desvios (11)**
- estouro: E1: tempo real é 31,3× o estimado
- feito sem prova: E1: marcada como feita à força: o único teste falhando é tests/test_lineares.py::test_ler_perfil_ocr, que já falha na main (tesseract do ambiente); balanço MANTER; aferição ok; determinismo ok; build real: interface 331/0, golden 0, EAP única × codificada 0, 23 leituras de IA reconferidas
- estouro: E2: tokens real é 1,6× o estimado
- estouro: E2: tempo real é 41,7× o estimado
- feito sem prova: E2: marcada como feita à força: o único teste falhando é tests/test_lineares.py::test_ler_perfil_ocr, que já falha na main (tesseract do ambiente); balanço MANTER; aferição ok; determinismo ok; build real: interface 331/0, golden 0, EAP única × codificada 0, 23 leituras de IA reconferidas
- estouro: E3: tempo real é 41,4× o estimado
- feito sem prova: E3: marcada como feita à força: o único teste falhando é tests/test_lineares.py::test_ler_perfil_ocr, que já falha na main (tesseract do ambiente); balanço MANTER; aferição ok; determinismo ok; build real: interface 331/0, golden 0, EAP única × codificada 0, 23 leituras de IA reconferidas
- estouro: E4: tempo real é 30,8× o estimado
- feito sem prova: E4: marcada como feita à força: o único teste falhando é tests/test_lineares.py::test_ler_perfil_ocr, que já falha na main (tesseract do ambiente); balanço MANTER; aferição ok; determinismo ok; build real: interface 331/0, golden 0, EAP única × codificada 0, 23 leituras de IA reconferidas
- entregável ausente: E4: marcada como feita sem: exemplos/foz/evidencias_ia.jsonl
- feito sem prova: E5: marcada como feita à força: o único teste falhando é tests/test_lineares.py::test_ler_perfil_ocr, que já falha na main (tesseract do ambiente); balanço MANTER; aferição ok; determinismo ok; build real: interface 331/0, golden 0, EAP única × codificada 0, 23 leituras de IA reconferidas

**Próxima etapa:** nenhuma disponível

Mudanças de objetivo: 39

### Correções sugeridas

| Prioridade | O quê | Por quê | Agente |
|---|---|---|---|
| alta | criar o entregável ou corrigir o status da etapa | entregável ausente: marcada como feita sem: exemplos/foz/evidencias_ia.jsonl | sonnet |
| média | dividir a etapa em partes menores ou recalibrar a estimativa | estouro: tempo real é 31,3× o estimado | opus |
| média | dividir a etapa em partes menores ou recalibrar a estimativa | estouro: tokens real é 1,6× o estimado | opus |
| média | dividir a etapa em partes menores ou recalibrar a estimativa | estouro: tempo real é 41,7× o estimado | opus |
| média | dividir a etapa em partes menores ou recalibrar a estimativa | estouro: tempo real é 41,4× o estimado | opus |
| média | dividir a etapa em partes menores ou recalibrar a estimativa | estouro: tempo real é 30,8× o estimado | opus |
| baixa | examinar o desvio com o humano | feito sem prova: marcada como feita à força: o único teste falhando é tests/test_lineares.py::test_ler_perfil_ocr, que já falha na main (tesseract do ambiente); balanço MANTER; aferição ok; determinismo ok; build real: interface 331/0, golden 0, EAP única × codificada 0, 23 leituras de IA reconferidas | humano |
| baixa | examinar o desvio com o humano | feito sem prova: marcada como feita à força: o único teste falhando é tests/test_lineares.py::test_ler_perfil_ocr, que já falha na main (tesseract do ambiente); balanço MANTER; aferição ok; determinismo ok; build real: interface 331/0, golden 0, EAP única × codificada 0, 23 leituras de IA reconferidas | humano |
| baixa | examinar o desvio com o humano | feito sem prova: marcada como feita à força: o único teste falhando é tests/test_lineares.py::test_ler_perfil_ocr, que já falha na main (tesseract do ambiente); balanço MANTER; aferição ok; determinismo ok; build real: interface 331/0, golden 0, EAP única × codificada 0, 23 leituras de IA reconferidas | humano |
| baixa | examinar o desvio com o humano | feito sem prova: marcada como feita à força: o único teste falhando é tests/test_lineares.py::test_ler_perfil_ocr, que já falha na main (tesseract do ambiente); balanço MANTER; aferição ok; determinismo ok; build real: interface 331/0, golden 0, EAP única × codificada 0, 23 leituras de IA reconferidas | humano |
| baixa | examinar o desvio com o humano | feito sem prova: marcada como feita à força: o único teste falhando é tests/test_lineares.py::test_ler_perfil_ocr, que já falha na main (tesseract do ambiente); balanço MANTER; aferição ok; determinismo ok; build real: interface 331/0, golden 0, EAP única × codificada 0, 23 leituras de IA reconferidas | humano |

_Sugestões geradas pelo vcm a partir das medições; nada foi alterado. Aplicar exige aprovação humana._
