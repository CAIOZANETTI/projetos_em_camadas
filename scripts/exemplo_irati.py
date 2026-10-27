"""Exemplo completo — EEB 10 Alto Recalque + Reservatório de Passagem (SAA Irati/PR).

1. monta o mosaico georreferenciado das fotos do drone (camadas.mosaico);
2. lê a folha 04/21 já separada em camadas do HTML-conceito (foto + 11 camadas);
3. registra a foto da folha sobre o mosaico (SIFT) -> a folha herda coordenadas UTM;
4. gera o visualizador HTML único com mosaico, satélite, folha, pegadas das fotos e
   anotações de exemplo.

Uso:
    python scripts/exemplo_irati.py --fotos dados/irati/foto_drone \
        --conceito "dados/irati/EEB 10 Irati – drone × projeto.html" --saida saida/irati
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from camadas import geo, visualizador  # noqa: E402
from camadas.mosaico import Mosaico  # noqa: E402
from camadas.registro import registrar  # noqa: E402


def ler_conceito(caminho: Path) -> dict:
    """Extrai do HTML-conceito a foto, os pacotes de camadas e a lista de camadas."""
    s = caminho.read_text(encoding="utf-8")
    i = s.index("const D=") + len("const D=")
    j = s.index(";\nconst W=", i)
    return json.loads(s[i:j])


def decodificar(b64: str, flags=cv2.IMREAD_UNCHANGED) -> np.ndarray:
    return cv2.imdecode(np.frombuffer(base64.b64decode(b64), np.uint8), flags)


def m23(M: np.ndarray) -> list:
    return np.asarray(M)[:2].ravel().tolist()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fotos", required=True)
    ap.add_argument("--conceito", required=True)
    ap.add_argument("--saida", required=True)
    ap.add_argument("--res-html", type=float, default=0.05, help="m/px do mosaico embutido no HTML")
    ap.add_argument("--leaflet", choices=["inline", "cdn"], default="inline")
    ap.add_argument("--artifact", action="store_true", help="grava também a versão sem <html>/<head> para publicar")
    a = ap.parse_args()
    out = Path(a.saida)
    out.mkdir(parents=True, exist_ok=True)

    # 1. mosaico ------------------------------------------------------
    mos_path = out / "mosaico.jpg"
    mosaico = Mosaico(a.fotos)
    rel = mosaico.executar(mos_path, res=0.04)
    epsg = mosaico.epsg
    mos = cv2.imread(str(mos_path))
    e0, n0, e1, n1 = rel["saida"]["extensao_utm"]
    res = rel["saida"]["res_m_px"]
    M_mos = np.array([[res, 0, e0], [0, -res, n1], [0, 0, 1]])        # px do mosaico -> UTM

    # 2-3. folha do conceito registrada no mosaico ----------------------
    D = ler_conceito(Path(a.conceito))
    foto = decodificar(D["foto"])
    r = registrar(foto[..., :3], mos, "similaridade", mascara_movel=foto[..., 3] > 0)
    M_folha = M_mos @ r["M"]                                          # px da folha -> UTM
    esc_folha = float(np.sqrt(abs(np.linalg.det(M_folha[:2, :2]))))
    print(f"Folha registrada no mosaico: {r['inliers']} pontos, resíduo mediano "
          f"{r['residuo_px'] * res * 100:.1f} cm; pixel da folha = {esc_folha * 100:.2f} cm")

    # mosaico reduzido para o HTML
    k = res / a.res_html
    mos_html = cv2.resize(mos, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    alfa = cv2.resize((mos.min(axis=2) < 250).astype(np.uint8) * 255, mos_html.shape[1::-1],
                      interpolation=cv2.INTER_NEAREST)
    M_mos_html = M_mos @ np.diag([1 / k, 1 / k, 1])

    # 4. vetores: pegadas das fotos e trajeto do voo ----------------------
    pegadas, trajeto = [], []
    for f in sorted(rel["fotos"], key=lambda f: f["data"] or ""):
        nome = Path(f["arquivo"]).name
        T = np.array(rel["foto_para_utm"][nome])
        w, h = f["largura"], f["altura"]
        cant = geo.aplicar(T, [[0, 0], [w, 0], [w, h], [0, h], [0, 0]])
        lon, lat = geo.para_lonlat(cant[:, 0], cant[:, 1], epsg)
        pegadas.append({"type": "Feature",
                        "geometry": {"type": "Polygon", "coordinates": [np.c_[lon, lat].round(8).tolist()]},
                        "properties": {"nome": nome, "data": f["data"], "alt_rel_m": f["alt_rel"],
                                       "gsd_cm": round(f["gsd"] * 100, 2)}})
        trajeto.append([round(f["lon"], 8), round(f["lat"], 8)])

    # 5. sistema de coordenadas -----------------------------------------
    alt_terreno = float(np.median([f["alt_abs"] - f["alt_rel"] for f in rel["fotos"]]))
    crs = visualizador.crs_info(epsg, [e0, n0, e1, n1], alt_terreno)
    print(f"Afim UTM<->lon/lat: erro máx {crs['erro_afim_m'] * 1000:.2f} mm; k = {crs['k']:.6f}")

    # 6. anotações de exemplo (px do mosaico a 4 cm -> lon/lat) ------------
    def ll(pts_px):
        u = geo.aplicar(M_mos, pts_px)
        lon, lat = geo.para_lonlat(u[:, 0], u[:, 1], epsg)
        return np.c_[lon, lat].round(9).tolist()

    exemplo = {"autor": "Exemplo", "status": "aberta", "criado": "2026-10-27T12:00:00", "exemplo": True}
    anot = [
        {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ll(
            [[1790, 1892], [2000, 1725], [2106, 1852], [1892, 2022], [1790, 1892]])]},
         "properties": {**exemplo, "id": "ex1", "tipo": "area", "disciplina": "Civil",
                        "titulo": "Cobertura da edificação existente",
                        "texto": "Área de projeção do telhado medida sobre o mosaico. Conferir com o levantamento cadastral."}},
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": ll([[1892, 2022], [1890, 2460]])},
         "properties": {**exemplo, "id": "ex2", "tipo": "distancia", "disciplina": "Civil",
                        "titulo": "Afastamento entre edificação existente e nova estrutura",
                        "texto": "Distância horizontal no plano UTM."}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": ll([[2500, 2000]])[0]},
         "properties": {**exemplo, "id": "ex3", "tipo": "nota", "disciplina": "Civil",
                        "titulo": "Margem do rio",
                        "texto": "Comparar a camada 'Cota de inundação / rio' com a margem visível na foto."}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": ll([[1890, 1610]])[0]},
         "properties": {**exemplo, "id": "ex4", "tipo": "nota", "disciplina": "Hidromecânica",
                        "titulo": "Tubos estocados no canteiro",
                        "texto": "Conferir diâmetros e quantidades com a lista de materiais da hidromecânica."}},
    ]

    # 7. montagem dos dados --------------------------------------------
    camadas = D["camadas"]
    for c in camadas:
        c["disciplina"] = "Civil"
    data_voo = (rel["fotos"][0]["data"] or "")[:10].replace(":", "-")
    aj = rel.get("ajuste", {})
    dados = {
        "id": "irati-eeb10",
        "titulo": "EEB 10 Alto Recalque + Reservatório de Passagem",
        "titulo_curto": "EEB 10 Irati",
        "subtitulo": "SAA Irati/PR · voo de drone " + "/".join(reversed(data_voo.split("-"))),
        "crs": crs,
        "bases": [{
            "id": "mosaico", "nome": f"Mosaico drone ({len(rel['fotos'])} fotos)", "grupo": "Levantamento",
            "src": visualizador.data_url(np.dstack([mos_html, alfa]), "webp", 80),
            "w": mos_html.shape[1], "h": mos_html.shape[0], "m": m23(M_mos_html), "visivel": True,
        }],
        "satelite": True,
        "folhas": [{
            "id": "f04", "nome": "Folha 04/21 · Layout de drenagem", "disciplina": "Civil",
            "w": D["w"], "h": D["h"], "m": m23(M_folha),
            "pacotes": ["data:image/webp;base64," + p for p in D["pacotes"]],
            "camadas": camadas,
        }],
        "vetores": [
            {"id": "pegadas", "nome": "Pegadas das fotos", "grupo": "Levantamento", "visivel": False,
             "geojson": {"type": "FeatureCollection", "features": pegadas},
             "estilo": {"color": "#f5c518", "weight": 1.5, "fillOpacity": 0.04, "dashArray": "4 3"}},
            {"id": "trajeto", "nome": "Trajeto do voo", "grupo": "Levantamento", "visivel": False,
             "geojson": {"type": "Feature", "properties": {"nome": "Trajeto do voo"},
                         "geometry": {"type": "LineString", "coordinates": trajeto}},
             "estilo": {"color": "#f5c518", "weight": 2}},
        ],
        "pendentes": {
            "Civil": ["Demais 20 folhas do projeto civil", "Terraplenagem e perfis"],
            "Hidromecânica": ["Tubulação de recalque", "Bombas, válvulas e conexões", "Reservatório (planta e cortes)"],
            "Elétrica": ["Entrada de energia e rede MT/BT", "Quadros e painéis", "Aterramento e SPDA"],
        },
        "anotacoes": {"type": "FeatureCollection", "features": anot},
        "info": [
            ["Sistema", f"{crs['nome']} (EPSG:{epsg})"],
            ["Mosaico", f"{len(rel['fotos'])} fotos DJI {rel['fotos'][0]['modelo']}, altura ≈ "
                        f"{np.median([f['alt_rel'] for f in rel['fotos']]):.0f} m"],
            ["GSD original", f"{aj.get('gsd_ajustado_m', 0) * 100:.1f} cm/px (embutido a {a.res_html * 100:.0f} cm/px)"],
            ["Costura entre fotos", f"mediana {aj.get('residuo_costura_m', {}).get('mediana', 0) * 100:.0f} cm"],
            ["Posição absoluta", f"GPS do drone, RMSE {aj.get('rmse_gps_m', 0):.1f} m (sem pontos de controle)"],
            ["Folha 04/21", f"registrada no mosaico por {r['inliers']} pontos, resíduo "
                            f"{r['residuo_px'] * res * 100:.0f} cm (herda o ajuste de 5 pontos do conceito, ≤ 0,5 m)"],
            ["Fator de escala", f"k = {crs['k']:.5f} (projeção {crs['k_proj']:.5f} × altitude {crs['k_alt']:.5f})"],
        ],
    }
    html = visualizador.gerar(dados, out / "visualizador.html", a.leaflet)
    print(f"Visualizador: {html} ({html.stat().st_size / 1e6:.1f} MB)")
    if a.artifact:
        visualizador.gerar(dados, out / "visualizador_artifact.html", "cdn", documento=False)
    (out / "registro_folha.json").write_text(json.dumps({
        "folha_px_para_utm": M_folha.tolist(), "inliers": r["inliers"],
        "residuo_cm": r["residuo_px"] * res * 100}, indent=2))


if __name__ == "__main__":
    main()
