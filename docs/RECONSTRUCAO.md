# Reconstrução: da extração à navegação pela EAP, só escopo (proposta, 04/11/2026)

Pedido do Caio (04/11/2026):

> O HTML está muito confuso [...] não está operacional. Primeiro uma arquitetura de extração de dados com as
> gavetas e depois a navegação do usuário pela EAP e pelo escopo, para ter evidência de tudo: de onde veio cada
> quantidade e cada detalhe do projeto, a EAP navegável apontando no mapa e nas pranchas. [...] O projeto cresceu
> muito e perdeu o foco. [...] Um processo estruturado, com começo, meio e fim.

Este documento é a **proposta para aprovação**. Nenhum código muda antes do "ok" do Caio às decisões da §5.

## 0. O fluxo do Caio × o que o código faz hoje (conferido no build de Foz, 04/11/2026)

O Caio definiu o fluxo (04/11/2026):

> Loop em todos os arquivos → inventário → classificação → abrir cada arquivo e extrair com código → gavetas (escopo
> e localização, para georreferenciar) → percorrer os modelos de EAP (obra linear, obra localizada) preenchendo com
> o que está nas gavetas → calcular os serviços complementares (adutora: demolição de pavimento, escavação,
> escoramento, rebaixamento, reaterro e recomposição por tipo de pavimento; localizada: escavação da fundação,
> impermeabilização, escoramento de laje…) → **o processo termina quando a EAP está completa.**

| # | Passo | Peça no repositório | Situação em Foz | Lacuna |
|---|---|---|---|---|
| 1 | Loop em todos os arquivos e inventário | `inventario.py` (pela listagem do Drive, cache por arquivo) | **funciona**: 328 arquivos, 325 PDFs no disco, 0 sem leitor | — |
| 2 | Classificação | `extracao.py` + `conceitos/fontes.json` (classe), `inventario` (planta, detalhe, documento) | **funciona**: projeto 165, memorial 99, edital 45, laudo 11, lista 8; extração completa 252, parcial 73 | a classe não diz **o que extrair** de cada arquivo para a EAP |
| 3 | Abrir cada arquivo e extrair para as gavetas | `extrair_gavetas.py` → `saida/foz/base/*.parquet` | **parcial**: só **13 documentos** chegam às gavetas (94 evidências, 180 fatos, 82 objetos: 66 furos, 15 trechos de rede, 1 conjunto de cavas) | o resto do escopo é extraído **por fora das gavetas**: os 464 elementos construtivos (estacas, blocos, pilares) em `construtivos`, as 86 linhas do contrato em `contrato_211`, os 1 002 itens de material em `escopo` e as 2 517 evidências de texto em `evidencias.jsonl` |
| 4 | Localização e georreferência | `georef_prancha`, `pdf_cad`, geometria das gavetas | **parcial**: 38 geometrias nas gavetas; 35 pranchas no mapa de 57 plantas | elementos e linhas do contrato não levam a geometria para as gavetas |
| 5 | Modelos de EAP (linear, localizada) | `conceitos/eap_padrao.json`: obra localizada (45 folhas) e obra linear (32), com etapas pré-definidas | **existe** | é "premissa" a conferir com o MOS |
| 6 | Percorrer a EAP preenchendo com as gavetas | `eap_padrao.montar` | **não é assim hoje**: preenche a partir da EAP codificada (feita dos `construtivos`), dos fatos de texto e do contrato; **as gavetas não entram** (elas alimentam outra árvore, a `eap_gavetas`) | o preenchimento tem de ler **só** das gavetas |
| 7 | Serviços complementares | `dimensoes.py` + `associados.py` + `conceitos/servicos_associados.jsonl` | **existe**, com as regras que o Caio citou: vala (corte e demolição de pavimento, escavação, escoramento por tipo, esgotamento, berço, envoltória, assentamento, reaterro, bota-fora, recomposição por classe de pavimento: pista, calçada, gramado…); laje (escoramento, impermeabilização); cava de fundação (escavação, reaterro); bloco, pilar, viga, parede, baldrame, estaca | calcula a partir dos `construtivos`, não das gavetas; o `contrato_211` refaz a vala por outro caminho |
| 8 | Termina quando a EAP está completa | `eap_padrao` mede (27 % preenchidas; 6 obrigatórias da localizada e 7 da linear a preencher); `conceitos/documentos_esperados.json` e a escada código → IA → humano em `extracao.py` | **não há laço nem critério de fim**: o build roda uma vez e mostra o que faltou | falta o laço "folha a preencher → documento esperado → novo passe de extração → preencher de novo" e o portão "EAP completa" |

