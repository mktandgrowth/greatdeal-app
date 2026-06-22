"""
GreatDeal · Backend FastAPI (v0.2 — secciones)
Endpoints:
  GET  /                          → sirve el frontend HTML
  GET  /api/voices                → lista de voces curadas
  POST /api/jobs                  → crea un job (clips + secciones + cta + logo)
  GET  /api/jobs/{job_id}         → estado de un job
  GET  /api/jobs/{job_id}/download → descarga el MP4 final
  POST /api/jobs/{job_id}/reprocess → re-procesa el job con nuevos sections/cta_data
"""
import os
import shutil
import threading
import uuid
import json
from pathlib import Path
from typing import Optional
from datetime import datetime

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Body
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from editor import build_reel, MUSIC_PRESETS
from voice import list_voices, generate_voiceover, build_voiceover_script
from runway_ai import (
    enhance_clip_with_runway, STYLE_PRESETS as RUNWAY_PRESETS,
    estimate_cost_usd, combine_preset_prompts,
)

# Paths
ROOT = Path(__file__).parent.parent
UPLOAD_DIR = ROOT / "uploads"
OUTPUT_DIR = ROOT / "outputs"
FRONTEND_DIR = ROOT / "frontend"
WORK_DIR = ROOT / "work"

for p in [UPLOAD_DIR, OUTPUT_DIR, WORK_DIR]:
    p.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="GreatDeal Editor API", version="0.2")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# In-memory job store
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


def set_job(job_id: str, **updates):
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(updates)
            JOBS[job_id]["updated"] = datetime.utcnow().isoformat()


@app.get("/")
async def root():
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return JSONResponse({"error": "frontend/index.html not found"}, status_code=404)


@app.head("/")
async def root_head():
    """Health check HEAD endpoint for Render."""
    return JSONResponse({})


@app.get("/health")
async def health():
    """Lightweight health endpoint."""
    return {"status": "ok"}


@app.head("/health")
async def health_head():
    return JSONResponse({})


# ─── PUBLISH TO C2C MARKETPLACE ──────────────────────────────────────────
# Inserta una propiedad en la tabla `properties` de Supabase (de properties-app)
# para que aparezca automáticamente en el feed de /comprar.
#
# Requiere env vars en Render:
#   SUPABASE_URL                   ej: https://xxxx.supabase.co
#   SUPABASE_SERVICE_ROLE_KEY      key 'service_role' (NO la anon — bypassa RLS)
#
# Schema esperado (tabla properties en properties-app):
#   type, operacion, price, currency, comuna, beds, baths, area,
#   title, description, video_url, thumbnail_url
@app.post("/api/publish")
async def publish_to_marketplace(payload: dict = Body(...)):
    """Publica la propiedad recién generada en el feed de C2C properties."""
    import requests
    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not supabase_url or not supabase_key:
        raise HTTPException(
            500,
            "Supabase no configurada — falta SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY en Render env vars",
        )

    video_url = payload.get("video_url")
    if not video_url:
        raise HTTPException(400, "Falta video_url en el payload")

    # Helpers de coerción segura
    def _f(v):
        try:
            return float(v) if v not in (None, "", "null") else None
        except (TypeError, ValueError):
            return None

    def _i(v):
        try:
            return int(float(v)) if v not in (None, "", "null") else None
        except (TypeError, ValueError):
            return None

    row = {
        "type":          (payload.get("type") or "Casa").strip()[:40],
        "operacion":     (payload.get("operacion") or "venta").lower().strip(),
        "price":         _f(payload.get("price")),
        "currency":      (payload.get("currency") or "UF").strip()[:8],
        "comuna":        (payload.get("comuna") or "").strip()[:80],
        "beds":          _i(payload.get("beds")),
        "baths":         _i(payload.get("baths")),
        "area":          _f(payload.get("area")),
        "title":         (payload.get("title") or "").strip()[:140],
        "description":   (payload.get("description") or "").strip(),
        "video_url":     video_url,
        "thumbnail_url": payload.get("thumbnail_url"),
    }
    # Saca claves con valor None para no pisar defaults de la DB
    row = {k: v for k, v in row.items() if v is not None}

    try:
        res = requests.post(
            f"{supabase_url}/rest/v1/properties",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
            json=row,
            timeout=15,
        )
    except Exception as e:
        raise HTTPException(502, f"No se pudo contactar Supabase: {e}")

    if res.status_code not in (200, 201):
        raise HTTPException(
            500,
            f"Supabase rechazó el insert ({res.status_code}): {res.text[:300]}",
        )

    inserted = res.json()
    prop_id = None
    if isinstance(inserted, list) and inserted:
        prop_id = inserted[0].get("id")
    elif isinstance(inserted, dict):
        prop_id = inserted.get("id")

    return {
        "ok": True,
        "id": prop_id,
        "feed_url": "https://greatdeal-platform.vercel.app/comprar",
    }


