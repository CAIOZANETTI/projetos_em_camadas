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
- `associados.csv`;
- `calibracao.csv` (premissa × observado, §7.4).

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

**Caminho seguro para a IA** (`roteiro` e `conferir`): `python -m camadas.evidencias roteiro [--escopo] [--obra]` gera o
que procurar por item (termos e sinônimos, serviços e unidades aceitas); a IA escreve uma linha JSON por afirmação com
o trecho copiado literalmente; `python -m camadas.evidencias conferir IA.jsonl --pdf DOC.pdf [--texto DOC.txt]
--saida aceitas.jsonl` valida o schema, localiza o documento por `documento.id` e aplica `conferir_citacao`. O relatório
diz quantas foram aceitas e o motivo de cada recusa (schema, documento não fornecido, trecho não encontrado, valor
fora do trecho); só as aceitas são gravadas. A skill `eap-evidencias` descreve o passo a passo.

A conferência exige trecho com 3 palavras ou 15 caracteres, achado numa página do documento (nunca atravessando páginas)
com fronteira de palavra e de número ("250 estacas" não está em "1.250 estacas" nem "5 m³" em "12,5 m³"). O par (valor,
unidade) tem de ser um dos que o trecho afirma ("250 estacas" → 250 un; "20 m²" → 20 m²; "m³ 1.250,50"; nunca o 2 de M2)
e vir da **mesma linha** em que o termo do item do código aparece, a no máximo 8 palavras do número; o item e o serviço
do código têm de existir na EAP geral (`*` só em unidade e sistema) e a unidade tem de ser a do serviço ou do item. O
localizador "p. N", se houver, tem de ser a página do trecho; aspas curvas, travessões e hífen de fim de linha são
unificados; toneladas viram kg, como no regex. O item citado tem de ser o termo de item mais próximo do número na linha
("Bloco de coroamento para 2 estacas un 12" é do bloco, não das estacas; empate = recusa "número pertence a outro item");
"12 m de estaca" e "3.000 metros de estacas" não são contagem de estacas; valor acima de 1e12 é recusado.
**Bloco de linha de tabela:** descrição de planilha em várias linhas, com a quantidade na última, também vale. O
trecho é expandido até as **linhas inteiras** da página (o recorte não esconde o que a linha tem antes ou depois); um
bloco são 2 ou 3 dessas linhas seguidas, da mesma página, sem linha em branco (nem quebra de página `\f`). O par (valor,
unidade) tem de começar na **última** linha, e as anteriores não podem afirmar nenhuma quantidade (número com unidade de
quantidade, "un 12", "12 estacas"). Dimensão de especificação (Ø, DN, "diâmetro" ou "diam." seguido de número e, se
houver, unidade de comprimento mm/cm/m/pol sem outro número depois) e medida em unidade fora do vocabulário ("40 cm") não
contam. **Continuação:** toda linha depois da primeira tem de continuar a descrição da anterior: ou só traz o par, rótulo
de quantidade (Quantidade, Quant., Qtde, Qtd, Qt; "Total" não é rótulo) e separadores, ou a linha de cima não termina em
"." nem ":" e ela começa em minúscula ou com conectivo (e, ou, com, sem, para, de, do, da, em, inclusive, incluso,
incluindo, conforme). Título, cabeçalho de seção ou de tabela e linha de outro item (maiúscula sem conectivo) não formam
bloco com a linha de baixo. Cumprido isso, o termo do item pode estar em qualquer linha, sem o limite de 8 palavras
para as anteriores; valem todas as outras regras (item mais próximo do número, item e serviço da EAP, unidade, página,
dedupe). Recusados: duas linhas de tabela de itens diferentes, 4 ou mais linhas, linha em branco, quebra de página.
Exemplos aceitos: "Estaca hélice contínua, diâmetro 40 cm, inclusive⏎mobilização e desmobilização un 250" e
"Estacas hélice contínua Ø40 cm⏎Quantidade: 250 un" (250 un de GEO.FUN.EST). Propostas da IA
no mesmo documento só colapsam se o trecho normalizado for o mesmo (a mesma frase em outra página é total repetido);
parcelas reais de valor igual ("Bloco B1 com 12 estacas", "Bloco B2 com 12 estacas") somam, e a mesma proposta (mesmo `id`,
que inclui `parcela`) conta uma vez. Só a IA é deduplicada por `id`: as demais fontes mantêm a soma de parcelas iguais. O build não confia no
selo `citacao` do arquivo: reconfere as evidências `ia` contra os documentos do `obra.json`. A leitura da IA vale como
afirmação própria (`documento.id` = `ia:<arquivo>`), para nunca somar com o regex do mesmo documento; mas conta como a
mesma fonte (L025/L029: fonte independente = documento diferente), então não aumenta a `forca`.

