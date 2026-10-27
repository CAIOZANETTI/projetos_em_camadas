# Plano de implementação — ETA Vila C / SAA Foz do Iguaçu (Sanepar LE 211/2026)

Entregável final: **HTML totalmente interativo** (`saida/foz/visualizador.html`, offline), com:
- ortofoto verdadeira e modelo 3D do drone;
- todas as pranchas possíveis em **vetor com os layers CAD**, georreferenciadas;
- etapas e escopo de materiais;
- sondagens e fundações.

Pipeline: `python -m camadas.obra exemplos/foz/obra.json`.

## 1. O que veio do Drive

| Pasta | Conteúdo | Uso |
|---|---|---|
| `fotos_drone` | 13 fotos do DJI Mini 2 (21/09/2026, 80–91 m) | 7 nadirais (0249–0255) + 6 oblíquas a ~42° (0256–0261) → SfM, ortofoto e 3D |
| `01. RECEBIDOS/LC2112026EDITAL_ELEMENTOS` | 328 arquivos (325 PDFs, nenhum DWG): Unidade 1 (ETA Vila C), Unidade 2 (adutoras AAT06/AAT02/Vila C), Anexo A (TR), Resolução | pranchas vetoriais, sondagens, fundação, memoriais |
| `05. ORÇAMENTO` | `211 - SAA Foz do Iguaçú.xlsx` + cotações | escopo por etapa |
| `04. COTAÇÕES` | ~45 propostas de fornecedores | (fase 2) ligar material ↔ cotação |

Disciplinas Sanepar: PBHI (hidráulica), PBGE (geotecnia), PBES (estrutura), PBME (mecânica),
PBEA (elétrica/automação), PARQ (arquitetura/urbanização).

Os PDFs são **vetoriais com layers CAD (OCG)**. A prancha 004 (layout) tem 56 layers
(`_PROJETADOS`, `_EXISTENTES A REESTRUTURAR`, `_UNIDADES FUTURAS`, `CISM_11_LINHA_TUBULAÇÃO`…)
e o texto convertido em curvas. As de geotecnia e elétrica têm texto real, pesquisável.

## 2. Achados de engenharia

- **Etapas**: a legenda do layout 004 define:
  - 1ª etapa em azul;
  - 2ª etapa em roxo;
  - **unidades futuras = 3ª etapa** em hachura vermelha;
  - existente a restaurar na 1ª ou 2ª etapa;
  - existente a manter;
  - "parte civil do módulo de microareia na 1ª etapa e equipamentos na 2ª".

  O `Escopo_1etapa_PBES` confirma que a divisão segue o desenho 004 e que os dois módulos de
  600 L/s têm estrutura civil na 1ª etapa e equipamento só em um. **O TR não cita a 3ª etapa**:
  pergunta para a Sanepar.
- **Orçamento**: a aba oculta `Relação de Materiais` traz a quantidade da 1ª e da 2ª etapa por
  tabela (01…79+), e cada tabela está ligada a um desenho.
  - Linhas: 796 só na 1ª etapa, 48 só na 2ª (não orçadas) e 37 nas duas.
  - Sem preço: 465 de 923 itens.
  - Sem etapa: 169 itens (ACTIFLO, válvulas, comportas, civil).
  - Total estimado: U1 R$ 41,7 mi e U2 R$ 19,2 mi.
- **Sondagens**: o relatório Geoazimute (2022) tem 16 SPT com **E/N em SIRGAS 2000 / UTM 21S** e
  cota de boca de 238–240 m.
  - NA entre 7,5 e 9 m.
  - Argila siltosa vermelha mole a rija até 5–9 m, depois silte argiloso rijo a muito rijo.
  - Impenetrável nas cotas 222,6–226,2 m.
  - O relatório Solitec (2023) tem 8 SPT sem coordenadas (só croqui).
- **Fundação**: 256 estacas hélice contínua (Ø40/Ø50, L de 6 a 16 m), distribuídas assim:

  | Estrutura | Estacas |
  |---|---|
  | ACTIFLO 360 | 39 |
  | ACTIFLO 600 | 91 |
  | Filtros novos | 96 |
  | ETL | 12 |
  | Depósito | 6 |
  | Guarita | 4 |
  | Torre do elevador | 4 |

  Há ainda 69 bases rasas e contenção com 193 estacas e 15 tirantes. Faltam a cota de
  arrasamento e a carga (pranchas PBES "locação e cargas" não vieram).

## 3. Arquitetura implementada

