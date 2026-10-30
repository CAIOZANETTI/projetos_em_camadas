# EAP (WBS) como linha mestra do projeto em camadas

> Pedido do Caio (30/10/2026): "nós, engenheiros, usamos a EAP como linha mestra. A EAP é a linha mestra, os projetos
> são as evidências, e o georreferenciamento é o jeito de ver o projeto no local". O mesmo pedido inclui camadas
> sobrepostas (civil, elétrica, hidráulica) com vista geral e particular, e quantificação determinística: se houver
> IA, um código confere o que ela disser.

## 1. O que o repositório já tinha

| Peça | Onde | Papel na EAP |
|---|---|---|
| Unidade (localizada × linear) → sistema → elemento | `camadas/construtivos.py`, `conceitos/unidades_construtivas.json` | **os dois primeiros níveis da EAP** e os elementos que serão medidos |
| Classe de layer CAD (estaca, bloco, pilar, viga, parede, tubo, equipamento…) com os serviços | `conceitos/elementos.json` | evidência gráfica do item (o traço na prancha) |
| Grupo/subgrupo de disciplina da prancha e do layer | `conceitos/disciplinas.json`, `pdf_cad.disciplina_da_prancha` | prancha → pacote da EAP |
| Obra linear × localizada pelo nome do PDF | `conceitos/tipos_prancha.json` (`linear`) | prancha → unidade |
| Escopo do contrato por etapa, sem preço | `camadas/orcamento_sanepar.py`, `obra.etapa_escopo` | quantidade do contrato a comparar por item (próximo passo) |
| Georreferência das pranchas, ortofoto, 3D | `georef_prancha`, `sfm`, `obra` | onde cada elemento está no terreno |
| Aba **Obra** do HTML (busca, árvore, ficha) | `templates/visualizador.html` | onde a árvore da EAP vai aparecer |

Faltava um **código único** que amarrasse elemento, prancha, quantidade e contrato. Faltava também separar as
disciplinas como a engenharia mede: em `disciplinas.json`, a geotecnia está dentro de "Civil" e os equipamentos em
"Mecânica".

## 2. Princípio

```
                 EAP  (conceitos/eap.json + unidades_construtivas.json)   ← linha mestra, código estável
                  │
   ┌──────────────┼───────────────────────┬──────────────────────────┐
   ▼              ▼                       ▼                          ▼
elemento       prancha                 quantidade                  contrato
(construtivos) (evidência do pacote)   (regra do item, determinística) (escopo por etapa)
   │              │                       │
   └── georreferência (UTM SIRGAS 2000) ──┴──► camadas no HTML: geral (nó alto) × particular (item)
                                               IA propõe ──► eap.verificar refaz a conta ──► aceita/recusa
```

## 3. Codificação

`UNIDADE.SISTEMA.DISCIPLINA.PACOTE.ITEM`. Unidade e sistema vêm de `unidades_construtivas.json`. Disciplina, pacote
e item vêm de `conceitos/eap.json`.

O **código mnemônico é a chave estável**: ele não muda quando entra um sistema novo. O número (`1.3.1.1.1`) é só a
ordem de exibição.

Exemplo: o sistema de microareia (Actiflo 600 L/s) da ETA Vila C, que tem construção civil e equipamentos
hidráulicos.

```
U1                         Unidade 1 — ETA Vila C (obra localizada)
└─ U1.ACT600               Actiflo 600 L/s (sistema de microareia)
   ├─ U1.ACT600.GEO        Geotecnia
   │  ├─ .GEO.FUN          Fundações ─ .EST estacas (un, m) · .BLO blocos (un, m²) · .CON contenções
   │  └─ .GEO.MOV          Movimentação de solo ─ .ESC escavação (m³) · .REA reaterro (m³) · .SUP supressão
   ├─ U1.ACT600.CIV        Civil
   │  ├─ .CIV.EST          Estruturas de concreto ─ .PIS piso/laje · .VIG viga · .PIL pilar (un) · .PAR parede
   │  └─ .CIV.PAV          Pavimentação ─ .REC demolição e recomposição
   ├─ U1.ACT600.HID        Hidráulica
   │  ├─ .HID.EQP          Equipamentos ─ .EQU fornecimento e montagem
   │  └─ .HID.TUB          Tubulações ─ .RED tubulação (m) · .VAL válvulas e conexões
   └─ U1.ACT600.ELE        Elétrica ─ .ELE.FOR instalações · .ELE.ATE aterramento e SPDA
U2                         Unidade 2 — Adutoras (obra linear)
└─ U2.AAT06                Adutora AAT06 ─ .GEO.MOV.VAL vala · .CIV.PAV.REC pavimento · .HID.TUB.RED tubo (m)
```

Cada item declara a que tipo de obra se aplica (`obra`). Por isso não existe `U2.AAT06.GEO.FUN.EST`: estaca não é
item de adutora.

## 4. Como cada item se liga às camadas (`conceitos/eap.json`)

| Campo do item | O que faz |
|---|---|
| `construtivos` | classes de `camadas.construtivos` que viram quantidade no item (uma cava alimenta escavação **e** reaterro) |
| `medicoes` | regra determinística: `contagem`, `soma` de um atributo, `comprimento` ou `area` da geometria em UTM |
| `layers` | classes de `elementos.json` que são evidência gráfica do item (traço na prancha) |
| `pranchas` (raiz) | subgrupo da prancha → pacote (`Geotecnia e fundação` → `GEO.FUN`, `GEO.MOV`) |
| `so_evidencia` (raiz) | classe que prova o sistema mas não é medida (mancha de etapa da folha 04) |

