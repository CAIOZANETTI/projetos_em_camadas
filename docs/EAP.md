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
  servicos_associados.jsonl  serviço que a execução exige: base (elemento ou fato), destino, variáveis, premissas,
                             fórmula
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
6  HTML ................. árvore da EAP com fatos, conflitos e evidências clicáveis (próxima rodada)
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

## 7. Serviços associados (`camadas/associados.py`, `conceitos/servicos_associados.jsonl`)

Cada regra tem:
- **base**: classe do elemento construtivo, ou fato consolidado;
- **destino**: item EAP + serviço;
- **variáveis**: atributo, geometria em UTM ou valor do fato;
- **premissas**, com fonte e estado, ou uma referência a outro conceito (`valas.json#berco_m.valor`);
- **cálculos intermediários** e a **fórmula**.

| Base | Serviço | Fórmula (resumo) |
|---|---|---|
| bloco (área A, perímetro P, face e arrasamento) | escavação (GEO.MOV.ESC) | (A + f·P + 4f²)·(h + e), h = face − arrasamento + embutimento |
| bloco | reaterro, lastro, forma, concreto, armadura | (Af − A)(h+e) · A·e · P·h · A·h · taxa·A·h (taxa a calibrar) |
| estaca (d, L) | concreto do fuste, arrasamento | π d²/4 · L · 1 un |
| trecho de rede (DE, extensão por superfície) | escavação, berço, reaterro de vala | b = max(DE + 0,60; 0,60); h = recobrimento (pista/calçada/outros) + DE + berço |
| trecho de rede | demolição e recomposição de pavimento | extensão em pista × (b + 2 × 0,15) |
| fato laje (m²) | escoramento | A |
| fato viga baldrame (m) | escavação e reaterro | L(b + 2f)(h + e) · L·2f·(h + e) (seção a conferir) |

Como as fórmulas são calculadas e usadas:
- **Avaliador restrito**: números, + − × ÷ **, max, min e pi. Nenhum código arbitrário roda.
- **Variável faltando** e sem padrão: o elemento vai para `sem_valor`, nunca para zero.
- **Memória de cálculo**: cada resultado vira evidência `associado`, com o cálculo no trecho. Exemplo: `Escavação
  para o bloco: Af * (h + e) = 20 m³ (f=0.5, emb=0.05, e=0.05, A=16, P=16, …) · premissa`.
- **Fatos em conflito** não geram serviço associado: primeiro se resolve o conflito.
- **`associados_x_edital`** lista o serviço associado que nenhum documento do edital cita: `não citado no edital:
  incluir ou confirmar`. É a pergunta "o escoramento da laje está no orçamento?".

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

## 9. Camadas no HTML: geral × particular (próxima rodada)

O build já grava `dados.eap` (nós, quantidades, pranchas por pacote, lacunas). Também grava `dados.evidencias` (fatos
com as afirmações, cobertura e associados × edital) e o código `eap` em cada elemento. Falta a interface:

1. **Árvore EAP** na aba Obra. Cada nó mostra o código, as quantidades e um selo de status: verde = convergente,
   cinza = fonte única, vermelho = conflito, amarelo = associado não citado no edital.
2. **Clique num nó = filtro por prefixo**:
   - liga os elementos do código, as pranchas do pacote e os layers do item;
   - esmaece as outras disciplinas, para ver a sobreposição civil × hidráulica × elétrica.
3. **Nó alto** (U1, U1.ACT600) dá a vista geral. **Item** dá a vista particular, já enquadrada no mapa.
4. **Ficha do fato**: cada afirmação com documento, página e trecho, a diferença em % e o botão "adotar valor", que
   exporta uma linha `decisao` para `decisoes_eap.jsonl`.

## 10. Próximos passos

| # | Passo | Peças |
|---|---|---|
| a | Aba EAP no HTML (§9) e teste de interface | `templates/visualizador.html`, `scripts/testar_visualizador.py` |
| b | Rodar Foz com o TR, os memoriais e a planilha: primeiros conflitos reais | `exemplos/foz/obra.json` (`evidencias`) |
| c | Skill de leitura por IA: lê os documentos e escreve `evidencias_ia.jsonl` com trecho literal | `.claude/skills/eap-evidencias` |
| d | Medir vigas, paredes e lajes nas formas (comprimento/área por layer já calculados em `pdf_cad.quantitativos`) | `pdf_cad`, `prancha.ficha_estrutura` |
| e | Calibrar premissas (taxa de armadura, embutimento, seção de baldrame) com projetos de armação | `servicos_associados.jsonl` |
| f | Calçada na vala (demolição/recomposição em fato próprio), escoramento de vala por profundidade, bota-fora por empolamento | `servicos_associados.jsonl`, `servicos.jsonl` |

## 11. Decisões em aberto (Caio)

1. **Mecânica dentro de Hidráulica?** Os equipamentos estão em `HID.EQP`, como no pedido. A Sanepar separa PBME/PMEC.
2. **Ordem dos níveis**: unidade → sistema → disciplina (como está) ou unidade → disciplina → sistema?
3. **Código oficial**: as UCs do TR e as fases de medição devem entrar como `codigo_contrato` em cada nó?
4. **Destino da escavação do bloco**: hoje ela vai para `GEO.MOV.ESC`, junto da cava calculada pelo MDS. São dois
   métodos para o mesmo fato e aparecem lado a lado. Ou deve ficar em `GEO.FUN.BLO / escavacao`?
5. **Tolerância de convergência**: 0,5 % para tudo, ou por serviço (concreto 2 %, contagem exata)?
