# Rastreabilidade — o que foi pedido, o que foi entregue e de onde veio cada parte do HTML

Pedido do Caio (03–04/11/2026): "analisar o que foi pedido e o que foi entregue nesse HTML; o repositório foi sendo
adequado e não sei qual parte do desenvolvimento gerou o protótipo".

## 1. Como saber o que gerou um HTML

Uma linha só de montagem: `exemplos/<obra>/obra.json` → `camadas/obra.py` (build) → dados → `camadas/templates/
visualizador.html` → `saida/<obra>/<id>_camadas_v<versão>_<data>.html`.

- **Pelo nome do arquivo** (desde a 0.14.0) ou pela linha **"Versão"** do painel Projeto: a versão do código.
- **A versão leva ao `CHANGELOG.md`** (o que mudou) e à tabela da seção 3 (PR, branch e data).
- **O plano da rodada** está em `docs/plano/` (pedido literal, itens com verificação e emendas).
- A tabela da seção 3 é regenerada do git: `python scripts/rastreabilidade.py --gravar docs/RASTREABILIDADE.md
  --ramos docs/rastreabilidade_ramos.json` (o JSON dá o branch dos PRs feitos em squash).

## 2. As sessões (branches) que escreveram o repositório

| Branch (sessão) | PRs | Versões | Frente |
|---|---|---|---|
| `claude/gracious-maxwell-6zyd9c` | #1 | (antes do CHANGELOG) | base: mosaico de drone, camadas de projeto e visualizador HTML (Irati) |
| `claude/intelligent-dijkstra-l3v3wh` | #2–16, #19, #21, #66 | 0.1–0.16, 0.18, 0.20, 0.58 | Foz inteira até a aba Obra: 3D e ortofoto, pranchas vetoriais por layer, georreferência, escopo sem preço, sondagens, inventário, escavação e valas, fichas de prancha, área da obra, pacote SIG, nome com versão, aba Obra, escopo por unidade, formas dos Actiflo, unidades da Relação de Desenhos; esta rastreabilidade e o build com o terreno da 0.56 |
| `claude/hopeful-archimedes-1kaoom` | #17 | 0.17 | obras lineares dentro da ETA (vala pelo MOS, sondagem, pavimento) |
| `claude/focused-dijkstra-m2k7pj` | #20, #22–24, #28, #30–31, #33, #48, #52–54, #58, #60–62, #64 | 0.19, 0.21–0.23, 0.27, 0.29, 0.31, 0.49–0.51 | arquitetura ("só escopo", sem cronograma/4D; ciclo de extração), geotecnia e obras lineares, decisões D4–D11, verificação noturna da arquitetura |
| `ccr-2f8fb1ac-7urfse` | #26–27, #29, #32, #35, #39, #46, #56, #63 | 0.24–0.26, 0.28, 0.30, 0.34, 0.36, 0.45, 0.53, 0.56 | memória espacial (gavetas, de-para), build real de Foz, conferência das cavas, terreno das cavas pela topografia do projeto |
| `claude/nifty-meitner-uqs554` | #18, #34, #36, #38, #40–45, #47, #49–51, #55, #57, #59, #65 | 0.32–0.33, 0.35, 0.37–0.44, 0.46–0.48, 0.52, 0.54–0.55, 0.57 | EAP codificada (aba EAP), leitura por IA com citação conferida, EAP padrão alinhada à planilha Sanepar |
| `ccr-a74a1d05-p8rjle` | #25, #37 | — | Vibe Code Metrics (higiene, `uv`, conjunto de referência) e testes de caracterização de `obra.py` |

## 3. Versão × PR × branch

