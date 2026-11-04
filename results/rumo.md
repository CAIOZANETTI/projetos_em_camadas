## Rumo do desenvolvimento

**Objetivo:** Orçamento de Foz 211, sem preço: as quantidades das linhas vazias da CUSTO CIVIL calculadas em código, com evidência, e as declaradas conferidas

`▓▓▓▓▓▓▓▓▓▓ 100%`

**Tempo:** Início 04/11/2026 14:24 UTC · fim 04/11/2026 15:44 · 0,06 dias corridos (1,3 h de calendário) · IA trabalhando: 0,7 h de relógio · 1,3 h de agente · paralelismo 1,8×

| Etapa | Nome | Status | Agente | Est. min | Est. tokens | Real min | IA h | Real tokens | Razão |
|---|---|---|---|--:|--:|--:|--:|--:|--:|
| E1 | Leitor da CUSTO CIVIL e de-para composição → EAP | ✅ feito | sonnet | 30 | 150.000 | 7 | 0,1 | 160.476 | 1,1× |
| E2 | Regras por composição e conferência das declaradas | ✅ feito | sonnet | 45 | 200.000 | 10 | 0,1 | 186.582 | 0,9× |
| E3 | Trechos FD internos da ETA pela prancha citada | ✅ feito | sonnet | 60 | 250.000 | 26 | 0,4 | 320.929 | 1,3× |
| E4 | Bloco no HTML e verificações de interface | ✅ feito | haiku | 20 | 80.000 | 7 | 0,1 | 193.874 | 2,4× |
| E5 | Build real, conferência de 5 linhas, balanço, PR e merge | ✅ feito | opus | 45 | 120.000 | 54 | 0,3 | 81.769 | 1,2× |

**Desvios (2)**
- estouro: E4: tokens real é 2,4× o estimado
- feito sem prova: E5: marcada como feita à força: o único teste falhando no balanço é tests/test_lineares.py::test_ler_perfil_ocr, que já falha na main (o tesseract 5.3.4 deste ambiente lê INFERIOR como INFERGR9O); balanço MANTER, 1339 testes passando, interface 274/0

**Próxima etapa:** nenhuma disponível

Mudanças de objetivo: 27

### Correções sugeridas

| Prioridade | O quê | Por quê | Agente |
|---|---|---|---|
| média | dividir a etapa em partes menores ou recalibrar a estimativa | estouro: tokens real é 2,4× o estimado | opus |
| baixa | examinar o desvio com o humano | feito sem prova: marcada como feita à força: o único teste falhando no balanço é tests/test_lineares.py::test_ler_perfil_ocr, que já falha na main (o tesseract 5.3.4 deste ambiente lê INFERIOR como INFERGR9O); balanço MANTER, 1339 testes passando, interface 274/0 | humano |

_Sugestões geradas pelo vcm a partir das medições; nada foi alterado. Aplicar exige aprovação humana._
