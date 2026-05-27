"""
GreatDeal · Runway AI integration (REST API directa con requests)
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
import base64
import subprocess
import urllib.request
from pathlib import Path
from typing import Optional

import requests


RUNWAY_API_BASE = "https://api.dev.runwayml.com/v1"
RUNWAY_VERSION = "2024-11-06"


# Presets de Runway para real estate — 4 casos de uso reales.
# Cada preset tiene:
# - prompt_es: instrucción CORTA en español (lo que se muestra al usuario, editable)
# - prompt_full: prompt LARGO en inglés con todos los detalles cinematográficos
#   (lo que se manda a Runway si el usuario no modifica el prompt corto)
STYLE_PRESETS = {
    "iluminacion_perfecta": {
        "label": "💡 Iluminación natural perfecta",
        "description": "Como si lo grabara un fotógrafo profesional a las 12 del día",
        "prompt_es": (
            "Misma escena con iluminación natural perfecta de mediodía, como si la grabara un fotógrafo "
            "arquitectónico profesional a las 12 del día. Luz brillante y uniforme en todo el espacio, "
            "sin sombras duras, exposición perfectamente balanceada, atmósfera fresca y aireada."
        ),
        # Core: el concepto principal sin la cinematografía detallada (se agrega al combinar)
        "prompt_core": (
            "PERFECT natural midday sunlight as if photographed at 12 noon by an architectural photographer "
            "for Architectural Digest, bright ambient daylight evenly distributed through windows, "
            "no harsh shadows, perfectly balanced exposure, 5600K daylight color temperature, "
            "bright airy fresh atmosphere, clean white walls glowing softly"
        ),
        "prompt_full": (
            "Same exact scene completely preserved with all furniture and objects in identical positions, "
            "but bathed in PERFECT natural midday sunlight as if photographed at exactly 12 noon on a clear sunny day "
            "by a professional architectural photographer for Architectural Digest magazine. "
            "Beautiful bright ambient daylight pouring evenly through every window, "
            "soft diffused fill light reaching every corner of the room, no harsh shadows anywhere, "
            "perfectly balanced exposure with detail in both highlights and shadows, "
            "clean white walls glowing softly, every surface clearly visible and beautifully lit, "
            "color temperature 5600K daylight balanced, slight warm boost in midtones, "
            "subtle volumetric light rays visible in the air, fresh airy bright atmosphere, "
            "shot on Phase One IQ4 medium format camera with 35mm Schneider Kreuznach lens at f/5.6, "
            "tack sharp across entire frame, museum-quality real estate photography, "
            "extremely slow smooth gimbal dolly forward movement, professional cinematography, "
            "ultra-realistic, photorealistic, 4K cinematic quality, no text overlays, no people, no animals"
        ),
    },
    "orden_limpieza": {
        "label": "🧹 Orden y limpieza",
        "description": "Saca cosas de encima, ordena, estira la cama",
        "prompt_es": (
            "Misma escena pero perfectamente ordenada y limpia, calidad revista. Sin objetos personales, "
            "cables, papeles o desorden. Cama tendida estilo hotel con sábanas blancas y almohadas "
            "arregladas. Mesones y mesas completamente despejados. Cojines simétricos en sofás. "
            "Todo impecable como una suite de lujo."
        ),
        "prompt_core": (
            "PERFECTLY tidy magazine-quality immaculate state, ALL clutter and personal items removed "
            "(no papers, cables, cups, clothes, remotes), bed made hotel-style with crisp white linens "
            "and pillows arranged geometrically, all surfaces clear and spotless, "
            "cushions on sofas arranged symmetrically, luxury hotel suite quality"
        ),
        "prompt_full": (
            "Same scene transformed to PERFECTLY tidy magazine-quality immaculate state. "
            "Remove ALL clutter, personal items, papers, cups, glasses, cables, remotes, "
            "clothing, toys, books out of place, and any visual mess. "
            "Bed must be PERFECTLY made hotel-style with crisp white linens, "
            "fluffed decorative pillows arranged geometrically, throw blanket folded precisely. "
            "All surfaces completely clear and spotless—countertops empty and gleaming, "
            "tables clear of any objects, no items on floors. "
            "Cushions on sofas arranged in perfect symmetric pattern. "
            "Curtains perfectly draped, floor pristine and shining, every surface polished. "
            "Look like a luxury hotel suite ready for inspection. "
            "Same lighting and camera angle preserved, just impeccable order everywhere. "
            "Shot on Sony Venice with 35mm Master Prime lens, professional real estate cinematography, "
            "smooth slow camera movement, ultra-realistic, photorealistic, 4K, no text, no people"
        ),
    },
    "estabilizar_pro": {
        "label": "🎬 Estabilizar y profesionalizar",
        "description": "Rescata tomas movidas, borrosas o mal grabadas",
        "prompt_es": (
            "Misma escena pero como toma de cinematografía profesional. Movimiento de cámara "
            "ultra-suave estabilizado con gimbal, enfoque perfectamente nítido, composición arquitectónica "
            "balanceada. Como una toma de listado inmobiliario de alta gama."
        ),
        "prompt_core": (
            "ULTRA-SMOOTH gimbal-stabilized cinematic camera movement (NO shake or wobble), "
            "tack-sharp focus throughout entire frame, perfectly balanced architectural composition "
            "with leading lines, slow intentional deliberate motion (smooth dolly or gentle pan)"
        ),
        "prompt_full": (
            "Same scene completely re-imagined as a perfectly executed professional cinematography shot. "
            "Replace any camera shake, wobble or handheld instability with ULTRA-SMOOTH gimbal-stabilized "
            "cinematic movement, perfectly steady and deliberate. "
            "If original is blurry, restore tack-sharp focus throughout entire frame. "
            "If original is poorly composed, recompose to optimal real estate framing showing the space "
            "professionally with leading lines and balanced architectural composition. "
            "Slow, intentional, controlled camera motion—either a smooth dolly forward, "
            "gentle pan left to right, or graceful slow reveal of the space. "
            "Perfect exposure, balanced color grading, crystal clear image quality. "
            "Shot on ARRI Alexa Mini LF with 35mm Master Anamorphic lens, "
            "f/2.8 shallow depth of field with creamy bokeh, "
            "professional architectural cinematography for high-end real estate listing, "
            "ultra-realistic, photorealistic, 4K cinematic quality, no text, no people"
        ),
    },
    "agregar_personas": {
        "label": "👥 Personas viviendo el lugar",
        "description": "Una pareja tomando café, gente disfrutando el espacio",
        "prompt_es": (
            "Misma escena con una pareja joven y feliz viviendo el espacio naturalmente. "
            "Uno tomando café, el otro relajado leyendo. Ropa casual elegante en tonos neutros. "
            "Ellos no son el foco, la propiedad sigue siendo la estrella. Vibe aspiracional de lifestyle."
        ),
        "prompt_core": (
            "young attractive happy couple in their 30s naturally living and enjoying the space "
            "(one sipping coffee, the other relaxed reading or smiling), elegant casual clothing in "
            "neutral tones (white shirts light jeans), they are NOT the focus the property remains the star, "
            "slightly out of focus while architecture stays sharp, lifestyle aspirational vibe"
        ),
        "prompt_full": (
            "Same scene preserved, now with a young attractive happy couple in their 30s naturally "
            "living and enjoying the space. They appear casually—one of them sipping coffee from a mug, "
            "the other reading or smiling, both relaxed and comfortable. "
            "They wear elegant casual clothing in neutral tones (white shirts, light jeans). "
            "Their presence feels authentic and aspirational, like a lifestyle magazine cover. "
            "They are NOT the focus—the property remains the star—they just inhabit the space gracefully. "
            "Natural body language, soft smiles, intimate but discrete interaction. "
            "Beautiful warm natural daylight floods the scene, golden hour lighting through windows, "
            "shot on Sony FX6 with 35mm f/1.8 lens, shallow depth of field with creamy bokeh, "
            "they're slightly out of focus while the architecture stays sharp, "
            "smooth slow gimbal dolly movement, lifestyle real estate cinematography, "
            "aspirational vibe like a luxury home commercial, "
            "ultra-realistic, photorealistic, 4K cinematic quality, no text overlays"
        ),
    },
}


def combine_preset_prompts(preset_keys: list[str]) -> str:
    """Combina múltiples presets en UN prompt unificado para Runway.
    Toma el `prompt_core` de cada preset y los une con el footer cinematográfico común.
    """
    cores = []
    for key in preset_keys:
        preset = STYLE_PRESETS.get(key)
        if not preset:
            continue
        core = preset.get("prompt_core") or preset.get("prompt_full", "")
        if core:
            cores.append(core)
    if not cores:
        return ""
    footer = (
        "Shot on professional cinema camera with high-end lens, "
        "smooth slow gimbal dolly movement, "
        "professional real estate cinematography, "
        "ultra-realistic, photorealistic, 4K cinematic quality, no text overlays"
    )
    combined = (
        "Same scene preserved, transformed simultaneously with the following improvements: "
        + ". Also, ".join(cores)
        + ". " + footer
    )
    return combined


def _get_api_key() -> str:
    """Get Runway API key from env (raises if missing)."""
    api_key = os.environ.get("RUNWAY_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "RUNWAY_API_KEY no configurada en el server. Agregala en Render → Environment."
        )
    return api_key


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "X-Runway-Version": RUNWAY_VERSION,
        "Content-Type": "application/json",
    }


def extract_first_frame(video_path: str, output_image: str) -> tuple[bool, str]:
    """Extract the first frame of a video as JPG."""
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
                             target_w: int = 540, target_h: int = 960,
                             max_duration: Optional[float] = None) -> tuple[bool, str]:
    """Normalize Runway output to GreatDeal pipeline format.
    If max_duration is given, truncates the video to that duration
    (Runway always genera 5 o 10 seg, esto recorta al largo real del clip)."""
    cmd = ["ffmpeg", "-y", "-i", input_video]
    if max_duration is not None and max_duration > 0:
        cmd.extend(["-t", f"{max_duration:.2f}"])
    cmd.extend([
        "-vf", f"scale={target_w}:{target_h}:flags=lanczos:force_original_aspect_ratio=decrease,"
               f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=black",
        "-r", "30",
        "-c:v", "libx264", "-preset", "fast", "-crf", "21",
        "-pix_fmt", "yuv420p", "-an",
        output_video,
    ])
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return False, r.stderr[-500:]
    return True, ""


def create_image_to_video_task(
    api_key: str,
    prompt_image_data_url: str,
    prompt_text: str,
    duration: int = 5,
    ratio: str = "768:1280",
    model: str = "gen3a_turbo",
) -> tuple[bool, str | dict]:
    """Create a Runway image-to-video task. Returns (success, response or error)."""
    url = f"{RUNWAY_API_BASE}/image_to_video"
    body = {
        "model": model,
        "promptImage": prompt_image_data_url,
        "promptText": prompt_text[:1000],
        "duration": duration,
        "ratio": ratio,
    }
    try:
        r = requests.post(url, headers=_headers(api_key), json=body, timeout=60)
        if r.status_code >= 400:
            return False, f"Runway HTTP {r.status_code}: {r.text[:400]}"
        return True, r.json()
    except requests.RequestException as e:
        return False, f"Runway request failed: {str(e)[:300]}"


def get_task_status(api_key: str, task_id: str) -> tuple[bool, str | dict]:
    """Poll a Runway task. Returns (success, response or error)."""
    url = f"{RUNWAY_API_BASE}/tasks/{task_id}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "X-Runway-Version": RUNWAY_VERSION,
    }
    try:
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code >= 400:
            return False, f"Runway poll HTTP {r.status_code}: {r.text[:300]}"
        return True, r.json()
    except requests.RequestException as e:
        return False, f"Runway poll failed: {str(e)[:200]}"


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
    target_duration: Optional[float] = None,
) -> tuple[bool, str]:
    """End-to-end: regenera una toma con Runway video-to-video."""
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    # 1. Get API key
    try:
        api_key = _get_api_key()
    except Exception as e:
        return False, str(e)

    # 2. Extract first frame
    frame_path = str(work / "rw_frame.jpg")
    ok, err = extract_first_frame(input_video, frame_path)
    if not ok:
        return False, f"Frame extraction failed: {err}"

    # 3. Encode frame as data URL
    with open(frame_path, "rb") as f:
        frame_b64 = base64.b64encode(f.read()).decode("ascii")
    frame_data_url = f"data:image/jpeg;base64,{frame_b64}"

    # 4. Build enriched prompt
    enriched_prompt = (
        f"{prompt}. Professional real estate video, smooth steady camera, "
        f"high quality, photorealistic, no text overlays."
    )

    # 5. Create task
    ok, resp = create_image_to_video_task(
        api_key=api_key,
        prompt_image_data_url=frame_data_url,
        prompt_text=enriched_prompt,
        duration=duration,
        ratio=ratio,
        model=model,
    )
    if not ok:
        return False, str(resp)
    task_id = resp.get("id") if isinstance(resp, dict) else None
    if not task_id:
        return False, f"Runway no devolvió task ID: {resp}"

    # 6. Poll
    start_time = time.time()
    last_status = None
    while True:
        elapsed = time.time() - start_time
        if elapsed > max_wait_seconds:
            return False, f"Runway timeout después de {max_wait_seconds}s (status={last_status})"
        ok, resp = get_task_status(api_key, task_id)
        if not ok:
            return False, str(resp)
        if isinstance(resp, dict):
            last_status = resp.get("status")
            if last_status == "SUCCEEDED":
                break
            if last_status == "FAILED":
                err_msg = resp.get("failure") or resp.get("error") or "unknown"
                return False, f"Runway task failed: {err_msg}"
        time.sleep(poll_interval)

    # 7. Get output URL
    output_urls = resp.get("output", []) if isinstance(resp, dict) else []
    if not output_urls:
        return False, "Runway returned no output URL"
    video_url = output_urls[0]

    # 8. Download
    downloaded = str(work / "rw_raw.mp4")
    try:
        urllib.request.urlretrieve(video_url, downloaded)
    except Exception as e:
        return False, f"Download failed: {str(e)[:200]}"

    # 9. Normalize (con trim a target_duration si está)
    ok, err = normalize_runway_output(
        downloaded, output_video,
        max_duration=target_duration,
    )
    if not ok:
        return False, f"Normalize failed: {err}"

    return True, ""


def estimate_cost_usd(duration_seconds: int, model: str = "gen3a_turbo") -> float:
    """Estimación de costo aproximada en USD."""
    rates = {
        "gen3a_turbo": 0.05,
        "gen4_turbo": 0.10,
    }
    rate = rates.get(model, 0.05)
    return round(duration_seconds * rate, 2)
