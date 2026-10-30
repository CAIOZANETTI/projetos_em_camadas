# Arquitetura — projetos em camadas (R7, 30/10/2026)

Diagrama, cenário de mesa e índice: https://claude.ai/artifact/ESsAkB2JX7JZgBdRRxPzyg (privado; peça acesso ao Caio).

## 1. Princípios

1. **Só escopo.** Serviços e atividades numa EAP com quantidades. Sem preço e sem prazo: nada de valor unitário,
   fornecedor, cronograma, 4D, curva S ou produtividade (decisões do Caio, 28/10 e 30/10/2026).
2. **A EAP é a linha mestra; os documentos são evidências; o georreferenciamento é o jeito de ver no local**
   (`docs/EAP.md`).
3. **Inventário primeiro, e reavaliado.** Nada se lê antes do inventário de todos os arquivos. Depois de cada
   extração, o inventário é reavaliado: o que não saiu, ou saiu incompleto, volta para o loop (§2).
4. **Todo fato diz de onde veio**: a classe da fonte (projeto, memorial, laudo, folha de dados, ordem de serviço…),
   o documento, o local dentro dele, o método e o passe (§3).
5. **Código para a certeza, IA para a dúvida.** O trabalho braçal vai para os agentes menores e o julgamento para os
   maiores. Cada dúvida resolvida vira regra com teste (§9).
6. **A decisão do engenheiro prevalece sobre a evidência**, sem apagá-la (§6).
7. **Um arquivo HTML** é a entrega e a memória da obra: dados, fatos, pendências e decisões moram dentro dele.

## 2. O ciclo de extração: inventário → extração → reavaliação → loop

```
pastas da obra ─► P0 inventário ─► P1 código ─► reavaliação ─► completa? ─ sim ─► fatos
                       ▲                              │ não
                       │                              ▼
                       └──── próximo passe da escada (código alternativo → Haiku → Sonnet → Opus → você)
```

**P0 · Inventário por pasta.** Cada obra tem a própria árvore no Drive, e cada pasta raiz tem um papel:
- orçamento/licitação: edital, projetos, planilha;
- obra/execução: ordens de serviço, folhas de dados, projeto executivo, atas;
- referências.

O papel da pasta vai para o `obra.json` (`inventario.pastas`, **a fazer**) e orienta a classe da fonte. A listagem
recursiva traz todo arquivo, de qualquer tipo (`camadas/inventario.py`). O download dos pendentes é feito por
`camadas/drive.py`, pelo link direto.

**P1 · Leitura por código.** Cada tipo de arquivo tem seu leitor:
- **PDF**: formato, layers, código Sanepar, carimbo;
- **planilha**: abas, inclusive as ocultas;
- **zip**: o conteúdo.

O que não tem leitor fica "sem leitor", à vista.

**Reavaliação** (`camadas/extracao.py`, regras em `conceitos/fontes.json`). Roda a cada build e grava
`saida/<obra>/pendencias.json`. Para cada arquivo, ela calcula:
- **classe da fonte**, em passadas: termos de cotação e de documento de obra, tipo do código Sanepar (DE, MD, RT,
  LM…), extensão e, por fim, termos no caminho, no nome e no carimbo;
- **estado**: completa · parcial · falhou · sem leitor · fora do disco. A classe exige campos para contar como
  completa: uma prancha precisa de título, folha e escala no carimbo; laudo, memorial e edital precisam ter texto;
- **próximo passe** da escada, para cada situação;
- **séries de folhas** pelo carimbo: "FOLHA 06/14" diz que a série tem 14 folhas, e as que não aparecem na listagem
  viram pendência;
- **registro** `saida/<obra>/extracao.jsonl`: uma linha por arquivo cada vez que o estado muda, com o passe e o
  executor. Mostra quantas voltas cada arquivo levou e quem resolveu.

**A escada** (`conceitos/fontes.json`, `escada`). A IA só entra depois que o código tentou:

