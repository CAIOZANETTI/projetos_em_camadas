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

## Verificações

- Roteiros de ataque da IA (`ataques`, `r3_ataques`, `r3_b`, `rev_bloco`, `rev_bloco2`): saída idêntica antes e depois
  (nenhuma conferência de citação mudou).
- Hash de `camadas.referencia` inalterado (0602c637…ac6de).

## O que falta

- **Quantidades em branco** na planilha de licitação (63 linhas de escopo sem quantidade): ficam como "só menção" até
  a Sanepar preencher.
- **Edital e termo de referência** de Foz: ainda não lidos; a ALO e a duração das etapas podem ter exigência própria.
- **Pranchas** (geometria) das unidades: as folhas de estrutura, fundações e movimento de terra só enchem com a medição
  das pranchas ou com leitura de memorial.
- Conferir a numeração das etapas com o MOS Sanepar (continua premissa).
- "Marcador oval / porta marcador" cai em tubulação (casa "tubos"): resíduo aceito, sem item próprio de identificação.
