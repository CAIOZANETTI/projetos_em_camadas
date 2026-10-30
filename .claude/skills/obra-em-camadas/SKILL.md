---
name: obra-em-camadas
description: Orquestra uma obra inteira de ponta a ponta — fotos de drone (nadirais + oblíquas) e pasta de projeto no Google Drive até o HTML interativo com ortofoto, 3D, pranchas vetoriais por layer CAD, etapas, escopo de materiais e sondagens. Use quando o usuário pedir "faça o mesmo para a obra X", passar uma pasta do Drive de uma obra nova, ou pedir o HTML em camadas completo. Define a divisão de trabalho Haiku/Sonnet/Opus.
---

# Obra em camadas: do Drive ao HTML

Referência viva: `exemplos/foz/obra.json` e `docs/PLANO_FOZ.md` (ETA Vila C, Foz do Iguaçu).
O pipeline inteiro é `python -m camadas.obra <obra.json>`. Cada etapa grava cache em
`saida/<obra>/`; use `--refazer sfm,pranchas,controle` para refazer.

## Divisão de trabalho (custo × qualidade)

| Quem | Tarefas | Por quê |
|---|---|---|
| **Haiku** (`model: "haiku"`) | inventário recursivo do Drive (só metadados) → CSV; download em massa dos PDFs/fotos e decodificação base64 | mecânico, muitas chamadas, zero julgamento |
| **Sonnet** (`model: "sonnet"`) | ler planilhas de orçamento e extrair escopo/etapas; ler relatórios de sondagem, pranchas de fundação, TR e memoriais e estruturar em JSON; implementar front-end a partir de spec (`docs/VISUALIZADOR_V2.md`, seções v2 e v3) | leitura técnica extensa com regras claras |
| **Opus** (sessão principal) | arquitetura, decisões de engenharia, georreferenciamento (pontos de controle visuais, validação), SfM/ortofoto, revisão dos resultados dos agentes, PR | julgamento, geometria, integração |

Rode os agentes Haiku/Sonnet **em segundo plano e em paralelo**, com prompts autocontidos
(ids do Drive, pasta de saída, formato exato de saída, "não invente"). Nunca deixe dois agentes
varrerem a mesma pasta `tool-results/` (um recolhe os downloads do outro).

## Passos

1. **Inventário (Haiku)** — skill `drive-ingestao`. Saída: CSV com caminho;titulo;id;mime;tamanho.
   Destaque: sondagem, fundação, layout/implantação, memorial, planilha orçamentária, "etapa".
2. **Fotos** — baixe as fotos do drone para `dados/<obra>/foto_drone/` (skill `drive-ingestao`).
3. **3D + ortofoto** — skill `modelo-3d-drone`: `python -m camadas.sfm <fotos> saida/<obra>/sfm --denso --orto 0.04`.
   A classificação nadir/oblíqua sai da pose do SfM (o EXIF do DJI Mini 2 grava pitch 0).
4. **Download dos PDFs (Haiku)** e **leituras técnicas (Sonnet)** em paralelo:
   - orçamento → skill `escopo-etapas` (`camadas/orcamento_sanepar.py`);
   - sondagens/fundação/etapas → JSON (`sondagens.json` com E/N, NSPT, camadas; `fundacoes.json`; `etapas.json`;
     `coordenadas_referencia.json` com qualquer afim pt→UTM obtida de coordenadas topográficas).
5. **Georreferenciar pranchas (Opus)** — skill `georef-pranchas`. Uma prancha base por pontos de
   controle; as demais como "irmãs" (CAD × CAD) ou por afim absoluta. Controle absoluto
   (sondagens locadas por topografia) corrige o viés do GPS do drone.
6. **obra.json** — copie `exemplos/foz/obra.json` e ajuste caminhos, pranchas, etapas, escopo,
   sondagens e `controle_absoluto`. Rode `python -m camadas.obra`.
7. **Visualizador** — `saida/<obra>/<id>_camadas_v<versão>_<data>.html` (offline; `obra.nome_html`, padrão
   mudável por `nome_html` no obra.json; versão em `camadas.VERSAO` = topo do CHANGELOG). Teste com
   `python scripts/testar_visualizador.py saida/<obra>/<arquivo>.html`.
   Para publicar (Artifact, limite 16 MB) use a versão `…_artifact.html` (CDN) e, se
   passar do limite, reduza `max_pontos_3d` e `res_html` no obra.json.
   **Área da obra** (`"area_obra": {"fontes": [regex de vetor], "margem_m", "margem_satelite_m"}`): a ortofoto do
   drone entra só na envoltória das intervenções + margem (o satélite mostra o entorno) e o satélite só pede tiles
   na extensão da obra (voo + pranchas georreferenciadas). Foz: 67 % do voo, ortofoto 1,84 → 1,24 MB. O peso maior
   do HTML são as pranchas vetoriais (~12 MB de 26): vão inteiras (a aba Pranchas mostra a folha toda),
   simplificadas a 0,25 pt só para a tela e por coluna + gzip 9; os quantitativos usam a geometria exata.
   **Aba Obra** (`camadas/construtivos.py`): o que já é vetor vira elemento construtivo pesquisável — unidades e
   sistemas em `conceitos/unidades_construtivas.json` (sigla sem nome no projeto fica com o código, estado premissa);
   rede = um trecho por folha, linha clicável com DN, extensão e contrato × desenho.
   **Escopo** (`camadas/escopo_obra.py`): cada unidade dentro/fora/a definir pela convenção do desenho de etapas
   (`escopo_unidades` no obra.json) ou manual com a fonte; decomposição por tipologia (`conceitos/construcao_civil.json`)
   com evidências determinísticas e link do Drive — lacuna aparece como "sem evidência", não se esconde.
