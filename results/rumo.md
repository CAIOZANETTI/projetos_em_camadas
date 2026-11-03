## Rumo do desenvolvimento

**Objetivo:** Rodar o build real de Foz (ETA Vila C) e conferir a memória espacial com dados verdadeiros: paridade das gavetas, cavas, conciliação com a EAP codificada e aba EAP no HTML

`▓▓▓▓▓▓▓▓▓▓ 100%`

**Tempo:** Início 02/11/2026 22:54 UTC · fim 03/11/2026 01:07 · 0,09 dias corridos (2,2 h de calendário) · IA trabalhando: 1,1 h de relógio · 1,2 h de agente · paralelismo 1,1×

| Etapa | Nome | Status | Agente | Est. min | Est. tokens | Real min | IA h | Real tokens | Razão |
|---|---|---|---|--:|--:|--:|--:|--:|--:|
| E1 | Ingestão do Drive: inventário, PDFs, fotos do drone e planilha | ✅ feito | haiku | 60 | 200.000 | 19 | 0,3 | 629.908 | 3,1× |
| E2 | Insumos derivados: sondagens pelo leitor de laudo, escopo pela planilha | ✅ feito | opus | 30 | 120.000 | 7 | 0,1 | 146.034 | 1,2× |
| E3 | Build real de Foz (SfM, pranchas, gavetas, EAP, HTML) | ✅ feito | opus | 60 | 80.000 | 85 | 0,4 | 167.677 | 2,1× |
| E4 | Conferência dos resultados, relatório e PR | ✅ feito | opus | 45 | 200.000 | 21 | 0,2 | 91.690 | 0,5× |

**Desvios (24)**
- fora do plano: CHANGELOG.md alterado sem pertencer a nenhum entregável
- fora do plano: camadas/__init__.py alterado sem pertencer a nenhum entregável
- fora do plano: camadas/evidencias.py alterado sem pertencer a nenhum entregável
- fora do plano: camadas/extrair_gavetas.py alterado sem pertencer a nenhum entregável
- fora do plano: camadas/gavetas.py alterado sem pertencer a nenhum entregável
- fora do plano: camadas/geotecnia.py alterado sem pertencer a nenhum entregável
- fora do plano: camadas/obra.py alterado sem pertencer a nenhum entregável
- fora do plano: camadas/obras_lineares.py alterado sem pertencer a nenhum entregável
- fora do plano: camadas/prancha.py alterado sem pertencer a nenhum entregável
- fora do plano: conceitos/de_para_extracao.json alterado sem pertencer a nenhum entregável
- fora do plano: conceitos/gavetas.json alterado sem pertencer a nenhum entregável
- fora do plano: docs/MEMORIA_ESPACIAL.md alterado sem pertencer a nenhum entregável
- fora do plano: exemplos/foz/obra.json alterado sem pertencer a nenhum entregável
- fora do plano: pdca/agentes.jsonl alterado sem pertencer a nenhum entregável
- fora do plano: pdca/determinismo.json alterado sem pertencer a nenhum entregável
- fora do plano: pdca/licoes.jsonl alterado sem pertencer a nenhum entregável
- fora do plano: tests/test_evidencias.py alterado sem pertencer a nenhum entregável
- fora do plano: tests/test_extrair_gavetas.py alterado sem pertencer a nenhum entregável
- fora do plano: tests/test_geotecnia.py alterado sem pertencer a nenhum entregável
- fora do plano: tests/test_obra_eap_gavetas.py alterado sem pertencer a nenhum entregável
- fora do plano: tests/test_obras_lineares.py alterado sem pertencer a nenhum entregável
- fora do plano: tests/test_prancha.py alterado sem pertencer a nenhum entregável
- estouro: E1: tokens real é 3,1× o estimado
- estouro: E3: tokens real é 2,1× o estimado

**Próxima etapa:** nenhuma disponível

Mudanças de objetivo: 8