<!-- versoes:inicio -->
| Versão | Data | PR | Branch (sessão) | Tema |
|---|---|---|---|---|
| 0.57.0 | 2026-11-04 | #65 | `claude/nifty-meitner-uqs554` | D10, D11, D12 e D13 na EAP padrão (frente WBS) |
| 0.56.0 | 2026-11-04 | #63 | `ccr-2f8fb1ac-7urfse` | Terreno das cavas: topografia do projeto no casco das curvas, MDS corrigido fora |
| 0.55.0 | 2026-11-03 | #59 | `claude/nifty-meitner-uqs554` | A etapa pelo título da planilha Sanepar |
| 0.54.0 | 2026-11-03 | #57 | `claude/nifty-meitner-uqs554` | EAP padrão alinhada à planilha real da Sanepar (Foz) |
| 0.53.0 | 2026-11-03 | #56 | `ccr-2f8fb1ac-7urfse` | Conferência das cavas por seções de corte e cotas da sequência executiva |
| 0.52.0 | 2026-11-03 | #55 | `claude/nifty-meitner-uqs554` | Itens codificados para as folhas vazias da EAP padrão |
| 0.51.0 | 2026-11-03 | #54 | `claude/focused-dijkstra-m2k7pj` | Decisão D9: DE no fallback, MND sem vala e bota-fora com berço e envoltória |
| 0.50.0 | 2026-11-03 | #53 | `claude/focused-dijkstra-m2k7pj` | Decisões D5 a D8: solo pelo substantivo, impenetrável como rocha, fallback e reaterro da vala |
| 0.49.0 | 2026-11-03 | #52 | `claude/focused-dijkstra-m2k7pj` | Um dimensionador de vala só: `dimensoes.dimensionar_vala` virou adaptador do `lineares` |
| 0.48.0 | 2026-11-03 | #51 | `claude/nifty-meitner-uqs554` | EAP padrão por tipo de obra (esqueleto a preencher) |
| 0.47.0 | 2026-11-03 | #50 | `claude/nifty-meitner-uqs554` | "Sem preço" também no texto da planilha lida pela IA |
| 0.46.0 | 2026-11-03 | #49 | `claude/nifty-meitner-uqs554` | Conciliação das duas EAP sem "confere" circular, com o documento independente |
| 0.45.0 | 2026-11-02 | #46 | `ccr-2f8fb1ac-7urfse` | Build real de Foz: a memória espacial com dados verdadeiros |
| 0.44.0 | 2026-11-02 | #47 | `claude/nifty-meitner-uqs554` | Número colado a letra não é quantidade (regex e IA, uma regra só) |
| 0.43.0 | 2026-11-02 | #45 | `claude/nifty-meitner-uqs554` | Leitura por IA: planilha como documento de leitura |
| 0.42.0 | 2026-11-02 | #44 | `claude/nifty-meitner-uqs554` | Calibração de premissas pela evidência (premissa × observado) |
| 0.41.0 | 2026-11-02 | #43 | `claude/nifty-meitner-uqs554` | Conferência de citação simplificada (sem mudança de comportamento) |
| 0.40.0 | 2026-11-02 | #42 | `claude/nifty-meitner-uqs554` | Leitura por IA: conferência por bloco de linha de tabela |
| 0.39.0 | 2026-11-02 | #41 | `claude/nifty-meitner-uqs554` | Leitura por IA com citação conferida |
| 0.38.0 | 2026-11-02 | #40 | `claude/nifty-meitner-uqs554` | Aba EAP: só pranchas desta disciplina |
| 0.37.0 | 2026-11-02 | #38 | `claude/nifty-meitner-uqs554` | Aba EAP: selo por nó, filtro por prefixo e vista particular |
| 0.36.0 | 2026-11-02 | #39 | `ccr-2f8fb1ac-7urfse` | Memória espacial, rodada 6: as gavetas falam a EAP codificada |
| 0.35.0 | 2026-11-02 | #36 | `claude/nifty-meitner-uqs554` | Aba EAP: árvore codificada, fatos e evidências |
| 0.34.0 | 2026-11-02 | #35 | `ccr-2f8fb1ac-7urfse` | Memória espacial, rodada 5: cavas e setores da ETA |
| 0.33.0 | 2026-11-02 | #34 | `claude/nifty-meitner-uqs554` | Escoramento total e planilha Obras Lineares como evidência |
| 0.32.0 | 2026-11-02 | #18 | `claude/nifty-meitner-uqs554` | EAP codificada como linha mestra |
| 0.31.0 | 2026-11-01 | #33 | `claude/focused-dijkstra-m2k7pj` | Rodada 25, PR 4: dimensionador único de vala, trechos e conferências no build |
| 0.30.0 | 2026-11-01 | #32 | `ccr-2f8fb1ac-7urfse` | Rodada 24 da memória espacial: valas, fatos da IA e escala de 100 km |
| 0.29.0 | 2026-11-01 | #31 | `claude/focused-dijkstra-m2k7pj` | Rodada 25, PR 3: modelo geotécnico único, conferências e leitor de perfil |
| 0.28.0 | 2026-11-01 | #29 | `ccr-2f8fb1ac-7urfse` | Rodada 23 da memória espacial: EAP lastreada no HTML e recálculo incremental |
| 0.27.0 | 2026-11-01 | #30 | `claude/focused-dijkstra-m2k7pj` | Rodada 25, PR 2: leitor de laudo de sondagem e estaqueamento da obra linear |
| 0.26.0 | 2026-11-01 | #27 | `ccr-2f8fb1ac-7urfse` | Rodada 22: extração para as gavetas |
| 0.25.0 | 2026-11-01 | #26 | `ccr-2f8fb1ac-7urfse` | Rodada 21: as caixas — formato das gavetas medido e escolhido |
| 0.24.0 | 2026-11-01 | #26 | `ccr-2f8fb1ac-7urfse` | Memória espacial: gavetas e os três de-para |
| 0.23.0 | 2026-10-31 | #24 | `claude/focused-dijkstra-m2k7pj` | Rodada 20, PR 3: o loop de extração fecha sozinho |
| 0.22.0 | 2026-10-31 | #23 | `claude/focused-dijkstra-m2k7pj` | Rodada 20, PR 2: releitura, PDF inteiro, papel por pasta e esperado × encontrado |
| 0.21.0 | 2026-10-30 | #22 | `claude/focused-dijkstra-m2k7pj` | Arquitetura R7: ciclo de extração, fontes de evidência e geotecnia separada |
| 0.20.0 | 2026-10-30 | #21 | `claude/intelligent-dijkstra-l3v3wh` | Foz, rodada 19: todas as unidades da Relação de Desenhos e os desenhos não entregues |
| 0.19.0 | 2026-10-30 | #20 | `claude/focused-dijkstra-m2k7pj` | Arquitetura: só escopo, inventário primeiro e índice de determinismo |
| 0.18.0 | 2026-10-30 | #19 | `claude/intelligent-dijkstra-l3v3wh` | Foz, rodada 18: a estrutura dos Actiflo a partir das formas do Drive |
| 0.17.0 | 2026-10-30 | #17 | `claude/hopeful-archimedes-1kaoom` | Foz, rodada 17: obras lineares dentro da ETA (demandas da Giselle) |
| 0.16.0 | 2026-10-30 | #16 | `claude/intelligent-dijkstra-l3v3wh` | Foz, rodada 16: aba Obra como determinação de escopo |
| 0.15.0 | 2026-10-29 | #15 | `claude/intelligent-dijkstra-l3v3wh` | Foz, rodada 15: o HTML navegável por elementos construtivos |
| 0.14.0 | 2026-10-29 | #14 | `claude/intelligent-dijkstra-l3v3wh` | Foz, rodada 14: HTML com nome e versão, nuvem e vetores mais leves |
| 0.13.0 | 2026-10-29 | #13 | `claude/intelligent-dijkstra-l3v3wh` | Foz, rodada 13: pranchas mais leves e medição exata |
| 0.12.0 | 2026-10-29 | #12 | `claude/intelligent-dijkstra-l3v3wh` | Foz, rodada 12: pacote SIG na área da obra e dependências completas |
| 0.11.0 | 2026-10-29 | #11 | `claude/intelligent-dijkstra-l3v3wh` | Foz, rodada 11: só a área da obra no HTML |
| 0.10.0 | 2026-10-29 | #10 | `claude/intelligent-dijkstra-l3v3wh` | Foz, rodada 10: saúde do código e as relações de materiais que faltavam |
| 0.9.0 | 2026-10-28 | #9 | `claude/intelligent-dijkstra-l3v3wh` | Foz, rodada 9: forma completa, fichas em lote e diagnóstico em código |
| 0.8.0 | 2026-10-28 | #8 | `claude/intelligent-dijkstra-l3v3wh` | Foz, rodada 8: a prancha lida em camadas de entendimento (pilotos) |
| 0.7.0 | 2026-10-28 | #7 | `claude/intelligent-dijkstra-l3v3wh` | Foz, rodada 7: inventário de projetos, movimento de terra e valas |
| 0.6.0 | 2026-10-28 | #6 | `claude/intelligent-dijkstra-l3v3wh` | Foz, rodada 6: adutoras completas, escopo × desenho e sondagens no 3D |
| 0.5.0 | 2026-10-27 | #5 | `claude/intelligent-dijkstra-l3v3wh` | Foz, rodada 5: malha de coordenadas, adutoras e escopo sem preço |
| 0.4.0 | 2026-10-27 | #4 | `claude/intelligent-dijkstra-l3v3wh` | Foz, rodada 4 |
| 0.3.0 | 2026-10-27 | #3 | `claude/intelligent-dijkstra-l3v3wh` | Foz, rodada de qualidade |
| 0.2.0 | 2026-10-27 | #3 | `claude/intelligent-dijkstra-l3v3wh` | Foz, primeira entrega |
| 0.1.0 | 2026-10-27 | #3 | `claude/intelligent-dijkstra-l3v3wh` | Irati |
<!-- versoes:fim -->