```
fotos ─► sfm.py (pycolmap CPU) ─► poses + classificação nadir/oblíqua (pela pose real)
                                 ├► nuvem densa (estéreo SGBM validado pelos pontos do SfM)
                                 └► MDS ─► ortofoto verdadeira (+ MDS 16 bits)
sondagens topográficas ─► controle_absoluto ─► corrige o viés do GPS do drone (1,50 m E)
PDF vetorial ─► pdf_cad.py (traços por layer/cor, /Rotate tratado, textos) ─► georef_prancha.py
              (pontos de controle + ICP | irmã CAD×CAD | afim absoluta) ─► pacote vetorial
orçamento xlsx ─► orcamento_sanepar.py ─► escopo por etapa ─┐
                                                            ├► obra.py ─► dados ─► visualizador.html
sondagens/fundação (JSON) ──────────────────────────────────┘
```

Módulos novos e reutilizáveis:
- `sfm.py`
- `pdf_cad.py`
- `georef_prancha.py`
- `obra.py`
- `orcamento_sanepar.py`

Skills: `obra-em-camadas` (orquestra), `drive-ingestao`, `modelo-3d-drone`,
`georef-pranchas`, `escopo-etapas`. Contrato do HTML: `docs/VISUALIZADOR_V2.md`.

## 4. Resultados nesta rodada

| Item | Resultado |
|---|---|
| SfM | 13/13 fotos, reprojeção de 0,68 px, oblíquas a 41–42° e nadirais a 3–4° da vertical |
| Nuvem densa | ~780 mil pontos após a filtragem (pares estéreo validados com desvio de 3–14 cm contra o SfM) |
| Ortofoto | verdadeira, 4 cm/px, 169 × 197 m; prédio administrativo e filtros com paredes retas (correção do MDS no telhado) |
| Posição absoluta | GPS do drone com RMSE de 1,2 m; viés medido contra as sondagens de **+1,50 m E / −0,12 m N** (desvio de 0,18 m), já corrigido |
| Prancha 004 (etapas) | 3 pontos de controle + ICP; resíduo mediano de 30 cm; manchas por etapa com área |
| Pranchas PBGE | GEOPLANTA1, fundação 1–3 e escavação 1–3 com afim absoluta (sondagens) |
| Demais pranchas | automático como "irmã" da 004, com critério rígido; as reprovadas ficam **pendentes** (visíveis na aba Pranchas, fora do mapa) |
| Mosaico 2D | bug corrigido: com rumo de ~90° o filtro de sobreposição descartava todos os pares |

## 5. Divisão de trabalho usada (e recomendada)

| Modelo | Tarefa nesta obra |
|---|---|
| Haiku | inventário recursivo do Drive (428 itens); download de 161 PDFs |
| Sonnet | estrutura do orçamento e etapas no xlsx; sondagens, fundação, escavação, TR e escopo da 1ª etapa → JSON; front-end do visualizador v2 a partir da spec |
| Opus | arquitetura; SfM, ortofoto e controle absoluto; georreferenciamento e validação visual; integração, testes e PR |

## 6. Próximos passos

1. **Pranchas pendentes**: dar pontos de controle (2–3 por folha) às que não passaram. Ideia:
   um modo "clicar pontos" no visualizador que exporta o JSON para o obra.json.
2. **PDFs acima de 5,5 MB** (22 arquivos, incluindo as formas dos módulos ACTIFLO e as pranchas
   PBES de locação e cargas) não passam pelo conector do Drive. Precisam de download manual em
   `dados/foz/projeto/`.
3. **Ligar tabela ↔ geometria**: cada tabela de material (01…79) aponta para um desenho. Falta
   localizar no desenho o trecho da tabela (bolhas de chamada) para clicar no item e acender a
   tubulação.
4. **Quantitativos vetoriais**: medir na prancha o comprimento por layer/DN e comparar com o
   orçamento (pandas). Os textos dos layers dão o DN.
5. **Unidade 2 (adutoras)**: as pranchas têm `E:/N:` impressos, o que permite georreferenciamento
   automático exato. Fora da área do voo; usar o satélite como base.
6. **Estacas e sondagens no 3D**: cilindros com o comprimento da estaca e o perfil SPT em
   profundidade.
7. **Pontos de controle em campo** (GNSS RTK, 4–6 alvos) para as-built com precisão de centímetros.
8. Fotos das cotações (04. COTAÇÕES) ligadas aos itens do escopo.

## 7. Perguntas para você

- A Sanepar confirma a 3ª etapa (unidades futuras), ou ela fica fora do contrato?
- As pranchas PBES de "locação e cargas" existem no edital? Sem elas não há cota de arrasamento.
- Pode subir os 22 PDFs grandes numa pasta separada, ou compactados em partes de até 5 MB?