| Situação | Próximo passe | Ação |
|---|---|---|
| fora do disco | código | `camadas/drive.py`; arquivo privado: você libera |
| falhou | código → Haiku | repetir a leitura; persistindo, o Haiku diz o que o arquivo é (protegido, corrompido, digitalizado) |
| carimbo incompleto | código → Haiku | OCR do carimbo em todas as páginas e em 300 dpi; persistindo, o Haiku lê o recorte do canto inferior direito |
| sem texto | código → Sonnet | OCR de página inteira; persistindo, o Sonnet lê a imagem com citação |
| sem leitor | Sonnet | lê e devolve no schema da classe, com citação; o leitor em código vira candidato a lição |
| classe desconhecida | Haiku | diz a classe pelo nome, pela pasta e pela 1ª página; a resposta vira termo novo em `fontes.json` |
| conteúdo não inventariado | código | extrair e inventariar o conteúdo do compactado |
| conflito ou julgamento | Opus | decide com as evidências; o que for regra vira `conceitos/` |
| fechamento | Fable | audita uma amostra e o relatório de pendências sem ver a conclusão de quem extraiu |

**Rodar mais de uma vez é desejado.** O inventário tem cache por arquivo, o registro só grava quando o estado muda
e a reavaliação é determinística. Cada volta fecha as pendências que o passe anterior abriu.

O loop para em dois casos:
- tudo completo;
- a escada esgotou: aí vira pendência sua, com o motivo.

O índice `completas_por_codigo` (fração dos arquivos completos sem nenhum passe de IA) mede o progresso.

**Ausência só por consulta.** `inventario.procurar(inv, padrão)` busca no nome, na pasta e no carimbo, em qualquer
situação, e separa "existe, não lido" de "não existe". A forma do Actiflo 360 foi dada como inexistente e existia
(lição L008).

**Ainda a fazer no ciclo:**
- papel por pasta;
- carimbo de todas as páginas;
- esperado × encontrado por sistema (forma, armadura, locação e cargas, fundação);
- os passes de código alternativo (OCR do carimbo em 300 dpi, OCR de página inteira, extrair o zip).

## 3. Fontes de evidência: o que cada documento entrega

| Classe | Exemplos | Entrega |
|---|---|---|
| projeto | pranchas DE (planta, perfil, detalhe), DWG | geometria, layers, tabelas de material, carimbo |
| memorial | MD, MC, ES, caderno | o que se constrói, materiais, critérios de medição |
| laudo | RT: sondagem, topografia, ensaio | furos, camadas, NSPT, NA, coordenadas |
| lista | LM, LC, QC | itens e quantidades de material, cabos, cargas |
| edital | edital, TR, anexos, minuta | escopo oficial, etapas, decisões do cliente |
| planilha | contrato, quantitativos (sem preço) | itens e quantidades por etapa |
| folha de dados | datasheet, catálogo, ficha técnica | equipamento, tag, vazão, potência, DN, PN |
| documento de obra | ordem de serviço, ata, notificação, ofício | o que será executado, liberado, por quem |
| cotação | proposta de fornecedor | **fora do escopo** (preço); fica no inventário |

**Todo fato carrega a fonte:**
- `classe`, `documento`, `id_drive`;
- localizador (página e linha, aba e célula, layer e ids dos elementos);
- trecho literal;
- `metodo` (texto, OCR, geometria, planilha, IA, decisão);
- `passe` e `executor`.

Esse formato já é o da evidência do ramo da EAP (`evidencia.schema.json`); ganha `classe` e `passe`. A força de um
fato é o número de **classes** que concordam, não de arquivos: projeto + memorial + planilha concordando vale mais
que três folhas do mesmo projeto. Hierarquia quando discordam:
1. decisão;
2. documento de obra;
3. edital;
4. planilha do contrato;
5. projeto;
6. memorial;
7. folha de dados.

## 4. Interpretação dos projetos pelo carimbo

