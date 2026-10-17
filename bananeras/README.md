# *La Masacre de las Bananeras* — Ciénaga, 1928

A vertical motion-graphics documentary of about 43 seconds, built entirely in code: Python with Pillow, NumPy and SciPy, plus FFmpeg. Every image is drawn by `production/render_video.py`. No photographs are used, and nothing imitates archival footage.

## Deliverables

| # | Deliverable | Status | File |
|---|---|---|---|
| 1 | Vertical MP4 | ✅ Rendered and checked (see the technical report). **The soundtrack is music and SFX only, with no narrator.** The script still plays as burned-in subtitles. | `out/bananeras_1080x1920.mp4` |
| 2 | Spanish narration script | ✅ 103 words, fact-checked line by line | `script/narracion.md` |
| 3 | Historical sources with URLs | ✅ Established facts and disputed points listed separately | `research/sources.md` |
| 4 | Production note: uncertainties and limits | ✅ Below | — |
| — | Subtitles (burned in and as SRT) | ✅ | `out/subtitles.srt` |
| — | Audio stems (48 kHz WAV) | ✅ narration, music, SFX, mix | `out/*.wav` |

## Storyboard as built (times come from the measured narration)

| Time | Scene | Visual | On-screen text |
|---|---|---|---|
| 0–2 s | Hook | A banana leaf on green paper. Its outline **morphs into the map of Colombia** and its veins dissolve into the map lines. | COLOMBIA, 1928 |
| 2–4.5 s | Map | Log-zoom to the Caribbean coast. The Ciénaga Grande lagoon, the hatched banana zone and the Santa Marta–Ciénaga–Fundación railway draw on. | MAR CARIBE · ZONA BANANERA |
| 4.5–7 s | Plantation | Parallax rows of banana plants, a distant freight train loaded with bunches, workers carrying bunches across the rails | RIQUEZA PARA LA EXPORTACIÓN / QUIENES COSECHAN: SIN CONTRATO DIRECTO |
| 7–10 s | Petition | The rails' ties give way to the ruled lines of a typed *pliego de peticiones*, whose six demands type themselves. A *vale* (company-store scrip) slides in. | NOVIEMBRE DE 1928 |
| 10–13 s | Strike | Dark map: red rings spread from town to town along the railway while workers and families gather. A headline is rubber-stamped on. | UNA HUELGA MASIVA |
| 13–15 s | Actors | Three separate cards: UNITED FRUIT COMPANY (US company), GOBIERNO DE COLOMBIA (Abadía Méndez), EJÉRCITO NACIONAL (Gen. Cortés Vargas). The arrow "envió tropas" runs only from the government to the army. | — |
| 15–20 s | Ciénaga | Night square by the railway station under flickering lamps. Rim-lit silhouettes of workers and families fill it, then a line of soldiers with shouldered rifles closes in. Muffled march. | 5–6 DE DICIEMBRE DE 1928 · CIÉNAGA, MAGDALENA |
| ≈20.2 s | Rupture | **Hard cut to black.** One thin red tear crosses the screen. The music stops dead. One muffled thud, then near silence. No gun, no muzzle flash, no blood. | — |
| 21–24 s | Aftermath | The same square, empty at grey dawn: a machete, a straw hat and scattered papers (the petition and a *vale*) | DETENCIONES · PERSECUCIÓN |
| 24–28 s | The count | A newspaper page emerges from the dark. A **split-flap counter** rolls and lands on 47, rolls again to 1000, then spins and can never settle. | muertos reconocidos por el jefe militar → más de mil, según otras estimaciones → LAS CIFRAS SIGUEN EN DEBATE |
| 28–30.5 s | Gaitán | Letters fly in from the newsprint to spell his name. An original engraved-medallion portrait inks in, labelled ILUSTRACIÓN. | JORGE ELIÉCER GAITÁN |
| 30.5–34 s | Denunciation | An investigation file slides in, and on "Congreso" a stamp lands on it | LA DENUNCIA · DEBATE EN LA CÁMARA, SEPTIEMBRE DE 1929 |
| 34–36 s | The country | Map of Colombia: red lines run from Bogotá to the country's cities | ANTE TODO EL PAÍS |
| 36–39.5 s | Lesson | Slow push-in on one composition: the worker's machete and hat, the newspaper and Gaitán's portrait. The railway becomes a timeline (1928 · 1929 · …) that runs on into darkness. | 1928 · 1929 · … |
| 39.5–43 s | End | The page folds down into black. The last line types on, and the gold musical sting lands. | LA HISTORIA NO TERMINÓ AQUÍ. |

**Creative element: the counter that never stops.** A split-flap board is the kind of device used to announce a final figure. Here it cannot announce one. It lands on the commander's 47, gets pushed to "more than a thousand", then spins into question marks. That turns the historiographic uncertainty into the image itself, without choosing a number or dramatizing one. It is backed by a second through-line: the railway that carried the bananas out becomes, in turn, the lines of the petition, the place of the massacre (the station square) and the closing timeline that runs off into the dark.

## Sound
**The narrator is left out of the mix** (`"narration_in_mix": false` in `production/timeline.json`). The scratch voice is still synthesized because its measured timing drives the subtitles, scene cuts and sound cues, but it is not heard. With no voice to make room for, the music is no longer ducked. Set the flag to `true` to put a narrator back in.