**Planilha como documento de leitura da IA** (`paginas_planilha`): cada aba vira uma página (csv = uma página), com uma
linha de texto por linha não vazia: as células não vazias unidas por " | ", na ordem das colunas; número em pt-BR, sem
arredondar (250.0 → `250`, 1250.5 → `1.250,5`), percentual `15%`, data `dd/mm/aaaa`. É o texto sobre o qual a IA copia o
trecho. O localizador pode ser `{"aba": "<nome>", "linha": N}`, com N a linha da planilha (1 = primeira da aba, contando
as vazias, como no Excel): o trecho tem de estar nessa linha da aba ("linha citada não contém o trecho"; aba que não
existe: "aba citada não existe no documento"; nome comparado em NFC, sem espaço nas pontas). "p. N" continua valendo, como
índice da aba. As regras do texto valem para o item (termo mais próximo do número, bloco de 2 a 3 linhas seguidas, sem
linha vazia entre elas, com o par na última), mas **a quantidade não vem do " | "**:
- **Colunas Un/Qtd.** Em cada aba, a linha com um rótulo de unidade (`Un`, `Und`, `Unid`, `Unidade`) e um de quantidade
  (`Qtd`, `Qtde`, `Quant`, `Quantidade`) é o cabeçalho das linhas abaixo dela (o último cabeçalho acima vence). O valor
  proposto tem de ser o número da coluna Qtd e a unidade a da coluna Un (normalizada pelo vocabulário), as duas células
  dentro do trecho. Preço, código e outras colunas nunca viram quantidade; Qtd vazia não vira quantidade.
- **Sem cabeçalho** reconhecido: só valem pares dentro de uma mesma célula ("250 un").
- **Célula que não vale como dado**: fórmula sem valor guardado ("[fórmula sem valor]") e número fora de 1e-6 a 1e15
  (ou NaN/infinito) recusam a linha ("célula sem valor calculado na planilha").
- **csv**: separador `;`, tabulação ou `,` pelo número de campos consistente nas linhas (empate: `;`); inconsistente, o
  documento é recusado. `.xls` exige `xlrd`; sem ele o documento é recusado com aviso (o build segue).
- A leitura por regex (`buscar_texto`) de uma planilha segue as mesmas colunas e grava o localizador `{aba, linha}`.

Isso é leitura pela IA (e pelo regex); a leitura determinística da planilha do contrato segue em `de_planilha`
(método `planilha`).

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

Número colado a letra ou hífen (`DN150`, `C30`, `CA-50`, `Ø40`) e dimensão com espaço (`DN 150`, `Ø 40 cm`, `diâmetro 150`)
não são quantidade, nem no regex (`quantidade`) nem na conferência da IA: a regra é uma só (`NAO_E_NUMERO`, `DIMENSAO`).

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

### 7.4 Calibração de premissas (`camadas/calibracao.py`)

Premissa × observado: quando um serviço associado tem um fato de fora (edital, planilha, memorial, IA conferida ou
decisão), a tabela mostra o valor que a premissa teria de ter para reproduzir o observado. Só informa: **nunca
sobrescreve** a premissa, que continua em `servicos_associados.jsonl` com `estado` e `fonte`; quem muda é o humano.

- **Regra**: `premissa implícita = p × observado / calculado`, só para fórmula **linear numa única premissa**
  (armadura = taxa × V; lastro = A_fundo × e). A linearidade é testada em cada elemento, avaliando a fórmula com a
  premissa em 0, p/2, p e 2p (tolerância relativa de 1e-9). Fórmula com `max`, `if`, patamar ou termo constante, regra
  sem premissa, mais de uma premissa proporcional ou mais de uma regra no mesmo serviço: `não calibrável`, com o
  motivo e sem número. Premissa por tipo de elemento (taxa de armadura): `valor_premissa` é a média ponderada pelo
  calculado.
