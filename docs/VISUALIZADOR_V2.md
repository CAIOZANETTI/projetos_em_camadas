# Visualizador v2 — pranchas vetoriais, etapas, escopo, sondagens e 3D

Contrato de dados entre o Python (`camadas/obra.py`) e o template
(`camadas/templates/visualizador.html`). Tudo continua num HTML único e offline
(`visualizador.gerar(..., "inline")`); para publicar como Artifact use `"cdn"`.

## Princípio: o vetor é preservado

As pranchas PDF da Sanepar são vetoriais e têm os **layers do CAD** (OCG), textos,
cotas e tabelas de material. Nada é rasterizado: cada prancha vai inteira em vetor e o
navegador desenha com `Path2D` em `<canvas>`. Isso permite ligar/desligar cada layer CAD,
medir sobre a geometria, clicar para identificar e buscar textos.

## Chaves novas em `dados`

### `pranchas[]` (gerado por `pdf_cad.pacote_vetorial`)

| campo | tipo | descrição |
|---|---|---|
| `id`, `nome`, `disciplina`, `pdf` | str | identificação |
| `largura`, `altura` | float | folha em pt (1/72"), origem no canto superior esquerdo, y para baixo |
| `layers[]` | `{nome, n, classe, cor}` | layers CAD na ordem de índice; `classe` = etapa/categoria quando há regra (ex.: `"1ª etapa"`) |
| `estilos[]` | `{s, f, w}` | contorno `#rrggbb` ou null, preenchimento ou null, largura em pt |
| `coords` | base64(gzip(Int32LE)) | pares (dx, dy) ×10 encadeados: ponto absoluto = soma acumulada / 10 (pt) desde (0,0), **contínua entre partes** |
| `partes` | base64(gzip(Uint32LE)) | 4 valores por subcaminho: `n_pontos, layer, estilo, flags` (flags: 1 fechado, 2 preenchido) |
| `n_partes`, `n_pontos` | int | tamanhos |
| `textos[]` | `{t, x, y, a, h, cor}` | spans de texto (pt), ângulo em graus (anti-horário), altura em pt |
| `M` | `[a,b,c,d,e,f]` ou null | pt → UTM: `E = a·x + b·y + c`, `N = d·x + e·y + f` (contém reflexão: y da folha para baixo) |
| `escala_m_pt` | float ou null | metros por pt (para medir na folha) |
| `clip_mapa` | `[x0,y0,x1,y1]` ou null | parte da folha a mostrar no mapa (implantação, sem carimbo/tabelas) |
| `georef` | `{ok, motivo, residuo_mediano_m, frac_05m}` | qualidade do georreferenciamento |

Decodificar com `DecompressionStream('gzip')`, de forma assíncrona e só quando a prancha
é ligada pela primeira vez.

### `etapas[]`
`{id, cor}`: `"1ª etapa"`, `"2ª etapa"`, `"3ª etapa (futura)"`, `"Existente a reestruturar"`, `"Existente a manter"`.
`layers[].classe` e `vetores[].geojson.features[].properties.etapa` usam esses ids.

### `escopo`
`{itens[], desenhos_por_tabela{tabela: código do desenho}, fonte}`. Cada item:
`{tabela, nome_tabela, item, codigo, descricao, un, q1, q2, etapa, material, local, preco}`,
onde `q1`/`q2` são as quantidades da 1ª/2ª etapa e `preco` é o unitário (pode ser null).

### `sondagens[]`
`{id, tipo, E, N, lon, lat, cota_boca, profundidade_m, na_m, nspt: [[prof_m, golpes]], camadas: [{de, ate, descricao, classe}], fonte}`.
Furos sem `lon/lat` aparecem só na lista.

### `modelo3d`
`{origem: [E0, N0, 0], n, pos_cm_b64 (Int32LE xyz em cm relativos à origem; z = altura sobre a decolagem), rgb_b64 (Uint8 rgb), cameras[]}`;
câmera: `{nome, centro [x,y,z] relativo, eixo [3], topo [3], angulo_vertical, tipo: "nadir"|"obliqua", focal_px, largura, altura}`.
Esses dois campos não usam gzip.

### `fotos`
`{nome_da_foto: dataURL webp}`: fotos reduzidas (nadirais e oblíquas).

## Funções da interface

1. **Pranchas no mapa**: camada canvas própria que desenha as partes dentro de `clip_mapa`
   com a afim pt → px de tela (pt → UTM → lon/lat → `latLngToContainerPoint`, com a afim
   local calculada por 3 pontos a cada redesenho). Na aba Camadas, por prancha: liga/desliga,
   opacidade, qualidade do georref e árvore de **layers CAD** (checkbox, cor, nº de traços).
   Botão "só esta etapa" filtra pelos layers de `classe` igual.
2. **Aba Pranchas**: visualizador da folha inteira (Leaflet `CRS.Simple` ou canvas com
   pan/zoom), com:
   - layers CAD;
   - busca de texto (lista de resultados → zoom e destaque);
   - medição de distância (em pt, convertida para m por `escala_m_pt`);
   - clique para identificar (layer, comprimento e, se fechado, área).
   Funciona também para pranchas sem georreferência.
3. **Identificar no mapa**: clique perto de um traço de prancha mostra prancha, layer,
   comprimento em m e área se fechado. As medições "grudam" nos vértices das pranchas
   visíveis (snap de 8 px).
4. **Aba Etapas & escopo**:
   - chips de etapa filtram as manchas (`vetores` com `etapa`), os layers com `classe` e a tabela;
   - tabela agrupada por `tabela`/`nome_tabela` com descrição, un, q 1ª, q 2ª e valor;
   - busca e totais por etapa;
   - situação por item (no escopo / fora / verificar) salva em `localStorage`, com exportação
     CSV (`;` e decimal `,`).
5. **Sondagens**: marcadores no mapa. O popup tem um gráfico SVG de NSPT × profundidade, a
   coluna de solo colorida por `classe` e a linha do NA.
6. **3D** (three.js r128 + OrbitControls embutidos):
   - nuvem `THREE.Points` com cores (RGB ou por altura) e controle de tamanho do ponto;
   - câmeras como pirâmides (oblíquas em laranja, nadirais em amarelo); clique abre a foto;
   - pranchas georreferenciadas visíveis desenhadas como linhas no nível do terreno
     (percentil 10 de z da nuvem);
   - medida 3D entre dois pontos da nuvem (distância e Δz).
7. **Fotos**: o vetor `cameras` (properties.foto) abre a foto do drone num diálogo.

## Teste

```bash
python -m camadas.obra exemplos/foz/obra.json   # gera saida/foz/visualizador.html
python scripts/testar_visualizador.py saida/foz/visualizador.html
```
O teste abre no Chromium (Playwright) e verifica:
- console sem erros;
- uma prancha ligada desenhando;
- o filtro de etapa;
- a busca de texto;
- o 3D renderizando com WebGL por swiftshader;
- capturas de tela em 1400 px e em 400 px de largura.
