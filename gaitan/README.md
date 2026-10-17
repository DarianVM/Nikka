# Jorge Eliécer Gaitán — *El hombre que pudo cambiar Colombia*

A 30-second vertical documentary for TikTok, built entirely from code: Python with Pillow, NumPy and SciPy, plus FFmpeg.

## Deliverables

| # | Deliverable | Status | File |
|---|---|---|---|
| 1 | Vertical MP4 | ✅ **Rendered**, but it is a *draft cut*: illustrated plates stand in for the archival photos, and a scratch voice stands in for the final narrator (see "What is not finished") | `out/gaitan_tiktok_1080x1920.mp4` |
| 2 | Spanish narration script | ✅ Done (75 words, every line fact-checked) | `script/narracion.md` |
| 3 | Shot-by-shot breakdown with timestamps | ✅ Done | `script/shotlist.md` |
| 4 | Historical sources and archival image URLs | ✅ Done | `research/sources.md`, `assets/manifest.json` |
| 5 | Asset attribution and licensing notes | ✅ Done (Commons licences still need a human check on the file pages) | `assets/manifest.json` |
| 6 | Technical report | ✅ Below | — |
| 7 | Separate audio mix and stems | ✅ Final mix plus narration, music and SFX stems (48 kHz WAV) | `out/mix.wav`, `out/narration.wav`, `out/music.wav`, `out/sfx.wav` |
| — | Subtitles (also burned into the video) | ✅ | `out/subtitles.srt` |

## What is not finished, and why

The build container's network policy allows only package registries and GitHub. These hosts were blocked:

- `upload.wikimedia.org`, `commons.wikimedia.org`, `archive.org`, `banrepcultural.org`: **no archival photographs could be downloaded.** The 1936 Commons portrait was imported server-side into the Magnific library (proving the URL is valid), but Magnific's file host `pikaso.cdnpk.net` is also blocked, so it could not come back into the container.
- Magnific / ElevenLabs output, served from the same blocked CDN: **no professional Colombian voice or AI-generated music could be used.**

The draft cut therefore uses:

1. **Illustrated plates instead of photos**, each tagged "ILUSTRACIÓN" on screen: typographic portrait and name, newsprint layouts, a radio microphone, a crowd of ink silhouettes, a burning city skyline. **No image is presented as a historical photograph.**
2. **A scratch narration** from Piper TTS (`es-carlfm-x-low`). It is Castilian rather than Colombian, low-fidelity and somewhat synthetic, so it is **not publishable**. It exists so the timing, subtitles and mix can be built and checked.
3. **An original score and sound design synthesized in code.** This is original and royalty-free, but simpler than a recorded or AI-generated orchestral score.

### Finishing the final cut (about 10 minutes of compute once the hosts are reachable)
```bash
# 1. allow upload.wikimedia.org in the environment's network settings, then:
production/fetch_assets.sh                   # downloads the verified photos into assets/archival/
# 2. put the Colombian narrator's takes in assets/audio/narration/L01.wav … L11.wav
#    (optional) put a licensed score in assets/audio/music.wav
python3 production/build_audio.py            # mixes everything, writes out/narration_timing.json
python3 production/render_video.py           # photos replace the illustrated plates automatically
```
The photo code path is tested: it was rendered with neutral test cards, which were then deleted. Captions name each photo's real event and date. Check each Commons licence before publishing (see `assets/manifest.json`). The *Marcha del Silencio* image has an unknown author, so it stays commented out in the fetch script until its provenance is confirmed.

## Technical report (measured with ffprobe / ebur128 on the rendered file)

| Property | Value |
|---|---|
| Resolution | 1080 × 1920 (9:16 vertical) |
| Duration | 30.50 s (915 frames) |
| Frame rate | 30 fps, constant |
| Video | H.264 High profile, yuv420p, CRF 19 capped at 12 Mb/s (≈12.3 Mb/s average), `+faststart` |
| Audio | AAC-LC, 48 kHz, stereo, 256 kb/s |
| Loudness | −14.1 LUFS integrated, LRA 3.7 LU, true peak −1.5 dBTP (no clipping) |
| File size | 47.9 MB |

QC performed: a contact sheet at 1-second intervals from the encoded MP4, a full-resolution compression check, safe-area checks (subtitles at y 1335–1480, content between x 90 and 960), a per-second level scan of the mix, a spectral balance check (music and SFX high-passed at 42 Hz and 32 Hz for phone speakers), and subtitle timing generated from the measured narration timing. Fixed during QC: overlay compositing that blanked frames, a blocky fire texture, mid-phrase subtitle breaks, headline collisions, a narration overrun past the rupture point, and a subtitle overlapping the title card.

## Editorial choices
- The disputed **birth year** (1898 vs. 1903) and the **birthplace** dispute are never stated. The title card shows only the date of death.
- No claim is made about **who ordered** the assassination, and Gaitán is never called "president-elect". The script says "Muchos lo veían como el próximo presidente."
- There is **no depiction of the shooting**, no gun, no blood, and no gunshot sound. The moment is a silence, a muffled thud and a torn image.
- Death tolls (Banana Massacre, Bogotazo) are omitted because estimates vary widely.

## Layout
```
production/timeline.json     narration lines, section times, sound cues (drives audio and video)
production/build_audio.py    narration processing, synthesized score and SFX, ducking, loudness
production/render_video.py   2D motion graphics renderer to H.264 MP4
production/fetch_assets.sh   archival downloads (needs upload.wikimedia.org)
assets/fonts/                Playfair Display, Oswald (OFL), Special Elite (Apache 2.0)
```
Requirements: Python 3.11+, `pip install numpy scipy pillow piper-tts`, ffmpeg with libx264.
