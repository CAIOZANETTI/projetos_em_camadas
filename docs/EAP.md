# EAP (WBS) como linha mestra do projeto em camadas

> Pedidos do Caio (30/10/2026):
> - "a EAP é a linha mestra, os projetos são as evidências, e o georreferenciamento é o jeito de ver o projeto no
>   local";
> - escopo água × esgoto e o cadastro de 40 mil materiais para balizar os serviços e ver se o edital os considera;
> - banco de palavras para escavação, forma, concreto e armadura, com evidência no edital e no projeto;
> - um esquema formal (JSON/JSONL) que sirva de regra para um loop em todos os documentos;
> - registrar evidências conflitantes (300 estacas no projeto × 250 em outro documento) e mostrar que várias
>   evidências concordantes reforçam o fato;
> - dicionário de sinônimos, abreviações e unidades;
> - serviços associados que nenhum documento cita (bloco → escavação e reaterro; laje → escoramento; rede →
>   escavação, reaterro, demolição e recomposição de pavimento), com fórmulas tendo o elemento como base de cálculo.

## 1. O que o repositório já tinha

| Peça | Onde | Papel na EAP |
|---|---|---|
| Unidade (localizada × linear) → sistema → elemento | `camadas/construtivos.py`, `conceitos/unidades_construtivas.json` | os dois primeiros níveis da EAP e os elementos medidos |
| Classe de layer CAD (estaca, bloco, pilar, viga, parede, tubo…) | `conceitos/elementos.json` | evidência gráfica do item |
| Grupo/subgrupo de disciplina da prancha | `conceitos/disciplinas.json` | prancha → pacote da EAP |
| Obra linear × localizada pelo nome do PDF | `conceitos/tipos_prancha.json` | prancha → unidade |
| Escopo do contrato por etapa, sem preço | `camadas/orcamento_sanepar.py` (`escopo_itens.csv`) | planilha do edital, linha a linha |
| Cadastro de materiais Sanepar (40 371 materiais) | `referencias/sanepar/catalogo_materiais.jsonl.gz` | baliza os itens hidráulicos e elétricos |
| Premissas de vala (NBR 12266) | `conceitos/valas.json` | base das fórmulas dos serviços associados das redes |
| Georreferência, ortofoto, 3D, aba Obra | `georef_prancha`, `sfm`, `visualizador.html` | onde o elemento está e onde a EAP vai aparecer |

## 2. Esquema geral: os arquivos que são a regra

```
conceitos/
  eap.json                   hierarquia: disciplina → pacote; escopos (água, esgoto); prancha → pacote
  eap_geral.jsonl            EAP GERAL — um item por linha: escopo, tipo de obra, termos de busca, serviços admitidos,
                             filtro no cadastro de materiais, classes construtivas, layers, medições
  servicos.jsonl             banco de serviços: escavação, reaterro, forma, concreto, armadura, escoramento… (termos)
  sinonimos.json             abreviações (EST. → ESTACA), sinônimos (CIMBRAMENTO → ESCORAMENTO), unidades e conversões
  dimensoes.json             tipos de elemento → dimensões padronizadas (V, A_forma, A_fundo…) e derivados; vala
  servicos_associados.jsonl  serviço que a execução exige: tipos, condição, destino, premissas, fórmula
  evidencia.schema.json      JSON Schema de uma evidência (uma linha do registro)
  unidades_construtivas.json unidades (obra localizada/linear, escopo) e sistemas (ACT600, AAT06…)
```

Linha de `eap_geral.jsonl` (estacas):

```json
{"codigo": "GEO.FUN.EST", "nome": "Estacas", "escopo": ["agua", "esgoto"], "obra": ["localizada"], "prioridade": 20,
 "termos": "\\bESTACAS?\\b(?!\\s*\\d+\\s*\\+)…", "servicos": ["arrasamento", "concreto", "armadura"],
 "construtivos": ["estaca"], "layers": ["estaca"], "catalogo": null,
 "medicoes": [{"grandeza": "quantidade", "unidade": "un", "regra": "contagem"}, …]}
```

O termo exclui "ESTACA 12+10,00": em obra linear, "estaca" é o estaqueamento do perfil, não uma fundação.

