---
name: obras-lineares
description: Calcula a vala de cada trecho de tubo (obra linear) pelo MOS Sanepar — largura L = D + SL + X + Y, escoramento acima de 1,25 m, escavação, reaterro, bota-fora, supressão vegetal e pavimento a demolir e recompor por tipo — com solo e lençol freático da sondagem mais próxima (esgotamento) e pavimento pela cor da ortofoto, VCA ou MND; confere a aba Obras Lineares da planilha Sanepar e concilia com os itens em metro do CUSTO CIVIL. Use quando o usuário falar de obras lineares, tubulação dentro da ETA, vala, escoramento, esgotamento, MND/HDD, supressão ou recomposição de pavimento de uma rede.
---

# Obras lineares

Código: `camadas/obras_lineares.py`. Regras: `conceitos/obras_lineares.json`. Referência do MOS (fórmula e Tabela I):
`referencias/sanepar/MOS_largura_de_vala_tabela_I.png`. Sem preço: só geometria e serviço associado.

## Onde estão os dados
- **CUSTO CIVIL**: os itens em metro (`1.2 ENTRADA DA ADUTORA DE ÁGUA BRUTA … M 57,3`), com o código de vala
  (`CVCAFD1000` = VCA, FD DN1000) e a prancha (coluna I).
- **Obras Lineares** (colunas V–BC): local, DN, tipo do tubo, sondagem inicial/final, NA, solo, profundidade média,
  escoramento, comprimento total (AE), método construtivo (VCA/MND), largura, área, escavação, reaterro,
  empolamento, bota-fora, supressão vegetal (AM), pavimentos 1 a 5 (tipo, comprimento, área) e observações.
- Os tubos **dentro da ETA** (água bruta, interligações com os Actiflo, lodo) são obra linear da **Unidade 1**,
  não AAT. Sistemas `AB_ENTRADA`, `AB_INTERLIG`, `LODO_SAIDA`, `LODO_RETORNO` em `conceitos/unidades_construtivas.json`
  (tipologia `rede_eta`).

## Regras
1. **Largura (MOS)**: L = D + SL + X + Y. SL pela Tabela I (material, DN, junta); X = 0,10 m só se escorado;
   Y = 0,10 m por metro ou fração além de 2 m. Ex.: FD DN1000 a 2,40 m escorado = 1,0 + 0,90 + 0,10 + 0,10 = 2,10 m.
2. **Escoramento**: profundidade > 1,25 m (coluna AD: `=SE(AC>1,25;"sim";"não")`, NR-18).
3. **VCA**: escavação = comprimento × L × profundidade; reaterro = escavação − π·DN²/4 × comprimento;
   bota-fora = volume do tubo × empolamento (1,3); pavimento = comprimento do tipo × L; supressão = área × fração
   vegetada (observação "x %" ou ortofoto).
4. **MND** (escolha do usuário, `obras_lineares.metodo` no obra.json): sem vala; caximbos 1 a cada 80 m, 4,5 m².
   Citar as orientações de HDD de `mnd.orientacoes`, sem dimensionar pelo executor.
5. **Sondagem**: com o eixo em UTM (`no_eixo`), cada metro na sondagem mais próxima dentro do raio de influência
   (60 m, calibrar); sem eixo, metade na inicial e metade na final da planilha. Solo pela descrição das camadas até o
   fundo da vala (1ª/2ª/3ª categoria); **NA mais raso que o fundo = esgotamento de vala**. Ids tolerantes:
   SP-02 = SP02 = SPT-2.
6. **Pavimento pela ortofoto/satélite**: verde = grama (e supressão), preto = asfalto, cinza claro = concreto/calçada
   (`asfalto_v_max`, calibrar). Paver e lajota só pelo usuário.

## Como rodar
```bash
python -m camadas.obras_lineares "211 - SAA Foz do Iguaçú.xlsx" --sondagens dados/foz/geotec/sondagens.json --saida saida/foz
```
No build (`python -m camadas.obra exemplos/foz/obra.json`) a etapa lê `obras_lineares` do obra.json, cruza com
`sondagens`, grava `obras_lineares.csv` e `obras_lineares_conciliacao.csv` em `saida/` e põe a tabela na aba
Projeto do HTML.

## Conferir sempre
- `confere_planilha`: diferença entre o cálculo e a planilha (tolerância 1 %); `alertas`: sem profundidade, fora da
  Tabela I, esgotamento, trecho sem sondagem, pavimentos que não somam o comprimento.
- Conciliação: cada item em metro do CUSTO CIVIL × trechos (Actiflo = micro areia); tubulação aérea fica sem vala.
- Achados do protótipo de Foz (30/10): linha 9 sem profundidade (reaterro −0,49 m³), supressão de 66 % no lodo sem
  observação, 1.9 drenagem do Actiflo 600 sem comprimento, 1.10 água potável fora da tabela, resumo B6:T13 com
  "PVC DN 100 – 119,3 m" de outro modelo.

## Pendente
Eixo de cada trecho nas pranchas 004/009/010 (layer do tubo) → `no_eixo` com a ortofoto, para trocar a premissa da
planilha (pavimento, supressão, sondagem inicial/final) pela posição real, e o trecho como linha na aba Obra.
