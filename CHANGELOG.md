# Changelog

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