## 3. Codificação

`UNIDADE.SISTEMA.DISCIPLINA.PACOTE.ITEM`. O código mnemônico é a chave estável. O número (`1.3.1.1.1`) é só a ordem
de exibição.

Quando o documento não diz um segmento, ele fica `*`. Por exemplo, `U1.*.GEO.FUN.EST` são as estacas da U1, de
sistema não dito, e `U1.*.CIV.EST.*` é forma sem elemento dito.

```
U1                         Unidade 1 — ETA Vila C (obra localizada, água)
└─ U1.ACT600               Actiflo 600 L/s (sistema de microareia)
   ├─ .GEO.FUN             Fundações ─ EST estacas · BLO blocos · CON contenções
   ├─ .GEO.MOV             Movimentação de solo ─ ESC escavação · REA reaterro · VAL vala · SUP supressão
   ├─ .CIV.EST             Estruturas de concreto ─ PIS piso/laje · BAL baldrame · VIG viga · PIL pilar · PAR parede
   ├─ .CIV.PAV             Pavimentação ─ REC demolição e recomposição
   ├─ .HID.EQP             Equipamentos ─ EQU fornecimento e montagem
   ├─ .HID.TUB             Tubulações ─ RED tubo · VAL válvulas e conexões · PVS poços de visita (só esgoto) · LIG ligações
   └─ .ELE                 FOR instalações · ATE aterramento e SPDA
U2                         Unidade 2 — Adutoras (obra linear, água)
└─ U2.AAT06                vala · pavimento · tubo · ligações (sem estaca, sem estrutura de concreto)
```

Fato = **(código, serviço, unidade)**. Exemplos:
- `(U1.FILTROS.GEO.FUN.BLO, concreto, m³)`: concreto dos blocos do módulo de filtros;
- `(U2.AAT06.GEO.MOV.VAL, escavacao, m³)`: escavação de vala da AAT06.

## 4. Quando a extração acontece: a linha do tempo

```
0  EAP GERAL ............ conceitos/*.jsonl — todos os itens e serviços que se podem procurar (água e esgoto)
1  Instanciar ........... obra.json: unidades, sistemas, escopo → EAP da obra (itens que valem para cada unidade)
2  Inventário ........... Drive → lista de documentos com tipo (edital, memorial, planilha, desenho) — drive-ingestao
3  LOOP NOS DOCUMENTOS .. cada documento passa por todos os itens e serviços da EAP geral:
     texto (edital, TR, memorial) ── vocabulário + termos ──► menção ou quantidade, com página e linha
     planilha do contrato ───────── cadastro de materiais pelo código, senão termos ──► parcela por linha
     pranchas medidas ───────────── eap.quantificar (elementos construtivos) ──► total por item
     serviços associados ────────── fórmulas sobre os elementos (bloco, estaca, trecho) ──► parcela por elemento
     IA (opcional) ──────────────── lê e propõe evidências com trecho literal ──► conferir_citacao
     decisões ───────────────────── o engenheiro adota um valor num conflito ──► evidência `decisao`
4  Consolidar ........... fatos: convergente | fonte única | conflito | só menção | decidido
   + associados aos fatos (laje convergente → escoramento) e nova consolidação
5  Cobertura ............ item × (projeto, edital); serviço associado × edital ("não citado: incluir ou confirmar")
6  HTML ................. aba EAP: árvore codificada, fatos com conflitos e evidências, associados × edital (§9)
```

No build (`python -m camadas.obra obra.json`), o passo 3–5 é `evidencias.etapa`. Ele roda depois dos elementos
construtivos e da EAP e grava estes arquivos em `saida/<obra>/`:
- `evidencias.jsonl`: o registro;
- `fatos.csv`;
- `cobertura.csv`;
- `associados.csv`.

No `obra.json`:

```json
"evidencias": {
  "documentos": [{"pdf": "dados/foz/edital/TR_R20.pdf", "tipo": "edital"},
                 {"pdf": "dados/foz/projeto/.../MEMORIAL_FUNDACOES.pdf", "tipo": "memorial", "unidade": "U1", "sistema": "ACT600"}],
  "ia": "dados/foz/evidencias_ia.jsonl",
  "decisoes": "dados/foz/decisoes_eap.jsonl"
}
```

