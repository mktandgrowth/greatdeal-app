"""
GreatDeal · Subtítulos automáticos con OpenAI Whisper API.

Flujo:
  1. Transcribir audio (voz) con Whisper → segmentos con timestamps
  2. Generar archivo .ass (Advanced SubStation Alpha) con estilo cinematográfico
  3. Quemar subtítulos sobre el video con FFmpeg subtitles filter

Costo: ~$0.006 por minuto de audio (~$0.003 por reel típico).
Requiere: OPENAI_API_KEY env var.
"""
import os
import subprocess
import requests
from pathlib import Path
from typing import Optional


WHISPER_URL = "https://api.openai.com/v1/audio/transcriptions"

# ASS subtitle style — cinematográfico (blanco con borde negro)
# Sizing for 540x960 vertical
ASS_HEADER_TEMPLATE = """[Script Info]
ScriptType: v4.00+
PlayResX: 540
PlayResY: 960
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cinema,{font},26,&H00FFFFFF,&H000000FF,&H00000000,&HF0000000,0,0,0,0,100,100,0,0,3,6,2,2,100,100,360,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


# Prompt con vocabulario inmobiliario chileno — fuerza a Whisper a usar
# estos términos y reduce traducciones/errores. Se pasa como `prompt`.
WHISPER_PROMPT_CHILE = (
    "Esta es una descripción de una propiedad inmobiliaria en Chile, en español "
    "chileno. Palabras comunes: comuna, dormitorio, baño, living, comedor, "
    "cocina, terraza, jardín, estacionamiento, bodega, ascensor, conserjería, "
    "metros cuadrados, m², UF, pesos, departamento, casa, parcela, oficina, "
    "Las Condes, Vitacura, Providencia, Ñuñoa, La Reina, Lo Barnechea, Maipú, "
    "Santiago, Concepción, Viña del Mar. La narración es natural y conversacional."
)


def transcribe_with_whisper(
    audio_path: str,
    api_key: Optional[str] = None,
    language: str = "es",
) -> tuple[bool, dict | str]:
    """Transcribe audio file using OpenAI Whisper API.
    Forzamos español + prompt con vocabulario chileno inmobiliario + temperature=0
    para reducir traducciones espurias y errores de interpretación.
    Returns (success, result_dict or error_msg).
    result has keys: text, segments (list of {start, end, text}).
    """
    api_key = api_key or os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return False, "OPENAI_API_KEY no configurada en el server"
    if not Path(audio_path).exists():
        return False, f"Audio file no existe: {audio_path}"

    try:
        with open(audio_path, "rb") as f:
            files = {"file": (Path(audio_path).name, f, "application/octet-stream")}
            # Pedir timestamps por palabra + segmento para flexibilidad
            data = [
                ("model", "whisper-1"),
                ("response_format", "verbose_json"),
                ("language", language),
                # Forzar transcripción (no traducción) y dar contexto del dominio
                ("prompt", WHISPER_PROMPT_CHILE),
                # temperature=0 → más determinista, menos alucinaciones
                ("temperature", "0"),
                ("timestamp_granularities[]", "word"),
                ("timestamp_granularities[]", "segment"),
            ]
            headers = {"Authorization": f"Bearer {api_key}"}
            r = requests.post(WHISPER_URL, headers=headers, files=files,
                              data=data, timeout=120)
        if r.status_code != 200:
            return False, f"Whisper HTTP {r.status_code}: {r.text[:300]}"
        return True, r.json()
    except requests.RequestException as e:
        return False, f"Whisper request failed: {str(e)[:300]}"
    except Exception as e:
        return False, f"Whisper unexpected: {str(e)[:300]}"


def _format_ass_time(seconds: float) -> str:
    """Convert seconds (float) to ASS time format H:MM:SS.CC."""
    if seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _escape_ass_text(text: str) -> str:
    """Escape special chars for ASS dialogue."""
    return (text.replace("\\", "\\\\")
                .replace("{", "\\{")
                .replace("}", "\\}")
                .replace("\n", "\\N"))


def generate_ass_file(
    segments: list[dict],
    output_path: str,
    font: str = "Poppins",
    time_offset: float = 0.0,
    words: Optional[list[dict]] = None,
    chunk_words: int = 3,
) -> tuple[bool, str]:
    """Generate an .ass subtitle file.
    Si `words` está disponible (lista de {word, start, end}), agrupa en chunks
    cortos de `chunk_words` palabras (estilo TikTok/Reels). Si no, divide los
    segments largos en chunks usando estimación de timing.
    """
    try:
        header = ASS_HEADER_TEMPLATE.format(font=font)
        lines = [header]

        # MODO 1: tenemos words con timestamps individuales (mejor)
        if words and len(words) > 0:
            chunks = []
            buf = []
            for w in words:
                word_text = (w.get("word", "") or "").strip()
                if not word_text:
                    continue
                buf.append({
                    "word": word_text,
                    "start": float(w.get("start", 0)),
                    "end": float(w.get("end", 0)),
                })
                if len(buf) >= chunk_words:
                    chunks.append(buf)
                    buf = []
            if buf:
                chunks.append(buf)

            for chunk in chunks:
                start = chunk[0]["start"] + time_offset
                end = chunk[-1]["end"] + time_offset
                # Gap chiquito entre chunks para que se vean separados
                end = max(end - 0.05, start + 0.3)
                text = _escape_ass_text(" ".join(w["word"] for w in chunk))
                text_with_fade = f"{{\\fad(60,60)}}{text}"
                dialogue = (
                    f"Dialogue: 0,{_format_ass_time(start)},"
                    f"{_format_ass_time(end)},Cinema,,0,0,0,,{text_with_fade}"
                )
                lines.append(dialogue)

        # MODO 2: solo segments (frases largas) — los partimos por palabras + timing estimado
        else:
            for seg in segments:
                start = float(seg.get("start", 0)) + time_offset
                end = float(seg.get("end", start + 2)) + time_offset
                text_raw = (seg.get("text", "") or "").strip()
                if not text_raw:
                    continue
                words_in_seg = text_raw.split()
                total_words = len(words_in_seg)
                if total_words == 0:
                    continue
                total_dur = max(end - start, 0.5)
                # Dividir en chunks de chunk_words
                num_chunks = max(1, (total_words + chunk_words - 1) // chunk_words)
                chunk_dur = total_dur / num_chunks
                for ci in range(num_chunks):
                    chunk_words_list = words_in_seg[ci * chunk_words:(ci + 1) * chunk_words]
                    if not chunk_words_list:
                        continue
                    c_start = start + ci * chunk_dur
                    c_end = c_start + chunk_dur - 0.05  # mini gap
                    text = _escape_ass_text(" ".join(chunk_words_list))
                    text_with_fade = f"{{\\fad(80,80)}}{text}"
                    dialogue = (
                        f"Dialogue: 0,{_format_ass_time(c_start)},"
                        f"{_format_ass_time(c_end)},Cinema,,0,0,0,,{text_with_fade}"
                    )
                    lines.append(dialogue)

        Path(output_path).write_text("\n".join(lines), encoding="utf-8")
        return True, ""
    except Exception as e:
        return False, f"ASS generation failed: {str(e)[:300]}"


def burn_subtitles(
    video_path: str,
    ass_path: str,
    output_path: str,
) -> tuple[bool, str]:
    """Burn .ass subtitles into video using FFmpeg ass filter.
    Usa ass= (no subtitles=) que es específico para ASS y más confiable.
    También agrega fontsdir para asegurar que libass encuentre las fuentes Montserrat.
    """
    # Path escape para FFmpeg filter
    ass_escaped = str(ass_path).replace("\\", "/").replace(":", "\\:")
    fontsdir_escaped = "/usr/share/fonts/truetype/montserrat"
    # Usar 'ass' filter (específico para .ass files, mejor que 'subtitles=')
    # fontsdir= le dice a libass dónde buscar las fuentes (importante para Montserrat)
    vf = f"ass='{ass_escaped}':fontsdir={fontsdir_escaped}"
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
        "-c:a", "copy",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        output_path,
    ]
    print(f"[ffmpeg] burn subtitles → {Path(output_path).name}", flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        # Logueamos el error completo de FFmpeg para diagnóstico
        err_tail = (r.stderr or "")[-2000:]
        print(f"[ffmpeg] burn subtitles FAILED:\n{err_tail}", flush=True)
        return False, err_tail
    return True, ""


def apply_auto_subtitles(
    video_path: str,
    audio_path: str,
    work_dir: str,
    output_path: str,
    language: str = "es",
) -> tuple[bool, str]:
    """End-to-end: transcribe audio + generate ASS + burn into video.
    También guarda los segments transcritos en `subs_segments.json` dentro de
    work_dir, para que después se puedan editar y re-quemar.
    Returns (success, error_msg)."""
    import json
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    # 1. Transcribe
    ok, result = transcribe_with_whisper(audio_path, language=language)
    if not ok:
        return False, f"Transcripción: {result}"

    segments = result.get("segments", []) if isinstance(result, dict) else []
    words = result.get("words", []) if isinstance(result, dict) else []

    # Guardar segments raw para edición posterior (solo campos relevantes)
    try:
        clean_segments = [
            {
                "id": i,
                "start": float(s.get("start", 0)),
                "end": float(s.get("end", 0)),
                "text": (s.get("text", "") or "").strip(),
            }
            for i, s in enumerate(segments)
        ]
        (work / "subs_segments.json").write_text(
            json.dumps(clean_segments, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[subs] no pude guardar segments json: {e}", flush=True)

    if not segments and not words:
        # No hubo audio detectado — copy original video unchanged
        import shutil
        shutil.copy(video_path, output_path)
        return True, "no-segments-detected"

    # 2. Generate ASS file con chunks de 3 palabras estilo TikTok
    ass_path = str(work / "subtitles.ass")
    ok, err = generate_ass_file(segments, ass_path, words=words,
                                 font="Montserrat", chunk_words=3)
    if not ok:
        return False, f"ASS: {err}"

    # 3. Burn into video
    ok, err = burn_subtitles(video_path, ass_path, output_path)
    if not ok:
        return False, f"Burn: {err}"

    return True, ""


def reapply_edited_subtitles(
    pre_subs_video: str,
    edited_segments: list[dict],
    work_dir: str,
    output_path: str,
) -> tuple[bool, str]:
    """Re-aplica subtítulos con el texto editado por el usuario.
    edited_segments: lista de {start, end, text}.
    Regenera el ASS y re-quema sobre el video pre-subs (sin re-procesar todo).
    """
    import json
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    # Validar/normalizar segments
    safe_segments = []
    for s in edited_segments:
        try:
            start = float(s.get("start", 0))
            end = float(s.get("end", start + 1.5))
            text = (s.get("text", "") or "").strip()
            if not text:
                continue
            if end <= start:
                end = start + 1.5
            safe_segments.append({"start": start, "end": end, "text": text})
        except (TypeError, ValueError):
            continue

    if not safe_segments:
        return False, "No quedaron segments válidos después de la edición"

    # Persistir los segments editados (sobrescribe los originales)
    try:
        (work / "subs_segments.json").write_text(
            json.dumps(
                [{"id": i, **s} for i, s in enumerate(safe_segments)],
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass

    # Regenerar ASS
    ass_path = str(work / "subtitles_edited.ass")
    ok, err = generate_ass_file(safe_segments, ass_path, words=None, font="Montserrat")
    if not ok:
        return False, f"ASS: {err}"

    # Re-quemar
    ok, err = burn_subtitles(pre_subs_video, ass_path, output_path)
    if not ok:
        return False, f"Burn: {err}"
    return True, ""