O carimbo fica no canto inferior direito (ABNT NBR 10582; região de 200 × 115 mm em `inventario.CARIMBO_MM`). A
leitura tenta três fontes, nesta ordem:
1. texto do PDF;
2. fonte embaralhada reparada;
3. OCR, quando o texto vem em traço SHX.

Campos lidos: título, folha n/m, escala, data. A completar: unidade construtiva, revisão, projetista e responsável.
O carimbo serve para:
- **identidade**: título e unidade decidem o sistema da EAP; a escala confere a georreferência (vista em 1:100 não
  encaixa numa folha em 1:250);
- **completude**: a série n/m acusa folhas faltando (feito); a Relação de Desenhos acusa desenhos citados e não
  entregues (rodada 19: 104 citados, 58 não entregues);
- **coerência**: revisão e disciplina do carimbo × as do nome do arquivo. Divergência vira pendência (a fazer);
- **todas as páginas**: um PDF de várias folhas tem um carimbo por página (a fazer; hoje só a 1ª).

## 5. Disciplinas

**Geotecnia é separada da civil**, com análise própria, porque a interpretação da sondagem decide boa parte do
escopo de movimento de terra e de fundação.

O que existe hoje:
- `sondagens.json` escrito por um agente a partir do laudo, sem schema validado;
- dois interpretadores divergentes, `obras_lineares.py` (main) e `dimensoes.dimensionar_vala` (ramo EAP):

| Ponto | `obras_lineares` | `dimensionar_vala` |
|---|---|---|
| raio de influência do furo | 60 m | 300 m |
| margem do NA | 0 | 0,5 m |
| impenetrável | só se a descrição diz | é topo de rocha |
| categoria de escavação 1ª/2ª/3ª | sim | não |
| empolamento | 1,30 | 1,25 (solo) / 1,50 (rocha) |
| cota do terreno × boca do furo | ignorada | considerada |

**Módulo `geotecnia`** (a fazer):
1. **Leitor de laudo por código**: tabela de coordenadas (com EPSG e datum declarados) e perfil SPT por furo
   (camadas, NSPT, NA, impenetrável), lidos do texto do PDF, com schema validado. O que não sair fica "não lido" e
   entra na escada.
2. **Modelo geotécnico único** (`conceitos/geotecnia.json`): perfil por furo, interpolação entre furos com a
   distância reportada e as funções `perfil(E, N)`, `topo_rocha`, `na`, `categoria_em(h)`. Os dois interpretadores
   passam a chamá-lo.
3. **Serviços GEO na EAP**: escavação por categoria, esgotamento e rebaixamento, escoramento por tipo, comprimento de
   estaca até a camada resistente, bota-fora, empréstimo e contenção.
4. **Conferências projeto × sondagem**:
   - estaca projetada × topo do impenetrável;
   - fundo de cava × NA;
   - boca do furo × terreno do MDS (já existe);
   - trecho fora do raio de qualquer furo.
5. **Relatório geotécnico independente** na aba EAP: furos, modelo, serviços e conflitos, separado da civil.

**Civil**: estruturas de concreto, edificações e pavimentação. Elementos pela geometria → dimensões → serviços
associados (forma, concreto, armadura por taxa, lastro, escoramento de laje). As formas dos Actiflo já entram pelo
build (rodada 18).

**Hidráulica**: três fontes, todas ligadas ao cadastro Sanepar de 40 mil materiais:
- relação de materiais da prancha, lida por OCR (balão → item);
- memorial descritivo como especificação (material, DN, PN, norma);
- planilha do contrato.

**Elétrica**: pranchas PBEA com texto real, listas de materiais e de cabos, quadro de cargas. Hoje só termos; o
leitor de listas é lacuna.

## 6. Decisões: ida e volta

Schema único: `{id, alvo (prefixo da EAP), estado (executar | nao_executar | a_definir), motivo, autor, data,
supera[]}`.
- O build aplica as decisões **antes** dos cálculos.
- Elas descem para os filhos e para os serviços associados: sem drenagem urbana, também não há vala nem pavimento da
  drenagem.
