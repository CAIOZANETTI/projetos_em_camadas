---
name: mosaico-drone
description: Monta um mosaico georreferenciado (SIRGAS 2000 / UTM) a partir de fotos nadirais de drone DJI com GPS no EXIF, usando camadas/mosaico.py. Use quando o usuário pedir para montar, refazer ou diagnosticar um mosaico de fotos de drone de uma obra.
---

# Mosaico de fotos de drone

1. **Obter as fotos.** No Google Drive, cada `download_file_content` é gravado num `.txt` JSON com o campo `content` em base64. Decodifique com Python para `dados/<obra>/foto_drone/` sem ler o conteúdo no contexto.
2. **Conferir os metadados** com `camadas.exif.ler_meta`: GPS, `RelativeAltitude`, `FlightYawDegree`, modelo. Se o modelo não estiver em `SENSOR_MM`, adicione a largura do sensor. Sem isso não há GSD.
3. **Rodar** `python -m camadas.mosaico <pasta> saida/<obra>/mosaico.jpg --res 0.04`.
4. **Ler o log e o `.json`**:
   - `GSD ajustado` deve ficar a ±10 % do `EXIF`. Uma diferença maior indica par errado ou terreno muito inclinado;
   - `RMSE vs GPS` em torno de 1 m é o normal para o GPS do drone;
   - `costura mediana` abaixo de ~15 cm (a 2 cm/px) é bom; pares com `residuo_m` acima de 0,5 m merecem olhar;
   - um aviso de "grupos sem ligação" significa que parte do mosaico foi posicionada só pelo GPS.
5. **Inspecionar visualmente**: reduza o JPG (`cv2.resize`) e veja um recorte em resolução cheia numa área com edificações.
6. **Ajustes possíveis**:
   - `--lado 2000` dá mais pontos SIFT;
   - `min_inliers`/`tol_gps_m` no construtor;
   - `--tipo afim` se houver distorção residual;
   - `--sigma-gps` para GPS melhor ou pior.

Limitações: não é ortofoto (há paralaxe de árvores e telhados) e a posição absoluta depende do GPS (~1 m). Para precisão centimétrica é preciso usar pontos de controle em campo ou OpenDroneMap.

> Se houver fotos oblíquas ou prédios altos, prefira a ortofoto verdadeira do SfM (skill `modelo-3d-drone`). O mosaico 2D fica como plano B.
