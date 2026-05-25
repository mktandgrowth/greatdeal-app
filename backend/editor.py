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


def normalize_clip(input_file: str, output_file: str) -> tuple[bool, str]:
    """Scale to 540x960 vertical, 30fps, with color correction."""
    cmd = [
        "ffmpeg", "-y", "-i", input_file,
        "-vf", f"scale={W}:{H}:flags=bilinear:force_original_aspect_ratio=decrease,"
               f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,"
               "eq=brightness=0.03:saturation=1.18:contrast=1.08:gamma=0.97",
        "-r", "30",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-an",
        output_file
    ]
    return run(cmd, f"normalize {Path(input_file).name}")


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
    """Add headline + subline overlay with bottom gradient.
    If both empty, just copies the file."""
    if not headline and not subline:
        shutil.copy(input_file, output_file)
        return True, ""

    fade_out_start = max(0.1, duration - 0.3)
    filters = []
    # Gradient overlay (bottom, for legibility)
    filters.append(
        "drawbox=x=0:y=h-345:w=iw:h=15:color=black@0.05:t=fill,"
        "drawbox=x=0:y=h-330:w=iw:h=30:color=black@0.12:t=fill,"
        "drawbox=x=0:y=h-300:w=iw:h=45:color=black@0.22:t=fill,"
        "drawbox=x=0:y=h-255:w=iw:h=150:color=black@0.40:t=fill"
    )
    if headline:
        filters.append(
            f"drawtext=fontfile={FONT_BOLD}:text='{_esc(headline)}':"
            f"fontsize=46:fontcolor=white:"
            f"x=(w-text_w)/2:y=h-315:"
            f"shadowx=2:shadowy=2:shadowcolor=black@0.7"
        )
    if subline:
        filters.append(
            f"drawtext=fontfile={FONT_REG}:text='{_esc(subline)}':"
            f"fontsize=27:fontcolor=white:"
            f"x=(w-text_w)/2:y=h-255:"
            f"shadowx=1:shadowy=2:shadowcolor=black@0.7"
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


def synth_ambient_music(output_file: str, duration: float) -> tuple[bool, str]:
    """Simple ambient pad."""
    fade_out_start = max(2, duration - 2)
    filter_complex = (
        f"sine=f=110:duration={duration}[s1];"
        f"sine=f=165:duration={duration}[s2];"
        f"sine=f=220:duration={duration}[s3];"
        f"[s1]volume=0.6,afade=t=in:st=0:d=2,afade=t=out:st={fade_out_start}:d=2[a1];"
        f"[s2]volume=0.4,afade=t=in:st=0:d=2.5,afade=t=out:st={fade_out_start}:d=2[a2];"
        f"[s3]volume=0.3,afade=t=in:st=0:d=3,afade=t=out:st={fade_out_start}:d=2[a3];"
        f"[a1][a2][a3]amix=inputs=3:duration=longest:normalize=0[mix];"
        f"[mix]lowpass=f=2200,volume=1.5[out]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-ac", "2", "-ar", "44100",
        "-c:a", "aac", "-b:a", "128k",
        "-t", str(duration),
        output_file
    ]
    return run(cmd, "synth ambient")


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
               logo_path: Optional[str] = None,
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

            # 1. Normalize
            norm_file = str(work / f"norm_{clip_idx}.mp4")
            ok, err = normalize_clip(input_path, norm_file)
            if not ok:
                return {"success": False, "error": f"normalize clip {clip_idx}: {err}", "log": log}
            log.append(f"normalized clip {clip_idx} ({section_name})")

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
        music_file = str(work / "ambient.aac")
        ok, err = synth_ambient_music(music_file, final_duration + 1)
        if not ok:
            return {"success": False, "error": f"music: {err}", "log": log}
        log.append("synthesized ambient music")

    # Mux
    ok, err = mux_audio(concat_file, music_file, voice_audio_path, output_path)
    if not ok:
        return {"success": False, "error": f"mux: {err}", "log": log}
    log.append("final mux complete")

    return {
        "success": True,
        "output_path": output_path,
        "duration": final_duration,
        "log": log
    }