A planilha entra sozinha pelo `escopo.itens_csv`, com o cadastro em `escopo.catalogo`. As pranchas entram pelos
elementos construtivos. Rodar de novo não duplica nada, porque o id da evidência é um hash do conteúdo.

## 5. Evidências: convergência e conflito (`camadas/evidencias.py`)

Cada evidência (`evidencia.schema.json`) traz:
- código, serviço, unidade e valor (ou `null` = só menção);
- `parcela` (soma dentro do documento) ou total;
- documento, localizador (página e linha, aba e linha, ids dos elementos);
- **trecho literal**, método e regra que casou.

Consolidação de um fato:
1. **uma afirmação por documento**: as parcelas se somam (linhas da planilha, elementos); o mesmo total repetido
   no documento conta uma vez;
2. **fato com `*`**: o documento que só fala dos sistemas concretos ganha uma afirmação derivada, a soma dos
   sistemas. Assim o "300" das pranchas (somado de todos os sistemas) se compara ao "250" de um memorial que fala
   da U1 inteira;
3. afirmações agrupadas por valor (tolerância 0,5 %):

| Status | Quando |
|---|---|
| `convergente` | um só valor, afirmado por ≥ 2 documentos; `forca` = nº de documentos que concordam |
| `fonte única` | um só valor, um documento |
| `conflito` | valores diferentes; mostra cada afirmação (documento, valor, trechos) e a diferença em % |
| `só menção` | o item é citado, sem número (ex.: "estacas conforme NBR 6122") |
| `decidido` | há evidência `decisao` (autor + justificativa); as afirmações continuam lá |

O código **não escolhe a verdade**. Ele extrai de forma reprodutível e guarda tudo com o trecho. Também mostra onde
os documentos concordam e onde divergem. Escolher um valor é papel do engenheiro, e a escolha fica registrada.

A IA lendo o mesmo documento não é fonte independente. Ela reforça a leitura, mas não aumenta a `forca`.

**IA com citação conferida** (`conferir_citacao`): o trecho tem de estar no documento e o número tem de estar no
trecho. Senão, a evidência fica registrada com `citacao: "trecho não encontrado no documento"` ou `"valor não está
no trecho"` e não entra na consolidação.

**Cobertura**: para cada unidade e item, mostra se há evidência no projeto (pranchas, geometria) e no edital
(edital, memorial, planilha):
- `só projeto: verificar se o edital considera`;
- `só edital: sem evidência no projeto`;
- `sem evidência`.

**Cadastro de materiais** (`catalogo_por_item`, `item_do_material`): a subcategoria, a família ou os termos ligam
cada material a um item. "PARA ESGOTO" na descrição tira o material do escopo água. Nos 40 371 materiais:

| Item | Água | Esgoto |
|---|---:|---:|
| HID.TUB.VAL válvulas e conexões | 9 926 | 12 484 |
| HID.EQP.EQU equipamentos | 5 612 | 6 086 |
| ELE.FOR.INS elétrica e automação | 5 525 | 5 593 |
| HID.TUB.RED tubulação | 3 585 | 5 338 |
| HID.TUB.LIG ligações e hidrometria | 47 | 47 |
| HID.TUB.PVS poços de visita | — | 43 |

Serviços civis (escavação, forma, concreto, armadura) não estão no cadastro, que só tem materiais. Eles vêm do banco
de serviços, dos sinônimos e da planilha CUSTO CIVIL.

## 6. Vocabulário: sinônimos, abreviações e unidades (`camadas/vocabulario.py`)

- **Abreviações**, aplicadas primeiro: `EST.` → ESTACA, `CONC.` → CONCRETO, `REAT.` → REATERRO, `ARM.` → ARMACAO,
  `P.V.` → POCO DE VISITA…
- **Sinônimos**: a variante acrescenta o termo canônico à linha usada na busca. Exemplos:
  - HÉLICE CONTÍNUA, TUBULÃO → ESTACA;
  - CIMBRAMENTO, PONTALETE → ESCORAMENTO;
  - FERRAGEM, CA-50, VERGALHÃO → ARMACAO;
  - BALDRAME → VIGA BALDRAME;
  - CBUQ → RECOMPOSIÇÃO DE PAVIMENTO.
