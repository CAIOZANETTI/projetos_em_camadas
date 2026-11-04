## Rumo do desenvolvimento

**Objetivo:** Aba EAP legível e interativa: WBS em árvore navegável, Contrato 211 agrupado por trecho, seções em sub-abas e clique que leva ao mapa e à prancha

`▓▓▓▓▓▓▓▓▓▓ 100%`

**Tempo:** Início 04/11/2026 17:48 UTC · fim 04/11/2026 18:53 · 0,05 dias corridos (1,1 h de calendário) · IA trabalhando: 0,8 h de relógio · 0,9 h de agente · paralelismo 1,1×

| Etapa | Nome | Status | Agente | Est. min | Est. tokens | Real min | IA h | Real tokens | Razão |
|---|---|---|---|--:|--:|--:|--:|--:|--:|
| E1 | Vista da aba EAP montada em Python (camadas/eap_vista.py): seções, árvore da WBS com as linhas do contrato, contrato por UC e trecho, contagens e índice de busca | ✅ feito | sonnet | 30 | 200.000 | 6 | 0,1 | 144.162 | 0,7× |
| E2 | Aba EAP no template: modo largo, sub-abas, árvore interativa, busca, filtros e ligação com o mapa e a prancha; verificações de interface | ✅ feito | sonnet | 60 | 300.000 | 39 | 0,5 | 465.666 | 1,6× |
| E3 | Build real, capturas, balanço, PR e merge | ✅ feito | opus | 45 | 120.000 | 20 | 0,2 | 32.730 | 0,5× |

**Desvios (2)**
- estouro: E2: tokens real é 1,6× o estimado
- feito sem prova: E3: marcada como feita à força: o único teste falhando no balanço é tests/test_lineares.py::test_ler_perfil_ocr, que já falha na main (tesseract 5.3.4 do ambiente); balanço SEM_GANHO sem piora, 1374 testes passando, interface 331/0

**Próxima etapa:** nenhuma disponível

Mudanças de objetivo: 31

### Correções sugeridas

| Prioridade | O quê | Por quê | Agente |
|---|---|---|---|
| média | dividir a etapa em partes menores ou recalibrar a estimativa | estouro: tokens real é 1,6× o estimado | opus |
| baixa | examinar o desvio com o humano | feito sem prova: marcada como feita à força: o único teste falhando no balanço é tests/test_lineares.py::test_ler_perfil_ocr, que já falha na main (tesseract 5.3.4 do ambiente); balanço SEM_GANHO sem piora, 1374 testes passando, interface 331/0 | humano |

_Sugestões geradas pelo vcm a partir das medições; nada foi alterado. Aplicar exige aprovação humana._