@app.get("/api/voices")
async def voices():
    return {"voices": list_voices()}


@app.get("/api/music-presets")
async def music_presets():
    """Lista de presets de música sintetizada disponibles."""
    return {
        "presets": [
            {"key": k, "label": v["label"], "description": v["description"]}
            for k, v in MUSIC_PRESETS.items()
        ]
    }


@app.get("/api/cinematic-filters")
async def cinematic_filters():
    """Lista de filtros cinematográficos profesionales disponibles."""
    from editor import CINEMATIC_FILTERS
    return {
        "filters": [
            {"key": k, "label": v["label"], "description": v["description"]}
            for k, v in CINEMATIC_FILTERS.items()
        ]
    }


@app.get("/api/music-preview/{preset_key}")
async def music_preview(preset_key: str):
    """Sirve un preview del preset. Intenta primero el mp3 real (Mixkit);
    si la CDN bloquea (403 hotlinking) o falla, genera un AAC sintetizado
    como fallback para que la app siga funcionando."""
    from editor import download_music_track, synth_music_preset, MUSIC_PRESETS as _MP
    if preset_key not in _MP:
        raise HTTPException(404, f"Preset '{preset_key}' no encontrado")

    # 1) Intentar mp3 real (rápido si está cacheado)
    ok, result = download_music_track(preset_key)
    if ok:
        return FileResponse(result, media_type="audio/mpeg",
                            headers={"Cache-Control": "public, max-age=86400",
                                     "Access-Control-Allow-Origin": "*"})

    # 2) Fallback: sintetizar un AAC de 8s
    print(f"[music-preview] mp3 falló ({result}), usando synth fallback", flush=True)
    preview_dir = OUTPUT_DIR / "music_previews"
    preview_dir.mkdir(exist_ok=True)
    preview_path = preview_dir / f"{preset_key}.aac"
    if not preview_path.exists() or preview_path.stat().st_size < 100:
        if preview_path.exists():
            preview_path.unlink()
        ok2, err = synth_music_preset(preset_key, str(preview_path), 8.0)
        if not ok2 or not preview_path.exists():
            raise HTTPException(500, f"Preview falló: {err[:300]}")
    return FileResponse(str(preview_path), media_type="audio/aac",
                        headers={"Cache-Control": "public, max-age=3600",
                                 "Access-Control-Allow-Origin": "*"})


# ──────────────────────────────────────────────────────────────────────
#  RUNWAY AI — Video-to-video regeneration por toma
# ──────────────────────────────────────────────────────────────────────

@app.get("/api/runway/presets")
async def runway_presets():
    """Lista de presets de estilo rápido para Runway.
    Devuelve el prompt CORTO en español (lo que se muestra al usuario).
    El prompt LARGO en inglés se mantiene server-side y se usa al llamar a Runway."""
    return {
        "presets": [
            {
                "key": k,
                "label": v["label"],
                "description": v.get("description", ""),
                "prompt": v.get("prompt_es") or v.get("prompt", ""),
            }
            for k, v in RUNWAY_PRESETS.items()
        ],
        "available": bool(os.environ.get("RUNWAY_API_KEY", "").strip()),
    }


# In-memory store of Runway tasks
RUNWAY_TASKS: dict[str, dict] = {}
RUNWAY_LOCK = threading.Lock()


def set_runway_task(task_id: str, **updates):
    with RUNWAY_LOCK:
        if task_id in RUNWAY_TASKS:
            RUNWAY_TASKS[task_id].update(updates)
            RUNWAY_TASKS[task_id]["updated"] = datetime.utcnow().isoformat()