**Conclusão:** o fluxo está certo e as peças existem (passos 1, 2, 5 e 7 prontos). O que falta é a ligação:
- tudo o que é extraído entra nas gavetas (passo 3);
- a EAP é preenchida **só** das gavetas (passo 6);
- os serviços complementares leem das gavetas e gravam nelas (passo 7);
- o processo roda em laço até a EAP fechar (passo 8).

As fases da §3 foram reorganizadas nesses passos.

## 1. Diagnóstico: o que temos (0.68.0)

### 1.1 Tamanho

| Peça | Medida |
|---|---|
| Código Python (`camadas/`) | 43 módulos, 24 433 linhas |
| Template do HTML | 3 753 linhas, 7 abas, 38 funções `html*`, 34 chaves de dado lidas |
| `dados.json` de Foz | 39 blocos, 24 MB |
| Testes | 57 arquivos, 1 374 testes |
| Planos | 41 em `docs/plano/` (12 só em 04/11), mais `PLANO.md` e `PLANO_FOZ.md`, que não estão marcados como superados |
| Versões | 68 no CHANGELOG, de 4 sessões em paralelo; 4 renumerações por colisão na `main` |
| `rumo.yaml` | 9 objetivos concluídos e trocados, 5 deles só em 04/11 |

### 1.2 O peso do HTML não está no escopo

Dos 24 MB do `dados.json`:
- **cerca de 21,7 MB são base visual:**
  - pranchas vetoriais: 12,4 MB;
  - fotos: 3,4 MB;
  - 3D: 1,8 MB;
  - vetores: 1,6 MB;
  - ortofoto: 1,2 MB;
  - construtivos: 1,2 MB;
- **o escopo e a EAP somam cerca de 2,2 MB.**

O template nem lê 6 blocos, entre eles `evidencias` (663 kB), o maior bloco de escopo.

### 1.3 Sete EAPs, nenhuma é "a" EAP

| # | Estrutura | Módulo | Código |
|---|---|---|---|
| 1 | EAP codificada (`eap`) | `eap.py` | `U.SIS.DISC.PAC.ITEM` |
| 2 | Painel da codificada (`eap_painel`) | `eap_painel.py` | o mesmo |
| 3 | EAP das gavetas (`eap_gavetas`) | `eap_html.py` / `gavetas.py` | `CV.01.C01`, `OL.01` (provisórios) |
| 4 | Conciliação 1 × 3 | `gavetas.conciliar_eap` | em Foz: **0 confere**, 2 difere, 6 só na codificada, 29 fora das gavetas |
| 5 | EAP padrão (`eap_padrao`) | `eap_padrao.py` | `OP.xx.yy` / `OL.xx.yy` |
| 6 | Contrato 211 | `contrato_211.py` | aba:linha → folha da EAP padrão |
| 7 | Vista da aba (`eap_vista`) | `eap_vista.py` | reformata 5 + 6 |

**`OL` tem dois sentidos:**
- no `de_para_eap.json`, OL.01 é escavação de vala;
- no `eap_padrao.json`, OL.01 é serviço preliminar.

**"Etapa" tem três sentidos:** 1ª/2ª etapa do contrato, etapa de execução OP.00–12 e etapa da memória espacial.

Nenhum documento diz qual árvore o usuário navega.

### 1.4 As gavetas existem, mas não são a fonte da verdade

- **A base existe:** Parquet em `saida/foz/base/`, com 7 tabelas, 82 objetos e 120 serviços.
- **Ninguém lê dela.** Só a própria extração a relê, para o cálculo incremental. `contrato_211`, `valas`, `escavacao`, `eap`, `eap_padrao` e `evidencias` calculam por conta própria.
- **Caminhos paralelos da mesma grandeza:**
  - comprimento de vala/tubo: 8 caminhos;
  - escavação de cava: o mesmo cálculo roda 2 vezes e entra 2 vezes na EAP, mais uma terceira estimativa por seções médias;
  - quantidade por item da EAP: 5 caminhos.
