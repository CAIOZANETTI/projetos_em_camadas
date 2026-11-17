# Plano PDCA — Captação CSP04, EEB09 e EEB10 / SAA Irati (LE 242/2025)

Obra: `exemplos/irati_captacao/obra.json` · PR #86 (`irati-captacao`) · 17/11/2026.

Este plano segue o ciclo de `CLAUDE.md` (especificar → executar em worktree → medir → decidir →
registrar). Cada frente de trabalho passa pelo PDCA abaixo. Agentes trabalham em paralelo só onde
não dividem arquivo nem dependem um do outro.

## 1. Onde estamos

| Frente | Situação | Fonte | Conferência independente |
|---|---|---|---|
| Ortofoto e nuvem 3D | feito | voo de 13/11 (32 fotos, 60 m) | malha da LAYLOC (36 cm) |
| Pranchas PBHI georreferenciadas | feito | LAYLOC, folhas 07, 09, 13 | ortofoto, ICP |
| Sondagens | só a Tabela 1, sem coordenada | PBGE-RT | boletins não recebidos |
| Quantitativos PBES | feito | 28 folhas + resumo | resumo com texto: 85.644 kg, 596,67 m³ |
| Fundações EEB09 e EEB10 | feito | 016 e 002 | PBHI 09/13 e ortofoto |
| Controle vertical | **provisório** (offset 812,02 m, ±0,41 m) | pisos concretados da EEB10 | terreno da EEB09; boca dos furos 798,00 |
| 3D EEB09, EEB10, descarregador | feito, com lacunas | 003–006, 017–019, 026 | ortofoto (22 cm), PBHI 09 (7,8 cm) |

**Não-conformidades a tratar primeiro:**

1. **O 3D não é reproduzível.** Os sólidos (`dados/irati_captacao/estrutura/*_estrutura.json`,
   `*_fundacao.json`, `csp04_descarregador.json`, `estacas_captacao.csv`) foram gerados por scripts
   descartáveis e moram em `dados/`, que o git ignora. Nenhum build os regera.
2. **Os commits da Irati não passaram por `vcm balanco`.**

## 2. Backlog

| Código | Item | Tipo | Depende de | Quem decide |
|---|---|---|---|---|
| **R1** | Leitura de forma PBES → sólidos 3D no build, com testes | código | — | gerente |
| R2 | Ponto de cota conhecida dentro do voo (RTK) | campo | — | Caio |
| R3 | Enviar o pedido dos boletins SPT (rascunho pronto) | decisão | — | Caio |
| E1 | EEB10: vigas, canais de descarga (PAR2/PAR4), pilar P9 | modelagem | R1 | gerente |
| E2 | EEB09: trecho baixo da ala (P16–P22–P23) no piso | modelagem | R1 | gerente |
| E3 | Descarregador: cortina de estacas (ensecadeira) | modelagem | R1 | gerente |
| Q1 | Armaduras posição a posição, folhas 001–014 | extração | — | gerente |
| Q2 | Armaduras posição a posição, folhas 015–028 | extração | — | gerente |
| S1 | Camada do KMZ "IRATI 31.08 Supressão Liberada" | código | — | gerente |
| S2 | Identificar pt0 e o levantamento 091114TRIBACK | campo | — | Caio |
| X1 | Escopo: estacas aparecem em "Unidade 1 — ETA Vila C" (regra de Foz) | código | — | gerente |
| X2 | HTML de 23,5 MB → ≤ 16 MB (publicável como artefato) | código | — | gerente |

## 3. Como cada item roda o PDCA

| Fase | Quem | O que entrega |
|---|---|---|
| **P** Plan | gerente + Caio | ficha do item: entrada, arquivos permitidos, saída, critério de aceite numérico, fonte independente do Check |
| **D** Do | executor (`executor-sonnet`, ou `executor-haiku` para tarefa mecânica), em worktree próprio | código e testes; relatório: arquivos, números, premissas, o que ficou de fora |
| **C** Check | verificador (agente novo, sem o raciocínio do executor) + gerente | pytest, ruff, `scripts/afericao.py`, `scripts/determinismo.py`, `vcm balanco`; conferência contra a fonte independente; veredito aprovado / com ressalva / reprovado |
| **A** Act | gerente + Caio | integra o aprovado; `obra.json`, `CHANGELOG.md`, `pdca/licoes.jsonl`, `results/agentes/execucoes.csv`; reprovado volta ao Plan com a causa |

Regras de arquivo: executores não tocam `obra.json`, `CHANGELOG.md`, `pdca/` nem `results/`; esses
são do gerente. Dois executores nunca escrevem o mesmo arquivo no mesmo ciclo.

Pontos de parada (o gerente espera o Caio): aprovar as fichas do Plan de cada ciclo; ver o veredito
do Check antes do commit; decisões de campo (R2, R3, S2).

## 4. Ciclos

| Ciclo | Itens | Agentes | Paralelo? |
|---|---|---|---|
| 1 | R1 (R1a → R1b → R1c) | 2 executores em série + 1 verificador | não: R1b usa R1a |
| 2 | E1, E2, E3, S1, X1 | 5 executores + 5 verificadores | sim |
| 3 | Q1, Q2, X2 | 3 executores + 3 verificadores | sim |
| Caio | R2, R3, S2 | — | a qualquer momento; R2 tira o "provisório" do controle vertical |