- **Observado**: o fato de fora (sem contar os próprios serviços associados, que seria circular). Convergente ou
  fonte única vale; decisão vale; conflito não calibra (`fato em conflito`); observado ≤ 0 não calibra.
- **Casamento**: a tabela parte dos fatos. Fato com `*` (`U1.*.CIV.EST.VIG`) soma os associados de todos os códigos
  que ele cobre; as unidades são levadas à de comparação (`vocabulario.converter`: t → kg). Associado sem fato com
  valor não entra.
- **Calculado**: soma das evidências associadas do grupo (o que a EAP mostra), também nas linhas não calibráveis. O
  recálculo por elemento (elementos casados por id **e** base, mais os de `dimensoes.de_fatos`) só serve para achar a
  premissa e a linearidade e tem de bater com essa soma; se não bate, `não calibrável`. Depois, a fórmula com a
  premissa implícita tem de reproduzir o observado (pega teto como `min(taxa × V, 300)`); falha de avaliação,
  condição que depende da premissa e fórmula não proporcional também não calibram. `unidade_premissa` vem do campo
  `unidade` da premissa (vazio se não declarado).
- **Tolerância**: `confere` se observado/calculado difere de 1 em até 5 % (`TOLERANCIA_CONFERE`); acima, `diverge`.
- **Saída**: `calibracao.csv` em `saida/<obra>/` e `dados["evidencias"]["calibracao"]`. Colunas: código, serviço,
  unidade, regra, premissa, unidade_premissa, valor_premissa, calculado, observado, razao, premissa_implicita, diferenca_pct, situacao,
  motivo, documentos.

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

### 8.1 Conciliação das duas EAP: origem das trilhas e documento independente (`gavetas.conciliar_eap`)

As gavetas e a EAP codificada medem os mesmos códigos. Comparar os dois números só valida alguma coisa se eles não
vieram do mesmo insumo; a escavação das cavas, por exemplo, sai de `escavacao.etapa` nas duas trilhas, e o "confere"
com diferença 0 é circular.

**Origem de cada trilha.** É o conjunto de insumos de onde o número veio, com dois tipos de item:
`arquivo:<nome>` (documento ou arquivo, sem pasta nem extensão, em minúsculas) e `etapa:<nome>` (etapa do build que
produziu a medida).
- Gavetas: cada serviço guarda `origem` (`gavetas.anotar_origem`, anotação fora da chave do incremental). Ela sai da
  cadeia serviço → `fatos` → `evidencia_id` → evidência da base: o `documento` vira `arquivo:` e o critério do
  localizador de uma etapa conhecida (`gavetas.ETAPA_DA_EVIDENCIA`, ex.: "plantas de escavação") vira `etapa:`. A origem
  da linha é a união dos serviços do código.
- EAP codificada: `eap.origem_das_quantidades` une os insumos dos elementos que compõem a quantidade (`evidencias` =
  ids dos elementos): o `doc` do elemento vira `arquivo:` e o começo da `fonte` de uma etapa (`eap.ETAPA_DA_FONTE`,
  ex.: "escavação calculada").
- Origem de um lado que não se determina (serviço sem fato, fato fora da base, elemento sem `doc` nem etapa
  conhecida) torna a linha `origem` = "indeterminada" e a situação fica como estava. Nada é inventado.

**Situação.** Com insumo em comum (uma origem contida na outra, ou só parte compartilhada), "confere" passa a
**"confere (mesma origem)"**: não é conferência independente. "difere" com a mesma origem continua "difere" e o
`motivo` o destaca (erro de cálculo, não de insumo, mais grave). Com origens disjuntas, "confere" vale. Cada linha traz
`origem` (mesma, independente ou indeterminada), `origem_gavetas`, `origem_codificada` e `motivo`.

