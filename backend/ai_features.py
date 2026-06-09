"""
GreatDeal · IA Features
Integraciones con OpenAI GPT-4o-mini (texto) y GPT-4o (visión) para:
  1. Auto-caption Instagram con hashtags
  2. Visión por toma: categorizar espacio + sugerir título
  3. Auto-feedback de calidad: detectar problemas en clips antes de procesar

Costo aproximado por reel completo (3-5 clips):
  - Auto-caption: ~$0.001
  - Visión por toma: ~$0.005 c/u → ~$0.025
  - Auto-feedback: ~$0.005 c/u → ~$0.025
  Total: ~$0.05 por reel — irrisorio comparado con Runway ($0.25 por toma).
"""
import os
import json
import base64
import subprocess
from pathlib import Path
from typing import Optional

import requests


OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"


def _api_key() -> Optional[str]:
    return os.environ.get("OPENAI_API_KEY", "").strip() or None


def _post_chat(messages: list, model: str = "gpt-4o-mini",
               max_tokens: int = 600, temperature: float = 0.7) -> tuple[bool, str | dict]:
    """Wrapper para llamadas a OpenAI Chat API."""
    key = _api_key()
    if not key:
        return False, "OPENAI_API_KEY no configurada"
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    try:
        r = requests.post(
            OPENAI_CHAT_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        if r.status_code != 200:
            return False, f"OpenAI HTTP {r.status_code}: {r.text[:300]}"
        data = r.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return True, content
    except requests.RequestException as e:
        return False, f"OpenAI request failed: {str(e)[:200]}"
    except Exception as e:
        return False, f"OpenAI unexpected: {str(e)[:200]}"


# ════════════════════════════════════════════════════════════════════
# FEATURE 1: AUTO-CAPTION INSTAGRAM
# ════════════════════════════════════════════════════════════════════

def generate_instagram_caption(property_data: dict, description: str = "") -> tuple[bool, str]:
    """Genera un caption profesional para Instagram listo para publicar.
    property_data: {tipo, comuna, m2, dorms, banos, precio_uf, diferenciador}
    description: descripción libre del usuario (opcional, generalmente de voz transcrita)

    Retorna (success, caption_text).
    """
    tipo = property_data.get("tipo", "propiedad")
    comuna = property_data.get("comuna", "")
    m2 = property_data.get("m2", "")
    dorms = property_data.get("dorms", "")
    banos = property_data.get("banos", "")
    precio = property_data.get("precio_uf", "")
    diferenciador = property_data.get("diferenciador") or property_data.get("tagline", "")

    # Armar bullets de datos disponibles
    bullets = []
    if m2: bullets.append(f"{m2} m²")
    if dorms: bullets.append(f"{dorms} dormitorios")
    if banos: bullets.append(f"{banos} baños")
    if precio: bullets.append(f"UF {precio}")
    bullets_str = " · ".join(bullets) if bullets else "(sin datos)"

    system_prompt = (
        "Eres un copywriter de marketing inmobiliario CHILENO especialista en Instagram. "
        "Escribes copy en ESPAÑOL DE CHILE (NO argentino, NO neutro). "
        "REGLAS DE ESPAÑOL CHILENO — críticas: "
        "1) Usa siempre 'tú' (NUNCA 'vos', NUNCA 'che', NUNCA 'sos/tenés/querés'). "
        "2) Verbos en imperativo con 'tú': 'Agenda', 'Conoce', 'Descubre', 'Mira', 'Visita' "
        "   (NUNCA 'agendá', 'conocé', 'descubrí', 'mirá'). "
        "3) Para casos formales/neutros usa imperativo impersonal: 'Agenda tu visita', "
        "   'Solicita más información'. "
        "4) Vocabulario chileno apropiado: 'departamento' (no 'depto'), 'arriendo', "
        "   'corretaje', 'cocina americana', 'piso flotante', 'aluminio', 'logia'. "
        "5) NO uses modismos informales como 'weón', 'po', 'cachái' (es marketing, no chat). "
        "6) Hashtags 100% chilenos: #PropiedadesChile #InmobiliariaChile #VivirEnSantiago "
        "   #CasasChile #DeptosChile #VentaPropiedades #ComunaXYZ etc. "
        "Tono: profesional pero cercano, aspiracional. Emojis con criterio (no demasiados)."
    )

    user_prompt = f"""Genera un copy/descripción de Instagram en ESPAÑOL DE CHILE para este reel de propiedad:

**Tipo:** {tipo}
**Ubicación:** {comuna or 'Chile'}
**Características:** {bullets_str}
{f'**Diferenciador:** {diferenciador}' if diferenciador else ''}
{f'**Descripción del agente:** {description}' if description else ''}

Estructura:
1. Frase de gancho (1-2 líneas con emoji llamativo al inicio)
2. Descripción breve (3-5 líneas, características destacables)
3. CTA claro EN ESPAÑOL CHILENO: usa 'Agenda tu visita', 'Escríbenos', 'Conoce más', 'Solicita más información', 'Contáctanos por DM' (NUNCA 'agendá', 'escribinos', 'conocé').
4. Línea separadora
5. 12-15 hashtags chilenos relevantes mezclando: ubicación específica, tipo de propiedad, mercado inmobiliario, estilo de vida chileno

Tono: profesional pero cercano, aspiracional. Máximo 2200 caracteres totales.

IMPORTANTE: revisa el texto antes de devolverlo y asegúrate que NO uses argentino ('vos', 'sos', 'tenés', 'querés', 'agendá', 'conocé', 'descubrí'). Solo español chileno con 'tú' o impersonal.

Devuelve SOLO el copy, sin meta-comentarios."""

    ok, result = _post_chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        model="gpt-4o-mini",
        max_tokens=700,
        temperature=0.85,
    )
    if not ok:
        return False, str(result)
    return True, str(result).strip()


