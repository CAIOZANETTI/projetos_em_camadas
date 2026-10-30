# Changelog

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
