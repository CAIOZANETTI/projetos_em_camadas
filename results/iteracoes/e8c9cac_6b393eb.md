## Retrospectiva da iteração `e8c9cac` → `6b393eb`

_Merge da main (0.52.0 de outra sessão): a conferência das cavas passa a 0.53.0, lição L049_

**Decisão proposta: DECISAO_HUMANA**. Houve troca: algo melhorou e algo piorou. Cabe ao humano decidir.

| Pergunta | Resposta |
|---|---|
| Ficou mais eficiente? | igual |
| Ficou mais determinístico? | igual |
| Ficou mais enxuto? | misto |
| Ficou mais robusto? | igual |
| Perdeu algo? | sim: sloc_por_funcao |
| Vale continuar nessa linha? | decisão humana, ver histórico |

### Correções sugeridas

| Prioridade | O quê | Por quê | Agente |
|---|---|---|---|
| alta | corrigir os testes que falham antes do merge (a decisão do balanço é REVERTER) | testes_falhando = 1 (vermelho; verde ≤ 0,00; senão vermelho) | sonnet |
| média | refatorar as funções mais complexas: camadas/extrair_gavetas.py etapa (35, E); camadas/prancha.py baloes (34, E); camadas/prancha.py itens_da_tabela (33, E); camadas/prancha.py ficha_hidraulica (33, E); camadas/eap.py validar (32, E) | complexidade_media = 6,194 (amarelo; verde ≤ 5,00; amarelo ≤ 10,00; senão vermelho) | sonnet |

_Sugestões geradas pelo vcm a partir das medições; nada foi alterado. Aplicar exige aprovação humana._

### Semáforo de estado (depois)

| Dimensão | Cor | Índice da iteração (antes = 1,0) |
|---|---|---:|
| eficiente | ⚪ cinza | 1,01 |
| deterministico | 🟢 verde | 1,00 |
| enxuto | 🟡 amarelo | 1,00 |
| robusto | 🔴 vermelho | 1,00 |

| Métrica | Dimensão | Valor | Cor | Regra |
|---|---|---:|---|---|
| tempo_referencia_ms | eficiente | 54,195 | ⚪ cinza | sem limite definido |
| pico_ram_mb | eficiente | 141,977 | ⚪ cinza | sem limite definido |
| frac_execucoes_identicas | deterministico | 1 | 🟢 verde | verde ≥ 1,00; amarelo ≥ 0,80; senão vermelho |
| sloc | enxuto | 14.528 | ⚪ cinza | sem limite definido |
| n_funcoes | enxuto | 1.083 | ⚪ cinza | sem limite definido |
| sloc_por_funcao | enxuto | 13,415 | 🟢 verde | verde ≤ 25,00; amarelo ≤ 50,00; senão vermelho |
| complexidade_media | enxuto | 6,194 | 🟡 amarelo | verde ≤ 5,00; amarelo ≤ 10,00; senão vermelho |
| n_dependencias | enxuto | 8 | 🟢 verde | verde ≤ 15,00; amarelo ≤ 30,00; senão vermelho |
| testes_total | robusto | 1.077 | ⚪ cinza | sem limite definido |
| tempo_testes_s | eficiente | 37,060 | ⚪ cinza | sem limite definido |
| testes_falhando | robusto | 1 | 🔴 vermelho | verde ≤ 0,00; senão vermelho |
| arquivos_com_erro | robusto | 0 | 🟢 verde | verde ≤ 0,00; senão vermelho |
| cobertura_testes | robusto | 0,812 | 🟢 verde | verde ≥ 0,80; amarelo ≥ 0,55; senão vermelho |
| alertas_seguranca | robusto | 0 | 🟢 verde | verde ≤ 0,00; senão vermelho |

| Métrica | Pergunta | Eliminatória | Antes | Depois | Variação | Veredito |
|---|---|---|---:|---:|---:|---|
| tempo_referencia_ms | eficiente |  | 55,574 | 54,195 | -2,5% | = igual |
| pico_ram_mb | eficiente |  | 141,891 | 141,977 | +0,1% | = igual |
| frac_execucoes_identicas | deterministico | sim | 1 | 1 | 0,0% | = igual |
| sloc | enxuto |  | 12.866 | 14.528 | +12,9% | · informativa |
| n_funcoes | enxuto |  | 991 | 1.083 | +9,3% | · informativa |
| sloc_por_funcao | enxuto |  | 12,983 | 13,415 | +3,3% | ▼ piorou |
| complexidade_media | enxuto |  | 6,348 | 6,194 | -2,4% | ▲ melhorou |
| n_dependencias | enxuto |  | 8 | 8 | 0,0% | = igual |
| testes_total | robusto |  | 1.015 | 1.077 | +6,1% | · informativa |
| tempo_testes_s | eficiente |  | 37,916 | 37,060 | -2,3% | · informativa |
| testes_falhando | robusto | sim | 1 | 1 | 0,0% | = igual |
| arquivos_com_erro | robusto |  | 0 | 0 | 0,0% | = igual |
| cobertura_testes | robusto |  | 0,814 | 0,812 | -0,1% | = igual |
| alertas_seguranca | robusto | sim | 0 | 0 | 0,0% | = igual |

### Gasto dos agentes nesta iteração

| Modelo | Chamadas | Tokens | Custo (US$) |
|---|---:|---:|---:|
| claude-opus-5-5 | 29 | 16.980.537 | 4,13 |
| claude-sonnet-5-5 | 61 | 11.532.262 | 2,54 |
| claude-fable-5-1 | 15 | 4.384.979 | 10,31 |
| **Total** | | **32.897.778** | **16,97** |

_Custo equivalente de API (preços de repertorio/modelos.yaml); em plano de assinatura não é o gasto real. Entram as chamadas entre os dois commits, feitas no repositório ou nas worktrees dos agentes._
