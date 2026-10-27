"""Gera o visualizador HTML (arquivo único) a partir de um dicionário de dados.

Estrutura de `dados` (tudo em JSON; imagens como data URL):
{
  "id": "irati-eeb10",                       # chave das anotações no navegador
  "titulo": "...", "subtitulo": "...",
  "crs": {"epsg": 31982, "nome": "SIRGAS 2000 / UTM 22S",
          "ll2utm": [6 coef.], "utm2ll": [6 coef.], "k": fator de escala combinado},
  "bases":   [{"id", "nome", "grupo", "src", "w", "h", "m": [2x3 px->UTM], "visivel", "info"}],
  "folhas":  [{"id", "nome", "disciplina", "w", "h", "m": [2x3 px->UTM],
               "pacotes": [data URLs, 3 camadas por imagem (R,G,B)],
               "camadas": [{"nome", "rgb": [[r,g,b]], "neon", "oculta", "regiao"}]}],
  "vetores": [{"id", "nome", "grupo", "geojson", "estilo", "visivel"}],
  "pendentes": {"Hidromecânica": ["..."], ...},   # itens ainda não extraídos (aparecem desabilitados)
  "anotacoes": GeoJSON FeatureCollection inicial (exemplos),
  "info": [[rótulo, valor], ...],

  # --- visualizador v2 (todas opcionais; veja docs/VISUALIZADOR_V2.md) ---
  "pranchas": [{"id", "nome", "disciplina", "pdf", "largura", "altura",        # folha em pt, y para baixo
                "layers": [{"nome", "n", "classe", "cor"}], "estilos": [{"s", "f", "w"}],
                "coords": base64(gzip(Int16LE)), "partes": base64(gzip(Uint32LE)),   # vetor da folha inteira
                "n_partes", "n_pontos", "textos": [{"t", "x", "y", "a", "h", "cor"}],
                "M": [a,b,c,d,e,f] pt->UTM | null, "escala_m_pt", "clip_mapa": [x0,y0,x1,y1] | null,
                "georef": {"ok", "motivo", "residuo_mediano_m", "frac_05m"}}],
  "etapas": [{"id": "1ª etapa", "cor": "#rrggbb"}],            # ids usados em layers[].classe e vetores[].etapa
  "escopo": {"itens": [{"tabela", "nome_tabela", "item", "codigo", "descricao", "un",
                        "q1", "q2", "etapa", "material", "local", "preco"}],
             "desenhos_por_tabela": {"01": "código do desenho (nome do PDF sem extensão)"}, "fonte": "..."},
  "sondagens": [{"id", "tipo", "E", "N", "lon", "lat", "cota_boca", "profundidade_m", "na_m",
                 "nspt": [[prof_m, golpes]], "camadas": [{"de", "ate", "descricao", "classe"}], "fonte"}],
  "modelo3d": {"origem": [E0, N0, 0], "n", "pos_cm_b64": Int32LE xyz em cm, "rgb_b64": Uint8 rgb,
               "cameras": [{"nome", "centro", "eixo", "topo", "tipo", "focal_px", "largura", "altura", ...}]},
  "fotos": {"DJI_0249.JPG": data URL webp},   # aberta ao clicar nas câmeras (vetor "cameras", properties.foto)
}

`gerar(..., leaflet="inline")` embute Leaflet e three.js r128 (+ OrbitControls); com "cdn" ambos vêm de CDN.
O three.js só entra no HTML quando há `modelo3d` (sem ele o botão 3D nem aparece).
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import cv2
import numpy as np

from . import geo

TEMPLATES = Path(__file__).parent / "templates"
LEAFLET_CDN = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.js"
THREE_CDN = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"
ORBIT_CDN = "https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"


def _json_seguro(dados: dict) -> str:
    """JSON compacto para embutir num <script>: escapa '</' e U+2028/9 para não encerrar o script."""
    return (json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
            .replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def data_url(img: np.ndarray, fmt: str = "webp", qualidade: int = 80) -> str:
    """Codifica uma imagem OpenCV (BGR/BGRA) como data URL. qualidade 101 = webp sem perdas."""
    params = {"webp": [cv2.IMWRITE_WEBP_QUALITY, qualidade],
              "jpg": [cv2.IMWRITE_JPEG_QUALITY, qualidade], "png": []}[fmt]
    ok, buf = cv2.imencode("." + fmt, img, params)
    if not ok:
        raise RuntimeError("falha ao codificar imagem")
    mime = {"webp": "image/webp", "jpg": "image/jpeg", "png": "image/png"}[fmt]
    return f"data:{mime};base64," + base64.b64encode(buf.tobytes()).decode()


def arquivo_data_url(caminho: str | Path) -> str:
    caminho = Path(caminho)
    mime = {".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg"}[caminho.suffix.lower()]
    return f"data:{mime};base64," + base64.b64encode(caminho.read_bytes()).decode()


def crs_info(epsg: int, extensao_utm, altitude_m: float = 0.0) -> dict:
    """Afins UTM<->lon/lat válidas na área (erro sub-milimétrico em obras de algumas centenas
    de metros) e fator de escala combinado (projeção × altitude) no centro."""
    from pyproj import CRS, Proj
    e0, n0, e1, n1 = extensao_utm
    E, N = np.meshgrid(np.linspace(e0, e1, 15), np.linspace(n0, n1, 15))
    E, N = E.ravel(), N.ravel()
    lon, lat = geo.para_lonlat(E, N, epsg)
    utm, ll = np.c_[E, N], np.c_[lon, lat]
    A = geo.ajustar(ll, utm, "afim")
    B = geo.ajustar(utm, ll, "afim")
    erro = float(geo.residuos(A, ll, utm).max())
    lonc, latc = geo.para_lonlat((e0 + e1) / 2, (n0 + n1) / 2, epsg)
    k_proj = Proj(CRS.from_epsg(epsg)).get_factors(lonc, latc).meridional_scale
    k_alt = 6_371_000 / (6_371_000 + altitude_m)
    return {"epsg": epsg, "nome": CRS.from_epsg(epsg).name,
            "ll2utm": A[:2].ravel().tolist(), "utm2ll": B[:2].ravel().tolist(),
            "erro_afim_m": erro, "k_proj": k_proj, "k_alt": k_alt, "k": k_proj * k_alt,
            "centro": [latc, lonc]}


def gerar(dados: dict, saida: str | Path, leaflet: str = "inline", documento: bool = True) -> Path:
    """leaflet='inline' embute as bibliotecas (Leaflet e, se houver `modelo3d`, three.js + OrbitControls:
    funciona offline); 'cdn' carrega do cdnjs/jsDelivr. documento=False grava só o conteúdo, sem
    <!doctype>/<html>/<head> (para publicar como Artifact)."""
    html = (TEMPLATES / "visualizador.html").read_text(encoding="utf-8")
    css = (TEMPLATES / "vendor" / "leaflet.css").read_text(encoding="utf-8")
    if leaflet == "inline":
        js = (TEMPLATES / "vendor" / "leaflet.js").read_text(encoding="utf-8")
        tag = f"<script>{js}</script>"
    else:
        tag = f'<script src="{LEAFLET_CDN}"></script>'
    # three.js só é necessário para o modo 3D (nuvem de pontos do SfM)
    if not dados.get("modelo3d"):
        tag3 = ""
    elif leaflet == "inline":
        tag3 = "".join(f"<script>{(TEMPLATES / 'vendor' / nome).read_text(encoding='utf-8')}</script>"
                       for nome in ("three.min.js", "OrbitControls.js"))
    else:
        tag3 = f'<script src="{THREE_CDN}"></script><script src="{ORBIT_CDN}"></script>'
    titulo = dados.get("titulo_curto") or dados["titulo"]
    html = (html.replace("/*__LEAFLET_CSS__*/", css)
                .replace("<!--__LEAFLET_JS__-->", tag)
                .replace("<!--__THREE_JS__-->", tag3)
                .replace("__TITULO__", titulo)
                .replace("/*__DADOS__*/null", _json_seguro(dados)))
    if documento:
        html = ('<!doctype html>\n<html lang="pt-BR"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
                + html + "\n</html>\n")
    saida = Path(saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(html, encoding="utf-8")
    return saida
