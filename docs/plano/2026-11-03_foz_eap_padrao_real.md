# Foz: EAP padrão alinhada com a primeira passada de dado real (2026-11-03)

Sem nenhum valor monetário: só descrições, unidades de medida e quantidades físicas.

## O que foi rodado

- Fonte: planilha do contrato Sanepar 211/26 (Foz do Iguaçu), `dados/foz/orcamento/principal.xlsx`; a pasta `dados/` é
  link para dados locais e não entra no git.
- Cadeia: `orcamento_sanepar.main` gera `escopo_itens.csv` (1.002 linhas: 923 de MATS E EQUIP e 79 de CUSTO CIVIL) →
  `evidencias.de_planilha` → `consolidar` → `eap_padrao.preencher` para os dois tipos de obra (Foz é mista:
  U1 ETA Vila C, localizada; U2 adutora de água tratada, linear).
- "Antes": worktree temporária do commit e8c9cac (0.52.0). "Depois": esta branch. Mesmo `escopo_itens.csv`, mesmo
  `exemplos/foz/obra.json`.

## Estrutura Sanepar encontrada na aba CUSTO CIVIL

- Duas unidades, cada uma aberta pela linha de administração local: "UNIDADE 1 - ETA Vila C" e
  "UNIDADE 02 - AAT06 / ANEIS". A linha "ADMINISTRAÇÃO LOCAL DE OBRA - ALO" é um título e abaixo vem o serviço
  "ADMINISTRAÇÃO LOCAL DA OBRA", em MÊS: 18 na unidade 1 e 12 na unidade 2.
- Nível 1 (frentes) da unidade 1: 1 interligações / água bruta / água potável; 2 aplicações de produtos químicos e
  sistemas de coleta; 3 reforma do edifício de lodo / guarita / sistema pneumático; 4 infraestrutura dos sistemas de
  microareia 360 e 600 L/s; 5 sistema de microareia 360 L/s; 6 sistema de microareia 600 L/s; 7 válvulas e comportas;
  8 instalações elétricas. Da unidade 2: 1 adutora AAT 06; 2 adutora AAT 02 Vila A; 3 adutora Vila C.
- Nível 2 (títulos) que reaparecem e foram copiados para `titulos_sanepar`: SERVIÇOS PRELIMINARES, ÁGUA POTÁVEL,
  BLOCOS DE ANCORAGEM, BLOCOS DE APOIO, MATERIAIS EQUIPAMENTOS, SISTEMA PNEUMÁTICO, REFORMA EDIFÍCIO LODO, GUARITA,
  ABRIGOS, URBANIZAÇÃO, RECOMPOSIÇÃO DE PAVIMENTO, SERVIÇOS FINAIS.
- Em MATS E EQUIP, 63 das 1.002 linhas de escopo estão sem quantidade (planilha de licitação ainda não preenchida).

## Contagens antes × depois (cadeia real de Foz)

| Medida | Antes (e8c9cac) | Depois |
|---|---|---|
| Evidências | 648 | 651 |
| Fatos | 40 | 35 |
| Fatos por status | fonte única 36 · só menção 4 | fonte única 31 · só menção 4 |
| ALO (U1 · U2) | sem item | 18 mês · 12 mês |
| Obra localizada: folhas | 42 (17 preenchidas · 25 a preencher; 40,5 %) | 43 (14 preenchidas · 29 a preencher; 32,6 %) |
| Obra linear: folhas | 30 (6 preenchidas · 24 a preencher; 20,0 %) | 32 (6 preenchidas · 26 a preencher; 18,8 %) |

A queda de fatos preenchidos não é perda: eram classificações erradas que enchiam folhas por engano (29 grades de
piso em laje de piso, 4 em parede, 3 em viga, 8 de vala em escavação de cava, 2 em calçada). Folhas da obra localizada que
deixaram de estar preenchidas: OP.02.01, OP.02.02 (a vala passou para OP.02.06), OP.04.01, OP.04.02 e OP.04.04; ganhou
OP.00.01 (ALO). Na obra linear ganharam OL.00.01 e OL.07.04. As de estrutura voltam a "a preencher" até as pranchas
serem medidas ou o memorial ser lido.

## Achados e correções (movimento por linha da planilha, antes → depois)