@app.post("/api/runway/enhance-clip")
async def runway_enhance_clip(
    clip: UploadFile = File(...),
    prompt: str = Form(...),
    model: str = Form("gen3a_turbo"),
    duration: int = Form(5),
    target_duration: Optional[float] = Form(None),
    preset_key: Optional[str] = Form(None),
    preset_keys: Optional[str] = Form(None),  # CSV de múltiples presets
):
    """Inicia una tarea de regeneración con Runway.
    - preset_keys (CSV): si vienen varios presets, COMBINA sus prompt_core en uno.
    - preset_key (single): si solo viene uno y el prompt no fue editado, expande a prompt_full.
    - Si el usuario editó el prompt, se manda tal cual.
    """
    if not os.environ.get("RUNWAY_API_KEY", "").strip():
        raise HTTPException(503, "RUNWAY_API_KEY no configurada en el server")
    if not prompt.strip():
        raise HTTPException(400, "Prompt vacío")
    # Runway Gen-3 Turbo SOLO acepta 5 o 10 segundos
    if duration not in (5, 10):
        duration = 5 if duration <= 7 else 10

    # Parse multiple preset keys (CSV → list)
    keys_list = []
    if preset_keys:
        keys_list = [k.strip() for k in preset_keys.split(",") if k.strip() in RUNWAY_PRESETS]
    elif preset_key and preset_key in RUNWAY_PRESETS:
        keys_list = [preset_key]

    effective_prompt = prompt
    if keys_list:
        # Si hay 2+ presets activos: combinar sus prompt_core
        if len(keys_list) >= 2:
            combined = combine_preset_prompts(keys_list)
            if combined:
                effective_prompt = combined
        else:
            # Solo un preset: si el usuario no editó el prompt_es, expandir a prompt_full
            preset = RUNWAY_PRESETS[keys_list[0]]
            prompt_es = (preset.get("prompt_es") or "").strip()
            prompt_full = (preset.get("prompt_full") or preset.get("prompt") or "").strip()
            norm_user = " ".join(prompt.split())
            norm_preset_es = " ".join(prompt_es.split())
            if norm_user == norm_preset_es and prompt_full:
                effective_prompt = prompt_full

    task_id = uuid.uuid4().hex[:12]
    upload_dir = UPLOAD_DIR / f"runway_{task_id}"
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Save uploaded clip
    ext = Path(clip.filename or "").suffix or ".mp4"
    clip_path = upload_dir / f"input{ext}"
    with open(clip_path, "wb") as f:
        shutil.copyfileobj(clip.file, f)

    output_path = OUTPUT_DIR / f"runway_{task_id}.mp4"
    work_dir = WORK_DIR / f"runway_{task_id}"

    task = {
        "id": task_id,
        "status": "pending",
        "created": datetime.utcnow().isoformat(),
        "prompt": prompt,
        "effective_prompt": effective_prompt,  # lo que realmente se manda a Runway
        "preset_key": preset_key,
        "model": model,
        "duration": duration,
        "target_duration": target_duration,
        "input_path": str(clip_path),
        "output_path": str(output_path),
        "work_dir": str(work_dir),
        "cost_usd": estimate_cost_usd(duration, model),
        "error": None,
    }
    with RUNWAY_LOCK:
        RUNWAY_TASKS[task_id] = task

    threading.Thread(
        target=_runway_process,
        args=(task_id, str(clip_path), effective_prompt, str(output_path),
              str(work_dir), model, duration, target_duration),
        daemon=True,
    ).start()

    return {
        "task_id": task_id,
        "status": "pending",
        "cost_estimate_usd": task["cost_usd"],
        "expected_wait_seconds": 60 if model == "gen3a_turbo" else 120,
    }


def _runway_process(task_id, input_path, prompt, output_path,
                     work_dir, model, duration, target_duration=None):
    set_runway_task(task_id, status="processing")
    try:
        ok, err = enhance_clip_with_runway(
            input_video=input_path,
            prompt=prompt,
            output_video=output_path,
            work_dir=work_dir,
            model=model,
            duration=duration,
            target_duration=target_duration,
        )
        if ok:
            set_runway_task(task_id, status="done")
        else:
            set_runway_task(task_id, status="error", error=err)
    except Exception as e:
        set_runway_task(task_id, status="error", error=f"unexpected: {str(e)[:300]}")


@app.get("/api/runway/tasks/{task_id}")
async def runway_task_status(task_id: str):
    with RUNWAY_LOCK:
        task = RUNWAY_TASKS.get(task_id)
    if not task:
        raise HTTPException(404, "Runway task not found")
    return {
        "id": task["id"],
        "status": task["status"],
        "created": task["created"],
        "updated": task.get("updated"),
        "prompt": task["prompt"],
        "model": task["model"],
        "duration": task["duration"],
        "cost_usd": task["cost_usd"],
        "error": task.get("error"),
        "download_url": f"/api/runway/tasks/{task_id}/download" if task["status"] == "done" else None,
    }


