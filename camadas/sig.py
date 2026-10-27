"""Exportações para SIG (QGIS/ArcGIS): GeoTIFF, GeoPackage e pontos de controle.

    saida/<obra>/sig/
        ortofoto.tif        RGB, SIRGAS 2000 / UTM, com overviews (abre rápido no QGIS)
        mds.tif             float32, altura sobre a decolagem (m), nodata = -9999
        obra.gpkg           camadas: etapas, supressao, sondagens, estacas, cameras e uma
                            camada de linhas por prancha (com layer CAD, grupo e subgrupo)
        pontos/<id>.points  pontos de controle no formato do Georreferenciador do QGIS
                            (pixel de um raster da prancha a `dpi_pontos`)

Segue as convenções do QGIS / pygis.io: geometrias em UTM (métrico) no GeoPackage,
CRS explícito (EPSG), atributos tabulares e um arquivo por tipo de dado.
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np


def geotiff(jpg_ou_png: str | Path, saida: str | Path, mds: bool = False) -> Path:
    """Converte imagem + .json de georreferência (camadas.geo.salvar_georef) em GeoTIFF."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import Affine
    src = Path(jpg_ou_png)
    meta = json.loads(src.with_suffix(".json").read_text())
    e0, n1 = meta["canto_sup_esq"]
    res = meta["res_m_px"]
    if mds:
        a = cv2.imread(str(src), cv2.IMREAD_UNCHANGED).astype(np.float32) / 100 + meta["z_min_m"]
        bandas, dtype, nodata = a[None], "float32", -9999.0
    else:
        img = cv2.imread(str(src), cv2.IMREAD_COLOR)[..., ::-1]
        alfa = (img.min(axis=2) < 250).astype(np.uint8) * 255
        bandas, dtype, nodata = np.concatenate([img.transpose(2, 0, 1), alfa[None]]), "uint8", None
    saida = Path(saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    perfil = dict(driver="GTiff", width=bandas.shape[2], height=bandas.shape[1], count=bandas.shape[0],
                  dtype=dtype, crs=f"EPSG:{meta['epsg']}", transform=Affine(res, 0, e0, 0, -res, n1),
                  tiled=True, blockxsize=512, blockysize=512, compress="deflate", nodata=nodata)
    if not mds:
        perfil["photometric"] = "RGB"
    with rasterio.open(saida, "w", **perfil) as dst:
        dst.write(bandas)
        if not mds:
            dst.colorinterp = [rasterio.enums.ColorInterp.red, rasterio.enums.ColorInterp.green,
                               rasterio.enums.ColorInterp.blue, rasterio.enums.ColorInterp.alpha]
        dst.build_overviews([2, 4, 8, 16], Resampling.average)
    return saida


def _gdf_de_fc(fc: dict, epsg: int):
    import geopandas as gpd
    if not fc.get("features"):
        return None
    g = gpd.GeoDataFrame.from_features(fc["features"], crs="EPSG:4326")
    # GPKG não aceita colunas que só diferem na caixa (OBS × Obs nos KMZ): minúsculas, juntando as repetidas
    for coluna in [c for c in g.columns if c != "geometry"]:
        nome = coluna.strip().lower()
        if nome != coluna:
            g[nome] = g[coluna] if nome not in g.columns else g[nome].combine_first(g[coluna])
            g = g.drop(columns=coluna)
    for c in g.columns:                                  # listas/dicts não cabem em coluna OGR
        if c != "geometry" and g[c].map(lambda v: isinstance(v, (list, dict))).any():
            g[c] = g[c].map(lambda v: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v)
    return g.to_crs(epsg)


def _geometrias_da_prancha(prancha: dict):
    """Pacote vetorial (coords/partes do visualizador) -> (layer, tipo, geometria) em UTM, uma por layer CAD.

    Reaproveita o que o pacote já tem (sem reler o PDF): deltas Int32 -> pontos em pt -> UTM pela afim; só as partes
    que tocam `clip_mapa`; hachuras e texto ficam de fora (estão no HTML). Construção vetorizada do shapely 2.
    """
    import base64
    import gzip
    import re
    import shapely
    deltas = np.frombuffer(gzip.decompress(base64.b64decode(prancha["coords"])), "<i4").reshape(-1, 2)
    partes = np.frombuffer(gzip.decompress(base64.b64decode(prancha["partes"])), "<u4").reshape(-1, 4)
    pontos_pt = np.cumsum(deltas.astype(np.int64), axis=0) / 10
    afim = np.asarray(prancha["M"], float).reshape(2, 3)
    utm = pontos_pt @ afim[:, :2].T + afim[:, 2]
    n_pontos, layer, flags = partes[:, 0].astype(np.int64), partes[:, 1], partes[:, 3]
    inicio = np.r_[0, np.cumsum(n_pontos)[:-1]]
    x0, y0, x1, y1 = prancha["clip_mapa"] or (0, 0, prancha["largura"], prancha["altura"])
    xmin, xmax = np.minimum.reduceat(pontos_pt[:, 0], inicio), np.maximum.reduceat(pontos_pt[:, 0], inicio)
    ymin, ymax = np.minimum.reduceat(pontos_pt[:, 1], inicio), np.maximum.reduceat(pontos_pt[:, 1], inicio)
    nomes = [l["nome"] for l in prancha["layers"]]
    fora = np.array([bool(re.search(r"HACHURA|TEXTO|TXT|CARIMBO|LOGO", n, re.I)) for n in nomes])
    usar = (xmax >= x0) & (xmin <= x1) & (ymax >= y0) & (ymin <= y1) & ~fora[layer] & (n_pontos >= 2)
    area = usar & (flags & 2 > 0) & (n_pontos >= 4)
    linha = usar & ~area
    saida = []
    for selecao, tipo in ((linha, "linhas"), (area, "areas")):
        ids = np.flatnonzero(selecao)
        if not len(ids):
            continue
        indice_ponto = np.repeat(np.arange(len(ids)), n_pontos[ids])
        idx = np.concatenate([np.arange(a, a + n) for a, n in zip(inicio[ids], n_pontos[ids])])
        if tipo == "linhas":
            geoms = shapely.linestrings(utm[idx], indices=indice_ponto)
        else:
            geoms = shapely.polygons(shapely.linearrings(utm[idx], indices=indice_ponto))
        for li in np.unique(layer[ids]):
            junto = geoms[layer[ids] == li]
            multi = shapely.multilinestrings(junto) if tipo == "linhas" else shapely.multipolygons(junto)
            saida.append((nomes[li], tipo, multi))
    return saida


def geopackage(dados: dict, saida: str | Path, epsg: int) -> Path:
    """Grava as camadas vetoriais da obra num GeoPackage (UTM): vetores, sondagens e uma camada por prancha
    georreferenciada (uma feição por layer CAD, com grupo e subgrupo da disciplina)."""
    import geopandas as gpd
    from shapely.geometry import Point
    saida = Path(saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.unlink(missing_ok=True)
    escritos = []

    def gravar(gdf, nome):
        if gdf is not None and len(gdf):
            gdf.to_file(saida, layer=nome, driver="GPKG")
            escritos.append(f"{nome} ({len(gdf)})")

    for v in dados.get("vetores", []):
        gdf = _gdf_de_fc(v["geojson"] if v["geojson"].get("type") == "FeatureCollection"
                         else {"features": [v["geojson"]]}, epsg)
        gravar(gdf, v["id"].replace("-", "_").replace(" ", "_")[:60])
    furos = [f for f in dados.get("sondagens", []) if f.get("E") and f.get("N")]
    if furos:
        gravar(gpd.GeoDataFrame([{k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v)
                                  for k, v in f.items() if k not in ("lon", "lat")} for f in furos],
                                geometry=[Point(f["E"], f["N"]) for f in furos], crs=f"EPSG:{epsg}"), "sondagens")
    for prancha in dados.get("pranchas", []):
        if prancha.get("M") is None:
            continue
        grupo = {l["nome"]: (l.get("grupo"), l.get("subgrupo")) for l in prancha["layers"]}
        linhas = _geometrias_da_prancha(prancha)
        if linhas:
            gravar(gpd.GeoDataFrame([{"layer": n, "tipo": t, "grupo": grupo[n][0], "subgrupo": grupo[n][1]}
                                     for n, t, _ in linhas],
                                    geometry=[g for _, _, g in linhas], crs=f"EPSG:{epsg}"), f"prancha_{prancha['id']}")
    (saida.parent / "camadas.txt").write_text("\n".join(escritos), encoding="utf-8")
    return saida


def pontos_qgis(M: np.ndarray, clip_pt, saida: str | Path, epsg: int, dpi: float = 150) -> Path:
    """Arquivo .points do Georreferenciador do QGIS: 4 cantos da área útil da prancha.
    `sourceX/sourceY` em pixel de um raster da prancha a `dpi` (y negativo, convenção do QGIS)."""
    x0, y0, x1, y1 = clip_pt
    k = dpi / 72
    linhas = [f"#CRS: EPSG:{epsg}", "mapX,mapY,sourceX,sourceY,enable,dX,dY,residual"]
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        E, N = M[:2, :2] @ [x, y] + M[:2, 2]
        linhas.append(f"{E:.4f},{N:.4f},{x * k:.3f},{-y * k:.3f},1,0,0,0")
    saida = Path(saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text("\n".join(linhas) + "\n")
    return saida


def ler_kmz(caminho: str | Path) -> list[dict]:
    """Marcos de um KMZ de rede de referência (Sanepar, IBGE, municipal, RBMC): nome, lon/lat e os atributos da
    tabela da descrição (`<td>chave</td><td>valor</td>` ou `atr-name`/`atr-value` do IBGE); `<Null>` vira None."""
    import html
    import re
    import zipfile
    with zipfile.ZipFile(caminho) as z:
        kml = z.read(next(n for n in z.namelist() if n.endswith(".kml"))).decode("utf-8", "replace")
    marcos = []
    for bloco in re.findall(r"<Placemark.*?</Placemark>", kml, re.S):
        coord = re.search(r"<coordinates>\s*([-\d.]+),([-\d.]+)", bloco)
        if not coord:
            continue
        pares = (re.findall(r"<td>([^<]*)</td>\s*<td>([^<]*)</td>", bloco)
                 or re.findall(r'atr-name">([^<]*)</span>:</strong>\s*<span class="atr-value">([^<]*)', bloco))
        atributos = {html.unescape(k).strip(): (None if html.unescape(v).strip() in ("", "<Null>") else html.unescape(v).strip())
                     for k, v in pares}
        nome = re.search(r"<name>([^<]*)</name>", bloco)
        marcos.append({"nome": html.unescape(nome.group(1)).strip() if nome else None,
                       "lon": float(coord.group(1)), "lat": float(coord.group(2)), "atributos": atributos})
    return marcos


def marcos_proximos(pasta: str | Path, lon: float, lat: float, raio_m: float, epsg: int) -> dict:
    """FeatureCollection dos marcos de todas as redes da pasta num raio do ponto, com distância (m, no plano UTM)
    e a rede de origem; da RBMC entra sempre a estação mais próxima (base para GNSS), mesmo fora do raio."""
    from . import geo
    e0, n0 = geo.para_utm(lon, lat, epsg)
    feats = []
    for arquivo in sorted(Path(pasta).glob("*.kmz")):
        rede = "RBMC" if "RBMC" in arquivo.name.upper() else arquivo.stem.split("_")[-3].title()
        marcos = ler_kmz(arquivo)
        if not marcos:
            continue
        lons, lats = np.array([m["lon"] for m in marcos]), np.array([m["lat"] for m in marcos])
        E, N = geo.para_utm(lons, lats, epsg)
        distancia = np.hypot(np.asarray(E) - e0, np.asarray(N) - n0)
        escolhidos = np.flatnonzero(distancia <= raio_m)
        if rede == "RBMC":
            escolhidos = np.union1d(escolhidos, [int(np.argmin(distancia))])
        for i in escolhidos[np.argsort(distancia[escolhidos])]:
            m = marcos[i]
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [m["lon"], m["lat"]]},
                          "properties": {"nome": m["nome"], "rede": rede, "distancia_m": round(float(distancia[i]), 1),
                                         **m["atributos"]}})
    feats.sort(key=lambda f: f["properties"]["distancia_m"])
    return {"type": "FeatureCollection", "features": feats}
