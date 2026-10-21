# Colombia: cuando la violencia se volvió cotidiana

Microdocumental vertical para TikTok (48,7 s) sobre el asesinato de Jorge Eliécer Gaitán, el Bogotazo y La Violencia. Es motion graphics 2D editorial, hecho **íntegramente en código**: Python con Pillow, NumPy, SciPy y Shapely, más FFmpeg.

**No contiene voz.** Ni narración sintética ni locución: la pista de audio es música y efectos originales, preparados para que el autor grabe encima su propia voz. **No se usó Magnific en ninguna fase.**

## Entregables

| # | Entregable | Archivo |
|---|---|---|
| 1 | Video final: MP4 vertical 1080 × 1920, 30 fps, H.264 + AAC, subtítulos integrados | `out/la_violencia_tiktok_1080x1920.mp4` |
| 2 | Guion definitivo con marcas de tiempo e indicaciones de lectura | `script/guion.md` |
| 3 | Subtítulos SRT (27 eventos, sincronizados con el guion) | `out/subtitulos.srt` |
| 4 | Storyboard completo por escena (composición, cámara, transiciones, sonido, fuentes) | `script/storyboard.md` |
| 5 | Investigación y fuentes con enlaces directos | `research/fuentes.md` |
| 6 | Proyecto editable y recursos: generadores de línea de tiempo, imagen y audio; mapa; tipografías; stems | `production/`, `assets/`, `out/*.wav` |
| 7 | Nota técnica (abajo) | — |

## Nota técnica: medida con ffprobe y ebur128 sobre el archivo exportado

| Propiedad | Valor real |
|---|---|
| Resolución | 1080 × 1920 (9:16, vertical) |
| Duración | 48,73 s (vídeo de 1.461 fotogramas, 48,70 s) |
| Fotogramas | 30 fps constantes |
| Vídeo | H.264 High, 4:2:0 de 8 bits (yuv420p), CRF 17 con tope de 16 Mb/s (13,5 Mb/s de media), `+faststart` |
| Color | Rec. 709 (`colorspace`, `primaries` y `transfer` bt709), rango limitado (tv). La conversión de RGB a YUV usa la matriz BT.709 |
| Audio | AAC-LC, 48 kHz, estéreo, 256 kb/s |
| Sonoridad de la pista (sin voz) | −20,0 LUFS integrados, pico −3,1 dBFS, LRA 9,7 LU |
| Tamaño | 83,6 MB |
| Marcas de agua | Ninguna |
| Voz | Ninguna (ni sintética ni grabada) |

La pista se dejó en −20 LUFS a propósito: con la voz a unos −16 LUFS, la mezcla final quedará cerca de −14 LUFS, el valor habitual en redes. La música baja 5 dB durante cada frase prevista y tiene un valle en 1–4 kHz para dejar sitio a la voz.

Control de calidad realizado:
- hoja de contacto cada 2 s del MP4 ya codificado (`out/qc/`, no versionada);
- revisión a resolución completa de los fotogramas con más texto;
- comprobación de que el texto esencial queda dentro de las zonas seguras (x 60–940; subtítulos en y ≈ 1300);
- subtítulos de dos líneas como máximo, sin solaparse entre eventos;
- SRT validado con ffprobe;
- sonoridad y pico medidos;
- duración y formato verificados.

En el control se corrigieron:
- desajustes de línea base en los subtítulos;
- solapes entre eventos de subtítulo;
- un periódico que se salía del cuadro;
- un hueco negro entre las escenas 3 y 4;
- etiquetas que invadían la zona de botones de TikTok;
- un fallo de Pillow con `MaxFilter(1)`.

## Limitaciones reales y cómo terminar la pieza
- **Fotografías de archivo:** este entorno bloquea Wikimedia, Banrepcultural y archive.org. No se descargó ni se fingió ninguna. Gaitán aparece como **silueta simbólica** («ILUSTRACIÓN SIMBÓLICA · NO ES UN RETRATO»), y la ciudad y el campo como recreaciones etiquetadas. Para usar una foto verificada, colócala en `assets/archival/gaitan.jpg` (y comprueba su licencia): el renderizador la integra en duotono y quita la etiqueta de silueta.
- **Fuentes:** se consultaron mediante búsquedas, no abriendo las páginas (bloqueadas). Revisa las marcadas con ★ en `research/fuentes.md` antes de publicar.
- **Tiempos de la voz:** están planificados a 6,2 sílabas/s. Si tu lectura difiere, ajusta `RATE` o los tiempos mínimos en `production/make_timeline.py` y reconstruye; las imágenes, los efectos y los subtítulos se recolocan solos.

## Reconstruir
```bash
pip install numpy scipy pillow shapely      # y ffmpeg con libx264
python3 production/make_timeline.py         # guion -> production/timeline.json + out/subtitulos.srt
python3 production/build_audio.py           # música, efectos, mezcla (y mezcla_con_voz si existe assets/voz/narracion.wav)
python3 production/render_video.py          # unos 4 min con 4 núcleos -> out/la_violencia_tiktok_1080x1920.mp4
python3 production/render_video.py --preview 12.5 22.0   # fotogramas sueltos en out/preview/
```

## Estructura
```
production/make_timeline.py   guion, ritmo de lectura, cortes de subtítulos, SRT
production/render_video.py    escenas, mapa (proyección y cámara), tipografía, grano, exportación H.264
production/build_audio.py     instrumentos y efectos sintetizados, atenuación para la voz, limitador, sonoridad
assets/geo/                   Colombia por departamentos y países vecinos (Natural Earth, dominio público)
assets/fonts/                 Bebas Neue, Oswald, Old Standard TT, Special Elite (OFL / Apache)
out/musica.wav, efectos.wav   stems separados para tu editor
out/mezcla_sin_voz.wav        la pista del MP4
```
