# Memória espacial: de-para do documento à EAP (v0.2, 31/10/2026)

Status: arquitetura conceitual do MVP. Complementa `docs/ARQUITETURA.md` sem substituí-lo.

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
| 1 | classe de documento + elemento lido (ex.: prancha de perfil → tubo, cota de geratriz, estaca) | gaveta da base (tabela + campos obrigatórios) | `conceitos/de_para_extracao.json` |
| 2 | gavetas necessárias (tubo + terreno + solo + NA + pavimento) | regra de serviço (vala, escoramento, reaterro…) | `conceitos/de_para_servicos.json`, usando `valas.json`, `obras_lineares.json` |
| 3 | serviço calculado | nó da EAP (código, unidade de medida) | `conceitos/de_para_eap.json` |

Regras:
- **O que não tem gaveta vira pendência**, não texto solto. Uma gaveta nova é decisão de arquitetura (Opus/Caio),
  não improviso do extrator.
- **Gaveta vazia também é informação**: se a regra de serviço precisa do NA e não há sondagem no raio, sai
  pendência com o motivo, não um valor inventado.
- O de-para 2 diz de quais fatos cada serviço depende. É isso que permite trocar o método executivo (vala aberta ×
  MND) sem reler as pranchas, e reprocessar só o que uma revisão afetou.

## 3. Etapa 1: extrair e guardar

O ciclo já existente (inventário → extração → reavaliação → escada) continua igual. Muda o destino: cada fato sai
do leitor direto para a sua gaveta.

### 3.1 Gavetas da base (esquema mínimo)

| Gaveta | Um registro é | Campos principais |
|---|---|---|
| `objetos` | uma coisa física (trecho de tubo, bloco, estaca, furo de sondagem, peça) | `objeto_id` estável, `classe` (de `elementos.json`), `disciplina`, `unidade` |
| `geometria` | a forma do objeto | XY(Z) em SIRGAS 2000/UTM, ou `eixo_id` + progressiva inicial/final + afastamento (obra linear) |
| `fatos` | uma propriedade de um objeto | `objeto_id`, `propriedade`, `valor`, `unidade`, `natureza` (observado, projetado, inferido, decidido) |
| `evidencias` | de onde o fato veio | formato do `ARQUITETURA.md` §3: classe, documento, revisão, localizador (página, bbox, layer, ids), trecho literal, método, passe, executor |
| `pendencias` | o que faltou ou conflitou | gaveta, objeto, motivo, próximo passe da escada |

A identidade (`objeto_id`) é separada do endereço espacial. Um objeto pode ocupar vários trechos ou células; um
trecho pode conter vários objetos.

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

Lê só da base; nunca do documento.

1. O engenheiro escolhe ou confirma o método executivo por trecho (decisão no formato do `ARQUITETURA.md` §6).
2. O de-para 2 seleciona a regra e os fatos de que ela depende.
3. O Python calcula comprimento, área, volume e quantidade com fórmula, unidade e premissa explícitas
   (`valas.py`, `obras_lineares.py`, `escavacao.py`, `construtivos.py`).
4. Cada resultado grava as dependências: os `objeto_id`, os fatos usados e a versão da regra. Mudou um fato ou a
   regra, recalcula só o que dependia dele.

A IA pode apontar requisitos ou alternativas, mas não cria medida nem substitui o cálculo.

## 5. Etapa 3: EAP e HTML

- O de-para 3 pendura cada serviço no nó da EAP, somando por trecho, etapa e unidade construtiva.
- Cada quantidade na EAP abre o caminho de volta: serviço → regra → fatos → evidência → recorte da prancha.
- O HTML do MVP mostra a EAP como eixo principal; a vista no mapa (ortofoto, pranchas, trechos) é o jeito de ver
  no local onde está cada item.
- Sem preço e sem prazo, como no restante do repositório.

## 6. MVP: o que fazer primeiro

| Passo | Entrega | Verificação |
|---|---|---|
| 1 | esquema das gavetas (§3.1) e os três de-para para **um** tipo de elemento: trecho de tubo de adutora | schema validado em teste com dados sintéticos |
| 2 | leitor atual de prancha (perfil/planta) gravando nas gavetas, com evidência | todo fato com evidência recuperável; o que não coube vira pendência |
| 3 | vala aberta de um trecho curto calculada só a partir da base | bate com o cálculo atual de `obras_lineares.py` no mesmo trecho |
| 4 | serviços pendurados na EAP e mostrados no HTML com o caminho até a prancha | clique na quantidade chega ao recorte da prancha |
| 5 | trocar o método do trecho (vala → MND) sem reler a prancha | só os serviços do trecho mudam |

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
