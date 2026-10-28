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
`{itens[], por_tabela, totais, desenhos_por_tabela{tabela: código do desenho}, fonte, fonte_cadastro}`. Cada item:
`{tabela, nome_tabela, item, codigo, descricao, un, q1, q2, etapa, material, local, alerta, cadastro}`,
onde `q1`/`q2` são as quantidades da 1ª/2ª etapa e `cadastro` é a especificação do cadastro de materiais Sanepar
(descrição, unidade, norma, situação, família, DN, PN, marcas homologadas) ou null. **Sem preço**: o escopo é o
do contrato; `por_tabela` e `totais` são contagens (decisão de 28/10/2026). `tubo_x_desenho` (rodada 6): por
prancha, o tubo principal das tabelas que apontam para ela, `{prancha, nome, tabelas, codigo, descricao, contrato_m,
desenho_m, diferenca_pct}`; o item comparado ganha `desenho = {prancha, medido_m, diferenca_pct}`.

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

---

# v3 — grupos por disciplina, intervenções, 4D, estacas e marcos

Chaves novas em `dados`. Tudo é calculado no Python; o front só seleciona e exibe (regra 12 do estilo).

| chave | conteúdo |
|---|---|
| `grupos` | `{grupo: [subgrupos]}` na ordem de exibição (`conceitos/disciplinas.json`) |
| `pranchas[].grupo/subgrupo` | disciplina da prancha (código Sanepar) |
| `pranchas[].layers[].grupo/subgrupo` | disciplina de cada layer CAD (o nome do layer pode mudar a da prancha, ex.: DRENAGEM → Civil › Drenagem) |
| `vetores[].grupo/subgrupo` | idem para camadas vetoriais (`Etapas`, `Intervenções`, `Levantamento`, `Civil`) |
| `vetores[id=estacas]` | pontos com `id, diametro_cm, comprimento_m, estrutura, cota_arrasamento` |
| `vetores[id=supressao]` | polígonos estimados `{tipo, categoria: supressao/limpeza, etapa, area_m2, altura_m, estimado: true}` + `resumo` por etapa |
| `vetores[id=marcos]` | marcos geodésicos `{nome, rede, distancia_m, CLASSIFICAÇÃO, SITUAÇÃO…}` |
| `intervencoes` | tipos de recorte `{id, nome, cor}` (`conceitos/intervencoes.json`) |
| `inventario` (rodada 7) | `{fonte, totais{pdfs, no_disco, falhou, nao_tentado, planta, detalhe, documento, no_mapa, plantas_fora_do_mapa}, resumo[{grupo, subgrupo, total, planta, detalhe, documento, no_mapa, fora_do_disco}], itens[{arquivo, pasta_drive, situacao, tipo, grupo, subgrupo, formato, paginas, mb, no_mapa, carimbo{titulo, folha, escala, data, fonte}}]}` (`camadas/inventario.py`) |
| `escavacao` (rodada 7) | `{cavas[{id, escavacao_m3, reaterro_m3, area_m2, base_m2, prof_media_m, prof_max_m, fundo_m[min,max], etapa, na_borda_do_levantamento}], total, modelo_m3, marcas{total, lidas, topo, sem_numero, fora_da_faixa, usadas}, bases_sem_marca, conferencia_crista{pontos, comprimento_m, mediana_m, p90_m, ate_1m}, parametros, fonte, premissas}` (`camadas/escavacao.py`) |
| `vetores[id=escavacao]` | contorno de cada cava com as mesmas propriedades da tabela, `estimado: true` |
| `valas` (rodada 7) | `{redes[{id, de_mm, fonte_de, criterio, extensao_m, quadro[{classe, nome, final, extensao_m, largura_m, profundidade_m, demolicao, demolicao_m2, recomposicao, recomposicao_m2, volume_vala_m3}]}], classes{id: {nome, cor}}, urbanizacao_m2, fonte, fora[], premissas}` (`camadas/valas.py`) |
| `fichas` (rodada 8) | `[{id, nome, piloto, identidade{arquivo, codigo, grupo, subgrupo, tipo, unidade, obra}, elementos[{id, nome, grupo, tracos, layers}], servicos[{elemento, servicos}], …}]`; hidráulica: `vistas[{caixa, escala_titulo, escala_afim, georreferenciada}], itens[{n, codigo, descricao, qtde, un, bloco, cadastro, contrato[]}], baloes[{n, item, centro_pt, ponta_pt}], itens_sem_balao, baloes_sem_item`; estrutura: `estacas, layer_estacas, layer_blocos, blocos[{rotulo, estacas, face_superior, arrasamento}], niveis, encaixe{inliers, total, residuo_mediano_m, escala, M, estruturas}` (`camadas/prancha.py`) |
| `elementos` (rodada 8) | `{id: {nome, grupo}}` das classes de elemento; `pranchas[].layers[].elemento` é o id da classe do layer (`conceitos/elementos.json`) |
| `vetores[id=blocos_forma]` | blocos lidos na forma `{rotulo, estacas, face_superior_m, arrasamento_m, ficha}` |
| `modelo3d.solidos` | `[{id, xy[[x,y]] relativo à origem, z0 (arrasamento), z1 (face superior)}]` extrudados no 3D (só com controle vertical) |
| `vetores[id=valas]` | trechos do tubo por classe `{rede, classe, tipo, cor, extensao_m, estimado}`; o front pinta cada trecho com `properties.cor` |
| `cronograma` | `{fonte, data_os, data_os_hipotese, prazo_dias, marcos[{id,dia,descricao}], atividades[{id,nome,inicio_dia,fim_dia,uc,etapa,peso_pct,origem_peso,elementos:{layers:{prancha:[layers]}, vetores:[], estacas:[ids], intervencoes:[tipos]}, n_elementos}], curva_s:{dia[], planejado_pct[]}}` |

