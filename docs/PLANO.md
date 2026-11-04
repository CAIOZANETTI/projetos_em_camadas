# Plano de implementação — Projetos em camadas

> **Superado em 04/11/2026** por `docs/RECONSTRUCAO.md` (decisões e fases F0–F7). Mantido só como histórico; não use como plano.


> Atualização (out/2026): as Fases 1–4 avançaram na obra de Foz — ver `docs/PLANO_FOZ.md` (3D/ortofoto verdadeira, pranchas vetoriais por layer, georreferência automática, escopo por etapa, sondagens, `camadas/obra.py`).

## 1. O que eu entendi

| # | Entendimento | Status |
|---|---|---|
| 1 | O repositório guarda **códigos e skills** reutilizáveis para transformar levantamento (drone/satélite) + projeto (civil, hidromecânico, elétrico) num **HTML navegável em camadas**. | base criada |
| 2 | Primeira tarefa: montar o **mosaico** das fotos de drone (`irati/foto_drone`, 10 fotos DJI Mini 2, 17/09/2026). | ✅ feito — `camadas/mosaico.py` |
| 3 | Depois: buscar os **projetos** (pacote `1023. SAA_IRATI.zip`, 14,7 GB) e separar por disciplina e por camada. | ⏳ depende do zip (ver §6) |
| 4 | Sobrepor projeto × mosaico × satélite com **georreferenciamento** confiável. | ✅ folha 04/21 já registrada |
| 5 | O HTML precisa permitir **medir** (comprimento, área, ângulo, coordenada), **anotar** (notas técnicas, status, autor) e **extrair informação** (clicar numa linha e saber a camada). | ✅ visualizador v0 |
| 6 | O HTML de conceito (`EEB 10 Irati – drone × projeto`) é o ponto de partida: raster da folha separado por cor do CAD + foto ajustada por 5 pontos. | ✅ reaproveitado e evoluído |

Pontos que preciso que você confirme estão na §6.

## 2. Arquitetura

```
 fotos drone ─► mosaico.py ─► mosaico.jpg + .jgw/.prj/.json (SIRGAS 2000 / UTM)
                                   │
 satélite (Esri, online) ──────────┤
                                   ▼
 PDF/DWG/DXF ─► folha.py / cad.py ─► camadas (raster por cor | vetor por layer)
                                   │   + afim px→UTM (pontos de controle ou registro.py)
                                   ▼
                visualizador.py + templates/visualizador.html
                                   ▼
                   HTML único (offline) — Leaflet embutido
                   medições em UTM · anotações → GeoJSON/CSV
```

**Decisões**

- **Tudo em UTM SIRGAS 2000 no Python** (EPSG:31982 em Irati). O navegador só converte para exibir. Medidas são feitas no plano UTM, o mesmo das pranchas. O fator k (0,99952 em Irati) aparece na aba *Projeto*.
- **Reamostragem no Python, posicionamento no navegador.** Cada imagem vai com uma afim *pixel → UTM*. O navegador aplica uma `matrix()` CSS, sem reamostrar. Assim as linhas da prancha continuam nítidas em qualquer zoom.
- **HTML único e offline.** O Leaflet, as imagens (WebP) e os dados ficam embutidos. O satélite é opcional e online.
- **Anotações como GeoJSON (RFC 7946).** Abrem no QGIS e no pandas/geopandas. O CSV usa `sep=';'` e `decimal=','`.
- **Licenças.** O núcleo usa numpy, OpenCV, pyproj e Pillow (licenças permissivas). PyMuPDF (AGPL) e ODM (AGPL) entram só como ferramentas opcionais.

## 3. Já entregue nesta etapa (Fase 0)

| Módulo | O que faz | Resultado em Irati |
|---|---|---|
| `camadas/exif.py` | Lê GPS, altitude relativa, rumo e câmera (EXIF + XMP DJI) e calcula o GSD | GSD 1,99 cm/px a 58 m |
| `camadas/mosaico.py` | SIFT + RANSAC em todos os pares. Pares incoerentes com o GPS são descartados. Faz ajuste global em duas etapas (geometria relativa → similaridade aos GPS), costura pela foto mais a prumo e grava world file | 10/10 fotos, 21 pares, costura mediana 12 cm, RMSE GPS 0,98 m, GSD ajustado 2,05 cm/px (bate com o EXIF), 29 s em CPU |
| `camadas/registro.py` | Registro automático imagem↔imagem (SIFT) | Folha 04/21 → mosaico: 649 pontos, resíduo 7,6 cm |
| `camadas/folha.py` | PDF → raster → camadas por cor do CAD (desmistura o antisserrilhado), empacotamento em WebP, extração vetorial por layer PDF | Teste de ida e volta: IoU 1,00 nas camadas coloridas; cinza/preto 0,80–0,94 |
| `camadas/geo.py` | Ajuste similaridade/afim/homografia, resíduos, UTM, world file | — |
| `camadas/visualizador.py` + template | HTML único: camadas por disciplina, mosaico, satélite, folha recolorível, medir distância/área/ângulo/coordenada, notas com status, cortina de comparação, inspeção da camada sob o cursor, exportação GeoJSON/CSV | 2,8 MB |
| `scripts/exemplo_irati.py` | Pipeline completo do exemplo | `exemplos/irati/` |

## 4. Fases seguintes

