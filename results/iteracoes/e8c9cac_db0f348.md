## Retrospectiva da iteração `e8c9cac` → `db0f348`

_Rumo: E4 da conferência das cavas concluída (3º aceite do Fable: ACEITA)_

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
| média | refatorar as funções mais complexas: camadas/extrair_gavetas.py etapa (35, E); camadas/prancha.py baloes (34, E); camadas/prancha.py itens_da_tabela (33, E); camadas/prancha.py ficha_hidraulica (33, E); camadas/eap.py validar (32, E) | complexidade_media = 6,187 (amarelo; verde ≤ 5,00; amarelo ≤ 10,00; senão vermelho) | sonnet |

_Sugestões geradas pelo vcm a partir das medições; nada foi alterado. Aplicar exige aprovação humana._

### Semáforo de estado (depois)

| Dimensão | Cor | Índice da iteração (antes = 1,0) |
|---|---|---:|
| eficiente | ⚪ cinza | 1,02 |
| deterministico | 🟢 verde | 1,00 |
| enxuto | 🟡 amarelo | 1,00 |
| robusto | 🔴 vermelho | 1,00 |

| Métrica | Dimensão | Valor | Cor | Regra |
|---|---|---:|---|---|
| tempo_referencia_ms | eficiente | 53,625 | ⚪ cinza | sem limite definido |
| pico_ram_mb | eficiente | 141,801 | ⚪ cinza | sem limite definido |
| frac_execucoes_identicas | deterministico | 1 | 🟢 verde | verde ≥ 1,00; amarelo ≥ 0,80; senão vermelho |
| sloc | enxuto | 14.501 | ⚪ cinza | sem limite definido |
| n_funcoes | enxuto | 1.080 | ⚪ cinza | sem limite definido |
| sloc_por_funcao | enxuto | 13,427 | 🟢 verde | verde ≤ 25,00; amarelo ≤ 50,00; senão vermelho |
| complexidade_media | enxuto | 6,187 | 🟡 amarelo | verde ≤ 5,00; amarelo ≤ 10,00; senão vermelho |
| n_dependencias | enxuto | 8 | 🟢 verde | verde ≤ 15,00; amarelo ≤ 30,00; senão vermelho |
| testes_total | robusto | 928 | ⚪ cinza | sem limite definido |
| tempo_testes_s | eficiente | 36,538 | ⚪ cinza | sem limite definido |
| testes_falhando | robusto | 1 | 🔴 vermelho | verde ≤ 0,00; senão vermelho |
| arquivos_com_erro | robusto | 0 | 🟢 verde | verde ≤ 0,00; senão vermelho |
| cobertura_testes | robusto | 0,812 | 🟢 verde | verde ≥ 0,80; amarelo ≥ 0,55; senão vermelho |
| alertas_seguranca | robusto | 0 | 🟢 verde | verde ≤ 0,00; senão vermelho |

| Métrica | Pergunta | Eliminatória | Antes | Depois | Variação | Veredito |
|---|---|---|---:|---:|---:|---|
| tempo_referencia_ms | eficiente |  | 55,574 | 53,625 | -3,5% | = igual |
| pico_ram_mb | eficiente |  | 141,891 | 141,801 | -0,1% | = igual |
| frac_execucoes_identicas | deterministico | sim | 1 | 1 | 0,0% | = igual |
| sloc | enxuto |  | 12.866 | 14.501 | +12,7% | · informativa |
| n_funcoes | enxuto |  | 991 | 1.080 | +9,0% | · informativa |
| sloc_por_funcao | enxuto |  | 12,983 | 13,427 | +3,4% | ▼ piorou |
| complexidade_media | enxuto |  | 6,348 | 6,187 | -2,5% | ▲ melhorou |
| n_dependencias | enxuto |  | 8 | 8 | 0,0% | = igual |
| testes_total | robusto |  | 1.015 | 928 | -8,6% | · informativa |
| tempo_testes_s | eficiente |  | 37,916 | 36,538 | -3,6% | · informativa |
| testes_falhando | robusto | sim | 1 | 1 | 0,0% | = igual |
| arquivos_com_erro | robusto |  | 0 | 0 | 0,0% | = igual |
| cobertura_testes | robusto |  | 0,814 | 0,812 | -0,2% | = igual |
| alertas_seguranca | robusto | sim | 0 | 0 | 0,0% | = igual |

### Gasto dos agentes nesta iteração

| Modelo | Chamadas | Tokens | Custo (US$) |
|---|---:|---:|---:|
| claude-opus-5-5 | 27 | 15.766.010 | 3,83 |
| claude-sonnet-5-5 | 61 | 11.532.262 | 2,54 |
| claude-fable-5-1 | 15 | 4.384.979 | 10,31 |
| **Total** | | **31.683.251** | **16,68** |

_Custo equivalente de API (preços de repertorio/modelos.yaml); em plano de assinatura não é o gasto real. Entram as chamadas entre os dois commits, feitas no repositório ou nas worktrees dos agentes._
