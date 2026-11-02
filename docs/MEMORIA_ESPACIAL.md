# Memória espacial: de-para do documento à EAP (v0.4, 01/11/2026)

Status: implementado e testado em dados sintéticos nas rodadas 21 a 24 (0.25.0 a 0.30.0). Ligado ao build. Falta o build
real de Foz (§8).
Complementa `docs/ARQUITETURA.md` sem substituí-lo.

## 1. A ideia em uma frase

**Cada informação extraída tem um lugar certo para ser guardada, georreferenciada e com a evidência; os serviços
são calculados depois, a partir desse lugar; a entrega é a EAP, mostrada num HTML completo.**

A base georreferenciada não é a entrega. É a **memória intermediária** entre os documentos e a EAP: o lugar onde
a extração deposita os fatos e de onde os cálculos os retiram. Separar as etapas evita fazer tudo junto e se
perder: quem lê não calcula, quem calcula não lê.

```
 documentos ──► ETAPA 1: extrair e guardar ──► base georreferenciada ──► ETAPA 2: serviços ──► ETAPA 3: EAP ──► HTML
 (pranchas,      de-para 1: documento → gaveta   (objetos, fatos,          de-para 2:            de-para 3:
  laudos,                                         evidências, pendências)   gaveta → serviço      serviço → nó EAP
  planilhas…)
```

Isso é coerente com os princípios do `ARQUITETURA.md`: a EAP é a linha mestra, os documentos são evidências, o
georreferenciamento é o jeito de ver no local e o HTML é a entrega.

## 2. Os três de-para

O "documento de-para" são três tabelas de correspondência, escritas **antes** da extração. Elas fixam o contrato
de cada etapa: um agente ou um leitor em código só pode gravar numa gaveta que já existe.

| De-para | De | Para | Onde mora (proposta) |
|---|---|---|---|
| 1 | classe de documento + elemento lido (ex.: prancha de perfil → tubo, cota de geratriz, estaca) | gaveta da base (tabela + campos obrigatórios) | `conceitos/de_para_extracao.json` (feito) |
| 2 | gavetas necessárias (tubo + terreno + solo + NA + pavimento) | regra de serviço (vala, escoramento, reaterro…) | `conceitos/de_para_servicos.json` (feito), usando `obras_lineares.json` |
| 3 | serviço calculado | nó da EAP (código, unidade de medida) | `conceitos/de_para_eap.json` (feito, códigos provisórios) |

Regras:
- **O que não tem gaveta vira pendência**, não texto solto. Uma gaveta nova é decisão de arquitetura (Opus/Caio),
  não improviso do extrator.
- **Gaveta vazia também é informação**: se a regra de serviço precisa do NA e não há sondagem no raio, sai
  pendência com o motivo, não um valor inventado.
- O de-para 2 diz de quais fatos cada serviço depende. É isso que permite trocar o método executivo (vala aberta ×
  MND) sem reler as pranchas, e reprocessar só o que uma revisão afetou.

## 3. Etapa 1: extrair e guardar

### 3.0 Inventário primeiro, em loop, e escada de executores

Para não haver alucinação, nada é lido antes do **inventário de todos os documentos**, e a extração é um **loop
sobre o inventário**, nunca uma leitura livre. A IA aciona o código Python, que percorre os arquivos; ela só entra
onde o código não resolveu. O ciclo já existe (`ARQUITETURA.md` §2, `camadas/inventario.py`, `camadas/extracao.py`,
`camadas/escada.py`); muda o destino: cada fato sai do leitor direto para a sua gaveta.

```
inventário ─► loop nos arquivos ─► leitor em código ─► gaveta ─► reavaliação ─► completo? ─ não ─► próximo degrau
                    ▲                                                                                  │
                    └──────────────────────────────────────────────────────────────────────────────────┘
```

A escada sobe por **complexidade do documento** ou por **ineficiência do código** (o leitor tentou e não extraiu):