## 5. Ciclo 1 — ficha do R1 (leitura de forma PBES → sólidos 3D)

**Objetivo.** O build (`uv run python -m camadas.obra exemplos/irati_captacao/obra.json`) gera, a
partir dos PDFs e de parâmetros declarados no `obra.json`, os mesmos sólidos e estacas que hoje estão
em `dados/irati_captacao/estrutura/`. A saída vai para `saida/irati_captacao/` (regenerável), não
para `dados/`.

**O que existe hoje (só no scratchpad, a portar):**

| Função | Faz | Lição que já embute |
|---|---|---|
| `preenchidos(pdf, chaves, região)` | polígonos das áreas preenchidas por (layer, cor) | caminho fora de ordem vira retângulo do `rect`; sem duplicata exata |
| junção por grupo | une os pedaços de um pilar ou laje | pilar em dois triângulos (018); "sombra" duplicada (003); laje sobreposta (004) |
| `sem_furos` | parte polígono com abertura em faixas sem furo | o visualizador só extruda o contorno externo |
| `tracos` + `vigas` | vigas como pares de traços paralelos a uma largura dada | a borda da viga não fecha face (018) |
| alinhar por pilares | translação folha → folha pelos pilares casados | 13 de 13 a 0,1 pt (017/018 → 016), 8 de 8 (004 → 003) |
| correlação de linhas | translação folha → folha pelos traços de eixo e cota | 019 → 018; a correlação de vigas dá dois picos |
| alinhar por pilar desenhado | rotação e translação pelo P7 da EEB09 na 026 | rotação de 3,04° |
| montagem por estrutura | paredes, pilares, lajes, vigas, escoras com z0/z1 | topo por zona; fundo pela face dos blocos; escora em prismas |

**Divisão:**

- **R1a — primitivas** (`executor-sonnet`, worktree próprio).
  - Arquivos permitidos: `camadas/forma3d.py` (novo, ~10 funções, uma família: leitura de forma
    para sólido) e `tests/test_forma3d.py` (novo).
  - Testes com PDFs sintéticos gerados no próprio teste (PyMuPDF), sem dados reais. Cobrem:
    pilar em dois triângulos; preenchimento duplicado; laje com abertura vira peças sem furo; par de
    traços a 20 cm vira viga; translação recuperada a < 0,1 pt; cor da legenda → nível.
  - Aceite: `uv run pytest -q` sem falha nova; ruff limpo; `metadados()` com as premissas.
- **R1b — montagem declarativa no build** (`executor-sonnet`, depois do R1a).
  - Arquivos permitidos: `camadas/forma3d.py`, `camadas/obra.py` (só a etapa nova e a chamada),
    `tests/test_forma3d.py`, `tests/test_obra_caracterizacao.py` (só testes novos).
  - Chave nova no `obra.json`, `estruturas_3d`: por estrutura, as folhas, a transformação declarada
    (base + translação/rotação em pt, com a conferência que o build recalcula), a legenda cor → nível,
    as zonas de topo, os rótulos por posição e as alturas de seção.
  - O build regrava os sólidos em `saida/<obra>/estrutura/` e as estacas num CSV ali; a chave
    `solidos` passa a aceitar esses arquivos gerados. Conferência recalculada a cada build: pilar ×
    estaca ≤ 0,5 pt; se falhar, a estrutura sai do 3D com pendência no log (não derruba o build).
  - Aceite: teste de ponta a ponta com um `obra.json` sintético; nenhuma mudança nas obras sem a chave.
- **R1c — configuração da Irati e regeneração** (gerente, com os PDFs reais).
  - Escreve `estruturas_3d` no `obra.json` da Irati com os parâmetros que hoje estão nos metadados
    dos JSONs, e roda o build.
  - Aceite contra os arquivos atuais (gabarito): mesma contagem de elementos por tipo e estrutura;
    área por tipo ±1 %; z0/z1 iguais a 1 cm; 90 estacas a ≤ 2 cm. As diferenças entram no relatório,
    uma por uma.

**Check do ciclo 1** (verificador novo):
- recebe só esta ficha e o diff;
- roda pytest, ruff, aferição, determinismo e `vcm balanco HEAD~n HEAD`;
- refaz a conferência R1c;
- abre as sobreposições (ortofoto × paredes da EEB10; PBHI 09 × descarregador).
- Veredito por critério.

**Act do ciclo 1:**
- apagar de `dados/irati_captacao/estrutura/` os JSONs gerados à mão (ficam `pbes_ocr.json` e as
  leituras de tabela com conferência visual);
- lição no `pdca/licoes.jsonl`: "sólido gerado fora do build não é entrega";
- registrar as execuções em `results/agentes/execucoes.csv`;
- anexar o `vcm balanco` ao PR.

**Fora do ciclo 1:** novos elementos (E1–E3), armaduras (Q1–Q2), qualquer mudança no visualizador.
