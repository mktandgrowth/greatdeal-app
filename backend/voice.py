"""
GreatDeal · ElevenLabs voiceover integration
Genera voiceover desde texto. Cuando Vale me dé su API key, esto funciona end-to-end.
"""
import os
import requests
from pathlib import Path
from typing import Optional

# Default ElevenLabs voices that work well for Spanish real estate narration.
# Voice IDs from ElevenLabs library (verify these at https://elevenlabs.io/app/voice-library)
CURATED_VOICES = {
    "refugio_calido": {
        "name": "Voz cálida",
        "description": "Mujer 30-38, tono cálido pausado. Para casas con carácter.",
        "voice_id": "EXAVITQu4vr4xnSDxMaL",  # Bella - warm female
        "model": "eleven_multilingual_v2",
        "settings": {"stability": 0.55, "similarity_boost": 0.75, "style": 0.4}
    },
    "premium_minimal": {
        "name": "Voz premium minimalista",
        "description": "Mujer 30-35, elegante y articulada. Para depto/casa moderna.",
        "voice_id": "MF3mGyEYCl7XYWbV9V6O",  # Elli - clear female
        "model": "eleven_multilingual_v2",
        "settings": {"stability": 0.6, "similarity_boost": 0.7, "style": 0.3}
    },
    "joven_aspiracional": {
        "name": "Voz joven aspiracional",
        "description": "Mujer 25-30, fresca pero no infantil. Para lofts/primer hogar.",
        "voice_id": "21m00Tcm4TlvDq8ikWAM",  # Rachel - young female
        "model": "eleven_multilingual_v2",
        "settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.5}
    },
    "hombre_confianza": {
        "name": "Voz masculina confianza",
        "description": "Hombre 35-45, tono grave firme. Para inversión/comerciales.",
        "voice_id": "VR6AewLTigWG4xSOukaG",  # Arnold - mature male
        "model": "eleven_multilingual_v2",
        "settings": {"stability": 0.6, "similarity_boost": 0.7, "style": 0.35}
    },
}


def list_voices() -> list[dict]:
    """Return curated voice list as dicts (for frontend selector)."""
    return [
        {"id": k, "name": v["name"], "description": v["description"]}
        for k, v in CURATED_VOICES.items()
    ]


def generate_voiceover(text: str, voice_key: str, output_path: str,
                        api_key: Optional[str] = None) -> tuple[bool, str]:
    """
    Generate voiceover MP3 using ElevenLabs API.

    Requires ELEVENLABS_API_KEY env variable OR explicit api_key arg.
    """
    api_key = api_key or os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        return False, "Missing ELEVENLABS_API_KEY (set env var or pass api_key)"

    if voice_key not in CURATED_VOICES:
        return False, f"Unknown voice key: {voice_key}. Available: {list(CURATED_VOICES.keys())}"

    voice = CURATED_VOICES[voice_key]
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice['voice_id']}"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg"
    }
    payload = {
        "text": text,
        "model_id": voice["model"],
        "voice_settings": voice["settings"]
    }
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=60)
    except requests.RequestException as e:
        return False, f"Network error: {e}"

    if r.status_code != 200:
        return False, f"ElevenLabs API error {r.status_code}: {r.text[:500]}"

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(r.content)
    return True, ""


def build_voiceover_script(property_data: dict) -> str:
    """
    Generate a natural-sounding voiceover script from property data.
    Returns ~30s of speech (about 75-90 words at normal pace).
    """
    tipo = property_data.get("tipo", "propiedad").lower()
    comuna = property_data.get("comuna", "")
    m2 = property_data.get("m2", "")
    m2_terreno = property_data.get("m2_terreno", "")
    dorms = property_data.get("dorms", "")
    banos = property_data.get("banos", "")
    precio = property_data.get("precio_uf", "")
    diferenciador = property_data.get("diferenciador", "")

    parts = []
    # Hook
    if diferenciador:
        parts.append(f"{diferenciador}.")
    else:
        parts.append(f"Una {tipo} con carácter te espera en {comuna}.")

    # Location detail
    if comuna:
        parts.append(f"Ubicada en {comuna}, este espacio combina amplitud con tranquilidad.")

    # Specs
    spec_bits = []
    if m2:
        spec_bits.append(f"{m2} metros cuadrados construidos")
    if m2_terreno:
        spec_bits.append(f"{m2_terreno} metros de terreno")
    if dorms:
        spec_bits.append(f"{dorms} dormitorios")
    if banos:
        spec_bits.append(f"{banos} baños")
    if spec_bits:
        parts.append(", ".join(spec_bits) + ".")

    # Atmospheric closer
    parts.append("No es solo una propiedad. Es un refugio.")

    # CTA
    if precio:
        parts.append(f"Desde {precio} UF. Conoce más en greatdeal.vercel.app.")
    else:
        parts.append("Conoce más en greatdeal.vercel.app.")

    return " ".join(parts)