- **Unidades**: M3, MC, METROS CÚBICOS → m³; ML, MT → m; UND, PÇ → un; TON → t; VB, GL → vb. A conversão t → kg
  permite comparar armadura em toneladas com armadura em quilos.
- "30 MPa" e "DN 300 mm" **não** viram quantidade.

O trecho da evidência é sempre a linha original. O vocabulário ajuda a achar, mas não reescreve o documento.

## 7. Serviços associados: elemento → dimensões → serviços

A EAP recebe dois tipos de serviço:
- os **declarados**, que estão nos documentos;
- os **associados**, que a execução de cada elemento exige, citados ou não no escopo.

Por exemplo:
- todo bloco precisa de lastro, forma, escavação e reaterro;
- toda laje suspensa precisa de escoramento;
- toda parede de tanque precisa de impermeabilização;
- toda rede precisa de vala, pavimento, escoramento e, às vezes, esgotamento.

O cálculo é genérico e tem três camadas, cada uma num arquivo:

```
conceitos/dimensoes.json ─ camadas/dimensoes.py      cada TIPO de elemento gera DIMENSÕES padronizadas
                                                     (V, A_forma, A_fundo, A_escoramento, A_imperm, V_esc…)
                                                     + derivados: bloco → cava; baldrame → vala corrida; trecho → vala
conceitos/servicos_associados.jsonl ─ camadas/associados.py   REGRAS sobre as dimensões, para os tipos listados
camadas/formulas.py                                  avaliador restrito (+ − × ÷ **, comparações, a if c else b,
                                                     max, min, pi) e premissas com fonte ou referência a outro conceito
```

**De onde vêm os elementos**: elementos construtivos lidos das pranchas (estaca, bloco, pilar, trecho), elementos
declarados no `obra.json` (laje, viga, parede, baldrame com as dimensões do projeto) e fatos consolidados (laje
120 m² → laje com A; baldrame 80 m → baldrame com L).

```json
"elementos_declarados": [
  {"id": "ACT600-laje-cobertura", "tipo": "laje", "unidade": "U1", "sistema": "ACT600",
   "dimensoes": {"A": 320.0, "e": 0.25, "P": 72.0}, "fonte": "forma ACT600 folha 3"},
  {"id": "ACT600-tanque", "tipo": "parede", "unidade": "U1", "sistema": "ACT600",
   "dimensoes": {"L": 48.0, "h": 5.2, "e": 0.30}}
]
```

**Dimensões padronizadas por tipo** (`dimensoes.json`):

| Tipo | Origem | V | A_forma | A_fundo (lastro) | A_escoramento | A_imperm | Derivado |
|---|---|---|---|---|---|---|---|
| estaca | d, L | π d²/4 · L | — | — | — | — | — |
| bloco | área, perímetro, face − arrasamento + 5 cm | A·h | P·h | A | — | — | cava de fundação |
| pilar | lado a, altura h | a²·h | 4a·h | — | — | — | — |
| laje | A, e, P, suspensa (1), imperm (0) | A·e | A·suspensa + P·e | A·(1 − suspensa) | A·suspensa | A·imperm | — |
| viga | b, h, L | b·h·L | (2h + b)·L | — | b·L | — | — |
| baldrame | L (b 0,20 e h 0,40 por premissa) | b·h·L | 2h·L | b·L | — | (2h + b)·L | vala corrida |
| parede | L, h, e, faces (1) | L·h·e | 2·L·h | — | — | L·h·faces | — |
| cava de fundação | A, P, h do pai; folga 0,5; lastro 0,05 | V_esc = (A + fP + 4f²)(h + e) · V_reat = V_esc − A(h + e) | | | | | |
| vala | `dimensionar_vala` (§7.1) | V_solo, V_rocha, A_demol, V_berço, V_env, V_reat, V_bota, A_escoramento | | | | | |

**Regras** (`servicos_associados.jsonl`): uma regra só, para todos os tipos que a listam.

