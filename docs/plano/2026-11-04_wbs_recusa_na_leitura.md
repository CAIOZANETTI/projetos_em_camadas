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

## Parecer do Fable sobre o plano: APROVA, com quatro ajustes obrigatórios

1. **A declaração chega a `loop` por parâmetro**: `etapa` já calcula `eap_padrao.trechos_do_cfg(cfg)` (fonte única) e
   passa a `loop(trechos_lineares=...)`; `None` = não conferir. A recusa fica em `loop`, **não** em `_conferir_ia`
   (compartilhada com a CLI `conferir`, que não conhece a obra; documentar que a CLI não aplica esta trava).
2. **Um mecanismo só**: em `loop`, um filtro único (`eap.eh_trecho_linear` + par não declarado) remove de `evs`, antes
   de `_sem_ia_repetida`/`consolidar`/`gravar`, toda evidência com sistema linear não declarado — IA, decisão, regex
   e extras — e registra `{motivo, evidencia}` em `recusadas`. A planilha declarada passa porque o par está declarado.
   As decisões passam por `validar_evidencia` (motivo de recusa, nunca exceção).
3. **Visibilidade**: `etapa` devolve as recusas (código, serviço, valor, documento, motivo) e elas entram nos
   `avisos` da EAP padrão com o mesmo texto "Sistema de trecho linear não declarado na obra: …".
4. **E2, decisão do gerente: recusar, não normalizar.** O schema (`conceitos/evidencia.schema.json`) já exige
   maiúsculas no sistema e no item; a IA já é recusada ("código fora do padrão"). Com o ajuste 2, a decisão também
   passa por `validar_evidencia` e o código fora do padrão é recusado com motivo. Nenhum código em minúsculas chega
   às folhas; `_item_do_codigo` não muda. A chamada direta de `preencher` (só em teste) fica fora do contrato.

Efeitos: Foz não tem IA, decisões nem documento com `sistema`, e o trecho está declarado, então E1 é vazia para
Foz. `camadas.referencia` não mede estes caminhos; o invariante útil é o hash da cadeia real de Foz (c5c2d5cd).

## Aceite

Aceite Fable 04/11/2026: ACEITA e605366 — recusa na leitura em `loop` como filtro único com declaração por parâmetro,
decisões validadas pelo schema, recusas visíveis nos avisos sem duplicar; Foz idêntica (hash c5c2d5cd) e três verdes
reproduzidos pelo revisor. Opcional tratado no mesmo PR: o aviso escolhe o texto pelo motivo (decisão inválida ganha
aviso próprio e não aparece como "não declarado"), com teste. Opcionais registrados: `sistema` em minúsculas no
`obra.json` levanta `ValueError` em `buscar_texto` (pré-existente); `pares_declarados` fora de `metadados()["funcoes"]`.
