# Changelog

## 0.57.0 — 2026-11-04 · D10, D11, D12 e D13 na EAP padrão (frente WBS)
- **D10** (decisão do Caio, 04/11): blocos de ancoragem e de apoio são um item só, `HID.TUB.ANC`, em qualquer unidade.
  O item vale em obra localizada e linear e casa "bloco de apoio" de tubulação/curva/peça; folha nova `OP.07.04` (não
  obrigatória) e títulos "BLOCOS DE ANCORAGEM"/"BLOCOS DE APOIO" em OP.07.
- **D11** (decisão do Caio, 04/11): a água potável da U1 (622 m) conta uma vez só, como trecho de obra linear.
  Declaração na obra (`eap_padrao.trechos_lineares`), aplicada **antes do `consolidar`**: a linha declarada recebe o
  sistema `U1.AGUA_POTAVEL`, marcado em `unidades_construtivas.json` com `vista_eap_padrao: "linear"`; a vista da EAP
  padrão é decidida por (unidade, sistema) (`eap.vista_do_codigo`), e `_derivadas` não cruza vistas. Em Foz, os 622 m
  saem de OP.02.06 e entram em OL.03.01; as 7 linhas de vala FD da ETA ficam na localizada.
- **D12** (04/11): os conceitos ajustados com o dado real de Foz (poço de visita para água, ALO como etapa 00,
  hidrômetro DN 200 como macromedidor) ficam confirmados; nenhuma mudança de código.
- **D13** (04/11): "lavagem de rede" é desinfecção e limpeza da rede. `GER.CTL.DSF` passa a valer também em obra
  localizada e a EAP padrão localizada ganha `OP.12.04` (serviços finais, não obrigatória).
- Correção de leitura do relatório de 03/11: "preenchidas" era inflado por tratar o valor vazio de fato "só menção"
  como número; pelo caminho real (`evidencias._registros`), Foz fica com 9/44 (localizada) e 7/32 (linear).
- Processo (acordos de `docs/ARQUITETURA.md` §16): plano `docs/plano/2026-11-04_wbs_d10_d11.md` aprovado pelo Fable
  (2º parecer, com duas condições cumpridas), rumo em `results/rumo/wbs.yaml`, aceite do Fable sobre a entrega, versão
  só no merge. Pendência registrada: trecho declarado × futura aba Obras Lineares (`U1.LINEARES`).
- Lição L053.

## 0.56.0 — 2026-11-04 · Terreno das cavas: topografia do projeto no casco das curvas, MDS corrigido fora
- **`camadas/topografia.py`**: lê as curvas de nível da GEOPLANTA (`Curvas_Mestras` e `Curvas_Auxiliares`, equidistância
  de 0,5 m):
  - as cotas saem dos rótulos por OCR, com alfabeto aprendido dos próprios rótulos;
  - a curva partida no PDF herda a cota da continuação;
  - o TIN é montado na grade do MDS;
  - compara a topografia com as sondagens, as seções de corte e o MDS (mapa do erro, por cobertura e por distância).
- **Decisão do Caio (opção D)**: o terreno das cavas é composto (`escavacao.terreno` no obra.json; sem a chave, nada
  muda e o hash da referência fica igual):
  - topografia dentro do casco;
  - fora dele, MDS corrigido pelo plano medido contra a topografia, sem edificação e sem vegetação alta;
  - costura de 5 m para fora do casco;
  - além de 30 m do casco, a origem é `mds_corrigido_extrapolado`, com alerta;
  - `validacao_fora_do_casco` declara que, fora do casco, o erro é desconhecido.
- **Foz:**
  - escavação 8 612 → **7 905 m³** (−8,2 %); reaterro 5 467 → **4 952 m³** (−9,4 %);
  - a C07, de 0,2 m de profundidade, some, porque a topografia fica abaixo do fundo projetado;
  - topografia × sondagens: rms 0,17 m (14 furos); topografia × seções: rms 0,16 m;
  - o MDS fica em média +0,54 m acima da topografia: copa e telhado (21 % da área com erro maior que 1 m) e um anel de
    +0,6 a +1 m na borda do casco.

  Relatório em `docs/plano/2026-11-03_decisao_terreno.md`.
- O cache das curvas leva `VERSAO_LEITURA_CURVAS`: o build reaproveitava em silêncio a leitura anterior. O extra
  `topografia` traz o scipy.
- Lição L052.

## 0.55.0 — 2026-11-03 · A etapa pelo título da planilha Sanepar
- **`orcamento_sanepar.extrair_custo_civil`**: colunas novas `titulo_etapa` e `titulo_trecho` no escopo (ao fim de
  `COLUNAS_ESCOPO`). Título de etapa é o que casa um `titulos_sanepar` de `conceitos/eap_padrao.json` (fonte única);
  linha sem composição e sem quantidade que não é etapa encerra a etapa anterior. A leitura passou a pular as
  colunas F e G (preço) em vez de lê-las e descartá-las. A função foi dividida (complexidade 25 → 15).
- **Evidência de planilha** guarda `titulo_etapa` no localizador; a classificação por item não muda.
- **EAP padrão**: cada etapa ganha `citada_no_contrato` (linhas do contrato sob o título da etapa, mesmo sem item
  codificado, com exemplos) e `avisos_titulo` (linha com item de outra etapa — candidato a erro de classificação).
  A situação das folhas não muda. A aba EAP mostra os dois por etapa.
- **Foz (dado real)**: 36 de 79 linhas da aba CUSTO CIVIL ganharam título de etapa; etapas OP.01, OP.07, OP.08,
  OP.10 e OP.12 citadas no contrato; **nenhum aviso** "item fora da etapa do título" — as 22 linhas com item caem
  todas na etapa do seu título, o que confirma a classificação. Candidatos para decisão: BLOCOS DE ANCORAGEM, BLOCOS
  DE APOIO e ÁGUA POTÁVEL aparecem dentro da ETA mas só estão em etapas da obra linear; "lavagem de rede" sem item.
- Lição L051.

## 0.54.0 — 2026-11-03 · EAP padrão alinhada à planilha real da Sanepar (Foz)
- **Primeira passada com dado real**: planilha do contrato Sanepar 211/26 (Foz do Iguaçu), baixada do Drive para
  `dados/` (fora do git), sem nenhuma coluna de preço → 1.002 linhas de escopo → 651 evidências → 35 fatos →
  EAP padrão. Relatório em `docs/plano/2026-11-03_foz_eap_padrao_real.md` (sem valores monetários).
- **Administração local da obra (ALO)**: etapa real da Sanepar que faltava. Item `GER.PRE.ALO` (mês/vb) e etapa
  00 obrigatória nos dois tipos; em Foz, 18 meses na ETA (U1) e 12 nas adutoras (U2).
- **`titulos_sanepar`** em cada etapa do padrão: os títulos reais da aba CUSTO CIVIL (serviços preliminares,
  recomposição de pavimento, blocos de ancoragem/apoio, materiais e equipamentos, urbanização, serviços finais…);
  a estrutura UNIDADE → frente → etapa da Sanepar casa com obra/unidade/sistema da EAP codificada.
- **Achados do dado real corrigidos**: poço de visita vale para água e esgoto (MOS módulo 09); hidrômetro
  ultrassônico DN 200 (macromedidor) não é ligação predial (vai para instrumentação, folha nova OL.07.04); grade de
  piso não é piso de concreto (29 linhas → acabamentos); composição de adutora não é cava (8 linhas → vala); talha
  não é viga; válvula "3 vias" não é recomposição de "via"; `MEDIDOR(ES)` e `MARCADOR(ES)` corrigidos no regex.
  Folhas preenchidas na localizada: 17 → 14 (as que saíram eram falsas). Roteiros de ataque da IA idênticos.
- Lição L050.

## 0.53.0 — 2026-11-03 · Conferência das cavas por seções de corte e cotas da sequência executiva
- **`camadas/secoes_corte.py`** lê as pranchas de corte (Civil 3D, vetoriais). Cada quadro é calibrado pelas marcas
  de 1 m e pelos rótulos de 5 m lidos por OCR (resíduo de 2 mm). Por seção saem a área de corte e a cota de fundo:
  terreno original × contorno da escavação, área por integral exata. Foz tem 18 seções.
- **`camadas/conferencia_cavas.py`** confere o modelo contra essas seções:
  - lê as linhas de seção da planta (tracejado do layer `CORTES` + letra por OCR);
  - mede o perfil do modelo na grade de corte de `escavacao.calcular`, que agora devolve `corte`, sem mudar volumes;
  - compara área, fundo e terreno por seção: confere / difere / não conferível, sempre com motivo;
  - faz seções médias onde há par paralelo na mesma cava;
  - liga as cotas da sequência executiva só quando a ligação é única.

  É uma etapa do build: grava `conferencia_cavas.json` e uma tabela na aba EAP.
- **Foz (depois do aceite do Fable):**
  - o fundo do modelo bate em 5 de 7 seções (0 a 0,06 m);
  - em HH e FF o fundo vem da marca de cota vizinha;
  - a área de corte difere principalmente pelo **terreno**: o MDS fica até 0,6 m abaixo da topografia do projeto no
    trecho do corte; corrigida por isso, a área vai de −14 % (OO) a +10 % (RR), com AA em +1 % e LL em +5 %;
  - placar final, depois de dois aceites do Fable: 1 confere (LL), 4 difere, 13 não conferível;
  - não dá para dizer se o volume está sub ou superestimado.

  O talude por seção foi cancelado pelo Caio, e nenhuma premissa mudou. Relatório em
  `docs/plano/2026-11-03_conferencia_cavas.md`.
- **Build no contêiner novo:** vira pendência visível, em vez de erro ou silêncio:
  - prancha com PDF ausente;
  - inventário sem listagem do Drive (ou com `_baixados.csv` de outro formato);
  - escavação sem controle vertical, que antes sumia **sem aviso**.
- Lição L049.

## 0.52.0 — 2026-11-03 · Itens codificados para as folhas vazias da EAP padrão
- **17 itens novos na EAP codificada** (`conceitos/eap_geral.jsonl`), disciplina nova `GER` "Serviços gerais"
  (`PRE` mobilização, topografia, sinalização; `CTL` ensaios, comissionamento, desinfecção, CFTV; `FIN` limpeza,
  faixa, cadastro/as built, desmobilização), `CIV.ACA.ACB` acabamentos, `CIV.PAV.URB` urbanização e
  `HID.TUB.ANC/TRV/MND/CAM` (ancoragens, travessias, MND/HDD, caixas e câmaras); 24 serviços e a unidade "mês".
  As 21 folhas da EAP padrão que só se preenchiam à mão agora apontam para esses itens e são preenchidas pelos
  documentos (edital, memorial, planilha, IA conferida).
- Termos regex no padrão das planilhas Sanepar, com prioridade entre itens e regra de inclusão: o termo depois de
  "inclusive/incluso/com/…" não vira item próprio ("estaca …, inclusive mobilização" continua estaca). 84 testes de
  frases que devem e que não devem casar. Roteiros de ataque da IA com saída idêntica; hash de referência igual.
- Revisão (650 frases comparadas antes × depois): a regra de inclusão saiu do regex e virou **regra da cabeça da
  descrição** em código (`evidencias._achados_da_cabeca`): item acessório (`"acessorio": true` — mobilização,
  topografia, desinfecção, travessia, MND, cadastro, ancoragem, caixa/câmara, acabamento…) só classifica a linha se
  nenhum item principal aparecer antes dele; vale em `classificar`, `buscar_texto` e na conferência da IA. Linha
  que continua a anterior herda a cabeça. Termos com objeto (desinfecção só de rede de água; CFTV só inspeção de
  rede; travessia só de rio/rodovia/ferrovia; MND só método/perfuração; faixa só recomposição final); "COM MND" na
  linha de assentamento vai para MND. "Mês" só vale como unidade em contexto de canteiro/manutenção/operação (não
  prazo, garantia ou cronograma). `HID.TUB.LIG` casa "ligação predial" no singular. As frases que mudaram de um
  item existente para outro são só as intencionais (cadastro, ancoragem, caixa/câmara, CFTV, travessia, pintura de
  parede, ensaio de compactação, teste de funcionamento de bomba, mobilização como cabeça).
