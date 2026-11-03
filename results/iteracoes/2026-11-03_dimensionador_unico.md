# Dimensionador único de vala (0.49.0)

Decisão do Caio (03/11/2026): dimensionador único (lineares). `dimensoes.dimensionar_vala` virou adaptador de
`lineares.dimensionar_vala`; o modelo geotécnico único (`conceitos/geotecnia.json`: raio de influência 60 m, margem do
NA 0 m, empolamento 1,30 solo / 1,50 rocha) vale para toda vala. O NBR 12266 (regra própria do `dimensoes`) saiu.

Medido por `uv run pytest -q` (724 passam, 63 pulados), `scripts/afericao.py` e `scripts/determinismo.py` ok.
Hash do conjunto de referência (`python -m camadas.referencia`): `0602c637b4b6e18271f78df964927123c045db2f70598dfddc58e5b2971ac6de`,
igual ao anterior.

## Casos alterados (antes = NBR 12266 do `dimensoes`; depois = MOS pelo `lineares`)

Trecho de 100 m (salvo indicação), furo SP-01 a 10 m do eixo, quantidades em m³ (escavação, reaterro), m² (demolição,
escoramento) ou m (largura b, profundidade h, corte).

| Teste | Caso | Grandeza | Antes | Depois | Causa |
|---|---|---|---|---|---|
| `test_vala_rasa_em_terra...` | PEAD DN 200, fora da via | b | 0,80 m | 0,55 m | MOS: D 0,20 + SL 0,35 (NBR: folga 0,60) |
| | | escavação | 72,0 | 49,5 | b menor |
| | | reaterro | 24,0 | 46,358 | agora escavação − tubo |
| | | bota-fora | 60,0 | 4,084 | agora tubo × empolamento 1,30 (regra do lineares) |
| `test_pista_asfalto...` | FD DN 630 → FD DN 300 (630 fora da Tabela I do MOS) | b | 1,23 m (DN 630) | 0,75 m (DN 300) | D 0,30 + SL 0,35 + X 0,10 |
| | | demolição | L × (b + 0,30) | L × b = 75 m² | sem sobrelargura de recorte |
| | | escavação | b × (h − 0,35) × L | b × h × L = 105 m³ | profundidade inteira |
| | | reaterro | esc − berço − tubo | esc − tubo | regra do lineares |
| `test_areia_pede_escoramento...` | PEAD DN 300, areia | b | 1,10 m | 0,75 m | MOS |
| | | escoramento | contínuo, 140 m² | contínuo, 140 m² | igual |
| | | escavação | 57,75 | 52,5 | b menor |
| `test_profundidade_do_perfil_e_rocha...` | PEAD DN 200, h = 3,0 m, 1/3 rocha | b | 0,90 m | 0,75 m | MOS |
| | | escavação solo | 180,0 | 150,075 | b menor; fração de rocha arredondada em 3 casas (0,333) |
| | | escavação rocha | 90,0 | 74,925 | idem |
| | | escoramento | 400 m² (só altura em solo) | 600 m² (2 × h × L) | regra do lineares |
| `test_vala_abaixo_do_na...` | PEAD DN 300, NA do furo 1,5 m → 1,0 m | h_agua | 0,4 m (NA de projeto 1,0 = 1,5 − 0,5) | 0,4 m com na_m = 1,0 | margem do NA 0,5 → 0 m; com na_m = 1,5 não há água (h = 1,4) |
| | | esgotamento | 20 h | 20 h | igual |
| `test_cota_do_trecho_desloca...` | cota do trecho 242 m, na_m 1,5 → 1,0 m | esgotamento | 0 | 0 (e 0,4 m de água sem a cota) | mesma margem; teste reforçado |
| `test_tubo_flexivel_tem_envoltoria` | PEAD DN 200 | envoltória | 3,686 m³ (b 0,80) | 2,436 m³ (b 0,55) | MOS |
| `test_classe_do_solo...` | "areia argilosa" | classe | areia | argila | 1ª regex que casa em `geotecnia.json` (ARGIL antes de AREI) |
| `test_servicos_associados_por_formula` (`test_evidencias`) | trecho 180 m, PE DN 630, h 1,73 m | b | 1,23 m | 1,08 m | MOS |
| | | escavação | 305,5 m³ | 336,3 m³ | profundidade inteira × b MOS |
| | | demolição | 275,4 m² (b + 2 × 0,15) | 194,4 m² (L × b) | sem sobrelargura |
| | | escoramento pontaleteamento | 622,8 m² | 622,8 m² | igual |
| `test_montar_passa_os_fatos_a_arvore` (`test_eap_painel`) | nó U2 | status, fatos, conflitos | conflito, 12, 7 | fonte única, 12, 0 | os 7 conflitos eram NBR × MOS da mesma vala |

## Testes trocados ou removidos

- `test_cada_metodo_e_uma_fonte_e_a_consolidacao_compara` (conflito de escavação 169,74 × 186,84 m³) virou
  `test_metodo_sem_regra_propria_fica_de_fora_com_alerta`.
- `test_metodo_que_nao_se_aplica_fica_de_fora_com_alerta` virou `test_tubo_fora_da_tabela_do_mos_fica_com_a_largura_em_faltando`.
- `test_escoramento_total_compara_metodos_que_escolhem_tipos_diferentes` (nome mantido, a lição L029 o cita): agora compara
  furo dentro × fora do raio de 60 m (contínuo × pontaleteamento) e confere o serviço total `escoramento`.
- `test_impenetravel_vira_topo_de_rocha` removido: chamava `dimensoes.solo_na_vala`, que deixou de existir. Furo
  impenetrável como rocha continua só em `geotecnia.topo_rocha_m` (o lineares não o usa; ver pendência).
- Novos: `test_adaptador_e_lineares_dao_a_mesma_largura_profundidade_e_escavacao`, `test_sondagem_proxima_usa_o_raio_do_modelo_geotecnico`,
  `test_premissas_do_dimensionador_antigo_foram_removidas_do_conceito`.

## Pendências

- Impenetrável do furo como rocha: o dimensionador único (`geotecnia.solo_na_faixa`) só vê rocha pela descrição das camadas.
- Tubos fora da Tabela I do MOS (ex.: FD DN 630) ficam sem largura (`faltando`) em vez de receber o número do NBR.
- Reaproveitamento do solo (`proprio`): continua o do `dimensoes.json` (rocha e solo mole não voltam), que o lineares não modela.
