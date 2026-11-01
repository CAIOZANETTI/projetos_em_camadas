# Repositórios e ferramentas com objetivo semelhante

Levantamento feito em outubro de 2026. As estrelas são aproximadas. A coluna *Uso aqui* diz o que já foi adotado neste repositório ou o que fica para depois.

## 1. Mosaico / ortofoto de drone

| Projeto | Licença | O que aproveitar | Cuidado | Uso aqui |
|---|---|---|---|---|
| [OpenDroneMap/ODM](https://github.com/OpenDroneMap/ODM) (~6,6k★) | AGPL-3.0 | Ortofoto verdadeira + MDS. Roda em Docker só na CPU. `--fast-orthophoto` processa poucas fotos em minutos | Precisa de 70–80 % de sobreposição. Usar como ferramenta externa | Fase 4, opcional, para voos maiores |
| [PyODM](https://github.com/OpenDroneMap/PyODM) / [NodeODM](https://github.com/OpenDroneMap/NodeODM) | BSD-3 / AGPL | Chamar o ODM a partir do Python, via REST | Exige o serviço Docker rodando | Fase 4 |
| [WebODM](https://github.com/WebODM/WebODM) (~4,2k★) | AGPL-3.0 | Referência de interface com medições | Pesado (Django/Postgres). Não gera HTML único | Inspiração de UX |
| [mapillary/OpenSfM](https://github.com/mapillary/OpenSfM) | BSD-2 | Como usar EXIF/GPS no bundle adjustment | Compilação em C++ | Estudo |
| [spifftek70/Drone-Footprints](https://github.com/spifftek70/Drone-Footprints) | verificar | Área de cada foto no terreno pelo XMP DJI (altitude, yaw, focal) | Erro de metros, sem costura | Ideia adotada: *prior* GPS+rumo+GSD em `mosaico.py` |
| [TextZip/OrthomosaicSLAM](https://github.com/TextZip/OrthomosaicSLAM), stitchers OpenCV diversos | variadas | Exemplos de ORB/SIFT + homografia | Encadeiam erros e saem sem georreferência | Evitado: ajuste global em vez de cadeia |

## 2. CAD / PDF → camadas

| Projeto | Licença | O que aproveitar | Cuidado |
|---|---|---|---|
| [mozman/ezdxf](https://github.com/mozman/ezdxf) (~1,5k★) | MIT | Iterar por layer e cor ACI, `virtual_entities()` para explodir blocos, `ezdxf.path` + flatten, addon `geo` (GeoJSON), addon `odafc` (DWG) | Conferir `$INSUNITS`. Hachuras e MTEXT dão trabalho |
| ODA File Converter | freeware | DWG → DXF em lote, o conversor mais confiável | Exige cadastro e não pode ser redistribuído |
| [LibreDWG](https://github.com/LibreDWG/libredwg) | GPL-3.0 | `dwg2dxf` por linha de comando | Leitura incompleta nas versões novas de DWG |
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) | AGPL / comercial | `get_drawings()` traz cor e layer de cada traço. `get_ocgs()` lista layers. Rasteriza a 200–300 dpi | AGPL. Só há layers se o PDF foi plotado com "criar layers PDF" |

## 3. Georreferenciar imagem no navegador

| Projeto | Licença | Observação |
|---|---|---|
| [publiclab/Leaflet.DistortableImage](https://github.com/publiclab/Leaflet.DistortableImage) | BSD-2 | Ajuste manual pelos 4 cantos. Bom para ajuste fino, mas tem muitas dependências |
| [IvanSanchez/Leaflet.ImageOverlay.Rotated](https://github.com/IvanSanchez/Leaflet.ImageOverlay.Rotated) | Beerware | Afim por 3 pontos. **Mesma ideia da nossa `AffineLayer`**, que é escrita à mão e tem ~25 linhas |
| MapLibre image source | BSD-3 | Imagem por 4 coordenadas. Pode deformar quadriláteros que não são paralelogramos |
| GDAL `gdal_translate -gcp` + `gdalwarp`; Georreferenciador do QGIS | MIT | Fluxo de referência e relatório de resíduos por ponto, a imitar na Fase 2 |

## 4. Medição, anotação e comparação

| Projeto | Licença | Observação |
|---|---|---|
| [geoman-io/leaflet-geoman](https://github.com/geoman-io/leaflet-geoman) (~2,4k★) | MIT | Editar geometrias (mover vértices). Candidato para a Fase 3 |
| [JamesLMilner/terra-draw](https://github.com/JamesLMilner/terra-draw) | MIT | Desenho que funciona com Leaflet, MapLibre e OpenLayers |
| [ljagis/leaflet-measure](https://github.com/ljagis/leaflet-measure) | MIT | Parado e quebra com Leaflet ≥ 1.8. Evitado |
| [digidem/leaflet-side-by-side](https://github.com/digidem/leaflet-side-by-side) | MIT | Cortina via CSS `clip`. **Técnica adotada** e reimplementada para panes |
| [python-visualization/folium](https://github.com/python-visualization/folium), [opengeos/leafmap](https://github.com/opengeos/leafmap) | MIT | Leaflet a partir do Python. Bom para protótipos, mas carrega JS de CDN (não funciona offline) e personaliza pouco |

## 5. Imagem de satélite de base

| Fonte | Situação |
|---|---|
| Esri World Imagery | Exige crédito e, pelos termos atuais, chave. Em Irati não há imagem no nível 19 (usamos até o 18). **Não embutir tiles no HTML** |
| Google / Bing | Só por API com chave |
| Sentinel-2 (Copernicus) | Livre, mas 10 m/px: serve só como contexto |
| IAT/PR, INDE/IBGE, Prefeitura de Irati | Não há WMS de ortofoto estadual confirmado para Irati. Consultar o IAT regional e o aerolevantamento cadastral da prefeitura |

## Lições aprendidas (e como entraram no código)

1. **Não encadear homografias.** Erros se acumulam. → `mosaico.py` resolve todas as fotos num sistema linear único.
2. **O GPS do drone é um ótimo filtro, mas não deve entrar no mesmo ajuste dos casamentos.** Testei os dois juntos e a escala "encolheu" 3,6× para reduzir os resíduos de costura. → Fizemos em duas etapas: geometria relativa primeiro, depois uma similaridade aos GPS. O GPS também valida os pares fracos (mata/água).
3. **Distorcer no Python, não no navegador.** O navegador só posiciona com uma afim. → `AffineLayer`.
4. **Trabalhar em UTM SIRGAS 2000 e medir no plano UTM.** Medir em pixels Web Mercator superestimaria as distâncias em ~11 % em Irati. → Afins lon/lat↔UTM com erro < 0,5 mm na área da obra, e fator k informado.
5. **DXF/DWG vale mais que PDF.** A camada sai exata e muitas vezes já em UTM. A separação por cor fica como plano B (cinza/preto ambíguos, como o teste confirmou).
6. **Toda transformação precisa de relatório de resíduos** (por ponto, por par, RMSE). → O `.json` do mosaico e o `registro_folha.json` trazem esses números.
7. **Licenças AGPL/GPL** (ODM, PyMuPDF, LibreDWG) só como ferramentas externas e opcionais.
8. **Plugins Leaflet antigos quebram.** Ferramentas simples (medir, ângulo, cortina) são escritas à mão, com poucas linhas.
9. **HTML único não grava em si mesmo.** As anotações ficam no navegador, com exportação/importação GeoJSON/CSV. Compartilhar em tempo real exige backend (decisão em aberto).
10. **Tamanho do arquivo.** Mosaico em WebP a 5 cm/px e camadas da prancha em WebP sem perdas, 3 por imagem. Acima de ~16 MB, usar pirâmide de tiles.

## 6. Memória espacial (rodada 21, 31/10/2026)

Levantamento feito só pela API de busca do GitHub (`search/repositories`); licença, estrelas e último push são os que a API devolveu em 31/10/2026 (estrelas arredondadas). Nada foi instalado nem executado: tudo abaixo é hipótese a testar. Os benchmarks de formato achados são pequenos e sem licença clara; servem de roteiro, não de resultado.

### 6.1 Formato das gavetas (G05, G08)

| Projeto | Licença | O que aproveitar | Cuidado | Uso aqui (hipótese) |
|---|---|---|---|---|
| [opengeospatial/geoparquet](https://github.com/opengeospatial/geoparquet) (~1,1k★, push 22/10/2026) | Apache-2.0 | Especificação: geometria em WKB, metadado `crs` em PROJJSON, `bbox` por coluna e por arquivo | Só geometria simples por linha; nossos fatos são tabelas largas com JSON em coluna | Candidato para `geometria`. Fatos e evidências ficam em Parquet comum, sem geometria |
| [duckdb/duckdb](https://github.com/duckdb/duckdb) (~42,7k★) e [duckdb/duckdb-spatial](https://github.com/duckdb/duckdb-spatial) (~720★, push 27/10/2026) | MIT | Consulta SQL direta sobre JSONL, CSV e Parquet, sem importar. `ST_*` para projeção e distância. Bom para p50/p95 de consulta por objeto e por trecho | A extensão spatial é separada do núcleo e a API muda entre versões. Fixar a versão no teste | Motor de consulta do G05/G08 por cima de qualquer formato, sem mudar o de-para |
| [geoarrow/geoarrow-python](https://github.com/geoarrow/geoarrow-python) (~96★) e [geoarrow/geoarrow](https://github.com/geoarrow/geoarrow) (~540★, spec) | Apache-2.0 / BSD-3 | Geometria em colunas Arrow nativas (sem WKB), ida e volta com pyarrow e geopandas | Projeto pequeno. Spec com último push em 05/2025 | Só se a leitura de WKB pesar no G08. Começar por GeoParquet |
| [geopandas/pyogrio](https://github.com/geopandas/pyogrio) (~340★) e [geopandas/geopandas](https://github.com/geopandas/geopandas) (~5,3k★) | MIT / BSD-3 | Leitura e escrita vetorizada de GeoPackage e GeoParquet. GeoPackage (SQLite) tem índice espacial e é um arquivo só | `opengeospatial/geopackage` é só a especificação (licença `NOASSERTION`). GeoPackage grava mal listas e JSON aninhado | GeoPackage como candidato de entrega para o QGIS. Medir contra Parquet |
| [simonw/sqlite-utils](https://github.com/simonw/sqlite-utils) (~2,2k★) | Apache-2.0 | SQLite com JSON em coluna, `upsert` e FTS em poucas linhas, sem ORM | SpatiaLite é difícil de instalar: `malexer/spatialite` (MIT) está parado desde 2019 e `pyspatialite` está arquivado | SQLite puro (sem SpatiaLite) como candidato transacional. Geometria como WKB/JSON e `bbox` em colunas |
| [ignfab/geoparquet-benchmark](https://github.com/ignfab/geoparquet-benchmark), [jtmiclat/geoparquet-compression-benchmark](https://github.com/jtmiclat/geoparquet-compression-benchmark), [Kanahiro/spatial-sort-benchmark](https://github.com/Kanahiro/spatial-sort-benchmark), [piclem/benchmark-geospatial-vector-format](https://github.com/piclem/benchmark-geospatial-vector-format) | GPL-3.0 / sem licença | Roteiros de medição: codec de compressão (zstd × snappy), ordenação espacial antes de gravar, shapefile × GPKG × GeoParquet × GeoJSON | Quase sem estrelas, dados diferentes dos nossos (milhões de feições, não milhares). `ignfab` é GPL-3.0: ler a metodologia, não copiar código. Os demais não têm licença | Copiar só a lista de métricas para o G05: tamanho, tempo de gravação e leitura, RAM, consulta |

### 6.2 Referenciamento linear: estaca, progressiva, afastamento

A busca devolveu pouco em Python puro. Não apareceu biblioteca de LRS para dutos ou ferrovias; o que existe é de rodovia ou plugin de QGIS. O núcleo continua sendo `shapely`.

| Projeto | Licença | O que aproveitar | Cuidado | Uso aqui (hipótese) |
|---|---|---|---|---|
| [shapely/shapely](https://github.com/shapely/shapely) (~4,5k★, push 27/10/2026) | BSD-3 | `line_locate_point` (progressiva de um ponto), `interpolate` (ponto na progressiva), `substring` (trecho), `offset_curve` (afastamento). Versões vetorizadas | Trabalha no plano: progressiva em UTM, sem correção de escala nem cota. `line_locate_point` projeta no ponto mais próximo e erra em eixos que se cruzam ou fazem laço | Base do `(eixo_id, progressiva, afastamento)`. Teste de ida e volta XY → LRS → XY com tolerância de 1 cm |
| [tariqshihadah/linref](https://github.com/tariqshihadah/linref) (~11★, push 12/10/2026) | MIT | Eventos lineares e pontuais sobre rotas, no pandas/geopandas: sobreposição de intervalos, dissolução, junção por trecho | Poucas estrelas, projeto de uma pessoa, pensado em rodovia. Verificar suporte a rota com mais de um segmento | Referência de API para "o que ocorre entre a estaca 10 e a 25" (sondagem × vala). Avaliar antes de reescrever |
| [blazek/lrs](https://github.com/blazek/lrs) (~14★, push 05/2026) | GPL-2.0 | Modelo conceitual de rota, medida (M), calibração e erros de rota. Plugin QGIS | GPL-2.0 e depende do QGIS. Só ler o modelo, não importar | Lista de erros de LRS a testar (rota com buraco, medida decrescente, trecho duplicado) |
| [Valery35/routeliner](https://github.com/Valery35/routeliner) (~1★, push 25/10/2026) | GPL-2.0 | Estacionamento em PK+ (estaca + resto) e livros de estacas em QGIS 3.40 | Só 1 estrela, GPL-2.0, plugin | Só como exemplo de formatação "estaca + metro" (por exemplo 12+7,50) |
| [Ludwig-K/QGisLinearReference](https://github.com/Ludwig-K/QGisLinearReference) (GPL-3.0) e [geoCML/open-lrs-tools](https://github.com/geoCML/open-lrs-tools) (GPL-2.0) | GPL | Operações ponto-sobre-linha e linha-sobre-linha em QGIS | Pouquíssimas estrelas, copyleft, QGIS | Apenas conferência cruzada no QGIS do que o Python calcular |

### 6.3 Extração de desenhos de engenharia, com saída estruturada e citação

Para desenho de engenharia (carimbo, planta, perfil) quase não há projeto aberto e maduro: o único achado direto, [Night-E-ye/Drawing_ocr_extractor](https://github.com/Night-E-ye/Drawing_ocr_extractor), tem 0 estrela e usa pdfplumber em peças mecânicas. Servem as ferramentas gerais de documento.

| Projeto | Licença | O que aproveitar | Cuidado | Uso aqui (hipótese) |
|---|---|---|---|---|
| [google/langextract](https://github.com/google/langextract) (~39k★, push 30/10/2026) | Apache-2.0 | Extração com **ancoragem na fonte**: cada campo volta com o trecho exato e a posição no texto. Esquema por exemplos. Aceita vários modelos | Trabalha sobre texto, não sobre geometria. O LLM pode devolver trecho parafraseado: conferir que o trecho existe literalmente | Modelo para o campo `trecho literal` da evidência. Aplicar sobre o texto do OCR do carimbo e das tabelas (G01) |
| [docling-project/docling](https://github.com/docling-project/docling) (~70k★, push 31/10/2026) | MIT | Layout, tabelas e ordem de leitura com bbox por elemento, OCR integrado, exporta JSON | Pesado (modelos). Tabela de prancha CAD girada ou sobre desenho pode falhar. Medir no nosso acervo | Concorrente do leitor atual de tabelas por OCR no G01. Comparar F1 por campo |
| [jsvine/pdfplumber](https://github.com/jsvine/pdfplumber) (~10,9k★) e [camelot-dev/camelot](https://github.com/camelot-dev/camelot) (~3,8k★) | MIT | Palavras, linhas e retângulos com coordenadas. Tabelas por linhas desenhadas (Camelot "lattice") | Só PDF com texto/vetor. Em PDF plotado de CAD, o texto costuma vir quebrado em letras | Linha de base barata para tabelas e carimbo. Bbox vira o localizador da evidência |
| [Unstructured-IO/unstructured](https://github.com/Unstructured-IO/unstructured) (~15,7k★) | Apache-2.0 | Particiona PDF e imagem em elementos tipados com metadados de página e coordenadas | Muitas dependências. Parte dos recursos fica no serviço pago | Segunda opinião no G01, não base |
| [microsoft/table-transformer](https://github.com/microsoft/table-transformer) (~2,9k★) | MIT | Detecção de tabela e de estrutura de tabela (linhas, colunas, células) | **Arquivado**; último push 06/2024. Treinado em artigos e documentos, não em pranchas | Só se tabelas sem linhas desenhadas falharem nas outras |
| [pymupdf/pymupdf4llm](https://github.com/pymupdf/pymupdf4llm) (~2,3k★) | AGPL-3.0 | PDF para Markdown com tabelas e bbox | AGPL-3.0, como o PyMuPDF (ver lição 7). Só como ferramenta externa e opcional | Não adotar no núcleo. Comparação isolada, se necessário |

### 6.4 Proveniência, linhagem e invalidação incremental

| Projeto | Licença | O que aproveitar | Cuidado | Uso aqui (hipótese) |
|---|---|---|---|---|
| [trungdong/prov](https://github.com/trungdong/prov) (~145★, push 31/10/2026) | MIT | Modelo W3C PROV em Python: `Entity`, `Activity`, `Agent`, `wasDerivedFrom`, `wasGeneratedBy`. Serializa em PROV-JSON e PROV-N | Vocabulário amplo demais para o nosso caso. Gerar em lote pesa se for um grafo por fato | Só exportar: documento = entidade, passe de extração = atividade, executor = agente. Interno continua JSONL |
| [OpenLineage/OpenLineage](https://github.com/OpenLineage/OpenLineage) (~2,7k★) e [MarquezProject/marquez](https://github.com/MarquezProject/marquez) (~2,3k★) | Apache-2.0 | Esquema de eventos de linhagem (`job`, `run`, `dataset`, facetas). Marquez é o servidor de referência | Feito para pipelines de dados com orquestrador e serviço. Excesso para uma execução local | Copiar a ideia de facetas (versão da regra, hash da entrada) nos eventos de `servicos`. Não subir servidor |
| [SQLMesh/sqlmesh](https://github.com/SQLMesh/sqlmesh) (~3,3k★, push 31/10/2026) | Apache-2.0 | Versão de cada modelo por impressão digital (hash do código + dependências) e "só recalcula o que mudou". Distingue mudança que quebra de mudança que não quebra | Acoplado a SQL e a banco. Aproveitar o conceito | Hash da regra + hash dos fatos de entrada = chave de cache do serviço (G06). Mudou o fato, recalcula só os dependentes |
| [treeverse/dvc](https://github.com/treeverse/dvc) (~16k★) e [snakemake/snakemake](https://github.com/snakemake/snakemake) (~2,9k★) | Apache-2.0 / MIT | `dvc.yaml`: dependências, saídas e hashes por etapa; reexecuta só o que mudou. Snakemake faz o mesmo por regras e arquivos | Ambos supõem arquivos por etapa, não fatos individuais. Snakemake exige DSL própria | Referência de granularidade: aqui a unidade é o fato, não o arquivo. Comparar custo de recálculo no G08 |
| [pydoit/doit](https://github.com/pydoit/doit) (~2,1k★) | MIT | Build incremental em Python puro: `file_dep`, `targets` e banco de checksums | Granularidade de arquivo | Opção leve se for preciso invalidar por documento (hash do PDF) antes de reler |

### 6.5 Quantitativos de obra e métricas de avaliação

Nada achado calcula vala de saneamento com a regra do MOS Sanepar: a busca por "trench excavation volume" não devolveu nada e a de terraplenagem devolveu só scripts de topografia sem estrelas. Os projetos abaixo valem pelo formato e pelas métricas.

| Projeto | Licença | O que aproveitar | Cuidado | Uso aqui (hipótese) |
|---|---|---|---|---|
| [IfcOpenShell/IfcOpenShell](https://github.com/IfcOpenShell/IfcOpenShell) (~2,9k★, push 30/10/2026) | LGPL-3.0 | `ifcopenshell.util` e `Qto` para quantidades por elemento; trabalha com `IfcAlignment` e relações de quantidade (`IfcElementQuantity`) | LGPL-3.0 (ligação dinâmica é ok; não copiar código). Cobertura de obras lineares em IFC ainda desigual | Modelo de saída para `servicos`: quantidade, unidade, método de medição e elemento de origem. Exportar IFC é opcional e futuro |
| [datadrivenconstruction/QuantityTakeoff-Python](https://github.com/datadrivenconstruction/QuantityTakeoff-Python) (~35★, 12/2023) | GPL-3.0 | Agrupar elementos por filtro e somar quantidades (BIM) | GPL-3.0, parado desde 2023, 35 estrelas | Só leitura de ideias de agrupamento. Não copiar |
| [chakki-works/seqeval](https://github.com/chakki-works/seqeval) (~1,2k★, push 08/2024) | MIT | Precision, recall e F1 por classe e micro/macro, com relatório | Feito para sequências de rótulos (NER), não para campos de documento. Parado desde 2024 | Só o relatório; o cálculo por campo é simples e cabe em poucas linhas nossas |
| [huggingface/evaluate](https://github.com/huggingface/evaluate) (~2,5k★) | Apache-2.0 | Interface comum de métricas (precision, recall, F1) | Genérica e de ML; não casa objeto por posição | Não adotar: o casamento com o gabarito por tolerância em XYZ e progressiva precisa ser escrito aqui |
| [rapidfuzz/RapidFuzz](https://github.com/rapidfuzz/RapidFuzz) (~4,2k★) | MIT | Distância e razão de texto para comparar valor extraído e gabarito (OCR com erro de uma letra) | Limiar de similaridade é decisão nossa e muda o F1 | Regra de casamento de campos de texto (código, nome de prancha) no gabarito |
| [pydantic/pydantic](https://github.com/pydantic/pydantic) (~29k★) | MIT | Validar a saída do leitor/LLM contra esquema tipado antes de gravar na gaveta | Já acoplado ao contrato de `conceitos/gavetas.json`? Verificar para não duplicar a validação | Camada de validação entre extração e `gavetas.gravar`. O que reprovar vira pendência |

### Hipóteses para testar

Os G01–G09 são os experimentos do documento de concepção v0.1 (G02 granularidade, G04 endereçamento, G07 revisão incremental, G09 ETA/ETE).

1. G05: gravar `geometria` em GeoParquet, `fatos` e `evidencias` em Parquet comum e comparar com JSONL e SQLite (via DuckDB), nas métricas já listadas em §3.1.1.
2. G05/G08: consultar os formatos com DuckDB e medir p50/p95; a decisão segue o critério fixado em `docs/plano/2026-10-31_rodada21.md` §4.
3. G08: repetir com a carga sintética de 100 km e ordenar por progressiva antes de gravar (técnica do `spatial-sort-benchmark`), medindo o ganho de leitura por trecho.
4. G04: testar ida e volta XY → (eixo, progressiva, afastamento) → XY com `shapely`, incluindo eixo com laço e fuso diferente, tolerância de 1 cm.
5. G04: avaliar `linref` para cruzar intervalos de estaca (furo de sondagem × vala) antes de escrever código próprio.
6. G01/G03: rodar `docling`, `pdfplumber`/`camelot` e o leitor atual nas tabelas e carimbos de 10 pranchas e comparar F1 por campo; casar texto com `rapidfuzz`.
7. G01: exigir que todo valor extraído por LLM traga o trecho literal (padrão do `langextract`) e rejeitar o que não aparecer no texto do OCR.
8. G07: chave de cache do serviço = hash da regra + hash dos fatos de entrada (ideia do SQLMesh/dvc); mudar um fato e conferir que só os serviços dependentes são recalculados.
