# Arquitetura — projetos em camadas (R10, 03/11/2026; estado do código em 0.45.0)

Diagrama, cenário de mesa e índice: https://claude.ai/artifact/ESsAkB2JX7JZgBdRRxPzyg (privado; peça acesso ao Caio).

## 1. Princípios

1. **Só escopo.** Serviços e atividades numa EAP com quantidades. Sem preço e sem prazo: nada de valor unitário,
   fornecedor, cronograma, 4D, curva S ou produtividade (decisões do Caio, 28/10 e 30/10/2026).
2. **A EAP é a linha mestra; os documentos são evidências; o georreferenciamento é o jeito de ver no local**
   (`docs/EAP.md`).
3. **Inventário primeiro, e reavaliado.** Nada se lê antes do inventário de todos os arquivos. Depois de cada
   extração, o inventário é reavaliado: o que não saiu, ou saiu incompleto, volta para o loop (§2).
4. **Todo fato diz de onde veio**: a classe da fonte (projeto, memorial, laudo, folha de dados, ordem de serviço…),
   o documento, o local dentro dele, o método e o passe (§3).
5. **Código para a certeza, IA para a dúvida.** O trabalho braçal vai para os agentes menores e o julgamento para os
   maiores. Cada dúvida resolvida vira regra com teste (§9).
6. **A decisão do engenheiro prevalece sobre a evidência**, sem apagá-la (§6).
7. **Um arquivo HTML** é a entrega e a memória da obra: dados, fatos, pendências e decisões moram dentro dele.
8. **Cada informação tem uma gaveta.** A extração grava fatos georreferenciados, com evidência, numa base
   intermediária; os serviços são calculados dessa base e pendurados na EAP pelos três de-para
   (`docs/MEMORIA_ESPACIAL.md`).

## 2. O ciclo de extração: inventário → extração → reavaliação → loop

```
pastas da obra ─► P0 inventário ─► P1 código ─► reavaliação ─► completa? ─ sim ─► fatos
                       ▲                              │ não
                       │                              ▼
                       └──── próximo passe da escada (código alternativo → Haiku → Sonnet → Opus → você)
```

**P0 · Inventário por pasta.** Cada obra tem a própria árvore no Drive, e cada pasta raiz tem um papel:
- orçamento/licitação: edital, projetos, planilha;
- obra/execução: ordens de serviço, folhas de dados, projeto executivo, atas;
- referências.

O papel da pasta vai para o `obra.json` (`inventario.pastas`, prefixo mais longo vence; feito na 0.22.0) e entra na avaliação de cada arquivo. A listagem
recursiva traz todo arquivo, de qualquer tipo (`camadas/inventario.py`). O download dos pendentes é feito por
`camadas/drive.py`, pelo link direto.

**P1 · Leitura por código.** Cada tipo de arquivo tem seu leitor:
- **PDF**: formato, layers, código Sanepar, carimbo;
- **planilha**: abas, inclusive as ocultas;
- **zip**: o conteúdo.

O que não tem leitor fica "sem leitor", à vista.

**Reavaliação** (`camadas/extracao.py`, regras em `conceitos/fontes.json`). Roda a cada build e grava
`saida/<obra>/pendencias.json`. Para cada arquivo, ela calcula:
- **classe da fonte**, em passadas: termos de cotação e de documento de obra, tipo do código Sanepar (DE, MD, RT,
  LM…), extensão e, por fim, termos no caminho, no nome e no carimbo;
- **estado**: completa · parcial · falhou · sem leitor · fora do disco. A classe exige campos para contar como
  completa: uma prancha precisa de título, folha e escala no carimbo; laudo, memorial e edital precisam ter texto;
- **próximo passe** da escada, para cada situação;
- **séries de folhas** pelo carimbo: "FOLHA 06/14" diz que a série tem 14 folhas, e as que não aparecem na listagem
  viram pendência;