| Degrau | Quem | Quando |
|---|---|---|
| 1 | código Python | sempre primeiro: leitor da classe, releitura, OCR em 300 dpi, extrair o zip |
| 2 | Haiku | arquivos simples e trabalho braçal: dizer a classe, ler um carimbo recortado, conferir contagens |
| 3 | Sonnet | leitura técnica: arquivo sem leitor, laudo, memorial, lista, prancha escaneada (com citação) |
| 4 | Opus | conflito entre fontes, georreferência difícil, julgamento; o que for regra vira `conceitos/` |
| 5 | Fable | verificação independente: audita uma amostra e as pendências sem ver a conclusão de quem extraiu |
| 6 | você | arquivo privado, decisão de engenharia, regra nova |

Os degraus e o `max_tentativas` de cada um estão em `conceitos/fontes.json` (`escada`). Cada agente só devolve as
propriedades que o de-para 1 lista para aquele documento, e o retorno é conferido em código
(`extracao.aplicar_retornos`: o trecho citado precisa estar na página). Toda evidência grava o `executor`, então se
sabe o que saiu por código e o que precisou de IA.

### 3.1 Gavetas da base (esquema mínimo)

| Gaveta | Um registro é | Campos principais |
|---|---|---|
| `objetos` | uma coisa física (trecho de tubo, bloco, estaca, furo de sondagem, peça) | `objeto_id` estável, `classe` (de `elementos.json`), `disciplina`, `unidade` |
| `geometria` | a forma do objeto | XY(Z) em SIRGAS 2000/UTM, ou `eixo_id` + progressiva inicial/final + afastamento (obra linear) |
| `fatos` | uma propriedade de um objeto | `objeto_id`, `propriedade`, `valor`, `unidade`, `natureza` (observado, projetado, inferido, decidido) |
| `evidencias` | de onde o fato veio | formato do `ARQUITETURA.md` §3: classe, documento, revisão, localizador (página, bbox, layer, ids), trecho literal, método, passe, executor |
| `pendencias` | o que faltou ou conflitou | gaveta, objeto, motivo, próximo passe da escada |
| `servicos` | uma quantidade calculada (Etapa 2) | objeto, regra, versão da regra, saída, valor, unidade, `fatos` usados |

A identidade (`objeto_id`) é separada do endereço espacial. Um objeto pode ocupar vários trechos ou células; um
trecho pode conter vários objetos.

### 3.1.1 Tipo da gaveta (formato físico): experimento, não decisão

O contrato das gavetas é **lógico** (nomes, campos, valores permitidos em `conceitos/gavetas.json`). O formato do
arquivo é testado e escolhido por métrica, da forma mais determinística possível (experimento G05 nos 5 km e G08 na
carga sintética de 100 km):

| Candidato | Situação (rodada 21, 01/11/2026) |
|---|---|
| **Parquet** | **atual**: venceu a bancada (8× menor que o JSONL em 100 km, consulta p95 ≤ 6 ms pelo DuckDB); RAM maior |
| GeoParquet | implementado; empata com o Parquet e custa 30 % mais em disco; serve para abrir a geometria em SIG (QGIS) |
| DuckDB | implementado; empata, arquivo 2,4× maior que o Parquet; motor de consulta comum sobre qualquer formato |
| JSONL | implementado; fica para os registros e exemplos versionados no git, pelo diff legível |
| CSV | implementado; listas e dicionários em JSON na célula |
| SQLite/SpatiaLite, PostGIS | não implementados; só se houver acesso simultâneo ou edição concorrente |

Evidência: `pdca/bancada_gavetas.jsonl` e `conceitos/gavetas.json` (`formato.decisao`). A base é sintética: a escolha
é reavaliada com a base real de Foz.

Métricas: ida e volta sem perda, tamanho em disco, tempo de gravação e leitura, p50/p95 de consulta por objeto e por
trecho, RAM máxima, auditabilidade e dependências extras. `gavetas.gravar` e `gavetas.ler` são o único ponto que
conhece o formato: trocá-lo não muda os de-para nem os cálculos.

### 3.2 Endereço espacial

- **Obra linear (adutora):** o endereço primário é `(eixo_id, progressiva, afastamento, cota)`, o referenciamento
  linear usado em rodovias. XYZ sai do eixo. Estacas de 20 m são unidades de associação e cálculo; a geometria
  guarda as mudanças entre estacas (curvas, PIs, conexões).