| Regra | Tipos | Fórmula | Destino |
|---|---|---|---|
| concreto | estaca, bloco, pilar, laje, viga, baldrame, parede | V | `{item}` · concreto |
| forma | bloco, pilar, laje, viga, baldrame, parede | A_forma | `{item}` · forma |
| armadura | idem + estaca | taxa(tipo) · V (40–120 kg/m³, a calibrar) | `{item}` · armadura |
| lastro | bloco, baldrame, laje | A_fundo · 0,05 | `{item}` · lastro |
| escoramento | laje, viga | A_escoramento | `{item}` · escoramento |
| impermeabilização | parede, laje, baldrame | A_imperm | `{item}` · impermeabilização |
| arrasamento | estaca | 1 | `{item}` · arrasamento |
| escavação / reaterro | cava de fundação, vala corrida | V_esc · V_reat | GEO.MOV.ESC · GEO.MOV.REA |
| vala (17 regras) | vala | corte, demolição, recomposição (condição: há pavimento), escavação solo/rocha, escoramento `escoramento_{tipo}` e total `escoramento` (condição: escorada), berço, envoltória, assentamento, reaterro, bota-fora, esgotamento ou ponteiras (condição: água) | `{item_pavimento}`, GEO.MOV.VAL, HID.TUB.RED |

`{item}` é o item EAP do próprio elemento (bloco → GEO.FUN.BLO, laje → CIV.EST.PIS). Para acrescentar um serviço,
basta uma linha no JSONL. Exemplo: "chapisco = A_forma · 1" para paredes. Para acrescentar um tipo de elemento,
basta declarar as dimensões dele no `dimensoes.json`. Nenhum dos dois casos exige código novo.

Regras de segurança:
- **Faltou dimensão, não sai o serviço**, e o motivo fica registrado com a cadeia até a origem. Exemplos:
  - `pilar P5 (falta A_forma ← h)`: o pilar não tem altura;
  - `bloco (falta V ← h ← face)`.
- **O que não depende da dimensão faltante sai**: a viga sem altura ainda dá o escoramento b × L, e o bloco sem a
  face ainda dá o lastro pela área.
- **Memória de cálculo**: cada evidência `associado` leva a regra, a fórmula e a cadeia das dimensões do elemento.
  Exemplo: `f = 0.5 (premissa); Af = A + f * P + 4 * f ** 2 = 25; h_esc = 0.8; V_esc = 20`.
- **Fatos em conflito** não viram elemento: primeiro se resolve o conflito.
- **`validar()`** reprova:
  - fórmula com construção proibida;
  - destino fora da EAP ou serviço não admitido no item;
  - regra que usa uma dimensão que o tipo não produz.
- **`associados_x_edital`** aponta o serviço associado que o edital não cita (`não citado no edital: incluir ou
  confirmar`).
- **Saídas**: `dimensoes.csv` (a memória por elemento) e `associados.csv` vão para `saida/<obra>/`.

### 7.1 A vala: o único tipo com dimensionamento próprio (`dimensoes.dimensionar_vala`, `dimensoes.json#vala`)

A vala depende de **decisões**, e não só de contas: profundidade, solo, rocha, NA, tipo de escoramento e tipo de
pavimento. Por isso ela tem um dimensionador. Ele gera um elemento `vala` **por segmento de superfície** do trecho
(pista, calçada, fora da via…). Os serviços saem das regras genéricas acima. Os passos do dimensionamento:

