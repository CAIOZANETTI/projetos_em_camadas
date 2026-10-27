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
3. **Prancha irmã** — outras pranchas do mesmo projeto CAD têm a mesma escala/rotação e outro
   enquadramento: `registrar(pts, referencia, M_irma=M_base)` contra o raster das linhas de
   existentes da prancha base (CAD × CAD; `obra.referencia_cad`). Critério de aceite rígido
   (`aceitavel`: resíduo ≤ 0,25 m e ≥ 60 % dos pontos a < 0,5 m quando a referência é CAD).
4. **Busca global automática** (`rot_norte_graus` + faixa de escalas) — só quando a prancha e o voo
   cobrem a mesma área; com área muito maior que o voo ela tende a falhar.

## 3. Confira SEMPRE visualmente
Desenhe as classes da prancha sobre a ortofoto reduzida (ver `docs/PLANO_FOZ.md`, "Conferência")
e olhe: meios-fios, tanques circulares e cantos de prédios precisam coincidir. Número bom com
imagem ruim = rejeite.

## Armadilhas conhecidas
- `/Rotate 270`: PyMuPDF devolve vetores e texto no espaço **sem rotação**; `pdf_cad` converte
  para o exibido. Afins vindas de outras ferramentas costumam estar no espaço exibido.
- ICP "encolhendo" a prancha sobre textura de grama: `refinar` limita a variação de escala a 10 %.
- Mapa de bordas da foto: só bordas longas (≥ 4 m) e proximidade com média zero, senão a busca
  prefere escalas pequenas.
- Folha com dois desenhos (ex.: FUNDACAO3 esquerdo/direito) tem duas afins: use `clip` por desenho.
- Plantas de detalhe têm outra escala: o critério de aceite as rejeita — marque pontos de controle.
