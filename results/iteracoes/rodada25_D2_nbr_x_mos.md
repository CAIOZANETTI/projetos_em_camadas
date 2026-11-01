# Rodada 25, D2: vala das adutoras, NBR 12266 × MOS Sanepar

Decisão D2 (plano da rodada 25), delegada pelo Caio: a largura da vala das adutoras deixa de ser a da NBR 12266
(b = DE + 0,60 m) e passa a ser a do MOS Sanepar (L = D + SL + X + Y), pelo dimensionador único
(`lineares.dimensionar_vala`). O `test_quadro_da_vala` de `tests/test_valas.py` é o gabarito e muda de acordo.

Caso do teste: DE 0,30 m, pista, 10 m de tubo, material FD (premissa, com alerta), vala de 1,40 m
(recobrimento 1,00 + DE 0,30 + berço 0,10), superfície a recompor.

| Grandeza | Antes (NBR 12266) | Depois (MOS) | Diferença |
|---|---|---|---|
| Largura da vala (m) | 0,90 | 0,75 | −0,15 (−16,7 %) |
| Profundidade (m) | 1,40 | 1,40 | 0 |
| Faixa demolida e recomposta (m) | 1,20 | 1,05 | −0,15 |
| Demolição de pavimento (m²) | 12,0 | 10,5 | −1,5 (−12,5 %) |
| Recomposição de pavimento (m²) | 12,0 | 10,5 | −1,5 (−12,5 %) |
| Volume de vala (m³) | 12,6 | 10,5 | −2,1 (−16,7 %) |
| Escoramento (novo) | não calculado | sim (> 1,25 m), pontaleteamento | acréscimo |

Composição da largura pelo MOS (Tabela I, FD DN 300): L = 0,30 (D) + 0,35 (SL) + 0,10 (X, vala escorada)
+ 0,00 (Y, vala não passa de 2 m) = 0,75 m. A sobrelargura de recorte (0,15 m de cada lado) continua em
`valas.py`: faixa = 0,75 + 2 × 0,15 = 1,05 m.

Para a calçada (recobrimento 0,60 m, vala de 1,00 m, sem escoramento): largura 0,65 m (antes 0,90 m), volume 6,5 m³
(antes 9,0 m³).

Observações:
- A largura do MOS é menor que a da NBR para DN pequeno e passa a ser maior quando o DN cresce (SL cresce com o DN).
- Fora da Tabela I do MOS (material ou DN não cobertos) a largura volta para DE + 0,60 m, com alerta na linha do quadro.
- O material padrão (FD) é premissa e sai com o alerta "material de premissa" até o contrato dizer o tipo do tubo.
- Mudança de hash do conjunto de referência: ver o corpo do PR.
