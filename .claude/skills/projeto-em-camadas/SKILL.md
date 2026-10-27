---
name: projeto-em-camadas
description: Gera o visualizador HTML único que sobrepõe mosaico de drone, satélite e pranchas de projeto (civil, hidromecânica, elétrica) em camadas, com medições em UTM e anotações. Use quando o usuário pedir para montar, atualizar ou estender o HTML de projeto em camadas de uma obra.
---

# Projeto em camadas → HTML

Referência completa: `scripts/exemplo_irati.py` e `docs/PLANO.md`.

1. **Mosaico georreferenciado**: use a skill `mosaico-drone`. Precisa do `.jpg` + `.json` com `extensao_utm` e `res_m_px`.
2. **Pranchas → camadas** (`camadas/folha.py`):
   - Com DXF/DWG, prefira camadas vetoriais por layer (Fase 1, ezdxf).
   - Com PDF que tem layers (OCG), use `vetores_pdf`.
   - Com PDF "chapado", faça `renderizar_pdf` (200 dpi), depois `cores_dominantes` e monte a lista de camadas com nome e cor do CAD. Em seguida `separar_por_cor`, `empacotar` e grave webp sem perdas (qualidade 101).
3. **Georreferenciar a prancha**: chegue a uma matriz 3×3 *px da prancha → UTM*.
   - Se a prancha já tem foto sobreposta, use `registro.registrar(foto, mosaico)` e componha com a afim do mosaico.
   - Senão, use pontos de controle `x_px;y_px;E;N` e `geo.ajustar(..., "similaridade")`. Reporte `geo.residuos`.
4. **Montar `dados`** (formato no docstring de `camadas/visualizador.py`):
   - `bases` (mosaico), `folhas` (pacotes + camadas + `m`), `vetores` (GeoJSON lon/lat);
   - `pendentes` por disciplina (aparecem como "a extrair");
   - `anotacoes` de exemplo (marque `exemplo: true`);
   - `info` com resíduos e RMSE;
   - `crs` via `visualizador.crs_info(epsg, extensao, altitude)`.
5. **Gerar**: `visualizador.gerar(dados, saida, "inline")` para o arquivo offline. Para publicar como Artifact use `"cdn", documento=False`.
6. **Testar no Chromium** (playwright já instalado): sem erros no console, folha alinhada à foto num zoom alto, medição de distância concluída com Enter, layout de 400 px em modo escuro.

Disciplinas e cores: Civil (laranja), Hidromecânica (azul), Elétrica (amarelo), Geral (verde-azulado). Para mudar, edite `DISC` no template e as variáveis `--civil/--hidro/--eletrica/--geral`.

> Fluxo novo (v2): `python -m camadas.obra <obra.json>` com pranchas **vetoriais** por layer CAD, etapas, escopo, sondagens e 3D — veja a skill `obra-em-camadas` e `docs/VISUALIZADOR_V2.md`. Este roteiro raster (v1) continua válido para PDFs escaneados.