| Linhas | Frase (resumo) | Antes | Depois |
|---|---|---|---|
| 29 | "GRADE DE PISO PRFV OU ACO INOX 316 VAO 0,4 X 0,4M GR 0,6X0,6M" | CIV.EST.PIS | CIV.ACA.ACB |
| 8 | "ESCAVAÇÃO, ESCORAMENTO, ASSENTAMENTO, REATERRO E REMOÇÃO DE PAVIMENTOS - FD DN 150" | GEO.MOV.ESC | GEO.MOV.VAL |
| 6 | "MEDIDOR DE VAZAO ELETROMAGNETICO … PN 10 DN 300" | sem item | ELE.FOR.INS |
| 4 | "VALVULA ESFERA 3 VIAS DUPLA UNIAO …" e "Válvula Direcional inline 5/2 vias monoestável" | CIV.PAV.REC ("via") | HID.TUB.VAL |
| 4 | "TORNEIRA PAREDE BICA RETA …" e "união passa-muro" | CIV.EST.PAR | sem item |
| 3 | "TALHA MANUAL DE CORRENTE COM TROLEY … MONOVIA VIGA I" | CIV.EST.VIG | HID.EQP.EQU |
| 2 | "TAMPA PLASTICA PARA REGISTRO PASSEIO - TPP PADRAO SANEPAR" | CIV.PAV.CAL | HID.TUB.VAL |
| 2 | "ADMINISTRAÇÃO LOCAL DA OBRA" | sem item | GER.PRE.ALO |
| 1 | "REVESTIMENTO COM ASFALTO (TERCEIRIZADO)" | CIV.ACA.ACB | CIV.PAV.REC |
| 1 | "HIDROMETRO ULTRASSONICO Q3 400,0 M3/HORA … DN200 POL 8" (macromedidor) | HID.TUB.LIG | ELE.FOR.INS |
| 1 | "Central de Preparação de ar comprimido, com secador por refrigeração" | ELE.FOR.INS | HID.EQP.EQU |
| 1 | "Plaquetas de identificação dos quadros … via rebite ou parafuso" | CIV.PAV.REC ("via") | sem item |
| 1 | "MARCADOR OVAL / PORTA MARCADOR (identificação de tubos)" | CIV.ACA.ACB (porta) | HID.TUB.RED |

Dois defeitos de regex achados ao escrever os testes e corrigidos no `eap_geral.jsonl`: `MEDIDORES?` e `MARCADORES?`
significam "MEDIDORE" e "MARCADORE" com S opcional, então "medidor de vazão" e "porta marcador" não casavam como se
queria; viraram `MEDIDOR(?:ES)?` e `MARCADOR(?:ES)?`. "Porta de madeira", "porta de alumínio" e "porta" sozinha
continuam esquadria (teste novo).

Mudanças de conceito: item `GER.PRE.ALO`; poço de visita em água e esgoto; `HID.TUB.LIG` restrito à ligação;
`ELE.FOR.INS` também linear; folha `OL.07.04`; etapa 00 e `titulos_sanepar` no padrão.

## Etapa pelo título da planilha

Segunda passada sobre a mesma planilha: o título de etapa da aba CUSTO CIVIL ("SERVIÇOS PRELIMINARES", "URBANIZAÇÃO"…)
agora indica a etapa do padrão (regra em `docs/EAP.md` §9.1). Sem preço: as colunas F e G não são lidas.
`escopo_itens.csv` foi regenerado numa pasta temporária (o de `dados/` não foi tocado).

| Medida | Antes | Depois |
|---|---|---|
| Linhas de CUSTO CIVIL (de 79) com `titulo_etapa` | sem a coluna | 36 (14 sem item, 22 com item) |
| Evidências · fatos | 651 · 35 | 651 · 35 (a classificação não mudou) |
| Evidências com título no localizador | 0 | 22 |
| Obra localizada: folhas preenchidas | 14 de 43 (32,6 %) | 14 de 43 (32,6 %) |
| Obra linear: folhas preenchidas | 6 de 32 (18,8 %) | 6 de 32 (18,8 %) |

Linhas por título de etapa: SERVIÇOS PRELIMINARES 11, RECOMPOSIÇÃO DE PAVIMENTO 8, BLOCOS DE ANCORAGEM 4, BLOCOS DE APOIO 3,
SERVIÇOS FINAIS 3, URBANIZAÇÃO 3, ADMINISTRAÇÃO LOCAL DE OBRA - ALO 2, ÁGUA POTÁVEL 1, MATERIAIS EQUIPAMENTOS 1. As outras
43 linhas estão sob título de trecho (ENTRADA DA ADUTORA, INTERLIGAÇÃO…, SAÍDA DO LODO…) ou sem título, e o título de trecho
encerra a etapa anterior. Os três "MEDIDORES DE VAZÃO" (linhas 37, 57 e 71) ficariam sob RECOMPOSIÇÃO DE PAVIMENTO se a
regra fosse só "último título de etapa"; como são bloco próprio da planilha, encerram a etapa (decisão declarada).