- **Obra localizada (ETA/ETE):** XYZ direto, com índice por setor ou célula esparsa para cruzar disciplinas.
- Nos dois casos, o índice só acelera a consulta. A coordenada exata fica na geometria.

### 3.3 Cuidados de referencial (entram como campos obrigatórios)

- **CRS horizontal** (EPSG) e **datum vertical** em toda geometria. Cota de prancha é ortométrica (ou arbitrária);
  a altitude do GPS do drone é elipsoidal. A conversão usa o MAPGEO2015 e fica registrada.
- **Distorção de escala UTM:** até cerca de 40 cm/km nas bordas do fuso. Armazenar em UTM; **medir comprimentos e
  volumes em verdadeira grandeza** (sistema topográfico local ou correção de escala). Uma adutora de 100 km pode
  cruzar dois fusos.
- **Comprimento horizontal × inclinado:** cada regra de serviço declara qual usa.
- **1 cm é resolução de endereço, não exatidão.** A exatidão vem da fonte e da georreferência (`georef_prancha.py`
  já devolve a incerteza).

## 4. Etapa 2: serviços complementares

Só depois do georreferenciamento. Lê só da base, nunca do documento. Serviços do MVP: escavação, escoramento,
reaterro, bota-fora, supressão, demolição e recomposição de pavimento (vala aberta) e caximbos (MND).

**Sondagens no local.** O furo é um objeto com geometria de ponto. Cada metro do eixo do tubo pega o furo mais
próximo dentro do raio de influência (`obras_lineares.json`), e é daí que saem o solo, a categoria de escavação, o
NA e o esgotamento. O trecho fora do raio de qualquer furo vira pendência. O fato do furo usado entra na memória de
cálculo do serviço.

1. O engenheiro escolhe ou confirma o método executivo por trecho (decisão no formato do `ARQUITETURA.md` §6).
2. O de-para 2 seleciona a regra e os fatos de que ela depende.
3. O Python calcula comprimento, área, volume e quantidade com fórmula, unidade e premissa explícitas
   (`valas.py`, `obras_lineares.py`, `escavacao.py`, `construtivos.py`).
4. Cada resultado grava as dependências: os `objeto_id`, os fatos usados e a versão da regra. Mudou um fato ou a
   regra, recalcula só o que dependia dele.

A IA pode apontar requisitos ou alternativas, mas não cria medida nem substitui o cálculo.

**Memória de cálculo lastreada.** Cada serviço (`gavetas.calcular`) grava a regra, a versão da regra e os
`fato_id` de que depende (do tubo e dos furos); cada fato aponta para a evidência e a evidência para o documento,
a página e o recorte. A mesma base com a mesma versão das regras dá sempre a mesma EAP: a entrega é determinística.

## 5. Etapa 3: EAP e HTML

- O de-para 3 pendura cada serviço no nó da EAP, somando por trecho, etapa e unidade construtiva.
- Cada quantidade na EAP abre o caminho de volta: serviço → regra → fatos → evidência → recorte da prancha.
- O HTML do MVP mostra a EAP como eixo principal; a vista no mapa (ortofoto, pranchas, trechos) é o jeito de ver
  no local onde está cada item.
- Sem preço e sem prazo, como no restante do repositório.

## 6. MVP: o que fazer primeiro

| Passo | Entrega | Verificação |
|---|---|---|
| 1 | esquema das gavetas (§3.1) e os três de-para para **um** tipo de elemento: trecho de tubo de adutora | **feito (0.24.0)**: `tests/test_gavetas.py` |
| 2 | leitor atual de prancha (perfil/planta) gravando nas gavetas, com evidência | todo fato com evidência recuperável; o que não coube vira pendência |
| 3 | vala aberta de um trecho curto calculada só a partir da base | **feito em dados sintéticos**: bate com `obras_lineares.quantificar`; falta o trecho real |
| 4 | serviços pendurados na EAP e mostrados no HTML com o caminho até a prancha | clique na quantidade chega ao recorte da prancha |
| 5 | trocar o método do trecho (vala → MND) sem reler a prancha | **feito em dados sintéticos**: a decisão MND troca a regra sem reler documento |

