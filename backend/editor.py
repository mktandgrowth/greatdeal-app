"""
GreatDeal · Video editor module
Extrae la pipeline FFmpeg que ya validamos en build/ y la deja como modulo reutilizable.
"""
import subprocess
import shutil
import json
from pathlib import Path
from typing import Optional

FONT_BOLD = "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"

# Fallback fonts (Windows users will adjust)
if not Path(FONT_BOLD).exists():
    FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
if not Path(FONT_REG).exists():
    FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

W, H = 720, 1280

# IG/TikTok safe zone: top 15%, bottom 25% are UI overlay zones.
# Bottom text y must be ABOVE h * 0.75 to be safe.
# For 1280 height: safe bottom edge = 960. Place text around y=900-940 (a bit higher than before).
TEXT_BASELINE_Y = 850   # Headline baseline
SUBLINE_BASELINE_Y = 940


def run(cmd: list, label: str = "") -> tuple[bool, str]:
    """Run a subprocess command, capture stderr."""
    print(f"[ffmpeg] {label or cmd[0]}...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return False, r.stderr[-1500:]
    return True, ""


def probe_duration(file: str) -> float:
    """Get duration of a media file in seconds."""
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
    """Scale to 720x1280, 30fps, with color correction (brightness +3%, saturation +18%, contrast +8%)."""
    cmd = [
        "ffmpeg", "-y", "-i", input_file,
        "-vf", "scale=720:1280:flags=lanczos:force_original_aspect_ratio=decrease,"
               "pad=720:1280:(ow-iw)/2:(oh-ih)/2:color=black,"
               "eq=brightness=0.03:saturation=1.18:contrast=1.08:gamma=0.97,"
               "unsharp=5:5:0.6:5:5:0.0",
        "-r", "30",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-an",
        output_file
    ]
    return run(cmd, f"normalize {Path(input_file).name}")


def trim_clip(input_file: str, output_file: str, start: float, duration: float) -> tuple[bool, str]:
    """Trim a clip to a specific time range."""
    cmd = [
        "ffmpeg", "-y", "-i", input_file,
        "-ss", str(start), "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-an",
        output_file
    ]
    return run(cmd, f"trim {Path(input_file).name}")


def add_text_overlay(input_file: str, output_file: str,
                     headline: str, subline: str, duration: float) -> tuple[bool, str]:
    """Add headline + subline overlay with bottom gradient. Respects IG safe zone."""
    fade_out_start = max(0.1, duration - 0.3)
    # Gradient overlay (4 stacked semi-transparent boxes) at the safe zone region
    gradient = (
        f"drawbox=x=0:y=h-460:w=iw:h=20:color=black@0.05:t=fill,"
        f"drawbox=x=0:y=h-440:w=iw:h=40:color=black@0.12:t=fill,"
        f"drawbox=x=0:y=h-400:w=iw:h=60:color=black@0.22:t=fill,"
        f"drawbox=x=0:y=h-340:w=iw:h=200:color=black@0.40:t=fill"
    )
    headline_filter = (
        f"drawtext=fontfile={FONT_BOLD}:text='{headline}':"
        f"fontsize=62:fontcolor=white:"
        f"x=(w-text_w)/2:y=h-420:"
        f"shadowx=2:shadowy=3:shadowcolor=black@0.7"
    )
    sub_filter = (
        f"drawtext=fontfile={FONT_REG}:text='{subline}':"
        f"fontsize=36:fontcolor=white:"
        f"x=(w-text_w)/2:y=h-340:"
        f"shadowx=2:shadowy=2:shadowcolor=black@0.7"
    )
    fade = f"fade=t=in:st=0:d=0.3,fade=t=out:st={fade_out_start}:d=0.3"
    filter_complex = f"{gradient},{headline_filter},{sub_filter},{fade}"

    cmd = [
        "ffmpeg", "-y", "-i", input_file,
        "-vf", filter_complex,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-an",
        output_file
    ]
    return run(cmd, f"overlay {Path(output_file).name}")


def build_cta(output_file: str, line1: str, line2: str, line3: str,
              line4: str, duration: float = 5.0) -> tuple[bool, str]:
    """Generate closing CTA card with GreatDeal branding."""
    filter_complex = (
        f"vignette=PI/4,"
        f"drawtext=fontfile={FONT_BOLD}:text='GREATDEAL':"
        f"fontsize=42:fontcolor=white:x=(w-text_w)/2:y=180,"
        f"drawbox=x=(iw-80)/2:y=240:w=80:h=3:color=0xfbbf24:t=fill,"
        f"drawtext=fontfile={FONT_BOLD}:text='{line1}':"
        f"fontsize=46:fontcolor=white:x=(w-text_w)/2:y=h/2-160,"
        f"drawtext=fontfile={FONT_REG}:text='{line2}':"
        f"fontsize=36:fontcolor=0xcbd5e1:x=(w-text_w)/2:y=h/2-100,"
        f"drawbox=x=(iw-120)/2:y=h/2-30:w=120:h=2:color=0xfbbf24:t=fill,"
        f"drawtext=fontfile={FONT_BOLD}:text='{line3}':"
        f"fontsize=58:fontcolor=0xfbbf24:x=(w-text_w)/2:y=h/2+20,"
        f"drawtext=fontfile={FONT_REG}:text='{line4}':"
        f"fontsize=40:fontcolor=white:x=(w-text_w)/2:y=h/2+110,"
        f"drawtext=fontfile={FONT_REG}:text='Vivir distinto':"
        f"fontsize=28:fontcolor=0x94a3b8:x=(w-text_w)/2:y=h-180,"
        f"fade=t=in:st=0:d=0.5,fade=t=out:st={duration-0.5}:d=0.5"
    )
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=0x0f172a:s={W}x{H}:r=30:d={duration},format=yuv420p",
        "-vf", filter_complex,
        "-r", "30",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-an",
        output_file
    ]
    return run(cmd, "CTA card")


