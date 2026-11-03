# Build real de Foz (ETA Vila C): a memória espacial com dados verdadeiros

Pedido do Caio (02/11/2026): "pode seguir com o build real de Foz", e depois "pode seguir até o PR". Método das rodadas
anteriores: o Opus gerencia, o Haiku faz o trabalho braçal (ingestão do Drive), cada achado é corrigido com teste,
seguido de `vcm balanco`, aceite do Fable e PR.

## Objetivo

Rodar `python -m camadas.obra exemplos/foz/obra.json` com os dados reais de Foz e conferir a memória espacial: a
paridade das gavetas, as cavas, a conciliação com a EAP codificada e a aba EAP no HTML. O que falhar fica registrado
com o motivo, sem ser escondido.

## Etapas

| # | Etapa | Quem | Estado |
|---|---|---|---|
| E1 | Ingestão do Drive: inventário, PDFs, fotos do drone e planilha | Haiku | feito: 259 PDFs (711 MB, todos com `%PDF`), 13 fotos, planilha; 0 falhas |
| E2 | Insumos derivados: sondagens pelo leitor de laudo, escopo pela planilha | Opus | feito: 23 furos lidos por código; escopo com 1 002 itens (923 MATS E EQUIP + 79 CUSTO CIVIL) |
| E3 | Build completo até o HTML | Opus | feito na 6ª execução (0.42.0) e refeito com as correções da revisão: `foz-vilac_camadas_v0.43.0_*.html` (23 MB) |
| E4 | Conferência, relatório e PR | Opus; Fable | este documento |

## Resultado do build

| Peça | Resultado |
|---|---|
| Sondagens | 23 furos (16 SP + 7 complementares "A"), E/N em SIRGAS 2000 / UTM 22S, NA de 7,50 a 9,00 m, camadas; **NSPT deste layout não é lido** |
| Pranchas | todas georreferenciadas pela malha impressa (resíduo máx. 0,29 m) |
| Controle vertical | plano em 13 pontos, validação cruzada 0,37 m (SP16 e SP07 descartados, SP12 sem nuvem) |
| Cavas | 7 cavas, 8 585,6 m³ de escavação e 5 462,7 m³ de reaterro |
| Valas das redes | AAT00, AAT01, AAT02, AAT06, drenagens DN400 e DN300 |
| Inventário | 259 arquivos: 201 com extração completa e 58 com parcial; fichas em lote: 125 desenhos, 0 erros, 2 232 balões ligados a item |
| Gavetas | 30 objetos, 81 fatos (todos de código, 0 de IA), 75 serviços, **0 erros de conferência e 0 diferenças de paridade** |
| Conciliação com a EAP codificada | escavação `U1.ETA.GEO.MOV.ESC` 8 585,6 = 8 585,6 m³ e reaterro `U1.ETA.GEO.MOV.REA` 5 462,7 = 5 462,7 m³, situação "confere" (diferença 0). **Não é uma validação do volume**: os dois lados vêm do mesmo `camadas.escavacao` (ver "Leitura honesta" abaixo). As 6 redes em `HID.TUB.RED` (m) são medidas só pela codificada: "fora das gavetas" |
| Código da EAP | os 75 serviços saem com o código completo (ex.: `U2.AAT06.GEO.MOV.VAL`, `U1.DREN_DN400.CIV.PAV.REC`); `area_cava_m2` (7) fica "sem código", como decidido na rodada 6 |
| Evidências | 1 574 evidências, 116 fatos, 39 conflitos |

## Achados que só o dado real mostrou (cada um corrigido com teste)

1. **Laudo Geoazimute.** O leitor de laudo esperava uma tabela de coordenadas e camadas "de X a Y". Em Foz:
   - a coordenada vem escrita "Sonda SP01: N = …; E = …", com N antes de E;
   - os furos complementares (SP 02A) têm a coordenada na própria folha do perfil;
   - o NA fica no alto da folha, antes do id do furo;
   - as camadas vêm em bloco, de baixo para cima;
   - o NA final está na frase de conclusão.

   Correção em `geotecnia`: coordenada rotulada, coordenada da folha, página de um furo só, camadas em bloco e NA pela
   conclusão. O NSPT agora exige espaço entre os números: antes "13,50" virava 13,5 m com 0 golpe. Resultado: a etapa
   sondagens passou de **IA a código** em `pdca/determinismo.json` (o `executor_sondagens` do obra.json virou
   "código").
2. **Sem `estacas.csv` o build caía no fim.** As fichas de estrutura sem arquivo de âncoras agora são puladas, com o
   motivo no log.
3. **A planilha do contrato no Drive não tem a aba "Obras Lineares".** Essa aba vem do protótipo da Giselle (30/10),
   que não está no Drive. O build caía em três lugares: `obras_lineares`, `extrair_gavetas` e `evidencias`. Os três
   passaram a usar `obras_lineares.tem_aba`, e o build segue sem os trechos da planilha.
