"""
GreatDeal · Runway AI integration
Video-to-video regeneration con prompts por toma.

Flujo:
  1. Extraer el primer frame del clip original (FFmpeg)
  2. Llamar Runway image-to-video con ese frame + prompt del usuario
  3. Polling del task hasta SUCCEEDED
  4. Descargar el video resultado
  5. Normalizar a 540x960 30fps (compatible con el resto del pipeline)
"""
import os
import time
import subprocess
import urllib.request
from pathlib import Path
from typing import Optional

try:
    from runwayml import RunwayML
    SDK_AVAILABLE = True
except ImportError:
    SDK_AVAILABLE = False


# Presets de estilo rápidos para el usuario
STYLE_PRESETS = {
    "luz_natural": {
        "label": "💡 Más luz natural",
        "prompt": "Same scene but with abundant natural daylight pouring through windows, bright airy atmosphere, soft warm lighting, professional real estate photography style",
    },
    "cinematografico": {
        "label": "🎬 Cinematográfico",
        "prompt": "Same scene with cinematic color grading, warm golden hour lighting, shallow depth of field, professional film look, smooth camera movement",
    },
    "verano_calido": {
        "label": "☀️ Verano cálido",
        "prompt": "Same scene bathed in warm summer afternoon sunlight, golden tones, vibrant colors, inviting atmosphere, professional real estate showcase",
    },
    "profesional_clean": {
        "label": "✨ Profesional limpio",
        "prompt": "Same scene with bright even professional lighting, crisp clean look, modern luxury real estate aesthetic, neutral color palette",
    },
    "nocturno_lujo": {
        "label": "🌃 Lujo nocturno",
        "prompt": "Same scene at twilight with warm interior lights on, luxury ambiance, high-end real estate, dramatic but inviting lighting",
    },
}


def get_client():
    """Get Runway client (raises if API key missing or SDK not installed)."""
    if not SDK_AVAILABLE:
        raise RuntimeError(
            "runwayml SDK no instalado. Agregalo a requirements.txt y redeployá."
        )
    api_key = os.environ.get("RUNWAY_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "RUNWAY_API_KEY no configurada en el server. Agregala en Render → Environment."
        )
    return RunwayML(api_key=api_key)


def extract_first_frame(video_path: str, output_image: str) -> tuple[bool, str]:
    """Extract the first frame of a video as JPG (for Runway image-to-video input)."""
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vframes", "1", "-q:v", "2",
        output_image,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return False, r.stderr[-500:]
    if not Path(output_image).exists():
        return False, "frame file not created"
    return True, ""


def probe_duration(video_path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", video_path],
        capture_output=True, text=True
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def normalize_runway_output(input_video: str, output_video: str,
                             target_w: int = 540, target_h: int = 960) -> tuple[bool, str]:
    """Normalize Runway output to GreatDeal pipeline format."""
    cmd = [
        "ffmpeg", "-y", "-i", input_video,
        "-vf", f"scale={target_w}:{target_h}:flags=lanczos:force_original_aspect_ratio=decrease,"
               f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=black",
        "-r", "30",
        "-c:v", "libx264", "-preset", "fast", "-crf", "21",
        "-pix_fmt", "yuv420p", "-an",
        output_video,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return False, r.stderr[-500:]
    return True, ""


def enhance_clip_with_runway(
    input_video: str,
    prompt: str,
    output_video: str,
    work_dir: str,
    model: str = "gen3a_turbo",
    duration: int = 5,
    ratio: str = "768:1280",
    poll_interval: int = 5,
    max_wait_seconds: int = 300,
) -> tuple[bool, str]:
    """
    Regenera una toma con Runway video-to-video.

    Returns (success, error_message).
    Si éxito, output_video tiene el clip regenerado normalizado a 540x960.
    """
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    # 1. Get client (validates API key)
    try:
        client = get_client()
    except Exception as e:
        return False, str(e)

    # 2. Extract first frame
    frame_path = str(work / "rw_frame.jpg")
    ok, err = extract_first_frame(input_video, frame_path)
    if not ok:
        return False, f"Frame extraction failed: {err}"

    # 3. Convert frame to data URL (Runway accepts URL or base64 data URI)
    import base64
    with open(frame_path, "rb") as f:
        frame_b64 = base64.b64encode(f.read()).decode("ascii")
    frame_data_url = f"data:image/jpeg;base64,{frame_b64}"

    # 4. Build enriched prompt for real estate
    enriched_prompt = (
        f"{prompt}. Professional real estate video, smooth steady camera, "
        f"high quality, photorealistic, no text overlays."
    )

    # 5. Create task on Runway
    try:
        task = client.image_to_video.create(
            model=model,
            prompt_image=frame_data_url,
            prompt_text=enriched_prompt[:1000],  # Runway has a prompt length limit
            duration=duration,
            ratio=ratio,
        )
        task_id = task.id
    except Exception as e:
        return False, f"Runway task creation failed: {str(e)[:300]}"

    # 6. Poll until done or timeout
    start_time = time.time()
    last_status = None
    while True:
        elapsed = time.time() - start_time
        if elapsed > max_wait_seconds:
            return False, f"Runway timeout después de {max_wait_seconds}s (status={last_status})"
        try:
            task = client.tasks.retrieve(task_id)
            last_status = task.status
        except Exception as e:
            return False, f"Runway poll failed: {str(e)[:200]}"
        if task.status == "SUCCEEDED":
            break
        if task.status == "FAILED":
            err_msg = getattr(task, "failure", None) or "unknown"
            return False, f"Runway task failed: {err_msg}"
        time.sleep(poll_interval)

    # 7. Get output URL
    output_urls = getattr(task, "output", None)
    if not output_urls or len(output_urls) == 0:
        return False, "Runway returned no output URL"
    video_url = output_urls[0]

    # 8. Download the resulting video
    downloaded = str(work / "rw_raw.mp4")
    try:
        urllib.request.urlretrieve(video_url, downloaded)
    except Exception as e:
        return False, f"Download failed: {str(e)[:200]}"

    # 9. Normalize to GreatDeal pipeline format (540x960, 30fps)
    ok, err = normalize_runway_output(downloaded, output_video)
    if not ok:
        return False, f"Normalize failed: {err}"

    return True, ""


def estimate_cost_usd(duration_seconds: int, model: str = "gen3a_turbo") -> float:
    """Estimación de costo aproximada en USD."""
    rates = {
        "gen3a_turbo": 0.05,  # ~$0.05/seg en Gen-3 Turbo
        "gen4_turbo": 0.10,
    }
    rate = rates.get(model, 0.05)
    return round(duration_seconds * rate, 2)
