---
name: georef-pranchas
description: Georreferencia pranchas de projeto em PDF vetorial (layers CAD) sobre a ortofoto do drone ou sobre coordenadas topográficas, usando camadas/pdf_cad.py e camadas/georef_prancha.py — pontos de controle + ICP, pranchas irmãs (CAD × CAD) e afim absoluta. Use ao sobrepor pranchas "sem escala" ou sem malha de coordenadas, ao diagnosticar prancha desalinhada, torta, espelhada ou com escala errada.
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
1. **Afim absoluta** — se algum elemento da prancha tem coordenada topográfica (furos de
   sondagem, marcos, vértices impressos): ajuste a afim com ≥3 pontos e use `M_absoluta` no
   obra.json. Uma prancha assim vira `controle_absoluto` e corrige o viés do GPS do drone
   (em Foz: 1,50 m em E).
2. **Pontos de controle + ICP** — para a prancha base. Meça 2–3 feições inequívocas na ortofoto
   (centro de prédio, fileira de tanques) com uma grade UTM de 10 m sobre um recorte, ache a
   mesma feição na prancha renderizada com grade de 100 pt e confira a **razão de aspecto** dos
   prédios (34×23 m ↔ 360×240 pt ⇒ 0,095 m/pt). `matriz_inicial(pt, utm)` e
   `registrar(pts_existentes, ortofoto, M_inicial=M0)`.
3. **Prancha irmã, CAD × CAD (o modo que mais rende)** — pranchas do mesmo modelo CAD diferem só por
   uma similaridade, mesmo com escala de plotagem diferente (0,077–0,095 m/pt em Foz):
   `registrar_cad(tracos, referencia, M_base, padrao_layers)` faz SIFT + RANSAC entre o raster das linhas
   da prancha e o das linhas da prancha base já georreferenciada (`obra.referencia_cad`). Aceite rígido:
   ≥ 50 correspondências, resíduo ≤ 15 cm, escala ±25 % e rotação ±5° da base. No `obra.json`:
   `irma`, `layers_irma` (layers da base usados de referência) e `layers_referencia` (da prancha).
   Contenção casou com escavação; elétricas com `SW_LAYOUT_01|EXIST`; layer sem nome → padrão `^`.
   Em Foz levou de 8 para **20/20 pranchas**. ICP fica como alternativa.
4. **Busca global automática** (`rot_norte_graus` + faixa de escalas) — só quando a prancha e o voo
   cobrem a mesma área; com área muito maior que o voo ela tende a falhar.

## 3. Confira SEMPRE visualmente
Desenhe as classes da prancha sobre a ortofoto reduzida (ver `docs/PLANO_FOZ.md`, "Conferência")
e olhe: meios-fios, tanques circulares e cantos de prédios precisam coincidir. Número bom com
imagem ruim = rejeite.

## Recorte do mapa
Sem `clip` no obra.json, `obra.prancha_vetorial` recorta a folha à área do levantamento + 25 m (carimbo e tabelas
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
