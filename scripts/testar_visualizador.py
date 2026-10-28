#!/usr/bin/env python3
"""Teste de ponta a ponta do visualizador v2 + v3 (Chromium headless via Playwright).

Uso:
    python scripts/testar_visualizador.py saida/foz/visualizador.html [--capturas saida/foz/capturas]

Roda o roteiro duas vezes: desktop 1400x900 (tema claro) e celular 400x860 (tema escuro), e verifica:
  * console sem erros (falhas de rede para hosts externos — fontes, satélite — são esperadas offline e ignoradas);
  * a prancha "f004" ligada desenhando no mapa e o clique/snap sobre os traços;
  * o filtro de etapa ("1ª etapa") escondendo layers e manchas;
  * a aba Pranchas numa prancha com textos ("fu1"): folha desenhada e busca de texto;
  * a aba Etapas & escopo (situação por item salva, CSV, contagens, especificação e alertas vindos do Python, sem preço);
  * sondagens (popup com SVG), foto do drone e o 3D (canvas WebGL com pixels desenhados);
  * v3: árvore por disciplina, recorte classificado (intervenção), estacas no mapa e no 3D, marcos geodésicos
    e o 4D (linha do tempo, play, curva S);
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
JS_TODAS_PRONTAS = "__viz.PR.filter(p => p.mapa.on).every(p => p.pronta)"
JS_INFO = """() => ({pr: __viz.PR.map(p => p.id), tem3d: !!__viz.D.modelo3d, sond: (__viz.D.sondagens || []).length,
  fotos: Object.keys(__viz.D.fotos || {}), escopo: ((__viz.D.escopo || {}).itens || []).length, etapas: (__viz.D.etapas || []).map(e => e.id),
  grupos: __viz.D.grupos || {}, interv: (__viz.D.intervencoes || []).length, crono: !!__viz.D.cronograma,
  totais: (__viz.D.escopo || {}).totais || null})"""


def js(c: dict, expr: str, arg=None):
    return c["page"].evaluate(expr, arg) if arg is not None else c["page"].evaluate(expr)


def foto(c: dict, nome: str) -> None:
    c["page"].screenshot(path=str(c["pasta"] / f"{nome}_{c['tag']}.png"))


def passo(c: dict, nome: str, condicao: bool, detalhe: str = "") -> bool:
    return c["rel"].passo(nome, condicao, detalhe)


def abrir_pagina(pw, html: Path, cen: dict, pasta: Path, rel: Relatorio):
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
    page.on("crash", lambda *_: print("  !! a aba caiu (crash do renderizador, em geral memória)", flush=True))

    def console(m):
        if m.type != "error":
            return
        if "Failed to load resource" in m.text and (m.location.get("url") or "").startswith(("http://", "https://")):
            return   # fonte/satélite bloqueados de propósito
        erros.append(f"console.error: {m.text}")
    page.on("console", console)
    page.goto(html.resolve().as_uri())
    page.wait_for_function("window.__viz && document.querySelector('#mapa .leaflet-pane')", timeout=60000)
    page.wait_for_timeout(600)
    c = {"page": page, "rel": rel, "pasta": pasta, "tag": cen["nome"], "erros": erros, "browser": browser}
    c["info"] = js(c, JS_INFO)
    return c


def verificar_inicio(c: dict) -> None:
    info = c["info"]
    passo(c, "página carregou e o mapa foi criado", True, f"{len(info['pr'])} pranchas, {info['sond']} sondagens, 3D={info['tem3d']}")
    passo(c, "sem rolagem horizontal da página", js(c, "document.documentElement.scrollWidth <= window.innerWidth + 1"))
    foto(c, "01_inicio")


def verificar_mapa(c: dict) -> None:
    """Prancha f004 ligada no mapa, identificar e snap sobre um vértice real."""
    if "f004" not in c["info"]["pr"]:
        return
    page = c["page"]
    page.click("#t-camadas")
    page.check("#v-prancha-f004")
    page.wait_for_function("__viz.PR.find(p => p.id === 'f004').ultimoDesenho", timeout=60000)
    page.wait_for_timeout(500)
    n = js(c, JS_PIXELS_CANVAS, ".leaflet-pranchas-pane canvas")
    passo(c, "prancha f004 desenhada no mapa", n > 2000, f"{n} pixels")
    ms = js(c, "__viz.PR.find(p => p.id === 'f004').ultimoDesenho.ms")
    passo(c, "redesenho do mapa rápido (< 400 ms)", ms < 400, f"{ms:.0f} ms")
    r = js(c, """() => {
      const P = __viz.PR.find(p => p.id === 'f004'), k = P.lay.findIndex((li, i) => P.ef[li] && P.ini[i + 1] - P.ini[i] > 3);
      const j = P.ini[k] + 1, x = P.xy[2 * j], y = P.xy[2 * j + 1], ll = __viz.pt2ll(P, x, y), m = __viz.map;
      const alvo = m.containerPointToLatLng(m.latLngToContainerPoint(ll).add([3, 2]));
      const sn = __viz.snapMapa(alvo), pa = m.latLngToContainerPoint(alvo);
      // o ponto grudado é o vértice mais próximo do cursor: no máximo tão longe quanto o vértice de referência (3,6 px)
      return {ident: __viz.identificarPranchas(ll).length, snap: sn ? m.latLngToContainerPoint(sn.ll).distanceTo(pa) : -1};
    }""")
    passo(c, "identificar no mapa acha o traço", r["ident"] > 0, f"{r['ident']} resultado(s)")
    passo(c, "snap gruda num vértice a menos de 8 px do cursor", 0 <= r["snap"] <= 3.62, f"{r['snap']:.2f} px")
    foto(c, "02_mapa_f004")


def verificar_filtro_etapa(c: dict) -> None:
    info, page = c["info"], c["page"]
    if "1ª etapa" not in info["etapas"]:
        return
    page.click("#t-escopo")
    com_etapa = "__viz.PR.find(p => p.d.layers.some(l => l.classe))"     # a primeira prancha pode não ter etapa
    antes = js(c, f"{com_etapa} ? {com_etapa}.ef.reduce((a, b) => a + b, 0) : 0")
    page.click('#eChips [data-etapa="1ª etapa"]')
    page.wait_for_timeout(500)
    passo(c, "chip '1ª etapa' ativo", js(c, "document.querySelector('#eChips [data-etapa=\"1ª etapa\"]').getAttribute('aria-pressed')") == "true")
    if info["pr"]:
        depois = js(c, f"{com_etapa}.ef.reduce((a, b) => a + b, 0)")
        passo(c, "filtro esconde layers de outras etapas", depois < antes, f"{antes} -> {depois} layers visíveis")
    oculta = js(c, """() => { const c = Object.values(__viz.camadasMapa).find(c => c.etapa && c.etapa !== '1ª etapa'); return c ? !__viz.map.hasLayer(c.layer) : true; }""")
    passo(c, "filtro esconde manchas de outras etapas", bool(oculta))


def verificar_escopo_tabela(c: dict) -> None:
    page = c["page"]
    if not c["info"]["escopo"]:
        return
    linhas = js(c, "document.querySelectorAll('#eTabelas details').length")
    passo(c, "tabela de escopo filtrada e agrupada", 0 < linhas < c["info"]["escopo"], f"{linhas} tabelas")
    page.locator("#eTabelas details > summary").first.click()   # situação por item (salva no localStorage) e CSV
    page.locator("#eTabelas select[data-k]").first.select_option("escopo")
    salvo = js(c, "Object.keys(JSON.parse(localStorage.getItem('camadas:escopo:' + __viz.D.id) || '{}')).length")
    passo(c, "situação do item salva no localStorage", salvo >= 1)
    page.click("#eCsv")
    csv = page.input_value("#dlgTxt")
    passo(c, "CSV do escopo com ';' e vírgula decimal", csv.count("\n") > 3 and ";" in csv.splitlines()[0] and "No escopo" in csv, f"{csv.count(chr(10)) + 1} linhas")
    page.click("#dlgFechar")
    foto(c, "03_etapas_escopo")
    page.click('#eChips [data-etapa=""]')   # volta para "Todas"
    page.click("#t-camadas")
    page.wait_for_timeout(300)


def verificar_escopo_valores(c: dict) -> None:
    """Contagens e alertas vêm prontos do Python; o front só exibe. Sem preço: nenhum R$ na aba."""
    T, page = c["info"]["totais"], c["page"]
    if not T:
        return
    page.click("#t-escopo")
    page.fill("#eBusca", "")
    page.select_option("#eSit", "")
    page.wait_for_timeout(300)
    txt = page.text_content("#eTot")
    itens = f"{T['itens']:,}".replace(",", ".")
    passo(c, "escopo: contagens do contrato vêm do Python (sem filtro)", "Escopo do contrato" in txt and itens in txt, itens)
    aba = page.text_content("#aba-escopo")
    passo(c, "escopo: nenhum preço ou valor em R$", "R$" not in aba and "Valor" not in aba)
    n_cad = js(c, "[...document.querySelectorAll('#eTabelas .cod')].filter(e => e.textContent.startsWith('Cadastro Sanepar')).length")
    passo(c, "escopo: especificação do cadastro Sanepar por item", n_cad == T["no_cadastro"], f"{n_cad} de {T['no_cadastro']}")
    n_alerta = js(c, "document.querySelectorAll('#eTabelas tr[data-alerta]').length")
    passo(c, "escopo: itens com alerta destacados", n_alerta == T["com_alerta"] and js(c, "!!document.querySelector('.esc-alerta')"), f"{n_alerta} de {T['com_alerta']}")
    page.fill("#eBusca", "tubo")
    page.wait_for_timeout(400)
    txt = page.text_content("#eTot")
    passo(c, "escopo: com busca o rótulo vira 'Linhas visíveis'", "Linhas visíveis" in txt and "Escopo do contrato" not in txt)
    foto(c, "03b_escopo_busca")
    page.fill("#eBusca", "")
    page.click("#t-camadas")


def verificar_pranchas(c: dict) -> None:
    """Aba Pranchas: folha com textos, busca, medição e identificação."""
    page = c["page"]
    if "fu1" not in c["info"]["pr"]:
        return
    page.click("#t-pranchas")
    page.select_option("#pSel", "fu1")
    page.wait_for_function("window.__viz.FV.P && window.__viz.FV.P.id === 'fu1' && window.__viz.FV.P.pronta && window.__viz.FV.bmp", timeout=60000)
    page.wait_for_timeout(500)
    n = js(c, JS_PIXELS_FOLHA)
    passo(c, "folha fu1 desenhada", n > 3000, f"{n} pixels de traço")
    foto(c, "04a_folha_fu1_inteira")
    termo = js(c, """() => { const t = __viz.PR.find(p => p.id === 'fu1').d.textos.find(t => /[A-Za-zÀ-ú]{4,}/.test(t.t)); return t ? t.t.match(/[A-Za-zÀ-ú]{4,}/)[0] : ''; }""")
    passo(c, "prancha fu1 tem texto pesquisável", bool(termo), termo)
    page.fill("#pBusca", termo)
    page.wait_for_selector("#pRes button", timeout=5000)
    achados = js(c, "document.querySelectorAll('#pRes button').length")
    passo(c, "busca de texto lista resultados", achados >= 1, f"'{termo}': {achados}")
    page.locator("#pRes button").first.click()
    page.wait_for_timeout(300)
    passo(c, "clique no resultado centra e destaca o texto", js(c, "__viz.FV.sel >= 0 && __viz.FV.s > __viz.FV.sFit * 1.4"))
    medir_na_folha(c)


def medir_na_folha(c: dict) -> None:
    page = c["page"]
    page.click("#pFMedir")
    box = page.locator("#fPalco").bounding_box()
    page.mouse.click(box["x"] + box["width"] * .35, box["y"] + box["height"] * .4)
    page.mouse.click(box["x"] + box["width"] * .6, box["y"] + box["height"] * .5)
    med = page.inner_text("#pMed")
    passo(c, "medição na folha calcula distância", "Distância" in med, med.splitlines()[1] if med.count("\n") else "")
    page.click("#pFIdent")
    foto(c, "04b_folha_fu1_busca_medida")
    page.click("#fVoltar")
    passo(c, "voltar ao mapa a partir da folha", js(c, "document.querySelector('#folha').hidden"))


def verificar_sondagens_fotos(c: dict) -> None:
    page, info = c["page"], c["info"]
    if info["sond"]:
        n = js(c, "document.querySelectorAll('.snd-pin').length")
        passo(c, "marcadores de sondagem no mapa", n > 0, f"{n}")
        if n:
            html_pop = js(c, """() => { const i = Object.keys(window.__viz.marcaSnd)[0]; return window.__viz.htmlSondagem(__viz.D.sondagens[i]); }""")
            passo(c, "popup de sondagem com gráfico SVG", "<svg" in html_pop and "NSPT" in html_pop)
            page.evaluate("() => { const m = Object.values(window.__viz.marcaSnd)[0]; window.__viz.map.setView(m.getLatLng(), 20, {animate: false}); m.openPopup(); }")
            page.wait_for_timeout(900)   # o popup faz um auto-pan para caber no mapa
            foto(c, "05_sondagem")
            page.keyboard.press("Escape")
    if info["fotos"]:
        page.evaluate("(n) => window.__viz.abrirFoto(n)", info["fotos"][0])
        page.wait_for_function("document.querySelector('#fotoImg').naturalWidth > 0", timeout=5000)
        passo(c, "foto do drone abre no diálogo", js(c, "document.querySelector('#dlgFoto').open"))
        foto(c, "06_foto")
        page.click("#fotoFechar")


JS_POS_CAMERA = """() => {
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
}"""


def verificar_3d(c: dict) -> None:
    page = c["page"]
    if not c["info"]["tem3d"]:
        passo(c, "sem modelo3d: botão 3D escondido", js(c, "!document.querySelector('#b-3d')"))
        return
    page.click("#b-3d")
    page.wait_for_function("window.__viz.v3 && window.__viz.v3.renderer", timeout=30000)
    page.wait_for_timeout(1500)
    n = js(c, JS_PIXELS_3D)
    passo(c, "3D: canvas WebGL desenhou (pixels não vazios)", n > 1500, f"{n} pixels")
    js(c, "document.querySelector('.painel3d').open = true")   # no celular o painel começa recolhido
    page.select_option("#v3Cor", "altura")
    page.wait_for_timeout(800)
    n2 = js(c, JS_PIXELS_3D)
    passo(c, "3D: cor por altura redesenha", n2 > 1500, f"{n2} pixels")
    sn = js(c, """() => { const S = __viz.D.modelo3d.sondagens || [], im = __viz.v3.sond;
      return {n: S.length, inst: im ? im.count : 0, esperado: S.reduce((a, s) => a + s.segmentos.length + (s.z_na != null), 0),
              topo: S.every(s => Math.abs(s.segmentos[0].z_topo - s.z_boca) < 0.01 && Math.abs(s.segmentos.at(-1).z_base - s.z_fundo) < 0.01)}; }""")
    if sn["n"]:
        passo(c, "3D: sondagens em cota (segmentos + NA)", sn["inst"] == sn["esperado"] and sn["topo"], f"{sn['n']} furos, {sn['inst']} peças")
    so = js(c, """() => { const S = __viz.D.modelo3d.solidos || [], g = __viz.v3.solidos;
      return {n: S.length, pecas: g ? g.children.length : 0, cota: S.every(s => s.z1 > s.z0 && s.z0 > 200)}; }""")
    if so["n"]:
        passo(c, "3D: blocos da forma extrudados entre arrasamento e face superior", so["pecas"] == 2 * so["n"] and so["cota"], str(so))
    foto(c, "07_3d_painel")
    js(c, "document.querySelector('.painel3d').open = false")   # libera a nuvem para os cliques da medida
    clicar_camera_3d(c)
    medir_3d(c)


def clicar_camera_3d(c: dict) -> None:
    """Clique numa câmera (pirâmide) abre a foto: usa a primeira visível fora do painel de controles."""
    page = c["page"]
    if not c["info"]["fotos"]:
        return
    pos = js(c, JS_POS_CAMERA)
    if not pos:
        passo(c, "3D: alguma câmera visível para clicar", False)
        return
    page.mouse.click(pos[0], pos[1])
    page.wait_for_timeout(400)
    passo(c, "3D: clique na câmera abre a foto", js(c, "document.querySelector('#dlgFoto').open"))
    foto(c, "07_3d_camera_foto")
    if js(c, "document.querySelector('#dlgFoto').open"):
        page.click("#fotoFechar")
    page.click("#v3Reset")


def medir_3d(c: dict) -> None:
    page = c["page"]
    page.click("#v3Medir")
    box = page.locator("#c3d").bounding_box()
    for fx, fy in ((.45, .55), (.55, .62)):
        page.mouse.click(box["x"] + box["width"] * fx, box["y"] + box["height"] * fy)
        page.wait_for_timeout(300)
    txt = page.inner_text("#r3d")
    passo(c, "3D: medida entre dois pontos (distância e Δz)", "Δz" in txt, txt)
    page.click("#v3Medir")
    foto(c, "07_3d")
    page.click("#v3Voltar")
    passo(c, "voltar do 3D ao mapa", js(c, "document.querySelector('#vista3d').hidden"))


JS_CIVIL_VISIVEIS = """() => __viz.PR.reduce((n, P) => n + P.d.layers.filter((l, i) => l.grupo === 'Civil' && P.ef[i] && P.mapa.on).length, 0)"""


def verificar_v3_arvore(c: dict) -> None:
    """Árvore por disciplina: grupos, subgrupo Civil › Drenagem, e o liga/desliga de um grupo inteiro."""
    page, grupos = c["page"], c["info"]["grupos"]
    if not grupos:
        return
    page.click("#t-camadas")
    achados = [g for g in ("Civil", "Hidráulica", "Elétrica e automação") if js(c, "(g) => !!document.querySelector(`#aba-camadas .gd[data-g=\"${g}\"]`)", g)]
    passo(c, "árvore tem os grupos Civil, Hidráulica e Elétrica e automação", len(achados) == 3, ", ".join(achados))
    passo(c, "árvore tem o subgrupo Civil › Drenagem", js(c, "!!document.querySelector('#aba-camadas .sd[data-g=\"Civil\"][data-s=\"Drenagem\"]')"))
    passo(c, "prancha aparece em mais de um subgrupo (f006 em Drenagem e em Estrutura)",
          js(c, "document.querySelectorAll('#aba-camadas .pr-l[data-p=\"f006\"]').length") > 1)
    page.check('#aba-camadas .gd[data-g="Civil"] > summary .cb-esc')
    page.wait_for_function(JS_TODAS_PRONTAS, timeout=120000)
    page.wait_for_timeout(800)
    ligados = js(c, JS_CIVIL_VISIVEIS)
    passo(c, "ligar Civil mostra os layers do grupo no mapa", ligados > 50, f"{ligados} layers Civil visíveis")
    foto(c, "08_arvore_disciplina")
    desligar_civil(c)


def desligar_civil(c: dict) -> None:
    page = c["page"]
    page.uncheck('#aba-camadas .gd[data-g="Civil"] > summary .cb-esc')
    page.wait_for_timeout(500)
    passo(c, "desligar Civil esconde os layers do grupo", js(c, JS_CIVIL_VISIVEIS) == 0)
    solo = js(c, "__viz.PR.filter(P => P.d.layers.every(l => l.grupo === 'Civil')).every(P => !P.mapa.on)")
    passo(c, "desligar Civil desliga as pranchas só de Civil", bool(solo))
    passo(c, "f004 segue ligada (tem layers de Hidráulica)", js(c, "__viz.PR.find(p => p.id === 'f004').mapa.on"))


def desenhar_recorte(c: dict) -> None:
    """Ferramenta Recortar: três cliques no mapa e Enter fecham o polígono e abrem a escolha do tipo."""
    page = c["page"]
    page.click("#b-recorte")
    box = page.locator("#mapa").bounding_box()
    for fx, fy in ((.45, .45), (.62, .47), (.55, .63)):
        page.mouse.click(box["x"] + box["width"] * fx, box["y"] + box["height"] * fy)
        page.wait_for_timeout(120)
    page.keyboard.press("Enter")
    page.wait_for_selector("#dlgInterv[open]", timeout=5000)
    passo(c, "recorte: o polígono fechado pede o tipo de intervenção", js(c, "document.querySelectorAll('#intTipos button').length") == c["info"]["interv"])
    foto(c, "09a_recorte_escolha")


def verificar_v3_intervencao(c: dict) -> None:
    page = c["page"]
    if not c["info"]["interv"]:
        return
    page.click("#t-camadas")
    js(c, "__viz.map.closePopup()")   # popups abertos pelas seções anteriores cobririam os cliques no mapa
    page.click("#b-enquadrar")
    page.wait_for_timeout(500)
    desenhar_recorte(c)
    page.click('#intTipos button:has-text("Supressão vegetal (desmatamento)")')
    page.wait_for_timeout(300)
    page.click("#t-camadas")
    n = js(c, "document.querySelectorAll('#intLista .item').length")
    area = js(c, "parseFloat((document.querySelector('#intLista .item .v') || {textContent: '0'}).textContent.replace(/\\./g, '').replace(',', '.'))")
    passo(c, "recorte classificado entra na lista com área > 0", n == 1 and area > 0, f"{n} recorte(s), {area} m²")
    passo(c, "recorte guarda properties.intervencao", js(c, "__viz.anot.features.some(f => f.properties.intervencao === 'supressao')"))
    passo(c, "totais por tipo mostram o tipo escolhido", "Supressão vegetal" in js(c, "document.querySelector('#intTot').textContent"))
    passo(c, "resumo da supressão estimada por etapa no painel", js(c, "document.querySelectorAll('.int-resumo tr').length") >= 2)
    js(c, "document.querySelector('#intLista').scrollIntoView({block: 'center'})")
    page.wait_for_timeout(300)
    foto(c, "09_recorte_intervencao")
    page.click("#b-navegar")


def verificar_v3_estacas_mapa(c: dict) -> None:
    page = c["page"]
    if not js(c, "__viz.ESTACAS.length"):
        return
    page.check("#v-estacas")
    page.evaluate("() => { const L2 = __viz.camadasMapa.estacas.layer; __viz.map.fitBounds(L2.getBounds().pad(.3), {animate: false}); }")
    page.wait_for_timeout(500)
    r = js(c, """() => {
      const E = __viz.ESTACAS, a = E.find(e => e.d === 40), b = E.find(e => e.d === 50), g = __viz.camadasMapa.estacas.layer;
      return {n: E.length, naMapa: __viz.map.hasLayer(g), paths: E.filter(e => e.marker._path).length, ra: a.marker.getRadius(), rb: b.marker.getRadius()};
    }""")
    passo(c, "estacas no mapa (círculos)", r["naMapa"] and r["paths"] == r["n"], f"{r['paths']} de {r['n']}")
    passo(c, "raio proporcional ao diâmetro (50 cm > 40 cm)", r["rb"] > r["ra"], f"{r['ra']:.2f} px × {r['rb']:.2f} px")
    page.evaluate("() => { const e = __viz.ESTACAS[0]; __viz.map.setView(e.ll, 21, {animate: false}); e.marker.openPopup(); }")
    page.wait_for_timeout(500)
    passo(c, "clique na estaca mostra os atributos", "Diâmetro" in js(c, "document.querySelector('.leaflet-popup-content').textContent"))
    foto(c, "10_estacas_mapa")
    page.keyboard.press("Escape")


def verificar_v3_estacas_3d(c: dict) -> None:
    page = c["page"]
    if not c["info"]["tem3d"] or not js(c, "__viz.ESTACAS.length"):
        return
    page.click("#b-3d")
    page.wait_for_function("window.__viz.v3 && window.__viz.v3.estacas", timeout=30000)
    page.click("#v3Topo")   # de cima os cilindros aparecem como círculos: bom para contar pixels
    js(c, "document.querySelector('.painel3d').open = false")
    page.wait_for_timeout(800)
    com = js(c, JS_PIXELS_3D)
    js(c, "(() => { __viz.v3.estacas.visible = false; })()")
    sem = js(c, JS_PIXELS_3D)
    js(c, "(() => { __viz.v3.estacas.visible = true; })()")
    passo(c, "estacas no 3D (cilindros desenham pixels)", com > sem + 50, f"{com} px com, {sem} px sem")
    passo(c, "3D tem uma instância por estaca", js(c, "__viz.v3.estacas.count === __viz.ESTACAS.length"))
    page.click("#v3Reset")   # vista oblíqua: mostra o comprimento das estacas
    page.wait_for_timeout(500)
    foto(c, "11_estacas_3d")
    page.click("#v3Voltar")


def verificar_v3_marcos(c: dict) -> None:
    page = c["page"]
    if not js(c, "!!__viz.camadasMapa.marcos"):
        return
    js(c, "__viz.map.closePopup()")
    page.evaluate("() => { __viz.map.fitBounds(__viz.camadasMapa.marcos.layer.getBounds().pad(.1), {animate: false}); }")
    page.wait_for_timeout(600)
    destr = js(c, "__viz.camadasMapa.marcos.layer.getLayers().filter(m => m.getPopup().getContent().includes('DESTRUÍDO')).length")
    passo(c, "marcos geodésicos: triângulos no mapa", js(c, "document.querySelectorAll('.marco-pin').length") >= 20)
    passo(c, "marcos destruídos em vermelho (conferência com a situação)", js(c, "document.querySelectorAll('.marco-pin.destruido').length") == destr, f"{destr} destruído(s)")
    # furos e marcos podem coincidir no zoom geral: abre o popup pela API em vez de clicar no ícone
    page.evaluate("() => __viz.camadasMapa.marcos.layer.getLayers()[0].openPopup()")
    page.wait_for_selector(".leaflet-popup-content", timeout=3000)
    txt = page.inner_text(".leaflet-popup-content")
    passo(c, "marco: popup com nome, rede, situação e distância à obra", all(k in txt for k in ("Situação", "Distância à obra", "Classificação")), txt.splitlines()[0])
    foto(c, "12_marcos")
    page.keyboard.press("Escape")


def verificar_projeto(c: dict) -> None:
    """Aba Projeto: inventário (soma = listagem), cavas (escavação e reaterro) e valas (uma tabela por rede)."""
    page = c["page"]
    if not js(c, "!!(__viz.D.inventario || __viz.D.escavacao || __viz.D.valas || __viz.D.fichas)"):
        return
    page.click("#t-info")
    page.wait_for_timeout(300)
    if js(c, "!!__viz.D.inventario"):
        r = js(c, """() => { const I = __viz.D.inventario, s = I.resumo.reduce((a, l) => a + l.total, 0);
          return {soma: s, pdfs: I.totais.pdfs, itens: I.itens.length, nota: document.querySelector('#invLista .nota-l').textContent}; }""")
        passo(c, "inventário: soma do resumo = PDFs da listagem = itens", r["soma"] == r["pdfs"] == r["itens"], str(r))
        page.select_option("#invTipo", "planta")
        page.wait_for_timeout(200)
        n = js(c, "document.querySelectorAll('#invLista .inv-i').length")
        passo(c, "inventário: filtro por plantas", n == js(c, "__viz.D.inventario.totais.planta"), f"{n} plantas")
        page.select_option("#invTipo", "")
    if js(c, "!!__viz.D.escavacao"):
        r = js(c, """() => ({linhas: document.querySelectorAll('#escTab tbody tr').length, cavas: __viz.D.escavacao.cavas.length,
          total: document.querySelector('#escTab tbody tr:last-child td:nth-child(2)').textContent,
          esperado: __viz.D.escavacao.total.escavacao_m3, mapa: !!__viz.camadasMapa.escavacao})""")
        passo(c, "escavação: uma linha por cava + total", r["linhas"] == r["cavas"] + 1 and r["mapa"], str(r))
        passo(c, "escavação: total exibido = total do Python",
              float(r["total"].replace(".", "").replace(",", ".")) == round(r["esperado"]), r["total"])
    if js(c, "!!__viz.D.valas"):
        r = js(c, """() => { const V = __viz.D.valas, ok = V.redes.every(r => Math.abs(r.quadro.reduce((s, q) => s + q.extensao_m, 0) - r.extensao_m) < 1);
          const l = __viz.camadasMapa.valas.layer.getLayers()[0];
          return {redes: V.redes.length, h3: [...document.querySelectorAll('#aba-info h3')].length, ok, cor: l.options.color === l.feature.properties.cor}; }""")
        passo(c, "valas: uma tabela por rede, extensão por classe soma a da rede", r["redes"] == r["h3"] and r["ok"], str(r))
        passo(c, "valas: no mapa, cada trecho na cor da classe", r["cor"])
    if js(c, "!!(__viz.D.fichas && __viz.D.fichas.length)"):
        r = js(c, """() => { const F = __viz.D.fichas, h = F.find(f => f.piloto === 'hidraulica'), e = F.find(f => f.piloto === 'estrutura');
          return {fichas: document.querySelectorAll('details.ficha').length, n: F.length,
                  baloes: h ? h.baloes.every(b => b.item) : true, est: e ? e.encaixe.inliers === e.estacas : true,
                  camadas: [...document.querySelectorAll('ol.camadas-ficha')].every(o => o.querySelectorAll(':scope > li').length >= 3),
                  mapa: e ? !!__viz.camadasMapa.blocos_forma : true}; }""")
        passo(c, "fichas: uma por prancha piloto, em camadas de entendimento", r["fichas"] == r["n"] and r["camadas"], str(r))
        passo(c, "fichas: balões todos ligados a item; estacas todas encaixadas; blocos no mapa", r["baloes"] and r["est"] and r["mapa"], str(r))
    foto(c, "16_projeto")
    page.click("#t-camadas")
    page.wait_for_timeout(300)


def ir_ao_dia(c: dict, dia: int) -> None:
    """Usa o próprio controle da linha do tempo (evento input do range). Espera dois quadros com prazo largo: no
    Chromium sem GPU (swiftshader), com o WebGL do 3D vivo e 34 canvases, o primeiro quadro do 4D já levou 42 s,
    com a CPU ociosa — demora de composição do ambiente de teste, não do código (o mesmo passo também deu 0,6 s)."""
    js(c, "(d) => { const r = document.querySelector('#b4Dia'); r.value = d; r.dispatchEvent(new Event('input', {bubbles: true})); }", dia)
    c["page"].wait_for_function("new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r(true))))",
                                timeout=180000)
    c["page"].wait_for_timeout(300)


def verificar_v3_4d_abrir(c: dict) -> None:
    page = c["page"]
    js(c, "__viz.map.closePopup()")
    page.click("#b-enquadrar")
    page.wait_for_timeout(500)
    page.click("#b-4d")
    page.wait_for_function(JS_TODAS_PRONTAS, timeout=180000)
    passo(c, "4D: barra da linha do tempo aberta", js(c, "!document.querySelector('#bar4d').hidden"))
    passo(c, "4D: aviso de data da OS hipotética", js(c, "!document.querySelector('#b4Aviso').hidden") == bool(js(c, "__viz.D.cronograma.data_os_hipotese")))
    passo(c, "4D: marcos MI na linha do tempo", js(c, "document.querySelectorAll('#b4Marcos button').length") == js(c, "__viz.D.cronograma.marcos.length"))
    passo(c, "4D: curva S desenhada em SVG", js(c, "document.querySelectorAll('#b4Curva polyline').length") == 1)
    ini = js(c, "document.querySelector('#b4Data').textContent")
    page.fill("#b4Os", "2027-03-01")
    passo(c, "4D: trocar a data da OS muda só o rótulo", js(c, "document.querySelector('#b4Data').textContent") != ini and js(c, "__viz.F4.dia") == 0)


def verificar_v3_4d_dia100(c: dict) -> None:
    ir_ao_dia(c, 100)
    exec_ = c["page"].inner_text("#b4Exec")
    passo(c, "4D dia 100: A04 e A05 em execução, A08 fora da lista", "A04" in exec_ and "A05" in exec_ and "A08" not in exec_)
    r = js(c, """() => {
      const f8 = __viz.PR.find(p => p.id === 'f008'), fu = __viz.PR.find(p => p.id === 'fu1'), E = __viz.ESTACAS;
      const g = __viz.camadasMapa.estacas.layer, ac = E.find(e => e.id.startsWith('ACT360')), fi = E.find(e => e.id.startsWith('FILTROS'));
      return {a08: f8.f4d.every(v => v === 1) && f8.ef.every(v => v === 0), a05: fu.f4d.some(v => v === 2),
        estOk: ac.f4 === 2 && fi.f4 === 1 && !g.hasLayer(fi.marker) && g.hasLayer(ac.marker), pct: document.querySelector('#b4Pct').textContent};
    }""")
    passo(c, "4D dia 100: elementos da A08 ocultos", r["a08"])
    passo(c, "4D dia 100: elementos da A05 destacados", r["a05"])
    passo(c, "4D dia 100: estacas ACT360 destacadas e FILTROS ocultas no mapa", r["estOk"])
    esperado = js(c, "__viz.D.cronograma.curva_s.planejado_pct[__viz.D.cronograma.curva_s.dia.indexOf(100)]")
    pct = float(r["pct"].replace("%", "").replace(",", ".").strip())
    passo(c, "4D dia 100: % planejado confere com a curva S", abs(pct - esperado) < .06, f"{pct} % × {esperado} %")
    foto(c, "13_4d_dia100")


def verificar_v3_4d_3d(c: dict) -> None:
    """No 3D as estacas seguem a mesma regra (escala zero = oculta; cor laranja = em execução)."""
    if not js(c, "!!(__viz.v3 && __viz.v3.estacas)"):
        return
    r = js(c, """() => {
      const im = __viz.v3.estacas, m = new THREE.Matrix4(), cor = new THREE.Color(), E = __viz.ESTACAS;
      const i = E.findIndex(e => e.id.startsWith('FILTROS')), j = E.findIndex(e => e.id.startsWith('ACT360'));
      im.getMatrixAt(i, m); const sx = m.elements[0]; im.getColorAt(j, cor);
      return {sx, laranja: cor.r > .9 && cor.g > .3 && cor.g < .6 && cor.b < .1};
    }""")
    passo(c, "4D dia 100: no 3D a estaca FILTROS some e a ACT360 fica laranja", r["sx"] == 0 and r["laranja"], str(r))


def verificar_v3_4d_dias(c: dict) -> None:
    ir_ao_dia(c, 400)
    exec_ = c["page"].inner_text("#b4Exec")
    passo(c, "4D dia 400: A10 e A11 em execução", "A10" in exec_ and "A11" in exec_ and "A04" not in exec_)
    foto(c, "14_4d_dia400")
    ir_ao_dia(c, 600)
    r = js(c, "({oculto: __viz.PR.some(P => P.f4d.some(v => v === 1)) || __viz.ESTACAS.some(e => e.f4 === 1), exec: document.querySelector('#b4Exec').textContent})")
    passo(c, "4D dia 600: 1ª etapa concluída, nada oculto (só a B01, da 2ª etapa, em execução)", not r["oculto"] and "B01" in r["exec"] and "A13" not in r["exec"])
    foto(c, "15_4d_dia600")


def verificar_v3_4d_play(c: dict) -> None:
    page = c["page"]
    ir_ao_dia(c, 0)
    page.click("#b4Play")
    page.wait_for_timeout(1000)
    dia = js(c, "__viz.F4.dia")
    passo(c, "4D: play por 1 s avança os dias", dia > 0, f"dia {dia}")
    page.click("#b4Play")
    passo(c, "4D: pausa", js(c, "document.querySelector('#b4Play').getAttribute('aria-pressed')") == "false")


def verificar_v3_4d_sair(c: dict) -> None:
    page = c["page"]
    page.click("#b4Fechar")
    page.wait_for_timeout(500)
    r = js(c, """() => ({f4d: __viz.PR.every(P => P.f4d.every(v => v === 0)), est: __viz.ESTACAS.every(e => e.f4 === 0),
      vet: Object.values(__viz.camadasMapa).every(c => !c.f4), f004: __viz.PR.find(p => p.id === 'f004').mapa.on, barra: document.querySelector('#bar4d').hidden})""")
    passo(c, "4D: ao sair, tudo volta ao estado anterior", r["f4d"] and r["est"] and r["vet"] and r["f004"] and r["barra"], str(r))


def verificar_final(c: dict) -> None:
    c["page"].wait_for_timeout(300)
    passo(c, "sem rolagem horizontal ao final", js(c, "document.documentElement.scrollWidth <= window.innerWidth + 1"))
    passo(c, "console sem erros", not c["erros"], "; ".join(c["erros"][:5]))
    c["browser"].close()


def roteiro(pw, html: Path, cen: dict, pasta: Path, rel: Relatorio) -> None:
    c = abrir_pagina(pw, html, cen, pasta, rel)
    for secao in (verificar_inicio, verificar_mapa, verificar_filtro_etapa, verificar_escopo_tabela, verificar_escopo_valores,
                  verificar_pranchas, verificar_sondagens_fotos, verificar_3d, verificar_v3_arvore, verificar_v3_intervencao,
                  verificar_v3_estacas_mapa, verificar_v3_estacas_3d, verificar_v3_marcos, verificar_projeto):
        secao(c)
    if c["info"]["crono"]:
        for secao in (verificar_v3_4d_abrir, verificar_v3_4d_dia100, verificar_v3_4d_3d, verificar_v3_4d_dias, verificar_v3_4d_play, verificar_v3_4d_sair):
            secao(c)
    verificar_final(c)


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
