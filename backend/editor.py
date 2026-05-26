"""
GreatDeal · Video editor module (v0.2 — secciones)
Pipeline FFmpeg estructurada por secciones de propiedad.
"""
import subprocess
import shutil
import json
from pathlib import Path
from typing import Optional

FONT_BOLD = "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"

# Fallback fonts
if not Path(FONT_BOLD).exists():
    FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
if not Path(FONT_REG).exists():
    FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

W, H = 540, 960


def _esc(text: str) -> str:
    """Escape text for ffmpeg drawtext filter."""
    if not text:
        return ""
    # Escape backslashes, single quotes, colons, percent signs
    return (text.replace("\\", "\\\\")
                .replace("'", "\\'")
                .replace(":", "\\:")
                .replace("%", "\\%"))


def run(cmd: list, label: str = "") -> tuple[bool, str]:
    print(f"[ffmpeg] {label or cmd[0]}...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return False, r.stderr[-1500:]
    return True, ""


def probe_duration(file: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", file],
        capture_output=True, text=True
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def normalize_clip(input_file: str, output_file: str,
                   enhance: bool = False) -> tuple[bool, str]:
    """Scale to 540x960 vertical, 30fps, with color correction.
    If enhance=True, apply 'pro cameraman' look: denoise + lift shadows +
    boost contrast/saturation + unsharp + sutil vignette.
    """
    if enhance:
        # Cinematic enhancement pipeline:
        # 1. hqdn3d   → denoise (limpia el grano de cámaras malas)
        # 2. eq       → lift shadows, boost contrast/saturation/gamma
        # 3. unsharp  → nitidez tipo lente bueno
        # 4. vignette → sutil viñeta cinematográfica
        vf = (
            f"scale={W}:{H}:flags=lanczos:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,"
            "hqdn3d=1.5:1.5:6:6,"
            "eq=brightness=0.06:contrast=1.20:saturation=1.32:gamma=1.05,"
            "unsharp=5:5:1.0:5:5:0.0,"
            "vignette=PI/5"
        )
        # Better quality preset when enhancing
        preset, crf = "fast", "21"
    else:
        vf = (
            f"scale={W}:{H}:flags=bilinear:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,"
            "eq=brightness=0.03:saturation=1.18:contrast=1.08:gamma=0.97"
        )
        preset, crf = "ultrafast", "23"

    cmd = [
        "ffmpeg", "-y", "-i", input_file,
        "-vf", vf,
        "-r", "30",
        "-c:v", "libx264", "-preset", preset, "-crf", crf,
        "-pix_fmt", "yuv420p", "-an",
        output_file
    ]
    return run(cmd, f"normalize{' +IA' if enhance else ''} {Path(input_file).name}")


def trim_clip(input_file: str, output_file: str,
              start: float, duration: float) -> tuple[bool, str]:
    """Trim a clip to a specific time range."""
    cmd = [
        "ffmpeg", "-y", "-i", input_file,
        "-ss", str(start), "-t", str(duration),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-an",
        output_file
    ]
    return run(cmd, f"trim {Path(input_file).name}")


def speedup_clip(input_file: str, output_file: str,
                 speed: float = 3.0) -> tuple[bool, str]:
    """Apply speed change to a video clip (no audio).
    speed=3.0 → 3x faster (15s becomes 5s)."""
    cmd = [
        "ffmpeg", "-y", "-i", input_file,
        "-filter:v", f"setpts=PTS/{speed}",
        "-r", "30",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-an",
        output_file
    ]
    return run(cmd, f"speed {speed}x {Path(input_file).name}")


def add_text_overlay(input_file: str, output_file: str,
                     headline: str, subline: str,
                     duration: float) -> tuple[bool, str]:
    """Add headline + subline overlay CENTERED VERTICALLY (zona media del video).
    - Headline: 36px bold, top at y=446 (W=540, H=960)
    - Subline: 22px regular, top at y=492
    - Both horizontally centered
    - Strong shadow + outline for legibility (sin gradient — los subtítulos
      automáticos ocupan el tercio inferior).
    If both empty, just copies the file (no re-encode = faster)."""
    if not headline and not subline:
        shutil.copy(input_file, output_file)
        return True, ""

    fade_out_start = max(0.1, duration - 0.3)
    filters = []
    # Gradient sutil en el centro vertical (legibilidad sin gastar tanta CPU como borderw)
    filters.append(
        "drawbox=x=0:y=(ih/2)-60:w=iw:h=120:color=black@0.30:t=fill"
    )
    if headline:
        # Headline centrado vertical (ligeramente sobre el centro)
        # Sin borderw (consume mucha CPU en Render Starter) — solo sombra fuerte
        filters.append(
            f"drawtext=fontfile={FONT_BOLD}:text='{_esc(headline)}':"
            f"fontsize=36:fontcolor=white:"
            f"x=(w-text_w)/2:y=(h-text_h)/2-25:"
            f"shadowx=3:shadowy=3:shadowcolor=black@0.9"
        )
    if subline:
        # Subline justo abajo del headline (centro + 25)
        filters.append(
            f"drawtext=fontfile={FONT_REG}:text='{_esc(subline)}':"
            f"fontsize=22:fontcolor=0xe5e5e5:"
            f"x=(w-text_w)/2:y=(h-text_h)/2+25:"
            f"shadowx=2:shadowy=2:shadowcolor=black@0.8"
        )
    filters.append(f"fade=t=in:st=0:d=0.3,fade=t=out:st={fade_out_start}:d=0.3")
    filter_complex = ",".join(filters)

    cmd = [
        "ffmpeg", "-y", "-i", input_file,
        "-vf", filter_complex,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-an",
        output_file
    ]
    return run(cmd, f"overlay {Path(output_file).name}")


def build_logo_slide(logo_file: str, output_file: str,
                     duration: float = 2.0) -> tuple[bool, str]:
    """Generate a logo slide: black background, centered logo, fade in/out."""
    fade_out_start = max(0.1, duration - 0.4)
    # Scale logo to max 400px wide, keep aspect, then overlay centered
    filter_complex = (
        f"[1:v]scale=400:-1:force_original_aspect_ratio=decrease,format=rgba[logo];"
        f"[0:v][logo]overlay=(W-w)/2:(H-h)/2,"
        f"fade=t=in:st=0:d=0.4,fade=t=out:st={fade_out_start}:d=0.4"
    )
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i",
        f"color=c=black:s={W}x{H}:r=30:d={duration},format=yuv420p",
        "-i", logo_file,
        "-filter_complex", filter_complex,
        "-r", "30",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-an",
        output_file
    ]
    return run(cmd, "logo slide")


def build_cta_v2(output_file: str,
                 info_line: str, precio_line: str, tagline: str,
                 duration: float = 5.0) -> tuple[bool, str]:
    """White-label CTA card.
    - Black background
    - Info line (e.g. '180 m² · 3 dorm · 2 baños') in white above the precio rect
    - Precio in BLACK text inside a WHITE filled rectangle
    - Tagline (editable, e.g. 'Vivir distinto') below in muted white
    - Subtle vignette + fade in/out
    """
    # White rectangle dimensions
    rect_w, rect_h = 420, 120
    rect_x = (W - rect_w) // 2          # =60
    rect_y = H // 2 - rect_h // 2       # =420

    filters = ["vignette=PI/4"]

    if info_line:
        filters.append(
            f"drawtext=fontfile={FONT_REG}:text='{_esc(info_line)}':"
            f"fontsize=30:fontcolor=white:"
            f"x=(w-text_w)/2:y={rect_y - 75}"
        )
    if precio_line:
        # White filled rectangle
        filters.append(
            f"drawbox=x={rect_x}:y={rect_y}:w={rect_w}:h={rect_h}:color=white:t=fill"
        )
        # Black precio text centered over rectangle
        filters.append(
            f"drawtext=fontfile={FONT_BOLD}:text='{_esc(precio_line)}':"
            f"fontsize=48:fontcolor=black:"
            f"x=(w-text_w)/2:y={rect_y + (rect_h - 48) // 2 - 2}"
        )
    if tagline:
        filters.append(
            f"drawtext=fontfile={FONT_REG}:text='{_esc(tagline)}':"
            f"fontsize=28:fontcolor=0xcbd5e1:"
            f"x=(w-text_w)/2:y={rect_y + rect_h + 60}"
        )

    filters.append(
        f"fade=t=in:st=0:d=0.5,fade=t=out:st={duration - 0.5}:d=0.5"
    )
    filter_complex = ",".join(filters)

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i",
        f"color=c=black:s={W}x{H}:r=30:d={duration},format=yuv420p",
        "-vf", filter_complex,
        "-r", "30",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-an",
        output_file
    ]
    return run(cmd, "CTA card v2")