**Terceira coluna: documento independente** (`gavetas.documento_independente`). Para cada código procura os fatos de
`dados["evidencias"]["fatos"]` do mesmo código (o `*` casa qualquer segmento, como em `evidencias`), com serviço vazio
(o próprio item) e a mesma unidade depois de `vocabulario.converter` (t × kg). Só contam afirmações de documento
independente: planilha, edital, memorial, IA com citação conferida e decisão. **Nunca** `geometria`, `associado` (fórmula
sobre outro número) nem `projeto` (as pranchas são a fonte que o construtivo mede). A decisão vale no lugar das
afirmações do fato, como em `evidencias.consolidar`. Colunas: `documento` (valor na unidade da linha), `documentos`
(nomes) e `situacao_documento`:
- `confere com documento` e `difere do documento` (Δ = referência − documento, e Δ % sobre o documento), com a mesma
  tolerância absoluta da conciliação; a referência é a medida das gavetas ou, sem ela, a da EAP codificada;
- `documento em conflito` (documentos independentes discordam entre si, sem valor);
- `sem documento`.

`eap_html.conciliacao` formata tudo em Python; a aba EAP só exibe as colunas Origem, Documento e Situação do documento,
e marca com selo e realce as linhas `mesma_origem` (o "confere (mesma origem)" e o "difere" de mesma origem). O build
concilia depois do loop de evidências (`obra._conciliar_eaps`), porque a terceira coluna precisa dos fatos.

## 9. Camadas no HTML: aba EAP (`camadas/eap_painel.py`)

Chaves de `dados` (cada etapa grava na sua; uma não pode sobrescrever a outra):

| Chave | Quem grava | Formato | Quem lê |
|---|---|---|---|
| `eap_gavetas` | `extrair_gavetas` → `eap_html.montar` | `{nos, pendencias, resumo, setores}` (gavetas, serviços lastreados) | `montarEap`, parte "Árvore da EAP" e "EAP por setor" |
| `eap` | `eap.montar` | `{fonte, nos, quantidades, pranchas, lacunas, sem_item}` (EAP codificada) | `eap_painel.montar` |
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

5. **Selo de status por nó** (`eap_painel.status_do_no`): cada nó da árvore traz `status_no`, `n_fatos` e `n_conflitos`,
   agregados em Python. Um fato cobre o nó quando o código dele tem o mesmo número de segmentos ou mais e casa
   segmento a segmento com o do nó; `*` casa qualquer segmento, e um fato de item cobre o item e os ancestrais, não
   os filhos. Fato com `*` é mais restrito: só cobre o nó se houver, sob ele, alguma quantidade da EAP codificada
   cujo código case com o fato (`U1.*.GEO.FUN.EST` cobre `U1`, `U1.A` e `U1.A.GEO.FUN` apenas nos sistemas que têm
   estaca; um sistema sem o item fica sem evidência, não em conflito). Fato sem `*` segue só a regra de prefixo.
   Os textos do selo (`selo_title`, com o plural certo) e da vista (`rotulo_vista`, com `n_elementos` do nó) vêm
   prontos do Python; `n_elementos` pode incluir ids sem geometria na camada do mapa. Regra: algum conflito →
   "conflito"; senão algum só menção ou fonte única → "fonte única"; senão todos convergentes ou decididos →
   "convergente"; sem fato → "sem evidência". O JS só mostra o selo (`st st-<slug>`) no `summary` do nó.
6. **Filtro por prefixo e vista particular**: "ver no mapa" guarda os ids do nó em `OBRA.filtroEap` e `estiloObra`
   esmaece (sem remover) os elementos fora da lista; como `aplicarEscopoMapa` e `resetStyle` passam por
   `estiloObra`, o esmaecimento sobrevive à troca de escopo e à seleção de elementos. `limparSelecaoObra` não o
   desfaz; só o botão "limpar filtro EAP" da linha "Vista: código · nome (n elementos)", no topo da aba EAP, que
   também limpa a seleção e o anel (se o usuário escolheu outro elemento depois do filtro, a escolha fica). Com o
   filtro ativo, a aba Obra mostra "Filtro EAP: código" com o mesmo botão de limpar. Item: abre a ficha do primeiro elemento (aba Obra) e, com vários, enquadra e
   destaca todos.