- **O caminho até a evidência some no meio:**
  - `eap_padrao` e `eap_vista` só têm texto;
  - `evidencias` (os hashes) está fora do HTML;
  - nenhuma estrutura chega à página da prancha nem à coordenada.

### 1.5 Caches sem garantia

| Cache | Situação |
|---|---|
| `sfm/sfm.json`, `ortofoto.jpg`, `ajuste_absoluto.json` | valem só por existir |
| `pranchas/_ref_*.png` | valem só por existir |
| `escavacao_cache`, `conferencia_cavas_cache` | sem versão de leitura |

Esse defeito já apareceu três vezes (L052, L064 e a f010).

### 1.6 Processo

- **Frentes em paralelo na mesma `main`:** WBS/EAP padrão, memória espacial, orçamento 211, georreferência, aba EAP e geotecnia. Cada uma tem o seu plano e o seu rumo.
- **O plano aprovado não foi seguido:** o plano de 04/11 dizia "A4 → A5 → B4". Depois da A5 vieram orçamento 211, georreferência e aba EAP, e a B4 não aconteceu.
- **Documentos contraditórios:**
  - escavação de 7 900, 7 905 ou 7 922 m³, conforme o documento;
  - "linha mestra" declarada em 3 documentos para árvores diferentes;
  - o gerente é Opus no CLAUDE.md e Fable na ARQUITETURA;
  - persistência em JSONL na §6 da MEMORIA e em Parquet na §8.
- **Desvio do foco:** o próprio `composicoes_sanepar.json` traz produtividade, dias úteis e DMT, com grandeza "prazo", contra o princípio "sem prazo". Isso foi aprovado na rodada do orçamento.

**Conclusão:** o protótipo provou as peças (leitura de prancha, georreferência, vala pelo MOS, cavas pela topografia, contrato sem preço, evidência conferida). Faltou o **eixo**: uma base única, uma EAP única e uma navegação que só leia da base.

## 2. Arquitetura-alvo: uma linha só

```
documentos ──► EXTRAÇÃO ──► BASE (gavetas) ──► CÁLCULO ──► BASE (serviços) ──► EAP ÚNICA ──► PACOTE ──► HTML
 (PDF, xlsx,    leitores      documentos,        regras       quantidades          árvore        só o      EAP │ detalhe │ mapa/prancha
  laudo, drone) por tipo      evidências,         determinís-  com os fatos         + roll-up     que a
                              objetos,            ticas        citados                            navegação
                              geometrias, fatos                                                   usa
```

**Regras da linha** (cada uma vira teste):
1. **A base é a fonte da verdade.** Extrator só escreve na base; regra de cálculo só lê da base e escreve serviço na
   base; o HTML só lê o pacote exportado da base. Nenhum módulo calcula "por fora".
2. **Uma grandeza, um caminho.** Comprimento de vala, escavação e quantidade por item: uma função cada. As outras
   viram chamada dela ou somem.
3. **Uma EAP.** Um código por item, uma árvore. As outras 6 viram vistas filtradas dela, ou saem.
4. **Nada sem evidência.** Toda quantidade cita fatos. Todo fato cita evidência com localizador completo:
   documento (sha256), página, retângulo na página e, quando houver, coordenada UTM. Quantidade sem evidência não
   entra na EAP: vira pendência.
5. **Só escopo.** Sem preço, sem prazo, sem produtividade.
6. **Determinístico e reproduzível.** Mesma entrada dá os mesmos bytes na base e no pacote. Todo cache leva a
   assinatura do que o decide.

### 2.1 A base (gavetas v2)

| Tabela | Chave | O que guarda | Novo em relação à v1 |
|---|---|---|---|
| `documentos` | `documento_id` (sha256) | arquivo, tipo, revisão, nº de páginas, data | **nova**: o registro dos insumos |
| `paginas` | `documento_id` + `pagina` | escala, afim pt→UTM (se georreferenciada), recorte PNG | **nova**: é o que a navegação abre |
| `evidencias` | `evidencia_id` | documento, página, retângulo (pt), trecho de texto ou célula, método (leitor, versão), executor | localizador obrigatório |
| `objetos` | `objeto_id` | classe (cava, trecho de rede, estaca, bloco, furo…), unidade, sistema | — |
| `geometria` | `objeto_id` | geometria UTM, CRS, datum | — |
| `fatos` | `fato_id` | objeto, atributo, valor, unidade, evidência | — |
| `servicos` | `servico_id` | código da EAP, quantidade, unidade, regra e versão, fatos citados | código **único** da EAP |
| `pendencias` | `pendencia_id` | o que falta, onde, por quê | ganha chave |