Persistência no MVP: JSONL por gaveta em `saida/<obra>/base/`, no mesmo estilo de `extracao.jsonl` (dict puro,
reprodutível, fácil de auditar). GeoParquet/DuckDB ou PostGIS só depois de medir volume e consulta na adutora de
5 km e em carga sintética de 100 km (experimentos G05 e G08).

## 7. Experimentos que continuam valendo

Os experimentos G01–G09 da v0.1 continuam valendo, com dois ajustes:
- G01, G03 e G06 partem do que já existe (`pdf_cad.py`, `prancha.py`, `georef_prancha.py`, `valas.py`,
  `obras_lineares.py`) como linha de base, comparados com as alternativas;
- o esquema das gavetas e os de-para (G04 lógico) vêm **antes** de G01, para que os métodos de extração produzam
  saídas comparáveis.

O F1 por elemento precisa de uma regra de casamento com o gabarito (tolerância em XYZ e progressiva, atributos
obrigatórios). A planilha do contrato serve de conferência, mas é estimativa de projeto, não verdade independente.

**Princípio:** primeiro o fato guardado no lugar certo, com evidência; depois o serviço calculado a partir dele;
por fim a EAP, que é o que o usuário vê.

## 8. Estado em 01/11/2026 (rodadas 21 a 24)

| Peça | Onde | Estado |
|---|---|---|
| Gavetas, contrato e conferência | `conceitos/gavetas.json`, `camadas/gavetas.py` | feito; fato sem evidência ou fora do contrato é reprovado |
| Formato físico | Parquet (`formato.decisao`) | medido na rodada 21 (8× menor que o JSONL em 100 km); JSONL para o que vai ao git |
| De-para 1: documento → gaveta | `extrair_gavetas`: planilha Obras Lineares, sondagens, decisões, valas das redes, retornos da IA | ligado; valor vazio ou padrão do leitor não vira fato; IA entra como `inferido` com trecho |
| De-para 2: gaveta → serviço | regras `vala_aberta`, `mnd` (`obras_lineares`) e `vala_rede` (`valas`) | feito; paridade com o cálculo atual sobre os serviços gravados |
| De-para 3: serviço → EAP | `de_para_eap.json` (OL.01–07, RD.01–03, provisórios) | feito; a casar com a EAP do PR #18 |
| EAP no HTML | `eap_html.py` + aba EAP | feito; nó → serviço → fato → evidência; o JS só apresenta |
| Recálculo incremental | `calcular_incremental`, chave com a impressão da regra | feito; mudar um fato recalcula um objeto |
| Cavas | gaveta `superficies` (MDS em `.npz` com sha256), regra `cavas`, CV.01–03 | feito (rodada 5, 0.34.0); paridade 0 com `escavacao.calcular` |
| Setores da ETA | `obra.json` `gavetas.setores`, `setor_de`, `setor_dos_servicos`, EAP por setor | feito (rodada 5); a soma dos setores confere com o total |
| Escala | `scripts/bancada_calculo.py` | 100 km em 4,3 s; o 2º cálculo sem mudança reprovou no critério de 10 % |

**O que a tese mostrou até aqui.** Com as gavetas e os três de-para, cada quantidade da EAP leva até o documento, e
as revisões independentes do Fable acharam falhas concretas em cada rodada, corrigidas com teste: paridade cega ao
método aplicado, padrão do leitor virando fato, chave do incremental sem as constantes do MOS. O cálculo pelas
gavetas reproduz o atual em todos os testes. Nos dados sintéticos, a resposta é sim: o processo ficou mais orientado
e rastreável, sem perder o resultado.

**O que falta para fechar a tese:**
1. o build real de Foz (`python -m camadas.obra exemplos/foz/obra.json`, com `dados/foz/`), com `paridade.json` vazio
   e a aba EAP conferida pelo Caio;
2. ~~cavas~~ e ~~setores da ETA~~: feitos na rodada 5 (0.34.0); falta o MDS e os setores reais de Foz;
3. casar OL, RD e CV com a EAP codificada do PR #18, que agora está na `main`;
4. uma chave barata para o 2º cálculo, se o custo fixo de 1,4 s em 100 km incomodar;
5. o acesso do CI ao `vibe_code_metrics` (segredo `VCM_TOKEN`), para o balanço rodar no PR.

