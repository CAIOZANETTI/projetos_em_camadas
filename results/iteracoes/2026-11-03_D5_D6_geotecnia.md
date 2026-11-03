# D5 e D6: modelo geotécnico único (decisão do Caio, 03/11/2026)

- D5: `classe_solo` classifica pela regex que casa mais cedo no texto (o substantivo); empate pela ordem da lista.
  `rocha_alterada` vence `rocha` quando casa em qualquer posição ("rocha alterada", "basalto alterado").
- D6: `solo_na_faixa` conta como rocha a parte da faixa abaixo do impenetrável (`topo_rocha_m`); premissa
  `impenetravel_e_rocha` em `conceitos/geotecnia.json`.

| Caso | Antes | Depois |
|---|---|---|
| "Areia fina argilosa" | argila | areia |
| "areia argilosa" (`test_areia_argilosa_e_areia`, era xfail) | argila | areia |
| "Argila arenosa", "Silte argiloso" | argila, silte | argila, silte |
| impenetrável a 2,0 m, faixa 0-3 m | 1/3 indefinido | 1/3 rocha |

Gabaritos (obras_lineares, valas, gavetas, dimensionar_vala): nenhum número mudou. Hash da referência inalterado
(0602c637...ac6de). Testes: 761 passaram, 64 ignorados.
