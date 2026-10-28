# Changelog

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
