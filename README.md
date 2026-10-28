# projetos_em_camadas

Códigos e skills para juntar **levantamento aéreo** (fotos de drone, satélite) e **projeto de engenharia** (civil, hidromecânico, elétrico) num **HTML único e navegável em camadas**. O HTML permite medir, anotar e extrair informação.

```
fotos do drone ─► mosaico georreferenciado (UTM) ─┐
pranchas PDF/DWG ─► camadas por disciplina ───────┼─► visualizador HTML (offline)
satélite (opcional, online) ──────────────────────┘    medir · anotar · comparar · exportar
```

## Estrutura

| Caminho | Conteúdo |
|---|---|
| `camadas/mosaico.py` | Metadados DJI (GPS, altitude, rumo, GSD) e mosaico 2D georreferenciado (plano B quando o SfM falha) |
| `camadas/geo.py` | Ajustes similaridade/afim/homografia, resíduos, UTM SIRGAS 2000, world file |
| `camadas/visualizador.py` | Gera o HTML único a partir de um dicionário de dados |
| `camadas/sfm.py` | 3D com pycolmap (CPU): poses, nadir × oblíqua, nuvem densa, **ortofoto verdadeira** + MDS |
| `camadas/pdf_cad.py` | PDF vetorial → traços (dict) por **layer CAD** e cor, textos, classificação por etapa e por disciplina (`conceitos/`), pacote vetorial p/ HTML; separação por cor para PDF escaneado |
| `camadas/georef_prancha.py` | Georreferencia prancha: **malha de coordenadas impressa (OCR)**, CAD × CAD por SIFT (pranchas irmãs), pontos de controle + ICP, busca global; registro imagem↔imagem |
| `camadas/supressao.py` | Supressão vegetal estimada: ExG + altura do MDS na faixa de obra, por etapa |
| `camadas/inventario.py` | Inventário determinístico de **todos** os PDFs da listagem do Drive: situação (no disco / falhou / não tentado), formato da folha, código Sanepar, carimbo (canto inferior direito; texto, fonte reparada ou OCR) e planta × detalhe × documento (`conceitos/tipos_prancha.json`) |
| `camadas/escavacao.py` | Escavação e reaterro por cava: base das estruturas + cota de fundo (OCR das marcas de nível) + crista desenhada + talude + MDS em cota; edificações como parede (`conceitos/escavacao.json`) |
| `camadas/valas.py` | Valas das redes: pista × calçada × lote pela posição no desenho (divisas, meio-fio, quadras) ou superfície existente pela ortofoto; demolição, recomposição e volume de vala por rede (`conceitos/valas.json`) |
| `camadas/sig.py` | GeoTIFF, GeoPackage por layer CAD, `.points` do QGIS; leitor de KMZ das redes de referência (Sanepar, IBGE, RBMC) |
| `conceitos/*.json` | Regras de domínio editáveis sem abrir código (etapas Sanepar, disciplinas, intervenções), com metadata e fonte |
| `referencias/sanepar/` | Redes de referência cadastral Sanepar/IBGE/municipal (fev/2026), RBMC, formulários de topografia SIRGAS 2000 e o cadastro de materiais Sanepar (`catalogo_materiais.jsonl.gz`, 40 mil materiais, só especificação) |
| `camadas/obra.py` | Pipeline completo a partir de um `obra.json` (cache por etapa) |
| `camadas/orcamento_sanepar.py` | Orçamento Sanepar (xlsx) → escopo do contrato com quantidade por etapa, **sem preço**; leitor do cadastro de materiais |
| `camadas/templates/` | Template do visualizador + Leaflet 1.9.4 embutido |
| `scripts/exemplo_irati.py` | Exemplo completo: EEB 10 Alto Recalque (SAA Irati/PR) |
| `exemplos/foz/obra.json` | Obra completa: ETA Vila C, SAA Foz do Iguaçu (etapas, sondagens, 3D) |
| `exemplos/irati/` | Resultado do exemplo: mosaico georreferenciado e visualizador |
| `docs/PLANO.md` | Plano de implementação, fases e perguntas em aberto |
| `docs/PLANO_FOZ.md` | Plano e resultados da obra de Foz (achados, divisão Haiku/Sonnet/Opus, pendências) |
| `docs/VISUALIZADOR_V2.md` | Contrato de dados do HTML v2 (pranchas vetoriais, etapas, escopo, 3D) |
| `docs/PESQUISA_REPOSITORIOS.md` | Projetos semelhantes e lições aprendidas |
| `.claude/skills/` | Skills para o Claude repetir o processo em novos projetos |

## Uso rápido — obra completa

```bash
pip install -r requirements.txt pycolmap pymupdf pytesseract   # + apt-get install tesseract-ocr (malha de coordenadas)
python -m camadas.obra exemplos/foz/obra.json        # SfM + ortofoto + pranchas + escopo + HTML
python scripts/testar_visualizador.py saida/foz/visualizador.html
python scripts/afericao.py --registrar     # régua do código (estilo-caio-python, regra 17)
```
Saídas em `saida/foz/`: `visualizador.html` (offline), `sig/` (ortofoto.tif, mds.tif, obra.gpkg, pontos/*.points para o
QGIS), `sfm/` (nuvem.ply, ortofoto, MDS).
Para uma obra nova, peça ao Claude: *"faça o mesmo para a obra X"* — a skill `obra-em-camadas`
conduz o processo (Haiku baixa, Sonnet lê documentos, Opus georreferencia e integra).

## Uso rápido — peças avulsas

```bash
pip install -r requirements.txt

# 1. mosaico das fotos (JPG com GPS no EXIF)
python -m camadas.mosaico dados/irati/foto_drone saida/irati/mosaico.jpg --res 0.04

# 2. exemplo completo (mosaico + folha 04/21 + visualizador)
python scripts/exemplo_irati.py --fotos dados/irati/foto_drone \
    --conceito "dados/irati/EEB 10 Irati – drone × projeto.html" --saida saida/irati

# testes
python -m pytest -q
```

Abra `saida/irati/visualizador.html` no navegador; funciona offline. O satélite só aparece com internet.
O mosaico (`.jpg` + `.jgw` + `.prj`) abre direto no QGIS, ArcGIS ou AutoCAD Map.

## Resultado do exemplo (Irati)

- **Mosaico**: 10/10 fotos (DJI Mini 2, 58 m, GSD 2 cm/px), costura mediana 12 cm, posição absoluta pelo GPS do drone com RMSE 0,98 m e sistema SIRGAS 2000 / UTM 22S (EPSG:31982). Leva 29 s em CPU.
- **Folha 04/21** (layout de drenagem) registrada automaticamente sobre o mosaico com 649 pontos e resíduo de 7,6 cm.
- **Visualizador** (2,8 MB):
  - camadas por disciplina, folha recolorível e satélite;
  - medições de distância, área, ângulo e coordenada em UTM;
  - notas técnicas com status e autor;
  - cortina de comparação e inspeção da camada sob o cursor;
  - exportação GeoJSON/CSV.

Dados brutos (fotos, zip do projeto) ficam fora do git, em `dados/` (veja `.gitignore`).