@app.get("/api/runway/tasks/{task_id}/download")
async def runway_task_download(task_id: str):
    with RUNWAY_LOCK:
        task = RUNWAY_TASKS.get(task_id)
    if not task:
        raise HTTPException(404, "Runway task not found")
    if task["status"] != "done":
        raise HTTPException(409, f"Task not done (status={task['status']})")
    path = task["output_path"]
    if not Path(path).exists():
        raise HTTPException(500, "Output file missing")
    return FileResponse(path, media_type="video/mp4",
                        filename=f"runway_{task_id}.mp4")


@app.post("/api/jobs")
async def create_job(
    sections: str = Form(...),
    cta_data: str = Form(...),
    clips: list[UploadFile] = File(...),
    logo: Optional[UploadFile] = File(None),
    music: Optional[UploadFile] = File(None),
    music_preset: str = Form("cinematic_view"),
    voice_audio: Optional[UploadFile] = File(None),
    voice_key: Optional[str] = Form(None),
    generate_voice: bool = Form(False),
    enhance_ai: str = Form("false"),
    cinematic_filter: str = Form(""),
    auto_subtitles: str = Form("false"),
    voice_segments_json: str = Form(""),  # transcripción pre-corregida por usuario
):
    """
    Create a new editing job with section-based structure.

    Multipart form:
      - sections: JSON string. Array of {name, clips: [{file_index, trim_start, trim_duration, headline, subline, speed}]}
                  file_index refers to the index in the `clips` array (0-based)
      - cta_data: JSON string {info, precio, tagline}
      - clips: list of MP4 files (all videos for all sections, in order)
      - logo: optional PNG/JPG of corredor logo
      - music: optional MP3
      - voice_audio: optional MP3 voiceover
      - voice_key: optional ElevenLabs voice ID
      - generate_voice: bool, generate voice from cta_data via ElevenLabs
    """
    try:
        sections_data = json.loads(sections)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"Invalid sections JSON: {e}")
    try:
        cta = json.loads(cta_data)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"Invalid cta_data JSON: {e}")

    job_id = uuid.uuid4().hex[:12]
    job_upload = UPLOAD_DIR / job_id
    job_upload.mkdir(parents=True, exist_ok=True)

    # Save clips (preserve order — important for file_index lookup)
    clip_paths = []
    for i, c in enumerate(clips):
        ext = Path(c.filename or "").suffix or ".mp4"
        path = job_upload / f"clip_{i:03d}{ext}"
        with open(path, "wb") as f:
            shutil.copyfileobj(c.file, f)
        clip_paths.append(str(path))

    # Save logo (optional)
    logo_path = None
    if logo:
        ext = Path(logo.filename or "").suffix or ".png"
        logo_path = job_upload / f"logo{ext}"
        with open(logo_path, "wb") as f:
            shutil.copyfileobj(logo.file, f)
        logo_path = str(logo_path)

    # Save music (optional)
    music_path = None
    if music:
        ext = Path(music.filename or "").suffix or ".mp3"
        music_path = job_upload / f"music{ext}"
        with open(music_path, "wb") as f:
            shutil.copyfileobj(music.file, f)
        music_path = str(music_path)

    # Save voice audio (optional)
    voice_audio_path = None
    if voice_audio:
        ext = Path(voice_audio.filename or "").suffix or ".mp3"
        voice_audio_path = job_upload / f"voice{ext}"
        with open(voice_audio_path, "wb") as f:
            shutil.copyfileobj(voice_audio.file, f)
        voice_audio_path = str(voice_audio_path)

    # Resolve file_index → input_path in each section's clips
    resolved_sections = _resolve_sections(sections_data, clip_paths)
    if isinstance(resolved_sections, dict) and "error" in resolved_sections:
        raise HTTPException(400, resolved_sections["error"])

    output_path = OUTPUT_DIR / f"reel_{job_id}.mp4"
    work_dir = WORK_DIR / job_id

    enhance_flag = (enhance_ai or "").strip().lower() in ("true", "1", "yes", "on")
    auto_subs_flag = (auto_subtitles or "").strip().lower() in ("true", "1", "yes", "on")

    # Parsear voice_segments_json (transcripción pre-corregida por el user)
    pre_segments = None
    if voice_segments_json:
        try:
            pre_segments = json.loads(voice_segments_json)
            if not isinstance(pre_segments, list):
                pre_segments = None
        except Exception:
            pre_segments = None

    job = {
        "id": job_id,
        "status": "pending",
        "created": datetime.utcnow().isoformat(),
        "sections": resolved_sections,
        "cta_data": cta,
        "clip_paths": clip_paths,
        "logo_path": logo_path,
        "voice_key": voice_key,
        "voice_audio_path": voice_audio_path,
        "voice_pre_segments": pre_segments,
        "music_path": music_path,
        "music_preset": music_preset,
        "enhance_ai": enhance_flag,
        "cinematic_filter": cinematic_filter or "",
        "auto_subtitles": auto_subs_flag,
        "output_path": str(output_path),
        "work_dir": str(work_dir),
        "log": [],
        "error": None,
    }
    with JOBS_LOCK:
        JOBS[job_id] = job

    threading.Thread(
        target=process_job,
        args=(job_id, resolved_sections, cta, str(work_dir),
              voice_audio_path, music_path, music_preset, logo_path,
              enhance_flag, auto_subs_flag, str(output_path),
              voice_key, generate_voice, cinematic_filter or "",
              pre_segments),
        daemon=True,
    ).start()

    return {"job_id": job_id, "status": "pending"}