4. **Serviço sem item.** `classificar` devolve `PACOTE.*` (ex.: a laje de fundo vira `CIV.EST.*`), e o schema da
   evidência recusa `*` no item, o que derrubava o build. A primeira correção afrouxou o schema, mas colidia com a
   decisão da `main` ("'*' só vale em unidade e sistema", teste adversarial da IA). A correção final mantém o schema:
   a linha de planilha ou de texto que só casa um pacote não vira evidência.
5. **Unidade e sistema.** Com os dados reais, os 7 objetos das gavetas saíam com "unidade e sistema não definidos", e
   as cavas, iguais à codificada até o decímetro, apareciam como "só na EAP codificada".
   - A rede de vala ganhou o fato `local`, que é o seu nome (AAT06 → u2/AAT06; "ETA drenagem DN400" → u1/DREN_DN400).
   - Foz declara `unidade_sistema_padrao` u1/ETA, que é o `sistema_geral` de `unidades_construtivas.json`, para onde
     a regra manda a cava sem estacas.

## Leitura honesta da conciliação (revisão do Fable)

O "confere" das cavas é **circular**. As gavetas usam o `saida_gavetas` de `escavacao.etapa`, e a EAP codificada soma o
`escavacao_m3` que `construtivos` grava na feature da cava, ou seja, o mesmo cálculo. A diferença 0 prova só duas
coisas:
- as duas trilhas leem o mesmo resultado sem perda;
- as duas atribuem o mesmo sistema, ETA. A codificada faz isso por "sem estaca dentro da cava", porque falta o
  `estacas.csv`; as gavetas, pelo padrão u1/ETA.

Se o `estacas.csv` aparecer, a codificada pode mover uma cava para FILTROS/ACT600 e as gavetas continuarão em ETA. A
conciliação passará a acusar "só nas gavetas" / "só na EAP codificada" sem que o volume mude. A conferência
independente do volume é contra o item de escavação do CUSTO CIVIL da planilha do contrato. Ela fica como pendência.

## O que falta (pendências para o Caio)

- **Conferência independente do volume das cavas** contra o item de escavação do CUSTO CIVIL, e o mesmo sistema nas
  duas trilhas quando o `estacas.csv` existir.

- **A planilha do protótipo com a aba "Obras Lineares"**, que não está no Drive. Sem ela, os trechos de tubo da ETA não
  entram nas gavetas nem na paridade OL.
- **A origem do `estacas.csv`**, lido por IA numa sessão anterior (`pdca/determinismo.json`, "origem exata a
  confirmar"). Sem ele, as fichas mod01/act01/act02 não são lidas, e as cavas vão para o sistema geral pela regra
  `cava_maioria`.
- **Os setores reais da ETA** no obra.json, para a EAP por setor.
- **NSPT do layout Geoazimute**: a tabela de golpes está no desenho do perfil; o texto não basta.
- **A qualidade das cavas**:
  - 56 bases sem marca de cota de fundo a ≤ 3 m;
  - 1 marca fora da faixa do terreno;
  - as cavas C01, C03, C05 e C06 estão na borda do levantamento.
- **A listagem do Drive está incompleta**: há pastas não expandidas e o `LC2112026EDITAL_ELEMENTOS.ZIP` (629 MB) não
  foi baixado.
- **`tests/test_lineares.py::test_ler_perfil_ocr`** falha neste ambiente também na `main`, por causa do OCR do
  tesseract local. No CI ele é pulado, porque lá não há tesseract.

## Custo

| Quem | Tarefa | Tokens | Tempo |
|---|---|---|---|
| Haiku | E1, ingestão do Drive | 454 282 | 15,7 min |
| Opus (gerente) | E2 a E4, os 5 achados e as correções | sessão principal | ~6 execuções do build (o 1º com SfM: 15 min; os seguintes de 7 a 27 min) |

## Revisão do Fable (1º aceite: REVISAR)

| # | Achado | Gravidade | Correção |
|---|---|---|---|
| 1 | "Página de um furo só é toda dele" roubava a continuação do perfil anterior e a prosa acima do cabeçalho, no layout de tabela | bloqueante | a regra vale só para a folha em bloco (com `TÉRMINO`); testes da continuação na página seguinte e da prosa antes do perfil |
| 2 | Etapas puladas só no terminal | importante | o `_log` do build guarda o que tem "(pendência" e o build grava em `dados["pendentes"]["Build (etapas puladas)"]`, mostrado no HTML |
| 3 | "Confere" das cavas é circular | importante | relatório corrigido (acima); conferência independente fica como pendência |
| 4 | Padrão u1/ETA silenciava qualquer objeto sem chave | importante | `unidade_sistema_padrao.classes` (Foz: só `conjunto_cavas`); uma rede nova sem chave volta a ser pendência |
| 5 | Profundidade sem descrição no meio do bloco fundia camadas | menor | o bloco devolve [] (nada é inventado); só a marca final do NA pode ficar sem descrição |
| 6 | Páginas sem cabeçalho vão ao último furo citado | menor | herdado da `main`, sem efeito em Foz; registrado |

Também registrado: os `nao_lidos` do leitor de laudo não chegam ao HTML (hoje é `[]` em Foz).