# ════════════════════════════════════════════════════════════════════
# FEATURE 2: VISIÓN POR TOMA — categorizar + sugerir título
# ════════════════════════════════════════════════════════════════════

def _extract_frame_b64(video_path: str, work_dir: str) -> tuple[bool, str]:
    """Extrae primer frame del video y lo retorna como base64 jpg."""
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    frame_path = work / "analyze_frame.jpg"
    cmd = [
        "ffmpeg", "-y",
        "-fflags", "+genpts+igndts",
        "-i", video_path,
        "-ss", "0.5",  # un poco adelante del primer frame para evitar negros
        "-vframes", "1",
        "-vf", "scale=720:-1",  # 720px ancho para no mandar imagen enorme
        "-q:v", "3",
        str(frame_path),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0 or not frame_path.exists():
            return False, (r.stderr or "")[-300:]
        b64 = base64.b64encode(frame_path.read_bytes()).decode("ascii")
        return True, b64
    except Exception as e:
        return False, f"frame extraction failed: {str(e)[:200]}"


def analyze_clip(video_path: str, work_dir: str) -> tuple[bool, dict | str]:
    """Analiza un clip con GPT-4o Vision. Devuelve:
        {
          "category": "cocina" | "living" | "dormitorio" | "baño" | "exterior" | "vista" | "otro",
          "suggested_title": "Cocina americana con isla",  # máx 35 chars
          "suggested_subtitle": "Mesón de granito y campana inox",  # máx 50 chars
          "quality_score": 1-10,
          "quality_issues": ["borroso", "mal iluminado", "objetos personales visibles", ...]
        }
    """
    ok, frame_b64 = _extract_frame_b64(video_path, work_dir)
    if not ok:
        return False, f"frame: {frame_b64}"

    system_prompt = (
        "Sos un experto en marketing inmobiliario chileno y fotografía de propiedades. "
        "Analizás clips de video de propiedades para sugerir títulos y detectar problemas."
    )

    user_text = """Analizá este frame de un clip para un reel inmobiliario.

Respondé SOLAMENTE con un JSON válido con estas keys exactas:
- "category": uno de [exterior, entrada, living, comedor, cocina, dormitorio, bano, terraza, vista, jardin, otro]
- "suggested_title": título corto en español chileno (máx 32 caracteres) — específico y atractivo
- "suggested_subtitle": subtítulo descriptivo (máx 48 caracteres) — destaca una feature
- "quality_score": número 1-10 evaluando calidad fotográfica (10 = pro, 1 = malo)
- "quality_issues": array de strings con problemas detectados (vacío si está perfecto). Posibles: "borroso", "mal iluminado", "muy oscuro", "muy claro", "objetos personales visibles", "desorden visible", "personas en la toma", "ángulo poco favorable", "cámara movida"

Ejemplos buenos de title/subtitle:
- "Cocina americana" / "Isla de mármol y campana inox"
- "Dormitorio principal" / "Walk-in closet y vista al parque"
- "Terraza panorámica" / "120 m² con quincho y jacuzzi"

NO inventes datos que no se ven (no digas m² si no podés saberlos). Sé honesto con quality_score.
Devolvé SOLO el JSON, sin markdown ni explicaciones."""

    ok, result = _post_chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{frame_b64}",
                        "detail": "low",  # 'low' = más barato (~$0.001 por imagen)
                    }},
                ],
            },
        ],
        model="gpt-4o",  # necesitamos visión, mini no soporta image_url igual de bien
        max_tokens=400,
        temperature=0.4,
    )
    if not ok:
        return False, str(result)

    # Parsear JSON
    text = str(result).strip()
    # A veces vienen rodeado de ```json ... ```
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return False, f"JSON inválido devuelto por GPT: {text[:200]}"

    # Validar y normalizar
    return True, {
        "category": str(data.get("category", "otro")).lower(),
        "suggested_title": str(data.get("suggested_title", ""))[:36],
        "suggested_subtitle": str(data.get("suggested_subtitle", ""))[:52],
        "quality_score": int(data.get("quality_score", 7)),
        "quality_issues": [str(x) for x in (data.get("quality_issues") or [])],
    }


