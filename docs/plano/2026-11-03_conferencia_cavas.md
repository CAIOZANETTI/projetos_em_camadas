# Conferência das cavas de Foz por testemunhas independentes

Pedido do Caio (03/11/2026): conferir as cavas da memória espacial. Ele mesmo lembrou que neste repositório a planilha
só entra como **escopo** (quantidades); preço é assunto de outro repositório. Método: o Opus gerencia, o Sonnet
implementa em worktree com testes e o Haiku faz o braçal no Drive; depois vêm `vcm balanco`, o aceite do Fable e o PR.

## Por que não "contra a planilha"

A aba civil do contrato da Unidade 1 **não tem item de cava**. Os itens de terra são:
- vala, por metro de tubo ("ESCAVAÇÃO, ESCORAMENTO, ASSENTAMENTO, REATERRO… FD DN 1000");
- carga, transporte e bota-fora em m³.

A coluna de quantidade está em branco em todos, exceto PVC DN 25 (622 m). Conferi na planilha crua: é campo de entrada
vazio, não fórmula sem valor calculado. As 5 pranchas de escavação (plantas 01 a 03, cortes 01 e 02) também não têm
quadro de volumes; o texto e o OCR foram varridos atrás de "volume", "m³" e "aterro". Não existe volume impresso para
comparar.

O Caio escolheu duas testemunhas independentes do cálculo pelo MDS:
1. **As seções das pranchas de corte**: área de corte e cota de fundo por seção.
2. **As cotas da sequência executiva** escritas na planta 02.

## Etapas

| # | Etapa | Quem | Estado |
|---|---|---|---|
| E1 | Reingestão do Drive (o contêiner novo não tinha `dados/`) | Haiku | feito: 36 de 37 PDFs citados + 13 fotos; depois a planilha, as 5 pranchas de escavação e o laudo (3 chamadas a mais) |
| E2 | Leitor das seções de corte (`camadas/secoes_corte.py`) | Sonnet | feito: 18 seções; calibração pela grade com resíduo de 2 mm; 1:100 nos dois eixos |
| E3 | Seções no modelo e conferência (`camadas/conferencia_cavas.py`) | Sonnet | feito: linhas de seção da planta, perfil do modelo, seções médias, sequência executiva, etapa do build e tabela na aba EAP |
| E4 | Build real, relatório, balanço, aceite e PR | Opus; Fable | este documento |

## Como cada testemunha é medida

**Projeto (E2).** Cada seção é um quadro de "profile view" do Civil 3D:
- o terreno vem do layer `TERRENO ORIGINAL`;
- o contorno da escavação vem do layer `ESCAVAÇÃO`: só a cor dominante na prancha, com traços abertos de até 8
  pontos, para descartar texto e chamadas;
- a calibração pt → m vem das marcas de 1 m da moldura, e a cota absoluta, do OCR dos rótulos de 5 m;
- a área é a integral exata de max(0, terreno − fundo).

**Modelo (E3).**
- **Linha de seção:** o tracejado verde do layer `CORTES` nas plantas 006 a 008, com a letra lida por OCR.
  Corrigindo a especificação, o layer `INDICAÇÃO  SEÇÃO` traz os trechos de contenção, não as seções.
- **Perfil:** amostrado na grade de corte de `escavacao.calcular` (MDS − fundo interpolado das marcas, talude de
  1,5:1).

**Tolerâncias** (constantes nomeadas em `conferencia_cavas.py`):

| Grandeza | Tolerância |
|---|---|
| Fundo | ±0,30 m |
| Terreno | ±0,30 m |
| Área | o maior entre 15 % e 0,30 m × largura |
| Seções médias | ±20 % |

## Resultado (build real de 03/11, 7 cavas, 8 612 m³ de escavação)

**Placar por seção: 1 confere, 5 difere, 12 não conferível.**

