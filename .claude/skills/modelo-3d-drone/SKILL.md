---
name: modelo-3d-drone
description: Reconstrói o 3D (SfM com pycolmap em CPU), separa fotos nadirais e oblíquas, densifica por estéreo e gera ortofoto verdadeira + MDS a partir de fotos de drone DJI, com camadas/sfm.py. Use quando o usuário trouxer fotos de fotogrametria e/ou em perspectiva, pedir 3D, nuvem de pontos, ortofoto, MDS, ou reclamar de prédio torto / costura na ortofoto.
---

# 3D e ortofoto a partir das fotos do drone

```bash
pip install pycolmap      # 4.x, CPU
python -m camadas.sfm dados/<obra>/foto_drone saida/<obra>/sfm --denso --orto 0.04
```
Use **todas** as fotos juntas (nadirais + oblíquas): as oblíquas amarram as poses e cobrem fachadas.

## O que sai
- `sfm.json` — câmeras (pose, `angulo_vertical`, `tipo` nadir/obliqua), RMSE contra o GPS, reprojeção.
- `nuvem.ply` (UTM, double) e `nuvem.npz` — Z = altura sobre a decolagem (o altímetro absoluto do DJI é vago);
  a cota vem do controle vertical (abaixo).
- `ortofoto.jpg` + `.jgw/.prj/.json` — ortofoto verdadeira (cada pixel projetado pelo MDS na foto mais a prumo).
- `ortofoto_mds.png` — MDS 16 bits em cm acima de z_min + world file.

## Leitura do log
- reprojeção < 1 px e todas as fotos registradas ⇒ SfM bom;
- `RMSE GPS` ~1 m é o GPS do drone; corrija o absoluto com `controle_absoluto` (skill `georef-pranchas`);
- cada par estéreo é validado contra os pontos esparsos (`desvio`); pares com desvio > 1 m são descartados;
- "geometria ruim" = base/rotação grandes demais para retificação — normal para muitos pares.

## Cota absoluta (datum vertical)
O Z da nuvem é altura sobre a decolagem e o SfM pode sair inclinado (Foz: 13 mm/m em N). Com sondagens de cota de
boca conhecida, declare no `obra.json`:
```json
"controle_vertical": {"fonte": "cota de boca dos furos SPT, relatório ...", "campo_cota": "cota_boca", "juntar_variantes_A": true}
```
`obra.etapa_controle_vertical` → `sfm.ajustar_vertical`: terreno = percentil 10 da nuvem num raio de 2/3/5 m em volta
de cada furo; furos em copa/edificação caem pela rejeição robusta (|d − mediana| > max(3·MAD·1,4826; 1,5 m));
plano z → cota com ≥ 6 furos, senão só deslocamento. Critério: validação cruzada (deixa-um-fora) ≤ 0,5 m.
`sfm.aplicar_vertical` leva nuvem, câmeras e MDS (GeoTIFF) para cota; o popup de cada sondagem mostra boca − terreno.
Foz: plano em 12 furos, validação cruzada 0,23 m (a constante dava 0,59 m); descartados SP-03, SP-07, SP-16.

## Prédio torto na ortofoto
Sinal de MDS sem dados no telhado (buraco preenchido com a cota do chão ⇒ paralaxe). Verifique a
fração de células válidas na área (`sfm.mds(...)["valido"]`). Correções, em ordem: mais pares
(`pares_estereo` com `base_max=1.0, ang_max=50` — padrão atual), `lado=1600`, `fechar_telhado_m`
maior. Em Foz isso levou a área norte de ~0 a 300 mil pontos e endireitou o prédio administrativo.

## Limites
Sem GPU não há MVS denso do COLMAP; o estéreo SGBM cobre bem telhados e pátios e mal fachadas.
Para malha texturizada/fachadas completas: OpenDroneMap (`--mesh-size`, GPU opcional) com as mesmas fotos.
O mosaico 2D (`camadas.mosaico`, skill `mosaico-drone`) continua útil quando o SfM falha
(poucas fotos/pouca sobreposição) — atenção ao rumo ~90°, corrigido em `casar`.