- O HTML mostra a evidência superada e o nó riscado, fora da soma.
- Ao gravar, o navegador gera uma nova versão do arquivo com o bloco de decisões; o build seguinte lê esse bloco.
- Um teste de ida e volta garante que nada se perde.

## 7. Quem faz o quê

| Executor | Papel no ciclo |
|---|---|
| Código | inventário, leitores, reavaliação, georreferência, dimensões, associados; valida tudo o que os agentes devolvem |
| Haiku | braçal: listar o Drive, dizer a classe de arquivo desconhecido, ler um recorte de carimbo, conferir contagens |
| Sonnet | leitura técnica em volume: arquivos sem leitor, laudos, memoriais, listas, perfil de planilha; módulo a partir de contrato fixo |
| Opus | sessão principal: contrato de saída, conflitos, georreferência difícil, revisão das dúvidas, integração e PR |
| Fable | revisor independente: auditoria do fechamento do ciclo, crítica de arquitetura, revisão de PR |
| Você | sistemas da obra nova, decisões de execução, arquivos privados, confirmação de regra nova |

Regras do paralelismo:
- o contrato de saída é fixado antes de abrir os lotes;
- lotes sem sobreposição (por pasta, por classe de fonte);
- a prancha não vai inteira para a IA, só o recorte em dúvida;
- cada agente devolve schema + dúvidas, nunca texto livre, e o passe dele entra no registro.

## 8. Processo (portões)

| Portão | O que fecha |
|---|---|
| G0 | inventário por pasta, reavaliado; nenhum arquivo sem estado; séries e índices cruzados conferidos |
| G1 | EAP da obra com os sistemas confirmados |
| G2 | extração em loop até a escada esgotar; pendências restantes com motivo |
| G3 | georreferência e âncoras (drone opcional) |
| G4 | fatos com a fonte de cada um |
| G5 | decisões aplicadas |
| G6 | geotecnia (modelo único) e serviços associados, um motor por assunto |
| G7 | caderno HTML dentro do orçamento de tamanho |

## 9. Regra da lição aprendida e índice de determinismo

**Regra.** Toda rodada com a IA deixa ao menos uma lição formalizada em código: uma regra em `conceitos/` ou uma
função, e um teste. As lições ficam em `pdca/licoes.jsonl`, com `versao`, `licao`, `antes`, `formalizada_em`, `teste`
e `estado`. Desde a 0.21.0, **cada versão do CHANGELOG a partir da 0.19.0 precisa de ao menos uma lição**, e um teste
reprova a falta (`tests/test_determinismo.py`). Assim a regra vale para qualquer sessão, não só para quem lembra
dela.

**Índice.** O índice mede a **IA na obra**: um agente leu, julgou, configurou ou operou para o dado existir. Não mede
a IA no desenvolvimento (escrever código e regras), que é o papel criativo dela e o caminho para virar código. A
decisão humana fica fora do índice.

```
python scripts/determinismo.py              # mede e confere as lições
python scripts/determinismo.py --registrar  # grava a rodada em pdca/determinismo.jsonl
```

| Medida (Foz) | Base | Rodada 18 | 0.21.0 |
|---|---:|---:|---:|
| Etapas do processo em código | 12 / 21 = 57,1 % | 13 / 21 = 61,9 % | **14 / 22 = 63,6 %** |

A reavaliação do inventário entrou como etapa de código. Antes, essa conferência era da IA na sessão.

**Meta:** 85 % das etapas em código. Próximas a converter:
1. 7 afins coladas;
2. afim da GEOPLANTA;
3. conferência visual;
4. configuração por prancha;
5. **leitor de laudo de sondagem** (geotecnia, §5).

O segundo índice, `completas_por_codigo` (§2), mede o mesmo por arquivo: quantos saem completos sem passe de IA.
