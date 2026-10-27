#!/usr/bin/env python3
"""Teste de ponta a ponta do visualizador v2 (Chromium headless via Playwright).

Uso:
    python scripts/testar_visualizador.py saida/foz/visualizador.html [--capturas saida/foz/capturas]

Roda o roteiro duas vezes: desktop 1400x900 (tema claro) e celular 400x860 (tema escuro), e verifica:
  * console sem erros (falhas de rede para hosts externos — fontes, satélite — são esperadas offline e ignoradas);
  * a prancha "f004" ligada desenhando no mapa e o clique/snap sobre os traços;
  * o filtro de etapa ("1ª etapa") escondendo layers e manchas;
  * a aba Pranchas numa prancha com textos ("fu1"): folha desenhada e busca de texto;
  * a aba Etapas & escopo (situação por item salva, CSV);
  * sondagens (popup com SVG), foto do drone e o 3D (canvas WebGL com pixels desenhados);
  * sem rolagem horizontal da página no celular.
Sai com código 1 se algum passo falhar. Capturas em PNG na pasta indicada (padrão: <pasta do html>/capturas).
Requer apenas `playwright` (já com o Chromium instalado); não instala nada.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ARGS_CHROMIUM = ["--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]
CENARIOS = [
    {"nome": "desktop", "viewport": {"width": 1400, "height": 900}, "esquema": "light"},
    {"nome": "celular_escuro", "viewport": {"width": 400, "height": 860}, "esquema": "dark"},
]


class Relatorio:
    def __init__(self) -> None:
        self.falhas: list[str] = []
        self.ok = 0

    def passo(self, nome: str, condicao: bool, detalhe: str = "") -> bool:
        if condicao:
            self.ok += 1
            print(f"  [ok]    {nome}" + (f" ({detalhe})" if detalhe else ""))
        else:
            self.falhas.append(nome)
            print(f"  [FALHA] {nome}" + (f" ({detalhe})" if detalhe else ""))
        return condicao


JS_PIXELS_CANVAS = """(sel) => {
  const c = document.querySelector(sel); if (!c || !c.width) return -1;
  const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0;
  for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++;
  return n;
}"""
# folha: conta pixels que não são papel branco nem transparentes
JS_PIXELS_FOLHA = """() => {
  const c = document.querySelector('#fCv'); if (!c || !c.width) return -1;
  const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0;
  for (let i = 0; i < d.length; i += 4) if (d[i + 3] > 0 && d[i] + d[i + 1] + d[i + 2] < 600) n++;
  return n;
}"""
JS_PIXELS_3D = """() => {
  const V = window.__viz && window.__viz.v3; if (!V || !V.renderer) return -1;
  V.renderer.render(V.scene, V.camera);
  const gl = V.renderer.getContext(), w = gl.drawingBufferWidth, h = gl.drawingBufferHeight, px = new Uint8Array(w * h * 4);
  gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, px);
  const r0 = px[0], g0 = px[1], b0 = px[2]; let n = 0;
  for (let i = 0; i < px.length; i += 4) if (Math.abs(px[i] - r0) + Math.abs(px[i + 1] - g0) + Math.abs(px[i + 2] - b0) > 24) n++;
  return n;
}"""


def roteiro(pw, html: Path, cen: dict, pasta: Path, rel: Relatorio) -> None:
    print(f"\n== {cen['nome']} ({cen['viewport']['width']}x{cen['viewport']['height']}, tema {cen['esquema']}) ==")
    # Chromium pré-instalado no ambiente (evita "playwright install" com versão diferente)
    exe = os.environ.get("CHROMIUM") or ("/opt/pw-browsers/chromium" if Path("/opt/pw-browsers/chromium").exists() else None)
    browser = pw.chromium.launch(args=ARGS_CHROMIUM, executable_path=exe)
    ctx = browser.new_context(viewport=cen["viewport"], color_scheme=cen["esquema"], device_scale_factor=1)
    # offline: nada de rede externa (fontes, tiles do satélite); os arquivos locais seguem normais
    ctx.route("**/*", lambda r: r.abort() if r.request.url.startswith(("http://", "https://")) else r.continue_())
    page = ctx.new_page()
    erros: list[str] = []
    page.on("pageerror", lambda e: erros.append(f"exceção: {e}"))

    def console(m):
        if m.type != "error":
            return
        if "Failed to load resource" in m.text and (m.location.get("url") or "").startswith(("http://", "https://")):
            return   # fonte/satélite bloqueados de propósito
        erros.append(f"console.error: {m.text}")
    page.on("console", console)
    tag = cen["nome"]

    def foto(nome: str) -> None:
        page.screenshot(path=str(pasta / f"{nome}_{tag}.png"))

    def js(expr, arg=None):
        return page.evaluate(expr, arg) if arg is not None else page.evaluate(expr)

    page.goto(html.resolve().as_uri())
    page.wait_for_function("window.__viz && document.querySelector('#mapa .leaflet-pane')", timeout=60000)
    page.wait_for_timeout(600)
    info = js("""() => ({pr: __viz.PR.map(p => p.id), tem3d: !!__viz.D.modelo3d, sond: (__viz.D.sondagens || []).length,
        fotos: Object.keys(__viz.D.fotos || {}), escopo: ((__viz.D.escopo || {}).itens || []).length, etapas: (__viz.D.etapas || []).map(e => e.id)})""")
    rel.passo("página carregou e o mapa foi criado", True, f"{len(info['pr'])} pranchas, {info['sond']} sondagens, 3D={info['tem3d']}")
    rel.passo("sem rolagem horizontal da página", js("document.documentElement.scrollWidth <= window.innerWidth + 1"))
    foto("01_inicio")

    # ---- 1) prancha f004 no mapa ----
    if "f004" in info["pr"]:
        page.click("#t-camadas")
        page.check("#v-prancha-f004")
        page.wait_for_function("__viz.PR.find(p => p.id === 'f004').ultimoDesenho", timeout=60000)
        page.wait_for_timeout(500)
        n = js(JS_PIXELS_CANVAS, ".leaflet-pranchas-pane canvas")
        rel.passo("prancha f004 desenhada no mapa", n > 2000, f"{n} pixels")
        ms = js("__viz.PR.find(p => p.id === 'f004').ultimoDesenho.ms")
        rel.passo("redesenho do mapa rápido (< 400 ms)", ms < 400, f"{ms:.0f} ms")
        # identificar e snap sobre um vértice real da prancha
        r = js("""() => {
          const P = __viz.PR.find(p => p.id === 'f004'), k = P.lay.findIndex((li, i) => P.ef[li] && P.ini[i + 1] - P.ini[i] > 3);
          const j = P.ini[k] + 1, x = P.xy[2 * j], y = P.xy[2 * j + 1], ll = __viz.pt2ll(P, x, y), m = __viz.map;
          const alvo = m.containerPointToLatLng(m.latLngToContainerPoint(ll).add([3, 2]));
          const sn = __viz.snapMapa(alvo), pa = m.latLngToContainerPoint(alvo);
          // o ponto grudado é o vértice mais próximo do cursor: no máximo tão longe quanto o vértice de referência (3,6 px)
          return {ident: __viz.identificarPranchas(ll).length, snap: sn ? m.latLngToContainerPoint(sn.ll).distanceTo(pa) : -1};
        }""")
        rel.passo("identificar no mapa acha o traço", r["ident"] > 0, f"{r['ident']} resultado(s)")
        rel.passo("snap gruda num vértice a menos de 8 px do cursor", 0 <= r["snap"] <= 3.62, f"{r['snap']:.2f} px")
        foto("02_mapa_f004")

    # ---- 2) filtro de etapa ----
    if info["etapas"] and "1ª etapa" in info["etapas"]:
        page.click("#t-escopo")
        antes = js("__viz.PR.length ? __viz.PR[0].ef.reduce((a, b) => a + b, 0) : 0")
        page.click('#eChips [data-etapa="1ª etapa"]')
        page.wait_for_timeout(500)
        rel.passo("chip '1ª etapa' ativo", js("document.querySelector('#eChips [data-etapa=\"1ª etapa\"]').getAttribute('aria-pressed')") == "true")
        if info["pr"]:
            depois = js("__viz.PR[0].ef.reduce((a, b) => a + b, 0)")
            rel.passo("filtro esconde layers de outras etapas", depois < antes, f"{antes} -> {depois} layers visíveis")
        oculta = js("""() => { const c = Object.values(__viz.camadasMapa).find(c => c.etapa && c.etapa !== '1ª etapa'); return c ? !__viz.map.hasLayer(c.layer) : true; }""")
        rel.passo("filtro esconde manchas de outras etapas", bool(oculta))
        if info["escopo"]:
            linhas = js("document.querySelectorAll('#eTabelas details').length")
            rel.passo("tabela de escopo filtrada e agrupada", 0 < linhas < info["escopo"], f"{linhas} tabelas")
            # situação por item (salva no localStorage) e CSV
            page.locator("#eTabelas details > summary").first.click()
            sel = page.locator("#eTabelas select[data-k]").first
            sel.select_option("escopo")
            salvo = js("Object.keys(JSON.parse(localStorage.getItem('camadas:escopo:' + __viz.D.id) || '{}')).length")
            rel.passo("situação do item salva no localStorage", salvo >= 1)
            page.click("#eCsv")
            csv = page.input_value("#dlgTxt")
            rel.passo("CSV do escopo com ';' e vírgula decimal", csv.count("\n") > 3 and ";" in csv.splitlines()[0] and "No escopo" in csv, f"{csv.count(chr(10)) + 1} linhas")
            page.click("#dlgFechar")
        foto("03_etapas_escopo")
        page.click('#eChips [data-etapa=""]')   # volta para "Todas"
        page.click("#t-camadas")
        page.wait_for_timeout(300)

    # ---- 3) aba Pranchas: folha com textos e busca ----
    if "fu1" in info["pr"]:
        page.click("#t-pranchas")
        page.select_option("#pSel", "fu1")
        page.wait_for_function("window.__viz.FV.P && window.__viz.FV.P.id === 'fu1' && window.__viz.FV.P.pronta && window.__viz.FV.bmp", timeout=60000)
        page.wait_for_timeout(500)
        n = js(JS_PIXELS_FOLHA)
        rel.passo("folha fu1 desenhada", n > 3000, f"{n} pixels de traço")
        foto("04a_folha_fu1_inteira")
        termo = js("""() => { const t = __viz.PR.find(p => p.id === 'fu1').d.textos.find(t => /[A-Za-zÀ-ú]{4,}/.test(t.t)); return t ? t.t.match(/[A-Za-zÀ-ú]{4,}/)[0] : ''; }""")
        rel.passo("prancha fu1 tem texto pesquisável", bool(termo), termo)
        page.fill("#pBusca", termo)
        page.wait_for_selector("#pRes button", timeout=5000)
        achados = js("document.querySelectorAll('#pRes button').length")
        rel.passo("busca de texto lista resultados", achados >= 1, f"'{termo}': {achados}")
        page.locator("#pRes button").first.click()
        page.wait_for_timeout(300)
        rel.passo("clique no resultado centra e destaca o texto", js("__viz.FV.sel >= 0 && __viz.FV.s > __viz.FV.sFit * 1.4"))
        # medição na folha (dois cliques no palco) e identificação
        page.click("#pFMedir")
        box = page.locator("#fPalco").bounding_box()
        page.mouse.click(box["x"] + box["width"] * .35, box["y"] + box["height"] * .4)
        page.mouse.click(box["x"] + box["width"] * .6, box["y"] + box["height"] * .5)
        rel.passo("medição na folha calcula distância", "Distância" in page.inner_text("#pMed"), page.inner_text("#pMed").splitlines()[1] if page.inner_text("#pMed").count("\n") else "")
        page.click("#pFIdent")
        foto("04b_folha_fu1_busca_medida")
        page.click("#fVoltar")
        rel.passo("voltar ao mapa a partir da folha", js("document.querySelector('#folha').hidden"))

    # ---- 4) sondagens e fotos ----
    if info["sond"]:
        n = js("document.querySelectorAll('.snd-pin').length")
        rel.passo("marcadores de sondagem no mapa", n > 0, f"{n}")
        if n:
            html_pop = js("""() => { const i = Object.keys(window.__viz.marcaSnd)[0]; return window.__viz.htmlSondagem(__viz.D.sondagens[i]); }""")
            rel.passo("popup de sondagem com gráfico SVG", "<svg" in html_pop and "NSPT" in html_pop)
            page.evaluate("() => { const m = Object.values(window.__viz.marcaSnd)[0]; window.__viz.map.setView(m.getLatLng(), 20, {animate: false}); m.openPopup(); }")
            page.wait_for_timeout(900)   # o popup faz um auto-pan para caber no mapa
            foto("05_sondagem")
            page.keyboard.press("Escape")
    if info["fotos"]:
        page.evaluate("(n) => window.__viz.abrirFoto(n)", info["fotos"][0])
        page.wait_for_function("document.querySelector('#fotoImg').naturalWidth > 0", timeout=5000)
        rel.passo("foto do drone abre no diálogo", js("document.querySelector('#dlgFoto').open"))
        foto("06_foto")
        page.click("#fotoFechar")

    # ---- 5) 3D ----
    if info["tem3d"]:
        page.click("#b-3d")
        page.wait_for_function("window.__viz.v3 && window.__viz.v3.renderer", timeout=30000)
        page.wait_for_timeout(1500)
        n = js(JS_PIXELS_3D)
        rel.passo("3D: canvas WebGL desenhou (pixels não vazios)", n > 1500, f"{n} pixels")
        js("document.querySelector('.painel3d').open = true")   # no celular o painel começa recolhido
        page.select_option("#v3Cor", "altura")
        page.wait_for_timeout(800)
        n2 = js(JS_PIXELS_3D)
        rel.passo("3D: cor por altura redesenha", n2 > 1500, f"{n2} pixels")
        foto("07_3d_painel")
        js("document.querySelector('.painel3d').open = false")   # libera a nuvem para os cliques da medida
        # clique numa câmera (pirâmide) abre a foto: clica na primeira câmera visível fora do painel de controles
        if info["fotos"]:
            pos = js("""() => {
              const V = __viz.v3, cv = document.querySelector('#c3d');
              V.renderer.render(V.scene, V.camera);
              const r = cv.getBoundingClientRect(), p = document.querySelector('.painel3d').getBoundingClientRect(), ok = [];
              for (const m of V.camMalhas) {
                m.geometry.computeBoundingBox();
                const c = m.geometry.boundingBox.getCenter(new THREE.Vector3()).project(V.camera), x = r.left + (c.x + 1) / 2 * r.width, y = r.top + (1 - c.y) / 2 * r.height;
                const sobPainel = x >= p.left - 5 && x <= p.right + 5 && y >= p.top - 5 && y <= p.bottom + 5;
                if (c.z < 1 && x > r.left + 8 && x < r.right - 8 && y > r.top + 8 && y < r.bottom - 8 && !sobPainel) ok.push([x, y]);
              }
              return ok[0] || null;
            }""")
            if pos:
                page.mouse.click(pos[0], pos[1])
                page.wait_for_timeout(400)
                rel.passo("3D: clique na câmera abre a foto", js("document.querySelector('#dlgFoto').open"))
                foto("07_3d_camera_foto")
                if js("document.querySelector('#dlgFoto').open"):
                    page.click("#fotoFechar")
                page.click("#v3Reset")
            else:
                rel.passo("3D: alguma câmera visível para clicar", False)
        # medida 3D entre dois pontos da nuvem
        page.click("#v3Medir")
        box = page.locator("#c3d").bounding_box()
        for fx, fy in ((.45, .55), (.55, .62)):
            page.mouse.click(box["x"] + box["width"] * fx, box["y"] + box["height"] * fy)
            page.wait_for_timeout(300)
        txt = page.inner_text("#r3d")
        rel.passo("3D: medida entre dois pontos (distância e Δz)", "Δz" in txt, txt)
        page.click("#v3Medir")
        foto("07_3d")
        page.click("#v3Voltar")
        rel.passo("voltar do 3D ao mapa", js("document.querySelector('#vista3d').hidden"))
    else:
        rel.passo("sem modelo3d: botão 3D escondido", js("!document.querySelector('#b-3d')"))

    page.wait_for_timeout(300)
    rel.passo("sem rolagem horizontal ao final", js("document.documentElement.scrollWidth <= window.innerWidth + 1"))
    rel.passo("console sem erros", not erros, "; ".join(erros[:5]))
    browser.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("html", help="visualizador.html gerado (ex.: saida/foz/visualizador.html)")
    ap.add_argument("--capturas", help="pasta das capturas (padrão: <pasta do html>/capturas)")
    a = ap.parse_args()
    html = Path(a.html)
    if not html.exists():
        print(f"arquivo não encontrado: {html}", file=sys.stderr)
        return 2
    pasta = Path(a.capturas) if a.capturas else html.parent / "capturas"
    pasta.mkdir(parents=True, exist_ok=True)
    rel = Relatorio()
    t0 = time.time()
    with sync_playwright() as pw:
        for cen in CENARIOS:
            roteiro(pw, html, cen, pasta, rel)
    print(f"\n{rel.ok} verificações ok, {len(rel.falhas)} falha(s) em {time.time() - t0:.0f} s. Capturas em {pasta}")
    for f in rel.falhas:
        print("  - FALHOU:", f)
    return 1 if rel.falhas else 0


if __name__ == "__main__":
    sys.exit(main())
