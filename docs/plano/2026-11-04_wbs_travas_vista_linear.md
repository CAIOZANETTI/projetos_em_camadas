# Frente WBS — ciclo de 04/11/2026 (2): travas da vista linear

Frente: EAP, evidências e EAP padrão (conversa "[WBS] estrutura de projetos"). Base: `main` 81ed4e2 (0.59.0).
Versão só no merge (`docs/ARQUITETURA.md` §16). Origem: pendências do aceite do Fable no ciclo D10–D13
(`docs/plano/2026-11-04_wbs_d10_d11.md`, seção Aceite).

## Por que

A D11 criou um sistema com `vista_eap_padrao: "linear"` (`U1.AGUA_POTAVEL`) e a declaração
`eap_padrao.trechos_lineares` na obra. O aceite apontou duas portas para número errado:

1. **Código de sistema linear sem declaração.** Uma evidência que já chega com o código `U1.AGUA_POTAVEL.*`
   (IA conferida, decisão, regex) numa obra que **não** declara esse trecho vai para a vista linear, enquanto a mesma
   quantidade, lida da planilha sem declaração, fica no fato `U1.*` da localizada: o número aparece nas duas vistas.
2. **Declaração em obra sem tipo linear.** Hoje só avisa; a linha declarada sai da localizada e não entra em vista
   nenhuma: o número some.

## Entregas

| # | Entrega | Arquivos | Contrato |
|---|---|---|---|
| E1 | Sistema linear só com declaração | `camadas/eap.py`, `camadas/eap_padrao.py` | a vista linear de um sistema marcado com `vista_eap_padrao` só vale se a obra declara um trecho com aquela (unidade, sistema); sem declaração, a evidência com esse código é **recusada na EAP padrão** (não entra em vista nenhuma) e gera aviso "sistema de trecho linear não declarado na obra: <código>"; nunca entra nas duas vistas |
| E2 | Declaração em obra sem tipo linear é recusada | `camadas/eap_padrao.py`, `camadas/evidencias.py` | se `tipo_da_obra` não inclui `obra_linear`, a declaração `trechos_lineares` é recusada (aviso) e **não é aplicada**: a linha fica na vista localizada com o código original (o número não some) |
| E3 | Testes | `tests/test_titulos_etapa.py` (ou arquivo novo) | E1: IA/decisão com `U1.AGUA_POTAVEL.GEO.MOV.VAL` em obra sem declaração → recusada com aviso, número fora das duas vistas, e com declaração → vista linear; E2: obra só localizada declarando trecho → aviso, linha na localizada com o código original, soma inalterada; Foz (mista, com declaração) inalterada |
| E4 | Registro | `docs/EAP.md` §9.1, `results/rumo/wbs.yaml`, este plano | regras descritas; rumo do ciclo |

## O que não muda

- Foz: mista e com a declaração da D11; os números da cadeia real ficam iguais (9/45 localizada, 7/32 linear).
- `U1.LINEARES.*` e os sistemas `rede_eta` continuam na localizada.

## Fora deste ciclo

- Trecho declarado × futura aba Obras Lineares (`U1.LINEARES`): depende da frente Geo Bd anexar a aba e de decisão
  do Caio sobre como as duas fontes do mesmo trecho se conciliam.

## Verificação

Três verdes (`uv run pytest -q`, `scripts/afericao.py`, hash de `camadas.referencia` = 0602c637…), suíte como o vcm
roda com 0 falhas, roteiros de ataque da leitura por IA idênticos, cadeia real de Foz igual, `vcm balanco` sem
REVERTER, aprovação do plano e aceite da entrega pelo Fable.

## Agentes

| Papel | Agente |
|---|---|
| plano e integração | Opus (gerente) |
| aprovação do plano e aceite | Fable |
| implementação com testes | Sonnet, em worktree a partir desta branch |

## Parecer do Fable sobre o plano: APROVA, com três ajustes obrigatórios

Recusar (E1) é melhor que rebaixar para `U*.*`: `vista_do_codigo` é função só do código e `_derivadas` já exclui
`U1.AGUA_POTAVEL.*` do fato `U1.*.X`; rebaixar criaria incoerência com `_derivadas` ou mudaria o código que a
IA/decisão conferiu. A perda não é silenciosa porque o aviso nomeia código, serviço, valor e documento, e o fato
continua em `fatos.csv`.

1. **E1, onde a trava age:** `preencher` recebe os pares (unidade, sistema) declarados; código de sistema marcado e
   não declarado sai das duas vistas **sem** cair em `indefinidas` (para não virar "unidade não atribuível"); o aviso
   nasce em `montar`, varrendo `dados["evidencias"]["fatos"]` **e** `dados["eap"]` (prancha pode ganhar o sistema
   pelas `chaves`). `vista_do_codigo` não muda (continua função só do código).
2. **E2, uma fonte só:** `trechos_do_cfg` consulta `tipo_da_obra(cfg)`, e `_configuracao`/`montar` descartam os
   mesmos trechos (sem aviso duplo); teste de que `trechos_do_cfg` e `montar` concordam.
3. **E3:** ajustar o teste existente de obra só localizada (texto do aviso), manter o teste de Foz (nenhum aviso de
   trecho, obra mista) e cobrir também evidência de decisão (hoje `_problemas_ia` não confere o sistema contra
   `unidades_construtivas.json`).

Pendência registrada (sugestão): recusar já em `loop`/`_conferir_ia`, para o número nem chegar ao `consolidar`.
