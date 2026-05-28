"""
GreatDeal · Video editor module (v0.2 — secciones)
Pipeline FFmpeg estructurada por secciones de propiedad.
"""
import subprocess
import shutil
import json
from pathlib import Path
from typing import Optional

FONT_BOLD = "/usr/share/fonts/truetype/montserrat/Montserrat-Black.ttf"  # peso 900 (más bold)
FONT_REG  = "/usr/share/fonts/truetype/montserrat/Montserrat-Regular.ttf"
FONT_THIN = "/usr/share/fonts/truetype/montserrat/Montserrat-Thin.ttf"

# Fallback fonts (DejaVu si Montserrat no se descargó)
if not Path(FONT_BOLD).exists():
    # Si no hay Black, intentar SemiBold; si no, DejaVu
    sb = "/usr/share/fonts/truetype/montserrat/Montserrat-SemiBold.ttf"
    FONT_BOLD = sb if Path(sb).exists() else "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
if not Path(FONT_REG).exists():
    FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
if not Path(FONT_THIN).exists():
    FONT_THIN = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

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
    """Run FFmpeg/ffprobe subprocess. Uses /dev/null for stdout (FFmpeg encoder output)
    and PIPE only for stderr (where FFmpeg writes status/errors). Avoids loading large
    binary output in RAM (which can OOM Render Starter)."""
    print(f"[ffmpeg] {label or cmd[0]}...", flush=True)
    try:
        # stdout to DEVNULL (no necesitamos stdout binario), stderr a PIPE pequeño
        r = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=600,  # 10 min max por operación
        )
    except subprocess.TimeoutExpired:
        return False, f"timeout after 10min running {label}"
    except Exception as e:
        return False, f"subprocess error: {str(e)[:300]}"
    if r.returncode != 0:
        return False, (r.stderr or "")[-1500:]
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
    if headline:
        # Headline: Montserrat SemiBold blanco con sombra negra fuerte
        filters.append(
            f"drawtext=fontfile={FONT_BOLD}:text='{_esc(headline)}':"
            f"fontsize=38:fontcolor=white:"
            f"x=(w-text_w)/2:y=(h-text_h)/2-25:"
            f"shadowx=3:shadowy=3:shadowcolor=black@0.95"
        )
    if subline:
        # Subline: Montserrat Regular blanco con sombra negra
        filters.append(
            f"drawtext=fontfile={FONT_REG}:text='{_esc(subline)}':"
            f"fontsize=24:fontcolor=white:"
            f"x=(w-text_w)/2:y=(h-text_h)/2+25:"
            f"shadowx=2:shadowy=2:shadowcolor=black@0.9"
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
    # White rectangle dimensions — más compacto y elegante
    rect_w, rect_h = 320, 80
    rect_x = (W - rect_w) // 2          # =110
    rect_y = H // 2 - rect_h // 2       # =440

    filters = ["vignette=PI/4"]

    if info_line:
        filters.append(
            f"drawtext=fontfile={FONT_REG}:text='{_esc(info_line)}':"
            f"fontsize=28:fontcolor=white:"
            f"x=(w-text_w)/2:y={rect_y - 60}"
        )
    if precio_line:
        # Rectángulo blanco semi-transparente (más elegante que blanco puro)
        filters.append(
            f"drawbox=x={rect_x}:y={rect_y}:w={rect_w}:h={rect_h}:color=white@0.92:t=fill"
        )
        # Precio en negro centrado sobre el rectángulo
        filters.append(
            f"drawtext=fontfile={FONT_BOLD}:text='{_esc(precio_line)}':"
            f"fontsize=36:fontcolor=black:"
            f"x=(w-text_w)/2:y={rect_y + (rect_h - 36) // 2 - 2}"
        )
    if tagline:
        filters.append(
            f"drawtext=fontfile={FONT_REG}:text='{_esc(tagline)}':"
            f"fontsize=26:fontcolor=0xcbd5e1:"
            f"x=(w-text_w)/2:y={rect_y + rect_h + 50}"
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
#  MUSIC PRESETS — synthesized vibes (10 opciones)
# ─────────────────────────────────────────────────────────────────────
# Parámetros disponibles:
#   freqs: frecuencias base (Hz) — más bajas = grave/dramático, más altas = brillante
#   volumes: volumen por frecuencia
#   lowpass: filtro pasabajos (Hz) — más bajo = más oscuro
#   highpass: filtro pasaaltos (Hz) — saca graves
#   post_volume: volumen final
#   echo: aplica aecho (reverb-like)
#   tremolo: modula volumen creando sensación de ritmo (Hz, ej 4 = pulsación lenta)
#   vibrato: modula pitch creando sensación expresiva (Hz)
# ============================================================================
# MÚSICA REAL — pistas libres de derechos de Mixkit (free for commercial use,
# sin atribución requerida). Se descargan a /app/music_cache/ on-demand
# la primera vez que se usan; luego se sirven desde cache.
# ============================================================================
MUSIC_CACHE_DIR = Path("/app/music_cache")

MUSIC_PRESETS = {
    "cinematic_view": {
        "label": "🎬 Cinematográfico — vista",
        "description": "Strings cinemáticos suaves — propiedades de lujo, vistas, panorámicas",
        "url": "https://assets.mixkit.co/music/preview/mixkit-serene-view-443.mp3",
    },
    "elegant_piano": {
        "label": "🎹 Piano elegante",
        "description": "Piano refinado — propiedades premium, casas con historia",
        "url": "https://assets.mixkit.co/music/preview/mixkit-piano-horizon-637.mp3",
    },
    "warm_acoustic": {
        "label": "🌅 Cálido acústico",
        "description": "Piano cálido y luminoso — casas familiares, hogareño",
        "url": "https://assets.mixkit.co/music/preview/mixkit-warm-piano-of-joy-3015.mp3",
    },
    "happy_summer": {
        "label": "☀️ Verano alegre",
        "description": "Ukulele alegre — casas de playa, propiedades luminosas",
        "url": "https://assets.mixkit.co/music/preview/mixkit-summer-fun-13.mp3",
    },
    "corporate_inspiring": {
        "label": "💼 Corporate inspiracional",
        "description": "Inspiracional motivacional — comercial, inversión, oficinas",
        "url": "https://assets.mixkit.co/music/preview/mixkit-driving-ambition-32.mp3",
    },
    "dreaming_big": {
        "label": "✨ Sueños grandes",
        "description": "Inspiracional emotivo — primera casa, sueño cumplido",
        "url": "https://assets.mixkit.co/music/preview/mixkit-dreaming-big-31.mp3",
    },
    "lofi_chill": {
        "label": "🌙 Lo-fi chill",
        "description": "Lo-fi relajado — vibe joven, scroll-friendly, moderno",
        "url": "https://assets.mixkit.co/music/preview/mixkit-relaxing-in-paradise-533.mp3",
    },
    "tech_house": {
        "label": "⚡ Tech house",
        "description": "Beat moderno — deptos urbanos, propiedades jóvenes",
        "url": "https://assets.mixkit.co/music/preview/mixkit-tech-house-vibes-130.mp3",
    },
    "urban_hiphop": {
        "label": "🏙️ Urban hip-hop",
        "description": "Beat hip-hop suave — lofts, deptos modernos, ciudad",
        "url": "https://assets.mixkit.co/music/preview/mixkit-deep-urban-623.mp3",
    },
    "chill_hiphop": {
        "label": "🎧 Chill hip-hop",
        "description": "Hip-hop relajado — vibes modernas, casual",
        "url": "https://assets.mixkit.co/music/preview/mixkit-hip-hop-02-738.mp3",
    },
}


def download_music_track(preset_key: str) -> tuple[bool, str]:
    """Descarga la pista mp3 desde su URL al cache local.
    Retorna (success, local_path_or_error)."""
    preset = MUSIC_PRESETS.get(preset_key)
    if not preset:
        return False, f"preset desconocido: {preset_key}"

    MUSIC_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = MUSIC_CACHE_DIR / f"{preset_key}.mp3"

    # Si ya está cacheado y tiene contenido razonable, usar el cached
    if cache_path.exists() and cache_path.stat().st_size > 50_000:
        return True, str(cache_path)

    url = preset["url"]
    print(f"[music] descargando {preset_key} desde {url}", flush=True)

    try:
        import requests
        r = requests.get(url, timeout=60, stream=True)
        if r.status_code != 200:
            return False, f"HTTP {r.status_code} al descargar {url}"
        with open(cache_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        if cache_path.stat().st_size < 10_000:
            return False, f"download too small ({cache_path.stat().st_size} bytes)"
        return True, str(cache_path)
    except Exception as e:
        return False, f"download failed: {str(e)[:200]}"


def synth_music_preset(preset_key: str, output_file: str,
                        duration: float) -> tuple[bool, str]:
    """Toma la pista real del preset, la loopea si hace falta, recorta a duración,
    aplica fade-out y la convierte a AAC. Nombre mantenido por compat."""
    # Fallback al primer preset si vienen claves viejas/inválidas
    if preset_key not in MUSIC_PRESETS:
        preset_key = "cinematic_view"

    ok, mp3_path = download_music_track(preset_key)
    if not ok:
        return False, mp3_path  # error message

    fade_out_start = max(0.5, duration - 1.5)
    # -stream_loop -1 loopea infinitamente la entrada hasta que -t corte.
    # afade out al final para que no se corte brusco.
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", mp3_path,
        "-t", f"{duration:.2f}",
        "-af", f"afade=t=out:st={fade_out_start:.2f}:d=1.5,volume=1.0",
        "-ac", "2", "-ar", "44100",
        "-c:a", "aac", "-b:a", "160k",
        output_file
    ]
    return run(cmd, f"music {preset_key}")


# Backward-compatible alias
def synth_ambient_music(output_file: str, duration: float) -> tuple[bool, str]:
    return synth_music_preset("cinematic_view", output_file, duration)


def mux_audio(video_file: str, music_file: str,
              voice_file: Optional[str], output_file: str) -> tuple[bool, str]:
    """Mux video with music (and optional voice).
    El VIDEO siempre dicta la duración final.
    Con voz: sidechain ducking REAL — música a volumen alto cuando NO hay voz,
    baja automáticamente cuando suena la voz.
    Sin voz: música a volumen normal alto.
    """
    video_dur = probe_duration(video_file)
    if video_dur <= 0:
        return False, "No pude obtener duración del video"

    if voice_file and Path(voice_file).exists():
        # Ducking dinámico real con sidechaincompress:
        # - Música a 80% base (audible cuando no hay voz)
        # - Voz a 100%
        # - sidechaincompress comprime la música SOLO cuando detecta voz
        # - Resultado: música alta cuando no habla, baja cuando habla
        filter_complex = (
            f"[1:a]volume=0.8,apad[music_base];"
            f"[2:a]volume=1.0,apad[voice_base];"
            # Split voice para usar uno como sidechain key y otro en mix
            f"[voice_base]asplit=2[voice_for_mix][voice_for_sc];"
            # Sidechain compress: música ducks cuando voz suena
            f"[music_base][voice_for_sc]sidechaincompress="
            f"threshold=0.05:ratio=10:attack=20:release=500:makeup=2[music_ducked];"
            # Mix de música ducked + voz
            f"[music_ducked][voice_for_mix]amix=inputs=2:duration=longest:normalize=0[mix];"
            f"[mix]volume=1.5,atrim=0:{video_dur:.2f},asetpts=PTS-STARTPTS[out]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", video_file,
            "-i", music_file,
            "-i", voice_file,
            "-filter_complex", filter_complex,
            "-map", "0:v", "-map", "[out]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            output_file
        ]
    else:
        # Solo música — VOLUME boost para que se escuche bien
        filter_complex = (
            f"[1:a]volume=1.5,apad,atrim=0:{video_dur:.2f},asetpts=PTS-STARTPTS[out]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", video_file, "-i", music_file,
            "-filter_complex", filter_complex,
            "-map", "0:v", "-map", "[out]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            output_file
        ]
    return run(cmd, "mux audio")


def process_clip_combined(input_path: str, output_path: str,
                           trim_start: float, trim_duration: float,
                           speed: float = 1.0,
                           headline: str = "", subline: str = "",
                           enhance_ai: bool = False) -> tuple[bool, str]:
    """Procesa un clip en UNA SOLA operación FFmpeg combinando:
    normalize + trim + speed + color correction + text overlay.
    Reemplaza 3-4 encodes separados → 1 encode. ~3x más rápido por clip.
    """
    filters = []

    # 1. Speed (si aplica): setpts=PTS/speed
    if abs(speed - 1.0) > 0.01:
        filters.append(f"setpts=PTS/{speed}")

    # 2. Scale + pad a 540x960 vertical
    if enhance_ai:
        filters.append(
            f"scale={W}:{H}:flags=lanczos:force_original_aspect_ratio=decrease"
        )
        filters.append(f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black")
        # Color cinematográfico
        filters.append("hqdn3d=1.5:1.5:6:6")
        filters.append("eq=brightness=0.06:contrast=1.20:saturation=1.32:gamma=1.05")
        filters.append("unsharp=5:5:1.0:5:5:0.0")
        filters.append("vignette=PI/5")
        preset, crf = "fast", "21"
    else:
        filters.append(
            f"scale={W}:{H}:flags=bilinear:force_original_aspect_ratio=decrease"
        )
        filters.append(f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black")
        filters.append("eq=brightness=0.03:saturation=1.18:contrast=1.08:gamma=0.97")
        preset, crf = "ultrafast", "23"

    # 3. Text overlay (si hay texto)
    # Estilo CapCut: letras blancas limpias, sin borde, sin sombra.
    # El contraste con el fondo del clip es suficiente para legibilidad.
    effective_duration = trim_duration / speed
    if headline or subline:
        fade_out_start = max(0.1, effective_duration - 0.3)
        if headline:
            filters.append(
                f"drawtext=fontfile={FONT_BOLD}:text='{_esc(headline)}':"
                f"fontsize=42:fontcolor=white:"
                f"x=(w-text_w)/2:y=(h-text_h)/2-28"
            )
        if subline:
            filters.append(
                f"drawtext=fontfile={FONT_REG}:text='{_esc(subline)}':"
                f"fontsize=26:fontcolor=white:"
                f"x=(w-text_w)/2:y=(h-text_h)/2+28"
            )
        filters.append(
            f"fade=t=in:st=0:d=0.3,fade=t=out:st={fade_out_start}:d=0.3"
        )

    vf = ",".join(filters)

    # Importante: -ss DESPUÉS de -i = "slow seek" = preciso al frame exacto
    # (-ss antes de -i sería "fast seek" pero puede saltar a keyframe lejano)
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-ss", str(trim_start),
        "-t", str(trim_duration),
        "-vf", vf,
        "-r", "30",
        "-c:v", "libx264", "-preset", preset, "-crf", crf,
        "-pix_fmt", "yuv420p", "-an",
        output_path,
    ]
    return run(cmd, f"process {Path(input_path).name}")


def build_reel(sections: list[dict], cta_data: dict, work_dir: str,
               voice_audio_path: Optional[str] = None,
               music_path: Optional[str] = None,
               music_preset: str = "cinematic_view",
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

            # Procesar todo en UNA sola operación FFmpeg (normalize+trim+speed+overlay)
            # ~3x más rápido que hacerlos por separado
            processed_file = str(work / f"clip_{clip_idx}.mp4")
            ok, err = process_clip_combined(
                input_path=input_path,
                output_path=processed_file,
                trim_start=trim_start,
                trim_duration=trim_duration,
                speed=speed,
                headline=headline,
                subline=subline,
                enhance_ai=enhance_ai,
            )
            if not ok:
                return {"success": False, "error": f"process clip {clip_idx}: {err}", "log": log}
            effective_duration = trim_duration / speed
            log.append(
                f"clip {clip_idx} ({section_name}) listo · {effective_duration:.1f}s"
                f"{f' · 🎬 IA color' if enhance_ai else ''}"
                f"{f' · ⚡ {speed}x' if abs(speed - 1.0) > 0.01 else ''}"
                f"{f' · 📝 {headline[:20]}' if headline else ''}"
            )
            segments.append((processed_file, effective_duration))

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

    # Subtítulos automáticos (opcional) — logging explícito para diagnóstico
    log.append(
        f"subs check: auto_subtitles={auto_subtitles}, "
        f"voice={'sí' if voice_audio_path else 'no'}, "
        f"voice_exists={Path(voice_audio_path).exists() if voice_audio_path else False}"
    )
    if needs_subtitles:
        log.append("🎤 transcribiendo voz con Whisper…")
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
                log.append(f"❌ subtítulos fallaron: {err[:200]}")
                # Fallback: copy pre_subs as output
                shutil.copy(pre_subtitles_path, output_path)
            else:
                log.append("✅ subtítulos quemados sobre el video")
        except Exception as e:
            log.append(f"❌ subtítulos error: {str(e)[:200]}")
            shutil.copy(pre_subtitles_path, output_path)
    else:
        log.append(f"⏭️ saltando subtítulos (necesita: voz cargada + toggle ON)")

    return {
        "success": True,
        "output_path": output_path,
        "duration": final_duration,
        "log": log
    }
