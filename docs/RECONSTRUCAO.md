# Reconstrução: da extração à navegação pela EAP, só escopo (proposta, 04/11/2026)

Pedido do Caio (04/11/2026):

> O HTML está muito confuso [...] não está operacional. Primeiro uma arquitetura de extração de dados com as
> gavetas e depois a navegação do usuário pela EAP e pelo escopo, para ter evidência de tudo: de onde veio cada
> quantidade e cada detalhe do projeto, a EAP navegável apontando no mapa e nas pranchas. [...] O projeto cresceu
> muito e perdeu o foco. [...] Um processo estruturado, com começo, meio e fim.

Este documento é a **proposta para aprovação**. Nenhum código muda antes do "ok" do Caio às decisões da §5.

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

| Fase | Entrega | Portão de saída (verificável) |
|---|---|---|
| **F0 · Congelar e consolidar** | decisões da §5 registradas; documentos superados em `docs/legado/`; `ARQUITETURA.md` reescrita como fonte única; contrato da base (esquema da §2.1) e da navegação; golden das quantidades atuais de Foz (escavação, valas, contrato) para provar que nada se perde | o Caio aprova o esquema e a EAP única; golden gravado |
| **F1 · Extração → base** | cada leitor existente (planilha, pranchas, laudo, topografia, drone) escreve na base, com `documentos`/`paginas`/`evidencias` completos; caches com assinatura | 0 fato sem evidência com página; mesma entrada dá os mesmos bytes; nº de objetos e fatos de Foz ≥ o de hoje |
| **F2 · Cálculo pela base** | as regras (vala MOS, cavas, contrato, estacas…) leem só da base e gravam serviços com fatos citados; os caminhos paralelos saem | paridade com o golden da F0 (tolerância declarada); um teste prova que nenhum módulo de cálculo lê PDF/xlsx direto |
| **F3 · EAP única** | árvore oficial com código único e soma por nível; contrato 211 e EAP padrão como vistas filtradas dela | cada linha do contrato e cada folha da EAP padrão aponta para um item da EAP única; 0 código órfão |
| **F4 · Pacote de navegação** | exportação da base para o HTML: EAP, detalhe, índice de evidências, geometria por objeto, recortes de página | o pacote tem só o que a navegação usa; tamanho medido; reproduzível |
| **F5 · HTML novo** | template novo, do zero, nos três painéis da §2.2; o atual fica até o aceite | teste de interface: do item à evidência e à prancha em ≤ 3 cliques, nos dois sentidos com o mapa, no celular |
| **F6 · Aceite** | o Caio confere 10 quantidades ao acaso, do número à prancha | aceite registrado; o HTML antigo e os módulos sem uso saem |

**Ordem:** F0 → F1 → F2 → F3 → F4 → F5 → F6. A F1 e a F2 andam leitor a leitor: primeiro valas e cavas, que já
estão na base; depois o contrato, depois estacas e blocos.

Cada fase segue o ciclo de sempre: rumo → executores em worktree → build real → balanço → revisão do gerente (com
captura, se houver tela) → PR → merge.

## 4. O que se aproveita

Quase todo o cálculo e a leitura **ficam**: `pdf_cad`, `georef_prancha`, `prancha`, `lineares`/`valas` (MOS),
`escavacao`/`topografia`, `geotecnia`, `contrato_211` (leitor sem preço), `evidencias` (a conferência da IA), `sfm`
(ortofoto). O que muda é **onde gravam e de onde leem**.

**Saem**, ou viram vista, depois da F3:
- `eap_painel`, `eap_html`, a conciliação e `eap_vista`;
- as abas Obra, Camadas, Etapas & escopo e EAP do HTML atual, substituídas pela navegação da F5.

## 5. Decisões do Caio antes da F0

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