| # | Passo | Regra |
|---|---|---|
| 1 | Profundidade | h = recobrimento da superfície (pista 1,0; calçada/outros 0,6) + DE + berço; ou a profundidade do perfil |
| 2 | Solo e água | furo com E/N mais próximo da linha do trecho, até 300 m: classes na faixa 0–h, NSPT mínimo, topo de rocha (camada de rocha ou impenetrável), NA medido − 0,5 m (margem sazonal); com a cota do trecho, as profundidades do furo são deslocadas |
| 3 | Escoramento | ≤ 1,25 m vala rasa (NR-18); ≤ 2,0 pontaleteamento; ≤ 3,0 descontínuo; ≤ 4,5 contínuo; acima, especial. Areia, aterro, NSPT < 4 ou abaixo do NA ⇒ no mínimo contínuo |
| 4 | Largura | b = max(DE + 0,60; mínimo da profundidade 0,60/0,80/1,00) + acréscimo do escoramento (0 a 0,30) |
| 5 | Pavimento | tipo pela superfície (pista → asfalto, calçada → concreto); corte com serra nas 2 bordas (m); demolição L × (b + 2 × 0,15) (m²); volume pelas camadas |
| 6 | Escavação | abaixo do pavimento, separada em **solo** e **rocha**; escoramento só na parte em solo |
| 7 | Tubo | berço; envoltória até 0,30 m acima da geratriz (só tubo flexível: PEAD, PVC); assentamento |
| 8 | Reaterro e bota-fora | reaterro = escavação − berço − envoltória − tubo; rocha e solo mole não voltam (reaterro importado); bota-fora empolado (solo 1,25; rocha 1,50; pavimento 1,35) |
| 9 | Recomposição | mesma área demolida (m²); camadas do pavimento em m³ como detalhe |
| 10 | Água | vala abaixo do NA: até 0,5 m de água em solo coesivo → bomba submersível (h); senão ou em areia/aterro → ponteiras (m + h); horas = L / avanço por DE × 10 h/dia |

Para quem usa o resultado:
- **Memória de cálculo**: cada decisão (h, solo, escoramento, b, pavimento, rocha, água) e cada cálculo do tipo.
- **Detalhes**: o volume demolido, as camadas e o reaterro importado ficam na memória, mas não viram evidência.
- **Itens EAP de destino**:
  - corte, demolição e recomposição vão para `CIV.PAV.REC` (asfalto) ou `CIV.PAV.CAL` (calçada);
  - escavação, rocha, escoramento por tipo, berço, envoltória, reaterro, bota-fora, esgotamento e rebaixamento vão
    para `GEO.MOV.VAL`;
  - o assentamento vai para `HID.TUB.RED`.
- **Sem sondagem no raio**: nada de rocha nem de NA é suposto, e o resultado leva o alerta.
- **Terreno**: sem a cota do trecho, o terreno fica na cota da boca do furo, também com alerta.

Exemplo (`dimensionar_vala` + `associados.aplicar`): AAT06, DE 630 PEAD, 120 m em pista e 30 m em calçada. O furo SP-07 está a 80 m, com
aterro e argila siltosa, NSPT 5–9, NA a 1,9 m e impenetrável a 2,3 m.

| Passo (pista) | Fórmula | Resultado |
|---|---|---|
| profundidade | 1,0 + 0,63 + 0,10 | 1,73 m |
| escoramento | 1,73 m e aterro (não coesivo) | contínuo |
| largura | max(0,63 + 0,60; 0,80) + 0,20 | 1,43 m |
| corte / demolição | 2 × 120 · 120 × (1,43 + 0,30) | 240 m · 207,6 m² |
| escavação em solo | 1,43 × (1,73 − 0,35) × 120 | 236,8 m³ (impenetrável abaixo da vala: sem rocha) |
| escoramento | 2 × 1,73 × 120 | 415,2 m² |
| lençol | 1,73 − (1,9 − 0,5) | 0,33 m de água → ponteiras, 80 h |

| Item | Serviço | Total do trecho |
|---|---|---|
| CIV.PAV.REC | corte · demolição · recomposição de asfalto | 240 m · 207,6 m² · 207,6 m² |
| CIV.PAV.CAL | corte · demolição · recomposição de calçada | 60 m · 51,9 m² · 51,9 m² |
| GEO.MOV.VAL | escavação em solo · escoramento contínuo | 288,7 m³ · 495,0 m² |
| GEO.MOV.VAL | berço · envoltória · reaterro · bota-fora | 21,5 · 152,7 · 67,8 · 382,7 m³ |
| GEO.MOV.VAL | rebaixamento (ponteiras) | 120 m · 80 h |
| HID.TUB.RED | assentamento | 150 m |

### 7.2 Vários métodos para a mesma vala: cada um é uma evidência

