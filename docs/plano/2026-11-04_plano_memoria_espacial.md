# Plano da memória espacial: onde estamos e onde vamos chegar (04/11/2026)

Aprovado pelo Caio em 04/11/2026 ("pode gravar o plano e seguir com a A4"). Complementa `docs/MEMORIA_ESPACIAL.md`
(§6 MVP e §8 Estado).

## Onde vamos chegar

Para cada obra, um HTML com a EAP completa. Cada quantidade leva, com um clique, ao serviço, ao fato, à evidência e ao
recorte do documento de origem. Tudo é calculado em código, sem IA no resultado, e conferido contra testemunhas
independentes.

| # | Pergunta da tese | Como se prova |
|---|---|---|
| T1 | Cada informação tem lugar certo e evidência? | 0 fato sem evidência, em Foz e numa 2ª obra |
| T2 | O cálculo pelas gavetas reproduz o atual? | paridade 0 em todas as regras, com dado real |
| T3 | As quantidades conferem contra uma testemunha independente? | conferência por elemento, com tolerância declarada |
| T4 | A EAP serve ao engenheiro? | a aba EAP conferida pelo Caio e usada numa obra |

## Onde estamos (0.56.0)

| Peça | Estado |
|---|---|
| Fundação: gavetas, três de-para e formato Parquet | feito (0.24 a 0.30) |
| Cálculo pelas gavetas: valas e cavas | feito; paridade 0 em Foz |
| EAP codificada e conciliação | feito (0.36) |
| Build real de Foz | feito (0.45) |
| Conferência independente das cavas por seções de corte | feito (0.53); falta ligar cada marca de cota à sua estrutura |
| Terreno validado pela topografia do projeto | feito (0.56); rms 0,17 m contra 14 sondagens |
| Leitura direta das pranchas → gavetas | parcial: redes e cavas sim; trecho de tubo por planta e perfil não |
| Obras lineares da ETA | bloqueado: falta a planilha do protótipo |
| EAP → recorte da prancha (clique) | parcial: chega à evidência, não ao recorte |
| Aceite humano da aba EAP | a fazer |
| 2ª obra | a fazer |

MVP do `MEMORIA_ESPACIAL.md` §6: 3 de 5 passos feitos (1, 3 e 5). O passo 2 (leitor de prancha) e o passo 4 (recorte)
estão parciais.

## O que falta

### Fase A: fechar a ETA de Foz

| Rodada | Entrega | Executor | Aceite | Depende do Caio |
|---|---|---|---|---|
| A1 | Obras lineares da ETA nas gavetas (trechos OL), com paridade contra `obras_lineares.quantificar` | Sonnet | paridade 0; a EAP inclui `GEO.MOV.VAL` das tubulações da ETA | **sim:** a planilha do protótipo (anexo da conversa da Giselle) |
| A2 | Setores reais da ETA no obra.json e EAP por setor | Opus | a soma dos setores confere com o total | **sim:** polígonos ou regra dos setores |
| A3 | Estacas lidas das formas em código, no lugar do `estacas.csv` | Sonnet | estacas com E/N e evidência; a cava ganha sistema pela regra `cava_maioria` | confirmação da origem do csv atual |
| A4 | Marca de cota ↔ estrutura: o fundo de cada base pela sua própria marca, não pela vizinha (HH e FF) | Sonnet | o fundo bate com o corte em todas as seções conferíveis | não |
| A5 | NSPT do laudo Geoazimute (tabela gráfica do perfil) | Sonnet | NSPT por metro nos 23 furos, conferido à mão em 3 | não |

### Fase B: ler direto das pranchas

| Rodada | Entrega | Aceite |
|---|---|---|
| B1 | Trecho de tubo pela planta: traço georreferenciado, DN e material pelo balão e pela relação de materiais | casa com a planilha (A1): comprimento ±1 %, DN exato |
| B2 | Perfil longitudinal → profundidade por trecho, ligado às gavetas | confere com a planilha |
| B3 | Quantidade → recorte da prancha no HTML (passo 4 do MVP) | um clique abre o recorte certo; teste em Chromium |
| B4 | Linhas de seção incompletas e quebradas (DD, EE, KK, CC); perfil por segmentos | mais seções conferíveis |

### Fase C: medir a tese

| Rodada | Entrega | Aceite |
|---|---|---|
| C1 | G05: o formato das gavetas medido na base real de Foz | decisão do formato revalidada, ou trocada com evidência |
| C2 | G01: F1 por elemento contra um gabarito conferido pelo Caio | gabarito trancado; F1 por classe |
| C3 | Chave barata para o 2º cálculo | 2º cálculo ≤ 10 % do 1º em 100 km |
| C4 | Determinismo do SfM entre duas reconstruções | variação declarada (hoje +0,3 %) |

### Fase D: aceite e generalização

| Rodada | Entrega | Aceite |
|---|---|---|
| D1 | O Caio confere a aba EAP de Foz: 10 quantidades ao acaso, do número ao documento | aceite registrado |
| D2 | 2ª obra só com configuração, sem código novo | 0 fato sem evidência; o que quebrar vira lição |
| D3 | Fechamento da tese: T1 a T4 no `MEMORIA_ESPACIAL.md` §9 | relatório final com as métricas |

## Ordem

```
Agora:      A4 → A5 → B4                     (só código)
Com o Caio: A1 (planilha) → A2 (setores) → A3 (estacas)
Depois:     B1 → B2 → B3 → D1 (aceite da aba EAP)
Medição:    C1 → C2 (gabarito) → C3 → C4
Fecho:      D2 (2ª obra) → D3
```

Cada rodada segue o mesmo ciclo:
1. rumo;
2. executor em worktree, com testes;
3. build real;
4. `vcm balanco`;
5. aceite do Fable;
6. PR e merge.