- Limite: os itens novos ainda não vêm das pranchas (sem layer/construtivo); só dos documentos.
- Lição L048.

## 0.51.0 — 2026-11-03 · Decisão D9: DE no fallback, MND sem vala e bota-fora com berço e envoltória
- **DE no fallback** (`lineares._diametro_externo_m`, `conceitos/lineares.json › de_por_dn`): fora da Tabela I do MOS a
  largura usa o DE do tubo: o `de_mm` do trecho, ou DN → DE pela tabela do material (FD, FOFO e PVC DEFoFo pela
  ISO 2531 / NBR 7675; PEAD, PE e PP com DE = DN); fora da tabela, DE = DN com alerta. Saída ganha `de_m` e `fonte_de`.
- **MND**: trecho sem vala sai com `fonte_largura` "não se aplica (MND)", sem o alerta do fallback.
- **Bota-fora do adaptador** (`dimensoes`): soma (berço + envoltória) × empolamento ponderado solo/rocha quando são
  material importado (`berco_envoltoria_importado`). PEAD DN 630, pista 120 m: 48,6 → 173,5 m³. O bota-fora do
  `lineares` (gabarito da planilha) não muda.
- Antes × depois: `results/iteracoes/2026-11-03_D9_observacoes.md`. Gabaritos intocados; hash da referência igual.
  Lição L047.

## 0.50.0 — 2026-11-03 · Decisões D5 a D8: solo pelo substantivo, impenetrável como rocha, fallback e reaterro da vala
- **D5, classe do solo pelo substantivo** (`geotecnia.classe_solo`): vence a regex que casa mais cedo na designação
  (NBR 6484); "Areia fina argilosa" passa de argila a areia. `rocha_alterada` vence `rocha` em qualquer posição.
- **D6, impenetrável é rocha** (`geotecnia.solo_na_faixa`): a parte da faixa abaixo do `topo_rocha_m` de um furo
  impenetrável conta como rocha, não como indefinido (premissa `impenetravel_e_rocha`).
- **D7, fallback numa regra só** (`lineares.dimensionar_vala`): fora da Tabela I do MOS, largura DE + 0,60 m (NBR 12266)
  com alerta e `fonte_largura`; `valas.py` perdeu a regra própria e o adaptador `dimensoes` deixa de ficar em
  "faltando". FD DN 630: 1,23 m nos três caminhos.
- **D8, reaterro sem dupla contagem** (adaptador `dimensoes`): reaterro = reaterro do MOS − berço − envoltória, nunca
  negativo. Pista 100 m, FD DN 300: 97,93 → 90,43 m³. O reaterro do `lineares` (gabarito da planilha) não muda.
- Antes × depois: `results/iteracoes/2026-11-03_D5_D6_geotecnia.md` e `2026-11-03_D7_D8_vala.md`. Gabaritos
  intocados; hash da referência igual. Dois Sonnet em paralelo; aceite do Fable. Lição L046.

## 0.49.0 — 2026-11-03 · Um dimensionador de vala só: `dimensoes.dimensionar_vala` virou adaptador do `lineares`
- **Decisão do Caio (03/11/2026): dimensionador único (lineares)**, com o modelo geotécnico único (raio de influência de
  60 m, margem do NA 0 m, empolamento 1,30 solo / 1,50 rocha). `dimensoes.dimensionar_vala` mantém a interface
  (trecho, sondagens, métodos) e o formato de saída, mas largura, profundidade, escoramento (tipo e agravantes),
  esgotamento, escavação, reaterro, bota-fora, escoramento em m² e pavimento em m² saem de `lineares.dimensionar_vala`.
  Daqui sai só o que o lineares não calcula: berço e envoltória (regra genérica, com a largura do MOS), espessura e item
  EAP do pavimento, horas de esgotamento e a divisão da escavação em solo e rocha pela fração de rocha do lineares.
- **Métodos de largura**: o MOS Sanepar é o único; o NBR 12266 (regra própria) saiu. Pedir `nbr12266` não gera elemento
  e avisa. A vala deixa de ter dois elementos e a comparação NBR × MOS (conflito sintético) some da consolidação.
- **Tubo que o MOS não cobre** (ex.: FD DN 630 fora da Tabela I): o elemento sai com a largura em `faltando` e só o que não
  depende dela (assentamento); antes o NBR dava um número. Nada é suposto.
- `sondagem_proxima` e `classe_solo` delegam a `geotecnia.furo_mais_proximo` e `geotecnia.classe_solo`; `solo_na_vala`,
  `escoramento`, `_agua` e os métodos de largura foram removidos. A cota do trecho só muda a referência das profundidades
  do furo (profundidade + cota do trecho − cota da boca) antes de chamar o lineares.
- `conceitos/dimensoes.json`: removidas as premissas duplicadas (sondagem a 300 m, margem do NA 0,5 m, empolamento 1,25,
  faixas de escoramento e agravantes, largura NBR, classes de solo, método de esgotamento).
- Testes de `dimensoes`, `evidencias` e `eap_painel` que fixavam números do dimensionador antigo mudaram, cada um com o
  valor antigo e o novo; tabela em `results/iteracoes/2026-11-03_dimensionador_unico.md`.
- Lição L045. (0.47.0 já estava em uso na main; esta é a próxima versão livre.)
## 0.48.0 — 2026-11-03 · EAP padrão por tipo de obra (esqueleto a preencher)
- **`conceitos/eap_padrao.json`**: dois modelos nas etapas de execução — `obra_localizada` (OP: preliminares,
  movimento de terra, fundações, estrutura de concreto, impermeabilização, arquitetura, instalações hidráulicas,
  equipamentos, elétrica e automação, urbanização, ensaios e comissionamento, serviços finais) e `obra_linear` (OL:
  preliminares, remoção de pavimento, vala, assentamento, reaterro, travessias/MND, poços de visita e peças
  especiais, recomposição de pavimento, testes, ligações, cadastro e desmobilização). 72 folhas, 51 apontando para
  itens/serviços da EAP codificada; todos os 21 itens de `eap_geral` estão no padrão. Estado premissa: a prática de
  orçamento de saneamento e a organização do MOS Sanepar (o MOS não está no repositório; etapas a conferir).
- **`camadas/eap_padrao.py`**: `validar`, `tipo_da_obra` (do obra.json ou deduzido), `preencher` — preenchida, só
  menção, a preencher (obrigatória em destaque), não se aplica (declarada em `obra.json → eap_padrao.nao_se_aplica`
  com justificativa) e sem item codificado — e % preenchido por etapa. É uma vista da EAP codificada: não cria
  quantidade. Seção "EAP padrão (a preencher)" na aba EAP; `eap_padrao.json` no build.
- Revisão: cada vista só soma unidades do seu tipo (`unidades_construtivas.json` → `obra`); código com `*` na
  unidade fica "só menção" (unidade não atribuível). Nova situação **calculada** (só serviço associado, sem documento
  nem medição), com "% preenchido" e "% calculada" separados. Folha que aponta item sem serviço aceita fatos de
  qualquer serviço do item. "Não se aplica" sobre quantidade real vira conflito; declarações malformadas viram
  avisos sem derrubar a seção. Preenchimento manual com documento para folhas sem item codificado
  (`eap_padrao.preenchimento_manual`) e teto do % mostrado. Folha fora do escopo da obra (esgoto em obra de água)
  sai do denominador. `tipo_da_obra` pelas unidades e pranchas (tubos internos da ETA não fazem obra linear; Foz
  é mista pelas pranchas das adutoras). A linear ficou com 30 folhas.
- Lição L044.

## 0.47.0 — 2026-11-03 · "Sem preço" também no texto da planilha lida pela IA
- **`evidencias.paginas_planilha`**: colunas de preço (rótulo PREÇO*, VALOR*, CUSTO*, R$, TOTAL, SUBTOTAL, BDI, PU,
  P. UNIT) saem do texto da linha e do mapa de células, da linha de cabeçalho até o próximo cabeçalho; célula com
  "R$" sai em qualquer linha. As colunas Un e Qtd nunca contam como preço. A citação que inclui o preço é recusada
  ("trecho não encontrado no documento"); a SKILL orienta a não copiar o preço.
- Conferido (só leitura): `de_planilha` e `obras_lineares.ler_custo_civil` já ignoravam as colunas de preço (F e G
  da aba CUSTO CIVIL, que é só o nome da aba da planilha do contrato).
- Limite: número solto sem cabeçalho e sem "R$" continua no texto (a planilha não diz que é preço).
- Lição L043.

## 0.46.0 — 2026-11-03 · Conciliação das duas EAP sem "confere" circular, com o documento independente
- **Origem de cada trilha** (`gavetas.origem_do_servico`, `eap.origem_das_quantidades`): conjunto de insumos
  (`arquivo:`, `etapa:`) de onde veio o número. Insumo em comum → **"confere (mesma origem)"**, com o motivo de que
  não é conferência independente; "difere" com a mesma origem continua "difere" e é marcado como erro de cálculo;
  origem que não se determina fica "indeterminada", sem inventar. Hoje só a etapa de escavação está mapeada nos dois
  lados (as outras classes ficam "indeterminada" até serem mapeadas).
- **Terceira coluna** (`gavetas.documento_independente`): fato do mesmo código vindo de documento independente
  (planilha, edital, memorial, IA conferida, decisão; nunca geometria, associado ou projeto), com "confere com
  documento", "difere do documento" (Δ e Δ%), "documento em conflito" ou "sem documento"; t → kg.
- Aba EAP mostra as colunas e o selo "mesma origem" (textos prontos do Python). `_conciliar_eaps` roda depois de
  `evidencias.etapa`. Resolve o achado do aceite do build de Foz: escavação e reaterro das cavas davam "confere" com
  Δ = 0 vindo do mesmo levantamento; a conferência independente agora espera a planilha CUSTO CIVIL.
- Revisão: linha concreta só compara com fato do mesmo código; fato com `*` (a planilha grava `U1.*.ITEM`) é
  comparado com a soma das linhas que casa, num bloco de totais à parte (`gavetas.conciliar_totais`,
  `conciliacao_eap_totais.json`, tabela própria na aba); concreto × `*` nunca vira conflito. Documentos agrupados
  com a tolerância relativa do `evidencias.consolidar` (`TOLERANCIA_RELATIVA`, 0,005). Origem estruturada: a
  prancha vira o stem do PDF (mapa de `cfg["pranchas"]`) e a etapa vai em campo próprio (`origem_etapa` na cava,
  `etapa_origem` na evidência), com o texto da `fonte` só como reserva. Decisão do engenheiro não conta como
  documento independente (aparece à parte).
- Lição L042.

## 0.45.0 — 2026-11-03 · Build real de Foz: a memória espacial com dados verdadeiros
- **Build completo de Foz até o HTML** com os dados do Drive. Gavetas: 30 objetos, 75 serviços, 0 erros de conferência
  e 0 diferenças de paridade. Escavação e reaterro das cavas dão "confere" com a EAP codificada (8 585,6 e
  5 462,7 m³, diferença 0). Isso **não valida o volume**, porque as duas trilhas vêm do mesmo `escavacao`; a
  conferência independente contra o CUSTO CIVIL fica pendente. Relatório em `docs/plano/2026-11-02_foz_build_real.md`.
