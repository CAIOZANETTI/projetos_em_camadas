# Arquitetura — projetos em camadas (R6, 30/10/2026)

Diagrama e cenário de mesa: https://claude.ai/artifact/ESsAkB2JX7JZgBdRRxPzyg (privado; peça acesso ao Caio).

## 1. Princípios

1. **Só escopo.** Serviços e atividades numa EAP com quantidades. Sem preço, sem prazo: nada de valor unitário,
   fornecedor, cronograma, 4D, curva S ou produtividade (decisões do Caio, 28/10 e 30/10/2026).
2. **A EAP é a linha mestra; os documentos são evidências; o georreferenciamento é o jeito de ver no local**
   (`docs/EAP.md`).
3. **Um arquivo HTML** é a entrega e a memória da obra: os dados, os fatos e as decisões moram dentro dele.
4. **Código para a certeza, IA para a dúvida.** O código extrai, mede e confere. A IA trabalha só no que o código não
   resolve e sempre com citação conferida. Cada dúvida resolvida vira regra com teste (§8).
5. **A decisão do engenheiro prevalece sobre a evidência**, sem apagá-la.

## 2. Inventário primeiro (portão G0)

Nada se lê antes de existir o inventário de **todos** os arquivos, e nada se afirma ausente sem consultá-lo. Lição
L008: a forma e a armadura do Actiflo 360 foram dadas como inexistentes e existiam. Em Foz, as formas dos Actiflo
estavam na listagem como PDFs acima de 5 MB, não baixados.

| # | Passo | Quem | Estado |
|---|---|---|---|
| 1 | Listagem recursiva do Drive: todo arquivo, de qualquer tipo (pasta não) | Haiku (conector) | feito |
| 2 | Download dos pendentes pelo link direto, conferindo `%PDF` e tamanho; arquivo privado fica como falha, com o motivo, para você liberar | código (`camadas/drive.py`) | feito |
| 3 | Loop em todos os arquivos com o leitor do tipo: PDF (formato, layers, código, carimbo), planilha (abas, inclusive ocultas), zip (conteúdo sem extrair); o resto fica "sem leitor", à vista | código (`inventario.ler_arquivo`) | feito |
| 4 | Situação final de cada arquivo: no disco e lido · lido com erro · sem leitor · falhou · não tentado | código | feito |
| 5 | Ausência só por consulta: `inventario.procurar(inv, padrão)` busca nome, pasta e título do carimbo em qualquer situação e separa "existe, não lido" de "não existe" | código | feito |
| 6 | O que cada arquivo entrega: arquivo → sistema × disciplina × conteúdo (planta, forma, armadura, locação, memorial…) pelo código Sanepar, pelo carimbo e pelos termos da EAP | código | a fazer |
| 7 | Esperado × encontrado: para cada sistema, os documentos que a tipologia exige (forma, armadura, locação e cargas, fundação) → achado ou falta, pela busca do passo 5 | código | a fazer |
| 8 | Índices cruzados: cada desenho citado na Relação de Desenhos e nos anexos do edital casa com um arquivo; citado e não achado vira alerta (Foz: 58 dos 104 desenhos da Relação do PBES não estão no Drive, rodada 18) | código | a fazer |
| 9 | PDF com várias folhas: carimbo e título de cada página, não só da primeira | código | a fazer |

O G0 fecha quando 100 % dos arquivos têm situação final e o relatório "esperado × encontrado" foi gerado. Os agentes
só entram nos arquivos sem leitor, e cada um vira candidato a leitor novo (regra da lição, §8).

## 3. Camadas

| # | Camada | Quem | Saída |
|---|---|---|---|
| 1 | Fontes: fotos, pranchas, planilha, TR, memoriais, laudos | — | `dados/<obra>/` (fora do git e do HTML) |
| 2 | Inventário e tipo: planta, perfil, detalhe, documento; disciplina | código (Haiku só baixa) | inventário |
| 3 | EAP da obra: unidades, sistemas, água/esgoto, localizada/linear | IA propõe, você confirma | sistemas da obra |
| 4 | Loop de evidências: texto, planilha, pranchas, associados, IA | código; IA no que sobra | evidências |
| 5 | Fatos: código EAP × serviço × unidade (convergente, fonte única, conflito, só menção, decidido) | código | fatos |
| 6 | EAP com quantidades, cobertura item × projeto × edital, regra dos 100 % | código | árvore da EAP |
| 7 | Caderno HTML: blocos `eap`, `fatos`, `camadas`, `decisões`, `dúvidas`, `versões` | código | `saida/<obra>/<id>_camadas_v…html` |

**Tipos de documento.** Planta: georreferenciada. Perfil: ancorado pela estaca ao trecho. Detalhe (armadura, forma,
corte): ancorado ao elemento, nunca georreferenciado. Documento: texto e tabelas.

**Disciplinas.**
- Civil e geotecnia: elementos pela geometria → dimensões → serviços associados (`dimensoes.json`,
  `servicos_associados.jsonl`).
- Hidráulica: relação de materiais da prancha (OCR), memorial descritivo e planilha, todos ligados ao cadastro
  Sanepar de 40 mil materiais.
- Elétrica: pranchas PBEA com texto real, listas de materiais e de cabos, quadros de carga e cadastro elétrico.
  Hoje só termos; o leitor de listas é lacuna.

## 4. Decisões: ida e volta