- **registro** `saida/<obra>/extracao.jsonl`: uma linha por arquivo cada vez que o estado muda, com o passe e o
  executor. Mostra quantas voltas cada arquivo levou e quem resolveu.

**A escada** (`conceitos/fontes.json`, `escada`). A IA só entra depois que o código tentou:

| Situação | Próximo passe | Ação |
|---|---|---|
| fora do disco | código | `camadas/drive.py`; arquivo privado: você libera |
| falhou | código → Haiku | repetir a leitura; persistindo, o Haiku diz o que o arquivo é (protegido, corrompido, digitalizado) |
| carimbo incompleto | código → Haiku | OCR do carimbo em todas as páginas e em 300 dpi; persistindo, o Haiku lê o recorte do canto inferior direito |
| sem texto | código → Sonnet | OCR de página inteira; persistindo, o Sonnet lê a imagem com citação |
| sem leitor | Sonnet | lê e devolve no schema da classe, com citação; o leitor em código vira candidato a lição |
| classe desconhecida | Haiku | diz a classe pelo nome, pela pasta e pela 1ª página; a resposta vira termo novo em `fontes.json` |
| conteúdo não inventariado | código | extrair e inventariar o conteúdo do compactado |
| conflito ou julgamento | Opus | decide com as evidências; o que for regra vira `conceitos/` |
| fechamento | Fable | audita uma amostra e o relatório de pendências sem ver a conclusão de quem extraiu |

**Rodar mais de uma vez é desejado.** O inventário tem cache por arquivo, o registro só grava quando o estado muda
e a reavaliação é determinística. Cada volta fecha as pendências que o passe anterior abriu.

O loop para em dois casos:
- tudo completo;
- a escada esgotou: aí vira pendência sua, com o motivo.

A `fracao_completa` (arquivos completos ÷ arquivos no escopo; cotação fica fora e é listada à parte) mede o
progresso da obra.

**Ausência só por consulta.** `inventario.procurar(inv, padrão)` busca no nome, na pasta e no carimbo, em qualquer
situação, e separa "existe, não lido" de "não existe". A forma do Actiflo 360 foi dada como inexistente e existia
(lição L008).

**O loop fecha sozinho** (rodada 20, 0.22.0 e 0.23.0). Os cinco pontos da revisão independente foram resolvidos:

| Ponto | Como ficou |
|---|---|
| executor da escada | `camadas/escada.py`: `python -m camadas.escada <obra.json> [--voltas 3]` lê as pendências, executa os degraus de código (baixar, reler, carimbo em 300 dpi, extrair o zip), reavalia e repete até não haver degrau de código; o que sobra vai para `saida/<obra>/lotes/<executor>.jsonl` |
| cache × repetição | `LEITURA_VERSAO` na assinatura, `reler`, erro relido; o resultado de degrau e de IA mora em `complementos.json`, fora do cache |
| degraus de código e tentativas | `degraus` por situação em `conceitos/fontes.json`, com `max_tentativas` em todo degrau; esgotou o código, sobe para Haiku, depois Sonnet, depois você |
| retorno da IA | o agente grava em `saida/<obra>/retornos/*.jsonl`; `extracao.aplicar_retornos` só aceita os campos de `retorno` da classe e confere o trecho citado na página; o registro grava o executor que completou |
| papel, esperado × encontrado, páginas | `inventario.pastas`, `conceitos/documentos_esperados.json`, carimbo e texto de todas as páginas (até 20) |

O ciclo de uma rodada fica assim:
1. Rodar `python -m camadas.escada <obra.json>`.
2. Os agentes leem os lotes e gravam os retornos.
3. Rodar a escada de novo: os retornos entram e o que fechou sai dos lotes.
4. Rodar o build.

O build não chama a escada: o build é reprodutível offline e não baixa nada da rede por conta própria.