def concat_clips(clips: list[tuple[str, float]], output_file: str) -> tuple[bool, str]:
    """Concat via demuxer (RAM-safe, hard cuts only)."""
    if not clips:
        return False, "No clips provided"
    if len(clips) == 1:
        shutil.copy(clips[0][0], output_file)
        return True, ""

    work_dir = Path(clips[0][0]).parent
    list_file = work_dir / "_concat_list.txt"
    with open(list_file, "w") as f:
        for c, _ in clips:
            f.write(f"file '{Path(c).absolute()}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c", "copy",
        output_file
    ]
    return run(cmd, "concat (demuxer)")


# ─────────────────────────────────────────────────────────────────────
#  MUSIC PRESETS — synthesized vibes
# ─────────────────────────────────────────────────────────────────────
MUSIC_PRESETS = {
    "chill": {
        "label": "Chill ambient",
        "description": "Pad suave y atmosférico — relajado, residencial",
        "freqs": [110, 165, 220],
        "volumes": [0.6, 0.4, 0.3],
        "lowpass": 2200,
        "post_volume": 1.5,
        "echo": False,
    },
    "cinematic": {
        "label": "Cinematográfico",
        "description": "Graves profundos con eco — lujo, dramático",
        "freqs": [55, 82.5, 110, 165],
        "volumes": [0.7, 0.5, 0.4, 0.3],
        "lowpass": 1800,
        "post_volume": 1.6,
        "echo": True,
    },
    "uplifting": {
        "label": "Uplifting / luminoso",
        "description": "Notas altas y abiertas — venta cálida, ligero",
        "freqs": [220, 330, 440],
        "volumes": [0.5, 0.4, 0.3],
        "lowpass": 4000,
        "post_volume": 1.4,
        "echo": False,
    },
    "melancholic": {
        "label": "Melancólico",
        "description": "Acordes menores — emocional, evocativo",
        "freqs": [110, 130.81, 196],  # A2, C3, G3 (Am-ish)
        "volumes": [0.6, 0.45, 0.35],
        "lowpass": 2000,
        "post_volume": 1.5,
        "echo": True,
    },
    "corporate": {
        "label": "Corporate clean",
        "description": "Estable y neutro — propiedades de inversión",
        "freqs": [110, 165],
        "volumes": [0.55, 0.4],
        "lowpass": 2500,
        "post_volume": 1.4,
        "echo": False,
    },
}