def _resolve_sections(sections_data, clip_paths):
    """Replace file_index in each clip with actual input_path."""
    resolved = []
    for section in sections_data:
        s = {"name": section.get("name", "custom"), "clips": []}
        for c in section.get("clips", []):
            idx = c.get("file_index")
            if idx is None or idx < 0 or idx >= len(clip_paths):
                return {"error": f"Invalid file_index {idx} in section {section.get('name')}"}
            s["clips"].append({
                "input_path": clip_paths[idx],
                "trim_start": c.get("trim_start", 0),
                "trim_duration": c.get("trim_duration", 3),
                "headline": c.get("headline", ""),
                "subline": c.get("subline", ""),
                "speed": c.get("speed", 1.0),
            })
        resolved.append(s)
    return resolved


def process_job(job_id, sections, cta_data, work_dir,
                voice_audio_path, music_path, music_preset, logo_path,
                enhance_ai, auto_subtitles, output_path,
                voice_key, generate_voice, cinematic_filter="",
                pre_segments=None):
    set_job(job_id, status="processing")

    # If user wants ElevenLabs voice generation
    if not voice_audio_path and generate_voice and voice_key:
        # Build minimal property dict for script generation
        script_data = {
            "comuna": cta_data.get("info", ""),
            "precio_uf": cta_data.get("precio", ""),
            "diferenciador": cta_data.get("tagline", ""),
        }
        script = build_voiceover_script(script_data)
        gen_path = Path(work_dir) / "voiceover.mp3"
        gen_path.parent.mkdir(parents=True, exist_ok=True)
        ok, err = generate_voiceover(script, voice_key, str(gen_path))
        if not ok:
            set_job(job_id, status="error", error=f"voiceover gen: {err}")
            return
        voice_audio_path = str(gen_path)
        set_job(job_id, voice_audio_path=voice_audio_path)

    result = build_reel(
        sections=sections,
        cta_data=cta_data,
        work_dir=work_dir,
        voice_audio_path=voice_audio_path,
        music_path=music_path,
        music_preset=music_preset,
        logo_path=logo_path,
        enhance_ai=enhance_ai,
        cinematic_filter=cinematic_filter,
        auto_subtitles=auto_subtitles,
        voice_pre_segments=pre_segments,
        output_path=output_path,
    )

    if result.get("success"):
        set_job(job_id, status="done", log=result.get("log", []),
                duration=result.get("duration"))
    else:
        set_job(job_id, status="error", error=result.get("error", "unknown"),
                log=result.get("log", []))