Já corrigido a partir da mesma revisão (lição L012):
- o nome do arquivo vale mais que a pasta;
- os termos têm fronteira de palavra (FORMA não casa INFORMAÇÕES);
- laudo vem antes de projeto (perfil de sondagem é laudo);
- toda classe que lê PDF exige texto, então a OS escaneada não sai completa;
- foto dispensa leitura e não vai para a IA;
- as séries de folhas separam por unidade e avisam quando há arquivos fora do disco na pasta;
- o registro grava qualquer mudança de classe, estado ou do que falta;
- a cotação é listada à parte.

## 3. Fontes de evidência: o que cada documento entrega

| Classe | Exemplos | Entrega |
|---|---|---|
| projeto | pranchas DE (planta, perfil, detalhe), DWG | geometria, layers, tabelas de material, carimbo |
| memorial | MD, MC, ES, caderno | o que se constrói, materiais, critérios de medição |
| laudo | RT: sondagem, topografia, ensaio | furos, camadas, NSPT, NA, coordenadas |
| lista | LM, LC, QC | itens e quantidades de material, cabos, cargas |
| edital | edital, TR, anexos, minuta | escopo oficial, etapas, decisões do cliente |
| planilha | contrato, quantitativos (sem preço) | itens e quantidades por etapa |
| folha de dados | datasheet, catálogo, ficha técnica | equipamento, tag, vazão, potência, DN, PN |
| documento de obra | ordem de serviço, ata, notificação, ofício | o que será executado, liberado, por quem |
| cotação | proposta de fornecedor | **fora do escopo** (preço); fica no inventário |

**Todo fato carrega a fonte:**
- `classe`, `documento`, `id_drive`;
- localizador (página e linha, aba e célula, layer e ids dos elementos);
- trecho literal;
- `metodo` (texto, OCR, geometria, planilha, IA, decisão);
- `passe` e `executor`.

Esse formato já é o da evidência do ramo da EAP (`evidencia.schema.json`); ganha `classe` e `passe`. A força de um
fato é o número de **classes** que concordam, não de arquivos: projeto + memorial + planilha concordando vale mais
que três folhas do mesmo projeto. Hierarquia quando discordam:
1. decisão;
2. documento de obra;
3. edital;
4. planilha do contrato;
5. projeto;
6. memorial;
7. folha de dados.

## 4. Interpretação dos projetos pelo carimbo

O carimbo fica no canto inferior direito (ABNT NBR 10582; região de 200 × 115 mm em `inventario.CARIMBO_MM`). A
leitura tenta três fontes, nesta ordem:
1. texto do PDF;
2. fonte embaralhada reparada;
3. OCR, quando o texto vem em traço SHX.

Campos lidos: título, folha n/m, escala, data. A completar: unidade construtiva, revisão, projetista e responsável.
O carimbo serve para:
- **identidade**: título e unidade decidem o sistema da EAP; a escala confere a georreferência (vista em 1:100 não
  encaixa numa folha em 1:250);
- **completude**: a série n/m acusa folhas faltando (feito); a Relação de Desenhos acusa desenhos citados e não
  entregues (rodada 19: 104 citados, 58 não entregues);
- **coerência**: revisão e disciplina do carimbo × as do nome do arquivo. Divergência vira pendência (a fazer);
- **todas as páginas**: um PDF de várias folhas tem um carimbo por página (a fazer; hoje só a 1ª).

## 5. Disciplinas

**Geotecnia é separada da civil**, com análise própria, porque a interpretação da sondagem decide boa parte do
escopo de movimento de terra e de fundação.

Até a 0.26.0 havia dois interpretadores divergentes, `obras_lineares.py` e `dimensoes.dimensionar_vala`. A tabela
abaixo fica como registro do que motivou o modelo único:

| Ponto | `obras_lineares` | `dimensionar_vala` |
|---|---|---|
| raio de influência do furo | 60 m | 300 m |
| margem do NA | 0 | 0,5 m |
| impenetrável | só se a descrição diz | é topo de rocha |
| categoria de escavação 1ª/2ª/3ª | sim | não |
| empolamento | 1,30 | 1,25 (solo) / 1,50 (rocha) |
| cota do terreno × boca do furo | ignorada | considerada |

**Módulo `geotecnia`** (`camadas/geotecnia.py`, `conceitos/geotecnia.json`; itens 1, 2 e 4 feitos entre 0.27.0 e 0.31.0, o leitor de laudo aguarda a conferência do Caio em Foz):
1. **Leitor de laudo por código**: tabela de coordenadas (com EPSG e datum declarados) e perfil SPT por furo
   (camadas, NSPT, NA, impenetrável), lidos do texto do PDF, com schema validado. O que não sair fica "não lido" e
   entra na escada.
2. **Modelo geotécnico único** (`conceitos/geotecnia.json`): perfil por furo, interpolação entre furos com a
   distância reportada e as funções `perfil(E, N)`, `topo_rocha`, `na`, `categoria_em(h)`. Os dois interpretadores
   passam a chamá-lo.
3. **Serviços GEO na EAP**: escavação por categoria, esgotamento e rebaixamento, escoramento por tipo, comprimento de
   estaca até a camada resistente, bota-fora, empréstimo e contenção.
4. **Conferências projeto × sondagem**:
   - estaca projetada × topo do impenetrável;
   - fundo de cava × NA;
   - boca do furo × terreno do MDS (já existe);
   - trecho fora do raio de qualquer furo.
5. **Relatório geotécnico independente** na aba EAP: furos, modelo, serviços e conflitos, separado da civil.

**Civil**: estruturas de concreto, edificações e pavimentação. Elementos pela geometria → dimensões → serviços
associados (forma, concreto, armadura por taxa, lastro, escoramento de laje). As formas dos Actiflo já entram pelo
build (rodada 18).

**Hidráulica**: três fontes, todas ligadas ao cadastro Sanepar de 40 mil materiais:
- relação de materiais da prancha, lida por OCR (balão → item);
- memorial descritivo como especificação (material, DN, PN, norma);
- planilha do contrato.

**Elétrica**: pranchas PBEA com texto real, listas de materiais e de cabos, quadro de cargas. Hoje só termos; o
leitor de listas é lacuna.

### Tipo de obra: localizada × linear (proposta R9, 01/11/2026)

A obra linear fica separada como **tipo de obra**, não como quinta disciplina. A disciplina diz o que se constrói;
o tipo de obra diz como a obra se organiza no espaço. A adutora tem geotecnia, civil e hidráulica, mas tudo nela se
localiza por estaca ao longo de um eixo, se mede em metro de rede e gira em torno da vala.

| | Obra localizada (ETA, EEE, reservatório) | Obra linear (adutora, rede coletora, recalque) |
|---|---|---|
| espinha | unidade construtiva | eixo, com o estaqueamento como coordenada |
| unidade de trabalho | estrutura e seus elementos | trecho (entre PVs, por superfície, entre sondagens) |
| serviço dominante | concreto armado e fundação | vala: escavação, escoramento, pavimento, reaterro, esgotamento |
| documento-chave | forma, armadura, locação e cargas | planta e perfil juntos (o perfil dá a profundidade real) |
| só dela | — | interferências, travessias e MND, PVs, ligações prediais |

**Módulo de obras lineares** (`camadas/lineares.py`, `conceitos/lineares.json`; estado em 0.31.0):
1. eixo e estaqueamento como espinha (feito, 0.27.0);
2. leitor do perfil: estaca, cota do terreno, cota da geratriz ou do fundo da vala (piloto, 0.29.0);
3. segmentação em trechos por PV, superfície e sondagem (`lineares.trechos`, 0.31.0);
4. **um único dimensionador de vala** (MOS Sanepar), alimentado pelo modelo geotécnico (`lineares.dimensionar_vala`,
   0.31.0): `valas.py` e `obras_lineares.py` delegam a ele. O ramo `nifty-meitner` trouxe para a `main` um segundo,
   `dimensoes.dimensionar_vala` (raio 300 m, NA −0,5 m, empolamento 1,25); por decisão do Caio (03/11, D4) ele vira
   adaptador do `lineares`, sem regra própria. Falta unificar `gavetas.eixo` com `lineares.eixo`;