def concat_with_xfade(clips: list[tuple[str, float]], output_file: str,
                       xfade_dur: float = 0.4) -> tuple[bool, str]:
    """Concatenate clips with crossfades. Each entry: (file_path, duration)."""
    if not clips:
        return False, "No clips provided"
    if len(clips) == 1:
        shutil.copy(clips[0][0], output_file)
        return True, ""

    inputs = []
    for c, _ in clips:
        inputs += ["-i", c]

    # Build progressive xfade
    parts = []
    last_stream = "[0:v]"
    cumulative = clips[0][1]
    for i, (clip, dur) in enumerate(clips):
        if i == 0:
            continue
        next_stream = f"[v{i}]"
        offset = cumulative - xfade_dur
        parts.append(
            f"{last_stream}[{i}:v]xfade=transition=fade:duration={xfade_dur}:offset={offset:.3f}{next_stream}"
        )
        last_stream = next_stream
        cumulative += dur - xfade_dur

    filter_complex = ";".join(parts)
    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", filter_complex,
        "-map", last_stream,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-an",
        output_file
    ]
    return run(cmd, "concat xfade")


def synth_ambient_music(output_file: str, duration: float) -> tuple[bool, str]:
    """Synthesize a warm ambient pad — used as fallback when no music uploaded."""
    fade_out_start = max(2, duration - 2)
    filter_complex = (
        f"sine=f=110:duration={duration}[s1];"
        f"sine=f=165:duration={duration}[s2];"
        f"sine=f=220:duration={duration}[s3];"
        f"sine=f=82.4:duration={duration}[s4];"
        f"sine=f=329.6:duration={duration}[s5];"
        f"[s1]volume=0.6,afade=t=in:st=0:d=2,afade=t=out:st={fade_out_start}:d=2[a1];"
        f"[s2]volume=0.4,afade=t=in:st=0:d=2.5,afade=t=out:st={fade_out_start}:d=2[a2];"
        f"[s3]volume=0.3,afade=t=in:st=0:d=3,afade=t=out:st={fade_out_start}:d=2[a3];"
        f"[s4]volume=0.5,afade=t=in:st=0:d=2,afade=t=out:st={fade_out_start}:d=2[a4];"
        f"[s5]volume=0.15,afade=t=in:st=0:d=4,afade=t=out:st={fade_out_start}:d=2[a5];"
        f"[a1][a2][a3][a4][a5]amix=inputs=5:duration=longest:normalize=0[mix];"
        f"[mix]lowpass=f=2200,highpass=f=60,aecho=0.7:0.8:80:0.25,volume=1.5[out]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-ac", "2", "-ar", "44100",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(duration),
        output_file
    ]
    return run(cmd, "synth ambient")