### Fase 1 — Ingestão do projeto (pacote SAA_IRATI)
1. **Inventário** (`camadas/inventario.py`): percorre o zip sem extrair tudo (`zipfile`) e gera um `inventario.csv` com pandas, com caminho, extensão, tamanho, disciplina inferida (pasta/nome: `CIV`, `HID`, `ELE`, `EST`…), número da folha e revisão. Saída: tabela + resumo por disciplina.
2. **DWG → DXF** com ODA File Converter (`ezdxf.addons.odafc`). Fallback: LibreDWG.
3. **DXF → GeoJSON por layer** (`camadas/cad.py` com ezdxf): explode blocos, aproxima arcos e splines por segmentos, preserva atributos (texto, bloco, cota) e mapeia *layer → disciplina → camada* do visualizador por regras num YAML (`regras_layers.yaml`).
   Se o DWG estiver em coordenadas UTM, a sobreposição sai direta, sem pontos de controle.
4. **PDF**:
   - se o PDF tiver layers (OCG), extrai vetor por layer (`folha.vetores_pdf`);
   - se não tiver, rasteriza a 200 dpi e separa por cor (`folha.separar_por_cor`), como na folha 04/21.
5. **Quantitativos** com pandas: comprimento de tubulação por diâmetro e layer, contagem de blocos (válvulas, caixas, postes), áreas de edificação. Exporta para Excel.

### Fase 2 — Georreferenciamento das pranchas
1. Arquivo de pontos de controle por folha (`pontos/folha04.csv`: `x_px;y_px;E;N`), com relatório de resíduos por ponto e RMSE, como no georreferenciador do QGIS.
2. **Pontos automáticos pela malha de coordenadas**: as pranchas costumam ter a grade `E 546.800 / N 7.183.600` impressa. Extrair esses textos com PyMuPDF e casar com as linhas da grade dá os pontos de controle sem clicar.
3. Modo "clicar pontos" no próprio visualizador: um clique na prancha e outro no mosaico exportam o CSV de pontos.
4. **Pontos de controle em campo** (GNSS RTK, 4 a 6 alvos) levam o mosaico do erro de ~1 m do GPS do drone para ~3–5 cm. Isso é necessário se quisermos usar o resultado como as-built.

### Fase 3 — Visualizador v1
- Camadas vetoriais do DXF com atributos ao clicar (diâmetro, material, cota) e busca por texto (ex.: "VG-03", "DN 200").
- **Snap** das medições aos vértices do projeto.
- **Comparação temporal**: vários voos (seletor de data + cortina) para acompanhar a obra.
- Mosaicos grandes em **pirâmide de tiles** (WebP por nível) para passar de ~16 MB sem perder resolução.
- Visualizador de foto original: clicar na pegada abre a foto do drone e mostra o ponto correspondente.
- **Anotações compartilhadas.** Hoje ficam salvas no navegador, com exportação/importação. Opções:
  (a) publicar como Artifact com banco compartilhado;
  (b) arquivo GeoJSON no Drive/GitHub;
  (c) backend leve (Supabase/Firebase).
  A escolha é sua (§6).
- Relatório de anotações (PDF/Excel) gerado em Python a partir do GeoJSON exportado.

### Fase 4 — Automação e skills
- CLI única: `python -m camadas construir projeto.yaml`. O YAML lista fotos, pranchas, regras de layers e pontos de controle. Saída: pasta com mosaico, camadas e HTML.
- Skills do Claude em `.claude/skills/`: *mosaico-drone* e *projeto-em-camadas* (já criadas). Ainda faltam *ingestao-cad* e *pontos-de-controle*.
- Testes com dados sintéticos (`tests/`), já iniciados.
- Opcional: **OpenDroneMap** (`--fast-orthophoto` ou completo) para voos maiores. Gera ortofoto verdadeira + MDS. Com o MDS dá para fazer curvas de nível, perfis (Plotly) e volumes de corte/aterro (numpy).

## 5. Riscos e limitações conhecidas

| Risco | Mitigação |
|---|---|
| Mosaico não é ortofoto: árvores e telhados têm paralaxe de alguns decímetros | Costura pela foto mais a prumo. Para precisão use ODM + pontos de controle |
| Posição absoluta depende do GPS do drone (~1 m) | Pontos de controle em campo ou registro em base oficial |
| Fotos isoladas (mata/água) casam pouco | Validação dos pares pelo GPS. Fotos sem par entram posicionadas só pelo GPS e são sinalizadas no relatório |
| Cinza e preto do CAD se confundem na separação por cor | Preferir DXF ou PDF com layers. Usar a cor só como último recurso |
| Satélite Esri: termos de uso, sem cobertura z19 em Irati e bloqueado em visualizadores restritos | Camada opcional com crédito. Avaliar ortofotos oficiais (IAT/PR, prefeitura) |
| 14,7 GB de projeto | Inventário primeiro, depois processar só as folhas do escopo |

## 6. Preciso que você confirme

1. **Acesso ao projeto**: o `1023. SAA_IRATI.zip` (14,7 GB) não passa pelo conector do Drive desta sessão. Pode descompactar no Drive só a parte da **EEB 10**, ou montar uma pasta `projeto/` com os DWG/PDF das três disciplinas? Arquivos de até ~50 MB cada funcionam bem.
2. **Formato**: os projetos existem em **DWG/DXF**, ou só em PDF? E estão em coordenadas UTM? Isso define se precisamos de pontos de controle.
3. **Escopo**: só a EEB 10 ou todas as unidades do SAA Irati (um HTML por unidade ou um HTML geral)?
4. **Colaboração**: as anotações precisam ser **compartilhadas em tempo real** entre a equipe, ou exportar/importar GeoJSON basta por enquanto?
5. **Precisão**: o uso é visual (compatibilização, acompanhamento) ou precisamos chegar a as-built (pontos de controle em campo)?