5. interferências e travessias (a fazer).

A EAP já separa as duas (U1 ETA × U2 adutoras).

## 6. Decisões: ida e volta

Schema único: `{id, alvo (prefixo da EAP), estado (executar | nao_executar | a_definir), motivo, autor, data,
supera[]}`.
- O build aplica as decisões **antes** dos cálculos.
- Elas descem para os filhos e para os serviços associados: sem drenagem urbana, também não há vala nem pavimento da
  drenagem.
- O HTML mostra a evidência superada e o nó riscado, fora da soma.
- Ao gravar, o navegador gera uma nova versão do arquivo com o bloco de decisões; o build seguinte lê esse bloco.
- Um teste de ida e volta garante que nada se perde.

### Registro das decisões de arquitetura

Decisão do Caio vale como regra até ser superada por outra, sempre registrada aqui e no plano da rodada.

| Id | Data | Decisão | Situação |
|---|---|---|---|
| D1 | 01/11 | premissas da geotecnia: raio de influência 60 m, margem do NA 0 m, empolamento 1,30 (solo) e 1,50 (rocha) | vigente |
| D2 | 01/11 | a vala das adutoras segue o MOS Sanepar, não a NBR 12266 (0,90 → 0,75 m no caso DE 0,30 m) | vigente |
| D3 | 01/11 | o ramo `nifty-meitner` não seria integrado; as faixas de escoramento dele entram como premissa | **revertida em 02–03/11**: o Caio fez o merge de 11 PRs do ramo (#18, #34, #36, #38, #40–#45, #47). A EAP codificada, a aba EAP, as evidências e a leitura por IA com citação conferida passam a fazer parte da arquitetura |
| D4 | 03/11 | fica um só dimensionador de vala, o `lineares.dimensionar_vala`, com as premissas da D1; o `dimensoes.dimensionar_vala` vira adaptador | vigente |

## 7. Quem faz o quê

| Executor | Papel no ciclo |
|---|---|
| Código | inventário, leitores, reavaliação, georreferência, dimensões, associados; valida tudo o que os agentes devolvem |
| Haiku | braçal: listar o Drive, dizer a classe de arquivo desconhecido, ler um recorte de carimbo, conferir contagens |
| Sonnet | leitura técnica em volume: arquivos sem leitor, laudos, memoriais, listas, perfil de planilha; módulo a partir de contrato fixo |
| Opus | sessão principal: contrato de saída, conflitos, georreferência difícil, revisão das dúvidas, integração e PR |
| Fable | revisor independente: auditoria do fechamento do ciclo, crítica de arquitetura, revisão de PR |
| Você | sistemas da obra nova, decisões de execução, arquivos privados, confirmação de regra nova |

Regras do paralelismo:
- o contrato de saída é fixado antes de abrir os lotes;
- lotes sem sobreposição (por pasta, por classe de fonte);
- a prancha não vai inteira para a IA, só o recorte em dúvida;
- cada agente devolve schema + dúvidas, nunca texto livre, e o passe dele entra no registro.

## 8. Processo (portões)

| Portão | O que fecha |
|---|---|
| G0 | inventário por pasta, reavaliado; nenhum arquivo sem estado; séries e índices cruzados conferidos |
| G1 | EAP da obra com os sistemas confirmados |
| G2 | extração em loop até a escada esgotar; pendências restantes com motivo |
| G3 | georreferência e âncoras (drone opcional) |
| G4 | fatos com a fonte de cada um |
| G5 | decisões aplicadas |
| G6 | geotecnia (modelo único) e serviços associados, um motor por assunto |
| G7 | caderno HTML dentro do orçamento de tamanho |

## 9. Regra da lição aprendida e índice de determinismo

**Regra.** Toda rodada com a IA deixa ao menos uma lição formalizada em código: uma regra em `conceitos/` ou uma
função, e um teste. As lições ficam em `pdca/licoes.jsonl`, com `versao`, `licao`, `antes`, `formalizada_em`, `teste`
e `estado`. Desde a 0.21.0, **cada versão do CHANGELOG a partir da 0.19.0 precisa de ao menos uma lição**, e um teste
reprova a falta (`tests/test_determinismo.py`). Assim a regra vale para qualquer sessão, não só para quem lembra
dela.

**Índice.** O índice mede a **IA na obra**: um agente leu, julgou, configurou ou operou para o dado existir. Não mede
a IA no desenvolvimento (escrever código e regras), que é o papel criativo dela e o caminho para virar código. A
decisão humana fica fora do índice.

```
python scripts/determinismo.py              # mede e confere as lições
python scripts/determinismo.py --registrar  # grava a rodada em pdca/determinismo.jsonl
```

| Medida (Foz) | Base | Rodada 18 | 0.21.0 |
|---|---:|---:|---:|
| Etapas do processo em código | 12 / 21 = 57,1 % | 13 / 21 = 61,9 % | **14 / 22 = 63,6 %** |

A reavaliação do inventário entrou como etapa de código. Antes, essa conferência era da IA na sessão.

**Meta:** 85 % das etapas em código. Próximas a converter:
1. 7 afins coladas;
2. afim da GEOPLANTA;
3. conferência visual;
4. configuração por prancha;
5. **leitor de laudo de sondagem** (geotecnia, §5).

Por arquivo, a `fracao_completa` (§2) mede quanto da obra já foi extraído. Quando o retorno da IA entrar no registro
(§2, item 4), dá para separar o que saiu só por código do que precisou de um passe de IA.

## 10. Como o trabalho anda: PDCA com gerente

Toda implementação segue um plano em `docs/plano/<data>_rodada<N>.md`. O plano tem uma tabela de entregas, cada uma
com a verificação que a aceita, e o estado de cada entrega anda `pendente` → `feito` → `verificado`.

| Fase | O que acontece | Quem |
|---|---|---|
| **P**lano | entregas, contrato de cada uma (arquivos, funções, schema), verificação e agente | Opus escreve; Fable aprova o plano |
| **D**o | implementação em Python no estilo do repositório; lotes em paralelo sem sobreposição de arquivos | Sonnet (código), Haiku (braçal) |
| **C**heck | `pytest`, `scripts/afericao.py`, `scripts/determinismo.py`; depois a revisão da entrega contra o plano: **aceita** ou **revisar**, com motivos | código, depois Fable |
| **A**ct | aceita: PR na `main` com merge automático, plano atualizado, lição em `pdca/licoes.jsonl`. Revisar: volta ao implementador com os motivos | Opus executa; Fable decide |

**Papéis.**
- **Fable é o gerente da rodada.** Aprova o plano, aceita ou devolve cada entrega e escreve a entrega final para o
  Caio: o prometido × o entregue, o que ficou de fora e por quê.
- **Opus é quem executa.** Abre os agentes, integra os ramos, roda os testes, abre o PR e faz o merge depois do aceite.
- **Sonnet e Haiku implementam** contra um contrato fixo: arquivos, funções, schema e testes esperados.
- **O Caio** recebe a entrega final e verifica.

**Regras.**
- Uma entrega só vai para a `main` com os três verdes (testes, aferição, determinismo) **e** o aceite do Fable.
- Cada PR sobe a versão, tem entrada no CHANGELOG e uma lição. O teste da lição reprova versão sem lição.
- Depois de cada entrega, o plano é revisitado: a entrega cumpriu a verificação prometida? O estado só vira
  `verificado` com a evidência escrita na linha do plano (números, testes, arquivos).
- Uma entrega devolvida duas vezes vira pendência explícita do plano, com o motivo, em vez de ser aceita pela metade.
- Sem os dados da obra (`dados/` fica fora do git), a verificação usa arquivos sintéticos nos testes. O build real de
  Foz fica como verificação do Caio, listada na entrega final.

**Estilo do código** (o mesmo dos módulos vizinhos):
- Python em português: nomes, docstrings e mensagens;
- dict puro e funções curtas (até 60 linhas, a aferição reprova a piora);
- regras e premissas em `conceitos/*.json`, com `fonte` e `estado`;
- `metadados()` em cada módulo;
- teste para cada regra;
- sem preço e sem prazo.

## 11. Observatório entre repositórios (proposta)

O Caio mantém vários repositórios de extração de dados (`ialocal.extrair.dados`, `ialocal.extrair.dossie-licitacao`,
`ialocal.orcamento`, `ialocal.gis.fontes`, `planejamento.obras`, `doc_to_dados`…). Este repositório passa a
acompanhá-los com análise crítica, para que todos evoluam no mesmo ritmo, com qualidade, determinismo e uso racional
de tokens.

**Contrato comum** (o mesmo `pdca/` deste repositório, copiado como kit, como a aferição já veio do `ialocal.gis.fontes`):

| Arquivo | O que mostra |
|---|---|
| `pdca/afericao.jsonl` | saúde do código: funções, órfãs, duplicatas, longas |
| `pdca/determinismo.json(l)` | etapas de código × IA e índice por rodada |
| `pdca/licoes.jsonl` | lições formalizadas em código, com teste |
| `pdca/agentes.jsonl` | custo por agente: modelo, tarefa, tokens, tempo, resultado (aceito ou revisar) |
| `docs/plano/*.md` | prometido × entregue por rodada |
| `CHANGELOG.md` | versão e o que entrou |

**Observatório** (a fazer): um script lê esse contrato de cada repositório da lista (`pdca/repositorios.json`) e monta
um relatório comparado:
- tendência do índice de determinismo;
- lições por versão;
- piora da aferição;
- tokens por entrega aceita e por modelo;
- taxa de devolução do gerente;
- planos com entregas paradas.

Repositório sem o contrato aparece como "sem PDCA", à vista. O Fable lê o relatório e escreve a análise crítica; uma
lição que vale para todos vira mudança no kit, propagada por PR em cada repositório.

**Uso racional de tokens:**
- o custo por entrega aceita é medido (`pdca/agentes.jsonl`);
- o modelo grande fica no julgamento (aceitar, devolver, decidir);
- o volume vai para os menores;
- uma devolução é custo dobrado, então o contrato de cada entrega precisa ser claro antes de abrir o agente. A
  devolução da E1 na rodada 20 veio de um prompt contraditório.

## 12. As telas: como o caderno funciona

Um único HTML, aberto no navegador sem servidor. O Python calcula tudo antes; a tela só apresenta, filtra e desenha
(exceção documentada: a medição interativa no mapa).

| Área | O que mostra | De onde vem |
|---|---|---|
| Mapa (centro) | ortofoto, satélite, pranchas por layer CAD, sondagens, valas, cavas; modo 3D com a nuvem de pontos | `dados.json` embutido: `bases`, `vetores`, `pranchas`, `modelo3d` |
| Aba **Obra** | identificação, área da obra, resumo | `obra.json` e `info` |
| Aba **Camadas** | liga e desliga cada camada, agrupada por disciplina | `grupos` de `pdf_cad.disciplinas()` |
| Aba **Pranchas** | cada prancha, a georreferência e a incerteza | `georef_prancha` |
| Aba **Etapas e escopo** | itens da planilha por etapa, o que está fora do escopo | `escopo_obra`, `orcamento_sanepar` |
| Aba **EAP** | árvore `U.SISTEMA.DISC.PACOTE.ITEM` com quantidade e selo por nó; ao abrir um nó: serviços → regra → fatos → evidência → recorte da prancha; "ver no mapa" filtra os elementos pelo prefixo | `eap_painel`, `eap_html`, gavetas |
| Aba **Anotações** | marcações do usuário no mapa | navegador |
| Aba **Projeto** | versão do código, das regras e do build | `VERSAO`, `info` |

**Selo por nó** (texto pronto do Python): convergente, fonte única, conflito, só menção, decidido, mesma origem. Um
nó com decisão "não executar" aparece riscado, fora da soma, com a evidência superada à vista (decisões com ida e
volta: a fazer, §6).

## 13. O banco de gavetas e os cálculos em etapas

A ideia do Caio, de dar à IA um lugar certo onde guardar o que lê e só depois calcular, é a **memória espacial**
(`docs/MEMORIA_ESPACIAL.md`, `camadas/gavetas.py`, `conceitos/gavetas.json`). Ela separa a obra em três etapas, cada
uma com um contrato escrito antes (os três de-para):

```
documentos ─► ETAPA 1: ler e guardar ─► GAVETAS ─► ETAPA 2: calcular serviços ─► ETAPA 3: EAP ─► HTML
              de-para 1                  (banco)    de-para 2                      de-para 3
              documento → gaveta                    gavetas → regra                serviço → nó
```

**As gavetas** (uma tabela cada; Parquet em `saida/<obra>/base/`, escolhido por bancada; DuckDB consulta):

| Gaveta | Um registro é | Liga com |
|---|---|---|
| `objetos` | uma coisa física: trecho de tubo, cava, estaca, furo | — |
| `geometria` | a forma do objeto, com CRS e datum | `objeto_id` |
| `fatos` | uma propriedade com valor, unidade e natureza (observado, projetado, inferido, decidido) | `objeto_id`, `evidencia_id` |
| `evidencias` | de onde o fato veio: classe, documento, local, trecho, método, executor | documento |
| `pendencias` | o que faltou ou conflitou, com o próximo passe da escada | `objeto_id` |
| `servicos` | uma quantidade calculada, com a regra, a versão e os `fato_id` usados | `objeto_id`, `fatos` |
| `superficies` | grade de terreno (MDS, ortofoto) com hash | `evidencia_id` |

**Como a IA interage com o banco.**
- A IA não escreve no banco direto: devolve um retorno no schema da gaveta, com o trecho citado; o código confere o
  trecho na página e só então grava o fato, com `executor` e `passe`.
- Fato que só a IA afirmou não alimenta regra de cálculo (0.30.0); ele aparece como evidência e pendência até outra
  fonte confirmar ou o Caio decidir.
- O que não tem gaveta vira pendência, não texto solto. Gaveta nova é decisão de arquitetura.

**Cálculo em mais de uma etapa e mais de uma volta.**
- Quem lê não calcula; quem calcula não lê: a Etapa 2 só lê das gavetas, nunca do documento.
- Cada serviço tem uma chave (`gavetas.chave_servico`): regra, versão, impressão do código e das premissas, dados,
  fatos e furos usados. Se nada mudou, o serviço é reaproveitado; mudou um fato ou uma premissa, só o que dependia
  dele é recalculado (`gavetas.calcular_incremental`).
- A paridade (`gavetas.paridade`) confere o cálculo das gavetas contra o cálculo direto; na 0.45.0, Foz deu 30
  objetos, 75 serviços, 0 erros de conferência e 0 diferenças de paridade.
- A Etapa 3 soma os serviços nos nós da EAP; cada número abre o caminho de volta até o recorte da prancha.