- **Score**, original and synthesized in `build_audio.py`. D minor low strings over a *muted* cumbia pulse (tambora on 1 and 3, a guache shaker accenting the off-beats) and a lone breathy gaita (cane-flute) lament. It is not party music. In the army section it turns to a muffled march pulse with timpani and a rising string cluster, which **stops dead at the rupture**. After the massacre there are only a thin high tone, wind and a slow gaita lament. Under Gaitán the strings climb, the timpani pulse and the brass swell. The ending is a single D-minor sting.
- **SFX**: railway clacks, steam, insects and leaves at the opening; paper and a rubber stamp for the petition; measured boots; one restrained low thud with a dry, low-passed crack at the rupture (no gunfire volley); wind and paper in the empty square; printing-press clacks; a paper fold before the end card.
- **Mix**: music plus SFX with the low end high-passed for phone speakers. When narration is in the mix, the music ducks about 9 dB under the voice. The master is normalized to about −14 LUFS with true peak at −1.4 dBTP.

## Technical report (measured with ffprobe and ebur128 on the encoded file)

| Property | Value |
|---|---|
| Resolution | 1080 × 1920, native vertical layout (nothing cropped from 16:9) |
| Duration | 43.1 s (1,294 frames). "Approximately 40 s": the extra 3 s are the post-massacre silence and the end-card hold. The words were not sped up. |
| Frame rate | 30 fps, constant |
| Video | H.264 High profile, yuv420p, CRF 18 capped at 14 Mb/s, `+faststart` |
| Audio | AAC-LC, 48 kHz stereo, 256 kb/s |
| Loudness | −14.6 LUFS integrated, LRA 8.2 LU (no voice holding the level steady), true peak −1.4 dBFS |
| Safe areas | Key text stays between x 90 and 960 (clear of the right-hand buttons). Subtitles sit at y ≈1372–1530, above the caption area. |

QC on the encoded MP4: a 1 fps contact sheet, full-resolution stills of every scene, a per-second level scan of the mix (the only dip is the intended silence after the rupture), and peak checks on every stem.

## What is not finished, and why

1. **There is no audible narrator.** The video carries the script as subtitles. The scratch voice that sets the timing was not good enough to keep in the mix, for these reasons. The brief asks for natural Colombian Spanish. In this container:
   - A Colombian ElevenLabs voice ("Valentina Santos") was generated through Magnific, but its file host `pikaso.cdnpk.net` is blocked by the network policy, so the audio could not come back in.
   - Hugging Face, which hosts the better Latin-American Piper voices, is also blocked.
   - What remains is Piper's `es-carlfm-x-low` from GitHub. It was **re-phonemized with espeak's Latin-American rules (`es-419`)**, so it uses seseo ("Ciénaga" with /s/, not /θ/) and yeísmo. It is still low-bandwidth (16 kHz), fairly flat in intonation and recognizably synthetic. **It is not publishable as the final voice.**
   - A second Piper voice (`es-mls_9972-low`) was more expressive, but it inserted pauses of up to 1.8 s mid-sentence and murmured after line ends, so it was rejected.
2. **The archival-source checks were indirect.** Wikipedia, Banrepcultural and archive.org could not be opened, so the facts come from search summaries cross-checked across sources (see `research/sources.md`). A person should open the key sources before publishing.
3. The score is original and royalty-free, but it is synthesized. It is simpler than a recorded orchestral score.

### Finishing the final cut
```bash
# 1. record the 8 lines of script/narracion.md (Colombian narrator) as
#    assets/audio/narration/L1.wav L2.wav L3a.wav L3b.wav L4.wav L5.wav L6.wav L7.wav
#    (optional) drop a licensed score at assets/audio/music.wav
# set "narration_in_mix": true in production/timeline.json
python3 production/build_audio.py     # re-times sections, cues and subtitles from the real takes
python3 production/render_video.py    # about 4–5 minutes on 4 cores
```
Every scene boundary and sound cue comes from the measured narration (`section_times()` in `build_audio.py`), so a professional take with different pacing re-times the whole film automatically.

## Historical uncertainties (kept out of the narration or flagged)
- **The death toll** is disputed: 47 acknowledged by Gen. Cortés Vargas, against estimates of hundreds to roughly 2,000. The video shows it as disputed and never gives a single number as the answer.
- **When Gaitán visited the zone** (Dec. 1928 vs. early 1929) and **how long the debate lasted** (3–6 Sept. 1929 vs. "15 days") vary between sources. The video says only "en 1929" and "septiembre de 1929".
- **Wages:** some historians argue that zone wages were relatively high for rural Colombia, so the video does **not** say wages were low. It shows the documented grievances: insurance, rest days, scrip, subcontracting, housing and hospitals.
- **What came next:** the ending suggests the story continued (Gaitán's rise) without claiming the massacre caused later events.
- **Depictions:** the people are generic, period-plausible illustrations (straw hats, cotton shirts, kepis, a 1920s station and steam freight). Gaitán's portrait is an original stylized illustration, labelled ILUSTRACIÓN on screen. The newspaper is generic and carries no real masthead. The *vale* uses a generic design with no company mark.

## Layout
```
production/timeline.json     narration lines (text, TTS spelling, earliest start), voice settings
production/build_audio.py    narration, synthesized score and SFX, ducking, loudness, timing JSON
production/render_video.py   2D motion-graphics renderer to H.264 MP4 (+ SRT)
script/narracion.md          final Spanish script with line-by-line verification
research/sources.md          sources, disputed points and how each is handled
assets/fonts/                Playfair Display, Oswald, Old Standard, Bebas Neue (OFL), Special Elite (Apache 2.0)
```
Requirements: Python 3.11+ and `pip install numpy scipy pillow piper-tts`, plus ffmpeg with libx264. The scratch voice downloads itself from GitHub into `assets/voices/` (git-ignored).
