## Rumo do desenvolvimento

**Objetivo:** Reconstrução F4 (docs/RECONSTRUCAO.md): os serviços complementares (concreto, forma, armadura, lastro, escoramento, impermeabilização; vala: corte, demolição, escavação, escoramento, berço, envoltória, reaterro, bota-fora, recomposição) calculados das gavetas e gravados nelas, preenchendo as folhas 'calculada' da EAP única

`▓▓▓▓▓▓▓░░░ 71%`

**Tempo:** Início 04/11/2026 21:04 UTC · fim agora (em andamento) · 0,03 dias corridos (0,8 h de calendário) · IA trabalhando: 0,5 h de relógio · 0,5 h de agente · paralelismo 1,0×

| Etapa | Nome | Status | Agente | Est. min | Est. tokens | Real min | IA h | Real tokens | Razão |
|---|---|---|---|--:|--:|--:|--:|--:|--:|
| E1 | F4: serviços complementares pelas gavetas (gavetas_servicos) e folhas 'calculada' na EAP única | 🔄 fazendo | sonnet | 60 | 300.000 | 48 | 0,4 | 365.403 | 1,2× |
| E2 | F4: ligação no build, build real, paridade, balanço, PR e merge | ✅ feito | opus | 45 | 120.000 | 0 | 0,0 | 0 | 0,0× |

**Desvios (4)**
- fora do plano: camadas/gavetas_construtivos.py alterado sem pertencer a nenhum entregável
- fora do plano: camadas/obra.py alterado sem pertencer a nenhum entregável
- fora do plano: conceitos/gavetas.json alterado sem pertencer a nenhum entregável
- feito sem prova: E2: marcada como feita à força: o único teste falhando é tests/test_lineares.py::test_ler_perfil_ocr, que já falha na main; balanço SEM_GANHO sem piora; build real: interface 331/0, golden 0, EAP única 0, complementares 25/25

**Próxima etapa:** nenhuma disponível

Mudanças de objetivo: 34

### Correções sugeridas

| Prioridade | O quê | Por quê | Agente |
|---|---|---|---|
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: camadas/gavetas_construtivos.py alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: camadas/obra.py alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: conceitos/gavetas.json alterado sem pertencer a nenhum entregável | humano |
| baixa | examinar o desvio com o humano | feito sem prova: marcada como feita à força: o único teste falhando é tests/test_lineares.py::test_ler_perfil_ocr, que já falha na main; balanço SEM_GANHO sem piora; build real: interface 331/0, golden 0, EAP única 0, complementares 25/25 | humano |

_Sugestões geradas pelo vcm a partir das medições; nada foi alterado. Aplicar exige aprovação humana._
