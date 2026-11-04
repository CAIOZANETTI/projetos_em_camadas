## Rumo do desenvolvimento

**Objetivo:** Decidir com evidência qual terreno vale para as cavas de Foz (MDS do drone ou topografia do projeto) e aplicar a decisão

`▓▓▓▓▓▓▓▓▓▓ 100%`

**Tempo:** Início 03/11/2026 21:34 UTC · fim 04/11/2026 12:08 · 0,61 dias corridos (14,6 h de calendário) · IA trabalhando: 1,5 h de relógio · 1,7 h de agente · paralelismo 1,1×

| Etapa | Nome | Status | Agente | Est. min | Est. tokens | Real min | IA h | Real tokens | Razão |
|---|---|---|---|--:|--:|--:|--:|--:|--:|
| E1 | Superfície topográfica do projeto (curvas de nível) e comparação com sondagens, seções e MDS | ✅ feito | sonnet | 90 | 300.000 | 34 | 0,5 | 499.084 | 1,7× |
| E2 | Relatório da evidência e decisão do humano | ✅ feito | opus | 30 | 80.000 | 770 | 0,0 | 8.140 | 25,7× |
| E3 | Aplicar a decisão ao terreno das cavas e recalcular a conferência | ✅ feito | sonnet | 60 | 250.000 | 15 | 0,2 | 240.755 | 1,0× |
| E4 | Build real, balanço, aceite do Fable, PR e merge | ✅ feito | opus | 60 | 200.000 | 56 | 0,4 | 94.601 | 0,9× |

**Desvios (24)**
- fora do plano: CHANGELOG.md alterado sem pertencer a nenhum entregável
- fora do plano: camadas/__init__.py alterado sem pertencer a nenhum entregável
- fora do plano: camadas/eap_padrao.py alterado sem pertencer a nenhum entregável
- fora do plano: camadas/evidencias.py alterado sem pertencer a nenhum entregável
- fora do plano: camadas/extrair_gavetas.py alterado sem pertencer a nenhum entregável
- fora do plano: camadas/orcamento_sanepar.py alterado sem pertencer a nenhum entregável
- fora do plano: camadas/templates/visualizador.html alterado sem pertencer a nenhum entregável
- fora do plano: docs/ARQUITETURA.md alterado sem pertencer a nenhum entregável
- fora do plano: docs/EAP.md alterado sem pertencer a nenhum entregável
- fora do plano: docs/MEMORIA_ESPACIAL.md alterado sem pertencer a nenhum entregável
- fora do plano: docs/arquitetura.html alterado sem pertencer a nenhum entregável
- fora do plano: docs/plano/2026-11-03_foz_eap_padrao_real.md alterado sem pertencer a nenhum entregável
- fora do plano: docs/plano/2026-11-03_mapa_erro_mds.png alterado sem pertencer a nenhum entregável
- fora do plano: exemplos/foz/obra.json alterado sem pertencer a nenhum entregável
- fora do plano: pdca/afericao.jsonl alterado sem pertencer a nenhum entregável
- fora do plano: pdca/agentes.jsonl alterado sem pertencer a nenhum entregável
- fora do plano: pdca/licoes.jsonl alterado sem pertencer a nenhum entregável
- fora do plano: pyproject.toml alterado sem pertencer a nenhum entregável
- fora do plano: scripts/verificacao_noturna.py alterado sem pertencer a nenhum entregável
- fora do plano: tests/test_escavacao_terreno.py alterado sem pertencer a nenhum entregável
- fora do plano: tests/test_titulos_etapa.py alterado sem pertencer a nenhum entregável
- fora do plano: tests/test_visualizador_eap_padrao.py alterado sem pertencer a nenhum entregável
- estouro: E1: tokens real é 1,7× o estimado
- estouro: E2: tempo real é 25,7× o estimado

**Próxima etapa:** nenhuma disponível

Mudanças de objetivo: 19

### Correções sugeridas

| Prioridade | O quê | Por quê | Agente |
|---|---|---|---|
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: CHANGELOG.md alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: camadas/__init__.py alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: camadas/eap_padrao.py alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: camadas/evidencias.py alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: camadas/extrair_gavetas.py alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: camadas/orcamento_sanepar.py alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: camadas/templates/visualizador.html alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: docs/ARQUITETURA.md alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: docs/EAP.md alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: docs/MEMORIA_ESPACIAL.md alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: docs/arquitetura.html alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: docs/plano/2026-11-03_foz_eap_padrao_real.md alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: docs/plano/2026-11-03_mapa_erro_mds.png alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: exemplos/foz/obra.json alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: pdca/afericao.jsonl alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: pdca/agentes.jsonl alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: pdca/licoes.jsonl alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: pyproject.toml alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: scripts/verificacao_noturna.py alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: tests/test_escavacao_terreno.py alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: tests/test_titulos_etapa.py alterado sem pertencer a nenhum entregável | humano |
| média | registrar a mudança como etapa nova no rumo.yaml ou reverter o arquivo | fora do plano: tests/test_visualizador_eap_padrao.py alterado sem pertencer a nenhum entregável | humano |
| média | dividir a etapa em partes menores ou recalibrar a estimativa | estouro: tokens real é 1,7× o estimado | opus |
| média | dividir a etapa em partes menores ou recalibrar a estimativa | estouro: tempo real é 25,7× o estimado | opus |

_Sugestões geradas pelo vcm a partir das medições; nada foi alterado. Aplicar exige aprovação humana._
