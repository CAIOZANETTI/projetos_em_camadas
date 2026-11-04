## Rumo do desenvolvimento

**Objetivo:** Reconstrução F3 (docs/RECONSTRUCAO.md): a EAP preenchida só pelas gavetas — laço sobre o modelo da EAP (localizada e linear), código da EAP única, cada quantidade citando objetos, fatos e evidências

`▓▓▓▓▓▓▓▓▓▓ 100%`

**Tempo:** Início 04/11/2026 20:24 UTC · fim 04/11/2026 21:01 · 0,03 dias corridos (0,6 h de calendário) · IA trabalhando: 0,3 h de relógio · 0,3 h de agente · paralelismo 1,1×

| Etapa | Nome | Status | Agente | Est. min | Est. tokens | Real min | IA h | Real tokens | Razão |
|---|---|---|---|--:|--:|--:|--:|--:|--:|
| E1 | F3: eap_preencher (itens técnicos e folhas pelas gavetas, paridade com o golden; fecha lacunas de extração se houver) | ✅ feito | sonnet | 45 | 250.000 | 15 | 0,2 | 52.572 | 0,3× |
| E2 | F3: ligação no build, build real, paridade, balanço, PR e merge | ✅ feito | opus | 45 | 120.000 | 21 | 0,1 | 9.119 | 0,5× |

**Desvios (1)**
- feito sem prova: E2: marcada como feita à força: o único teste falhando é tests/test_lineares.py::test_ler_perfil_ocr, que já falha na main (tesseract do ambiente); balanço SEM_GANHO sem piora; build real: interface 331/0, golden 0 diferença, EAP única 37/37

**Próxima etapa:** nenhuma disponível

Mudanças de objetivo: 33

### Correções sugeridas

| Prioridade | O quê | Por quê | Agente |
|---|---|---|---|
| baixa | examinar o desvio com o humano | feito sem prova: marcada como feita à força: o único teste falhando é tests/test_lineares.py::test_ler_perfil_ocr, que já falha na main (tesseract do ambiente); balanço SEM_GANHO sem piora; build real: interface 331/0, golden 0 diferença, EAP única 37/37 | humano |

_Sugestões geradas pelo vcm a partir das medições; nada foi alterado. Aplicar exige aprovação humana._