## 4. O que o Caio pediu na sessão `intelligent-dijkstra` e onde está no HTML

Situação conferida na `main` 0.58.0 (template e build), 04/11/2026.

| Pedido (data) | Entregue em | Onde aparece | Na 0.58.0 |
|---|---|---|---|
| Obra de Foz em camadas: 3D, ortofoto, pranchas por layer, etapas, escopo, sondagens (27/10) | 0.2–0.3 | abas Camadas, Pranchas, Etapas & escopo; 3D | mantido |
| "Só o escopo, sem preço" (28/10) | 0.5–0.6 | Etapas & escopo; escopo × desenho das adutoras | mantido (e reforçado: sem prazo, 0.19) |
| Inventário de projetos, escavação/reaterro, pavimento × calçada (28/10) | 0.7 | aba Projeto; camadas de cavas e valas | mantido; inventário de todos os arquivos desde a 0.19 |
| A prancha lida em camadas de entendimento: tipo de obra → vistas → tabelas → layers → vínculos → serviços (28/10) | 0.8–0.9 | aba Projeto, fichas das pranchas; inventário com ficha por desenho | mantido |
| "Tudo o que executa com IA, fazer código e pôr no repositório" (28/10) | 0.9 | `camadas/diagnostico.py` (fora do HTML) | mantido |
| Saúde do código e complementar o repositório (29/10) | 0.10 | — | mantido |
| Só a área da obra (satélite dá o entorno), arquivo mais leve (29/10) | 0.11, 0.13–0.14 | ortofoto recortada; satélite limitado à obra; pranchas e nuvem comprimidas | mantido |
| GDAL para o recorte (29/10) | 0.12 | pacote SIG (`saida/<obra>/sig/`, fora do HTML) | mantido |
| Nome do arquivo específico e com versão (29/10) | 0.14 | nome do arquivo e linha "Versão" | mantido |
| Camadas virando elementos construtivos: achar um pilar; unidade 1 localizada × unidade 2 linear; rede como linha vetorial (29/10) | 0.15 | aba Obra: busca, árvore, ficha; trechos de rede clicáveis | mantido |
| Aba Obra como a principal: escopo por unidade com checagem, decomposição construtiva com evidências, fonte com link, módulo de filtros fora (30/10) | 0.16 | aba Obra (abre primeiro) | mantido; a aba EAP passou a ser a linha mestra (0.32+) |
| Estrutura dos Actiflo que estava no Drive (30/10) | 0.18 | blocos dos Actiflo no mapa, no 3D e na decomposição; `camadas/drive.py` | mantido |
| Unidades da Relação de Desenhos e desenhos não entregues (30/10) | 0.20 | aba Obra: desenhos citados × entregues, filtro de pendência | mantido |
| Rastreabilidade do HTML e o HTML da main atual (04/11) | 0.58 | `docs/RASTREABILIDADE.md`; build com o terreno da 0.56 | novo |
| Orçamento de Foz 211, sem preço: as quantidades do CUSTO CIVIL calculadas em código, mostradas na aba EAP (04/11) | 0.64 | aba EAP, bloco "Contrato 211"; `camadas/contrato_211.py`; trechos internos da f004 em `valas` | 29 de 58 linhas vazias calculadas e 7 parciais na 0.64; **51 de 58 na 0.66** |
| Georreferenciar as folhas 009 e 010 (04/11) | 0.66 | pranchas f009, f009_600 e f010 no mapa; trechos de interligação nas valas e no Contrato 211 | novo; planta 600 da f010 pendente |