Formato: Parquet (já escolhido e medido), com DuckDB para consulta.

### 2.2 A navegação (o HTML novo)

Três painéis fixos, sem abas de diagnóstico:

```
┌──────────────────┬──────────────────────────────┬───────────────────────────┐
│ EAP (árvore)     │ DETALHE do item              │ MAPA  ⇄  PRANCHA          │
│ busca · filtros  │ quantidade = Σ serviços      │ ortofoto + geometria dos  │
│ etapa ▸ item     │  ▸ serviço: regra, fatos     │ objetos do item           │
│   selo situação  │    ▸ fato: valor, unidade    │ ou                        │
│   quantidade     │      ▸ evidência: documento, │ página da prancha com o   │
│                  │        página, trecho  [ver] │ retângulo da evidência    │
└──────────────────┴──────────────────────────────┴───────────────────────────┘
```

Clicar num item destaca os objetos dele no mapa. Clicar numa evidência abre a página da prancha com o retângulo marcado.
A ida e a volta funcionam nos dois sentidos: clicar num objeto do mapa mostra a que itens da EAP ele pertence.

Ficam **fora** do HTML principal: 3D, fotos oblíquas, conferência das cavas, conciliação, gavetas em bruto,
inventário de arquivos e sondagens em 3D. O que for diagnóstico vai para um **relatório de conferência** à parte,
gerado do mesmo pacote. O peso cai de 24 MB para o que a navegação usa: a ortofoto recortada, a geometria dos objetos
e os recortes das páginas citadas.

## 3. O processo: fases com portão de entrada e de saída

Uma frente ativa por vez, um `rumo.yaml` por fase. Cada fase só começa quando a anterior passa no portão de saída. A
`main` continua recebendo só por PR, com o `vcm balanco`.

As fases seguem os passos do fluxo do Caio (§0). O processo **termina na F6, com a EAP completa**. A navegação (F7)
só apresenta o que a F6 fechou.

| Fase | Passo do fluxo | Entrega | Portão de saída (verificável) |
|---|---|---|---|
| **F0 · Congelar e consolidar** | — | decisões da §5 registradas; documentos superados em `docs/legado/`; `ARQUITETURA.md` como fonte única; esquema das gavetas v2 (§2.1); golden das quantidades atuais de Foz (escavação, valas, contrato, elementos) | o Caio aprova o esquema e a EAP única; golden gravado |
| **F1 · Inventário e classificação** | 1 e 2 | o inventário que já existe ganha, por arquivo, **o que extrair dele**: classe → leitor → gavetas de destino, pelo `documentos_esperados.json` e pelo `fontes.json` | todo arquivo tem destino ou motivo de não ter; 0 "sem leitor" |
| **F2 · Extração para as gavetas** | 3 e 4 | todos os leitores escrevem nas gavetas, com `documentos`, `paginas` e `evidencias` completos e geometria quando houver: pranchas (redes, cavas, estacas, blocos, pilares, lajes), planilha do contrato (linhas sem preço), relação de materiais, laudo, topografia, memoriais e editais (texto com citação conferida) | nada do escopo fica fora das gavetas (o `construtivos`, o `contrato_211`, o `escopo` e o `evidencias` passam a ler da base); 0 fato sem evidência com página; mesma entrada dá os mesmos bytes |
| **F3 · Preencher a EAP pelas gavetas** | 5 e 6 | laço sobre o modelo da EAP (linear e localizada): cada folha consulta as gavetas pelo seu código e soma os fatos medidos; EAP única (§5.1) | cada folha preenchida cita os fatos; paridade com o golden da F0 |
| **F4 · Serviços complementares** | 7 | as regras de `servicos_associados.jsonl` leem as dimensões das gavetas e gravam os serviços nas gavetas (vala: demolição, escavação, escoramento, rebaixamento, reaterro, recomposição por pavimento; localizada: escavação da fundação, impermeabilização, escoramento de laje…); um só caminho por grandeza (o `contrato_211` deixa de refazer a vala) | cada serviço cita as dimensões e a premissa; paridade com o golden; 0 caminho paralelo (teste) |
| **F5 · Laço até a EAP completa** | 8 | para cada folha "a preencher": qual documento deveria trazer o dado (`documentos_esperados.json`) → novo passe da escada (código → IA com citação conferida → humano) → F2–F4 de novo; o que não existe no projeto vira pendência com motivo | **portão "EAP completa"**: toda folha obrigatória preenchida, calculada ou "não se aplica / ausente do projeto" com motivo; o índice de completude fica registrado por obra |
| **F6 · Aceite da EAP** | fim do processo | o Caio confere 10 quantidades ao acaso, do número à prancha | aceite registrado: **fim do processo** para a obra |
| **F7 · Navegação (HTML novo)** | apresentação | pacote exportado das gavetas e template novo, do zero, nos três painéis da §2.2: EAP → detalhe → mapa/prancha | do item à evidência e à prancha em ≤ 3 cliques, nos dois sentidos com o mapa; o HTML antigo e os módulos sem uso saem |

