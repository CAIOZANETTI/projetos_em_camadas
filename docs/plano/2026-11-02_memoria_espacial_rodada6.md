# Plano — memória espacial, rodada 6: casar a EAP das gavetas com a EAP codificada

Pedido do Caio (02/11/2026): casar os códigos provisórios das gavetas (OL, RD e CV) com a EAP codificada do PR #18
(`camadas/eap.py`, `conceitos/eap.json`, `eap_geral.jsonl` e `servicos.jsonl`), e mostrar o avanço de forma visual
no chat. Método: o das rodadas anteriores (Opus gerencia, Sonnet executa, `vcm balanco`, aceite do Fable, PR).

## Objetivo

Toda quantidade das gavetas sai com o código completo da EAP codificada, `UNIDADE.SISTEMA.DISCIPLINA.PACOTE.ITEM`,
e os serviços do item. Exemplo: a escavação de vala do trecho "Entrada de água bruta" sai como
`U1.AB_ENTRADA.GEO.MOV.VAL`, serviço `escavacao`. Onde as duas EAP medem a mesma coisa, as quantidades são
conferidas uma contra a outra.

## Decisões do gerente (fixadas antes)

1. **Tabela de-para** em `conceitos/de_para_eap.json` (`codigo_eap` por saída): feita na etapa 1, com todos os itens
   e serviços conferidos contra `eap_geral.jsonl` e `servicos.jsonl`.
   - Vala (obras lineares e redes): `GEO.MOV.VAL`, com os serviços escavacao, escoramento, reaterro e bota_fora.
   - Pavimento: `CIV.PAV.REC`, ou `CIV.PAV.CAL` quando a chave é calçada; serviços demolicao e recomposicao.
   - Supressão: `GEO.MOV.SUP`.
   - Cavas: `GEO.MOV.ESC` e `GEO.MOV.REA`.
   - **Sem item**: `caximbos` (MND) e `area_cava_m2` saem como "sem código na EAP codificada", à vista, nunca com
     um código forçado.
2. **Unidade e sistema do objeto**, nesta ordem:
   - (a) fatos `unidade` e `sistema` do setor em que o objeto cai (setor declarado no obra.json com unidade e
     sistema);
   - (b) o sistema achado pelo `local` do trecho com as `chaves` de `conceitos/unidades_construtivas.json` (a mesma
     regra que `escopo_obra` já usa);
   - (c) `gavetas.unidade_sistema_padrao` do obra.json.

   Sem nenhum dos três, o serviço sai com "unidade e sistema não definidos": é pendência, e o código não é
   inventado. Mais de um sistema casando pelo `local` também é pendência.
3. **Conciliação**: onde a EAP codificada mede o mesmo código (ex.: `GEO.MOV.ESC`, volume das cavas pelos
   construtivos), a soma das gavetas tem de bater com a quantidade da EAP codificada. Diferença acima da tolerância
   é uma linha em `conciliacao_eap.json` e no resumo, nunca um erro que derrube o build. O que só uma das EAP mede
   aparece como "só nas gavetas" ou "só na EAP codificada".

## Etapas

| # | Etapa | Quem | Estado |
|---|---|---|---|
| 1 | Tabela de-para (`codigo_eap`), conferida contra os catálogos | Opus | feito |
| 2 | Unidade e sistema do objeto, código completo em cada serviço, pendência sem código | Sonnet | feito — `codigo_eap`, `unidade_sistema`, `anotar_codigo_eap`; formato conferido contra `eap.estrutura` |
| 3 | Conciliação das duas EAP e código real na aba EAP | Sonnet (mesmo executor, logo depois) | feito — `conciliar_eap`, `obra._conciliar_eaps`, tabela na aba; ajuste do gerente: só a medida do item (`mede`) e itens fora das gavetas só na contagem |
| 4 | Fechamento: testes, `vcm balanco`, aceite do Fable, PR | Opus; Fable | em andamento — 0.36.0, L032 |

## Emendas
- 02/11, **integração (gerente).**
  - A conciliação passou a usar só a saída marcada `mede` no de-para 3, a medida que o item declara na EAP
    codificada. Sem isso, escavação, reaterro e bota-fora de `GEO.MOV.VAL`, todos em m³, seriam somados quando a
    codificada passasse a medir vala.
  - Itens que as gavetas não medem (estacas, blocos) aparecem como "fora das gavetas" só na contagem, sem linha na
    tabela.
  - Merge com a 0.35.0 da outra sessão (#36, aba EAP codificada com `eap_painel`): a aba mostra as gavetas (com a
    conciliação) e depois o painel codificado; os testes de `_aba_projeto` passaram a simular também o painel.
  - Notas do executor, registradas e não mudadas:
    - a planilha troca "calçada" por "concreto" (`obras_lineares.py:290`), então `CIV.PAV.CAL` só aparece nas redes;
    - um `local` ambíguo ("Drenagem" casa DREN_DN400 e DN300) é pendência de propósito.