**Etapas citadas no contrato** (linhas sem item sob o título; sem quantidade). Todas na obra localizada (U1); a unidade 2
(linear) só tem a ALO como linha de CUSTO CIVIL, então nenhuma etapa linear foi citada.

| Etapa | Título | Linhas sem item | Exemplos |
|---|---|---|---|
| OP.01 Serviços preliminares | SERVIÇOS PRELIMINARES | 4 | sondagem para execução da rede; pesquisa e remanejamento de interferências; locação de caçamba para entulho |
| OP.07 Instalações hidráulicas e OP.08 Equipamentos | MATERIAIS EQUIPAMENTOS (título nas duas) | 1 | fornecimento e montagem hidromecânica de materiais e equipamentos |
| OP.10 Urbanização e pavimentação | URBANIZAÇÃO | 1 | execução de guia de concreto pré-moldada |
| OP.12 Serviços finais | SERVIÇOS FINAIS | 1 | lavagem de rede |

**Avisos "item fora da etapa do título": nenhum.** As 22 linhas com item caem todas numa folha da etapa do título (a):
topografia e mobilização em OP.01, supressão e raspagem em OP.01.04, recomposição e pavimento em OP.10, limpeza e cadastro
em OP.12, ALO em OP.00. Nada a corrigir na classificação por este caminho; nenhuma correção foi feita.

Observações que a passada deixou, sem mudar nada (candidatos para decisão humana):

- **Título sem etapa equivalente no tipo da unidade.** U1 é obra localizada, mas BLOCOS DE ANCORAGEM (4 linhas, sem item),
  BLOCOS DE APOIO (3, sem item) e ÁGUA POTÁVEL (1, vala em PVC DN 25) só constam em `titulos_sanepar` das etapas da obra
  linear (OL.04, OL.03 a OL.05). Nessas linhas o título não age. Se a Sanepar usa os mesmos blocos e a mesma água potável
  dentro da ETA, falta listar o título numa etapa de `obra_localizada` (fundações ou instalações hidráulicas); fica para o
  mantenedor, porque `conceitos/eap_padrao.json` não era escopo desta tarefa.
- **Sem item sob título de etapa.** "SONDAGEM PARA EXECUÇÃO DA REDE", "PESQUISA E REMANEJAMENTO DE INTERFERÊNCIAS" e "LOCAÇÃO
  DE CAÇAMBA PARA DESTINAÇÃO DE ENTULHO" (preliminares), "EXECUÇÃO DE GUIA DE CONCRETO PRÉ-MOLDADA" (urbanização) e
  "LAVAGEM DE REDE" (serviços finais; parece desinfecção e limpeza da rede, `GER.CTL.DSF`, mas o termo exige tubulação ou
  adutora e não cobre "lavagem de rede") não têm item na EAP. Não foi alterado: "lavagem de rede" não é erro claro.

## D10 e D11 na cadeia real (ciclo de 04/11/2026)

Plano: `docs/plano/2026-11-04_wbs_d10_d11.md`. Mesma planilha, `escopo_itens.csv` regenerado em pasta temporária (o de
`dados/` não foi tocado), sem preço. Antes = `main` 4090759; depois = esta entrega, com a declaração
`eap_padrao.trechos_lineares` (U1, "ÁGUA POTÁVEL", sistema `AGUA_POTAVEL`) no `exemplos/foz/obra.json`. Os números abaixo
vêm do caminho real (`evidencias._registros`, que torna NaN em `null`): as tabelas das seções anteriores deste relatório
usaram `to_dict` direto, que tratava o valor vazio dos fatos "só menção" como número e inflava as folhas preenchidas
(14 e 6 contra 10 e 6 aqui); a comparação desta seção é consistente entre antes e depois.