8. **Conferência visual (Opus)** — sobreponha cada prancha aceita à ortofoto em zoom alto; marque
   no obra.json como pendente o que não convencer. Nunca aceite georreferência só pelo número.

## Rodada 3 (o que entrou e como usar)
- **Conceitos editáveis** em `conceitos/*.json` (etapas Sanepar, disciplinas, intervenções), com metadata e fonte.
  Classificação errada (ex.: PLATERRA = aterramento, REESTRUTURAR ≠ estrutura) se corrige ali, com teste.
- **Marcos geodésicos**: `referencias/sanepar/*.kmz` (Sanepar MRRN/RN, IBGE, municipal, RBMC). `obra.json`
  `referencias_geodesicas: {pasta, raio_m}` cria a camada com distância à obra. Use os marcos em bom estado para
  pontos de controle GNSS e datum vertical; a RBMC mais próxima é a base do RTK/PPK.
- **Supressão vegetal estimada** (`supressao`): `obra.json` `supressao: {faixa_m, altura_min_m, etapas}`.
- **4D**: `cronograma` com atividades (início/fim em dias da OS, peso % das UCs do TR, seletor por pranchas,
  grupos, etapas, vetores, estacas). Elementos e curva S são calculados no Python; o HTML só exibe.
- **SIG**: `sig/` com ortofoto.tif, mds.tif, obra.gpkg e pontos/*.points (`"sig": true`).
- **Estilo do Caio** (skill `estilo-caio-python`): dict puro, pt-BR, YAGNI, cálculo no Python,
  `metadados()` com bibliografia, `python scripts/afericao.py --registrar` antes do PR.

## Rodada 7 (inventário, movimento de terra e valas)
- **Inventário** (`camadas/inventario.py`, aba Projeto): todos os PDFs da listagem do Drive com situação, carimbo e
  planta × detalhe × documento; detalhe e documento ficam só na aba Projeto. Resumo por disciplina para conferir
  com o levantamento real. Skill `drive-ingestao`.
- **Escavação e reaterro** (`camadas/escavacao.py`): `obra.json` `escavacao: {pranchas, layer_base, layer_marca,
  layer_crista, cores_etapa}`. Base = preenchimentos das estruturas; fundo = OCR das marcas de nível (cache em
  `saida/<obra>/escavacao_cache.json`); crista desenhada recorta a cava; edificações do MDS são parede. Exige
  controle vertical. Confira a crista do modelo × a desenhada e as cavas "na borda do levantamento".
- **Valas** (`camadas/valas.py`): `obra.json` `valas: {redes[{id, pranchas, criterio, layer_*, de_mm?}],
  urbanizacao}`. Critérios: `divisas` (contagem de linhas), `meio_fio` (meio-fio × alinhamento em layers
  separados), `quadras` (cadastro municipal) e `ortofoto` (superfície existente pela cor). O DE vem do contrato
  (`tubo_x_desenho`) quando a prancha está ligada a uma tabela. Valide a hachura da urbanização pela área do item do
  contrato antes de usá-la (Foz: H01 2 780 m² × asfalto 2 704 m²).

## Rodada 8 (prancha em camadas de entendimento)
- **Fichas** (`camadas/prancha.py`, skill `ler-prancha`): `obra.json` `fichas: [...]` com piloto `hidraulica`
  (balões → relação de materiais → contrato) ou `estrutura` (estacas e blocos pela geometria, encaixe nas estacas
  com E/N, níveis → blocos em 3D). Aba Projeto mostra a ficha; o mapa ganha `blocos_forma` e o 3D os sólidos.
- **Classe de elemento por layer** (`conceitos/elementos.json`): cada layer do pacote vetorial ganha `elemento`
  (tubo, válvula, bloco…), exibido na árvore de layers e pesquisável no filtro.

## Regras que valem ouro
- **Mantenha o vetor.** PDF de prancha tem layers CAD, textos e quantidades: nada de rasterizar
  para o HTML (`pdf_cad.pacote_vetorial`).
- Coordenadas sempre em SIRGAS 2000 / UTM no Python; o navegador só converte para exibir.
- Dados do cliente (orçamento, PDFs, fotos) ficam em `dados/` (fora do git). **Sem preço**: o escopo é o do
  contrato — nenhum valor unitário, total ou fornecedor sai do extrator nem vai para o HTML (decisão do Caio,
  28/10/2026). A especificação vem de `referencias/sanepar/catalogo_materiais.jsonl.gz`.
- Pranchas com malha de coordenadas impressa (adutoras, urbanização, drenagem) vão por `"malha"` no obra.json
  (skill `georef-pranchas`, modo 0); enraíze as irmãs numa prancha absoluta ou com malha, nunca numa escala
  medida na foto.
- Relate lacunas explicitamente (ex.: "3ª etapa existe no desenho mas não no TR").
