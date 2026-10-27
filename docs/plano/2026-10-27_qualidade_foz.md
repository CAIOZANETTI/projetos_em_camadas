# Plano — qualidade máxima na obra de Foz (rodada 3)

Pedido do Caio (27/10/2026): "fazer da melhor forma possível para garantir a maior qualidade".
Pedidos que entraram no meio da rodada:
- recorte classificado no HTML (ex.: desmatamento no trecho da adutora);
- camadas agrupadas por disciplina (Civil › fundação, estrutura, arquitetura, urbanização,
  drenagem, pavimentação; Hidráulica; Elétrica);
- 4D (camada de prazo com "play");
- usar as referências de SIG (QGIS, pygis.io);
- incluir as referências da Sanepar (`ialocal.gis.fontes/sanepar`);
- seguir a skill `estilo-caio-python`.

Estados possíveis: `pendente` → `feito` → `verificado`.

| # | Item | Verificação | Estado |
|---|---|---|---|
| 1 | Georreferenciar as 12 pranchas pendentes (CAD × CAD por SIFT + RANSAC, critério rígido) | 20/20 aceitas pelo critério; sobreposição visual em cada uma (vias, tanques, prédios) | verificado |
| 2 | Supressão vegetal estimada: ExG + altura do MDS na faixa de obra, por etapa | áreas por etapa no log; sobreposição visual no trecho leste da adutora | verificado |
| 3 | Taxonomia de disciplinas (prancha e layer → grupo › subgrupo) em `conceitos/disciplinas.json` | todo layer das 20 pranchas recebe grupo; teste cobre 100% dos layers | verificado — 1.082 layers, 0 sem grupo; testes de prancha/layer |
| 4 | Cronograma 4D a partir dos marcos MI01–MI06 do TR (durações = hipótese declarada), com as atividades por dia **calculadas no Python** | cada atividade com seletor que casa com ≥ 1 elemento; teste | verificado — 13/15 com elementos (A03, A13 e ALO não têm geometria); curva S 58 % no dia 360; teste sintético ok; 4D verificado na interface (dias 100/400/600) |
| 5 | Exportações de SIG: GeoTIFF (ortofoto, MDS), GeoPackage por camada, `.points` do QGIS | arquivos abrem com rasterio e pyogrio; CRS EPSG:31981; GPKG < 150 MB; tempo declarado | verificado — 29 camadas, 87 MB, EPSG:31981, 11 s (orçamento declarado: 60 s) |
| 6 | Referências Sanepar no repositório (`referencias/sanepar/`) + leitor de KMZ + camada "marcos geodésicos" perto da obra (raio de 3 km) | marcos de Foz lidos com coordenada; distância à ETA; teste com KMZ sintético | verificado — 24 marcos a até 3 km (MRRN2 a 57 m; RN07A destruído; RBMC ITAI a 4,7 km); teste ok |
| 7 | Estilo: regras de domínio em `conceitos/*.json` com metadata e fonte (etapas Sanepar, disciplinas, intervenções); sem `dataclass` no código novo | `aferir` sem função órfã nem duplicata; nenhum `@dataclass` em `camadas/` | feito — 0 órfã, 0 duplicata, 0 funda; resta `Foto` em mosaico.py (ver emenda) |
| 8 | Visualizador v3 (Sonnet, a partir de spec): árvore por grupo, recorte classificado (intervenções), 4D com linha do tempo e "play", estacas no 3D, supressão e marcos | `scripts/testar_visualizador.py` com as verificações novas, 0 falha | verificado — 134 verificações, 0 falha (desktop claro e celular escuro) |
| 9 | Totais do escopo calculados no Python (regra 12): o front só exibe | totais por etapa iguais aos do Python no teste de interface | verificado — R$ 9,42 mi na 1ª etapa; o front lê `escopo.totais` e os valores por item |
| 10 | Testes, aferição, docs, PR, merge e HTML na tela | pytest ok; aferição registrada; PR mesclado | verificado — 25 testes; aferição ok (registrada em pdca/afericao.jsonl); PR mesclado |

## Emendas
- 27/10: o GPKG saiu com 514 MB (uma feição por subcaminho). Passou a uma feição por layer CAD, sem hachuras e
  texto: 111 MB, mas 8,5 min de gravação. Otimizar no item 5.
- 27/10: GPKG passou a ser montado do pacote vetorial já calculado (sem reler PDF, shapely vetorizado): 514 s → 11 s.
- 27/10: conceito corrigido em `conceitos/disciplinas.json`: PLATERRA (PBEA) é aterramento, não terraplenagem;
  "REESTRUTURAR" não é estrutura. Os dois casos têm teste.
- 27/10: `mosaico.py` mantém a classe `Mosaico` e o `@dataclass Foto` (código herdado de Irati, ~40 usos de atributo).
  A conversão para dict fica como item próprio da próxima rodada para não arriscar o mosaico verificado.
- 27/10: `visualizador.py` ficou com 4 funções (arquivo raso) depois de remover a órfã `arquivo_data_url`. O papel é
  próprio (gerar o HTML a partir do template) e `obra.py` já passa de 20 funções, então fica separado.
- 27/10: marcos geodésicos — o popup procurava `SITUAÇÃO`, mas os KMZ trazem `SITUAÇÃO ÚLTIMA VISITA`; o RN07A
  (destruído) passaria como "não informada". Campos normalizados no Python (`sig._campos_marco`), com teste.