| Medida | Antes (4090759) | Depois |
|---|---|---|
| Evidências · fatos | 651 · 35 (fonte única 31 · só menção 4) | 655 · 37 (fonte única 31 · só menção 6) |
| Obra localizada: folhas | 43 (10 preenchidas · 4 só menção · 29 a preencher; 23,3 %) | 44 (9 preenchidas · 6 só menção · 29 a preencher; 20,5 %) |
| Obra linear: folhas | 32 (6 preenchidas · 25 a preencher · 1 fora do escopo; 19,4 %) | 32 (7 preenchidas · 24 a preencher · 1 fora do escopo; 22,6 %) |
| Água potável (622 m) | `OP.02.06`, fato `U1.*.GEO.MOV.VAL` | `OL.03.01`, fato `U1.AGUA_POTAVEL.GEO.MOV.VAL`; uma vez só, na vista linear |
| `OP.02.06` (valas internas da U1) | preenchida: Escavação 622,00 m | só menção (sem quantidade na planilha) |
| `OP.07.04` (D10, folha nova) | não existia | só menção (4 linhas de bloco de ancoragem sem quantidade) |
| Avisos de `montar` (fora o aviso de premissa) | nenhum | nenhum (nenhuma linha declarada sem folha linear que a receba) |
| Etapas citadas no contrato | OP.01 (4) · OP.07 (1) · OP.08 (1) · OP.10 (1) · OP.12 (1) | OP.01 (4) · OP.07 (4) · OP.08 (1) · OP.10 (1) · OP.12 (1); obra linear: nenhuma |
| Itens fora do padrão (`validar`) | 0 | 0 |

- **D11.** A linha 127 do CUSTO CIVIL (ÁGUA POTÁVEL, vala em PVC DN 25, 622 m) foi a única que a declaração tocou: o código
  passou de `U1.*.GEO.MOV.VAL` para `U1.AGUA_POTAVEL.GEO.MOV.VAL` antes do `consolidar`, e a folha `OL.03.01` (serviço
  `escavacao`) recebe os 622 m. Os 622 m aparecem uma vez só: nenhum outro fato de Foz leva esse valor. As outras 7 linhas de
  vala da U1 (FD DN 1000 nas linhas 16, 30 e 50, DN 200, DN 300 e DN 150 nas linhas 99 e 113) continuam na vista localizada,
  em `OP.02.06`, todas sem quantidade na planilha. O pedido do ciclo falava em "8 linhas FD DN 150": na planilha são 7 linhas
  de FD (DN 1000, 200, 300 e 150) e 1 de PVC DN 25; as de DN 150 são as linhas 99 e 113.
- **D10.** As 4 linhas "BLOCOS DE ANCORAGEM" (linhas 23, 92, 106 e 120) passaram a ter item (`HID.TUB.ANC`, serviço
  `bloco_ancoragem`) e, sem quantidade, formam o fato "só menção" que deixa `OP.07.04` em "só menção". As 3 linhas
  "BLOCOS DE APOIO" (linhas 43, 63 e 77) continuam sem item (a descrição é só o título, sem tubulação, curva ou peça), e agora
  contam como etapa `OP.07` citada no contrato, porque o título está em `titulos_sanepar` dela. Isto resolve a primeira
  observação da seção "Etapa pelo título" (título sem etapa equivalente na obra localizada) para ANCORAGEM e APOIO; a
  ÁGUA POTÁVEL ficou resolvida pela D11, e não por título na obra localizada.
- **Não mudou.** Os sistemas `rede_eta` da U1 (AB_ENTRADA, LODO_*) e `U1.LINEARES.*` seguem na vista localizada; PV para
  água, ALO, macromedidor e "lavagem de rede" (decisões pendentes) não foram tocados.

## Verificações

- Roteiros de ataque da IA (`ataques`, `r3_ataques`, `r3_b`, `rev_bloco`, `rev_bloco2`): saída idêntica antes e depois
  (nenhuma conferência de citação mudou).
- Hash de `camadas.referencia` inalterado (0602c637…ac6de).
- Ciclo D10/D11 (04/11/2026): os mesmos cinco roteiros de ataque com saída idêntica entre 4090759 e esta entrega; hash de
  `camadas.referencia` inalterado; nenhum golden regenerado.

## O que falta

- **Quantidades em branco** na planilha de licitação (63 linhas de escopo sem quantidade): ficam como "só menção" até
  a Sanepar preencher.
- **Edital e termo de referência** de Foz: ainda não lidos; a ALO e a duração das etapas podem ter exigência própria.
- **Pranchas** (geometria) das unidades: as folhas de estrutura, fundações e movimento de terra só enchem com a medição
  das pranchas ou com leitura de memorial.
- Conferir a numeração das etapas com o MOS Sanepar (continua premissa).
- "Marcador oval / porta marcador" cai em tubulação (casa "tubos"): resíduo aceito, sem item próprio de identificação.