@app.post("/api/jobs/{job_id}/reprocess")
async def reprocess_job(
    job_id: str,
    sections: str = Form(...),
    cta_data: str = Form(...),
    music_preset: Optional[str] = Form(None),
    enhance_ai: Optional[str] = Form(None),
    cinematic_filter: Optional[str] = Form(None),
    auto_subtitles: Optional[str] = Form(None),
    voice_segments_json: Optional[str] = Form(None),
    voice_audio: Optional[UploadFile] = File(None),
    music: Optional[UploadFile] = File(None),
):
    """Re-process an existing job with new sections/cta_data (re-edit feature).
    Reuses the original clips, logo, music, voice. Only re-applies trim/text/CTA.
    Optionally change music_preset."""
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    try:
        sections_data = json.loads(sections)
        cta = json.loads(cta_data)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"Invalid JSON: {e}")

    resolved = _resolve_sections(sections_data, job["clip_paths"])
    if isinstance(resolved, dict) and "error" in resolved:
        raise HTTPException(400, resolved["error"])

    # New work dir for the reprocess (avoid stale intermediates)
    new_work = WORK_DIR / f"{job_id}_v{uuid.uuid4().hex[:4]}"
    new_output = OUTPUT_DIR / f"reel_{job_id}_{new_work.name.split('_v')[-1]}.mp4"

    effective_preset = music_preset or job.get("music_preset", "cinematic_view")
    effective_enhance = (
        (enhance_ai or "").strip().lower() in ("true", "1", "yes", "on")
        if enhance_ai is not None
        else bool(job.get("enhance_ai", False))
    )
    effective_subs = (
        (auto_subtitles or "").strip().lower() in ("true", "1", "yes", "on")
        if auto_subtitles is not None
        else bool(job.get("auto_subtitles", False))
    )

    # Si llega un voice_audio nuevo, guardarlo y reemplazar
    effective_voice_path = job.get("voice_audio_path")
    if voice_audio is not None:
        upload_dir = UPLOAD_DIR / job_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        ext = Path(voice_audio.filename or "").suffix or ".mp3"
        new_voice_path = upload_dir / f"voice_v{uuid.uuid4().hex[:4]}{ext}"
        with open(new_voice_path, "wb") as f:
            shutil.copyfileobj(voice_audio.file, f)
        effective_voice_path = str(new_voice_path)

    # Si llega música nueva, igual
    effective_music_path = job.get("music_path")
    if music is not None:
        upload_dir = UPLOAD_DIR / job_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        ext = Path(music.filename or "").suffix or ".mp3"
        new_music_path = upload_dir / f"music_v{uuid.uuid4().hex[:4]}{ext}"
        with open(new_music_path, "wb") as f:
            shutil.copyfileobj(music.file, f)
        effective_music_path = str(new_music_path)

    # Parsear voice_segments_json — transcripción editada por el usuario
    effective_pre_segments = job.get("voice_pre_segments")  # default: del job original
    if voice_segments_json:
        try:
            parsed = json.loads(voice_segments_json)
            if isinstance(parsed, list) and parsed:
                effective_pre_segments = parsed
        except Exception:
            pass

    effective_cinematic = (
        cinematic_filter if cinematic_filter is not None
        else job.get("cinematic_filter", "")
    )

    set_job(job_id, status="processing", sections=resolved, cta_data=cta,
            output_path=str(new_output), work_dir=str(new_work),
            music_preset=effective_preset, enhance_ai=effective_enhance,
            cinematic_filter=effective_cinematic,
            auto_subtitles=effective_subs,
            voice_audio_path=effective_voice_path,
            voice_pre_segments=effective_pre_segments,
            music_path=effective_music_path,
            log=[], error=None)

    threading.Thread(
        target=process_job,
        args=(job_id, resolved, cta, str(new_work),
              effective_voice_path, effective_music_path,
              effective_preset, job.get("logo_path"),
              effective_enhance, effective_subs,
              str(new_output), None, False,
              effective_cinematic or "",
              effective_pre_segments),
        daemon=True,
    ).start()

    return {"job_id": job_id, "status": "pending"}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    output_filename = None
    if job["status"] == "done":
        op = job.get("output_path", "")
        if op:
            output_filename = Path(op).name
    return {
        "id": job["id"],
        "status": job["status"],
        "created": job["created"],
        "updated": job.get("updated"),
        "log": job.get("log", []),
        "error": job.get("error"),
        "duration": job.get("duration"),
        "sections": job.get("sections"),
        "cta_data": job.get("cta_data"),
        "download_url": f"/api/jobs/{job_id}/download" if job["status"] == "done" else None,
        # URL persistente al archivo específico (para versionado / "volver al anterior")
        "output_filename": output_filename,
        "file_url": f"/api/files/{output_filename}" if output_filename else None,
    }


