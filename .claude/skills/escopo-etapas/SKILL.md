---
name: escopo-etapas
description: Extrai o escopo de materiais/serviços do orçamento (planilhas Sanepar/USMA) com quantidades por etapa e liga tabelas de material às pranchas e às cores de etapa do layout, para conferir visualmente o que pertence a cada etapa e o que está fora do escopo. Use quando o usuário falar de etapas da obra, recorte de escopo, quantitativos, lista de materiais, cotação ou "o que entra na 1ª etapa".
---

# Escopo por etapa

## Fontes (em ordem de autoridade)
1. **Layout de processo** (Sanepar PBHI-DE-0001…LAYOUTPROCES): legenda de cores = etapas
   (azul 1ª, roxo 2ª, hachura vermelha "unidades futuras 3ª etapa", hachura verde existente a
   restaurar 1ª/2ª, laranja tracejado existente a manter, hachura azul "civil na 1ª, equipamentos na 2ª").
   `pdf_cad.REGRAS_ETAPA_SANEPAR` classifica por layer + cor; `pdf_cad.manchas` gera áreas por etapa.
2. **Escopo_1etapa** (PBES) e **Termo de Referência** — texto oficial; cite literalmente.
3. **Orçamento** (xlsx): aba oculta `Relação de Materiais` com "Quantidade 1ª etapa" e "2ª etapa"
   por tabela (01…N) ligada ao desenho; `MATS E EQUIP` com preços; `CUSTO CIVIL` (serviços).

## Extração
```bash
python -m camadas.orcamento_sanepar dados/<obra>/orcamento   # principal.xlsx, cotacao_*.xlsx
```
Gera `escopo_itens.csv`, `relacao_materiais_etapas.csv`, resumos e cotações (sep `;`, decimal `,`).
Para planilhas de outro cliente, delegue a um agente **Sonnet** a adaptação das funções
`extrair_*` (cabeçalho, colunas, blocos) — mantenha a mesma saída.

## Conferência que importa
- itens sem etapa (equipamentos, válvulas, civil global) ⇒ "verificar";
- quantidade do orçamento ≠ quantidade da 1ª etapa ⇒ divergência (liste);
- tabelas só da 2ª etapa não orçadas ⇒ fora do escopo (confirme com o TR);
- etapas no desenho que o TR não menciona (ex.: 3ª etapa em Foz) ⇒ pergunta ao cliente.
No HTML, a aba **Etapas & escopo** filtra manchas, layers e itens pela etapa e grava a situação
de cada item (no escopo / fora / verificar) para exportar.
