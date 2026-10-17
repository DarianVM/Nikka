# Guion de narración (español)

**Duración:** ~28 s de voz dentro de un video de 30,5 s · **75 palabras** (forma escrita) · tono documental, sobrio, intensidad creciente hasta el 9 de abril.

| # | Inicio | Texto (subtítulo) | Lectura / dirección |
|---|---|---|---|
| L01 | 0:00.35 | Pudo cambiar la historia de Colombia. | Grave, contenida. Pausa breve al final. |
| L02 | 0:02.20 | Se llamaba Jorge Eliécer Gaitán. | Nombre completo, claro, sin prisa. |
| L03 | 0:04.15 | Hijo de una maestra, estudió derecho en Bogotá y en Roma, | Narrativo, ritmo ágil. |
| L04 | 0:07.48 | y le habló al pueblo como nadie. | Leve calidez, apoyo en "pueblo". |
| L05 | 0:09.19 | En 1929 denunció en el Congreso la masacre de las bananeras. | Firme. "mil novecientos veintinueve". Peso en "masacre". |
| L06 | 0:13.40 | Multitudes lo seguían. Muchos lo veían como el próximo presidente. | Crece la energía; el final abierto, sin triunfalismo. |
| L07 | 0:17.15 | Pero el 9 de abril de 1948, en Bogotá, | Más lento y bajo. "nueve de abril de mil novecientos cuarenta y ocho". |
| — | 0:20.7–0:22.0 | *(silencio)* | Silencio deliberado; la música cae a cero en 0:21.6. |
| L08 | 0:22.00 | le dispararon. | Casi en voz baja, seco, sin dramatizar. |
| L09 | 0:23.15 | Murió esa misma tarde. | Pausado, con peso. |
| L10 | 0:25.00 | Bogotá ardió. | Contundente. |
| L11 | 0:26.20 | Y Colombia nunca volvió a ser la misma. | Frase final deliberada; dejar respirar "la misma". |

Times are from the current render (`out/narration_timing.json`). With a different narrator, `build_audio.py` re-flows the lines automatically (each starts at its target time or 0.12 s after the previous line ends) and the subtitles follow.

## Verificación de cada frase
- "Pudo cambiar…": interpretive hook, framed as possibility, not certainty.
- "Hijo de una maestra": his mother, Manuela Ayala, was a schoolteacher (EcuRed, Biografías y Vidas).
- "derecho en Bogotá y en Roma": Universidad Nacional (1924); Real Universidad de Roma under Enrico Ferri (from 1926).
- "En 1929 denunció en el Congreso la masacre de las bananeras": the September 1929 debate in the Cámara.
- "Muchos lo veían como el próximo presidente": avoids "presidente electo" and any certainty of victory.
- "el 9 de abril de 1948, en Bogotá, le dispararon. Murió esa misma tarde.": shot on Carrera Séptima, died at the Clínica Central that afternoon.
- "Bogotá ardió": the Bogotazo fires in central Bogotá.
- "Y Colombia nunca volvió a ser la misma": interpretive closing line (see research/sources.md §6).

## Recording the final voice (to replace the scratch track)
The current render uses a **scratch** voice (Piper `es-carlfm-x-low`: Castilian Spanish, low fidelity) as a timing guide. For the final version:
1. Record or generate each line separately as `assets/audio/narration/L01.wav` … `L11.wav` (48 kHz, any length, silence is trimmed automatically). Write numbers out as words in the read text (see the `spoken` field in `production/timeline.json`).
2. Voice brief: native Colombian (Bogotá / *rolo*) male, 40–60 years old, deep and clear documentary voice, emotionally controlled; no trailer delivery, no radio effect, no heavy reverb.
3. Run `python3 production/build_audio.py` and then `python3 production/render_video.py`.
