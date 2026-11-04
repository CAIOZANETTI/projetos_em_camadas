#!/usr/bin/env python3
"""Teste de ponta a ponta do visualizador v2 + v3 (Chromium headless via Playwright).

Uso:
    python scripts/testar_visualizador.py saida/foz/foz-vilac_camadas_v0.14.0_2026-10-29.html [--capturas saida/foz/capturas]

Roda o roteiro duas vezes: desktop 1400x900 (tema claro) e celular 400x860 (tema escuro), e verifica:
  * console sem erros (falhas de rede para hosts externos — fontes, satélite — são esperadas offline e ignoradas);
  * a prancha "f004" ligada desenhando no mapa e o clique/snap sobre os traços;
  * o filtro de etapa ("1ª etapa") escondendo layers e manchas;
  * a aba Pranchas numa prancha com textos ("fu1"): folha desenhada e busca de texto;
  * a aba Etapas & escopo (situação por item salva, CSV, contagens, especificação e alertas vindos do Python, sem preço);
  * sondagens (popup com SVG), foto do drone e o 3D (canvas WebGL com pixels desenhados);
  * v3: árvore por disciplina, recorte classificado (intervenção), estacas no mapa e no 3D, marcos geodésicos;
  * aba Obra (só com `D.construtivos`): é a primeira aba e abre ao carregar; busca por rótulo/classe/sistema, árvore por
    unidade, clique que enquadra e destaca um único elemento, ficha (só no painel) com atributos e fonte como link,
    popup do mapa mínimo, trecho de rede como linha vetorial clicável; e, com `construtivos.escopo`: resumo
    dentro/fora/a definir, filtro "Só o escopo", escolha por sistema (localStorage, exportar/restaurar), decomposição
    construtiva com evidências em link e partes com geometria enquadradas no mapa; sistemas sem elemento de geometria;
    desenhos da Relação por sistema (entregue com link, não entregue com alerta), resumo geral e atalho "Só com desenho não entregue";
  * Contrato 211 (aba EAP, só com `D.contrato_211`): título, uma linha por linha do Python, sem "R$" e sem rolagem
    horizontal da página;
  * aba EAP com vista (só com `D.eap_vista`): painel largo (>= 900 px no desktop, largura total no celular), uma sub-aba por
    seção e uma seção visível por vez, WBS recolhida com menos de 3 000 px, busca e chips de situação (WBS e Contrato 211),
    abrir linha do contrato mostra o detalhe, links folha <-> linha do contrato, "ver no mapa" e "abrir prancha" (quando a
    linha traz redes/pranchas), sem "R$" e sem rolagem horizontal;
  * sem rolagem horizontal da página no celular.
Sai com código 1 se algum passo falhar. Capturas em PNG na pasta indicada (padrão: <pasta do html>/capturas).
Requer apenas `playwright` (já com o Chromium instalado); não instala nada.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import unicodedata
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
  grupos: __viz.D.grupos || {}, interv: (__viz.D.intervencoes || []).length,
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
      // vértice de uma parte desenhada no mapa: layer ligado, > 3 pontos e dentro do recorte do mapa (clip_mapa)
      const P = __viz.PR.find(p => p.id === 'f004'), c = P.d.clip_mapa || [-Infinity, -Infinity, Infinity, Infinity];
      const k = P.lay.findIndex((li, i) => { const x = P.xy[2 * (P.ini[i] + 1)], y = P.xy[2 * (P.ini[i] + 1) + 1];
        return P.ef[li] && P.ini[i + 1] - P.ini[i] > 3 && x >= c[0] && x <= c[2] && y >= c[1] && y <= c[3]; });
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


def verificar_area_obra(c: dict) -> None:
    """Ortofoto do drone só na área da obra (o retângulo da base cabe nela + 2 px) e satélite limitado à obra."""
    if not js(c, "!!__viz.D.area_obra"):
        return
    r = js(c, """() => { const D = __viz.D, b = D.bases[0], xs = D.area_obra.utm.map(p => p[0]), ys = D.area_obra.utm.map(p => p[1]);
      const e0 = b.m[2], n1 = b.m[5], e1 = e0 + b.w * b.m[0], n0 = n1 - b.h * b.m[0], s = __viz.camadasMapa.satelite;
      const t = 2 * b.m[0];   // 2 px: arredondamento da rasterização do polígono
      return {cabe: e0 >= Math.min(...xs) - t && e1 <= Math.max(...xs) + t && n0 >= Math.min(...ys) - t && n1 <= Math.max(...ys) + t,
              limites: !s || !!s.layer.options.bounds, contorno: !!__viz.camadasMapa.area_obra}; }""")
    passo(c, "área da obra: ortofoto recortada nela, satélite só na extensão da obra", r["cabe"] and r["limites"] and r["contorno"], str(r))

def sem_acento_maiusculo(txt: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", txt) if not unicodedata.combining(ch)).upper()


JS_OBRA_ALVOS = """() => { const it = __viz.obra.itens, C = __viz.D.construtivos, geom = k => (C.classes[k] || {}).geometria;
  const pilar = it.find(i => i.classe === 'pilar' && i.rotulo.toUpperCase() === 'P5') || it.find(i => i.classe === 'pilar') || it[0];
  const ponto = it.find(i => geom(i.classe) === 'ponto'), linha = it.find(i => geom(i.classe) === 'linha'), cont = {};
  it.forEach(i => { cont[i.classe] = (cont[i.classe] || 0) + 1; });
  const maior = Object.entries(cont).sort((a, b) => b[1] - a[1])[0][0];
  return {pilar: pilar.rotulo, classe: pilar.classe, ponto: ponto ? ponto.rotulo : null, maior: (C.classes[maior] || {}).nome || maior,
    linha: linha ? linha.id : null, termoLinha: it.some(i => /AAT06/i.test(i.sisNome + ' ' + i.rotulo)) ? 'AAT06' : (linha ? linha.sisNome : null),
    classeLinha: linha ? linha.classe : null}; }"""
JS_OBRA_SELECAO = """() => { const o = __viz.obra, lay = o.camada.get(o.sel), it = o.itens.find(i => i.id === o.sel), C = __viz.D.construtivos;
  const b = lay.getBounds ? lay.getBounds().pad(.02) : L.latLngBounds([lay.getLatLng(), lay.getLatLng()]).pad(.02), c = __viz.map.getCenter();
  const num = ((it.f.properties.atributos || []).map(a => a[1]).find(v => typeof v === 'number' && !Number.isInteger(v)));
  return {sel: o.sel, dentro: b.contains(c) || (!lay.getBounds && c.distanceTo(lay.getLatLng()) < .5), zoom: __viz.map.getZoom(), aneis: o.halo.getLayers().length,
    ligada: __viz.map.hasLayer(__viz.camadasMapa.construtivos.layer), caixas: [document.querySelector('#obMapa').checked, document.querySelector('#v-construtivos').checked],
    ficha: document.querySelector('#obFicha').textContent, popup: (document.querySelector('.leaflet-popup-content') || {}).textContent || '',
    popTabelas: document.querySelectorAll('.leaflet-popup-content table').length, sisNome: it.sisNome, fichaTabelas: document.querySelectorAll('#obFicha table').length,
    popBotao: [...document.querySelectorAll('.leaflet-popup-content button')].some(b => /ver ficha/i.test(b.textContent)),
    classe: C.classes[it.classe].nome, rotulo: it.rotulo, num: num == null ? null : num.toLocaleString('pt-BR', {maximumFractionDigits: 3}),
    cores: [...o.camada.values()].every(l => { const k = C.classes[l.feature.properties.classe]; return !k || l.options[l.feature.geometry.type === 'Point' ? 'fillColor' : 'color'] === k.cor; })}; }"""


def verificar_obra_abertura(c: dict) -> None:
    """A aba Obra é a primeira e vem aberta ao carregar; entrega as demais seções à aba Camadas, como sempre foi."""
    if not js(c, "!!(__viz.D.construtivos && __viz.obra)"):
        return
    r = js(c, """() => { const t = [...document.querySelectorAll('.abas button:not([hidden])')];
      return {primeira: t[0].id, sel: t[0].getAttribute('aria-selected'), obra: !document.querySelector('#aba-obra').hidden,
              outras: t.slice(1).every(b => b.getAttribute('aria-selected') === 'false'), camadas: document.querySelector('#aba-camadas').hidden}; }""")
    passo(c, "obra: é a primeira aba e abre ao carregar; as demais ficam como secundárias",
          r["primeira"] == "t-obra" and r["sel"] == "true" and r["obra"] and r["outras"] and r["camadas"], str(r))
    foto(c, "00_obra_aberta")
    c["page"].click("#t-camadas")


def verificar_obra(c: dict) -> None:
    """Aba Obra (só com `D.construtivos`): escopo por sistema, árvore, busca, ficha/popup, fonte, decomposição e trecho de rede."""
    page = c["page"]
    if not js(c, "!!(__viz.D.construtivos && __viz.obra)"):
        return
    js(c, "__viz.map.closePopup()")
    page.click("#b-navegar")
    passo(c, "obra: aba Obra visível; camada no grupo Obra, desligada até selecionar",
          js(c, "!document.querySelector('#t-obra').hidden && __viz.camadasMapa.construtivos.grupo === 'Obra' && !__viz.map.hasLayer(__viz.camadasMapa.construtivos.layer)"))
    page.click("#t-obra")
    escopo = js(c, "!!__viz.obra.ES")
    passo(c, "obra: dados com escopo por sistema (D.construtivos.escopo)", escopo)
    if escopo:
        obra_escopo(c)
        obra_escopo_alternar(c)
        page.uncheck("#obSoEscopo")   # os passos abaixo olham todos os sistemas, também os de fora
    obra_arvore(c)
    alvos = obra_busca(c)
    obra_selecao(c, alvos)
    if escopo:
        obra_fonte(c)
        obra_decomposicao(c)
        obra_sem_geometria(c)
        obra_desenhos(c)
        obra_desenhos_filtro(c)
    obra_linha(c, alvos)
    obra_fim(c, alvos)
    js(c, "__viz.obra.definirSoEscopo(true)")   # volta ao padrão


JS_ESCOPO_ESTADO = """() => { const o = __viz.obra, E = o.ES.sistemas, ids = [...document.querySelectorAll('#obArvore .ob-sis')].map(d => d.dataset.sis);
  const cont = {dentro: 0, fora: 0, 'a definir': 0}; ids.forEach(i => cont[(E[i] || {}).estado || 'a definir']++);
  const chips = Object.fromEntries([...document.querySelectorAll('#obResumo .ob-chip')].map(x => [x.dataset.e, +x.querySelector('b').textContent]));
  return {cont, chips, total: ids.length, resumo: o.resumo()}; }"""
JS_ESCOPO_SISTEMA = """(id) => { const o = __viz.obra, g = __viz.camadasMapa.construtivos.layer, its = o.itens.filter(i => i.sis === id), d = document.querySelector('.ob-sis[data-sis="' + id + '"]');
  const l = its.length ? o.camada.get(its[0].id) : null, cb = d.querySelector('.ob-esc-cb');
  return {n: its.length, noMapa: its.filter(i => g.hasLayer(o.camada.get(i.id))).length, opac: parseFloat(getComputedStyle(d.querySelector('.ob-sis-h')).opacity),
          estilo: l ? (l.options.fillOpacity !== undefined && l.options.fill !== false ? l.options.fillOpacity : l.options.opacity) : null,
          marcado: cb.checked, indef: cb.indeterminate, orig: d.querySelector('.ob-orig').textContent, estado: d.dataset.escopo, rotulo: its.length ? its[0].rotulo : null,
          achados: its.length ? o.buscar(its[0].rotulo).filter(i => i.sis === id).length : 0, alterado: d.dataset.alterado === '1',
          altVisivel: !d.querySelector('.ob-alt-l').hidden, altTexto: d.querySelector('.ob-alt-l').textContent}; }"""


def obra_escopo(c: dict) -> None:
    """Resumo no topo e filtro "Só o escopo" (ligado por padrão): sistema fora fica esmaecido na árvore e some do mapa e da busca."""
    page = c["page"]
    r = js(c, JS_ESCOPO_ESTADO)
    passo(c, "obra/escopo: resumo no topo (dentro / fora / a definir) bate com os dados",
          r["chips"] == r["cont"] == {k: r["resumo"][k] for k in r["cont"]} and sum(r["cont"].values()) == r["total"] > 0, f"{r['chips']}")
    passo(c, "obra/escopo: filtro 'Só o escopo' vem ligado", js(c, "document.querySelector('#obSoEscopo').checked && __viz.obra.soEscopo"))
    ids = js(c, """() => { const E = __viz.obra.ES.sistemas, ids = [...document.querySelectorAll('#obArvore .ob-sis')].map(d => d.dataset.sis);
      return {fora: ids.find(i => (E[i] || {}).estado === 'fora') || null, dentro: ids.find(i => (E[i] || {}).estado === 'dentro' && __viz.obra.itens.some(x => x.sis === i)) || null,
              definir: ids.find(i => ((E[i] || {}).estado || 'a definir') === 'a definir') || null}; }""")
    if ids["fora"]:
        r = js(c, JS_ESCOPO_SISTEMA, ids["fora"])
        passo(c, "obra/escopo: sistema fora aparece na árvore, esmaecido e desmarcado, com a origem e o motivo",
              r["opac"] < 1 and not r["marcado"] and not r["indef"] and r["estado"] == "fora" and "fora" in r["orig"] and len(r["orig"]) > 8, f"{ids['fora']}: {r['orig']}")
        passo(c, "obra/escopo: com 'Só o escopo' o sistema fora some do mapa e da busca",
              r["n"] > 0 and r["noMapa"] == 0 and r["achados"] == 0, f"{r['n']} elementos, {r['noMapa']} no mapa")
        page.fill("#obBusca", r["rotulo"])
        nota = js(c, "document.querySelector('#obRes .nota-l').textContent")
        passo(c, "obra/escopo: a busca avisa dos resultados ocultos pelo filtro", "fora do escopo" in nota and "Só o escopo" in nota, nota)
        page.fill("#obBusca", "")
        page.uncheck("#obSoEscopo")
        r2 = js(c, JS_ESCOPO_SISTEMA, ids["fora"])
        passo(c, "obra/escopo: sem o filtro os elementos voltam ao mapa, esmaecidos",
              r2["noMapa"] == r2["n"] and r2["estilo"] is not None and r2["estilo"] < .3 and r2["achados"] > 0, f"opacidade {r2['estilo']}")
        page.check("#obSoEscopo")
    if ids["dentro"]:
        r = js(c, JS_ESCOPO_SISTEMA, ids["dentro"])
        passo(c, "obra/escopo: sistema dentro marcado, sem esmaecer, no mapa e na busca",
              r["marcado"] and r["opac"] == 1 and r["noMapa"] == r["n"] and r["achados"] > 0 and r["estado"] == "dentro", f"{ids['dentro']}: {r['orig']}")
    if ids["definir"]:
        r = js(c, JS_ESCOPO_SISTEMA, ids["definir"])
        passo(c, "obra/escopo: sistema 'a definir' aparece indeterminado, visível no mapa", r["indef"] and r["noMapa"] == r["n"], ids["definir"])
    foto(c, "18_obra_escopo")


def storage_ok(c: dict) -> bool:
    return js(c, "(() => { try { localStorage.setItem('__t', '1'); localStorage.removeItem('__t'); return true; } catch (e) { return false; } })()")


def obra_escopo_alternar(c: dict) -> None:
    """Alterar o escopo de um sistema muda o resumo e o mapa, persiste (localStorage), exporta em JSON e restaura; sem storage funciona."""
    import json
    page = c["page"]
    js(c, "__viz.obra.restaurar()")
    alvo = js(c, "() => [...document.querySelectorAll('#obArvore .ob-sis')].map(d => d.dataset.sis).find(i => __viz.obra.estado(i) === 'dentro' && __viz.obra.itens.some(x => x.sis === i))")
    if not alvo:
        return
    antes = js(c, JS_ESCOPO_ESTADO)
    page.locator(f'.ob-sis[data-sis="{alvo}"] .ob-esc-cb').click()
    depois = js(c, JS_ESCOPO_ESTADO)
    r = js(c, JS_ESCOPO_SISTEMA, alvo)
    passo(c, "obra/escopo: desmarcar 'No escopo' muda o resumo (dentro -1, fora +1) e o mapa",
          depois["chips"]["dentro"] == antes["chips"]["dentro"] - 1 and depois["chips"]["fora"] == antes["chips"]["fora"] + 1 and depois["resumo"]["fora"] == depois["chips"]["fora"]
          and r["estado"] == "fora" and r["noMapa"] == 0, f"{antes['chips']} -> {depois['chips']}")
    passo(c, "obra/escopo: o sistema fica marcado 'alterado por você', com o estado do projeto",
          r["alterado"] and r["altVisivel"] and "alterado por você" in r["altTexto"] and "projeto: dentro" in r["altTexto"] and "alterado" in js(c, "document.querySelector('#obResumo').textContent"), r["altTexto"])
    foto(c, "18b_obra_escopo_alterado")
    exp = js(c, "(() => { document.querySelector('#obExp').click(); return document.querySelector('#dlgTxt').value; })()")
    try:
        d = json.loads(exp)
    except ValueError:
        d = {}
    v = d.get(alvo, {})
    passo(c, "obra/escopo: 'Exportar escolhas de escopo' gera {sistema: {estado, origem: manual, data}}",
          list(d) == [alvo] and v.get("estado") == "fora" and v.get("origem") == "manual" and bool(js(c, "(s) => /^\\d{4}-\\d{2}-\\d{2}$/.test(s)", v.get("data") or "")), exp.replace("\n", " "))
    page.click("#dlgFechar")
    if storage_ok(c):
        p2 = page.context.new_page()
        p2.on("pageerror", lambda e: c["erros"].append(f"exceção (página 2): {e}"))
        p2.goto(page.url)
        p2.wait_for_function("window.__viz && window.__viz.obra", timeout=60000)
        r2 = p2.evaluate("(id) => ({e: __viz.obra.estado(id), alt: !document.querySelector('.ob-sis[data-sis=\"' + id + '\"] .ob-alt-l').hidden, r: __viz.obra.resumo()})", alvo)
        p2.close()
        passo(c, "obra/escopo: a escolha persiste ao recarregar (localStorage com D.id)", r2["e"] == "fora" and r2["alt"] and r2["r"]["alterados"] == 1, str(r2))
    else:
        passo(c, "obra/escopo: sem localStorage neste ambiente (persistência não testada)", True)
    # sem storage (modo privado, dados bloqueados) a aba tem de funcionar do mesmo jeito, só sem lembrar
    p3 = page.context.new_page()
    erros3: list[str] = []
    p3.on("pageerror", lambda e: erros3.append(str(e)))
    p3.add_init_script("Object.defineProperty(window, 'localStorage', {get() { throw new Error('bloqueado'); }});")
    p3.goto(page.url)
    p3.wait_for_function("window.__viz && window.__viz.obra", timeout=60000)
    r3 = p3.evaluate("""(id) => { const o = __viz.obra, a = o.resumo(); o.definirEscopo(id, 'fora'); const b = o.resumo();
      return {a: a.dentro, b: b.dentro, fora: b.fora, aba: !document.querySelector('#aba-obra').hidden, alt: o.resumo().alterados}; }""", alvo)
    p3.close()
    passo(c, "obra/escopo: sem localStorage a aba abre e as escolhas funcionam na sessão",
          r3["aba"] and r3["b"] == r3["a"] - 1 and r3["alt"] == 1 and not erros3, f"{r3} {erros3[:2]}")
    page.click("#obRest")
    r = js(c, JS_ESCOPO_ESTADO)
    guardado = js(c, "(k) => { try { return localStorage.getItem(k); } catch (e) { return null; } }", js(c, "__viz.obra.chave"))
    passo(c, "obra/escopo: 'Restaurar do projeto' volta ao estado dos dados e limpa o que estava guardado",
          r["chips"] == r["cont"] == antes["cont"] and js(c, "Object.keys(__viz.obra.manual).length") == 0 and guardado is None and js(c, "document.querySelector('#obRest').disabled"), str(r["chips"]))


def abrir_sistema(c: dict, sis: str) -> None:
    sel = f'#obArvore .ob-sis[data-sis="{sis}"] .ob-sis-h'
    if js(c, "(s) => document.querySelector(s).getAttribute('aria-expanded')", sel) != "true":
        c["page"].click(sel)


JS_OBRA_DECOMP = r"""() => { const o = __viz.obra, E = o.ES.sistemas, ids = Object.keys(E).filter(i => document.querySelector('.ob-sis[data-sis="' + i + '"]'));
  const dec = i => E[i].decomposicao || [], est = i => new Set(dec(i).map(p => p.estado));
  const link = ev => { const d = o.ES.documentos[ev.doc]; return d && /^https:\/\//.test(d.link || '') ? d : null; };
  const tri = [...ids].sort((a, b) => est(b).size - est(a).size)[0];
  const geos = []; for (const i of ids) for (const p of dec(i)) if (p.estado === 'geometria' && o.estado(i) === 'dentro') geos.push({i, p: p.id, n: o.elementosDaParte(i, p).length});
  geos.sort((a, b) => b.n - a.n); const geo = geos.length && geos[0].n ? geos[0].i : null;
  const soltas = []; for (const i of ids) for (const p of dec(i)) if (p.estado === 'geometria' && p.n_geometria > 0 && o.elementosDaParte(i, p).length !== p.n_geometria) soltas.push(i + '/' + p.id);
  const par = [];
  for (const i of ids) for (const p of dec(i)) if ((p.evidencias || []).some(link)) par.push({sis: i, parte: p.id, pontos: (p.estado === 'documento' ? 2 : 0) + (p.evidencias.some(e => e.pagina != null) ? 1 : 0) + (p.evidencias.some(e => e.trecho) ? 1 : 0)});
  par.sort((a, b) => b.pontos - a.pontos);
  return {tri, geo, parteGeo: geo ? geos[0].p : null, soltas, ev: par[0] || null, estadosDados: [...new Set(ids.flatMap(i => [...est(i)]))]}; }"""
JS_OBRA_DECOMP_DOM = """(a) => { const d = document.querySelector('.ob-sis[data-sis="' + a.tri + '"]'), E = __viz.obra.ES.sistemas[a.tri].decomposicao || [];
  const marca = p => { const m = getComputedStyle(p.querySelector('.ob-mk')); return [m.backgroundColor, m.clipPath, m.borderTopWidth, m.backgroundImage].join('|'); };
  const por = {}; d.querySelectorAll('.ob-parte').forEach(p => { por[p.dataset.estado] = por[p.dataset.estado] || p; });
  const marcas = Object.values(por).map(marca), sem = d.querySelector('.ob-parte.est-sem > .ob-pt');
  const todos = [...new Set([...document.querySelectorAll('#obArvore .ob-parte')].map(p => p.dataset.estado))];
  return {partes: d.querySelectorAll('.ob-parte').length, esperado: E.length, grupos: d.querySelectorAll('.ob-grp').length, gEsperado: new Set(E.map(p => p.grupo || 'Outros')).size,
          estados: Object.keys(por), distintas: new Set(marcas).size === marcas.length,
          semAtencao: sem ? getComputedStyle(sem).backgroundColor !== 'rgba(0, 0, 0, 0)' && getComputedStyle(d.querySelector('.ob-parte.est-sem .ob-mk')).clipPath !== 'none' : null,
          agrupado: [...d.querySelectorAll('.ob-grp')].every(g => g.nextElementSibling && g.nextElementSibling.classList.contains('ob-parte')),
          todos, nome: d.querySelector('.ob-parte .nm').textContent, n: E.filter(p => p.estado === 'geometria').every(p => d.querySelector('.ob-parte[data-parte="' + p.id + '"] .es').textContent.includes(String(p.n_geometria)))}; }"""


def obra_decomposicao(c: dict) -> None:
    """Decomposição construtiva por sistema: partes por grupo, três estados com marcador distinto, evidências em link e geometria no mapa."""
    page = c["page"]
    page.fill("#obBusca", "")   # com busca preenchida a árvore fica oculta
    a = js(c, JS_OBRA_DECOMP)
    if not a["tri"]:
        return
    abrir_sistema(c, a["tri"])
    r = js(c, JS_OBRA_DECOMP_DOM, a)
    passo(c, "obra/decomposição: partes agrupadas por 'grupo', cada uma com estado e nº de elementos",
          r["partes"] == r["esperado"] > 0 and r["grupos"] == r["gEsperado"] and r["agrupado"] and r["n"], f"{a['tri']}: {r['partes']} partes em {r['grupos']} grupos")
    passo(c, "obra/decomposição: cada estado (geometria, documento, sem evidência) tem marcador visual distinto",
          r["distintas"] and set(r["estados"]) == set(js(c, "(i) => [...new Set(__viz.obra.ES.sistemas[i].decomposicao.map(p => p.estado))]", a["tri"])), str(r["estados"]))
    passo(c, "obra/decomposição: 'sem evidência' chama a atenção (fundo e marcador de alerta)", r["semAtencao"] in (True, None), str(r["semAtencao"]))
    passo(c, "obra/decomposição: todos os estados presentes nos dados aparecem na árvore", set(r["todos"]) == set(a["estadosDados"]), str(r["todos"]))
    passo(c, "obra/decomposição: toda parte com geometria casa com a classe dos elementos do sistema (n_geometria = elementos no mapa)", not a["soltas"], str(a["soltas"]))
    sem = page.locator(f'#obArvore .ob-sis[data-sis="{a["tri"]}"] .ob-parte.est-sem > .ob-pt')
    if sem.count():
        sem.first.click()
        passo(c, "obra/decomposição: abrir uma parte sem evidência mostra a lacuna",
              js(c, "(i) => { const l = document.querySelector('.ob-sis[data-sis=\"' + i + '\"] .ob-parte.est-sem .ob-lacuna'); return !!l && l.offsetParent !== null; }", a["tri"]))
    foto(c, "19_obra_decomposicao")
    if a["ev"]:
        abrir_sistema(c, a["ev"]["sis"])
        page.locator(f'#obArvore .ob-sis[data-sis="{a["ev"]["sis"]}"] .ob-parte[data-parte="{a["ev"]["parte"]}"] > .ob-pt').click()
        e = js(c, r"""(a) => { const E = __viz.obra.ES, pt = E.sistemas[a.sis].decomposicao.find(p => p.id === a.parte), box = document.querySelector('.ob-sis[data-sis="' + a.sis + '"] .ob-parte[data-parte="' + a.parte + '"] .ob-pt-c');
          const ev = pt.evidencias.find(x => E.documentos[x.doc] && /^https:\/\//.test(E.documentos[x.doc].link || '')), d = E.documentos[ev.doc];
          const lk = [...box.querySelectorAll('a')].find(x => x.href === d.link || x.getAttribute('href').startsWith(d.link));
          return {visivel: box.offsetParent !== null, href: lk ? lk.getAttribute('href') : null, alvo: lk ? lk.target : null, rel: lk ? lk.rel : null, titulo: lk ? lk.textContent : null, tit: d.titulo,
                  pag: ev.pagina == null ? true : box.textContent.includes('p. ' + ev.pagina), trecho: !ev.trecho || box.textContent.includes('“' + ev.trecho + '”'), link: d.link}; }""", a["ev"])
        passo(c, "obra/decomposição: a evidência é o título do documento como link https em nova aba (noopener)",
              e["visivel"] and e["href"] is not None and e["href"].startswith("https://") and e["alvo"] == "_blank" and "noopener" in e["rel"] and e["titulo"] == e["tit"], f"{e['titulo']} → {e['href']}")
        passo(c, "obra/decomposição: a página aparece como 'p. N' e o trecho entre aspas", e["pag"] and e["trecho"])
    if a["geo"] and a["parteGeo"]:
        abrir_sistema(c, a["geo"])
        parte = f'#obArvore .ob-sis[data-sis="{a["geo"]}"] .ob-parte[data-parte="{a["parteGeo"]}"]'
        page.locator(parte + " > .ob-pt").click()
        page.locator(parte + ' [data-ob-acao="parte-mapa"]').click()
        page.wait_for_timeout(700)
        g = js(c, """(a) => { const o = __viz.obra, pt = o.ES.sistemas[a.geo].decomposicao.find(p => p.id === a.parteGeo), its = o.elementosDaParte(a.geo, pt), m = __viz.map, b = m.getBounds();
          const lista = document.querySelectorAll('.ob-sis[data-sis="' + a.geo + '"] .ob-parte[data-parte="' + a.parteGeo + '"] .ob-els [data-ob-id]').length;
          return {n: its.length, lista, todos: its.every(i => { const l = o.camada.get(i.id); return b.contains(l.getBounds ? l.getBounds().getCenter() : l.getLatLng()); }),
                  ligada: m.hasLayer(__viz.camadasMapa.construtivos.layer), classes: [...new Set(its.map(i => i.classe))].join(',')}; }""", a)
        passo(c, "obra/decomposição: parte com geometria lista e enquadra os elementos dela no mapa",
              g["n"] > 0 and g["lista"] == min(g["n"], 300) and g["todos"] and g["ligada"], f"{g['n']} elemento(s) da classe {g['classes']}")
        foto(c, "19b_obra_parte_no_mapa")


def mostrar_no_topo(c: dict, seletor: str) -> None:
    """Rola a aba Obra até o elemento ficar logo abaixo da busca fixa (para a captura mostrar o que interessa)."""
    js(c, "(s) => { const a = document.querySelector('#aba-obra'), e = document.querySelector(s); a.scrollTop += e.getBoundingClientRect().top - a.getBoundingClientRect().top - document.querySelector('.ob-busca').offsetHeight - 4; }", seletor)


JS_OBRA_DESENHOS = r"""() => { const E = __viz.obra.ES, ids = [...document.querySelectorAll('#obArvore .ob-sis')].map(d => d.dataset.sis);
  const des = i => (E.sistemas[i] || {}).desenhos || [], pend = i => des(i).filter(d => d.entregue !== true).length;
  const pr = new Set(__viz.PR.map(p => p.id)), https = d => d && /^https:\/\//.test(d.link || '');
  const vazios = __viz.obra.OB.arvore.flatMap(u => u.sistemas).filter(s => Object.keys(s.classes || {}).length === 0).map(s => s.id);
  const comDes = ids.filter(i => des(i).length), comPend = ids.filter(i => pend(i) > 0);
  const ent = comDes.find(i => des(i).some(d => d.entregue === true && d.doc && https(E.documentos[d.doc])));
  const comPr = comDes.find(i => des(i).some(d => d.entregue === true && d.doc && E.documentos[d.doc] && E.documentos[d.doc].prancha && pr.has(E.documentos[d.doc].prancha)));
  return {vazios: vazios.filter(i => ids.includes(i)), comDes, comPend, ent: ent || null, comPr: comPr || null, resumo: E.desenhos_resumo || null,
          todosEntregues: comDes.filter(i => pend(i) === 0)}; }"""
JS_OBRA_DES_DOM = r"""(id) => { const E = __viz.obra.ES, d = document.querySelector('.ob-sis[data-sis="' + id + '"]'), L = (E.sistemas[id] || {}).desenhos || [];
  const sec = [...d.querySelectorAll('.ob-corpo .ob-sec')].find(x => /Desenhos do projeto \(Rela/.test(x.textContent)), n = d.querySelector('.ob-des-n'), linhas = [...d.querySelectorAll('.ob-des')];
  const k = L.filter(x => x.entregue !== true).length, ne = d.querySelector('.ob-sis-h .ob-ne');
  const ok = (x, el) => !!el && el.querySelector('.f').textContent === (x.folha || '—') && el.querySelector('.ct').textContent.includes(x.conteudo || '') && el.querySelector('.ar').textContent === x.arquivo;
  return {sec: !!sec, nota: n ? n.textContent.replace(/\s+/g, ' ').trim() : null, esperada: L.length + ' citados · ' + (L.length - k) + ' entregues · ' + k + ' não entregues',
          linhas: linhas.length, n: L.length, campos: L.every((x, i) => ok(x, linhas[i])),
          indicador: ne ? ne.textContent.trim() : null, indEsperado: k ? k + ' não entregue' + (k > 1 ? 's' : '') : null, indVisivel: ne ? ne.offsetParent !== null : false}; }"""
JS_OBRA_DES_LINHAS = r"""(id) => { const E = __viz.obra.ES, d = document.querySelector('.ob-sis[data-sis="' + id + '"]'), L = (E.sistemas[id] || {}).desenhos || [], linhas = [...d.querySelectorAll('.ob-des')];
  const nao = linhas.filter((el, i) => L[i].entregue !== true), sim = linhas.filter((el, i) => L[i].entregue === true);
  const marca = el => { const m = el.querySelector('.ob-nao'); return m ? {txt: m.textContent.trim(), forma: getComputedStyle(m, '::before').clipPath, cor: getComputedStyle(m).color, fundo: getComputedStyle(el).backgroundColor} : null; };
  const lk = el => { const a = el.querySelector('a'); return a ? {href: a.getAttribute('href'), alvo: a.target, rel: a.rel} : null; };
  const sem = document.querySelector('.ob-parte.est-sem .es');
  return {nao: nao.length, naoMarca: nao.every(el => marca(el) && marca(el).txt === 'não entregue'), naoSemLink: nao.every(el => !el.querySelector('a')),
          alerta: nao.length ? marca(nao[0]) : null, lacuna: sem ? getComputedStyle(sem).color : null,
          sim: sim.length, simSemMarca: sim.every(el => !el.querySelector('.ob-nao')),
          simLink: sim.map(el => { const doc = L[linhas.indexOf(el)].doc && E.documentos[L[linhas.indexOf(el)].doc];
            return {doc: !!doc, esperado: doc ? doc.link : null, l: lk(el), pr: doc && doc.prancha ? !!el.querySelector('[data-ob-acao="prancha"]') : null}; })}; }"""


def obra_sem_geometria(c: dict) -> None:
    """Sistema sem elemento de geometria (`classes = {}`) vem na árvore, abre sem erro e mantém o controle de escopo."""
    page = c["page"]
    page.fill("#obBusca", "")
    a = js(c, JS_OBRA_DESENHOS)
    if not a["vazios"]:
        passo(c, "obra/sem geometria: nenhum sistema sem elemento nos dados (não testado)", True)
        return
    sid = a["vazios"][0]
    erros = len(c["erros"])
    abrir_sistema(c, sid)
    r = js(c, """(id) => { const d = document.querySelector('.ob-sis[data-sis="' + id + '"]'), h = d.querySelector('.ob-sis-h'), cb = d.querySelector('.ob-esc-cb');
      return {aberto: h.getAttribute('aria-expanded') === 'true' && !d.querySelector('.ob-corpo').hidden, cls: d.querySelectorAll('.ob-cls').length, mapa: d.querySelectorAll('[data-ob-acao="parte-mapa"]').length,
              aviso: /Sem elementos de geometria/.test(d.querySelector('.ob-corpo').textContent), nota: h.querySelector('.nota').textContent, nan: /NaN|undefined|null/.test(d.textContent),
              cb: !!cb, motivo: d.querySelector('.ob-motivo').textContent.length > 8, elementos: __viz.obra.itens.filter(i => i.sis === id).length}; }""", sid)
    passo(c, "obra/sem geometria: o sistema sem elemento aparece na árvore e abre sem erro, sem 'ver no mapa' nem classes",
          r["aberto"] and r["cls"] == 0 and r["mapa"] == 0 and r["aviso"] and not r["nan"] and r["elementos"] == 0 and len(c["erros"]) == erros, f"{sid} ({len(a['vazios'])} sem geometria)")
    passo(c, "obra/sem geometria: sem contagem de elementos no cabeçalho; 'No escopo' e a origem do escopo continuam",
          r["nota"] == "sem geometria" and r["cb"] and r["motivo"], r["nota"])
    antes = js(c, JS_ESCOPO_ESTADO)
    est = js(c, "(i) => __viz.obra.estado(i)", sid)
    page.locator(f'.ob-sis[data-sis="{sid}"] .ob-esc-cb').click()
    depois = js(c, JS_ESCOPO_ESTADO)
    novo = js(c, "(i) => __viz.obra.estado(i)", sid)
    passo(c, "obra/sem geometria: alternar 'No escopo' muda o estado e o resumo do sistema sem elemento",
          novo != est and sum(depois["chips"].values()) == sum(antes["chips"].values()) and depois["chips"] != antes["chips"], f"{est} -> {novo}")
    js(c, "__viz.obra.restaurar()")
    mostrar_no_topo(c, f'#obArvore .ob-sis[data-sis="{sid}"]')
    foto(c, "21_obra_sem_geometria")


def obra_desenhos(c: dict) -> None:
    """Desenhos do projeto (Relação) por sistema: contagem, não entregue com marcador de alerta e sem link, entregue com link e 'ver na aba Pranchas'; resumo geral."""
    page = c["page"]
    page.fill("#obBusca", "")
    a = js(c, JS_OBRA_DESENHOS)
    if not a["comDes"]:
        passo(c, "obra/desenhos: nenhum sistema com desenhos da Relação nos dados (não testado)", True)
        return
    erros = len(c["erros"])
    for sid in a["comDes"]:
        abrir_sistema(c, sid)
    dom = {i: js(c, JS_OBRA_DES_DOM, i) for i in a["comDes"]}
    ruins = [i for i, r in dom.items() if not (r["sec"] and r["nota"] == r["esperada"] and r["linhas"] == r["n"] and r["campos"])]
    passo(c, "obra/desenhos: cada sistema com desenhos mostra a seção, 'N citados · M entregues · K não entregues' igual aos dados, e uma linha por desenho (folha, conteúdo, arquivo)",
          not ruins, f"{len(dom)} sistema(s)" + (f"; falhou {ruins[:3]}" if ruins else ""))
    passo(c, "obra/desenhos: na árvore, o indicador 'K não entregues' aparece só nos sistemas com pendência e bate com os dados",
          all(r["indicador"] == r["indEsperado"] and (r["indicador"] is None or r["indVisivel"]) for r in dom.values()), f"{len(a['comPend'])} com pendência")
    passo(c, "obra/desenhos: sistema com todos os desenhos entregues não mostra o indicador",
          all(dom[i]["indicador"] is None for i in a["todosEntregues"]), f"{len(a['todosEntregues'])} sistema(s)")
    nao = next(iter(a["comPend"]), None)
    if nao:
        r = js(c, JS_OBRA_DES_LINHAS, nao)
        passo(c, "obra/desenhos: desenho não entregue traz o marcador de alerta 'não entregue' e nenhum link",
              r["nao"] > 0 and r["naoMarca"] and r["naoSemLink"] and r["alerta"]["forma"] != "none", f"{nao}: {r['nao']} não entregue(s)")
        passo(c, "obra/desenhos: o alerta usa a cor da lacuna 'sem evidência' e destaca a linha",
              (r["lacuna"] is None or r["alerta"]["cor"] == r["lacuna"]) and r["alerta"]["fundo"] != "rgba(0, 0, 0, 0)", r["alerta"]["cor"])
        mostrar_no_topo(c, f'#obArvore .ob-sis[data-sis="{nao}"]')
        foto(c, "22_obra_desenhos")
    if a["ent"]:
        r = js(c, JS_OBRA_DES_LINHAS, a["ent"])
        bons = [x for x in r["simLink"] if x["doc"] and (x["esperado"] or "").startswith("https://")]
        passo(c, "obra/desenhos: desenho entregue é link https para o documento, em nova aba (target=_blank, rel=noopener), sem marcador de alerta",
              r["simSemMarca"] and bool(bons) and all(x["l"] and x["l"]["href"] == x["esperado"] and x["l"]["alvo"] == "_blank" and "noopener" in x["l"]["rel"] for x in bons), f"{a['ent']}: {len(bons)} entregue(s)")
    else:
        passo(c, "obra/desenhos: nenhum desenho entregue com link nos dados (não testado)", True)
    if a["comPr"]:
        r = js(c, JS_OBRA_DES_LINHAS, a["comPr"])
        com = [x for x in r["simLink"] if x["pr"] is not None]
        passo(c, "obra/desenhos: entregue que é prancha oferece 'ver na aba Pranchas'", bool(com) and all(x["pr"] for x in com), a["comPr"])
        alvo = js(c, "(i) => { const D = __viz.obra.ES.sistemas[i].desenhos, E = __viz.obra.ES.documentos; return D.map(d => d.doc && E[d.doc] && E[d.doc].prancha).find(Boolean); }", a["comPr"])
        c["page"].locator(f'#obArvore .ob-sis[data-sis="{a["comPr"]}"] .ob-des [data-ob-acao="prancha"]').first.click()
        p = js(c, "() => ({folha: __viz.FV.P ? __viz.FV.P.id : null, aba: !document.querySelector('#aba-pranchas').hidden})")
        passo(c, "obra/desenhos: 'ver na aba Pranchas' abre a prancha do documento", p["folha"] == alvo and p["aba"], str(p["folha"]))
        page.select_option("#pSel", "")
        page.click("#t-obra")
    rs = a["resumo"]
    if rs:
        txt = js(c, "document.querySelector('#obDesResumo').textContent.replace(/\\s+/g, ' ').trim()")

        def f(n: int) -> str:
            return f"{n:,}".replace(",", ".")

        esperado = f"Desenhos do projeto: {f(rs['citados'])} citados · {f(rs['entregues'])} entregues · {f(rs['nao_entregues'])} não entregues"
        topo = js(c, "(() => { const r = document.querySelector('#obDesRes'), t = document.querySelector('#obArvore'); return !r.hidden && r.getBoundingClientRect().bottom <= t.getBoundingClientRect().top; })()")
        passo(c, "obra/desenhos: resumo geral no topo da aba bate com desenhos_resumo", txt == esperado and topo, txt)
    else:
        passo(c, "obra/desenhos: sem desenhos_resumo nos dados o resumo geral fica vazio", js(c, "document.querySelector('#obDesResumo').textContent === ''"))
    passo(c, "obra/desenhos: console sem erros ao abrir os sistemas e a seção", len(c["erros"]) == erros, "; ".join(c["erros"][erros:erros + 2]))
    js(c, "document.querySelector('#aba-obra').scrollTop = 0")
    foto(c, "23_obra_resumo_desenhos")


def obra_desenhos_filtro(c: dict) -> None:
    """Atalho "Só com desenho não entregue": a árvore lista exatamente os sistemas com pendência."""
    page = c["page"]
    a = js(c, JS_OBRA_DESENHOS)
    if not a["comDes"]:
        return
    page.fill("#obBusca", "")
    antes = js(c, "document.querySelectorAll('#obArvore .ob-sis:not([hidden])').length")
    page.check("#obSoPend")
    r = js(c, """() => ({ids: [...document.querySelectorAll('#obArvore .ob-sis:not([hidden])')].filter(d => d.offsetParent !== null).map(d => d.dataset.sis).sort(),
      unidades: [...document.querySelectorAll('#obArvore .ob-un')].every(u => u.hidden === !u.querySelector('.ob-sis:not([hidden])')),
      n: document.querySelector('#obSoPendN').textContent})""")
    passo(c, "obra/desenhos: 'Só com desenho não entregue' lista exatamente os sistemas com pendência (e esconde unidades vazias)",
          r["ids"] == sorted(a["comPend"]) and r["unidades"] and str(len(a["comPend"])) in r["n"], f"{len(r['ids'])} de {antes} sistemas")
    for sid in r["ids"]:   # só para a captura: fecha os sistemas abertos, para a lista de pendências caber na tela
        if js(c, "(s) => document.querySelector(s).getAttribute('aria-expanded')", f'#obArvore .ob-sis[data-sis="{sid}"] .ob-sis-h') == "true":
            page.click(f'#obArvore .ob-sis[data-sis="{sid}"] .ob-sis-h')
    mostrar_no_topo(c, "#obArvore")
    foto(c, "24_obra_so_pendentes")
    page.uncheck("#obSoPend")
    depois = js(c, "document.querySelectorAll('#obArvore .ob-sis:not([hidden])').length")
    passo(c, "obra/desenhos: desligar o atalho devolve todos os sistemas à árvore", depois == antes, f"{depois} sistemas")


def obra_fonte(c: dict) -> None:
    """Fonte da ficha como link (nova aba) e 'ver na aba Pranchas'; popup mínimo leva à ficha mesmo com outra aba aberta."""
    page = c["page"]
    a = js(c, r"""() => { const o = __viz.obra, E = o.ES, bom = (i, p) => { const d = E.documentos[i.f.properties.doc]; return d && /^https:\/\//.test(d.link || '') && (!p || (d.prancha && __viz.PR.some(x => x.id === d.prancha))); };
      const it = o.itens.find(i => bom(i, true)) || o.itens.find(i => bom(i, false)); if (!it) return null; const d = E.documentos[it.f.properties.doc];
      return {id: it.id, rotulo: it.rotulo, titulo: d.titulo, link: d.link, prancha: d.prancha && __viz.PR.some(x => x.id === d.prancha) ? d.prancha : null}; }""")
    if not a:
        passo(c, "obra/fonte: nenhum elemento com documento e link nos dados (não testado)", True)
        return
    js(c, "(id) => __viz.obra.selecionar(id, {enquadrar: false})", a["id"])
    page.wait_for_timeout(400)   # o popup anterior some com um fade de 200 ms
    r = js(c, """(a) => { const lk = [...document.querySelectorAll('#obFicha a')].find(x => x.getAttribute('href') === a.link);
      return {href: !!lk, alvo: lk ? lk.target : null, rel: lk ? lk.rel : null, titulo: lk ? lk.textContent : null, fonte: [...document.querySelectorAll('#obFicha tr')].some(t => t.firstElementChild.textContent === 'Fonte' && t.contains(lk)),
              botao: !!document.querySelector('#obFicha [data-ob-acao="prancha"]'), popBotao: [...document.querySelectorAll('.leaflet-popup-content button')].filter(b => /ver ficha/i.test(b.textContent)).length}; }""", a)
    passo(c, "obra/fonte: 'Fonte' na ficha é o link do projeto, em nova aba (target=_blank, rel=noopener)",
          r["href"] and r["fonte"] and r["alvo"] == "_blank" and "noopener" in r["rel"] and a["link"].startswith("https://") and r["titulo"] == a["titulo"], f"{r['titulo']} → {a['link']}")
    foto(c, "20_obra_ficha_fonte")
    # popup mínimo: com outra aba aberta, 'ver ficha' traz a aba Obra de volta, já no elemento
    page.click("#t-camadas")
    passo(c, "obra/popup: uma só ação no popup, 'ver ficha'", r["popBotao"] == 1)
    page.locator(".leaflet-popup-content button", has_text="Ver ficha").click()
    passo(c, "obra/popup: 'ver ficha' abre a aba Obra no elemento",
          js(c, "(a) => !document.querySelector('#aba-obra').hidden && document.querySelector('#obFicha').textContent.includes(a.rotulo) && __viz.obra.sel === a.id", a))
    if a["prancha"]:
        page.locator('#obFicha [data-ob-acao="prancha"]').click()
        p = js(c, "() => ({folha: __viz.FV.P ? __viz.FV.P.id : null, aba: !document.querySelector('#aba-pranchas').hidden, sel: document.querySelector('#t-pranchas').getAttribute('aria-selected')})")
        passo(c, "obra/fonte: 'ver na aba Pranchas' abre a prancha do documento", p["folha"] == a["prancha"] and p["aba"] and p["sel"] == "true", f"{p['folha']}")
        page.select_option("#pSel", "")   # fecha a folha: o roteiro segue pelo mapa
        page.click("#t-obra")


def obra_arvore(c: dict) -> None:
    page = c["page"]
    r = js(c, """() => { const C = __viz.D.construtivos, uns = [...document.querySelectorAll('#obArvore .ob-un')];
      return {un: uns.length, esperado: C.arvore.length, obra: C.arvore.every((u, i) => uns[i].querySelector('summary').textContent.includes(u.obra)),
        classes: C.arvore.every((u, i) => u.sistemas.every(s => uns[i].querySelectorAll('.ob-sis[data-sis="' + s.id + '"] .ob-cls').length === Object.keys(s.classes).length)),
        sist: C.arvore.reduce((a, u) => a + u.sistemas.length, 0), sistDom: document.querySelectorAll('#obArvore .ob-sis').length}; }""")
    passo(c, "obra: árvore com uma entrada por unidade, com o tipo de obra", r["un"] == r["esperado"] > 0 and r["obra"], f"{r['un']} unidade(s)")
    passo(c, "obra: cada sistema traz suas classes com contagem", r["classes"] and r["sist"] == r["sistDom"], f"{r['sistDom']} sistemas")
    alvo = js(c, """() => { const t = []; for (const u of __viz.D.construtivos.arvore) for (const s of u.sistemas) for (const [k, n] of Object.entries(s.classes)) t.push({sis: s.id, classe: k, n});
      return t.find(x => x.classe === 'pilar') || t.find(x => x.n > 0 && x.n <= 300) || null; }""")
    if alvo:
        page.click(f'#obArvore .ob-sis[data-sis="{alvo["sis"]}"] .ob-sis-h')
        page.click(f'#obArvore .ob-cls[data-sis="{alvo["sis"]}"][data-classe="{alvo["classe"]}"]')
        n = js(c, "(a) => document.querySelectorAll('#obArvore .ob-cls[data-sis=\"' + a.sis + '\"][data-classe=\"' + a.classe + '\"] + .ob-els [data-ob-id]').length", alvo)
        passo(c, "obra: clicar numa classe lista os elementos dela", n == alvo["n"], f"{alvo['classe']}: {n} de {alvo['n']}")


def obra_busca(c: dict) -> dict:
    page = c["page"]
    a = js(c, JS_OBRA_ALVOS)
    page.fill("#obBusca", a["pilar"])
    r = js(c, """(k) => { const b = [...document.querySelectorAll('#obRes [data-ob-id]')];
      return {n: b.length, alvo: b.filter(x => x.dataset.classe === k).length, completos: b.every(x => ['.r', '.c', '.s'].every(s => x.querySelector(s).textContent.trim())),
              arvore: document.querySelector('#obArvore').hidden}; }""", a["classe"])
    passo(c, f"obra: busca '{a['pilar']}' acha o pilar, com rótulo, classe e sistema", r["alvo"] >= 1 and r["completos"] and r["arvore"], f"{r['alvo']} de {r['n']} resultado(s)")
    if a["ponto"]:
        page.fill("#obBusca", a["ponto"])
        primeiro = js(c, "document.querySelector('#obRes [data-ob-id] .r').textContent")
        passo(c, f"obra: busca pelo código '{a['ponto']}' põe o elemento em primeiro", primeiro == a["ponto"], primeiro)
    if a["termoLinha"]:
        page.fill("#obBusca", a["termoLinha"])
        n = js(c, "(k) => [...document.querySelectorAll('#obRes [data-ob-id]')].filter(x => x.dataset.classe === k).length", a["classeLinha"])
        passo(c, f"obra: busca '{a['termoLinha']}' acha os trechos da rede", n >= 1, f"{n} trecho(s)")
    page.fill("#obBusca", a["maior"])
    r = js(c, "(q) => ({total: __viz.obra.buscar(q).length, linhas: document.querySelectorAll('#obRes [data-ob-id]').length, nota: document.querySelector('#obRes .nota-l').textContent})", a["maior"])
    passo(c, "obra: no máximo 50 resultados, com a contagem total", r["linhas"] == min(r["total"], 50) and (r["total"] <= 50 or f"{r['total']:,}".replace(",", ".") in r["nota"]), r["nota"])
    iguais = js(c, "(q) => __viz.obra.buscar(q[0]).length === __viz.obra.buscar(q[1]).length", [a["maior"], sem_acento_maiusculo(a["maior"])])
    passo(c, "obra: busca sem acento e sem maiúsculas dá o mesmo resultado", iguais and r["total"] > 0, f"'{a['maior']}' = '{sem_acento_maiusculo(a['maior'])}'")
    return a


def obra_selecao(c: dict, a: dict) -> None:
    page = c["page"]
    page.fill("#obBusca", a["pilar"])
    page.locator(f'#obRes [data-ob-id][data-classe="{a["classe"]}"]').first.click()
    page.wait_for_timeout(900)
    r = js(c, JS_OBRA_SELECAO)
    passo(c, "obra: clicar no resultado enquadra o elemento (centro do mapa dentro dos limites, zoom alto)", r["dentro"] and r["zoom"] >= 19, f"zoom {r['zoom']}")
    passo(c, "obra: a camada Obra liga sozinha e as duas caixas ficam marcadas", r["ligada"] and all(r["caixas"]))
    passo(c, "obra: elementos desenhados com a cor da classe", r["cores"])
    f = r["ficha"]
    passo(c, "obra: ficha com rótulo, classe, sistema, unidade, etapa, atributos e fonte",
          all(t in f for t in (r["rotulo"], r["classe"], "Sistema", "Unidade", "Etapa", "Atributos", "Fonte")), f"{r['classe']} {r['rotulo']}")
    passo(c, "obra: popup do mapa é mínimo (rótulo, classe, sistema e 'ver ficha'), sem a tabela de atributos",
          r["rotulo"] in r["popup"] and r["classe"] in r["popup"] and r["sisNome"] in r["popup"] and r["popBotao"] and r["popTabelas"] == 0 and "Atributos" not in r["popup"])
    passo(c, "obra: a ficha completa (tabelas e atributos) fica só no painel", r["fichaTabelas"] >= 1 and "Atributos" in f)
    passo(c, "obra: atributo decimal com vírgula (pt-BR)", r["num"] is None or ("," in r["num"] and r["num"] in f), str(r["num"]))
    passo(c, "obra: elemento destacado (anel duplo) e item da lista marcado", r["aneis"] == 2 and js(c, "document.querySelectorAll('#obRes [aria-current=true]').length") == 1)
    foto(c, "17_obra")
    anterior = r["sel"]
    outro = js(c, "(ant) => { const it = __viz.obra.itens, k = it.find(i => i.id === ant).classe; return it.find(i => i.id !== ant && i.classe === k) || null; }", anterior)
    if outro:
        page.fill("#obBusca", outro["rotulo"])
        page.locator(f'#obRes [data-ob-id="{outro["id"]}"]').first.click()
        page.wait_for_timeout(900)
        r2 = js(c, """(ant) => { const o = __viz.obra, l = o.camada.get(ant), est = __viz.camadasMapa.construtivos.layer.options.style(l.feature);
          return {sel: o.sel, volta: l.options.weight === est.weight && l.options.fillOpacity === est.fillOpacity, aneis: o.halo.getLayers().length,
                  ficha: document.querySelector('#obFicha').textContent}; }""", anterior)
        passo(c, "obra: só o elemento selecionado fica em destaque (o anterior volta ao estilo)",
              r2["sel"] == outro["id"] and r2["volta"] and r2["aneis"] == 2 and outro["rotulo"] in r2["ficha"])


def obra_linha(c: dict, a: dict) -> None:
    """Trecho de rede: linha vetorial (L.Polyline) clicável de verdade, com clique do mouse sobre um vértice do traço."""
    page = c["page"]
    if not a["linha"]:
        return
    page.click('[data-ob-acao="limpar"]')
    r = js(c, """(id) => { const l = __viz.obra.camada.get(id), m = __viz.map, it = __viz.obra.itens.find(i => i.id === id), k = __viz.D.construtivos.classes[it.classe];
      m.fitBounds(l.getBounds(), {padding: [70, 70], maxZoom: 22, animate: false});
      const cen = m.getSize().divideBy(2), p = l.getLatLngs().flat(Infinity).map(ll => m.latLngToContainerPoint(ll)).sort((x, y) => x.distanceTo(cen) - y.distanceTo(cen))[0];
      const caixa = m.getContainer().getBoundingClientRect();
      return {linha: l instanceof L.Polyline && !(l instanceof L.Polygon), interativa: l.options.interactive !== false, cor: l.options.color === k.cor, classe: k.nome,
              rotulo: it.rotulo, x: caixa.left + p.x, y: caixa.top + p.y}; }""", a["linha"])
    passo(c, "obra: trecho de rede é uma linha vetorial clicável, na cor da classe", r["linha"] and r["interativa"] and r["cor"], r["rotulo"])
    page.mouse.click(r["x"], r["y"])
    page.wait_for_timeout(500)
    r2 = js(c, "() => { const o = __viz.obra, it = o.itens.find(i => i.id === o.sel); return {classe: it ? it.classe : null, ficha: document.querySelector('#obFicha').textContent, popup: !!document.querySelector('.leaflet-popup-content')}; }")
    passo(c, "obra: clicar no trecho no mapa abre a mesma ficha", r2["classe"] == a["classeLinha"] and r["classe"] in r2["ficha"] and r2["popup"], r["rotulo"])
    foto(c, "17b_obra_trecho")


def obra_fim(c: dict, a: dict) -> None:
    page = c["page"]
    page.click('[data-ob-acao="limpar"]')
    passo(c, "obra: 'Limpar seleção' tira o destaque e a ficha",
          js(c, "__viz.obra.sel === null && __viz.obra.halo.getLayers().length === 0 && !document.querySelector('#obFicha').textContent.trim()"))
    page.uncheck("#obMapa")
    passo(c, "obra: desligar a camada na aba Obra tira os elementos do mapa e desmarca em Camadas",
          js(c, "!__viz.map.hasLayer(__viz.camadasMapa.construtivos.layer) && !document.querySelector('#v-construtivos').checked"))
    page.click("#t-camadas")
    page.check("#v-construtivos")
    page.click("#t-obra")
    passo(c, "obra: ligar em Camadas liga a caixa da aba Obra (grupo Obra na árvore de camadas)",
          js(c, "document.querySelector('#obMapa').checked && __viz.map.hasLayer(__viz.camadasMapa.construtivos.layer)"))
    page.uncheck("#obMapa")
    if c["info"]["tem3d"]:   # com o 3D por cima do mapa, selecionar volta ao mapa
        page.click("#b-3d")
        page.wait_for_function("window.__viz.v3 && window.__viz.v3.renderer", timeout=30000)
        page.fill("#obBusca", a["pilar"])
        page.locator(f'#obRes [data-ob-id][data-classe="{a["classe"]}"]').first.click()
        page.wait_for_timeout(600)
        passo(c, "obra: selecionar com o 3D aberto volta ao mapa", js(c, "document.querySelector('#vista3d').hidden && !!__viz.obra.sel"))
        page.click('[data-ob-acao="limpar"]')
        page.uncheck("#obMapa")
    page.fill("#obBusca", "")
    page.click("#t-camadas")
    page.wait_for_timeout(300)


def verificar_projeto(c: dict) -> None:
    """Aba Projeto: inventário (soma = listagem), cavas (escavação e reaterro) e valas (uma tabela por rede)."""
    page = c["page"]
    if not js(c, "!!(__viz.D.inventario || __viz.D.escavacao || __viz.D.valas || __viz.D.fichas)"):
        return
    page.click("#t-info")
    page.wait_for_timeout(300)
    if js(c, "!!__viz.D.inventario"):
        r = js(c, """() => { const I = __viz.D.inventario, s = I.resumo.reduce((a, l) => a + l.total, 0);
          return {soma: s, total: I.totais.arquivos ?? I.totais.pdfs, itens: I.itens.length, nota: document.querySelector('#invLista .nota-l').textContent}; }""")
        # desde a 0.19.0 o inventário tem todos os arquivos da listagem (não só PDF): totais.arquivos
        passo(c, "inventário: soma do resumo = arquivos da listagem = itens", r["soma"] == r["total"] == r["itens"], str(r))
        page.select_option("#invTipo", "planta")
        page.wait_for_timeout(200)
        n = js(c, "document.querySelectorAll('#invLista .inv-i').length")
        passo(c, "inventário: filtro por plantas", n == js(c, "__viz.D.inventario.totais.planta"), f"{n} plantas")
        page.select_option("#invTipo", "")
        page.select_option("#invSit", "baloes")
        page.wait_for_timeout(200)
        r = js(c, """() => ({lista: document.querySelectorAll('#invLista .inv-i').length,
          esperado: __viz.D.inventario.itens.filter(i => i.ficha && i.ficha.baloes).length,
          fichas: __viz.D.inventario.itens.filter(i => i.ficha).length,
          disco: __viz.D.inventario.itens.filter(i => i.situacao.startsWith('no disco')).length})""")
        passo(c, "inventário: fichas em lote só de arquivo no disco; filtro 'com balões'",
              0 < r["fichas"] <= r["disco"] and r["lista"] == r["esperado"] > 0, str(r))
        page.select_option("#invSit", "")
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
        r = js(c, """() => { const F = __viz.D.fichas, l = __viz.camadasMapa.blocos_forma;
          return {pilares: F.reduce((s, f) => s + (f.pilares || []).length, 0),
                  mapa: l ? l.layer.getLayers().filter(x => x.feature.properties.tipo === 'Pilar (forma)').length : 0}; }""")
        passo(c, "fichas: pilares da forma no mapa", r["pilares"] == r["mapa"], str(r))
    foto(c, "16_projeto")
    page.click("#t-camadas")
    page.wait_for_timeout(300)


def verificar_contrato_211(c: dict) -> None:
    """Contrato 211 (aba EAP, com `D.contrato_211`): aparece, tem título, uma linha por linha do Python, sem preço e sem
    rolagem horizontal da página. Sem `D.contrato_211` as verificações são puladas."""
    if not js(c, "!!__viz.D.contrato_211"):
        print("  [--]    Contrato 211: sem D.contrato_211 (verificações puladas)")
        return
    page = c["page"]
    passo(c, "Contrato 211: aba EAP aparece", js(c, "!document.querySelector('#t-eap').hidden"))
    passo(c, "Contrato 211: título 'Contrato 211' na aba EAP", js(c, "document.querySelector('#aba-eap').textContent.includes('Contrato 211')"))
    page.click("#t-eap")
    page.wait_for_timeout(300)
    # com `D.eap_vista` o contrato vira lista (`.ctr-l`, uma por linha); sem ela segue a tabela de sempre
    r = js(c, """() => { const vista = !!__viz.D.eap_vista, raiz = document.querySelector(vista ? '#eap-s-contrato' : '#aba-eap');
      return {tabela: document.querySelectorAll(vista ? '#eap-s-contrato .ctr-l' : '#aba-eap table.ctr211 tbody tr').length,
      esperado: __viz.D.contrato_211.linhas.length,
      preco: raiz.textContent.includes('R$') || [...raiz.querySelectorAll('[title]')].some(e => e.title.includes('R$'))}; }""")
    passo(c, "Contrato 211: uma linha na tabela por linha do Python", r["tabela"] == r["esperado"], str(r))
    passo(c, "Contrato 211: nenhum texto da tabela com preço (R$)", not r["preco"], str(r))
    passo(c, "Contrato 211: o bloco não aumenta a largura da página", js(c, "document.documentElement.scrollWidth <= window.innerWidth + 1"))
    foto(c, "17_contrato_211")
    page.click("#t-camadas")
    page.wait_for_timeout(300)


def verificar_eap_vista(c: dict) -> None:
    """Aba EAP com vista (`D.eap_vista`, montada em Python): aba larga, sub-abas (uma seção por vez), WBS recolhida curta, busca e
    chips de situação, linha do Contrato 211 que abre o detalhe, links folha <-> contrato, "ver no mapa" e "abrir prancha"
    (só se houver linha com rede/prancha) e sem rolagem horizontal. Sem `D.eap_vista` as verificações são puladas."""
    if not js(c, "!!__viz.D.eap_vista"):
        print("  [--]    aba EAP: sem D.eap_vista (verificações puladas)")
        return
    page, celular = c["page"], c["tag"] != "desktop"
    page.click("#t-eap")
    page.wait_for_timeout(300)
    n_secoes = js(c, "__viz.D.eap_vista.secoes.length")
    larg = js(c, "({aside: document.querySelector('aside').offsetWidth, janela: window.innerWidth})")
    if celular:
        passo(c, "aba EAP: no celular o painel ocupa a largura toda", larg["aside"] >= larg["janela"] - 1, str(larg))
    else:
        passo(c, "aba EAP: no desktop o painel tem ao menos 900 px", larg["aside"] >= 900, str(larg))
    passo(c, "aba EAP: uma sub-aba por seção do Python", js(c, "document.querySelectorAll('#aba-eap [data-eap-sec]').length") == n_secoes, f"{n_secoes} seções")
    visiveis = js(c, "[...document.querySelectorAll('#aba-eap .eap-sec')].filter(s => s.offsetParent !== null).length")
    passo(c, "aba EAP: só uma seção visível por vez", visiveis == 1, f"{visiveis} visível(is)")
    ids = js(c, "__viz.D.eap_vista.secoes.map(s => s.id)")
    passo(c, "aba EAP: os rótulos e contagens das sub-abas vêm do Python",
          js(c, "[...document.querySelectorAll('#aba-eap [data-eap-sec]')].every((b, i) => b.textContent.includes(__viz.D.eap_vista.secoes[i].rotulo) && b.textContent.includes(__viz.D.eap_vista.secoes[i].n_txt))"))
    if "wbs" in ids:
        page.click('#aba-eap [data-eap-sec="wbs"]')
        page.wait_for_timeout(200)
        altura = js(c, "document.querySelector('#aba-eap').scrollHeight")
        if not celular:
            passo(c, "aba EAP: WBS recolhida com menos de 3 000 px de rolagem", altura < 3000, f"{altura} px")
        foto(c, "18_eap_wbs")
        page.fill('#aba-eap [data-eap-q="wbs"]', "Rebaixamento")
        page.wait_for_timeout(200)
        r = js(c, """() => { const v = [...document.querySelectorAll('#eap-s-wbs .wbs-fo')].filter(e => !e.hidden);
          return {n: v.length, todas: v.every(e => e.dataset.busca.includes('rebaixamento')),
                  etapasVazias: [...document.querySelectorAll('#eap-s-wbs .wbs-et')].filter(e => !e.hidden && !e.querySelector('.wbs-fo:not([hidden])')).length,
                  abertas: [...document.querySelectorAll('#eap-s-wbs .wbs-et')].filter(e => !e.hidden).every(e => e.open)}; }""")
        passo(c, "WBS: a busca 'rebaixamento' deixa folhas e todas contêm o termo", r["n"] >= 1 and r["todas"], str(r))
        passo(c, "WBS: etapa sem folha visível some e as com resultado abrem", r["etapasVazias"] == 0 and r["abertas"], str(r))
        page.fill('#aba-eap [data-eap-q="wbs"]', "")
        page.wait_for_timeout(200)
        r = js(c, "({escondidas: [...document.querySelectorAll('#eap-s-wbs .wbs-fo')].filter(e => e.hidden).length, abertas: document.querySelectorAll('#eap-s-wbs .wbs-et[open]').length})")
        passo(c, "WBS: limpar a busca devolve a árvore recolhida", r["escondidas"] == 0 and r["abertas"] == 0, str(r))
        chip = js(c, "__viz.D.eap_vista.situacoes.wbs[0]")
        page.click(f'#eap-s-wbs [data-eap-sit="{chip["rotulo"]}"]')
        r = js(c, """(rot) => { const v = [...document.querySelectorAll('#eap-s-wbs .wbs-fo')].filter(e => !e.hidden);
          return {n: v.length, so: v.every(e => e.dataset.sit === rot)}; }""", chip["rotulo"])
        passo(c, f"WBS: chip '{chip['rotulo']}' mostra só folhas dessa situação, na quantidade do Python", r["so"] and r["n"] == chip["n"], f"{r} esperado {chip['n']}")
        page.click('#eap-s-wbs [data-eap-sit=""]')
        page.click("#eap-s-wbs [data-eap-exp='1']")
        abertas = js(c, "[...document.querySelectorAll('#eap-s-wbs .wbs-et')].every(e => e.open)")
        page.click("#eap-s-wbs [data-eap-exp='0']")
        fechadas = js(c, "[...document.querySelectorAll('#eap-s-wbs details')].every(e => !e.open)")
        passo(c, "WBS: expandir tudo e recolher tudo", abertas and fechadas)
        folha = page.locator("#eap-s-wbs .wbs-fo:has(.wbs-q li):has([data-ir-linha])").first   # a primeira folha com quantidades e linhas
        folha.locator("xpath=ancestor::details[1]/summary").click()   # abre a etapa
        folha.locator("summary").click()   # e a folha
        page.wait_for_timeout(200)
        passo(c, "WBS: abrir etapa e folha mostra quantidades e linhas do contrato", folha.locator(".wbs-ct li").count() >= 1 and folha.locator(".wbs-q li").count() >= 1)
        foto(c, "19_eap_wbs_aberta")
    if "contrato" in ids:
        page.click('#aba-eap [data-eap-sec="contrato"]')
        page.wait_for_timeout(200)
        esperado = js(c, "__viz.D.contrato_211.linhas.length")
        n_dom = js(c, "document.querySelectorAll('#eap-s-contrato .ctr-l').length")
        passo(c, "Contrato 211: uma linha por linha do Python na lista", n_dom == esperado, f"{n_dom} de {esperado}")
        chip = next((s for s in js(c, "__viz.D.eap_vista.situacoes.contrato") if s["rotulo"] == "a preencher"), None)
        if chip:
            page.click('#eap-s-contrato [data-eap-sit="a preencher"]')
            r = js(c, """() => { const v = [...document.querySelectorAll('#eap-s-contrato .ctr-l')].filter(e => !e.hidden);
              return {n: v.length, so: v.every(e => e.dataset.sit === 'a preencher')}; }""")
            passo(c, "Contrato 211: chip 'a preencher' mostra só essas linhas, na quantidade do Python", r["so"] and r["n"] == chip["n"], f"{r} esperado {chip['n']}")
        page.fill('#aba-eap [data-eap-q="contrato"]', "adutora")
        r = js(c, "[...document.querySelectorAll('#eap-s-contrato .ctr-l')].filter(e => !e.hidden).every(e => e.dataset.busca.includes('adutora'))")
        passo(c, "Contrato 211: a busca filtra pelo índice normalizado do Python", r)
        page.fill('#aba-eap [data-eap-q="contrato"]', "")
        page.click('#eap-s-contrato [data-eap-sit=""]')
        linha = page.locator("#eap-s-contrato .ctr-l:not([hidden])").first
        linha.locator("summary").click()
        page.wait_for_timeout(200)
        det = linha.locator(".ctr-det")
        passo(c, "Contrato 211: abrir uma linha mostra o detalhe", det.is_visible() and len(det.inner_text()) > 10, det.inner_text()[:60].replace("\n", " "))
        passo(c, "Contrato 211: descrição, calculada e situação à vista na linha",
              js(c, "(() => { const s = document.querySelector('#eap-s-contrato .ctr-l[open] > summary'); return !!s.querySelector('.rot').textContent && !!s.querySelector('.ctr-c').textContent && !!s.querySelector('.sel'); })()"))
        foto(c, "20_eap_contrato_linha")
        # link da linha de volta à folha da WBS, e da folha de novo à linha (com um filtro que esconde o destino)
        if "wbs" in ids and js(c, "!!document.querySelector('#eap-s-contrato .ctr-l [data-ir-folha]')"):
            page.locator("#eap-s-contrato .ctr-l [data-ir-folha]").first.click()
            page.wait_for_timeout(200)
            r = js(c, "(() => { const f = [...document.querySelectorAll('#eap-s-wbs .wbs-fo')].find(e => e.open); return {sec: [...document.querySelectorAll('.eap-sec')].find(s => s.offsetParent !== null).dataset.sec, aberta: !!f}; })()")
            passo(c, "link linha -> folha leva à WBS e abre a folha", r["sec"] == "wbs" and r["aberta"], str(r))
            if chip:   # um filtro do contrato que esconde o destino: o link tem de limpá-lo
                page.click('#aba-eap [data-eap-sec="contrato"]')
                page.click('#eap-s-contrato [data-eap-sit="a preencher"]')
                page.click('#aba-eap [data-eap-sec="wbs"]')
            alvo = js(c, "document.querySelector('#eap-s-wbs .wbs-fo[open] [data-ir-linha]').dataset.irLinha")
            page.locator("#eap-s-wbs .wbs-fo[open] [data-ir-linha]").first.click()
            page.wait_for_timeout(200)
            r = js(c, """(id) => { const l = [...document.querySelectorAll('#eap-s-contrato .ctr-l')].find(e => e.dataset.id === id);
              return {sec: [...document.querySelectorAll('.eap-sec')].find(s => s.offsetParent !== null).dataset.sec, aberta: !!l && l.open && l.offsetParent !== null}; }""", alvo)
            passo(c, "link folha -> contrato muda para a sub-aba Contrato e abre a linha", r["sec"] == "contrato" and r["aberta"], str(r))
        # botões "ver no mapa" e "abrir prancha": só existem em linhas com `redes`/`pranchas` (o build real as traz)
        page.click("#eap-s-contrato [data-eap-exp='1']")   # os botões ficam nas linhas: abre UC e trechos
        if js(c, "!!document.querySelector('#eap-s-contrato [data-ver-redes]')"):
            page.locator("#eap-s-contrato [data-ver-redes]").first.click()
            page.wait_for_timeout(500)
            r = js(c, """() => { const c = __viz.camadasMapa.valas, conj = new Set(document.querySelector('#eap-s-contrato [data-ver-redes]').dataset.verRedes.split('\\n'));
              let dest = 0, outros = 0; c.layer.eachLayer(l => { if (conj.has(l.feature.properties.rede)) dest += l.options.weight >= 6 ? 1 : 0; else outros += l.options.opacity < 0.5 ? 1 : 0; });
              return {dest, outros, ligada: __viz.map.hasLayer(c.layer)}; }""")
            passo(c, "ver no mapa: liga as valas e destaca os traços da rede", r["ligada"] and r["dest"] >= 1, str(r))
            foto(c, "21_eap_ver_no_mapa")
            page.click("#eapMapaAviso [data-redes-limpar]")
            r = js(c, "(() => { let n = 0; __viz.camadasMapa.valas.layer.eachLayer(l => { if (l.options.weight >= 6) n++; }); return n; })()")
            passo(c, "ver no mapa: 'limpar' desfaz o destaque", r == 0, f"{r} traços ainda destacados")
        else:
            print("  [--]    ver no mapa: nenhuma linha com redes neste HTML (verificação pulada)")
        if js(c, "!!document.querySelector('#eap-s-contrato [data-abrir-prancha]')"):
            pid = js(c, "document.querySelector('#eap-s-contrato [data-abrir-prancha]').dataset.abrirPrancha")
            page.locator("#eap-s-contrato [data-abrir-prancha]").first.click()
            page.wait_for_timeout(1500)
            passo(c, "abrir prancha: liga a prancha da linha", js(c, "(id) => { const P = __viz.PR.find(p => p.id === id); return !!P && (P.mapa.on || !document.querySelector('#folha').hidden); }", pid), pid)
        else:
            print("  [--]    abrir prancha: nenhuma linha com pranchas neste HTML (verificação pulada)")
    for sec in ids:   # nenhuma seção alarga a página, nem no celular
        page.click(f'#aba-eap [data-eap-sec="{sec}"]')
        page.wait_for_timeout(150)
        r = js(c, "({pagina: document.documentElement.scrollWidth <= window.innerWidth + 1, aba: document.querySelector('#aba-eap').scrollWidth <= document.querySelector('#aba-eap').clientWidth + 1})")
        passo(c, f"aba EAP ({sec}): sem rolagem horizontal da página", r["pagina"] and r["aba"], str(r))
    lembrada = js(c, "localStorage.getItem('camadas:eap:secao:' + __viz.D.id)")
    passo(c, "aba EAP: a última sub-aba fica lembrada no localStorage", lembrada == ids[-1], str(lembrada))
    r = js(c, """() => { const a = document.querySelector('#aba-eap');
      return [...a.querySelectorAll('[title]')].some(e => e.title.includes('R$')) || a.textContent.includes('R$'); }""")
    passo(c, "aba EAP: nenhum texto ou dica com preço (R$)", not r)
    page.click("#t-camadas")
    page.wait_for_timeout(300)
    passo(c, "aba EAP: ao sair, o painel volta à largura normal", js(c, "!document.querySelector('aside').classList.contains('ampla')"))


def verificar_final(c: dict) -> None:
    c["page"].wait_for_timeout(300)
    passo(c, "sem rolagem horizontal ao final", js(c, "document.documentElement.scrollWidth <= window.innerWidth + 1"))
    passo(c, "console sem erros", not c["erros"], "; ".join(c["erros"][:5]))
    c["browser"].close()


def roteiro(pw, html: Path, cen: dict, pasta: Path, rel: Relatorio) -> None:
    c = abrir_pagina(pw, html, cen, pasta, rel)
    for secao in (verificar_obra_abertura, verificar_inicio, verificar_mapa, verificar_filtro_etapa, verificar_escopo_tabela, verificar_escopo_valores,
                  verificar_pranchas, verificar_sondagens_fotos, verificar_3d, verificar_v3_arvore, verificar_v3_intervencao,
                  verificar_v3_estacas_mapa, verificar_v3_estacas_3d, verificar_v3_marcos, verificar_area_obra,
                  verificar_obra, verificar_projeto, verificar_contrato_211, verificar_eap_vista):
        secao(c)
    verificar_final(c)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("html", help="HTML gerado (ex.: saida/foz/foz-vilac_camadas_v0.14.0_2026-10-29.html)")
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