def synth_music_preset(preset_key: str, output_file: str,
                        duration: float) -> tuple[bool, str]:
    """Synthesize background music from a preset. Falls back to 'chill' if unknown."""
    preset = MUSIC_PRESETS.get(preset_key, MUSIC_PRESETS["chill"])
    freqs = preset["freqs"]
    vols = preset["volumes"]
    lowpass = preset["lowpass"]
    post_vol = preset["post_volume"]
    echo = preset["echo"]

    fade_out_start = max(2, duration - 2)

    # Build sine generators
    sines = ";".join(
        f"sine=f={f}:duration={duration}[s{i}]" for i, f in enumerate(freqs)
    )
    # Apply per-sine volume + fades
    voiced = ";".join(
        f"[s{i}]volume={vols[i]},"
        f"afade=t=in:st=0:d={2 + i * 0.3},"
        f"afade=t=out:st={fade_out_start}:d=2[a{i}]"
        for i in range(len(freqs))
    )
    # Mix
    inputs = "".join(f"[a{i}]" for i in range(len(freqs)))
    mix = f"{inputs}amix=inputs={len(freqs)}:duration=longest:normalize=0[mix]"

    # Post-processing
    post_chain = f"[mix]lowpass=f={lowpass}"
    if echo:
        post_chain += ",aecho=0.6:0.3:600:0.3"
    post_chain += f",volume={post_vol}[out]"

    filter_complex = f"{sines};{voiced};{mix};{post_chain}"

    cmd = [
        "ffmpeg", "-y",
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-ac", "2", "-ar", "44100",
        "-c:a", "aac", "-b:a", "128k",
        "-t", str(duration),
        output_file
    ]
    return run(cmd, f"synth {preset_key}")