Schema único: `{id, alvo (prefixo da EAP), estado (executar | nao_executar | a_definir), motivo, autor, data,
supera[]}`. O build aplica as decisões **antes** dos cálculos e elas descem para os filhos e os serviços associados.
Exemplo: sem drenagem urbana, também não há vala nem pavimento da drenagem. O HTML mostra a evidência superada e o nó
riscado, fora da soma. Ao gravar, o navegador gera uma nova versão do arquivo com o bloco de decisões. O build
seguinte lê esse bloco. Um teste de ida e volta garante que nada se perde.

## 5. Quem faz o quê

| Executor | Papel |
|---|---|
| Código | tudo o que já é certeza; valida o que os agentes devolvem |
| Haiku | volume mecânico: listar e baixar o Drive (um por pasta), conferir contagens |
| Sonnet | leitura técnica em volume (memoriais, laudos, perfil de planilha, listas); módulo a partir de contrato fixo |
| Fable | revisor independente: crítica de arquitetura, cenário de mesa, revisão de PR sem ver a conclusão do autor |
| Opus | sessão principal: contrato de saída, georreferência difícil, revisão das dúvidas, integração e PR |
| Você | sistemas da obra nova, decisões de execução, confirmação de regra nova |

Regras do paralelismo:
- o contrato de saída é fixado antes de abrir os lotes;
- lotes sem sobreposição;
- a prancha não vai inteira para a IA;
- cada agente devolve schema + dúvidas, nunca texto livre.

## 6. Processo (portões)

| Portão | O que fecha |
|---|---|
| G0 | inventário de todos os arquivos com situação final, esperado × encontrado e orçamento de MB por bloco |
| G1 | EAP da obra com os sistemas confirmados |
| G2 | extração por perfil, com as dúvidas na fila |
| G3 | georreferência e âncoras (drone opcional) |
| G4 | fatos |
| G5 | decisões aplicadas |
| G6 | serviços associados, com um motor por assunto |
| G7 | caderno HTML dentro do orçamento de tamanho |

## 7. O que o cenário de mesa mostrou (obra nova: elevatória + 3 km de rede de esgoto)

Trava em cinco pontos. As correções da R4 são estas:

1. **Sistemas da obra**: `unidades_construtivas.json` só tem Foz. Correção: separar conceito (todas as obras) de obra
   (sistemas no caderno).
2. **Planilha**: `orcamento_sanepar.py` fixa as abas de Foz. Correção: perfil de planilha em JSON e leitor genérico.
   A IA escreve o perfil, não o código.
3. **Obra sem drone**: o build exige o SfM. Correção: drone opcional, com base satélite.
4. **Três motores de vala** com regras diferentes (`valas.py`, `dimensoes.dimensionar_vala`, `obras_lineares`).
   Correção: um dimensionador, com o MOS Sanepar como padrão.
5. **Decisões**: a exportação do navegador usa outra chave e fica fora do HTML. Correção: o schema único do §3.

## 8. Regra da lição aprendida e índice de determinismo

**Regra.** Toda rodada com a IA deixa ao menos uma lição formalizada em código: uma regra em `conceitos/` ou uma
função, e um teste. As lições ficam em `pdca/licoes.jsonl`, com `licao`, `antes`, `formalizada_em`, `teste` e
`estado`. A rodada não se registra sem lição nova.

**Índice.** O índice mede a **IA na obra**, não a IA no desenvolvimento:
- **IA na obra**: um agente leu, julgou, configurou ou operou para que o dado existisse;
- **IA no desenvolvimento**: escrever código e regras. É o papel criativo da IA e o caminho para ela virar código.

`pdca/determinismo.json` lista cada etapa do processo com o executor (`codigo`, `ia` ou `humano`), o número de itens
da obra e, nas etapas de IA, o que falta para virar código (`para_codigo`). A decisão humana fica fora do índice: ela
é desejada.

```
python scripts/determinismo.py              # mede e confere as lições
python scripts/determinismo.py --registrar  # grava a rodada em pdca/determinismo.jsonl
```

O script reprova em três casos:
- lição dada como formalizada cujo arquivo ou teste não existe;
- índice por etapas pior que o da última rodada;
- rodada registrada sem lição nova.

**Base (Foz, 30/10/2026):**

| Medida | Base | Após a rodada 18 | |
|---|---:|---:|---|
| Etapas do processo (código / IA) | 12 / 9 = **57,1 %** | 13 / 8 = **61,9 %** | o download passou a código (`camadas/drive.py`) |
| Registros (PDFs, itens, estacas, furos…) | 2 518 / 952 = 72,6 % | 2 684 / 791 = 77,2 % | |

As 8 etapas que ainda são de IA, por papel:
- **operação** (1): listar o Drive (conector);
- **julgamento** (3): afim da GEOPLANTA, 7 afins coladas, conferência visual;
- **leitura** (2): sondagens e estacas;
- **configuração** (2): configuração por prancha e sistemas da obra.

Houve 1 decisão humana: o módulo de filtros fora do escopo.

**Meta:** 85 % das etapas em código, com +5 p.p. por rodada: são 5 rodadas a partir de hoje. As próximas etapas a
virar código são as de menor esforço:
1. as 7 afins coladas → irmã CAD × CAD da GEOPLANTA no build;
2. a afim da GEOPLANTA → ajuste no build pelas sondagens;
3. a conferência visual → testemunha independente com limiar;
4. a configuração por prancha → perfil por disciplina.

Os 15 % restantes ficam com a IA criativa: dúvida nova, obra nova e melhoria do próprio código.