## Interface

1. **Árvore por disciplina** na aba Camadas: Grupo › Subgrupo › (prancha › layers) e camadas vetoriais.
   - Checkbox de grupo e subgrupo liga e desliga tudo o que está abaixo.
   - Os layers de uma prancha podem cair em subgrupos diferentes; a prancha aparece em cada subgrupo que tiver layers seus.
   - Mantém os controles atuais de prancha (opacidade, georref, "só").
2. **Recorte classificado (intervenções)**: na ferramenta Área (ou num botão "Recortar intervenção"), depois de fechar
   o polígono o usuário escolhe o tipo em `intervencoes`.
   - A área em m² vem da medição UTM que já existe.
   - O recorte é uma anotação com `properties.intervencao` e a cor do tipo.
   - Lista e totais por tipo (somas de áreas já medidas são apresentação aceitável; não recalcular geometria).
   - A camada `supressao` aparece no grupo "Intervenções", com o resumo por etapa no painel.
3. **4D**: botão "4D" abre uma barra inferior com:
   - linha do tempo de `0…max(fim_dia)`, marcos MI;
   - data calendário = `data_os` + dias, com aviso "data da OS hipotética" quando `data_os_hipotese` e campo para trocar
     a data da OS (só muda o rótulo);
   - botões ▶ play / pausa e velocidade;
   - mini-Gantt das atividades;
   - curva S (pontos de `curva_s`, SVG simples, sem biblioteca).

   No dia `d`, cada elemento de cada atividade fica:
   - **oculto** se `d < inicio_dia`;
   - **destacado** (laranja, pulsante) se `inicio ≤ d ≤ fim`;
   - **normal** se `d > fim`.

   Elementos que não pertencem a nenhuma atividade ficam normais. Ao sair do 4D, tudo volta.
   O painel mostra as atividades em execução no dia e o % planejado (`curva_s`, interpolação linear é aceitável).
   No 3D, as estacas seguem a mesma regra.
4. **Estacas**:
   - no mapa, círculos com raio proporcional ao diâmetro;
   - no 3D, cilindros verticais do terreno (percentil 10 de z da nuvem) para baixo, com `comprimento_m`, cor por estrutura;
   - o clique mostra os atributos.
5. **Marcos geodésicos**: ícone triangular, popup com nome, rede, classificação, situação (destacar "DESTRUÍDO") e
   distância à obra.

## Teste (acrescentar a `scripts/testar_visualizador.py`)
- a árvore tem os grupos Civil, Hidráulica, Elétrica e automação, e o subgrupo Civil › Drenagem;
- desligar Civil esconde as pranchas ou layers do grupo;
- desenhar um polígono, classificar como "Supressão vegetal (desmatamento)" e ver o recorte na lista com área > 0;
- 4D: ir ao dia 100 (A04 e A05 em execução, A08 oculta), ao dia 600 (tudo concluído), play por 1 s sem erro;
  a curva S aparece;
- estacas no mapa e no 3D;
- marcos com popup;
- console sem erros nos dois cenários.