- **Revisão do Fable**:
  - a página inteira vai a um furo só na folha em bloco, e a continuação do perfil no layout de tabela fica com o seu
    furo;
  - as etapas puladas vão a `dados["pendentes"]` (HTML);
  - `unidade_sistema_padrao.classes` limita o padrão (Foz: só cavas);
  - uma profundidade sem descrição no meio do bloco não funde camadas.
- **`geotecnia.ler_laudo` lê o layout Geoazimute**:
  - coordenada rotulada ("Sonda SP01: N = …; E = …") e coordenada na folha do perfil;
  - furo complementar (SP 02A);
  - página de um furo só é toda dele, porque o NA vem antes do id;
  - camadas em bloco, de baixo para cima;
  - NA pela frase de conclusão;
  - NSPT exige espaço entre profundidade e golpes.

  São 23 furos, e a etapa sondagens passa de IA a código.
- **O build não cai mais por falta de insumo**: ficha de estrutura sem `estacas.csv`, planilha sem a aba "Obras
  Lineares" (`obras_lineares.tem_aba`, usado por obras lineares, gavetas e evidências) e serviço sem item (`PACOTE.*`),
  que não vira evidência. O schema da evidência continua o da `main`.
- **Rede de vala com `local`** (o seu nome): unidade e sistema pelas chaves de `unidades_construtivas.json`. Foz declara
  `gavetas.unidade_sistema_padrao` u1/ETA (o sistema geral, para a cava sem estacas).
- Lição L041.

## 0.44.0 — 2026-11-03 · Número colado a letra não é quantidade (regex e IA, uma regra só)
- **`camadas/vocabulario.py`** (`NAO_E_NUMERO`, `DIMENSAO`, `UNIDADE_ANTES`): número colado a letra ou letra+hífen
  (DN150, C30, CA-50) não é quantidade; dimensão com prefixo (DN 150, Ø 40 cm, diâmetro) é apagada antes da busca;
  o fallback "número + termo" recusa número logo depois de unidade ("m³ 45", "un 250") ou com unidade no meio.
  A conferência da IA passa a usar as mesmas expressões do vocabulário (saída dos roteiros de ataque inalterada).
- Corrige o método regex: "Tubo PVC DN150 m 320" deixava 150 m, "Concreto C30 m³ 45" deixava 30 m³ e "aço CA-50
  kg 1.200" deixava 50 kg; agora ficam sem quantidade (só menção), porque o formato "unidade antes do número" não é
  lido pelo regex. "Tubo DN 150 320 m" dá 320 m; "fck 30 MPa 45 m³" dá 45 m³.
- Hash de referência inalterado. Fecha a pendência "número colado a letra ou hífen" de `docs/EAP.md` §10.
- Lição L040.

## 0.43.0 — 2026-11-03 · Leitura por IA: planilha como documento de leitura
- **`evidencias.paginas_planilha`**: xlsx/xlsm/csv (xls com `xlrd`) viram documento de leitura da IA. Cada aba é uma
  página e cada linha não vazia é uma linha de texto, com as células unidas por " | " e os números em pt-BR sem
  arredondar (250.0 → "250", 1250.5 → "1.250,5"); csv sai como está no arquivo. Determinístico.
- **Localizador `{"aba", "linha"}`** conferido contra a linha real da planilha (linhas vazias contam, como no Excel):
  "aba citada não existe no documento" e "linha citada não contém o trecho"; "p. N" continua valendo como índice da
  aba. As regras da conferência valem iguais ("Estaca hélice | m | 12 | un | 250" proposto como 12 un é recusado).
- CLI `conferir … --planilha arquivo.xlsx`; `etapa` reconhece planilha em `evidencias.documentos` pela extensão.
  O método determinístico `planilha` (`de_planilha`) não muda.
- Revisão: na planilha a quantidade vem das **colunas** — cabeçalho com rótulo de unidade (UN, UND, UNID, UNIDADE) e
  de quantidade (QTD, QTDE, QUANT, QUANTIDADE); o valor tem de ser o da coluna Qtd e a unidade a da coluna Un da
  linha citada; preço e código do item nunca viram quantidade; sem cabeçalho só vale "250 un" numa mesma célula.
  Fórmula sem valor guardado e número fora de 1e-6–1e15 não conferem. Separador do csv pela consistência do número
  de campos (`;` no empate; ambíguo → documento recusado com aviso, sem derrubar o build); quebra de linha dentro de
  aspas vira espaço. Bloco só com linhas consecutivas da planilha; com localizador aba/linha, o par tem de estar na
  linha citada. `buscar_texto` em planilha usa aba/linha e as colunas. `.xls` sem `xlrd` é recusado com aviso.
  `evidencia.schema.json`: `localizador` aceita texto ou `{aba, linha}`.
- Fecha a pendência "aceitar planilha como documento de leitura" de `docs/EAP.md` §10.
- Lição L039.

## 0.42.0 — 2026-11-02 · Calibração de premissas pela evidência (premissa × observado)
- **`camadas/calibracao.py`**: para cada serviço associado com fato observado fora do próprio cálculo (edital,
  planilha, IA conferida ou decisão), calcula a **premissa implícita** `p × observado / calculado` quando a fórmula é
  linear numa única premissa (testado avaliando em 0, p/2, p e 2p, tolerância 1e-9): taxa de armadura, espessura de
  lastro e afins. Situação `confere` (até 5 %), `diverge` ou `não calibrável` com motivo (fórmula com patamar, `max`
  ou `if`; várias premissas proporcionais; fato em conflito; regra fora de `servicos_associados.jsonl`).
- **Nunca altera premissa**: só informa; trocar o valor é decisão humana. O observado exclui o próprio documento
  "associado" (senão o fato seria circular e tudo conferiria).
- `evidencias.etapa` grava `calibracao.csv` e `dados["evidencias"]["calibracao"]`; `docs/EAP.md` §7.4.
- Revisão: elementos casados por id e pela base do código (V1 em U1 e V1 em U2 não somam); o recálculo inclui os
  elementos vindos de fatos (`dimensoes.de_fatos`) e tem de bater com a soma das evidências do grupo, senão "não
  calibrável" com motivo; fato com `*` soma os associados de todos os códigos que cobre; t → kg antes de casar; a
  fórmula é reavaliada com a premissa implícita e tem de reproduzir o observado (pega `min`/limiar fora de
  [p/2, 2p]); condição que usa a premissa, divisão por zero e observado ≤ 0 → não calibrável; coluna
  `unidade_premissa` (`unidade` acrescentada às premissas de `servicos_associados.jsonl`, sem mudar valores); linhas
  não calibráveis mostram o calculado real.
- Sem dados reais no repositório (as planilhas estão no Drive), nenhum valor de premissa foi mudado.
- Lição L038.

## 0.41.0 — 2026-11-02 · Conferência de citação simplificada (sem mudança de comportamento)
- **`camadas/evidencias.py` refatorado** (apontado pelo `vcm balanco`): `_problemas_ia` 43 → 14, `conferir_citacao`
  37 → 7, `_situacao_do_item` 22 → 7, `_afirmacoes` 22 → 11, `consolidar` 21 → 12 (complexidade ciclomática, radon);
  nenhuma função do arquivo acima de 15. Funções novas por responsabilidade: validação de forma, de código/serviço e
  de valor/unidade; localização do trecho; conferência de linha × bloco; situação do item pelo número; consolidação
  por documento e por chave.
- **Comportamento idêntico, provado**: 10.532 casos gerados (trecho × valor × unidade × código × serviço ×
  localizador, mais linhas malformadas) e os 7 roteiros de ataque das revisões dão saída byte a byte igual antes e
  depois; nenhum teste alterado; hash de referência igual; desempenho igual (500 páginas × 200 evidências ≈ 0,5 s).
- Lição L037.

## 0.40.0 — 2026-11-02 · Leitura por IA: conferência por bloco de linha de tabela
- **Bloco de 2–3 linhas** (`evidencias.conferir_citacao`): descrição de planilha quebrada em várias linhas com a
  quantidade na última ("Estaca hélice contínua, diâmetro 40 cm, inclusive⏎mobilização e desmobilização un 250") e
  "Quantidade: 250 un" em linha própria passam a ser aceitas. O bloco é o trecho citado inteiro, na mesma página, sem
  linha em branco; o par (valor, unidade) começa na última linha; as anteriores não afirmam quantidade (dimensões com
  Ø, DN ou "diâmetro" são ignoradas); o termo do item pode estar em qualquer linha do bloco e valem item mais próximo,
  item/serviço/unidade da EAP geral, página e dedupe.
- Continuam recusados: duas linhas de tabela de itens diferentes, bloco de 4+ linhas, com linha em branco ou
  atravessando página, e "Bloco de coroamento⏎un 30" proposto como estaca.
- Revisão: o bloco é conferido sobre as linhas inteiras do documento (o recorte do trecho não esconde quantidade nem
  item rival); cada linha depois da primeira tem de continuar a anterior (só o par e rótulo de quantidade, ou a
  anterior sem "."/":" e esta em minúscula ou com conectivo), então título de seção e cabeçalho não viram item;
  "Total" não é rótulo; Ø/DN/diâmetro não engolem a unidade do par seguinte ("DN 150 m 350"); `\f` dentro de uma
  página vira linha em branco.
- Fecha a pendência "conferência por bloco de linha de tabela" de `docs/EAP.md` §10.
- Balanço vcm das iterações 0.38.0 e 0.39.0 em `results/iteracoes/8eb6034_a3dc7a8.*` (decisão humana: complexidade
  média +1,1%; RAM −8,6% e cobertura +0,9%).
- Lição L036.

## 0.39.0 — 2026-11-02 · Leitura por IA com citação conferida
- **Roteiro de leitura** (`evidencias.roteiro`, `roteiro_md`): por item da EAP geral (filtrado por escopo e tipo de obra),
  código, nome, termos de busca legíveis (termos do item e sinônimos de `sinonimos.json`), serviços admitidos com
  unidades e unidades aceitas.
- **CLI** `python -m camadas.evidencias`: `roteiro [--escopo] [--obra] [--saida]` e `conferir IA.jsonl --pdf … --texto …
  [--saida]`. `conferir_arquivo` valida o schema, localiza o documento por `documento.id`, aplica `conferir_citacao` e
  recusa com motivo (JSON ou schema inválido, documento não fornecido, trecho não encontrado, valor fora do trecho). Só
  as aceitas são gravadas; saída 0 mesmo com recusas, 2 sem o arquivo de entrada. `id` e `regra` ausentes são completados.
- **Conferência endurecida** (vale para todo o caminho, inclusive `loop`/`etapa`): o trecho precisa ter 3 palavras ou
  15 caracteres e estar no documento com fronteira de palavra; o par (valor, unidade) tem de ser um dos que o trecho
  afirma (`vocabulario.QTD_DEPOIS`/`quantidade`; o 2 de M2 e o 50 de CA-50 não contam); unidade só do vocabulário; valor
  não negativo. Campos do código (`citacao`, `derivada`, `id`, `autor`, `justificativa`) vindos da IA são descartados e o
  `id` recalculado; o build reconfere as evidências `ia` e não confia no selo do arquivo. A leitura da IA é afirmação
  própria (`ia:<arquivo>`): não soma com o regex e não aumenta a `forca`. `id` normaliza `250` e `250.0`.
- **Skill `eap-evidencias`**: o passo a passo "a IA propõe, o código confere".
- **Conferência por linha** (3ª rodada de revisão): o par (valor, unidade) e o termo do item (ou sinônimo) têm de estar
  na mesma linha do documento, a até 8 palavras; o trecho não atravessa página. Recusados: pedaço de número ("250" de
  "1.250", "5 m³" de "12,5 m³"); item inexistente na EAP geral, serviço não admitido pelo item ou unidade fora das do
  serviço; `escopo` fora do enum; página do localizador que não contém o trecho. Aceitos: unidade antes do número
  ("Escavação m³ 1.250,50"), número com parênteses por extenso, vários pares na mesma linha. Toneladas viram kg.
  Linha malformada no JSONL (inclusive valor fora de ±1e12) vira recusa com motivo, sem derrubar `etapa` nem `conferir`.