O código não escolhe um método de cálculo: roda **todos** os de `dimensoes.json#vala.metodos`, sobre os mesmos
trechos. Cada método gera os seus elementos `vala` e entra na consolidação como um documento próprio
(`metodo:nbr12266`, `metodo:mos_sanepar`). Se os métodos concordam, o fato é convergente. Se divergem, o fato fica
em conflito, com os valores de cada método e a diferença em %. A escolha é uma `decisao` do engenheiro, que não
apaga as afirmações.

| Método | O que calcula | Fonte |
|---|---|---|
| `nbr12266` | largura max(DE + 0,60; mínimo da profundidade) + acréscimo do escoramento; serviços pelas regras genéricas (escavação abaixo do pavimento, solo × rocha, bota-fora com empolamento e entulho) | `valas.json`, `dimensoes.json#vala` |
| `mos_sanepar` | **o dimensionador único da `main`** (`lineares.dimensionar_vala`, D2): L = D + SL + X + Y, escoramento por faixa e agravantes, escavação, reaterro, bota-fora, escoramento e pavimento dele, com o modelo geotécnico (raio de 60 m). Berço e envoltória, que ele não calcula, saem da regra genérica com a largura do MOS | `camadas/lineares.py`, `conceitos/lineares.json`, `obras_lineares.json`, `geotecnia.json` |

Exemplo AAT06 (PEAD DE 630, 120 m em pista e 30 m em calçada, furo SP-07 a 80 m):

| Serviço | NBR 12266 | MOS (lineares) | Status | Por quê |
|---|---:|---:|---|---|
| corte de asfalto, assentamento | iguais | iguais | convergente | não dependem da largura |
| demolição / recomposição de asfalto | 207,6 m² | 129,6 m² | conflito 37,6 % | NBR soma 0,15 m de corte de cada lado; MOS = comprimento × L |
| escavação de vala | 288,7 m³ | 267,3 m³ | conflito 7,4 % | NBR b = 1,43 abaixo do pavimento; MOS L = 1,08 × h inteira |
| escoramento | contínuo 495 m² | pontaleteamento 495 m² | um tipo em cada | o MOS não vê o furo (raio 60 m < 80 m): sem aterro, sem NA |
| escoramento total | 495 m² | 495 m² | convergente | regra `escoramento_vala_total`: o mesmo fato (GEO.MOV.VAL, `escoramento`, m²), qualquer tipo; compara métodos e fontes que não dizem o tipo |
| rebaixamento | 120 m, 80 h | — | fonte única | idem: para o MOS a vala não atinge o NA |
| reaterro | 67,8 m³ | 220,5 m³ | conflito 69,3 % | NBR desconta berço e envoltória; MOS = escavação − tubo |
| bota-fora | 382,7 m³ | 60,8 m³ | conflito 84,1 % | NBR: excedente de solo + entulho do pavimento; MOS: volume do tubo × empolamento |

Os conflitos mostram onde os critérios diferem: raio da sondagem, sobrelargura do corte e o que vai para o
bota-fora. A escolha é do engenheiro, registrada como `decisao`. O build continua usando o MOS (D2) como quantidade
de obra. Método que não se aplica ao tubo (material fora da Tabela I do MOS) fica de fora, com alerta em todos os
elementos do trecho. Valores dados por um método (os volumes do MOS) vencem os cálculos genéricos do tipo `vala`
(`dimensoes.dimensionar`). `validar()` reprova o método declarado sem código.

### 7.3 A planilha Obras Lineares como fonte (`evidencias.de_obras_lineares`, `de_obras_lineares_mos`)

