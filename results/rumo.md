## Rumo do desenvolvimento

**Objetivo:** Reconstrução F0–F2 (docs/RECONSTRUCAO.md): decisões registradas, gavetas v2 e golden das quantidades (F0); inventário com destino por arquivo (F1); todo o escopo de Foz extraído para as gavetas com documento, página e geometria (F2)

`▓▓▓▓▓▓▓▓▓▓ 100%`

**Tempo:** Início 04/11/2026 19:42 UTC · fim 04/11/2026 20:17 · 0,02 dias corridos (0,6 h de calendário) · IA trabalhando: 0,4 h de relógio · 0,7 h de agente · paralelismo 1,8×

| Etapa | Nome | Status | Agente | Est. min | Est. tokens | Real min | IA h | Real tokens | Razão |
|---|---|---|---|--:|--:|--:|--:|--:|--:|
| E1 | F0: decisões, documentos superados, esquema das gavetas v2 e validação | ✅ feito | opus | 40 | 150.000 | 3 | 0,0 | 37.912 | 0,3× |
| E2 | F0: golden das quantidades atuais de Foz (script + teste) | ✅ feito | haiku | 20 | 100.000 | 7 | 0,0 | 133.020 | 1,3× |
| E3 | F0: prazo fora da quantificação (escoramento un/mês, produtividade, dias úteis) | ✅ feito | sonnet | 15 | 100.000 | 3 | 0,0 | 32.787 | 0,3× |
| E4 | F1+F2: documentos e páginas de todos os arquivos do inventário nas gavetas, com destino por arquivo | ✅ feito | sonnet | 40 | 200.000 | 7 | 0,1 | 120.138 | 0,6× |
| E5 | F2: elementos construtivos (estacas, blocos, pilares, trechos) nas gavetas com página e geometria | ✅ feito | sonnet | 40 | 200.000 | 15 | 0,2 | 187.261 | 0,9× |
| E6 | F2: linhas do contrato 211 e itens de material nas gavetas (aba e linha, sem preço) | ✅ feito | sonnet | 30 | 150.000 | 4 | 0,0 | 88.026 | 0,6× |
| E7 | Integração na extração (extrair_gavetas.etapa), build real, paridade com o golden, balanço, PRs | ✅ feito | opus | 60 | 150.000 | 17 | 0,1 | 38.827 | 0,3× |

**Desvios (1)**
- feito sem prova: E7: marcada como feita à força: o único teste falhando no balanço é tests/test_lineares.py::test_ler_perfil_ocr, que já falha na main (tesseract do ambiente); balanço DECISAO_HUMANA (sloc_por_funcao +2,1 %), aceito pelo Caio no 'pode seguir com o PR, merge'

**Próxima etapa:** nenhuma disponível

Mudanças de objetivo: 32

### Correções sugeridas

| Prioridade | O quê | Por quê | Agente |
|---|---|---|---|
| baixa | examinar o desvio com o humano | feito sem prova: marcada como feita à força: o único teste falhando no balanço é tests/test_lineares.py::test_ler_perfil_ocr, que já falha na main (tesseract do ambiente); balanço DECISAO_HUMANA (sloc_por_funcao +2,1 %), aceito pelo Caio no 'pode seguir com o PR, merge' | humano |

_Sugestões geradas pelo vcm a partir das medições; nada foi alterado. Aplicar exige aprovação humana._