- **4ª rodada**: parcelas da IA no mesmo documento só colapsam com o mesmo trecho normalizado (B1 e B2 com 12 estacas
  cada somam 24; a mesma frase em outra página conta uma vez); dedupe por `id` só para `ia` (as outras fontes somam
  como antes); "3.000 metros de estacas" não vira unidade; o número pertence ao termo de item mais próximo na linha
  (senão "número pertence a outro item"); número colado a letra ("DN150", "CA-50") não é quantidade para a IA;
  milhar com espaço ("1 250") barrado; páginas normalizadas uma vez por documento (500 páginas × 200 evidências em
  0,6 s, antes ~100 s).
- Limites declarados: descrição de planilha em várias linhas e "Quantidade: 250 un" em linha própria são recusados;
  ponto decimal ("1250.50") é recusado; "Escavação manual para blocos de estacas m³ 45" ainda pode virar estaca; o
  serviço não precisa aparecer no trecho.
- Lição L035.

## 0.38.0 — 2026-11-02 · Aba EAP: só pranchas desta disciplina
- **Recorte dos layers CAD pelo nó da EAP** (`eap_painel.subgrupos_do_codigo`): cada nó da árvore codificada traz
  `subgrupos_mapa` e `pranchas_txt`, calculados em Python pelo mapa subgrupo → pacote de `conceitos/eap.json`
  (`pranchas`). Nó de disciplina: subgrupos com algum pacote da disciplina; pacote ou item: subgrupos com o pacote
  exato; unidade e sistema: sem recorte.
- **Checkbox "só pranchas desta disciplina"** na linha "Vista" da aba EAP (só com pranchas georreferenciadas): guarda
  um instantâneo de `P.vis` e `P.mapa.on` de cada prancha, deixa ligados só os layers dos subgrupos do nó e restaura
  o instantâneo ao desmarcar, ao limpar o filtro EAP ou ao trocar de nó. O JS só testa pertencer à lista.
- Fecha o pendente da 0.37.0 (`docs/EAP.md` §9, item 7).
- Revisão: ligar pelo recorte não tira o mapa do enquadramento do nó (`ligarPranchaMapa` com `semVoo`); limites
  conhecidos registrados em `docs/EAP.md` §9.
- Lição L034.

## 0.37.0 — 2026-11-02 · Aba EAP: selo por nó, filtro por prefixo e vista particular
- **Selo de status por nó** (`eap_painel.status_do_no`, `arvore`): `status_no`, `n_fatos` e `n_conflitos` calculados em
  Python a partir dos fatos sob o nó. Fato com `*` no código vale para todo nó que casa segmento a segmento; fato de
  item vale para o item e os ancestrais. Conflito > fonte única (inclui só menção) > convergente (inclui decidido);
  sem fato, "sem evidência". `montar(eap_codificada, evidencias)` segue como interface pública.
- **Filtro por prefixo no mapa**: "ver no mapa" esmaece os demais elementos construtivos (sem removê-los) até
  "limpar filtro EAP". O esmaecimento está em `estiloObra`, então sobrevive a `aplicarEscopoMapa` e à troca de escopo.
- **Vista particular**: o item abre a ficha do primeiro elemento (e enquadra todos, se forem vários); linha
  "Vista: código · nome (n elementos)" no topo da aba EAP, com o botão de limpar.
- Revisão: o `*` só cobre sistemas que têm o item (quantidade sob o nó); `selo_title` e `rotulo_vista` vêm do Python;
  aviso "Filtro EAP: código" com botão de limpar também na aba Obra; limpar o filtro preserva a seleção feita depois;
  item com vários elementos não abre popup com autoPan (o enquadramento manda); nó não-item com um elemento volta a
  selecionar e abrir popup sem trocar de aba (como antes); fatos e quantidades divididos uma vez, indexados por unidade.
- Pendente: esmaecer layers CAD de outras disciplinas (ver `docs/EAP.md` §9).
## 0.36.0 — 2026-11-02 · Memória espacial, rodada 6: as gavetas falam a EAP codificada
- **De-para 3 com o código real** (`conceitos/de_para_eap.json`, `codigo_eap`): cada saída das gavetas aponta o
  item (`eap_geral.jsonl`) e os serviços (`servicos.jsonl`) da EAP codificada. Vala vai para `GEO.MOV.VAL`,
  pavimento para `CIV.PAV.REC`/`CAL`, supressão para `GEO.MOV.SUP` e cavas para `GEO.MOV.ESC`/`REA`. Caximbos e área
  de cava ficam "sem código", à vista.
- **Código completo por serviço** (`gavetas.codigo_eap`, `unidade_sistema`): `UNIDADE.SISTEMA.ITEM` no formato de
  `eap.estrutura`. A unidade e o sistema vêm do setor, do `local` do trecho pelas `chaves` de
  `unidades_construtivas.json` ou do padrão do obra.json. Sem nenhum, ou com mais de um sistema, vira pendência,
  nunca código inventado.
- **Conciliação das duas EAP** (`gavetas.conciliar_eap`, `obra._conciliar_eaps`): a medida de cada item das gavetas
  é comparada com a quantidade da EAP codificada. As situações são confere, difere, só nas gavetas, só na EAP
  codificada e fora das gavetas. O resultado vai para `conciliacao_eap.json` e para a tabela na aba EAP.
- Lição L032.

## 0.35.0 — 2026-11-02 · Aba EAP: árvore codificada, fatos e evidências
- **Fim da colisão em `dados["eap"]`** (`camadas/obra.py`): a árvore das gavetas fica em `dados["eap_gavetas"]`
  e a EAP codificada em `dados["eap"]` (convenção da 0.34.0); o painel é montado a partir da codificada.
- **`camadas/eap_painel.py`** (`dados["eap_painel"]`): árvore codificada com quantidades somadas por nó (nunca entre
  unidades ou tipos de item diferentes) e os ids dos elementos; fatos com conflito primeiro e afirmações; serviços
  associados × edital; resumo por status. Tudo em texto pt-BR, calculado em Python.
- **Aba EAP do visualizador**: aparece também só com `eap_painel` e ganha três seções (EAP codificada com "ver no mapa",
  Fatos e evidências com filtro por status, Serviços associados × edital). O destaque no mapa reutiliza o halo da aba Obra.

## 0.34.0 — 2026-11-02 · Memória espacial, rodada 5: cavas e setores da ETA
- **Gaveta `superficies`**: o terreno (MDS do drone) vai para `base/superficies/<id>.npz`, gravado byte a byte
  determinístico, e a gaveta guarda o sha256, o CRS, o datum e a evidência. `ler_superficie` confere o sha256: um
  arquivo adulterado ou ausente vira pendência, sem cálculo.
- **Cavas nas gavetas**: um objeto `conjunto_cavas` com as marcas de cota, as bases, as cristas e a superfície. A regra
  `cavas` (`escavacao.quantificar_gavetas`) chama o `escavacao.calcular` atual, com paridade 0. A EAP ganha CV.01 a
  CV.03 por cava, e trocar o MDS muda a chave e recalcula.
- **Setores da ETA**: setores declarados no `obra.json` (`gavetas.setores`, natureza `decidido`). Cada objeto cai no
  setor que contém o seu ponto representativo, e cada cava cai no seu pelo ponto do serviço. Sobreposição vira
  pendência. A EAP mostra também a soma por setor, conferida contra o total de cada nó.
- O gerador sintético monta todas as gavetas do contrato.
- Lição L030.
## 0.33.0 — 2026-11-02 · Escoramento total e planilha Obras Lineares como evidência
- **Escoramento total da vala** (`conceitos/servicos_associados.jsonl`, regra `escoramento_vala_total`): além do serviço
  por tipo (`escoramento_continuo`…), toda vala escorada gera o fato (GEO.MOV.VAL, `escoramento`, m²). Métodos que
  escolhem tipos diferentes (NBR contínuo × MOS pontaleteamento) e fontes que não dizem o tipo agora se comparam.
- **Planilha Obras Lineares como fonte** (`evidencias.de_obras_lineares`): uma evidência por trecho e grandeza digitada
  (comprimento, escavação, reaterro, bota-fora, supressão), código `U1.LINEARES.*` (configurável em
  `obras_lineares.eap` no obra.json). O escoramento da planilha é sim/não, sem área, e não gera evidência.
- **Planilha × MOS dos mesmos trechos** (`evidencias.de_obras_lineares_mos`): o recálculo por
  `lineares.dimensionar_vala` entra como `metodo:mos_sanepar` nos mesmos fatos: digitado igual ao recalculado é
  convergente, diferente é conflito com as duas afirmações. `evidencias.etapa` soma as duas fontes via `loop(extras=...)`.

## 0.32.0 — 2026-11-01 · EAP codificada como linha mestra
- **EAP (WBS)** (`camadas/eap.py`, `conceitos/eap.json`, `docs/EAP.md`): código `UNIDADE.SISTEMA.DISCIPLINA.PACOTE.ITEM`
  sobre as unidades e os sistemas de `unidades_construtivas.json` (obra localizada × linear); disciplinas Geotecnia
  (fundações: estacas, blocos, contenções; movimentação de solo), Civil (estruturas de concreto: piso, viga, pilar,
  parede; pavimentação), Hidráulica (equipamentos; tubulações) e Elétrica. O item vale só para o tipo de obra
  declarado.
- **Quantificação determinística**: elemento construtivo → item pela classe → quantidade pela regra do item
  (contagem, soma de atributo, comprimento ou área em UTM), sempre com os ids dos elementos e a fonte. Elemento sem
  o atributo vai para `sem_valor`. A consolidação soma por tipo de item. `lacunas` lista o que falta e `sem_item` o
  que sobra (regra dos 100 %).
- **Prancha como evidência do pacote** (subgrupo de disciplina → pacote; `eap` opcional na prancha do obra.json).
- **IA verificada** (`eap.verificar`): a proposta é refeita só com as evidências citadas. Sem evidência, evidência de
  outro item, medição não prevista ou número que não sai dos elementos: recusada.
- **EAP geral em JSONL** (`conceitos/eap_geral.jsonl`): um item por linha, com escopo água/esgoto, tipo de obra,
  termos de busca, serviços admitidos, filtro no cadastro de materiais e medições; itens novos: viga baldrame,
  poços de visita (esgoto) e ligações prediais. `eap.json` fica só com a hierarquia.
- **Banco de serviços** (`conceitos/servicos.jsonl`): escavação, reaterro, escoramento, lastro, forma, concreto,
  armadura, demolição e recomposição de pavimento, assentamento…
- **Vocabulário** (`camadas/vocabulario.py`, `conceitos/sinonimos.json`): abreviações, sinônimos e unidades (t → kg).
  "30 MPa" e "DN 300 mm" não viram quantidade.
- **Loop de evidências** (`camadas/evidencias.py`, `conceitos/evidencia.schema.json`): texto (página e linha),
  planilha do contrato (item pelo cadastro de materiais, senão pela descrição), pranchas medidas, IA com citação
  conferida e decisões com autor. Fato = código × serviço × unidade. Status: convergente (força = nº de documentos),
  fonte única, conflito (todas as afirmações e a diferença %), só menção ou decidido. O código `*` compara o total
  de um documento com a soma dos sistemas de outro (300 estacas nas pranchas × 250 no memorial = conflito).
  Também gera a cobertura item × projeto/edital e o registro `evidencias.jsonl` sem duplicar.
