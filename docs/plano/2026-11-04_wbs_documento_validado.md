# Frente WBS — ciclo de 04/11/2026: documento de leitura validado e opcionais do aceite da 0.62

Frente: EAP, evidências, leitura por IA, planilha e EAP padrão (conversa "[WBS] estrutura de projetos").
Base: `main` e4ef3d5 (0.62.0). Versão só no merge (acordo de `docs/ARQUITETURA.md` §16).

## Por que este ciclo

O aceite do Fable da 0.62 deixou dois opcionais registrados no plano `2026-11-04_wbs_recusa_na_leitura.md`:

1. Documento do `obra.json` (`evidencias.documentos`) com `unidade`/`sistema` fora do padrão (ex.: `sistema` em
   minúsculas) faz `buscar_texto` levantar `ValueError` em `evidencia()` na primeira linha que casa um item, e a
   etapa de evidências inteira cai. A regra da 0.62 é recusar com motivo, nunca exceção nem normalização.
2. `pares_declarados` virou pública e não está em `eap_padrao.metadados()["funcoes"]`.

Além disso, o aviso da 0.62 para recusa que não é de sistema não declarado diz "Decisão recusada na leitura"; com
uma segunda origem de recusa (documento), o texto tem de ser genérico, senão repete o defeito de motivo trocado.

## Entregas

| # | Entrega | Arquivos | Contrato |
|---|---|---|---|
| E1 | Documento validado na entrada | `camadas/evidencias.py` | em `_documentos`, antes de ler as páginas: `unidade` e `sistema` declarados (ausente = `*`) são conferidos contra o padrão do campo `codigo` de `conceitos/evidencia.schema.json` (montando o código com um item de teste, sem regex duplicada). Fora do padrão: o documento fica de fora, `log` com o motivo e uma recusa `{motivo: "documento inválido: …", evidencia: {documento: {id}, codigo}}` vai para as `recusadas` que `etapa` devolve. Sem normalizar caixa. `buscar_texto` não muda |
| E2 | Aviso genérico | `camadas/eap_padrao.py` | recusa cujo motivo não é `MOTIVO_NAO_DECLARADO` vira "Recusada na leitura: {código} ({motivo})" (decisão e documento); a de sistema não declarado não muda |
| E3 | Metadados | `camadas/eap_padrao.py` | `pares_declarados` e `sistema_linear_nao_declarado` em `metadados()["funcoes"]` |
| E4 | Testes | `tests/test_titulos_etapa.py` | `etapa` com documento de `sistema` minúsculo: não levanta, recusa com motivo, aviso "Recusada na leitura" na EAP padrão, outros documentos da obra seguem lidos; documento válido inalterado; teste da 0.62 ajustado ao texto genérico; metadados listam as duas funções |
| E5 | Registro | `docs/EAP.md`, este plano, `results/rumo/wbs.yaml`, `CHANGELOG.md`, `camadas/__init__.py`, `pdca/licoes.jsonl`, `results/agentes/execucoes.csv` | versão no merge, lição, aceite |

## O que não muda

- `evidencia()` continua levantando `ValueError` (contrato da construção); a recusa acontece antes, na entrada.
- CLI `conferir` (documentos da linha de comando não têm unidade/sistema declarados).
- Foz: documentos sem `sistema` ou com sistema válido; cadeia real idêntica (hash c5c2d5cd…).

## Verificação

- `uv run pytest -q` e a suíte como o vcm roda: 0 falhas; nenhum golden regenerado.
- `camadas.referencia` 0602c637…; `scripts/afericao.py` ok; ruff limpo; roteiros de ataque idênticos; Foz idêntica.
- `vcm balanco` sem REVERTER; aceite do Fable antes do PR.

## Agentes

| Papel | Agente |
|---|---|
| plano e integração | Opus (gerente) |
| aprovação do plano e aceite | Fable |
| implementação com testes | Sonnet, em worktree a partir da `main` |
