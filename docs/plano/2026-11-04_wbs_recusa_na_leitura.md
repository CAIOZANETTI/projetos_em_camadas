# Frente WBS — ciclo de 04/11/2026 (3): recusa na leitura e caixa do item

Frente: EAP, evidências e EAP padrão. Base: `main` acf756b (0.61.0). Versão só no merge (`docs/ARQUITETURA.md` §16).
Origem: pendências registradas nos aceites do Fable (`docs/plano/2026-11-04_wbs_travas_vista_linear.md`, Aceite).

## Por que

1. **Recusa tardia.** Hoje a evidência com código de sistema linear (`vista_eap_padrao`) sem declaração na obra só
   é barrada na EAP padrão; ela ainda entra no `consolidar` e aparece em `fatos.csv` e na cobertura como se valesse.
   O número deve ser recusado na leitura, onde as outras recusas já acontecem, com motivo.
2. **Caixa do item.** O item do código em minúsculas (`u1.agua_potavel.geo.mov.val`) não casa com folha em nenhuma
   vista (pré-existente). Unidade e sistema já são comparados em minúsculas; o item (DISC.PAC.ITEM) não é normalizado.

## Entregas

| # | Entrega | Arquivos | Contrato |
|---|---|---|---|
| E1 | Recusa na leitura | `camadas/evidencias.py` | em `loop`/`_conferir_ia` (e no caminho de decisão), evidência cujo código tem sistema marcado `vista_eap_padrao` sem a (unidade, sistema) declarada na obra é recusada com motivo "sistema de trecho linear não declarado na obra"; não chega ao `consolidar`; a planilha declarada (`de_planilha` com `trechos_lineares`) continua valendo; a trava da EAP padrão (0.61.0) fica como segunda barreira |
| E2 | Caixa do item | `camadas/eap.py`, `camadas/eap_padrao.py` (só onde o código é lido) | o código é normalizado num lugar só: unidade e sistema como já são; DISC.PAC.ITEM em maiúsculas; mesma regra para a comparação com as folhas; `vista_do_codigo` continua função só do código |
| E3 | Testes | `tests/test_titulos_etapa.py` (ou novo) | IA e decisão com sistema linear sem declaração → recusadas na leitura com o motivo, ausentes de `fatos`; com declaração → aceitas; código em minúsculas casa a folha como em maiúsculas; Foz inalterada |
| E4 | Registro | `docs/EAP.md` §9.1, este plano, `results/rumo/wbs.yaml` | regras descritas; pendência tirada da lista |

## O que não muda

Foz (mista, declarada): mesmos números (9/45 e 7/32) e mesmo hash da cadeia real; roteiros de ataque da leitura por IA
com saída idêntica; `U1.LINEARES.*` e `rede_eta` na localizada.

## Verificação

Três verdes, suíte como o vcm roda com 0 falhas, hash de `camadas.referencia` = 0602c637…, roteiros de ataque
idênticos, cadeia real de Foz igual, `vcm balanco` sem REVERTER, aprovação do plano e aceite da entrega pelo Fable.
