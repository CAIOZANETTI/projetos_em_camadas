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
  cada rótulo uma vez; rótulo sobre hachura costuma faltar — deixe sem rótulo, não deduza.

## Sinônimos de layer
Layer novo sem classe: acrescente em `conceitos/elementos.json` **só o que o nome diz com segurança** (com fonte);
o resto fica "sem classe" para conferir com a projetista. Rode o teste `test_classe_de_elemento_pelo_layer`.