@app.get("/api/jobs/{job_id}/download")
async def download(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] != "done":
        raise HTTPException(409, f"Job not done (status={job['status']})")
    path = job["output_path"]
    if not Path(path).exists():
        raise HTTPException(500, "Output file missing")
    return FileResponse(path, media_type="video/mp4",
                        filename=f"greatdeal_reel_{job_id}.mp4")


@app.get("/api/files/{filename}")
async def download_file_by_name(filename: str):
    """Sirve un archivo MP4 por su nombre exacto. Usado para acceder a
    versiones anteriores de reels (cuando reprocess genera un archivo nuevo
    y el viejo sigue en disco). Validación: solo nombres simples (sin path)."""
    # Sanity check para prevenir path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "Invalid filename")
    if not filename.endswith(".mp4"):
        raise HTTPException(400, "Only .mp4 files allowed")
    path = OUTPUT_DIR / filename
    if not path.exists():
        raise HTTPException(404, f"File not found: {filename}")
    return FileResponse(str(path), media_type="video/mp4", filename=filename)


@app.get("/api/jobs/{job_id}/subtitles")
async def get_job_subtitles(job_id: str):
    """Devuelve los segments transcritos por Whisper para edición.
    Si el job no está en memoria (restart de Render), buscamos por path en disk."""
    import json as _json
    job = jobs.get(job_id)
    if job:
        work_dir = Path(job.get("work_dir", ""))
    else:
        # Fallback: buscar work_dir por convención
        work_dir = WORK_DIR / job_id
    segs_path = work_dir / "subs_segments.json"
    if not segs_path.exists():
        return {"segments": [], "available": False,
                "reason": "no-segments-file",
                "hint": "Regenerá el reel con voz para tener subs editables"}
    try:
        segments = _json.loads(segs_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(500, f"No pude leer subs: {e}")
    return {"segments": segments, "available": True}


@app.post("/api/jobs/{job_id}/subtitles")
async def reapply_job_subtitles(job_id: str, payload: dict = Body(...)):
    """Re-aplica subtítulos con el texto editado.
    payload: {"segments": [{"start": float, "end": float, "text": str}, ...]}
    Usa el video pre-subs guardado en work_dir y reescribe el output del job.
    """
    from subtitles import reapply_edited_subtitles
    job = jobs.get(job_id)
    segments = payload.get("segments") or []
    if not isinstance(segments, list) or not segments:
        raise HTTPException(400, "Falta lista de segments")

    if job:
        work_dir = Path(job.get("work_dir", ""))
        output_path = Path(job.get("output_path", ""))
    else:
        # Fallback por convención (mismo path que process_job)
        work_dir = WORK_DIR / job_id
        output_path = OUTPUT_DIR / f"reel_{job_id}.mp4"
    pre_subs = work_dir / "_pre_subs.mp4"
    if not pre_subs.exists():
        raise HTTPException(
            409,
            "El video pre-subs no está disponible (regenerá el reel primero)."
        )
    if not output_path:
        raise HTTPException(500, "Falta output_path en el job")

    ok, err = reapply_edited_subtitles(
        pre_subs_video=str(pre_subs),
        edited_segments=segments,
        work_dir=str(work_dir),
        output_path=str(output_path),
    )
    if not ok:
        raise HTTPException(500, f"Re-aplicar subs falló: {err[:300]}")

    return {
        "ok": True,
        "download_url": f"/api/jobs/{job_id}/download?v={uuid.uuid4().hex[:6]}",
    }


# ══════════════════════════════════════════════════════════════════════
# IA FEATURES — auto-caption, visión por toma, feedback de calidad
# ══════════════════════════════════════════════════════════════════════

@app.post("/api/generate-caption")
async def generate_caption_endpoint(payload: dict = Body(...)):
    """Genera un caption profesional para Instagram listo para publicar.
    Body: {property: {tipo, comuna, m2, dorms, banos, precio_uf, diferenciador}, description: str}
    """
    from ai_features import generate_instagram_caption
    prop = payload.get("property") or {}
    desc = (payload.get("description") or "").strip()
    if not prop:
        raise HTTPException(400, "Falta property data")
    ok, result = generate_instagram_caption(prop, desc)
    if not ok:
        raise HTTPException(500, f"Caption gen failed: {result[:300]}")
    return {"caption": result}


@app.post("/api/analyze-clip")
async def analyze_clip_endpoint(clip: UploadFile = File(...)):
    """Analiza un clip con GPT-4o Vision: categoriza espacio, sugiere
    título/subtítulo, evalúa calidad y detecta issues.
    Multipart con 'clip' (UploadFile).
    """
    from ai_features import analyze_clip
    task_id = uuid.uuid4().hex[:8]
    work_dir = WORK_DIR / f"analyze_{task_id}"
    work_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(clip.filename or "").suffix or ".mp4"
    clip_path = work_dir / f"input{ext}"
    with open(clip_path, "wb") as f:
        shutil.copyfileobj(clip.file, f)

    ok, result = analyze_clip(str(clip_path), str(work_dir))
    try:
        clip_path.unlink()
        (work_dir / "analyze_frame.jpg").unlink(missing_ok=True)
        work_dir.rmdir()
    except Exception:
        pass

    if not ok:
        raise HTTPException(500, f"Analysis failed: {result}")
    return result


@app.post("/api/analyze-quality")
async def analyze_quality_endpoint(payload: dict = Body(...)):
    """Toma una lista de análisis de clips (output de /api/analyze-clip)
    y genera reporte de calidad global del reel.
    Body: {analyses: [...], property: {...}}
    """
    from ai_features import generate_quality_report
    analyses = payload.get("analyses") or []
    prop = payload.get("property") or {}
    if not isinstance(analyses, list) or not analyses:
        raise HTTPException(400, "Falta lista de analyses")
    ok, report = generate_quality_report(analyses, prop)
    if not ok:
        raise HTTPException(500, f"Report failed: {report.get('error', 'unknown')}")
    return report


@app.post("/api/transcribe-audio")
async def transcribe_audio(audio: UploadFile = File(...)):
    """Transcribe un audio con Whisper y devuelve text + segments con timing.
    Se usa para que Vale revise/corrija la transcripción ANTES de quemarla
    en el video como subtítulos."""
    from subtitles import transcribe_with_whisper
    upload_dir = UPLOAD_DIR / "transcribes"
    upload_dir.mkdir(exist_ok=True)
    ext = Path(audio.filename or "").suffix or ".webm"
    tmp_path = upload_dir / f"desc_{uuid.uuid4().hex[:8]}{ext}"
    with open(tmp_path, "wb") as f:
        shutil.copyfileobj(audio.file, f)
    ok, result = transcribe_with_whisper(str(tmp_path), language="es")
    try:
        tmp_path.unlink()
    except Exception:
        pass
    if not ok:
        raise HTTPException(500, f"Transcribe failed: {result}")
    if not isinstance(result, dict):
        return {"text": "", "segments": []}
    raw_segments = result.get("segments") or []
    # Limpiar segments para serialización (solo lo que nos importa)
    segments = []
    for i, s in enumerate(raw_segments):
        segments.append({
            "id": i,
            "start": float(s.get("start", 0)),
            "end": float(s.get("end", 0)),
            "text": (s.get("text") or "").strip(),
        })
    return {
        "text": result.get("text", ""),
        "segments": segments,
    }


@app.post("/api/generate-voice")
async def generate_voice_standalone(
    script: str = Form(...),
    voice_key: str = Form(...),
):
    """Genera voz con ElevenLabs y devuelve el MP3 directamente.
    El frontend puede usar el blob como un archivo de voz para el reel."""
    if not script.strip():
        raise HTTPException(400, "Script vacío")
    voice_id = uuid.uuid4().hex[:12]
    out_path = OUTPUT_DIR / f"voice_{voice_id}.mp3"
    ok, err = generate_voiceover(script, voice_key, str(out_path))
    if not ok:
        raise HTTPException(500, f"Voice gen failed: {err[:300]}")
    if not out_path.exists():
        raise HTTPException(500, "Audio file not generated")
    return FileResponse(
        str(out_path),
        media_type="audio/mpeg",
        filename=f"voice_{voice_id}.mp3",
        headers={"X-Voice-Id": voice_id},
    )


@app.get("/api/script-preview")
async def script_preview(comuna: str = "", m2: str = "", dorms: str = "",
                          banos: str = "", precio_uf: str = "",
                          diferenciador: str = "", tipo: str = "casa"):
    data = {
        "tipo": tipo, "comuna": comuna, "m2": m2, "dorms": dorms,
        "banos": banos, "precio_uf": precio_uf, "diferenciador": diferenciador,
    }
    return {"script": build_voiceover_script(data)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