Quando o subgrupo não basta para saber a que sistema uma prancha pertence, declare `"eap": "U1.ACT600"` na prancha
do `obra.json`. Sem essa declaração, a evidência fica `U1.*.GEO.FUN` (qualquer sistema da unidade).

## 5. Quantificação determinística (`camadas/eap.py`)

```python
from camadas import construtivos, eap
c = construtivos.montar(dados, cfg)            # elementos com geometria e atributos
quant = eap.quantificar(c, epsg)               # DataFrame: codigo, grandeza, unidade, quantidade, n_elementos,
                                               #            sem_valor, evidencias (ids), fontes (pranchas/arquivos)
eap.consolidar(quant, "unidade")               # soma por tipo de item: "estacas da U1", "escavação da U1"
eap.lacunas(quant)                             # itens do modelo sem nenhum elemento: o que o projeto não evidencia
eap.sem_item(c)                                # elementos sem item: classe a encaixar no modelo
eap.validar()                                  # o modelo bate com unidades, elementos.json e disciplinas.json
```

Regras que impedem a alucinação:
- **nenhuma quantidade sem elemento**: toda linha carrega os ids dos elementos (`evidencias`) e a fonte de cada um;
- **elemento sem o atributo não vira zero escondido**: ele conta em `sem_valor`. Exemplo: cava sem reaterro calculado
  fica com `sem_valor = 1`;
- **só soma a mesma coisa**: a consolidação é por tipo de item, grandeza e unidade de medida. "un" de bloco não soma
  com "un" de pilar;
- **regra dos 100 %** (PMI): `lacunas` mostra o que falta e `sem_item` mostra o que sobra.

## 6. IA associada: propõe, o código confere (`eap.verificar`)

A IA (ou uma pessoa) entrega linhas `{codigo, grandeza, unidade, quantidade, evidencias: [ids]}`. O código refaz a
conta **só com os elementos citados**:

| Status | Quando | Aceito |
|---|---|---|
| `confere` | soma das evidências = proposto e = total do item | sim |
| `confere, parcial (faltam elementos do item)` | bate com as evidências, mas o item tem mais elementos | sim, sinalizado |
| `quantidade diverge das evidências` | o número não sai dos elementos citados (traz o valor calculado) | não |
| `sem evidência` | nenhum id citado | não |
| `evidência inválida` | id inexistente ou de outro item | não |
| `medição não prevista no item` | grandeza/unidade que o item não mede (ex.: m³ de estaca) | não |
| `código inexistente` | código fora da EAP instanciada | não |

Assim a IA serve para ler, classificar e sugerir. Por exemplo, ela pode ler a relação de materiais de uma folha e
propor o item `HID.EQP.EQU`. Mas nada entra na quantidade sem passar por `verificar`.

## 7. Camadas no HTML: geral × particular (proposta para a próxima rodada)

O build já grava `dados.eap` e o código `eap` em cada elemento da aba Obra (`obra._aba_projeto`). Falta a interface:

1. **Árvore EAP** na aba Obra, no lugar da árvore unidade → sistema → classe. Cada nó mostra o código, o nome e as
   quantidades (`dados.eap.quantidades`).
2. **Clique num nó = filtro por prefixo**:
   - liga só os elementos cujo `eap` começa pelo código;
   - liga as pranchas do pacote (`dados.eap.pranchas`) e, dentro delas, os layers das classes do item (`layers`);
   - as outras disciplinas ficam esmaecidas, não somem. Assim se vê a sobreposição civil × hidráulica × elétrica.
3. **Nó alto** (U1, U1.ACT600) dá a vista geral. **Item** (U1.ACT600.GEO.FUN.EST) dá a vista particular, já
   enquadrada no mapa.
4. **Ficha do nó**: quantidades com as evidências clicáveis, as pranchas-evidência, as lacunas e o contrato (item 8b).

## 8. Próximos passos

| # | Passo | Peças |
|---|---|---|
| a | Aba EAP no HTML (§7) e teste de interface | `templates/visualizador.html`, `scripts/testar_visualizador.py` |
| b | Item do contrato → código EAP (disciplina e família do material → item), para comparar contrato × desenho por item | `orcamento_sanepar.disciplina_*`, `obra.etapa_escopo` |
| c | Medir itens que hoje só têm evidência gráfica (vigas, paredes, pisos): comprimento/área por layer na geometria exata, já calculados em `pdf_cad.quantitativos` | `pdf_cad`, `prancha.ficha_estrutura` |
| d | Equipamentos do Actiflo (misturadores, raspadores, bombas de microareia, hidrociclones) a partir da relação de materiais × balões | `prancha` (relação de materiais), `HID.EQP.EQU` |
| e | Declarar `eap` nas pranchas de Foz (`exemplos/foz/obra.json`) e rodar a obra real | `obra.json` |
| f | Etapa (1ª/2ª) e cronograma por nó da EAP | `cronograma_4d`, `etapas_sanepar.json` |

## 9. Decisões em aberto (Caio)

1. **Mecânica dentro de Hidráulica?** Hoje os equipamentos estão em `HID.EQP`, como no pedido. A Sanepar separa
   PBME/PMEC (mecânica).
2. **Ordem dos níveis**: unidade → sistema → disciplina (cada módulo carrega suas disciplinas) ou unidade →
   disciplina → sistema (cada disciplina lista os módulos)? O código atual usa a primeira ordem. Trocar só muda
   `estrutura` e o código; as regras não mudam.
3. **Código Sanepar**: existe uma EAP/codificação do contrato (UCs do TR, fases de medição) que deva ser o código
   oficial? Se existir, ela entra como atributo `codigo_contrato` em cada nó.
4. **Arquitetura e urbanização** ficaram em Civil. Elas devem ser uma disciplina própria?
