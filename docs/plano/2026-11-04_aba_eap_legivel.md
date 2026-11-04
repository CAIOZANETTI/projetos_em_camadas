# Rodada: aba EAP legível e interativa (04/11/2026, 0.68.0)

Pedido do Caio (04/11/2026): "pode melhorar a tabela na aba EAP numa nova rodada [...] a wbs eap não [está] em
formato legível e também não está interativa". A imagem que ele colou não chegou à sessão. O diagnóstico partiu da
captura do build da 0.66.0.

## Antes

| Medida | Valor |
|---|---|
| Largura da aba EAP (desktop 1 400 px) | 329 px (o painel lateral) |
| Rolagem da aba | 37 151 px, com 10 seções empilhadas |
| Elementos | 863 `<details>`, 26 tabelas |
| Contrato 211 | só Linha e UC/trecho visíveis; quantidade e situação depois de rolar para o lado |

## O que mudou

- **E1 (`camadas/eap_vista.py`)**: o dado da aba sai pronto do Python.
  - Seções com um resumo curto de cada uma.
  - Situações, com contagem, para os filtros.
  - A WBS em árvore: tipo → etapa → folha, com as linhas do contrato de cada folha.
  - O contrato agrupado em UC → trecho → linha.
  - Índice de busca normalizado (minúsculas, sem acento).
  - Para cada linha, as `redes` e as `pranchas` tiradas das evidências.
- **E2 (template)**:
  - modo amplo e sub-abas;
  - a WBS com busca, filtros e expandir/recolher;
  - o contrato legível, com detalhe ao abrir a linha;
  - links entre folha e linha;
  - "ver no mapa", que destaca e enquadra o trecho de vala da linha;
  - "abrir prancha".
- **E3**: build real, capturas, balanço, PR e merge.

## Depois (build real de Foz)

| Medida | Valor |
|---|---|
| Largura do painel | 1 036 px numa tela de 1 400 px (no celular, a largura toda) |
| WBS recolhida | 1 352 px de rolagem |
| Contrato | 45 linhas com "ver no mapa" e 49 com "abrir prancha" |
| `testar_visualizador` | 331 verificações, 0 falha (eram 274) |

As capturas ficam em `saida/foz/capturas/eap_1_wbs.png`, `eap_2_contrato_ver_no_mapa.png` e `eap_3_celular.png`,
fora do git.
