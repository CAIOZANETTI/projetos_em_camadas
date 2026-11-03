## Rumo do desenvolvimento

**Objetivo:** Conferir as cavas da memória espacial de Foz por testemunhas independentes do cálculo pelo MDS: área e fundo de cada seção das pranchas de corte e cotas da sequência executiva

`▓▓▓▓▓▓▓▓▓▓ 100%`

**Tempo:** Início 03/11/2026 18:32 UTC · fim 03/11/2026 21:05 · 0,11 dias corridos (2,5 h de calendário) · IA trabalhando: 2,2 h de relógio · 2,9 h de agente · paralelismo 1,3×

| Etapa | Nome | Status | Agente | Est. min | Est. tokens | Real min | IA h | Real tokens | Razão |
|---|---|---|---|--:|--:|--:|--:|--:|--:|
| E1 | Reingestão do Drive de Foz (o contêiner novo não tem dados/) | ✅ feito | haiku | 30 | 500.000 | 9 | 0,1 | 272.591 | 0,5× |
| E2 | Leitor das seções de corte (área de corte e cota de fundo por seção) | ✅ feito | sonnet | 60 | 250.000 | 34 | 0,4 | 151.293 | 0,6× |
| E3 | Seções no modelo e conferência (área, fundo, cotas da sequência executiva, seções médias) | ✅ feito | sonnet | 60 | 250.000 | 113 | 0,3 | 215.546 | 1,9× |
| E4 | Build real, relatório, balanço, aceite do Fable e PR | ✅ feito | opus | 60 | 200.000 | -6 | 0,0 | 0 | 0,0× |
| E5 | Talude por cava a partir das seções do projeto (decisão do Caio, 03/11) | ✖ cancelado | sonnet | 60 | 250.000 | — | — | — | — |

**Desvios (36)**
- fora do plano: CHANGELOG.md alterado sem pertencer a nenhum entregável
- fora do plano: camadas/__init__.py alterado sem pertencer a nenhum entregável
- fora do plano: camadas/dimensoes.py alterado sem pertencer a nenhum entregável
- fora do plano: camadas/evidencias.py alterado sem pertencer a nenhum entregável
- fora do plano: camadas/geotecnia.py alterado sem pertencer a nenhum entregável
- fora do plano: camadas/inventario.py alterado sem pertencer a nenhum entregável
- fora do plano: camadas/lineares.py alterado sem pertencer a nenhum entregável
- fora do plano: camadas/obra.py alterado sem pertencer a nenhum entregável
- fora do plano: camadas/templates/visualizador.html alterado sem pertencer a nenhum entregável
- fora do plano: camadas/valas.py alterado sem pertencer a nenhum entregável
- fora do plano: camadas/vocabulario.py alterado sem pertencer a nenhum entregável
- fora do plano: conceitos/dimensoes.json alterado sem pertencer a nenhum entregável
- fora do plano: conceitos/eap.json alterado sem pertencer a nenhum entregável
- fora do plano: conceitos/eap_geral.jsonl alterado sem pertencer a nenhum entregável
- fora do plano: conceitos/eap_padrao.json alterado sem pertencer a nenhum entregável
- fora do plano: conceitos/geotecnia.json alterado sem pertencer a nenhum entregável
- fora do plano: conceitos/lineares.json alterado sem pertencer a nenhum entregável
- fora do plano: conceitos/servicos.jsonl alterado sem pertencer a nenhum entregável
- fora do plano: conceitos/sinonimos.json alterado sem pertencer a nenhum entregável
- fora do plano: conceitos/valas.json alterado sem pertencer a nenhum entregável
- fora do plano: docs/ARQUITETURA.md alterado sem pertencer a nenhum entregável
- fora do plano: docs/EAP.md alterado sem pertencer a nenhum entregável
- fora do plano: docs/MEMORIA_ESPACIAL.md alterado sem pertencer a nenhum entregável
- fora do plano: docs/arquitetura.html alterado sem pertencer a nenhum entregável
- fora do plano: exemplos/foz/obra.json alterado sem pertencer a nenhum entregável
- fora do plano: pdca/afericao.jsonl alterado sem pertencer a nenhum entregável
- fora do plano: pdca/agentes.jsonl alterado sem pertencer a nenhum entregável
- fora do plano: pdca/licoes.jsonl alterado sem pertencer a nenhum entregável
- fora do plano: tests/test_dimensoes.py alterado sem pertencer a nenhum entregável
- fora do plano: tests/test_eap_itens_gerais.py alterado sem pertencer a nenhum entregável
- fora do plano: tests/test_eap_padrao.py alterado sem pertencer a nenhum entregável
- fora do plano: tests/test_evidencias.py alterado sem pertencer a nenhum entregável
- fora do plano: tests/test_geotecnia.py alterado sem pertencer a nenhum entregável
- fora do plano: tests/test_obra_eap_gavetas.py alterado sem pertencer a nenhum entregável
- fora do plano: tests/test_visualizador_eap_padrao.py alterado sem pertencer a nenhum entregável
- estouro: E3: tempo real é 1,9× o estimado

**Próxima etapa:** nenhuma disponível

Mudanças de objetivo: 14

### Correções sugeridas

| Prioridade | O quê | Por quê | Agente |
|---|---|---|---|
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: CHANGELOG.md alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: camadas/__init__.py alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: camadas/dimensoes.py alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: camadas/evidencias.py alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: camadas/geotecnia.py alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: camadas/inventario.py alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: camadas/lineares.py alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: camadas/obra.py alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: camadas/templates/visualizador.html alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: camadas/valas.py alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: camadas/vocabulario.py alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: conceitos/dimensoes.json alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: conceitos/eap.json alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: conceitos/eap_geral.jsonl alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: conceitos/eap_padrao.json alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: conceitos/geotecnia.json alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: conceitos/lineares.json alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: conceitos/servicos.jsonl alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: conceitos/sinonimos.json alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: conceitos/valas.json alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: docs/ARQUITETURA.md alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: docs/EAP.md alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: docs/MEMORIA_ESPACIAL.md alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: docs/arquitetura.html alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: exemplos/foz/obra.json alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: pdca/afericao.jsonl alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: pdca/agentes.jsonl alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: pdca/licoes.jsonl alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: tests/test_dimensoes.py alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: tests/test_eap_itens_gerais.py alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: tests/test_eap_padrao.py alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: tests/test_evidencias.py alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: tests/test_geotecnia.py alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: tests/test_obra_eap_gavetas.py alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: tests/test_visualizador_eap_padrao.py alterado sem pertencer a nenhum entregável | humano |
| média | dividir a etapa em partes menores ou recalibrar a estimativa | estouro: tempo real é 1,9× o estimado | opus |

_Sugestões geradas pelo vcm a partir das medições; nada foi alterado. Aplicar exige aprovação humana._