7. **Só pranchas desta disciplina** (`eap_painel.subgrupos_do_codigo`): cada nó da árvore traz `subgrupos_mapa`
   (subgrupos de `conceitos/disciplinas.json`, em ordem alfabética) e `pranchas_txt` ("Pranchas: Adutoras, Geotecnia e
   fundação, Terraplenagem"; vazio sem subgrupos), tirados da chave `pranchas` de `conceitos/eap.json` (subgrupo → pacotes
   `DISC.PAC`). A disciplina e o pacote são os segmentos `disciplina` e `pacote` de `eap.NIVEIS` (em `U1.A.GEO.FUN.EST`,
   `GEO` e `FUN`). Nó de disciplina (`U1.A.GEO`): subgrupos com algum pacote `GEO.*`; nó de pacote ou item
   (`U1.A.GEO.FUN`, `U1.A.GEO.FUN.EST`): subgrupos que contêm `GEO.FUN`; unidade e sistema: lista vazia, sem recorte. Com
   "ver no mapa" ativo, o nó com `subgrupos_mapa` e ao menos uma prancha georreferenciada mostra, na linha "Vista", o
   checkbox "só pranchas desta disciplina" (desmarcado). Ao marcar, o JS guarda `P.vis` e `P.mapa.on` de cada prancha
   georreferenciada e deixa ligados só os layers cujo subgrupo (`layer.subgrupo` ou o da prancha) pertence à lista
   (pertencer ou não, sem conta); a prancha sem nenhum layer da lista é desligada. Desmarcar, "limpar filtro EAP" ou
   "ver no mapa" de outro nó restauram o instantâneo exato, e trocar de nó desmarca o checkbox.
   Ligar ou desligar uma prancha pelo recorte não move o mapa (`ligarPranchaMapa(P, on, semVoo)`): o enquadramento
   continua o do nó. Limites conhecidos (revisão da 0.38.0): o que o usuário mudar nas pranchas com o recorte ativo é
   desfeito pela restauração (o instantâneo manda); o recorte é por disciplina, não por unidade (`U2.X.GEO` também liga
   as pranchas de GEO de U1); no nó de disciplina a lista vem de todos os pacotes da disciplina em `eap.json`, não só
   dos pacotes-filho do nó; o checkbox aparece mesmo se nenhuma prancha tiver layer da lista (marcar desliga todas).

## 10. Próximos passos

- [x] **Skill de leitura por IA** (`.claude/skills/eap-evidencias`, `evidencias.roteiro`, `evidencias.conferir_arquivo`):
  a IA lê edital, TR, memorial e laudo seguindo o roteiro e só entra com citação conferida pelo código (§5).
- [x] Conferir também o localizador (a página citada contém o trecho).
- [x] **Aceitar planilha como documento de leitura** (`evidencias.paginas_planilha`; CLI `conferir --planilha`;
  `evidencias.documentos` aceita .xlsx/.xls/.csv): uma página por aba, uma linha de texto por linha não vazia (células
  não vazias unidas por " | ", números em pt-BR sem arredondar) e localizador `{"aba", "linha"}` conferido (§5).
- [x] **Conferência por bloco de linha de tabela** (IA): bloco de 2 a 3 linhas seguidas do trecho, sem linha em branco,
  com o par (valor, unidade) na última linha e nenhuma quantidade nas anteriores (§5; `_confere_bloco`).
- [x] **Número colado a letra ou hífen em outro campo da linha** ("DN150 m 320", "C30 m³ 45", "CA-50 kg 1.200"): o
  número com letra ou letra+hífen colada não é quantidade, e o regex que não é IA lê igual: regra única em
  `vocabulario.NAO_E_NUMERO` (e `DIMENSAO` para "DN 150", "Ø 40 cm"), usada por `vocabulario.quantidade` e pela guarda da IA.
  O regex só lê "número unidade" (e "número termo"): "DN150 m 320" fica sem quantidade (só menção).
- [x] **Calibração de premissas pela evidência** (`camadas/calibracao.py`, §7.4): premissa implícita e situação
  (`confere`/`diverge`/`não calibrável`) por serviço associado com fato de fora; nunca sobrescreve a premissa.
- [ ] Calibrar com dados reais de obra (lista de ferros, planilhas): decidir, premissa a premissa, quais valores mudam.
- [ ] Calibração de premissas não lineares (patamares da vala): exige método próprio, não a proporção.
- [x] Selo de status por nó da árvore, filtro por prefixo e só pranchas desta disciplina (§9).