- **Serviços associados** (primeira versão, substituída abaixo pelas regras genéricas): bloco → escavação,
  reaterro, lastro, forma, concreto e armadura (taxa a calibrar); estaca → concreto e arrasamento; trecho → escavação,
  berço e reaterro de vala, demolição e recomposição de pavimento (premissas de `valas.json`); laje → escoramento;
  baldrame → escavação e reaterro. Fórmulas num avaliador restrito, com a memória de cálculo no trecho. Variável
  faltando vai para `sem_valor`, nunca para zero. `associados_x_edital` aponta o serviço associado que o edital não
  cita.
- **Serviços associados genéricos: elemento → dimensões → serviços.**
  - `camadas/dimensoes.py` e `conceitos/dimensoes.json`: cada tipo (estaca, bloco, pilar, laje, viga, baldrame,
    parede, vala) gera as dimensões padronizadas V, A_forma, A_fundo, A_escoramento, A_imperm e V_esc/V_reat. A
    origem pode ser o elemento das pranchas, o `obra.json` (`elementos_declarados`) ou um fato consolidado.
    Derivados: bloco → cava de fundação, baldrame → vala corrida, trecho → vala por superfície.
  - `camadas/associados.py` e `conceitos/servicos_associados.jsonl`: uma regra por serviço, valendo para todos os
    tipos que lista (forma = A_forma para bloco, pilar, laje, viga, baldrame e parede; lastro = A_fundo × 0,05;
    escoramento; impermeabilização; armadura por taxa do tipo; escavação/reaterro de cava). Tem condição e modelos
    de destino (`{item}`, `{item_pavimento}`, `escoramento_{tipo_escoramento}`).
  - `camadas/formulas.py`: avaliador restrito com comparações e condicional, e `conferir` nas validações.
- **Vários métodos para a mesma vala, sem escolher um**: cada método de `dimensoes.json#vala.metodos` vira uma fonte
  de evidência (`metodo:<id>`). O método `mos_sanepar` chama o dimensionador único da `main`
  (`lineares.dimensionar_vala`, D2): a evidência MOS é o mesmo número do build. O `nbr12266` usa as regras genéricas.
  A consolidação mostra convergência (corte, assentamento) e conflito com o porquê. Exemplo da AAT06: o raio de 60 m
  do MOS não alcança o furo a 80 m; o bota-fora do MOS é só o volume do tubo (60,8 × 382,7 m³).
- **A vala é só mais um tipo**. `dimensoes.dimensionar_vala` decide por segmento de superfície:
  - profundidade (recobrimento + DE + berço, ou a do perfil);
  - solo, rocha e NA da sondagem mais próxima (raio 300 m, NA com margem de 0,5 m);
  - escoramento pela NR-18 (1,25 m) e pelos agravantes (areia/aterro, NSPT < 4, abaixo do NA);
  - largura com o acréscimo do escoramento e tipo de pavimento.

  Desses dados saem, pelas regras genéricas: corte, demolição e recomposição (asfalto → `CIV.PAV.REC`, calçada →
  `CIV.PAV.CAL`, item novo), escavação em solo e em rocha, escoramento por tipo, berço, envoltória (tubo
  flexível), assentamento, reaterro com reaproveitamento, bota-fora empolado e esgotamento ou ponteiras. Sem
  sondagem, nada disso é suposto e o resultado leva alerta. Serviços novos: corte de pavimento, escavação em
  rocha, escoramento por tipo, envoltória e esgotamento.
- Dimensão que falta não vira zero: o serviço fica "sem valor" com a cadeia até a origem (`V ← h ← face`). O que
  não depende dela sai normalmente (viga sem altura ainda dá o escoramento b × L).
- Cadastro de materiais × EAP: 24,7 mil materiais balizam itens no escopo água e 29,6 mil no esgoto.
- O build grava `dados.eap`, `dados.evidencias` e o código `eap` em cada elemento da aba Obra, além de
  `evidencias.jsonl`, `fatos.csv`, `cobertura.csv` e `associados.csv`. A aba EAP no HTML fica para a próxima rodada
  (`docs/EAP.md` §9).
## 0.31.0 — 2026-11-01 · Rodada 25, PR 4: dimensionador único de vala, trechos e conferências no build
- **Dimensionador único de vala** (`lineares.dimensionar_vala`): profundidade pelo perfil longitudinal (média
  ponderada pela extensão, sem extrapolar; sem perfil, premissa com alerta), largura pelo MOS Sanepar, escoramento pela
  NR-18 (acima de 1,25 m) com tipo por faixa de profundidade (pontaleteamento, descontínuo, contínuo, especial) e
  agravantes da sondagem (areia ou aterro, solo mole, NSPT < 4, fundo abaixo do NA), esgotamento por bomba ou
  ponteiras pela altura de água e pelo solo da faixa submersa, `alerta_na` sazonal. Regras em
  `conceitos/lineares.json › vala`, todas como premissa com fonte. `obras_lineares.quantificar` delega a ele; o
  gabarito da aba Obras Lineares passa sem alteração.
- **Valas das adutoras pelo mesmo dimensionador (D2)**: `valas.secao` deixa a NBR 12266 e usa o MOS; cada rede ganha
  `material` (FD de premissa, com alerta) e `dn_mm`. Caso DE 0,30 m na pista, 10 m: largura 0,90 → 0,75 m, volume
  12,6 → 10,5 m³ (`results/iteracoes/rodada25_D2_nbr_x_mos.md`). O hash do conjunto de referência muda só no
  `caso_valas_por_classe` (conferido caso a caso).
- **Trechos do eixo** (`lineares.trechos`): corta nas fronteiras de superfície, no ponto médio entre furos e nos PVs;
  a soma dos trechos é o comprimento do eixo.
- **Conferências geotécnicas no build** (`obra._conferencias_geotecnia`): boca do furo × terreno, estaca sem
  coordenada, estaca × impenetrável, cava × NA; vão para `dados["geotecnia"]` e para `pendencias.json`.
- **Impressão da regra** com fecho transitivo dos módulos e dos imports tardios declarados em `DEPENDENCIAS`.
- PDCA: L3a por um Opus, L3b e F por Sonnet; o Fable aceitou com ressalvas não bloqueantes. Lições L026 e L027.

## 0.30.0 — 2026-11-01 · Rodada 24 da memória espacial: valas, fatos da IA e escala de 100 km
- **Valas das redes nas gavetas**: `extrair_gavetas.de_valas` grava a rede como objeto `rede_vala`, com o eixo
  amostrado e a classe de superfície de cada metro como fato (natureza `inferido` quando a classe vem da ortofoto). A
  regra `vala_rede` (`valas.quantificar_gavetas`) dá demolição, recomposição e escavação por classe, que entram na
  EAP como RD.01 a RD.03. A paridade com `valas.quantificar` usa os serviços gravados.
- **Fatos da IA no build**: `extrair_gavetas.de_retornos` lê `retornos_gavetas/*.jsonl`. O que passa vira fato
  `inferido`, com executor e trecho; recusa, linha inválida ou classe divergente vira pendência com motivo. O fato
  da IA nunca vence o do documento.
- **Escala** (`scripts/bancada_calculo.py`, critério fixado antes):
  - `gavetas.indice` monta a base uma vez e o `anterior` é indexado;
  - `furo_por_metro` filtra os furos pela caixa do eixo antes de delegar a `geotecnia.furo_mais_proximo`, com
    resultado idêntico (300 casos aleatórios; o hash da referência não mudou);
  - `id_furo` com cache e `para_eap` linear;
  - em 20 km, o 1º cálculo caiu de 70,4 s para 0,4 s;
  - em 100 km (5 501 objetos e 31 503 fatos): cálculo completo em 4,3 s, montagem da EAP em 2,2 s e pico de 466 MB,
    todos dentro do critério;
  - **o critério do 2º cálculo reprovou** (1,38 s contra o limite de 10 %, 0,43 s): ele monta a entrada de cada
    objeto para obter a chave, e isso é um custo fixo.
- Lição L025.

## 0.29.0 — 2026-11-01 · Rodada 25, PR 3: modelo geotécnico único, conferências e leitor de perfil
- **Modelo geotécnico único** (`camadas/geotecnia.py`): `classe_solo`, `solo_na_faixa`, `categoria_escavacao`,
  `na_m`, `topo_rocha_m`, `perfil_em` (furo mais próximo, vetorizado, com a distância e o raio) e `alerta_na` (fundo
  da vala a menos de 0,5 m do NA, porque o NA é sazonal; o alerta não muda o cálculo). As regras de solo, rocha e
  categoria, o raio e o empolamento saíram de `obras_lineares`, que agora delega: uma só fonte, em
  `conceitos/geotecnia.json`. O hash do conjunto de referência não mudou.
- **Conferências projeto × sondagem** (`geotecnia.conferir`): estaca que não chega ao impenetrável ou passa dele,
  cava abaixo do NA (esgotamento) e trecho de rede sem furo no raio, com tolerância absoluta de 0,10 m.
- **Leitor do perfil longitudinal, piloto** (`lineares.ler_perfil`): pela grade sob o desenho, lê estaca, cota do
  terreno, cota da geratriz inferior ou do fundo da vala e profundidade escrita. Profundidade = terreno − (geratriz −
  berço), ou terreno − fundo. O que não sai vai para `nao_lidos`.
- PDCA: G2/G3 e L2 feitos por dois Sonnet em paralelo. O Fable devolveu o L2 uma vez: o fundo da vala somava o berço e
  deixava a vala 10 cm mais funda. O gerente corrigiu, e o L2 foi aceito no 2º julgamento. Lição L023.

## 0.28.0 — 2026-11-01 · Rodada 23 da memória espacial: EAP lastreada no HTML e recálculo incremental
- **EAP montada em Python** (`camadas/eap_html.py`): cada nó leva aos serviços, cada serviço aos fatos usados e cada
  fato à evidência (documento, onde, trecho, executor). Os valores saem formatados no padrão brasileiro e com unidade
  SI; o HTML só apresenta.
- **Aba EAP no visualizador**: árvore nó → serviço → fato → evidência, pendências e resumo, sem nenhuma conta em JS
  (teste no Chromium: `tests/test_visualizador_eap.py`). A conferência de ponta a ponta com dados do próprio código
  achou 0 números sem origem no Python.
- **Recálculo incremental** (`gavetas.calcular_incremental`, `chave_servico`): a chave é o hash da regra, da versão,
  dos dados de entrada, dos fatos e dos furos usados; o serviço de mesma chave é reaproveitado sem chamar a regra. A
  etapa do build lê o anterior em `base/servicos.parquet` e o resumo conta recalculados e reaproveitados.
- `dados["eap"]` ligado ao build (`extrair_gavetas.etapa` → `obra._aba_projeto`).
- Lição L022.
## 0.27.0 — 2026-11-01 · Rodada 25, PR 2: leitor de laudo de sondagem e estaqueamento da obra linear
- **Geotecnia como disciplina** (`camadas/geotecnia.py`, `conceitos/geotecnia.json`): schema do furo com a unidade de
  cada campo (os nomes já em uso, sem renomear, enquanto a memória espacial está em andamento); `validar_furos`; e
  `ler_laudo`, que lê pelo texto do PDF a tabela de coordenadas e o perfil de cada furo (camadas, NA, impenetrável,
  NSPT). O que não sai vai para `nao_lidos` com o motivo, sem inventar. Premissas da decisão D1 declaradas: raio de
  60 m, margem do NA de 0 m, empolamento de 1,30 no solo e 1,50 na rocha.
- **Obra linear: eixo e estaqueamento** (`camadas/lineares.py`, `conceitos/lineares.json`): "12+10,00" ↔ progressiva
  ↔ ponto, projeção de um ponto no eixo com afastamento e lado, segmento entre progressivas. Vetorizado, com tolerância
  de 1 mm.
