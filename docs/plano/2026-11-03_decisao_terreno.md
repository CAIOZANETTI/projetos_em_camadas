# Decisão do terreno das cavas de Foz: MDS do drone × topografia do projeto

Pedido do Caio (03/11/2026): seguir com a decisão do terreno. A conferência das cavas (0.53.0) mostrou que a diferença
de área de corte entre o modelo e as seções do projeto vem principalmente do terreno. Esta rodada junta a evidência;
a decisão é do Caio.

## O ponto de partida

O MDS **não é uma testemunha independente** da topografia. A altitude dele vem de um plano ajustado às cotas de boca de
12 sondagens (`saida/foz/sfm/ajuste_vertical.json`), que são dados do levantamento topográfico de 2022. O MDS herda a
altitude da topografia e acrescenta o erro da reconstrução por fotos.

A testemunha usada foi a topografia do próprio projeto: as curvas de nível da **GEOPLANTA**, layers `Curvas_Mestras` e
`Curvas_Auxiliares`, com equidistância de 0,5 m. O layer `CURVA DE NÍVEL` das plantas de escavação, ao contrário do
nome, traz os contornos das cavas projetadas, não o terreno. O módulo novo `camadas/topografia.py` lê as curvas, monta
o TIN na mesma grade do MDS e faz as comparações. Nenhum volume foi alterado.

**Leitura das curvas:**

| Item | Valor |
|---|---|
| Curvas | 45 |
| Com cota pelo rótulo | 27 (o OCR com alfabeto aprendido lê os 15 rótulos) |
| Inferidas pela vizinhança, com alerta | 4 |
| Sem cota (bordas e o empilhado do lado oeste) | 14 (516 m de traço) |
| Área do casco convexo | 12 958 m² |

## A evidência

**A topografia é coerente com as outras peças do projeto.**

| Comparação | n | Média | RMS |
|---|---:|---:|---:|
| Topografia × TERRENO ORIGINAL das seções de corte | 14 | −0,08 m | **0,16 m** |
| Topografia × cota de boca das sondagens (dentro do casco) | 11 | −0,10 m | **0,25 m** |

O RMS de 0,25 m é da ordem do erro esperado do TIN entre curvas de 0,5 m, metade da equidistância.

**O MDS não acompanha a topografia.**

| Comparação | Média | RMS | Observação |
|---|---:|---:|---|
| MDS × topografia, toda a área válida | +0,54 m | 1,15 m | 21 % da área com erro maior que 1 m |
| MDS × topografia, terreno aberto (grama, pavimento, solo) | +0,33 m | 0,80 m | |
| MDS × seções de corte | +0,30 m | 0,82 m | |

**Diagnóstico do erro do MDS** (mapa em `docs/plano/2026-11-03_mapa_erro_mds.png`):

1. **Cobertura: o maior componente.** O erro cresce com a altura do que cobre o chão:

   | Cobertura | Erro médio |
   |---|---:|
   | Grama | +0,27 m |
   | Pavimento | +0,42 m |
   | Vegetação alta | +0,70 m |
   | Edificação | +1,31 m |

   As duas manchas maiores somam cerca de 2 250 m², com erro médio de +2 a +2,7 m:
   - **prédio central:** a abertura morfológica de 15 m não remove um telhado mais largo que isso;
   - **mancha de vegetação sobre SP07:** o MDS bruto chega a 248 m, contra 238,40 m na boca do furo.

   Os três furos que o ajuste vertical descartou (SP03, SP07 e SP16) são justamente os que ficam embaixo dessas
   coberturas.
2. **Forma: inclinação da reconstrução, não cúpula.** No terreno aberto, um plano tira 70 % da variância (RMS de 0,42
   para 0,23 m). Sobra uma inclinação de cerca de 1 m a cada 100 m no sentido norte-sul: azul (MDS abaixo) no norte,
   onde ficam AA e OO, e vermelho no sul. A quadrática não melhora o ajuste.
3. **Mudança real do terreno de 2022 para 2026: não separável com os dados atuais.** As plantas são de 19/08/2022 e o
   voo é de 21/09/2026. Não há polígono de aterro ou de obra nova para dizer onde o terreno mudou.

## As opções

| Opção | A favor | Contra |
|---|---|---|
| **A. Topografia do projeto** | RMS de 0,16 m contra as seções e 0,25 m contra as sondagens; imune a copa, prédio e inclinação; é a mesma fonte das seções de corte e das cotas de projeto | cobre só o casco (12 958 m²), sem SP12 a SP16; data de 2022; ~0,25 m de interpolação; 14 curvas sem cota |
| **B. MDS atual** | cobre tudo; é de 2026 | 21 % da área com erro maior que 1 m (copa e prédio); inclinação residual; usa as mesmas sondagens (não é independente) |
| **C. MDS só no terreno aberto, corrigido pelo plano da topografia** | no aberto, o erro cai para 0,23 m | máscara a decidir; continua dependente; ajuste feito só nesta área |
| **D. Topografia no casco, MDS fora dele** | usa a melhor fonte onde ela existe | costura entre as duas superfícies, com salto na borda |

## Recomendação do gerente

**D, com o MDS de fora corrigido pela inclinação medida contra a topografia e sem as áreas de edificação e vegetação
alta.**

- **Dentro do casco, a topografia.** Ela é coerente com as seções e com as sondagens. Além disso, a cota de fundo das
  cavas vem do mesmo projeto: medir a escavação entre o terreno do projeto e o fundo do projeto é consistente.
- **Fora do casco, o MDS** com o plano de correção (RMS de 0,23 m no terreno aberto) e com a costura suavizada na
  borda.
- **O que fica explícito no resultado:** o terreno pode ter mudado de 2022 para 2026 e não há como saber com os dados
  atuais. Se houve aterro ou obra nova, o MDS de 2026 é que vale ali, e isso só se resolve com a informação do Caio ou
  com um levantamento novo.

Decisão do Caio: (registrar aqui)