def mux_audio_with_ducking(video_file: str, music_file: str, voice_file: Optional[str],
                            output_file: str) -> tuple[bool, str]:
    """Mux video with music. If voice provided, apply sidechain ducking (music drops 60% when voice present)."""
    if voice_file and Path(voice_file).exists():
        # Voice + music with ducking
        filter_complex = (
            # Reduce music volume to 0.35 baseline (lower when voice)
            f"[1:a]volume=0.45[music_raw];"
            f"[2:a]volume=1.0[voice_raw];"
            f"[music_raw][voice_raw]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=400[ducked_music];"
            f"[ducked_music][voice_raw]amix=inputs=2:duration=longest:normalize=0[mix];"
            f"[mix]volume=1.2[out]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", video_file,
            "-i", music_file,
            "-i", voice_file,
            "-filter_complex", filter_complex,
            "-map", "0:v", "-map", "[out]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart",
            output_file
        ]
    else:
        # Just music
        cmd = [
            "ffmpeg", "-y",
            "-i", video_file, "-i", music_file,
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart",
            output_file
        ]
    return run(cmd, "mux audio")


def build_reel(clips: list[dict], property_data: dict, work_dir: str,
               voice_audio_path: Optional[str] = None,
               music_path: Optional[str] = None,
               output_path: str = "reel.mp4") -> dict:
    """
    Main entry point. Builds a complete reel from raw clips + property data.

    clips: list of {input_path, headline, subline, trim_start, trim_duration}
    property_data: {tipo, comuna, m2, dorms, banos, precio_uf}
    voice_audio_path: optional MP3/WAV of voiceover (overrides any auto-narration)
    music_path: optional MP3 to use as background music (else synthesizes ambient)
    """
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    log = []

    # Step 1: normalize and trim each clip
    text_segments = []
    cumulative_duration = 0
    for i, c in enumerate(clips, start=1):
        norm_file = str(work / f"norm_{i}.mp4")
        ok, err = normalize_clip(c["input_path"], norm_file)
        if not ok:
            return {"success": False, "error": f"normalize clip {i}: {err}", "log": log}
        log.append(f"normalized clip {i}")

        trim_file = str(work / f"trim_{i}.mp4")
        ok, err = trim_clip(norm_file, trim_file, c.get("trim_start", 0), c["trim_duration"])
        if not ok:
            return {"success": False, "error": f"trim clip {i}: {err}", "log": log}
        log.append(f"trimmed clip {i} → {c['trim_duration']}s")

        text_file = str(work / f"text_{i}.mp4")
        ok, err = add_text_overlay(trim_file, text_file,
                                     c.get("headline", ""), c.get("subline", ""),
                                     c["trim_duration"])
        if not ok:
            return {"success": False, "error": f"text overlay clip {i}: {err}", "log": log}
        log.append(f"overlay clip {i}: '{c.get('headline','')}' / '{c.get('subline','')}'")

        text_segments.append((text_file, c["trim_duration"]))
        cumulative_duration += c["trim_duration"]

    # Step 2: build CTA card
    cta_file = str(work / "cta.mp4")
    line1 = f"{property_data.get('m2','?')} m2 construidos"
    line2 = f"{property_data.get('dorms','?')} dorm  {property_data.get('banos','?')} banos"
    line3 = f"Desde {property_data.get('precio_uf','?')} UF"
    line4 = "greatdeal.vercel.app"
    ok, err = build_cta(cta_file, line1, line2, line3, line4, duration=5.0)
    if not ok:
        return {"success": False, "error": f"CTA: {err}", "log": log}
    log.append(f"CTA card: {line3}")
    text_segments.append((cta_file, 5.0))
    cumulative_duration += 5.0

    # Step 3: concat all with xfades
    concat_file = str(work / "concat.mp4")
    ok, err = concat_with_xfade(text_segments, concat_file, xfade_dur=0.4)
    if not ok:
        return {"success": False, "error": f"concat: {err}", "log": log}
    final_video_duration = probe_duration(concat_file)
    log.append(f"concat done, total {final_video_duration:.1f}s")

    # Step 4: music (uploaded or synthesized)
    if music_path and Path(music_path).exists():
        music_file = music_path
        log.append(f"using uploaded music")
    else:
        music_file = str(work / "ambient.aac")
        ok, err = synth_ambient_music(music_file, final_video_duration + 1)
        if not ok:
            return {"success": False, "error": f"music: {err}", "log": log}
        log.append("synthesized ambient music")

    # Step 5: mux
    ok, err = mux_audio_with_ducking(concat_file, music_file, voice_audio_path, output_path)
    if not ok:
        return {"success": False, "error": f"mux: {err}", "log": log}
    log.append("final mux complete")

    return {
        "success": True,
        "output_path": output_path,
        "duration": final_video_duration,
        "log": log
    }
