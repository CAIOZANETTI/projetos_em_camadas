# D9: três observações do revisor (decisão do Caio 03/11/2026)

## Regras
1. DE no fallback fora da Tabela I do MOS: `de_mm` do trecho quando vem (valas.py e adaptador passam); senão DN -> DE por material
   (`conceitos/lineares.json`, `vala.largura_fora_da_tabela.de_por_dn`: ISO 2531 / NBR 7675 para FD e PVC DEFoFo; PEAD/PE/PP DE = DN);
   fora da tabela, DE = DN com alerta "DE estimado igual ao DN". Saída ganha `de_m` e `fonte_de`.
2. MND: `fonte_largura` = "não se aplica (MND)", sem alerta de fallback; `largura_m` segue None.
3. Bota-fora do adaptador `dimensoes`: V_bota = V_bota (lineares) + (V_berco + V_env) × empolamento. Empolamento = solo 1,30 e rocha 1,50
   ponderados pela fração de rocha da escavação do segmento (escolha simples: o solo que sai tem a mesma composição da escavação).
   Chave `vala.volumes.berco_envoltoria_importado` (true) em `conceitos/dimensoes.json`; com false não acrescenta.

## Antes x depois
| caso | antes | depois |
|---|---|---|
| PEAD DN 630, pista 120 m, sem sondagem: V_bota do adaptador | 48,629 m3 | 173,534 m3 (+ 124,905 m3 = (berço + envoltória 96,08 m3) × 1,30) |
| FD DN 630 (fora da Tabela I) | largura 1,23 m | 1,23 m (mesmo número), agora com alerta "DE estimado igual ao DN" e `de_m` 0,63 |
| FD DN 600 | largura MOS | igual; `de_m` informado 0,635 |
| MND fora da Tabela I | `fonte_largura` "NBR 12266 (fallback)" e alerta | "não se aplica (MND)", sem alerta |
| lineares / obras_lineares / valas (gabaritos) | | inalterados |
| hash do conjunto de referência | 0602c637...c6de | igual |

## Aceite do Fable (03/11): ACEITO COM RESSALVAS, corrigidas no merge
- Trecho sem DN nem DE não quebra mais o fallback (`_diametro_externo_m` devolve None).
- Vala rasa (reaterro cortado a 0): o acréscimo ao bota-fora fica limitado ao reaterro do MOS, então o bota-fora não
  passa de escavação × empolamento.
- Página da arquitetura com a linha da D9.
