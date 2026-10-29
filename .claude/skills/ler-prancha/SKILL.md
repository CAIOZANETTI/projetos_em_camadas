---
name: ler-prancha
description: Lê uma prancha de projeto em PDF vetorial em camadas de entendimento — identidade (código, disciplina, unidade, localizada × linear), vistas e escala, tabelas da folha por OCR (relação de materiais, níveis), elementos pelo nome do layer ou pela geometria (estacas, blocos), vínculos (balão → item → código → cadastro/contrato; estaca do desenho → estaca com E/N) e serviços — com camadas/prancha.py e conceitos/elementos.json. Use quando o usuário quiser saber o que uma prancha contém, ligar elementos do desenho a itens de tabela ou serviços, georreferenciar estrutura sem malha, ou criar/ajustar sinônimos de layer.
---

# Ler a prancha em camadas

```python
from camadas import prancha, pdf_cad
fichas = prancha.etapa(cfg, pranchas, escopo, Path("saida/<obra>"))   # obra.json: "fichas": [...]
```
No `obra.json`, cada ficha declara o piloto:
```json
{"id": "f010", "piloto": "hidraulica", "layer_balao": "CISM_18_BLOCO_LISTA_PEÇAS",
 "layer_numero": "CISM_24_TEXTO_IND_LISTA_PEÇAS", "tabelas": ["16", "17"]}
{"id": "mod01_forma", "piloto": "estrutura", "pdf": "…FORMA….pdf", "escala": 50, "ancoras": "dados/<obra>/geotec/estacas.csv"}
```
O cache (`saida/<obra>/fichas_cache.json`) é por assinatura do PDF e da configuração: o OCR é lento.

## A ordem
1. **Identidade** — `identidade(pdf)`: código Sanepar, disciplina, tipo (planta/detalhe/documento), unidade, obra
   linear (`conceitos/tipos_prancha.json`, chave `linear`) ou localizada.
2. **Vistas** — `vistas()` separa os blocos de desenho; `escala_do_titulo()` lê "ESCALA 1:100" abaixo da vista;
   `escala_da_afim(M)` compara. **Folha de detalhe com várias vistas não tem uma afim só**: a vista em 1:100 nunca
   encaixa com a escala da folha irmã em 1:250 (Foz f010: estava 2,5× grande no mapa desde a rodada 5).
3. **Tabelas** — `grades()` acha a grade na imagem; `celulas()` lê célula a célula; `itens_da_tabela()` usa o
   cabeçalho ("DESCRI") para as colunas; `niveis_da_tabela()` para tabelas de nível ("PC9 a PC14…" vira a lista).
   `conferir_itens()` liga o código ao cadastro Sanepar e à tabela do contrato.
   Cabeçalho separado do corpo por linha dupla é outra grade: `grades()` junta as empilhadas de mesma largura
   (`_empilhar`) antes de filtrar. Colunas "1ª ETAPA / 2ª ETAPA" entram pela ordem em `q1`, `q2` (o OCR lê "1ª"
   como "4a").
   Variações já vistas (`_colunas`, `SINONIMOS_COLUNA`): "DISCRIMINAÇÃO · QUANT. · UND." com o código SAM numa
   coluna sem título logo depois do nº (042A); "Nº" pequeno lido vazio → a coluna antes do código (perfis AAT06);
   dois códigos na célula (tubo + flange) → fica o primeiro.
4. **Elementos** — pelo layer (`pdf_cad.elemento_do_layer`, `conceitos/elementos.json`, primeira regra que casa
   vence: grafismo antes de objeto) ou, se o layer é numerado por pena, pela geometria (`estacas_e_blocos`:
   círculos tracejados no diâmetro da estaca; retângulos de até 8 m que contêm estacas).
5. **Vínculos** — `baloes()`: número do balão → item da tabela; `registrar_pontos()`: estacas do desenho →
   estacas com E/N, sem correspondência prévia (RANSAC de similaridade com a escala da folha).
6. **Serviços** — `servicos(classes)`: cada classe de elemento lista os serviços que gera.

## OCR do texto SHX (medido, não opinado)
- O texto das pranchas é traço (SHX): `get_text()` devolve vazio. OCR sempre.
- **Tamanho da letra decide**: com a letra a 16–18 px o tesseract leu 6/6 cotas; a 25 px trocou todo 3 por 5
  (`_limpar` leva a letra a 18 px, tira bordas, corta justo).