A aba "Obras Lineares" da planilha Sanepar traz, por trecho, valores digitados (comprimento, escavação, reaterro,
bota-fora, supressão vegetal). Cada um vira uma evidência `parcela` do documento da planilha (método `planilha`, regra
`obras_lineares.planilha`), com o local e a linha no localizador. O escoramento da planilha é "sim/não", sem área, e por
isso não gera evidência. Os mesmos trechos são recalculados pelo MOS (`lineares.dimensionar_vala`) e entram como
`metodo:mos_sanepar:obras_lineares` (id distinto do `metodo:mos_sanepar` das valas dos elementos, para que as parcelas
não se somem no mesmo documento), nos mesmos fatos (escavação, reaterro, bota-fora e o escoramento total em m²).
Digitado igual ao recalculado é convergente; diferente é conflito, com as duas afirmações e a diferença em %.
O comprimento não é recalculado (o MOS só o copia da entrada), então o assentamento e a supressão ficam só com a
planilha (fonte única). Trecho em MND tem recálculo (só os caximbos escavam, sem largura); em VCA, sem profundidade ou
com material fora da Tabela I, não tem. A aba faz parte da planilha de orçamento do contrato Sanepar e, de propósito,
conta como edital (`TIPOS_EDITAL` inclui `planilha`): em `cobertura` o item aparece como "só edital" e em
`associados_x_edital` o serviço citado na aba sai como "citado no edital". A base do código é `U1.LINEARES` e se muda em `obras_lineares.eap` no
obra.json; `evidencias.etapa` soma as duas fontes quando `obras_lineares.planilha` existe no disco.

## 8. Quantificação das pranchas e verificação de proposta (`camadas/eap.py`)

- `eap.quantificar`: item EAP e grandeza → quantidade, com os ids dos elementos e as fontes. Elemento sem o
  atributo vai para `sem_valor`.
- `eap.consolidar(quant, nivel)`: soma por tipo de item (un de bloco não soma com un de pilar).
- `eap.lacunas` e `eap.sem_item`: o que falta e o que sobra (regra dos 100 %).
- `eap.verificar(proposta)`: refaz a conta só com os elementos citados. Os status são:
  - `confere`;
  - `confere, parcial`;
  - `quantidade diverge`;
  - `sem evidência`;
  - `evidência inválida`;
  - `medição não prevista`;
  - `código inexistente`.

## 9. Camadas no HTML: aba EAP (`camadas/eap_painel.py`)

Chaves de `dados` (cada etapa grava na sua; uma não pode sobrescrever a outra):

| Chave | Quem grava | Formato | Quem lê |
|---|---|---|---|
| `eap` | `extrair_gavetas` → `eap_html.montar` | `{nos, pendencias, resumo}` (gavetas, serviços lastreados) | `montarEap`, parte "Árvore da EAP" |
| `eap_codificada` | `eap.montar` | `{fonte, nos, quantidades, pranchas, lacunas, sem_item}` | `eap_painel.montar` |
| `evidencias` | `evidencias.etapa` | `{fatos, cobertura, associados, dimensoes, …}` | `eap_painel.montar` |
| `eap_painel` | `eap_painel.montar` | `{arvore, fatos, associados, resumo}`, tudo em texto pt-BR | `montarEap`, três seções novas |

O Python soma, ordena, conta e formata; o JS só desenha e alterna visibilidade. A aba EAP aparece com `eap`, com
`eap_painel` ou com os dois, e o conteúdo de `eap` não muda.

1. **EAP codificada**: `<details>` aninhados pelo `pai`. Cada nó mostra código, número, nome e `quantidades_txt`,
   somadas por nó e descendentes, por grandeza e unidade, sempre por tipo de item (`eap.consolidar`): acima do item, o
   texto leva o código do item ("12 un · GEO.FUN.BLO"). `elementos` são os ids dos elementos construtivos cujo código
   EAP está sob o nó.
2. **"Ver no mapa"** (só com a camada de elementos construtivos da aba Obra): liga a camada, enquadra e destaca só os
   ids do nó. Um elemento usa `selecionarObra`; vários usam o mesmo anel da aba Obra (`haloObra`), sem conta em JS.
3. **Fatos e evidências**: resumo por status, filtro visual por status e uma linha por fato (selo, código, serviço,
   valor, diferença). Ordem: conflito, só menção, fonte única, convergente, decidido. Ao abrir, as afirmações
   (documento, tipo, valor, trecho de até 200 caracteres).
4. **Serviços associados × edital**: tabela com a quantidade formatada; "não citado no edital" fica em destaque
   (`destaque` vem calculado do Python).

Fica para depois: selo de status por nó da árvore, clique no nó como filtro por prefixo que esmaece as outras
disciplinas e a vista particular já enquadrada para o item.