| Seção | Área projeto × modelo (m²) | Fundo projeto × modelo (m) | Talude do projeto (H:V) | Situação |
|---|---|---|---|---|
| RR | 57,9 × 63,0 (+9 %) | 235,00 × 235,06 | 1,0 | confere |
| HH | 89,3 × 78,5 (−12 %) | 235,35 × 235,05 | 1,0 | difere: fundo −0,30 m, no limite |
| AA | 33,5 × 23,9 (−29 %) | 237,75 × 237,75 | 3,7 | difere: área; terreno do MDS −0,42 m |
| FF | 61,1 × 44,4 (−27 %) | 235,97 × 236,37 | 2,4 | difere: área e fundo +0,40 m |
| OO | 70,1 × 48,4 (−31 %) | 234,95 × 234,95 | 1,75 | difere: área; terreno −0,37 m |
| BB | 11,6 × 0 | 237,25 × — | 1,7 | difere: o modelo não tem cava nessa linha |
| DD, EE | 42,1 × 44,6; 114,0 × 15,0 | 237,45 × 237,45; 235,21 × 235,57 | 1,5; 5,7 | não conferível: a cava do modelo passa da ponta da linha |
| PP, QQ | 17,9 × 9,1; 16,6 × 9,9 | 235,57 × 235,92 / 235,95 | 1,0 a 1,5 | não conferível: área parcial no projeto (borda do quadro) |
| CC | 77,3 × 23,6 | 234,46 × 237,76 | 5,2 | não conferível: linha quebrada na planta |
| NN | 62,6 × 68,6 | 234,50 × 234,50 | 1,75 | não conferível: só 75 % da linha dentro do MDS |
| GG, JJ, KK, LL, MM | — | — | — | não conferível: sem linha de seção legível na planta |
| II | 0,5 × 1,9 | 239,30 × 239,42 | — | não conferível: sem corte no projeto (< 1 m²) |

**Seções médias:** a cava C01, entre FF e HH (d = 11,4 m), dá V_projeto 856 m³ × V_modelo 742 m³ (−13 %) e **confere**.
Das outras 9 combinações, nenhuma tem par paralelo com as duas seções completas.

**Sequência executiva (planta 02):**
- **Escavação 239,20 (Caixa de Saída 01):** liga só a C07, cujo fundo no modelo é 239,42 m; confere.
- **237,50 e 236,80:** aparecem para a Câmara de Contato e para a Caixa de Saída 02 com o mesmo valor. Ligar a uma cava
  seria inventar, então ficam como não conferíveis.
- **Notas "cota final":** sem número, não conferíveis.
- **Reaterro:** o modelo não tem cota de reaterro; não conferível.

## Leitura honesta (corrigida no aceite do Fable)

A primeira versão deste relatório dizia que "o volume está provavelmente subestimado" e que a causa era o talude. O
aceite independente mostrou que os próprios dados não sustentam isso. A leitura correta é esta:

1. **O terreno é a primeira fonte de diferença.** O MDS do drone fica de 0,12 a 0,42 m **abaixo** do TERRENO ORIGINAL
   do projeto nas 6 seções comparáveis, sempre no mesmo sentido. Corrigida por esse desnível (área do modelo −
   diferença de terreno × largura), a área fica assim:

   | Seção | Área do projeto | Área do modelo | Modelo corrigido pelo terreno | Diferença |
   |---|---:|---:|---:|---:|
   | AA | 33,5 | 23,9 | 33,9 | **+1 %** |
   | FF | 61,1 | 44,4 | 47,8 | −22 % |
   | HH | 89,3 | 78,5 | 82,2 | −8 % |
   | RR | 57,9 | 63,0 | 67,6 | **+17 %** |
   | OO | 70,1 | 48,4 | 55,9 | −20 % |

   Em AA, a diferença inteira era o terreno. Sobram OO (−20 %) e, **no sentido contrário**, RR (+17 %). Se o volume
   está sub ou superestimado depende de qual terreno está certo, o MDS ou a topografia do projeto. Os dados desta
   rodada não decidem isso.