- Célula numérica ou de rótulos é relida com `--psm 7` e lista de caracteres permitidos (`RELEITURA`).
- Número de balão: desenhe só os traços do layer do número (`_ocr_tracos`) e leia em três configurações;
  só vale leitura com um dígito por glifo (senão "4" no lugar de "11" vira "04") e vence a mais votada entre os
  números da tabela.
- Rótulo de elemento (PC12, P3): OCR da vista inteira em 130/160/200 dpi e atribuição do mais perto ao mais longe,
  cada rótulo uma vez. O que falta passa por uma 2ª leitura num recorte **redesenhado sem a hachura**
  (`desenho_sem_hachura`: tira os segmentos longos a 45°, não o layer — o rótulo pode estar no mesmo layer da
  hachura), com 70 pt de margem. Forma MOD01: 41/41. O que ainda faltar fica sem rótulo; não deduza.

## Número do balão
SHX: traços do layer do número (sem `layer_numero`, o layer com mais traços dentro dos círculos, o do próprio balão
incluído). Fonte do PDF: `palavras(pagina)` → `baloes(..., textos=…)` (sistema pneumático). A linha de chamada tem
de sair do círculo.

## Relação na folha irmã
Folha com balões e sem relação: `_relacao_da_familia` liga os balões à relação de uma irmã (mesma descrição no
código Sanepar, sem o número final), **só com os números que a irmã lista como "sem balão"** — Foz: itens 80–84 da
019 nos balões da 015–018. Resultado em `completa.familia = {relacao_em, validos, itens}`.

## Pilares
`pilares(pagina, blocos, escala)`: o quadrado preto do pilar é hachura de traços, não preenchimento. Raster a
144 dpi + abertura 9×9 deixa só as manchas cheias; vale a mancha quadrada dentro de um bloco com lado próximo do
nominal. Forma MOD01: 12 pilares, exatamente nos blocos P1–P12, lado 0,41 m.

## Vista de detalhe no mapa
`registrar_vista(linhas_pt, escala, ref_utm)`: encaixe da vista (com a escala do título) nas linhas UTM de uma
referência já georreferenciada (`"referencia_vistas"` na ficha): rotações de 90°, correlação por template e nota
F1 (precisão × revocação das linhas). Só aceita com **pico claro**: o 1º ao menos 15 % acima do 2º (sintético
certo: 29 %; referência sem o desenho: 8 %). Sem pico, a vista fica sem coordenada, com o motivo — não force.
Com a vista encaixada, os balões ganham `utm` e entram no mapa (vetor `pecas_baloes`).

## Escala do título
`escala_do_titulo(pg, caixa, tracos=tr, textos=palavras(pg))`: faixa abaixo da vista e, se nada, a de cima
(contenção: "ESC 1:50" em fonte acima); texto de fonte direto do PDF, senão OCR só dos glifos SHX.

## Lote (todas as pranchas no disco)
`lote(cfg, escopo, out)` (chave = caminho relativo à pasta do inventário; só desenho: `e_desenho`) dá a `ficha_leve` (identidade, vistas, escalas, nº de tabelas, layer de balão, nº de
balões, objetos por classe, % genérico) a todo PDF de desenho (tipo DE) da pasta do inventário; onde há balões,
roda a completa (relação de materiais por OCR × balões × tabelas do contrato que apontam para o desenho). Cache em
`saida/<obra>/fichas_lote_cache.json`; erro de PDF fica como `{"erro": motivo}`. `resumo_lote` vai para a linha
do inventário na aba Projeto (filtro "Com balões"). Mudou o algoritmo → suba `VERSAO` (entra na assinatura).

## Conferência visual (`camadas/diagnostico.py`)
O que antes era script avulso:
```
python -m camadas.diagnostico layers <obra.json> <prancha> <E> <N> <raio_m> saida.png   # layers em volta do ponto
python -m camadas.diagnostico inventario-layers <obra.json> layers.csv                    # todos os layers + classe
python -m camadas.diagnostico recorte arquivo.pdf x0 y0 x1 y1 saida.png                  # trecho da folha
```
Em Python: `sobrepor([(linhas_utm, cor, esp), …], centro, raio, saida, ortofoto=…)` para conferir georreferência
antes de aceitar; `afinar_ocr(pagina, {texto: caixa})` para escolher altura de letra × dpi.

## Sinônimos de layer
Layer novo sem classe: acrescente em `conceitos/elementos.json` **só o que o nome diz com segurança** (com fonte);
o resto fica "sem classe" para conferir com a projetista. Rode o teste `test_classe_de_elemento_pelo_layer`.
