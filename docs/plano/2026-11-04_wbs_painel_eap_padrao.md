# Frente WBS — ciclo de 04/11/2026: dados do painel da EAP padrão reproduzíveis no repositório

Frente: EAP, evidências, leitura por IA, planilha e EAP padrão (conversa "[WBS] estrutura de projetos").
Base: `main` a7d0b8d (0.65.0). Versão só no merge (acordo de `docs/ARQUITETURA.md` §16).

## Por que este ciclo

O painel "EAP padrão de Foz" (artefato publicado em 04/11) foi gerado por um roteiro do scratchpad: a cadeia real
(planilha 211 → evidências → `eap_padrao.montar`) e o achatamento do resultado em quatro tabelas (resumo, situações,
etapas, folhas). Fora do repositório, ele não é reproduzível nem testado, e a fração preenchida foi calculada nesse
roteiro. Regra 2 do mantenedor: o cálculo fica em Python, no pacote, com teste; o painel só apresenta.

## Entregas

| # | Entrega | Arquivos | Contrato |
|---|---|---|---|
| E1 | Tabelas do painel | `camadas/eap_padrao.py` | `tabelas_do_painel(resultado: dict) -> dict[str, list[dict]]`, função pura sobre a saída de `montar`: `resumo` (tipo, nome, folhas, aplicaveis, preenchidas, calculadas, pct_preenchida = preenchidas/aplicaveis arredondada a 4 casas, 0 sem aplicáveis, obrigatorias_a_preencher, conflitos), `situacoes` (tipo, situacao, n; só n > 0), `etapas` (etapa, tipo, nome, folhas, preenchidas, mencao, citada_no_contrato "sim"/"não", linhas_citadas), `folhas` (folha, tipo, etapa, nome, situacao, obrigatoria, aponta, quantidade, evidencias, observacao). Sem preço (só campos da EAP padrão). Entra em `metadados()["funcoes"]` |
| E2 | Roteiro | `scripts/painel_eap_padrao.py` | `uv run python scripts/painel_eap_padrao.py <obra.json> <planilha.xlsx> <saida/>`: roda a cadeia (`orcamento_sanepar` em pasta temporária → `evidencias.loop` com trechos declarados → `consolidar` → `montar`), grava `resumo.json`, `situacoes.json`, `etapas.json`, `folhas.json` (UTF-8, ordem determinística) e imprime o hash do resultado de `montar`, como no roteiro de conferência de Foz. Não lê nem grava nada em `dados/` além da planilha de entrada |
| E3 | Testes | `tests/test_eap_padrao.py` | `tabelas_do_painel` sobre um `montar` sintético (já usado nos testes): contagens batem com `resumo` de cada tipo; soma de `situacoes` = folhas; uma linha de `folhas` por folha; pct com zero aplicáveis; nenhuma chave com "preco"/"valor_unit"/"custo" |
| E4 | Renomear (opcional do aceite da 0.65) | `camadas/eap.py` | `_recusa_das_evidencias` → `_recusa_por_evidencias`, sem outra mudança |
| E5 | Registro | este plano, `docs/EAP.md` (como gerar o painel), `results/rumo/wbs.yaml`, `CHANGELOG.md`, `camadas/__init__.py`, `pdca/licoes.jsonl`, `results/agentes/execucoes.csv` | versão no merge, lição, aceite |

## O que não muda

- `montar` e toda a cadeia; Foz só planilha idêntica (hash c5c2d5cd…). O painel de 04/11 foi gerado sem cadastro: as
  tabelas novas podem diferir dele, e a diferença é relatada (folhas que mudam de situação) e o painel é republicado.
- O painel (artefato) não entra no repositório: ele lê os quatro JSON.

## Verificação

- `uv run pytest -q` e a suíte como o vcm roda: 0 falhas; `camadas.referencia` 0602c637…; ruff limpo.
- Roteiro rodado na planilha real de Foz: hash c5c2d5cd… e as quatro tabelas iguais às do scratchpad
  (`scratchpad/artefato/*.json`).
- `vcm balanco` sem REVERTER; aceite do Fable antes do PR. (Aferição: reprova na main desde o PR #74, por funções
  longas de outra frente; registrar só se voltar a passar.)

## Parecer do Fable sobre o plano: APROVA COM AJUSTES

Obrigatórios e decisão do gerente:
1. **A cadeia de conferência dos ciclos anteriores não era a real**: o roteiro do scratchpad chama a planilha sem o
   cadastro Sanepar (`escopo.catalogo` do `obra.json` de Foz) e sem as pranchas (`dados["eap"]`). Decisão: o roteiro
   E2 roda **como a obra declara** — planilha do contrato (`escopo.itens_csv`) **com o cadastro** e trechos lineares
   declarados; sem pranchas, o que fica escrito no `docs/EAP.md` e no painel ("planilha do contrato + cadastro, sem
   pranchas"). O hash dessa rodada passa a ser a referência do painel e é registrado no Aceite; o hash c5c2d5cd…
   (só planilha, sem cadastro) continua como invariante de regressão desta frente e não pode mudar.
2. **Sem reescrever o encadeamento**: E2 reaproveita `evidencias._planilha_do_contrato` (tornar pública como
   `planilha_do_contrato`, chamadores atualizados) e `titulos_da_planilha`; não copia o roteiro do scratchpad.
3. **Contrato de E1 fechado**: `mencao` = folhas com `situacao == "só menção"` da etapa; `aponta` = `", "`.join de
   `aponta_txt`; `quantidade` = `" | "`.join de `quantidades_txt`; `pct_preenchida` = `n_preenchidas/n_aplicaveis` do
   `resumo` do tipo (não recontar folhas); `situacao` é a constante de `SITUACOES` (filtro) e `situacao_txt` vai junto
   (apresentação, regra 3); `pct_txt` do resumo também.

Opcionais aceitos: teste confere **valores** sem "R$"; caso com `situacao_txt` parcial e `citada_no_contrato`/`mencao`.
E4 (renomeação) em commit separado.

## Agentes

| Papel | Agente |
|---|---|
| plano e integração | Opus (gerente) |
| aprovação do plano e aceite | Fable |
| implementação com testes | Sonnet, em worktree a partir da `main` |

## Aceite

1º parecer do Fable sobre a entrega (401f28f, 7070c01): REVISAR — a razão da "só menção" (`motivo`, "citado sem valor")
saía vazia nas tabelas (lacuna do contrato). Corrigido pelo gerente em 687e6e8 (coluna `motivo`, asserção) com o
opcional do aviso no roteiro quando o csv não tem `titulo_etapa`.

Aceite Fable 04/11/2026: ACEITA 687e6e8 — "tabelas do painel puras e testadas (com `motivo`), roteiro reproduz a cadeia
planilha+cadastro (ac51cc5a…), c5c2d5cd… e 0602c637… inalterados; bug a registrar em outra camada: cadastro 304469
(conjunto de boca de lobo) com subcategoria motobomba leva OP.08.01/OP.10.03 ao item errado."

Referência do painel: `scripts/painel_eap_padrao.py exemplos/foz/obra.json <saida> --planilha
dados/foz/orcamento/principal.xlsx` → hash ac51cc5ae7b72703bb89667f4bf3e405f17662e00ca2820a7fc53f09c5512910 (784
evidências, 39 fatos, localizada 8/45, linear 8/31). Opcionais registrados: tornar públicas `_registros` e
`_titulos_do_contrato`; hidrômetro DN200 (318560) como macromedidor na EAP.
