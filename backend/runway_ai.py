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
        "description": "DRAMATICA mejora de luz natural, espacio brillante e impecable",
        "prompt_es": (
            "DRAMATICAMENTE iluminar la escena con luz natural cinematográfica intensa, "
            "como portada de revista Architectural Digest. SAME walls/furniture/layout (NO cambiar "
            "estructura), pero iluminación TOTALMENTE transformada: luz dorada cinematográfica "
            "entrando fuerte por ventanas, contraste rico, sombras dramáticas suaves, "
            "exposición perfectamente expuesta, blancos brillantes glowing, atmosphere etérea premium."
        ),
        "prompt_core": (
            "DRAMATICALLY transformed lighting (architecture/furniture UNCHANGED): "
            "intense cinematic natural sunlight pouring through windows creating volumetric god rays, "
            "warm golden hour glow, rich contrast, dramatic soft shadows, "
            "perfectly exposed highlights with detail in shadows, white walls glowing brilliantly, "
            "5600K balanced daylight pushed to magazine cover quality, Architectural Digest professional look"
        ),
        "prompt_full": (
            "EXACT same scene — walls, furniture, layout, decor, windows ALL preserved identically. "
            "Transform ONLY the lighting DRAMATICALLY to magazine cover quality: "
            "intense cinematic natural daylight pouring through every window creating beautiful "
            "volumetric god rays in the air, warm golden cinematic glow, rich high-end contrast, "
            "dramatic but soft shadows revealing texture and depth, perfectly balanced exposure "
            "with crisp highlights and detail in shadows, white walls glowing softly luminous, "
            "every surface beautifully illuminated, color temperature 5600K daylight balanced "
            "pushed to Architectural Digest cover quality, slight warm cinematic boost in midtones. "
            "Look as if shot at the PERFECT magical moment by a top architectural photographer "
            "with Phase One IQ4 150MP medium format camera, 35mm Schneider Kreuznach lens at f/5.6, "
            "professional 3-point HMI cinema lighting setup outside windows pushing light in, "
            "tack sharp museum-quality real estate photography. "
            "Extremely slow smooth gimbal dolly forward movement, professional cinematography, "
            "ultra-realistic, photorealistic, 4K cinematic, no text overlays, no people, no animals"
        ),
    },
    "orden_limpieza": {
        "label": "🧹 Orden y limpieza extrema",
        "description": "Vaciar TODO el desorden, look hotel 5 estrellas, calidad revista",
        "prompt_es": (
            "TRANSFORMACION EXTREMA a estado impecable nivel hotel 5 estrellas. SAME walls/furniture "
            "(NO cambiar estructura), pero VACIAR completamente: cero objetos personales, cero "
            "papeles, cero ropa, cero cables, cero items en superficies. Cama PERFECTAMENTE tendida "
            "estilo Four Seasons con sábanas blancas crujientes, almohadas arregladas en geometría "
            "perfecta. Mesones brillantes y vacíos. Cojines simétricos militarmente. "
            "Suelos brillando. Look IMPECABLE como suite presidencial."
        ),
        "prompt_core": (
            "EXTREME magazine-perfect tidiness (architecture UNCHANGED): "
            "ALL clutter REMOVED—zero papers, cables, cups, clothes, toys, remotes, personal items. "
            "Bed made hotel-style with crisp white Egyptian cotton linens, decorative pillows "
            "arranged geometrically perfect, throw blanket folded precisely. "
            "All countertops completely empty and gleaming spotless. "
            "Cushions on sofas militarily symmetric, floors pristine shining like just-polished. "
            "Look like Four Seasons presidential suite ready for VIP guest inspection"
        ),
        "prompt_full": (
            "SAME exact scene — walls, fixed furniture, layout, windows ALL preserved. "
            "Transform to ABSOLUTELY IMPECCABLE 5-star hotel showroom state — EXTREME makeover: "
            "REMOVE absolutely ALL clutter, personal items, papers, cups, glasses, cables, remotes, "
            "clothing, toys, books out of place, kitchen appliances on counters, products in bathroom, "
            "ANY visual mess whatsoever. Bed must be PERFECTLY made Four Seasons hotel-style with "
            "crisp white Egyptian cotton linens, fluffed decorative pillows arranged in geometric "
            "perfection, throw blanket folded precisely at 45 degrees. "
            "ALL surfaces completely clear and gleaming — countertops empty and polished, "
            "tables clear of all objects, nothing on floors, kitchen counters bare and shining. "
            "Cushions on sofas arranged in perfect mirror symmetry. Curtains perfectly draped. "
            "Floor pristine and reflective like just-mopped. Every surface polished, dust-free, "
            "glowing. Look like Four Seasons presidential suite ready for a magazine photoshoot. "
            "Same lighting and camera angle preserved, just IMPECCABLE order everywhere. "
            "Shot on Sony Venice cinema camera with 35mm Master Prime lens, professional real estate "
            "cinematography, ultra-realistic, photorealistic, 4K, no text, no people, no clutter"
        ),
    },
    "estabilizar_pro": {
        "label": "🎬 Cinematografía profesional",
        "description": "Transforma toma amateur en cinematografía broadcast con grading rico",
        "prompt_es": (
            "TRANSFORMACION COMPLETA a cinematografía broadcast premium. SAME walls/furniture/layout "
            "(NO cambiar estructura), pero el resto TOTALMENTE elevado: movimiento de cámara "
            "ULTRA suave estabilizado profesional, enfoque tack-sharp cristalino, color grading "
            "cinematográfico rico (highlights cálidos + shadows fríos estilo Netflix), composición "
            "arquitectónica balanceada con leading lines, depth of field cinemático. "
            "Pasar de toma amateur a calidad de comercial de inmobiliaria de lujo."
        ),
        "prompt_core": (
            "DRAMATIC cinematic upgrade (architecture UNCHANGED): "
            "ULTRA-smooth gimbal-stabilized motion (zero shake), tack-sharp crystal clear focus, "
            "rich cinematic color grading (warm highlights + teal shadows, Netflix-quality), "
            "perfect architectural composition with strong leading lines, "
            "shallow cinematic depth of field with creamy bokeh, "
            "elevated from amateur to luxury real estate commercial production value"
        ),
        "prompt_full": (
            "SAME exact scene — walls, furniture, layout, decor ALL preserved. "
            "Transform from amateur footage to BROADCAST CINEMA quality production: "
            "Replace ANY camera shake, wobble, handheld instability, blur or amateur look with "
            "ULTRA-SMOOTH professional gimbal-stabilized cinematic movement, perfectly steady, deliberate. "
            "Restore tack-sharp crystal-clear focus across entire frame. "
            "Recompose to optimal real estate framing with strong leading lines and balanced "
            "architectural composition. Apply DRAMATIC cinematic color grading: warm golden highlights, "
            "cool teal-ish shadows, rich saturation pushed to Netflix/HBO broadcast standard, "
            "deep blacks, brilliant whites, midtones with magazine quality contrast. "
            "Slow, intentional, controlled motion — smooth dolly forward, gentle pan, or graceful reveal. "
            "Perfect exposure, masterful color science, crystal clear premium image quality. "
            "Shot on ARRI Alexa Mini LF with 35mm Master Anamorphic lens, f/2.8 shallow depth of field "
            "with creamy organic bokeh, professional architectural cinematography for "
            "$10M+ real estate listing commercial. Ultra-realistic, photorealistic, 4K cinema, "
            "no text overlays, no people"
        ),
    },
    "agregar_personas": {
        "label": "👥 Personas viviendo el lugar",
        "description": "Pareja elegante disfrutando el espacio, vibe aspiracional",
        "prompt_es": (
            "Misma escena (SAME walls/furniture/layout, NO cambiar), AGREGAR pareja joven elegante "
            "viviendo el espacio: uno tomando café en taza minimalista, el otro relajado leyendo, "
            "ambos felices y cómodos. Ropa elegante casual tonos neutros (camisas blancas, jeans claros). "
            "Ellos out-of-focus, la propiedad foco principal. Iluminación dorada cinemática golden hour. "
            "Vibe aspiracional comercial de marca de lujo."
        ),
        "prompt_core": (
            "(architecture UNCHANGED) ADD young attractive happy couple in their 30s naturally "
            "enjoying the space (one sipping coffee, other relaxed reading or smiling), elegant casual "
            "clothing in neutral tones (white shirts light jeans), they're OUT OF FOCUS while "
            "architecture stays sharp, golden hour cinematic lighting, aspirational lifestyle commercial vibe"
        ),
        "prompt_full": (
            "SAME exact scene — walls, furniture, layout, decor ALL preserved. "
            "ADD a young attractive happy couple in their 30s naturally living and enjoying the space. "
            "They appear casually — one sipping coffee from a minimalist ceramic mug, the other "
            "reading or smiling softly, both relaxed and comfortable. They wear elegant casual "
            "clothing in neutral tones (crisp white shirts, light denim jeans). "
            "Their presence feels authentic, aspirational, like a luxury lifestyle magazine cover. "
            "They are NOT the focus — the property remains the absolute star — they just gracefully "
            "inhabit the space. Natural body language, soft genuine smiles, intimate but discrete. "
            "Beautiful warm golden hour cinematic daylight floods the scene through windows, "
            "rich cinematic color grading. Shot on Sony FX6 with 35mm f/1.8 lens, shallow depth of "
            "field with creamy bokeh, they're slightly OUT OF FOCUS while architecture stays tack-sharp. "
            "Smooth slow gimbal dolly movement, lifestyle real estate cinematography, "
            "aspirational vibe like luxury home commercial for top brand, "
            "ultra-realistic, photorealistic, 4K cinematic, no text overlays"
        ),
    },
    "golden_hour_dramatico": {
        "label": "🌅 Golden hour dramático",
        "description": "Atardecer dorado cinematográfico premium",
        "prompt_es": (
            "TRANSFORMAR a golden hour dramático cinematográfico. SAME walls/furniture/layout "
            "(NO cambiar), pero AGREGAR luz dorada espectacular del atardecer entrando por ventanas, "
            "creando volumetric rays visibles en el aire, sombras alargadas dramáticas, color "
            "grading cálido naranja-dorado-magenta, atmosphere mágica de hora dorada. Como "
            "comercial de lujo de marca de joyería o auto premium."
        ),
        "prompt_core": (
            "DRAMATIC golden hour transformation (architecture UNCHANGED): "
            "spectacular warm golden sunset light pouring through windows, "
            "visible volumetric god rays in the air, long dramatic shadows, "
            "rich warm orange-gold-magenta color grading, magical atmosphere, "
            "luxury jewelry commercial quality lighting"
        ),
        "prompt_full": (
            "SAME exact scene — walls, furniture, layout ALL preserved. "
            "TRANSFORM to dramatic GOLDEN HOUR cinematic moment: "
            "spectacular warm golden sunset light pouring through every window, "
            "creating beautiful visible volumetric god rays cutting through the air, "
            "long dramatic shadows stretching across floors and walls, "
            "rich cinematic color grading with warm oranges, deep golds, soft magentas, "
            "highlights glowing warm, shadows deep and rich, magical hour atmosphere. "
            "Look as if shot exactly 30 minutes before sunset by a top cinematographer "
            "for a luxury jewelry or premium car commercial. "
            "Shot on ARRI Alexa LF with anamorphic lens, T1.5 shallow depth, "
            "premium broadcast cinematography, ultra-realistic, photorealistic, 4K, no text, no people"
        ),
    },
    "revista_magazine": {
        "label": "📸 Calidad revista premium",
        "description": "Look Architectural Digest / Elle Decor — finish editorial",
        "prompt_es": (
            "TRANSFORMACION a calidad de revista de arquitectura premium (Architectural Digest / "
            "Elle Decor / Dwell). SAME walls/furniture/layout (NO cambiar), pero TOTALMENTE "
            "elevar el resto: iluminación editorial perfecta multi-fuente, composición editorial "
            "balanceada, color grading rico cinematográfico, todo limpio e impecable, "
            "vibe editorial sofisticada. Como portada de revista de diseño de interiores."
        ),
        "prompt_core": (
            "(architecture UNCHANGED) EDITORIAL magazine cover transformation: "
            "perfect multi-source editorial lighting, balanced editorial composition, "
            "rich cinematic color grading, immaculate cleanliness, "
            "sophisticated Architectural Digest / Elle Decor / Dwell editorial quality"
        ),
        "prompt_full": (
            "SAME exact scene — walls, furniture, layout ALL preserved identically. "
            "TRANSFORM to Architectural Digest magazine cover quality editorial photography: "
            "Perfect multi-source professional lighting setup, key light + fill + rim lighting, "
            "balanced editorial composition with rule of thirds and leading lines, "
            "rich sophisticated cinematic color grading editor-magazine quality, "
            "immaculate cleanliness (zero clutter, all surfaces polished), "
            "luxurious sophisticated editorial atmosphere. "
            "Look exactly like the cover photo of Architectural Digest, Elle Decor, or Dwell. "
            "Shot on Phase One IQ4 150MP medium format with 35mm at f/8 for maximum sharpness, "
            "tack sharp museum quality, perfect color science, "
            "extremely slow smooth dolly movement, premium cinematography, "
            "ultra-realistic, photorealistic, 4K editorial, no text, no people"
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
        "Shot on ARRI Alexa Mini LF with 35mm prime lens, "
        "smooth slow gimbal dolly cinematic movement, "
        "luxury real estate commercial cinematography production value, "
        "ultra-realistic, photorealistic, 4K cinematic quality, no text overlays"
    )
    combined = (
        "DRAMATICALLY TRANSFORM scene (walls/layout/architecture UNCHANGED), "
        "applying ALL these BOLD improvements simultaneously and visibly: "
        + ". ALSO, ".join(cores)
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

    # 4. Build enriched prompt — DRAMATICA transformación forzada con keywords
    # "DRAMATICALLY transform" para que Runway no sea conservador con los cambios.
    enriched_prompt = (
        f"DRAMATICALLY TRANSFORM the scene with these professional improvements: {prompt}. "
        f"Make the visual changes BOLD and CLEARLY VISIBLE compared to the original. "
        f"Keep walls, layout and fixed architecture identical, but elevate everything else to "
        f"luxury real estate commercial production quality. "
        f"Smooth steady cinematic camera, ultra high quality, photorealistic, 4K, no text overlays."
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
