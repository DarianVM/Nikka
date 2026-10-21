# Guion definitivo: «Colombia: cuando la violencia se volvió cotidiana»

**Duración total:** 48,7 s · **voz:** 41,2 s en 14 frases · **120 palabras** · **ritmo previsto:** 6,2 sílabas/s, una narración documental natural, sin prisa.

Los tiempos salen de `production/make_timeline.py`, que cuenta las sílabas del texto *tal como se pronuncia* (con los años en letras), añade pausas de 0,14 s en las comas y de 0,22 s en los puntos interiores, y deja al menos 0,28 s de respiración entre frases. Ningún subtítulo dura menos de 1 s en pantalla.

| # | Inicio–fin | Texto que vas a leer | Subtítulo | Dirección de lectura |
|---|---|---|---|---|
| L01 | 0:00.55–0:04.96 | «Mil novecientos cuarenta y ocho. Liberales y conservadores ya se enfrentan.» | 1948. / Liberales y conservadores / ya se enfrentan. | Sobrio. Pausa corta tras el año. |
| L02 | 0:05.24–0:09.74 | «El nueve de abril asesinan en Bogotá a Jorge Eliécer Gaitán, líder liberal.» | El 9 de abril asesinan en Bogotá / a Jorge Eliécer Gaitán, líder liberal. | El sello rojo cae en «nueve de abril». Nombre completo y claro. |
| L03 | 0:10.02–0:11.93 | «Linchan al tirador, Juan Roa Sierra.» | Linchan al tirador, Juan Roa Sierra. | Informativo, sin dramatizar. |
| L04 | 0:12.21–0:14.61 | «Si alguien más lo ordenó, nunca se probó.» | Si alguien más lo ordenó, / nunca se probó. | Leve suspenso; cierra bajando. |
| L05 | 0:14.89–0:15.70 | «Bogotá arde.» | Bogotá arde. | Seco. Entra sobre el golpe grave. |
| L06 | 0:15.98–0:19.08 | «El Bogotazo se apaga en días. La Violencia, no.» | El Bogotazo se apaga en días. / La Violencia, no. | Bisagra de la pieza: silencio breve antes de «no». |
| L07 | 0:19.36–0:22.73 | «En el campo, ser liberal o conservador puede costar la vida.» | En el campo, / ser liberal o conservador / puede costar la vida. | Las regiones se iluminan mientras hablas. |
| L08 | 0:23.00–0:24.78 | «Cada región vive su propia guerra.» | Cada región vive su propia guerra. | Firme. |
| L09 | 0:25.60–0:29.15 | «Los muertos se estiman entre decenas de miles y más de doscientos mil.» | Los muertos se estiman / entre decenas de miles / y más de doscientos mil. | Contenido; la cifra pesa sola. |
| L10 | 0:29.60–0:31.54 | «Cientos de miles de campesinos huyen.» | Cientos de miles de campesinos huyen. | Más bajo. |
| L11 | 0:32.00–0:36.01 | «En mil novecientos cincuenta y ocho, los partidos pactan el Frente Nacional.» | En 1958, los partidos / pactan el Frente Nacional. | Neutro, casi notarial. |
| L12 | 0:36.29–0:39.33 | «Frena la guerra partidista, no el problema de la tierra.» | Frena la guerra partidista, / no el problema de la tierra. | El contraste recae en «no». |
| L13 | 0:39.61–0:42.80 | «En los sesenta, en esas regiones, nacen nuevas guerrillas.» | En los sesenta, en esas regiones, / nacen nuevas guerrillas. | Sin alarmismo. |
| L14 | 0:43.40–0:46.63 | «¿Qué pasa cuando un país cierra una guerra sin cerrar sus causas?» | ¿Qué pasa cuando un país cierra / una guerra sin cerrar sus causas? | Pregunta real, no retórica. Deja respirar el final. |
| — | 0:46.73–0:48.73 | *(sin voz: tarjeta de título)* | — | — |

## Por qué cada frase es defendible
- **L01:** la confrontación partidista era anterior al 9 de abril (Boyacá y Santanderes desde 1946). En pantalla: «Desde 1946… ya había violencia partidista en regiones como Boyacá y los Santanderes».
- **L02:** la fecha, el lugar y el cargo (jefe liberal desde 1947) están documentados. Se dice «asesinan», no quién lo ordenó.
- **L03–L04:** Roa Sierra fue señalado como el tirador y linchado. La autoría intelectual nunca se probó. En pantalla, dos bloques separados: **DOCUMENTADO** y **SIN ESCLARECER**.
- **L05–L06:** distinguen el estallido urbano (días) del periodo (más de una década) sin confundirlos.
- **L07–L08:** persecución por filiación partidista con actores distintos según la región, como se ve en el mapa.
- **L09:** un rango que cubre las estimaciones académicas (57.700 en BanRep 2019; 134.800 en Guzmán y otros, 1962; unas 200.000 en la cifra más difundida). En pantalla se precisan el autor y el periodo de cada una.
- **L10:** formulación prudente. La estimación de 2 millones aparece atribuida en pantalla, no en la voz.
- **L11–L12:** el pacto bipartidista redujo la violencia entre partidos, pero dejó sin resolver el problema agrario.
- **L13:** las FARC (Marquetalia, Tolima) y el ELN (San Vicente de Chucurí, Santander) nacen en regiones marcadas en el mapa. En pantalla: «antecedentes, no causa única».
- **L14:** la pregunta histórica que pide el encargo.

## Grabación de tu voz
1. Graba una toma continua y léela con el video en silencio de fondo, siguiendo los subtítulos. O graba frase por frase y móntalas en tu editor en los tiempos de la tabla.
2. Formato recomendado: WAV de 48 kHz y 24 bits, en mono, sin reverberación. Objetivo de mezcla: la voz a unos −16 LUFS sobre la pista del video (que está a −20 LUFS).
3. Si tu lectura queda más rápida o más lenta, hay dos opciones:
   - **En tu editor:** monta la voz sobre `out/la_violencia_tiktok_1080x1920.mp4` (la música ya deja hueco en las frases y en la banda de 1–4 kHz).
   - **Reconstruyendo:** ajusta `RATE` (o los tiempos `earliest` de cada frase) en `production/make_timeline.py` y vuelve a ejecutar el pipeline. Si guardas tu voz como `assets/voz/narracion.wav`, `build_audio.py` genera además `out/mezcla_con_voz.wav`.
