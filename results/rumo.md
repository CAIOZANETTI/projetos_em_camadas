## Rumo do desenvolvimento

**Objetivo:** Reconstrução F5 (docs/RECONSTRUCAO.md): laço até a EAP completa — o texto dos editais, memoriais e laudos lido por código para as gavetas (menções com página), e para cada folha a preencher: onde está, o roteiro do próximo passe (IA com citação conferida ou o Caio) e o portão 'EAP completa'

`▓▓▓▓▓▓▓▓▓▓ 100%`

**Tempo:** Início 04/11/2026 21:57 UTC · fim 04/11/2026 22:26 · 0,02 dias corridos (0,5 h de calendário) · IA trabalhando: 0,2 h de relógio · 0,4 h de agente · paralelismo 1,9×

| Etapa | Nome | Status | Agente | Est. min | Est. tokens | Real min | IA h | Real tokens | Razão |
|---|---|---|---|--:|--:|--:|--:|--:|--:|
| E1 | F5: texto dos documentos → gavetas (menções por página) | ✅ feito | sonnet | 45 | 250.000 | 30 | 0,1 | 306.619 | 1,2× |
| E2 | F5: laço da EAP (destino de cada folha a preencher, roteiro do próximo passe, portão EAP completa) | ✅ feito | sonnet | 45 | 250.000 | 6 | 0,1 | 303.671 | 1,2× |
| E3 | F5: ligação no build, build real, balanço, PR e merge | ✅ feito | opus | 45 | 120.000 | 0 | 0,0 | 0 | 0,0× |

**Desvios (2)**
- feito sem prova: E1: marcada como feita à força: o único teste falhando é tests/test_lineares.py::test_ler_perfil_ocr, que já falha na main; balanço SEM_GANHO sem piora; build real: interface 331/0, golden 0, EAP única 0, complementares 0
- feito sem prova: E3: marcada como feita à força: o único teste falhando é tests/test_lineares.py::test_ler_perfil_ocr, que já falha na main; balanço SEM_GANHO sem piora; build real: interface 331/0, golden 0, EAP única 0, complementares 0

**Próxima etapa:** nenhuma disponível

Mudanças de objetivo: 35

### Correções sugeridas

| Prioridade | O quê | Por quê | Agente |
|---|---|---|---|
| baixa | examinar o desvio com o humano | feito sem prova: marcada como feita à força: o único teste falhando é tests/test_lineares.py::test_ler_perfil_ocr, que já falha na main; balanço SEM_GANHO sem piora; build real: interface 331/0, golden 0, EAP única 0, complementares 0 | humano |
| baixa | examinar o desvio com o humano | feito sem prova: marcada como feita à força: o único teste falhando é tests/test_lineares.py::test_ler_perfil_ocr, que já falha na main; balanço SEM_GANHO sem piora; build real: interface 331/0, golden 0, EAP única 0, complementares 0 | humano |

_Sugestões geradas pelo vcm a partir das medições; nada foi alterado. Aplicar exige aprovação humana._
