---
name: georef-pranchas
description: Georreferencia pranchas de projeto em PDF vetorial (layers CAD) pela malha de coordenadas impressa (OCR), sobre coordenadas topográficas ou sobre a ortofoto do drone, usando camadas/pdf_cad.py e camadas/georef_prancha.py — malha, afim absoluta, pranchas irmãs (CAD × CAD) e pontos de controle + ICP. Use ao sobrepor pranchas "sem escala" ou sem malha de coordenadas, ao diagnosticar prancha desalinhada, torta, espelhada ou com escala errada.
---

# Georreferenciar pranchas PDF

Matriz final: 3×3 **pt → UTM** (pt = 1/72", espaço da página *exibida*, y para baixo).
Ela contém uma **reflexão** (y da folha para baixo, N para cima) — por isso
`georef_prancha.matriz_inicial` ajusta contra (E, −N). Nunca use `geo.ajustar(..., "similaridade")`
direto de pt para UTM: sai espelhado.

## 1. Inspecione a prancha
```python
from camadas import pdf_cad
pdf_cad.layers_pdf(pdf)                          # OCGs = layers do CAD
tr = pdf_cad.extrair(pdf)                        # já no espaço exibido (/Rotate tratado)
pdf_cad.resumo_layers(tr)                        # layer × nº × cores → monte as regras
```
Procure: rosa dos ventos (direção do norte), layers de "EXISTENTES" (referência para casar
com a foto), legenda de cores (etapas), texto com coordenadas (`E:745750.526`) — se houver,
use-as como pontos de controle exatos.

## 2. Escolha o modo (em ordem de confiança)
0. **Malha de coordenadas impressa** — procure layer com `GRADE`, `MALHA` ou `GRID` (`pdf_cad.layers_pdf`). Os
   rótulos (7182800, 745400) quase sempre vêm em fonte SHX, isto é, traço e não texto: `registrar_malha(tracos,
   padrao_layer, escala=1000)` agrupa os glifos, lê com OCR (`pip install pytesseract` + `apt-get install
   tesseract-ocr`), dá a cada linha o rótulo alinhado com ela e ajusta a afim. Malha só na moldura (sem linhas): o
   centro do rótulo marca a coordenada (modo "rótulos"). No `obra.json`: `"malha": "<regex do layer>"`, `"escala":
   1000`. Exige 4 valores distintos (3 com escala declarada, que tem de bater em ±0,5 %); leitura errada sai pelo
   resíduo. O recorte do mapa vira a janela da malha — serve para adutoras fora do voo.
   Foz: 15 folhas (AAT00/01/02/06, urbanização, drenagem) com resíduo de mm a 29 cm; os marcos E/N impressos na
   AAT00-01 caíram a 0,20 e 0,23 m. **Rótulo errado no próprio desenho existe**: na AAT00-05 o 744200 aparece em
   duas linhas a 200 m uma da outra e na AAT00-06 as linhas a 200 m dizem 743600 e 744000. Com 3 linhas a malha
   sozinha não sabe qual está errada; com a escala declarada sobram poucas afins (sentido do eixo × rótulo certo),
   e a folha vizinha decide: `"continuidade": {"vizinha": "aat00_04", "layer": "SJMH_ADUTORA_TUBO"}` no obra.json
   (`hipoteses_malha` + `escolher_por_continuidade`). Vence a hipótese em que o tubo **coincide** com o da vizinha
   na área que as duas janelas têm em comum (metros com par a ≤ 1,5 m, nos dois sentidos; ≥ 10 m e ≥ 3× a 2ª).
   Não use "menor sobreposição": cada folha desenha uma cauda de tamanho diferente além da emenda (21 m a ~190 m em
   Foz) e esse critério escolheu errado na AAT00-06. Confira a escolha em imagem (tubos das folhas em cores).
   Lotes e quadras não servem de testemunha aqui: as janelas de folhas vizinhas quase não se sobrepõem.
   **Croqui de localização engana o CAD × CAD**: ele é o mesmo em todas as folhas e casa consigo mesmo (a folha
   "herda" a afim da vizinha). Use `clip` na janela da planta antes de registrar folhas de uma mesma série.
1. **Afim absoluta** — se algum elemento da prancha tem coordenada topográfica (furos de
   sondagem, marcos, vértices impressos): ajuste a afim com ≥3 pontos e use `M_absoluta` no
   obra.json. Uma prancha assim vira `controle_absoluto` e corrige o viés do GPS do drone
   (em Foz: 1,50 m em E).
2. **Pontos de controle + ICP** — para a prancha base. Meça 2–3 feições inequívocas na ortofoto
   (centro de prédio, fileira de tanques) com uma grade UTM de 10 m sobre um recorte, ache a
   mesma feição na prancha renderizada com grade de 100 pt e confira a **razão de aspecto** dos
   prédios. `matriz_inicial(pt, utm)` e `registrar(pts_existentes, ortofoto, M_inicial=M0)`.
   **Cuidado com a escala**: em Foz a f004 começou com 0,095 m/pt "medido na foto" e ficou 7,9 % grande (a
   verdadeira, contra a GEOPLANTA, é 0,0882). O ICP não corrige isso (trava de ±10 %) e a nota de bordas não
   discrimina (~47 % dos traços a < 0,5 m de uma borda nas duas escalas). Use este modo só sem malha, sem
   coordenada topográfica e sem prancha absoluta para servir de irmã.
3. **Prancha irmã, CAD × CAD (o modo que mais rende)** — pranchas do mesmo modelo CAD diferem só por
   uma similaridade, mesmo com escala de plotagem diferente (0,077–0,095 m/pt em Foz):
   `registrar_cad(tracos, referencia, M_base, padrao_layers)` faz SIFT + RANSAC entre o raster das linhas
   da prancha e o das linhas da prancha base já georreferenciada (`obra.referencia_cad`). Aceite rígido:
   ≥ 50 correspondências, resíduo ≤ 15 cm, escala ±25 % e rotação ±5° da base. No `obra.json`:
   `irma`, `layers_irma` (layers da base usados de referência) e `layers_referencia` (da prancha).
   Contenção casou com escavação; elétricas com `SW_LAYOUT_01|EXIST`; layer sem nome → padrão `^`.
   Em Foz levou de 8 para **20/20 pranchas**. ICP fica como alternativa. A irmã herda a escala da base: enraíze a
   cadeia numa prancha absoluta ou com malha (a f004 passou a irmã da GEOPLANTA na rodada 5).
4. **Busca global automática** (`rot_norte_graus` + faixa de escalas) — só quando a prancha e o voo
   cobrem a mesma área; com área muito maior que o voo ela tende a falhar.

## 3. Confira SEMPRE visualmente
Desenhe as classes da prancha sobre a ortofoto reduzida (ver `docs/PLANO_FOZ.md`, "Conferência")
e olhe: meios-fios, tanques circulares e cantos de prédios precisam coincidir. Número bom com
imagem ruim = rejeite.

## Recorte do mapa
`clip` no obra.json; senão a janela da malha (`janela_pt` do registro); senão a área do levantamento + 25 m (carimbo e tabelas
ficam só na aba Pranchas). Folha com dois desenhos de afins diferentes: `clip` manual por desenho.

## Exportar para o QGIS
`sig.pontos_qgis` grava o `.points` (4 cantos da área útil) e `sig.geopackage` uma camada por prancha, com uma
feição por layer CAD (grupo/subgrupo nos atributos).

## Armadilhas conhecidas
- `/Rotate 270`: PyMuPDF devolve vetores e texto no espaço **sem rotação**; `pdf_cad` converte
  para o exibido. Afins vindas de outras ferramentas costumam estar no espaço exibido.
- ICP "encolhendo" a prancha sobre textura de grama: `refinar` limita a variação de escala a 10 %.
- Mapa de bordas da foto: só bordas longas (≥ 4 m) e proximidade com média zero, senão a busca
  prefere escalas pequenas.
- Folha com dois desenhos (ex.: FUNDACAO3 esquerdo/direito) tem duas afins: use `clip` por desenho.
- Plantas de detalhe têm outra escala: o critério de aceite as rejeita — marque pontos de controle.
- Duas georreferências que "passam" na nota de bordas podem diferir 4 m dentro da foto. Confira contra uma
  testemunha independente (malha, GEOPLANTA, marcos E/N impressos), não contra a própria foto.