- Lint de `camadas/mosaico.py` e `tests/test_escada.py` (Haiku).
- PDCA: G1 e L1 feitos por dois Sonnet em paralelo, o lint por um Haiku. O Fable devolveu o G1 uma vez (a preposição
  "na" virava nível d'água); o gerente corrigiu e o G1 foi aceito no 2º julgamento. O balanço do vcm acusou o tempo da
  referência, tratado como ruído (mesmo hash, faixas sobrepostas em 5 execuções).

## 0.26.0 — 2026-11-01 · Rodada 22: extração para as gavetas
- **Leitores → gavetas** (`camadas/extrair_gavetas.py`): a planilha Obras Lineares vira objetos `trecho_tubo`, com
  fatos e evidência de aba e linha; as sondagens viram `furo_sondagem` com geometria de ponto e o executor de quem
  escreveu o arquivo; a escolha de método do obra.json vira fato `decidido`. Valor vazio não vira fato.
- **Paridade** (`gavetas.paridade`): o cálculo das gavetas é comparado, serviço a serviço, com o
  `obras_lineares.quantificar`. Sem eixo, os furos citados na planilha entram na memória de cálculo.
- **IA aponta a gaveta**: os lotes da escada dizem em que gaveta cada classe de arquivo grava
  (`extracao.gavetas_da_classe`); `extracao.fatos_do_retorno` transforma o retorno conferido em fatos `inferido`,
  com o executor e o trecho citado, e recusa o que estiver fora do de-para.
- **Base no build**: a etapa `gavetas` grava `saida/<obra>/base/` (parquet), `paridade.json` e `resumo.json`; o build
  segue mesmo se a etapa falhar.
- Lição L020.

## 0.25.0 — 2026-11-01 · Rodada 21: as caixas — formato das gavetas medido e escolhido
- **Gerador sintético** (`camadas/sintetico.py`, `base_linear(km)`): adutora com eixo em UTM, trechos de 20 m, furos
  a cada 200 m e fatos com evidência; 100 km em 0,17 s, a mesma base para a mesma semente.
- **Formatos nas gavetas** (`camadas/gavetas.py`): parquet (tipo nativo nas colunas homogêneas, JSON nas outras),
  geoparquet (WKB e metadados `geo` 1.1.0 com o CRS) e duckdb, além de jsonl e csv; ida e volta sem perda nos cinco.
- **Bancada** (`scripts/bancada_gavetas.py`): tamanho, gravação, leitura, RAM (pico de RSS num subprocesso) e três
  consultas p50/p95 pelo motor comum DuckDB e pelo nativo; `decidir` aplica o critério fixado antes de medir.
- **Decisão**: `formato.atual = parquet` (`conceitos/gavetas.json`, com a evidência). Em 100 km, 8× menor que o JSONL
  e consulta pelo motor comum 13× mais rápida; RAM maior (117 × 54 MB). Registros versionados no git continuam em
  JSONL. `pyarrow` passa a ser dependência obrigatória.
- Lição L019.

## 0.24.0 — 2026-10-31 · Memória espacial: gavetas e os três de-para
- **Gavetas** (`conceitos/gavetas.json`, `camadas/gavetas.py`): objetos, geometria, fatos, evidências, pendências e
  serviços, com campos obrigatórios e valores permitidos. Um fato só entra com propriedade declarada, natureza
  (observado, projetado, inferido, decidido) e evidência existente (`conferir_base`).
- **Três de-para**: documento → gaveta (`de_para_extracao.json`), gaveta → serviço (`de_para_servicos.json`) e
  serviço → EAP (`de_para_eap.json`); `conferir_de_para` reprova propriedade, função ou nó inexistente.
- **Serviços só das gavetas** (`calcular`): vala aberta e MND pelo `obras_lineares.quantificar`, com a sondagem
  colocada pela posição (furo mais próximo de cada metro do eixo, no raio de influência). Cada serviço guarda os
  fatos e a versão da regra (memória de cálculo); fato obrigatório faltando vira pendência e nenhum serviço. A decisão
  do método troca a regra sem reler documento.
- **EAP lastreada** (`para_eap`): soma por nó com os serviços e objetos que a sustentam.
- **Formato físico como experimento**: JSONL (atual) e CSV com ida e volta sem perda; Parquet, DuckDB e os demais
  candidatos ficam para G05/G08, com as métricas listadas em `gavetas.json`.
- `docs/MEMORIA_ESPACIAL.md` v0.3: formato das gavetas, inventário e escada de executores, sondagens e memória de
  cálculo. Lição L018.

## 0.23.0 — 2026-10-31 · Rodada 20, PR 3: o loop de extração fecha sozinho
- **Executor da escada** (`camadas/escada.py`, `python -m camadas.escada <obra.json>`): cada pendência sobe pelos
  `degraus` de `conceitos/fontes.json` (código: baixar, reler, carimbo em 300 dpi, extrair o zip; depois Haiku, Sonnet,
  você), com `max_tentativas` em todo degrau; repete até não haver degrau de código; o resto vai para
  `saida/<obra>/lotes/<executor>.jsonl` (sobrescrito a cada rodada). O conteúdo dos zips vira itens filhos
  inventariados.
- **Retorno da IA conferido** (`extracao.aplicar_retornos`): o agente grava em `saida/<obra>/retornos/`; entram só os
  campos de `retorno` da classe e só se o trecho citado está na página (imagem: "não conferível", anotado); retorno
  repetido não conta duas vezes. O registro grava quem completou (`registrar_por_executor`), no build e na escada.
  O esperado × encontrado usa os itens já complementados.
- Teste de integração do ciclo inteiro: lote do Sonnet → retorno → a volta seguinte fecha o item e registra "Sonnet".
- Índice de determinismo: 66,7 % das etapas em código (a escolha do próximo passe e a conferência do retorno deixaram
  de ser da IA na sessão). Lição L014.
- Aceite do Fable no 2º julgamento da E6: a escalada da IA não subia (chaves diferentes para a mesma tentativa; o
  retorno recusado não contava). Corrigido, e toda escada termina em "você" (lição L015).

## 0.22.0 — 2026-10-31 · Rodada 20, PR 2: releitura, PDF inteiro, papel por pasta e esperado × encontrado
- **Releitura sem o cache travar** (`inventario.py`): `LEITURA_VERSAO` na assinatura, `reler` força a leitura e erro
  é relido em toda rodada. O resultado dos degraus e da IA fica em `saida/<obra>/complementos.json`, com executor e
  tentativas, mesclado por `extracao.pendencias` (o cache guarda só a leitura básica).
- **PDF lido inteiro**: `texto` pela fração de páginas com texto (até 20), carimbo de cada página e `reler_carimbo`
  em 300 dpi como degrau alternativo.
- **Papel por pasta e esperado × encontrado** (`extracao.papel`, `extracao.esperado_x_encontrado`,
  `conceitos/documentos_esperados.json`): cada sistema confere os documentos que a tipologia exige (forma, armadura,
  locação e cargas, fundação; planta e perfil nas redes). Vai para `pendencias.json` (`esperado`, `por_papel`).
- **Custo dos agentes** (`pdca/agentes.jsonl`, resumo por modelo em `scripts/determinismo.py`) e a **proposta do
  observatório entre repositórios** (`docs/ARQUITETURA.md` §11).
- PDCA: implementado por três Sonnet (dois em paralelo, um na revisão), julgado pelo Fable. E1 e E3 foram devolvidas
  uma vez e aceitas na revisão. A aferição deixou de varrer `.claude/` (os worktrees dos agentes duplicavam o código).

## 0.21.0 — 2026-10-30 · Arquitetura R7: ciclo de extração, fontes de evidência e geotecnia separada
- **Reavaliação do inventário a cada build** (`camadas/extracao.py`, `conceitos/fontes.json`): classe da fonte de
  cada arquivo (projeto, memorial, laudo, lista, edital, planilha, folha de dados, documento de obra, cotação fora do
  escopo), estado da extração (completa, parcial, falhou, sem leitor, fora do disco) pelos campos que a classe exige,
  próximo passe da escada (código → Haiku → Sonnet → Opus → você) e séries de folhas incompletas pelo carimbo "n/m".
  Grava `saida/<obra>/pendencias.json` e o registro `extracao.jsonl` (só quando o estado muda).
- **Arquitetura R7** (`docs/ARQUITETURA.md`): o ciclo inventário → extração → reavaliação → loop, a fonte de cada
  fato, a interpretação dos projetos pelo carimbo, a geotecnia como disciplina independente (modelo geotécnico único
  no lugar dos dois interpretadores divergentes) e os agentes por degrau da escada.
- **A regra da lição vale para qualquer sessão**: cada versão do CHANGELOG desde a 0.19.0 precisa de uma lição em
  `pdca/licoes.jsonl` (teste). Lições L010 (rodada 19), L011 e L012. Índice de determinismo: 63,6 % das etapas em
  código.
- **Revisão independente (Fable)** antes do PR: nome vale mais que a pasta, termos com fronteira de palavra, laudo
  antes de projeto, OS escaneada não sai completa, foto dispensa leitura, séries por unidade com aviso de arquivo fora
  do disco, registro de qualquer mudança e cotação listada à parte. O que falta para o loop fechar sozinho está em
  `docs/ARQUITETURA.md` §2.
- **Arquitetura R8** (§10, PDCA com gerente): cada rodada tem plano com entregas e verificação. O Fable aprova o plano,
  aceita ou devolve cada entrega e escreve a entrega final; o Opus executa; Sonnet e Haiku implementam contra um
  contrato fixo. PR na `main` só com testes, aferição, determinismo verdes e o aceite. Plano da rodada 20
  (`docs/plano/2026-10-30_rodada20.md`) e o campo `retorno` por classe em `conceitos/fontes.json`.

## 0.20.0 — 2026-10-30 · Foz, rodada 19: todas as unidades da Relação de Desenhos e os desenhos não entregues
- **Unidades da Relação na aba Obra** (regra código do desenho → sistema em `conceitos/unidades_construtivas.json`):
  7 novas — câmara de contato, canal de água tratada, EEE lodo / reservatório de lodo, RECALD e RECALF, blocos de
  apoio e ancoragem, caixas de saída de água tratada e caixas de chegada de água bruta (CXA separado pela unidade da
  Relação); sistema sem geometria aparece na árvore ("sem geometria").
- **Desenhos citados × entregues** por unidade e no total: 104 citados, 46 entregues, 58 não entregues; entregue com
  link do Drive, não entregue com marcador de alerta; filtro "Só com desenho não entregue" (8 unidades).
- Escopo das novas: "a definir" sem pegada no mapa, com o motivo; caixas de saída fora pelo contrato (tabelas 03 e
  04 só com quantidade na 2ª etapa).
- Python e aba feitos por dois agentes (Sonnet) contra um contrato fixo; revisão, build e testes na sessão principal.

## 0.19.0 — 2026-10-30 · Arquitetura: só escopo, inventário primeiro e índice de determinismo
- **Cronograma e 4D removidos**: o sistema trata só de escopo (serviços e atividades numa EAP com quantidades), sem
  prazo nem preço. Saem `obra.cronograma_4d`, o bloco `cronograma` do obra.json de Foz (marcos MI, pesos das UCs,
  curva S), a barra 4D do visualizador, os testes e a documentação. Os marcos geodésicos (topografia) ficam.
- **Arquitetura R6** (`docs/ARQUITETURA.md`): EAP como linha mestra, o HTML único como caderno da obra, decisões com
  ida e volta, tipos de documento (planta, perfil, detalhe, documento), disciplinas, agentes por papel (Fable como
  revisor independente) e portões G0–G7. O cenário de mesa de uma obra nova trava em cinco pontos, com a correção de
  cada um.
- **Inventário de todos os arquivos** (`camadas/inventario.py`): não só PDF. Planilha (abas, inclusive ocultas), zip
  (conteúdo) e o que não tem leitor fica "sem leitor", à vista. `procurar` prova a ausência: busca nome, pasta e
  carimbo em qualquer situação e separa "existe, não lido" de "não existe" (lição do Actiflo 360).
- **Regra da lição aprendida e índice de determinismo** (`scripts/determinismo.py`, `pdca/determinismo.json`,
  `pdca/licoes.jsonl`): toda rodada com a IA deixa ao menos uma lição em código, com teste; o índice mede a IA na obra
  × o código. Reprova índice pior, lição sem arquivo/teste e rodada sem lição nova. Foz: 61,9 % das etapas em código
  (57,1 % antes do download pelo link direto); meta 85 %. 9 lições, 7 com teste.

## 0.18.0 — 2026-10-30 · Foz, rodada 18: a estrutura dos Actiflo a partir das formas do Drive
- **Download pelo link direto** (`camadas/drive.py`): o conector do Drive não passa de ~5,5 MB por arquivo e as
  formas e armaduras (6 a 22 MB) nunca desciam. Foz: 164 PDFs pendentes (811 MB), 0 falha; inventário com os 325
  PDFs da listagem no disco.
- **Formas dos Actiflo** (fichas `act01_forma`, `act02_forma`): Actiflo 600 — 87/87 estacas encaixadas a 6 mm, 85
  blocos (83 rotulados); Actiflo 360 — 39/39 a 3 mm, 30 blocos (29 rotulados), com níveis. Blocos na aba Obra, no
  mapa e no 3D (78 sólidos, eram 41); "blocos de coroamento" dos Actiflo passa a geometria.
- Conferido na Relação de Desenhos: o Actiflo 360 não tem pilar nem passarela, e nenhum Actiflo tem projeto de
  impermeabilização — as lacunas restantes dessas unidades são do projeto, não da leitura.

## 0.17.0 — 2026-10-30 · Foz, rodada 17: obras lineares dentro da ETA (demandas da Giselle)
- **Obras lineares da Unidade 1** (`camadas/obras_lineares.py`, `conceitos/obras_lineares.json`): os trechos de tubo
  da ETA (entrada de água bruta, interligações com os Actiflo 360/600, saída e retorno de lodo) não são AAT; cada
  trecho tem DN, material, profundidade média, comprimento e método (VCA ou MND, escolhido pelo usuário).
- **Vala pelo MOS Sanepar**: L = D + SL + X + Y, com a Tabela I de sobrelargura, X = 0,10 m se escorado e Y = 0,10 m
  por metro ou fração acima de 2 m; escoramento acima de 1,25 m (NR-18; fórmula da coluna AD). Escavação, reaterro
  (− π·DN²/4), bota-fora (empolamento 1,3), escoramento, pavimento demolido/recomposto por tipo (grama, asfalto,
  concreto, paver, lajota) e supressão vegetal. MND: só os caximbos (1 a cada 80 m, 4,5 m²) e orientações de HDD.
- **Sondagem no trecho**: cada metro do eixo na sondagem mais próxima dentro do raio de influência (60 m, calibrar)
  ou metade inicial/metade final pelos ids da planilha; solo e categoria de escavação pela descrição das camadas até
  o fundo da vala; NA mais raso que o fundo = esgotamento de vala.
- **Pavimento pela ortofoto** no eixo desenhado: verde = grama (e supressão), preto = asfalto, cinza claro =
  concreto/calçada (limiar de brilho a calibrar).
- **Conferência e conciliação** da planilha `211 - SAA Foz do Iguaçu`: o cálculo reproduz as linhas 4 a 8 da aba
  Obras Lineares; acusa a supressão de 66 % nas linhas do lodo (sem observação), a linha 9 sem profundidade
  (reaterro −0,49 m³) e concilia os itens em metro do CUSTO CIVIL (1.2, 1.3, 1.4, 1.7 e 1.8 batem; 1.5 e 1.6 são
  aéreos; 1.9 drenagem do Actiflo 600 sem comprimento nem trecho).
- **No build e no HTML**: `obras_lineares` no obra.json (planilha, unidade, método por trecho escolhido pelo
  usuário) → etapa com as sondagens da obra (ids tolerantes: SP-02 = SPT-2) → `obras_lineares.csv` e
  `obras_lineares_conciliacao.csv` em `saida/` e tabela "Obras lineares" na aba Projeto (trecho, L, volumes,
  supressão, pavimentos, solo, NA, esgotamento, conferência com a planilha, alertas, orientações de MND).
- **Tubos da ETA na Unidade 1**: sistemas `AB_ENTRADA`, `AB_INTERLIG`, `LODO_SAIDA`, `LODO_RETORNO` (tipologia
  `rede_eta`); o perfil hidráulico da ETA (`ETAVILACPERFILHIDRAU`) deixa de ser classificado como obra linear.
- Referência `referencias/sanepar/MOS_largura_de_vala_tabela_I.png` e skill `obras-lineares`.

## 0.16.0 — 2026-10-30 · Foz, rodada 16: aba Obra como determinação de escopo
- **Escopo por unidade construtiva** (`camadas/escopo_obra.py`): dentro / fora / a definir pela convenção do desenho
  004 (regra do `Escopo_1etapa_PBES.pdf`, manchas lidas da f004), pelo contrato (redes) ou manual
  (`escopo_unidades.manual` no obra.json — módulo de filtros fora, Caio 30/10), com motivo e evidência. Foz:
  Actiflo 360 e 600, adutoras e drenagens dentro; filtros, edifício do lodo e EEE fora; torre, guarita e depósito a
  definir.
- **Decomposição construtiva** (`conceitos/construcao_civil.json`, 5 tipologias, 38 partes): cada unidade desdobrada
  no que se constrói (escavação, estacas, blocos, laje de fundo, paredes, pilares, vigas, lajes, escadas,
  impermeabilização…), com evidências de geometria, pranchas e Relação de Desenhos, memoriais/TR e itens do
  contrato (sem preço); lacuna fica "sem evidência".
- **Fonte com link** para o projeto (Google Drive, pelo id da listagem) e para a aba Pranchas; elementos com `doc`.
- **Aba Obra principal**: abre primeiro; controle "No escopo" por sistema (salvo no navegador, exporta para o
  obra.json, restaura do projeto); filtro "Só o escopo"; resumo dentro/fora/a definir; ficha só no painel e popup
  mínimo.
- Motor e aba feitos por dois agentes (Sonnet) contra um contrato fixo; regra no obra.json, ligação, revisão e
  testes na sessão principal.

## 0.15.0 — 2026-10-29 · Foz, rodada 15: o HTML navegável por elementos construtivos
- **Elementos construtivos** (`camadas/construtivos.py`, `conceitos/unidades_construtivas.json`): Unidade 1 (ETA,
  obra localizada) e Unidade 2 (adutoras, obra linear) → sistema (módulo de filtros, Actiflo 360/600, AAT06…) →
  elemento, cada um vetor com atributos e fonte. Foz: 349 elementos — 256 estacas, 41 blocos, 12 pilares, 8 cavas,
  16 estruturas e 16 trechos de rede.
- **Redes como linhas consultáveis**: um trecho por folha, com DN/DE, extensão por superfície e contrato × desenho.
- **Aba "Obra"**: busca ("P5", "pilar", "AAT06"), árvore unidade → sistema → classe, clique → enquadra, destaca e
  abre a ficha; clique na linha da rede no mapa abre a mesma ficha.
- Valas: a camada do mapa somava o dobro da extensão nas redes desenhadas como faixa (corrigido).
- Forma sem blocos (ETL01, reforma) não quebra mais a leitura.
- Modelo e aba feitos por dois agentes (Sonnet) em paralelo contra um contrato fixo; ligação, revisão e testes na
  sessão principal.

## 0.14.0 — 2026-10-29 · Foz, rodada 14: HTML com nome e versão, nuvem e vetores mais leves
- **Nome do HTML com obra, versão e data** (`obra.nome_html`, `nome_html` no obra.json):
  `saida/foz/foz-vilac_camadas_v0.14.0_2026-10-29.html`; versão única do código em `camadas.VERSAO` (teste amarra ao
  CHANGELOG) e linha "Versão" no painel de informações.
- **Nuvem 3D comprimida sem perda** (`sfm.pacote_visualizador`, Sonnet): Morton 3D + deltas zigzag + planos de bytes
  + gzip 9 (`pos_cm_gz`, `rgb_gz`); 6,0 → 1,79 MB, mesmo conjunto de pontos e cores.
- **GeoJSON do HTML a 7 casas decimais** (`visualizador.arredondar_geojson`, Haiku): ≈ 1 cm; vetores 1,48 → 1,01 MB.
- Foz: HTML 26,4 → 21,7 MB.

## 0.13.0 — 2026-10-29 · Foz, rodada 13: pranchas mais leves e medição exata
- **Simplificação correta das polilinhas** (`pdf_cad.simplificar_partes`, distância ao segmento): a antiga (cv2,
  distância à reta) cortava pontas e símbolos e encurtava os comprimentos dos quantitativos em 3,5–17 % por prancha.
- **Quantitativos na geometria exata**; a simplificação (0,25 pt) é só para a tela. Escopo × desenho inalterado.
- **Pranchas por coluna + gzip 9** (Python e front): coords 12,8 → 10,6 MB; HTML 27,3 → 26,4 MB já com a geometria
  corrigida.
- Implementação e medição da simplificação por agente (Sonnet); decisão, desacoplamento da medição, formato e
  testes na sessão principal.

## 0.12.0 — 2026-10-29 · Foz, rodada 12: pacote SIG na área da obra e dependências completas
- **GeoTIFF recortado na área da obra** (`sig.recortar`, `rasterio.mask` — GDAL): `sig/ortofoto_obra.tif` (alfa 0
  fora) e `sig/mds_obra.tif` (nodata fora) ao lado dos inteiros. Foz: ortofoto 54,2 → 39,5 MB, MDS 1,6 → 1,1 MB.
- **`requirements.txt` completo**: `shapely>=2.0` obrigatório; `geopandas`, `rasterio` (GDAL) e `playwright` nos
  opcionais com o módulo que os usa; nota do SIG no README.
- Feito com agentes em paralelo (Sonnet no recorte, Haiku na auditoria de dependências), revisado na sessão
  principal.

## 0.11.0 — 2026-10-29 · Foz, rodada 11: só a área da obra no HTML
- **Área da obra** (`obra.area_da_obra`, `"area_obra"` no obra.json): envoltória convexa das intervenções calculadas
  dentro do voo + margem; contorno como camada. Foz: 22 331 m², 67 % do voo.
- **Ortofoto do drone só na área da obra** (transparente fora e recortada): 1,84 → 1,24 MB; o satélite mostra o
  entorno. HTML 27,9 → 27,3 MB.
- **Satélite só na extensão da obra** (`limites_obra`: voo + pranchas georreferenciadas + 200 m, 5,1 × 6,1 km em
  Foz): tiles fora não são pedidos.
- A nuvem 3D já estava toda dentro da área; o peso maior continua nas pranchas vetoriais (13,2 MB), que vão
  inteiras para a aba Pranchas.

## 0.10.0 — 2026-10-29 · Foz, rodada 10: saúde do código e as relações de materiais que faltavam
- **Ruff limpo** no repositório inteiro (40 avisos antigos → 0).
- **`obra.construir` em partes** (132 → 57 linhas) e `etapa_escopo` (81 → 29), com o escopo idêntico; a aferição
  cai de 8 para 6 funções longas — as restantes dependem de dados fora do disco para provar a refatoração.
- **Lote pelo caminho** (dois PDFs com o mesmo nome em pastas diferentes colidiam) e **só desenhos**
  (`prancha.e_desenho`: termo de referência, memorial, lista e descritivo ficam fora): 128 desenhos em Foz.
- **Relação na folha irmã** (`_relacao_da_familia`): balões de folha sem relação ligados à da irmã, só pelos itens
  que ela lista sem balão (015–018 → 019; PMEC 004 → 002/003).
- **Mais formatos de relação**: "DISCRIMINAÇÃO · QUANT. · UND." com código sem coluna (042A), "Nº" lido vazio
  (perfis AAT06), dois códigos na célula; **número do balão em fonte do PDF** (`palavras`, sistema pneumático);
  **escala do título em fonte e acima da vista** (contenção, 1:50).
- Foz: balões ligados a item 1 864 → 2 336 (87 %), itens lidos 538 → 597 em 29 folhas, 456 no contrato; só 011 e
  012 (TRATAM360) ficam sem relação — nenhuma irmã a tem no disco.

## 0.9.0 — 2026-10-28 · Foz, rodada 9: forma completa, fichas em lote e diagnóstico em código
- **Forma completa** (`prancha.rotulos`, `prancha.pilares`): rótulos sob hachura lidos numa 2ª passada sobre o
  recorte redesenhado sem a hachura (`desenho_sem_hachura`) → 41/41 blocos rotulados (antes 34); pilares como
  manchas cheias quadradas dentro dos blocos → 12 pilares (P1–P12, 0,41 m), no mapa (`blocos_forma`) e na ficha.
- **Fichas em lote** (`prancha.lote`, `ficha_leve`): toda prancha de desenho no disco ganha ficha (identidade,
  vistas, escalas, tabelas, balões, objetos por classe); onde há balões, a completa (relação de materiais × balões
  × contrato). Foz: 144 PDFs, 0 erro; 36 folhas com balões (2 685), 538 itens de relação lidos em 26 delas, 443 (82 %) com código no contrato, 1 864 balões (69 %) ligados a item. Aba Projeto: linha "Ficha" por item e filtro "Com balões". Em paralelo (um processo
  por núcleo); tesseract numa thread.
- **Relação de materiais mais robusta**: cabeçalho separado do corpo por linha dupla (`_empilhar`), quantidade por
  etapa (`q1`, `q2`, colunas "1ª/2ª ETAPA" pela ordem), número do balão no próprio layer do círculo e escolha
  automática do layer do número (f010 41/41 sem configurar; folha 053: 0 → 97/105).
- **Escala do título 50× mais rápida**: OCR só dos glifos SHX da faixa, redesenhados no branco (2 s por folha).
- **Encaixe de vista de detalhe** (`registrar_vista`): rotações de 90°, correlação e nota F1, só com pico claro
  (≥ 15 % sobre o 2º); balões de vista encaixada no mapa (`pecas_baloes`). A f010 continua sem coordenada: nenhuma
  referência tem o desenho das interligações (1º e 2º a 1–2 %).
- **`camadas/diagnostico.py`** (pedido do Caio: o que a IA fazia em script avulso vira código): layers em volta de
  um ponto UTM, inventário de layers × classe, recorte da folha, sobreposição prancha × referência × ortofoto,
  afinação do OCR; linha de comando `python -m camadas.diagnostico`.
- Cache das fichas versionado (`prancha.VERSAO`).

## 0.8.0 — 2026-10-28 · Foz, rodada 8: a prancha lida em camadas de entendimento (pilotos)
- **Classe de elemento por layer** (`conceitos/elementos.json`, `pdf_cad.elemento_do_layer`): 40 classes (tubo,
  válvula, conexão, bloco, estaca, pilar, viga, parede, meio-fio, calçada…) com os serviços que geram; 99,6 % dos
  traços de Foz classificados; cada layer do pacote vetorial ganha `elemento`, exibido e pesquisável na árvore.
- **Ficha da prancha** (`camadas/prancha.py`, skill `ler-prancha`): identidade → vistas e escala → tabelas por OCR
  → elementos (layer ou geometria) → vínculos → serviços. Piloto hidráulica (f010): 32 itens da relação de
  materiais, 41/41 balões ligados a item, 30 itens no contrato. Piloto estrutura (forma do módulo de filtros):
  104 estacas e 41 blocos pela geometria, encaixe nas estacas com E/N 104/104 a 9 mm (RANSAC), níveis das tabelas
  → 34 blocos em 3D e camada `blocos_forma` no mapa.
- **f010 sai do mapa**: a folha de detalhe herdava a escala 1:250 da irmã, mas a planta é 1:100 (2,5× grande desde
  a rodada 5). Conferência escala do título × escala da afim.
- OCR do SHX com a letra normalizada a 18 px (6/6 cotas; a 25 px, 0/6).

## 0.7.0 — 2026-10-28 · Foz, rodada 7: inventário de projetos, movimento de terra e valas
- **Inventário determinístico** (`camadas/inventario.py`): a listagem do Drive é a referência e cada PDF ganha uma
  linha — situação (no disco / outra pasta / falhou / não tentado), formato da folha (A0–A4, estendido), código
  Sanepar e o carimbo do canto inferior direito (texto do PDF, fonte ArialMT sem ToUnicode reparada, ou OCR).
  Foz: 325 PDFs, 163 no disco, 22 falharam e 140 nunca foram tentados. Aba Projeto com resumo por disciplina e
  lista filtrável.
- **Planta × detalhe × documento** (`conceitos/tipos_prancha.json`): detalhe e documento ficam só na aba Projeto;
  as 34 pranchas do mapa saem como planta e 17 plantas ainda fora do mapa ficam listadas.
- **Escavação e reaterro** (`camadas/escavacao.py`, `conceitos/escavacao.json`): base das estruturas, cota de fundo
  por OCR das marcas de nível, crista desenhada, talude 1,5H:1V, MDS em cota; edificações (filtro morfológico
  progressivo + ExG) são parede. Foz: 8 cavas, 8 769 m³ de escavação e 5 558 m³ de reaterro (estimativa).
- **Valas** (`camadas/valas.py`, `conceitos/valas.json`): cada metro de tubo em pista, calçada ou lote pela posição
  no desenho (divisas, meio-fio × alinhamento, quadras) ou pela ortofoto (ETA), com a superfície final da
  urbanização; demolição, recomposição e volume de vala por rede. Camada no mapa colorida por classe.
- `supressao`: `terreno`, `mds_na_grade`, `rasterizar` e `poligonos` passam a públicos (reuso, sem duplicata);
  `mascaras_vegetacao` devolve `valido`.
- Teste de interface: aba Projeto (soma do inventário, filtro de plantas, cavas, valas e cor por classe).

## 0.6.0 — 2026-10-28 · Foz, rodada 6: adutoras completas, escopo × desenho e sondagens no 3D
- Malha com rótulo errado no próprio desenho: `georef_prancha.hipoteses_malha` (afins discretas com a escala
  declarada) + `escolher_por_continuidade` (coincidência do tubo com a folha vizinha na área comum). AAT00-05 e -06
  entram no mapa: 34/34 pranchas. Rótulos errados identificados (05: 744200 → 744000; 06: 744000 → 743800).
- Escopo × desenho (`obra.tubo_contrato_x_desenho`): o tubo principal de cada tabela do contrato contra o eixo
  medido na prancha georreferenciada que a tabela aponta; 14 pranchas, AAT06 a +0,2–0,4 %. Painel na aba Etapas &
  escopo e linha em cada tabela.
- Sondagens no 3D (`obra.sondagens_3d`): perfil de cada furo em cota, camadas confirmadas na cor do solo, trecho sem
  limite confirmado em cinza, NA em azul.
- Janela da malha "só na moldura" = a moldura.

## 0.5.0 — 2026-10-28 · Foz, rodada 5: malha de coordenadas, adutoras e escopo sem preço
- Georreferência pela **malha de coordenadas impressa** (`georef_prancha.registrar_malha`): linhas da grade,
  rótulos em traço SHX lidos por OCR (tesseract), voto por família de paralelas e descarte de leitura errada pelo
  resíduo; modo "rótulos" para malha só na moldura. 15 folhas com resíduo de 0 a 29 cm; os marcos E/N da AAT00-01
  caem a 0,20 e 0,23 m.
- **Correção de escala**: a f004 (e 9 irmãs) estava 7,9 % grande desde a rodada 3. Agora é irmã da GEOPLANTA
  (sondagens topográficas); urbanização e drenagem vão pela malha e batem com a cadeia em 0,15–0,20 m.
- Adutoras no mapa (Hidráulica › Adutoras): AAT00 01–04, AAT01, AAT02 e AAT06 009–014, recortadas à janela da
  planta; AAT00-05/06 pendentes (malha incoerente no desenho).
- `pdf_cad.quantitativos` mede o eixo de polilinha com largura (`eixo_faixa_m`): tubo da AAT06 a +0,2–0,4 % da
  tabela da folha.
- **Escopo sem preço**: extrator, `obra.etapa_escopo` e HTML sem valor, total, montagem ou fornecedor; só itens,
  quantidades por etapa, contagens e alertas.
- **Cadastro de materiais Sanepar** (`referencias/sanepar/catalogo_materiais.jsonl.gz`, 40.371 materiais, só
  especificação): cada código do escopo ganha descrição, unidade, norma, situação, DN/PN e marcas; 702 de 882 itens
  de Foz no cadastro.

## 0.4.0 — 2026-10-28 · Foz, rodada 4
- Cota absoluta: `sfm.ajustar_vertical` / `aplicar_vertical` ajustam o plano z → cota às cotas de boca das SPT
  (rejeição robusta, validação cruzada deixa-um-fora); nuvem, câmeras, 3D e GeoTIFF do MDS passam a cota.
  Foz: 12 furos, 0,23 m.
- Quantitativos do desenho por layer CAD (`pdf_cad.quantitativos`, `decodificar_pacote`): comprimento (m) e área (m²)
  pela afim pt → UTM, exibidos na aba Pranchas.
- `mosaico.py` sem classe nem dataclass: `carregar → casar → ajustar_global → renderizar` com estado em dict;
  `executar(pasta, saida, ...)` devolve o relatório com `epsg`. Mesmos números no Foz.
- Marcos destruídos identificados (RN07A a 22 m, RN2 a 2,06 km).

## 0.3.0 — 2026-10-27 · Foz, rodada de qualidade
- 20/20 pranchas georreferenciadas: CAD × CAD por SIFT + RANSAC (`georef_prancha.registrar_cad`), critério rígido e
  conferência visual; recorte automático do mapa à área do levantamento.
- Supressão vegetal estimada por etapa (`supressao.py`); recorte classificado de intervenções no HTML.
- Disciplinas Civil (fundação, estrutura, arquitetura, urbanização, drenagem, pavimentação, terraplenagem),
  Hidráulica, Mecânica e Elétrica para cada prancha e layer (`conceitos/disciplinas.json`).
- 4D: cronograma de referência a partir dos marcos MI01–MI06 do TR, elementos por atividade e curva S calculados no
  Python.
- SIG: GeoTIFF, GeoPackage por layer CAD (11 s em vez de 514 s) e `.points` do QGIS.
- Referências geodésicas Sanepar/IBGE/municipal/RBMC e camada de marcos perto da obra.
- Estilo: regras em `conceitos/*.json`, sem dataclass, `metadados()` com bibliografia, aferição em `scripts/afericao.py`;
  módulos rasos fundidos (exif → mosaico, registro → georef_prancha, folha/disciplinas → pdf_cad).
- Escopo: totais calculados no Python; quantidades com cara de data do Excel e unidade divergente viram alerta.

## 0.2.0 — 2026-10-27 · Foz, primeira entrega
- SfM (pycolmap), ortofoto verdadeira, controle absoluto pelas sondagens, pranchas vetoriais por layer CAD,
  escopo por etapa, sondagens e 3D no visualizador.

## 0.1.0 — 2026-10 · Irati
- Mosaico de drone, folha raster por cor, visualizador HTML.
