# A4: o fundo de cada cava pela marca de cota da própria estrutura

Rodada A4 do plano `docs/plano/2026-11-04_plano_memoria_espacial.md`. Pedido do Caio (04/11/2026): "pode gravar o
plano e seguir com a A4"; depois, "pode seguir até o merge".

## O problema

Até a 0.56.0, cada célula da cava recebia o fundo da **marca de cota mais próxima** num raio de 3 m. Numa planta com
várias estruturas encostadas, a marca de uma estrutura rasa vizinha ganhava da marca da própria estrutura sempre que
estivesse mais perto. Isso aparecia em dois casos:
- **HH, Câmara de Contato:** o fundo escrito é 235,35, mas sem o símbolo de marca. O modelo usava o 235,05 de um poço
  a 7,3 m e, em parte da câmara, o 238,53 das BOMBAS DOSADORAS DE FLÚOR.
- **A estrutura de 107 m² cortada por LL:** tem duas marcas internas de 235,57, mas 133 m² das células dela recebiam
  238,07, a marca da estrutura vizinha (28 m²).

## O que mudou (`camadas/escavacao.py`)

1. **Ligação marca ↔ base** (`ligar_marcas`, `_ligar_base`). Cada base recebe, nesta ordem:
   - as marcas **dentro** dela; com duas ou mais, o degrau fica só entre elas;
   - a **cota escrita sem símbolo** dentro dela ou a até 1,5 m da borda;
   - só então a marca vizinha a até 3 m, com alerta.

   A origem do fundo de cada base fica registrada.
2. **Cota escrita sem símbolo** (`cotas_escritas`): os rótulos de cota são agrupados pelos glifos e lidos por OCR de
   recorte, com cache por prancha e versão da leitura. Um rótulo que repete, até 0,05 m, a cota de um símbolo a até
   3 m dele é rótulo daquela estrutura e não vale para a base encostada.
3. **Fundo na cava pela base mais próxima da mesma região.** É a mesma regra da superfície do talude. Sem esta
   troca, não há como dar a cada base o fundo da própria marca: a regra antiga era o mecanismo da contaminação.
4. Escritas fora da faixa do terreno (OCR errado) passam a ser contadas e avisadas, e os alertas de marca vizinha vão
   agregados ao HTML.

O hash da referência não mudou e a paridade entre as gavetas e o cálculo continua 0.

## Resultado em Foz

**Origem do fundo, por base (170):**

| Origem | Bases |
|---|---:|
| Marca interna | 23 |
| Cota escrita | 21 |
| Marca vizinha (alerta) | 83 |
| Sem marca | 43 |

Das 16 cotas escritas lidas, o Fable conferiu as 16 no PDF:
- 13 certas;
- 237,257 ×2, que é "237,25" (o 7 é um glifo vizinho);
- 236,14, que é "236,16";
- 250,21 e 290,21, que são "235,21" e foram descartadas pela faixa do terreno.

Com a tolerância de 0,05 m, os dois erros de último dígito passam a ser reconhecidos como rótulo do símbolo vizinho.

**Volume: escavação 7 905 → 8 904 m³ (+12,6 %).** O aumento é a própria correção:

| Onde | Variação | Testemunha |
|---|---:|---|
| Estrutura de 107 m² cortada por LL (C02): fundo 238,07 → 235,57, pela marca interna | +793 m³ | LL: fundo do projeto 235,57, do modelo 235,57; área 102,6 × 104,8 m² |
| Câmara de contato (C01): fundo 235,05/238,53/239,5 → 235,35 | +166 m³ | HH: o corte diz "COTA ESCAVAÇÃO 235,35"; passa a conferir |
| C05: 237,75 no lugar de 238,25/239,20 | +52 m³ | AA: o corte tem 237,75 na largura toda |
| C04: 234,46 → 235,16 | −43 m³ | sem seção conferível |
| C07 (nova, 38 m³): talude sul de uma estrutura da 1ª etapa, que antes ficava sem fundo em silêncio | +38 m³ | planta: curvas 236,16 a 238,50 em volta |

**Nas seções conferíveis**, a soma dos desvios de área cai de 56,7 para 46,7 m², e o placar vai de 2/4/12 para
**3/3/12**.

## O que não foi resolvido

- **FF.** O corte tem o canal a **235,97** sobre a contenção BB, mas essa cota **não existe na planta 007**: não há
  símbolo, rótulo nem texto. Além disso, a marca vizinha mais próxima é "237,50 TOPO V. COROAMENTO": o número está a
  90° e o OCR perdeu o "TOPO". Antes, o modelo acertava a FF a 0,9 m por coincidência, por causa do poço a 2 m.
  FF só confere com a entrada que falta.
- **Envoltória** (fundo = mínimo, por base, de fundo + talude × distância). É o modelo físico certo em geral, mas não
  é a correção da FF. Ela vale nos dois lugares (`superficie_da_cava` e `fundo_na_regiao`), muda o hash da
  referência e vai para uma rodada própria, com uma seção que a prove.
- **83 bases pela marca vizinha.** A maioria são peças da mesma estrutura e recebem a cota certa. O caso ruim é o
  canal junto da FF, que recebe 237,50 "TOPO" como fundo: é uma limitação do `ler_cota`, que não lê "TOPO" a 90°.
- **Critério de aceite da A4** ("fundo bate em todas as seções conferíveis"): **atingido em HH e LL**, não em FF
  (entrada ausente), RR (+0,50 m) nem OO (área).
- A cota escrita viaja nas gavetas pelo sufixo " (escrita)" no texto da marca. Funciona, mas o certo é um campo
  próprio em `marcas_cota` de `conceitos/gavetas.json` (rodada futura).

## Aceite do Fable (1º: REVISAR pontual)

- **Manter** a troca do método do fundo: é a A4, e LL e HH a confirmam.
- O diagnóstico da FF foi corrigido neste relatório (entrada ausente, não envoltória).
- Ajustes pedidos e feitos: tolerância de mesma cota de 0,05 m, escritas descartadas contadas, alertas agregados e
  mensagem das bases sem marca corrigida.
