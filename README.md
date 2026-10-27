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
| `camadas/exif.py` | Metadados DJI: GPS, altitude relativa, rumo, GSD |
| `camadas/mosaico.py` | Mosaico georreferenciado (SIFT + ajuste global + GPS), saída JPG/PNG + world file |
| `camadas/registro.py` | Registro automático imagem↔imagem (ex.: prancha com foto → mosaico) |
| `camadas/folha.py` | PDF → raster → camadas por cor do CAD; extração vetorial por layer PDF |
| `camadas/geo.py` | Ajustes similaridade/afim/homografia, resíduos, UTM SIRGAS 2000, world file |
| `camadas/visualizador.py` | Gera o HTML único a partir de um dicionário de dados |
| `camadas/templates/` | Template do visualizador + Leaflet 1.9.4 embutido |
| `scripts/exemplo_irati.py` | Exemplo completo: EEB 10 Alto Recalque (SAA Irati/PR) |
| `exemplos/irati/` | Resultado do exemplo: mosaico georreferenciado e visualizador |
| `docs/PLANO.md` | Plano de implementação, fases e perguntas em aberto |
| `docs/PESQUISA_REPOSITORIOS.md` | Projetos semelhantes e lições aprendidas |
| `.claude/skills/` | Skills para o Claude repetir o processo em novos projetos |

## Uso rápido

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