**Ordem:** F0 → F1 → F2 → F3 → F4 → F5 → F6 → F7.

A F2 anda leitor a leitor. Primeiro valas, cavas e furos, que já estão nas gavetas. Depois as estruturas (estacas,
blocos), o contrato, os materiais e o texto.

Cada fase segue o ciclo de sempre: rumo → executores em worktree → build real → balanço → revisão do gerente (com
captura, se houver tela) → PR → merge.

## 4. O que se aproveita

Quase todo o cálculo e a leitura **ficam**: `pdf_cad`, `georef_prancha`, `prancha`, `lineares`/`valas` (MOS),
`escavacao`/`topografia`, `geotecnia`, `contrato_211` (leitor sem preço), `evidencias` (a conferência da IA), `sfm`
(ortofoto). O que muda é **onde gravam e de onde leem**.

**Saem**, ou viram vista, depois da F3:
- `eap_painel`, `eap_html`, a conciliação e `eap_vista`;
- as abas Obra, Camadas, Etapas & escopo e EAP do HTML atual, substituídas pela navegação da F5.

## 5. Decisões do Caio (04/11/2026: "pode seguir com as recomendações e começar a F0")

Decidido:
1. **EAP única**: o esqueleto da EAP padrão por etapa de execução (OP/OL), com os itens técnicos
   (`UNIDADE.SISTEMA.ITEM`) como folhas. É um código só, e o `OL` dos códigos provisórios das gavetas sai na F3.
2. **Uma frente só** até a F6: esta. As outras sessões precisam ser avisadas pelo Caio; a sessão não consegue
   pará-las.
3. **HTML principal só com a navegação da §2.2**: 3D, fotos oblíquas, conferências e inventário vão para o relatório
   de conferência.
4. **Prazo fora da quantificação**:
   - o escoramento blindado em un/mês fica "a preencher (depende de prazo)";
   - a produtividade, os dias úteis e os jogos de escoramento saem;
   - a ALO fica só como "declarada";
   - a DMT fica, porque m³×km é quantidade de transporte, não prazo.

### Texto da proposta (para histórico)

1. **Qual é a EAP única?**
   - Recomendo o **esqueleto da EAP padrão por etapa de execução** (OP/OL), que é como a planilha da Sanepar e o
     engenheiro leem.
   - Abaixo dele, os itens com o código técnico `UNIDADE.SISTEMA.ITEM` da codificada, como folhas.
   - Um código só; o prefixo `OL` deixa de ter dois sentidos.
2. **Uma frente só até a F3?** As outras sessões (frente WBS, memória espacial, geotecnia) param ou passam a seguir
   este plano. Sem isso, as colisões na `main` continuam.
3. **O que sai do HTML principal?** Proposta da §2.2: 3D, fotos oblíquas, conferências e inventário vão para o
   relatório de conferência.
4. **Prazo no escopo:** escoramento em un/mês, ALO em meses, produtividade e DMT contrariam "sem prazo". Saem da
   quantificação e ficam como linhas "declarada" / "a preencher (depende de prazo)"? Ou ficam como premissa?
