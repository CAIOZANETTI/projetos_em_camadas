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