# ════════════════════════════════════════════════════════════════════
# FEATURE 3: AUTO-FEEDBACK DE CALIDAD (global del reel)
# ════════════════════════════════════════════════════════════════════

def generate_quality_report(clip_analyses: list[dict],
                             property_data: Optional[dict] = None) -> tuple[bool, dict]:
    """Toma una lista de análisis de clips (output de analyze_clip) y genera:
        {
          "overall_score": 1-10,
          "summary": "string corto, 1-2 oraciones",
          "missing_shots": ["fachada", "vista", ...],  # tomas que faltan
          "recommendations": [
              "Re-grabá el clip 2 — está borroso",
              "Agregá una toma de la fachada — aumenta clicks",
              ...
          ]
        }
    """
    if not clip_analyses:
        return False, {"error": "No hay clips analizados"}

    # Resumen ejecutivo del input
    categories = [c.get("category", "otro") for c in clip_analyses]
    avg_score = sum(c.get("quality_score", 7) for c in clip_analyses) / max(1, len(clip_analyses))
    issues_per_clip = [
        {"clip": i + 1, "category": c.get("category"),
         "score": c.get("quality_score"), "issues": c.get("quality_issues", [])}
        for i, c in enumerate(clip_analyses)
    ]

    property_summary = ""
    if property_data:
        bits = []
        if property_data.get("tipo"): bits.append(property_data["tipo"])
        if property_data.get("comuna"): bits.append(property_data["comuna"])
        if property_data.get("m2"): bits.append(f"{property_data['m2']} m²")
        if property_data.get("dorms"): bits.append(f"{property_data['dorms']} dorms")
        if bits: property_summary = " · ".join(bits)

    system_prompt = (
        "Sos un consultor experto en contenido inmobiliario para redes sociales. "
        "Analizás conjuntos de tomas de un reel y das feedback profesional accionable."
    )

    user_prompt = f"""Analizá las siguientes tomas para un reel inmobiliario.

{f'**Propiedad:** {property_summary}' if property_summary else ''}

**Tomas detectadas:** {', '.join(categories)}

**Detalle por clip:**
{json.dumps(issues_per_clip, ensure_ascii=False, indent=2)}

Generá un reporte de feedback constructivo en formato JSON con estas keys:
- "overall_score": número 1-10 evaluando el set completo de tomas
- "summary": 1-2 oraciones de feedback general
- "missing_shots": array de strings con tipos de tomas que faltan y serían valiosas (ej: ["fachada", "vista panorámica", "terraza"]). Para una propiedad standard de venta tipicamente conviene: exterior/fachada, living principal, cocina, dormitorio principal, baño principal, vista/terraza si aplica.
- "recommendations": array de 2-5 strings con recomendaciones específicas y accionables. Mencioná números de clip cuando aplique (ej: "Re-grabá el clip 2: está borroso").

Devolvé SOLO el JSON, sin markdown."""

    ok, result = _post_chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        model="gpt-4o-mini",
        max_tokens=600,
        temperature=0.5,
    )
    if not ok:
        return False, {"error": str(result)}

    text = str(result).strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return False, {"error": f"JSON inválido: {text[:200]}"}

    return True, {
        "overall_score": int(data.get("overall_score", int(avg_score))),
        "summary": str(data.get("summary", "")),
        "missing_shots": [str(x) for x in (data.get("missing_shots") or [])],
        "recommendations": [str(x) for x in (data.get("recommendations") or [])],
    }