2. **O fundo do modelo está certo em 5 de 7 seções.** AA, DD, OO, RR e NN batem com diferença de 0 a 0,06 m. Em HH e FF,
   o fundo vem da **marca de cota vizinha errada**:
   - em HH, o "235,35" da Câmara de Contato é texto de cota sem símbolo de marca, e o modelo usa o 235,05 do poço,
     a 7,3 m. Isso dá cerca de 0,30 m × 580 m², ou ~170 m³ a mais na C01;
   - em FF, o modelo usa as marcas 237,15 e 237,45 do corredor, e o fundo fica 0,40 m acima.
3. **BB não é "difere".** A linha corre sobre a passarela da estrutura existente (hachura de existente na planta). O
   modelo exclui edificação, então ali não há cava a comparar; BB passa a "não conferível".
4. **A ligação da sequência executiva é só por valor.** A cota 239,20 é "compatível por valor" com C07 (fundo 239,42 m),
   mas a nota é a base da viga de coroamento da Caixa de Saída 01, e C07 tem 0,17 m de profundidade e 12 m³. Isso não
   confirma a cava.
5. **O talude fica como está.** O Caio chegou a aprovar o talude por seção do projeto, mas desistiu depois desta
   leitura (E5 cancelada): o talude não é a causa principal. A próxima rodada decide primeiro o terreno (MDS ×
   topografia do projeto) e depois o talude, já com o terreno resolvido.
6. **Reprodutibilidade do SfM.** O mesmo conjunto de fotos, reconstruído do zero em outro contêiner, deu 8 612 m³ contra
   8 585,6 m³ no build de 02/11 (+0,3 %). O controle vertical também mudou: 12 pontos e SP03 descartado, contra 13
   antes. O código é determinístico; a reconstrução por fotos não é bit a bit. Fica registrado como limite do método.

## Revisão do Fable (1º aceite: REVISAR, sem bloqueante)

| # | Achado | Correção |
|---|---|---|
| A1 | As seções JJ, KK e LL têm linha na planta, mas a letra está deitada (90°) e o OCR não a lia; o motivo "sem linha" era falso | OCR da letra em 0, 90, 180 e 270° |
| A2 | Linha incompleta (EE: 15,6 m de 45 m) era registrada como "a cava continua além da linha" | cheque comprimento da linha × largura do quadro |
| A3 | BB sobre edificação existente contava como "difere" | "não conferível: edificação na linha" |
| A4 | A conclusão "subestimado" não se sustentava | relatório corrigido e coluna "área corrigida pelo terreno" |
| A5 | O fundo de HH e FF vem da marca vizinha | registrado (acima) |
| A6 | "Confere" pela sequência executiva exagerava | passa a "compatível por valor" |
| A8 | O ponto final da frase virava vírgula | formatar só os números |

## Achados do contêiner novo (corrigidos com teste)

- **Prancha citada e ausente** (`PLANTIM-R2`, elétrica): é pulada com pendência. Antes derrubava `etapa_pranchas`.
- **Inventário sem `_listagem_drive.csv`**, ou com `_baixados.csv` de outras colunas: é pulado com pendência.
- **Escavação sem controle vertical:** sem `sondagens.json`, as cavas sumiam **sem aviso**. Agora sai "Escavação: NÃO
  CALCULADA", também no HTML.

## O que falta

- **Seções sem linha legível na planta** (GG, JJ, KK, LL, MM): 5 tracejados ficaram sem letra lida. Rotulá-los
  daria mais 5 seções conferidas.
- **CC:** o perfil por segmentos para linha quebrada não foi implementado.
- **Terreno (MDS × topografia do projeto)** e, depois, o talude: próxima rodada (ver a Leitura honesta).
- **Listagem completa do Drive** (para o inventário) e a prancha `PLANTIM-R2`, que não está no Drive.