## 5. Decisões que mudaram o que tinha sido entregue

- **0.19 (`focused-dijkstra`)**: "só escopo, sem prazo" — saíram o cronograma, o 4D e a curva S, que tinham entrado na
  0.3. A arquitetura cita decisão do Caio de 28/10 e 30/10 (`docs/ARQUITETURA.md`, princípio 1).
- **0.32 em diante (`nifty-meitner`, `ccr-2f8fb1ac`)**: a **EAP codificada** virou a linha mestra (aba EAP); os
  documentos são evidências e o mapa é o jeito de ver no local. A aba Obra continua, ao lado.
- **0.39 em diante**: leitura de documentos por IA com citação conferida pelo código ("a IA propõe, o código
  confere"); o cálculo de engenharia continua sem IA (`CLAUDE.md`, regras de processo).

## 6. Pedido e ainda não entregue (ou parcial), sessão `intelligent-dijkstra`

1. **Pilar, viga, laje e parede dos Actiflo como geometria**: só estacas e blocos viram elemento; o resto é evidência
   de documento (Relação de Desenhos). Texto das armaduras é traço (SHX) e o OCR sai ruidoso.
2. **"Funções que determinam a construção civil"**: decomposição por tipologia com evidências, sem quantidades de
   concreto, forma e aço.
3. **Folha 10 (interligações) no mapa**: nenhuma referência tem o mesmo desenho.
4. **Escopo "a definir"**: câmara de contato, canal de água tratada, EEE lodo, recalques, caixas de chegada, torre,
   guarita, depósito — falta a decisão do Caio (controle "No escopo" → exportar para o obra.json).
5. **58 desenhos citados na Relação não estão no Drive**.
6. **8 estacas** do `estacas.csv` com a unidade trocada (marcadas "Conferir").

## 7. O HTML da main de 04/11/2026 (0.58.0), parte por parte

`saida/foz/foz-vilac_camadas_v0.58.0_2026-11-04.html` (24,2 MB), gerado com o código da 0.58.0 (a `main` 0.57.0 mais este PR), com o
extra `topografia` (scipy) e com a planilha do contrato (`211 - SAA Foz do Iguaçú.xlsx`, fora do git). Teste de
interface: 264 verificações, 0 falha.

O que o build precisa para sair igual: os extras `pdf`, `ocr`, `sig` e `topografia`. Sem o scipy, o build não quebra,
mas o terreno das cavas fica no MDS e o log avisa "topografia NÃO aplicada". Foi assim no primeiro build desta
rodada, com 8 cavas e 8 769 m³ de escavação. Com o scipy, a 0.56.0 quebrava nos furos com coordenada `null`; a
correção entrou na 0.58.0.

| Aba | Criada em (sessão) | Mexida depois em |
|---|---|---|
| Obra (abre primeiro) | 0.15–0.16 (`intelligent-dijkstra`) | 0.18, 0.20 (`intelligent-dijkstra`) |
| Camadas | 0.2 (`intelligent-dijkstra`) | 0.11, 0.13–0.14 (área da obra, peso) |
| Pranchas | 0.2 (`intelligent-dijkstra`) | 0.13 (simplificação e medição exata) |
| Etapas & escopo | 0.3–0.6 (`intelligent-dijkstra`) | 0.19 (`focused-dijkstra`: sem cronograma/4D) |
| EAP | 0.35 (`nifty-meitner`) | 0.37–0.38, 0.46–0.48, 0.52, 0.54–0.55, 0.57 (`nifty-meitner`); gavetas 0.36 (`ccr-2f8fb1ac`) |
| Anotações | 0.1 (`gracious-maxwell` / Irati) | — |
| Projeto | 0.7 (`intelligent-dijkstra`) | 0.8–0.10 (fichas), 0.19 (inventário de todos os arquivos) |

| Bloco de dados no HTML | Módulo | Versões (sessão) |
|---|---|---|
| `bases`, `area_obra`, `limites_obra` | `obra` | 0.2, 0.11 (`intelligent-dijkstra`) |
| `pranchas`, `folhas`, `elementos` | `pdf_cad`, `obra` | 0.2–0.8, 0.13 (`intelligent-dijkstra`) |
| `escopo` (sem preço) | `orcamento_sanepar`, `obra` | 0.5–0.6 (`intelligent-dijkstra`) |
| `sondagens`, `vertical`, `modelo3d` | `sfm`, `obra` | 0.2, 0.6, 0.14 (`intelligent-dijkstra`) |
| `inventario` | `inventario` | 0.7 (`intelligent-dijkstra`), 0.19, 0.21–0.23 (`focused-dijkstra`) |
| `fichas` | `prancha` | 0.8–0.10, 0.18 (`intelligent-dijkstra`) |
| `escavacao`, `valas` | `escavacao`, `valas` | 0.7, 0.15 (`intelligent-dijkstra`) |
| `construtivos` (+ `escopo`): 464 elementos, 104 desenhos citados / 46 entregues | `construtivos`, `escopo_obra` | 0.15–0.16, 0.18, 0.20 (`intelligent-dijkstra`) |
| `geotecnia` | `geotecnia`, `lineares` | 0.21, 0.27–0.31, 0.49–0.51 (`focused-dijkstra`) |
| `gavetas`, `eap_gavetas`: 73 objetos, 132 fatos, 77 serviços | `gavetas`, `extrair_gavetas` | 0.24–0.26, 0.28, 0.30, 0.34, 0.36 (`ccr-2f8fb1ac`) |
| `eap`, `eap_padrao`, `eap_painel` | `eap`, `eap_padrao`, `eap_painel`, `eap_html` | 0.32, 0.35–0.38, 0.46–0.48, 0.52, 0.54–0.55, 0.57 (`nifty-meitner`) |
| `evidencias`: 2 517 evidências, 167 fatos, 6 conflitos | `evidencias`, `vocabulario` | 0.39–0.44, 0.47 (`nifty-meitner`) |
| `conferencia_cavas` | `conferencia_cavas`, `secoes_corte` | 0.53 (`ccr-2f8fb1ac`) |
| `escavacao` com terreno composto. As cavas usam a topografia da GEOPLANTA dentro do casco das curvas e o MDS corrigido fora (15 265 m² de topografia, 6 192 m² de MDS corrigido, 1 387 m² de costura). Resultado: 7 cavas, 7 922 m³ de escavação e 4 951 m³ de reaterro. Dois alertas: o furo SP-16 (provável copa) e 4 288 m² extrapolados a mais de 30 m do casco | `topografia`, `escavacao` | 0.56 (`ccr-2f8fb1ac`), 0.58 (`intelligent-dijkstra`: furos `null` fora da validação) |

**Fica de fora neste build:** as obras lineares dentro da ETA (0.17, `hopeful-archimedes`) e os trechos das gavetas
que vêm delas. O código espera a aba "Obras Lineares" do protótipo da Giselle (30/10), que não está no Drive — a
planilha do contrato no Drive não tem essa aba (`docs/plano/2026-11-02_foz_build_real.md`, achado 3).

## 8. Como manter

A cada PR: a versão no `CHANGELOG.md` (o teste amarra `camadas.VERSAO` ao topo), o plano em `docs/plano/` e, ao
fechar, `python scripts/rastreabilidade.py --gravar docs/RASTREABILIDADE.md --ramos docs/rastreabilidade_ramos.json`
(PR novo em squash: acrescente o branch no JSON). Pedido novo do Caio entra na seção 4 com a versão que o entregou.