# Backward-compatible alias
def synth_ambient_music(output_file: str, duration: float) -> tuple[bool, str]:
    return synth_music_preset("chill", output_file, duration)


def mux_audio(video_file: str, music_file: str,
              voice_file: Optional[str], output_file: str) -> tuple[bool, str]:
    """Mux video with music (and optional voice)."""
    if voice_file and Path(voice_file).exists():
        filter_complex = (
            f"[1:a]volume=0.25[music_raw];"
            f"[2:a]volume=1.0[voice_raw];"
            f"[music_raw][voice_raw]amix=inputs=2:duration=longest:normalize=0[mix];"
            f"[mix]volume=1.2[out]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", video_file,
            "-i", music_file,
            "-i", voice_file,
            "-filter_complex", filter_complex,
            "-map", "0:v", "-map", "[out]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            "-shortest", "-movflags", "+faststart",
            output_file
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_file, "-i", music_file,
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            "-shortest", "-movflags", "+faststart",
            output_file
        ]
    return run(cmd, "mux audio")


def build_reel(sections: list[dict], cta_data: dict, work_dir: str,
               voice_audio_path: Optional[str] = None,
               music_path: Optional[str] = None,
               music_preset: str = "chill",
               logo_path: Optional[str] = None,
               enhance_ai: bool = False,
               auto_subtitles: bool = False,
               output_path: str = "reel.mp4") -> dict:
    """
    Main entry. Builds a reel from structured sections.

    sections: list of {
        "name": "exterior" | "entrada" | "dormitorios" | "banos" | "areas" | "vista" | "custom",
        "clips": [
            {input_path, trim_start, trim_duration, headline, subline, speed}
        ]
    }
    cta_data: {info, precio, tagline}
    logo_path: optional PNG/JPG path to show before CTA
    """
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    log = []

    segments = []  # list of (path, duration)
    clip_idx = 0

    for section in sections:
        section_name = section.get("name", "custom")
        for c in section.get("clips", []):
            clip_idx += 1
            input_path = c["input_path"]
            speed = float(c.get("speed", 1.0))
            trim_start = float(c.get("trim_start", 0))
            trim_duration = float(c["trim_duration"])
            headline = c.get("headline", "")
            subline = c.get("subline", "")

            # 1. Normalize (with optional AI enhancement)
            norm_file = str(work / f"norm_{clip_idx}.mp4")
            ok, err = normalize_clip(input_path, norm_file, enhance=enhance_ai)
            if not ok:
                return {"success": False, "error": f"normalize clip {clip_idx}: {err}", "log": log}
            log.append(f"normalized clip {clip_idx} ({section_name}){' +IA' if enhance_ai else ''}")

            # 2. Trim
            trim_file = str(work / f"trim_{clip_idx}.mp4")
            ok, err = trim_clip(norm_file, trim_file, trim_start, trim_duration)
            if not ok:
                return {"success": False, "error": f"trim clip {clip_idx}: {err}", "log": log}
            log.append(f"trimmed clip {clip_idx} → {trim_duration}s")

            current_file = trim_file
            effective_duration = trim_duration

            # 3. Speed (optional)
            if abs(speed - 1.0) > 0.01:
                speed_file = str(work / f"speed_{clip_idx}.mp4")
                ok, err = speedup_clip(trim_file, speed_file, speed)
                if not ok:
                    return {"success": False, "error": f"speed clip {clip_idx}: {err}", "log": log}
                log.append(f"sped clip {clip_idx} {speed}x")
                current_file = speed_file
                effective_duration = trim_duration / speed

            # 4. Text overlay (only if headline/subline)
            if headline or subline:
                text_file = str(work / f"text_{clip_idx}.mp4")
                ok, err = add_text_overlay(current_file, text_file,
                                            headline, subline, effective_duration)
                if not ok:
                    return {"success": False, "error": f"overlay clip {clip_idx}: {err}", "log": log}
                log.append(f"overlay clip {clip_idx}: '{headline}'")
                current_file = text_file

            segments.append((current_file, effective_duration))

    # Logo slide (optional, before CTA)
    if logo_path and Path(logo_path).exists():
        logo_file = str(work / "logo_slide.mp4")
        ok, err = build_logo_slide(logo_path, logo_file, duration=2.0)
        if not ok:
            return {"success": False, "error": f"logo slide: {err}", "log": log}
        log.append("logo slide added")
        segments.append((logo_file, 2.0))

    # CTA card
    cta_file = str(work / "cta.mp4")
    ok, err = build_cta_v2(
        cta_file,
        info_line=cta_data.get("info", ""),
        precio_line=cta_data.get("precio", ""),
        tagline=cta_data.get("tagline", ""),
        duration=5.0
    )
    if not ok:
        return {"success": False, "error": f"CTA: {err}", "log": log}
    log.append(f"CTA: {cta_data.get('precio', '')}")
    segments.append((cta_file, 5.0))

    # Concat
    concat_file = str(work / "concat.mp4")
    ok, err = concat_clips(segments, concat_file)
    if not ok:
        return {"success": False, "error": f"concat: {err}", "log": log}
    final_duration = probe_duration(concat_file)
    log.append(f"concat done, total {final_duration:.1f}s")

    # Music
    if music_path and Path(music_path).exists():
        music_file = music_path
        log.append("using uploaded music")
    else:
        music_file = str(work / "music.aac")
        ok, err = synth_music_preset(music_preset, music_file, final_duration + 1)
        if not ok:
            return {"success": False, "error": f"music: {err}", "log": log}
        log.append(f"synthesized music ({music_preset})")

    # Mux — primero a un archivo temporal si vamos a quemar subtítulos
    needs_subtitles = (
        auto_subtitles
        and voice_audio_path
        and Path(voice_audio_path).exists()
    )
    pre_subtitles_path = (
        str(work / "_pre_subs.mp4") if needs_subtitles else output_path
    )
    ok, err = mux_audio(concat_file, music_file, voice_audio_path, pre_subtitles_path)
    if not ok:
        return {"success": False, "error": f"mux: {err}", "log": log}
    log.append("final mux complete")

    # Subtítulos automáticos (opcional)
    if needs_subtitles:
        log.append("transcribiendo voz con Whisper…")
        try:
            from subtitles import apply_auto_subtitles
            ok, err = apply_auto_subtitles(
                video_path=pre_subtitles_path,
                audio_path=voice_audio_path,
                work_dir=str(work),
                output_path=output_path,
                language="es",
            )
            if not ok:
                log.append(f"subtítulos fallaron, video sin subs: {err[:100]}")
                # Fallback: copy pre_subs as output
                shutil.copy(pre_subtitles_path, output_path)
            else:
                log.append("subtítulos quemados sobre el video")
        except Exception as e:
            log.append(f"subtítulos error: {str(e)[:100]}, video sin subs")
            shutil.copy(pre_subtitles_path, output_path)

    return {
        "success": True,
        "output_path": output_path,
        "duration": final_duration,
        "log": log
    }
