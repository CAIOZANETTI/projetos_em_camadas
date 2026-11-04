# Frente WBS — ciclo de 04/11/2026: complexidade das funções da frente (refatoração sem mudança de saída)

Frente: EAP, evidências, leitura por IA, planilha e EAP padrão (conversa "[WBS] estrutura de projetos").
Base: `main` 77662a1 (0.63.0). Versão só no merge (acordo de `docs/ARQUITETURA.md` §16).

## Por que este ciclo

Os três últimos balanços (0.61–0.63) deram SEM_GANHO: correções de robustez que o vcm não mede. O próprio cartão
sugere refatorar as funções mais complexas (`complexidade_media` amarela, 6,08). O edital/TR de Foz, que abriria o
próximo ciclo de conteúdo, ainda não tem local informado. Este ciclo ataca a complexidade **só nos módulos desta
frente** (os outros, como `extrair_gavetas.etapa` e `prancha.*`, são de outras conversas e não entram).

## Entregas

| # | Função (radon, base) | Arquivo | Meta |
|---|---|---|---|
| E1 | `validar` — E (32) | `camadas/eap.py` | ≤ 10: uma função por bloco de regra (códigos, pais, termos/regex, obra/escopo, serviços…), `validar` só junta as listas na mesma ordem |
| E2 | `_status` — C (18) | `camadas/eap.py` | ≤ 10 |
| E3 | `_avisos_nao_declarados` — D (22) | `camadas/eap_padrao.py` | ≤ 10: um gerador por origem (fatos, recusadas, quantidades) |
| E4 | `etapa` — C (20) | `camadas/evidencias.py` | ≤ 10: montagem das fontes e registro no log em funções próprias |
| E6 | Registro | `results/rumo/wbs.yaml`, este plano, `CHANGELOG.md`, `camadas/__init__.py`, `pdca/licoes.jsonl`, `results/agentes/execucoes.csv`, `pdca/afericao.jsonl` | versão no merge, lição, aceite |

## Contrato (o que não pode mudar)

- **Saída idêntica**: mesma ordem e mesmo texto de erros, avisos e linhas de log; mesmos dicionários. Nenhum teste
  existente é alterado (só se acrescentam testes de caracterização quando faltar cobertura de um ramo tocado).
- Assinaturas públicas e `metadados()` iguais; funções novas privadas (`_…`), em português, com docstring.
- Nenhuma regra nova, nenhum conceito/JSON alterado, nenhum golden regenerado.
- `uv run ruff check camadas tests` limpo; não rodar `ruff format` em arquivo que não estava formatado.

## Verificação

- Antes de mexer: rodar e guardar a saída de referência; depois, comparar byte a byte:
  `uv run pytest -q`; suíte como o vcm roda; `camadas.referencia` 0602c637…; `scripts/afericao.py` ok;
  roteiros de ataque da leitura por IA (scratchpad `ataques.py`, `r3_ataques.py`, `r3_b.py`, `rev_bloco.py`,
  `rev_bloco2.py`) idênticos; Foz idêntica (656 evidências, 38 fatos, 9/45, 7/32, hash c5c2d5cd…).
- `uvx radon cc` antes × depois das cinco funções e das novas (nenhuma nova acima de 10).
- `vcm balanco` sem REVERTER; esperado ganho em "enxuto" (complexidade média).
- Aceite do Fable antes do PR.

## Parecer do Fable sobre o plano: APROVA COM AJUSTES

Obrigatórios (incorporados):
1. **Caracterização antes de refatorar** (testes novos, no mesmo PR, sem alterar os existentes; commit próprio antes da
   refatoração): `eap.validar` com `monkeypatch` de `GERAL`/`REGRAS`, um item quebrado por bloco, asserindo a lista
   inteira e a ordem (repetidos → pacote → por item → vistas → pranchas); as funções novas leem os globais do módulo
   na chamada, não no import. `evidencias.etapa`: lista completa do `log` num caso com `ia` e `decisoes` no cfg (e o
   ramo `extras`), preservando a ordem de avaliação (`_documentos` antes de `_obras_lineares_da_obra`; `return None`
   depois dos logs de recusa e antes de `gravar`).
2. `_avisos_nao_declarados`: manter ordem fatos → recusadas → quantidades e a deduplicação final; `_status`: ordem dos
   retornos antecipados e o `float(linha.get("quantidade", np.nan))`.
3. `ruff format` só em `eap_padrao.py` (os outros não estavam formatados).

Decisão do gerente: `eap_html.valor_txt` **sai do ciclo** — formata propriedades de `gavetas.json` (frente Geo Bd,
§13); fica para combinar com aquela conversa. Opcionais aceitos: funções novas com ao menos ~2 ramos (sem
pulverizar); `pytest --cov-branch` antes × depois nos módulos tocados. Os roteiros de ataque ficam no scratchpad e
são rodados por caminho absoluto, contra o worktree.

## Agentes

| Papel | Agente |
|---|---|
| plano e integração | Opus (gerente) |
| aprovação do plano e aceite | Fable |
| refatoração com testes | Sonnet, em worktree a partir da `main` |
