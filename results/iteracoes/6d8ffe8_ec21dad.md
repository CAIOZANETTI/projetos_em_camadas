## Retrospectiva da iteração `6d8ffe8` → `ec21dad`

_Irati: barragem, EEB09 e EEB10 georreferenciadas por vetor × vetor_

**Decisão proposta: DECISAO_HUMANA**. Houve troca: algo melhorou e algo piorou. Cabe ao humano decidir.

| Pergunta | Resposta |
|---|---|
| Ficou mais eficiente? | não |
| Ficou mais determinístico? | igual |
| Ficou mais enxuto? | igual |
| Ficou mais robusto? | igual |
| Perdeu algo? | sim: tempo_referencia_ms |
| Vale continuar nessa linha? | decisão humana, ver histórico |

### Correções sugeridas

| Prioridade | O quê | Por quê | Agente |
|---|---|---|---|
| alta | corrigir os testes que falham antes do merge (a decisão do balanço é REVERTER) | testes_falhando = 6 (vermelho; verde ≤ 0,00; senão vermelho) | sonnet |
| média | refatorar as funções mais complexas: camadas/prancha.py baloes (34, E); camadas/prancha.py itens_da_tabela (33, E); camadas/prancha.py ficha_hidraulica (33, E); camadas/formulas.py _no (29, D); camadas/prancha.py estacas_e_blocos (29, D) | complexidade_media = 5,938 (amarelo; verde ≤ 5,00; amarelo ≤ 10,00; senão vermelho) | sonnet |
| baixa | perfilar o conjunto de referência para achar a origem da perda de eficiência | tempo_referencia_ms = 42,949; piorou de 36,595 para 42,949 (+17,4%) | sonnet |

_Sugestões geradas pelo vcm a partir das medições; nada foi alterado. Aplicar exige aprovação humana._

### Semáforo de estado (depois)

| Dimensão | Cor | Índice da iteração (antes = 1,0) |
|---|---|---:|
| eficiente | ⚪ cinza | 0,92 |
| deterministico | 🟢 verde | 1,00 |
| enxuto | 🟡 amarelo | 1,00 |
| robusto | 🔴 vermelho | 1,00 |

| Métrica | Dimensão | Valor | Cor | Regra |
|---|---|---:|---|---|
| tempo_referencia_ms | eficiente | 42,949 | ⚪ cinza | sem limite definido |
| pico_ram_mb | eficiente | 155,281 | ⚪ cinza | sem limite definido |
| frac_execucoes_identicas | deterministico | 1 | 🟢 verde | verde ≥ 1,00; amarelo ≥ 0,80; senão vermelho |
| sloc | enxuto | 21.288 | ⚪ cinza | sem limite definido |
| n_funcoes | enxuto | 1.484 | ⚪ cinza | sem limite definido |
| sloc_por_funcao | enxuto | 14,345 | 🟢 verde | verde ≤ 25,00; amarelo ≤ 50,00; senão vermelho |
| complexidade_media | enxuto | 5,938 | 🟡 amarelo | verde ≤ 5,00; amarelo ≤ 10,00; senão vermelho |
| n_dependencias | enxuto | 8 | 🟢 verde | verde ≤ 15,00; amarelo ≤ 30,00; senão vermelho |
| testes_total | robusto | 1.493 | ⚪ cinza | sem limite definido |
| tempo_testes_s | eficiente | 24,178 | ⚪ cinza | sem limite definido |
| testes_falhando | robusto | 6 | 🔴 vermelho | verde ≤ 0,00; senão vermelho |
| arquivos_com_erro | robusto | 0 | 🟢 verde | verde ≤ 0,00; senão vermelho |
| cobertura_testes | robusto | 0,827 | 🟢 verde | verde ≥ 0,80; amarelo ≥ 0,55; senão vermelho |
| alertas_seguranca | robusto | 0 | 🟢 verde | verde ≤ 0,00; senão vermelho |

| Métrica | Pergunta | Eliminatória | Antes | Depois | Variação | Veredito |
|---|---|---|---:|---:|---:|---|
| tempo_referencia_ms | eficiente |  | 36,595 | 42,949 | +17,4% | ▼ piorou |
| pico_ram_mb | eficiente |  | 155,469 | 155,281 | -0,1% | = igual |
| frac_execucoes_identicas | deterministico | sim | 1 | 1 | 0,0% | = igual |
| sloc | enxuto |  | 21.288 | 21.288 | 0,0% | · informativa |
| n_funcoes | enxuto |  | 1.484 | 1.484 | 0,0% | · informativa |
| sloc_por_funcao | enxuto |  | 14,345 | 14,345 | 0,0% | = igual |
| complexidade_media | enxuto |  | 5,938 | 5,938 | 0,0% | = igual |
| n_dependencias | enxuto |  | 8 | 8 | 0,0% | = igual |
| testes_total | robusto |  | 1.493 | 1.493 | 0,0% | · informativa |
| tempo_testes_s | eficiente |  | 23,663 | 24,178 | +2,2% | · informativa |
| testes_falhando | robusto | sim | 6 | 6 | 0,0% | = igual |
| arquivos_com_erro | robusto |  | 0 | 0 | 0,0% | = igual |
| cobertura_testes | robusto |  | 0,827 | 0,827 | 0,0% | = igual |
| alertas_seguranca | robusto | sim | 0 | 0 | 0,0% | = igual |
