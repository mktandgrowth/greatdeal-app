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

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from editor import build_reel, MUSIC_PRESETS
from voice import list_voices, generate_voiceover, build_voiceover_script

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


@app.post("/api/jobs")
async def create_job(
    sections: str = Form(...),
    cta_data: str = Form(...),
    clips: list[UploadFile] = File(...),
    logo: Optional[UploadFile] = File(None),
    music: Optional[UploadFile] = File(None),
    music_preset: str = Form("chill"),
    voice_audio: Optional[UploadFile] = File(None),
    voice_key: Optional[str] = Form(None),
    generate_voice: bool = Form(False),
    enhance_ai: str = Form("false"),
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
        "music_path": music_path,
        "music_preset": music_preset,
        "enhance_ai": enhance_flag,
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
              enhance_flag, str(output_path), voice_key, generate_voice),
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
                enhance_ai, output_path, voice_key, generate_voice):
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

    effective_preset = music_preset or job.get("music_preset", "chill")
    effective_enhance = (
        (enhance_ai or "").strip().lower() in ("true", "1", "yes", "on")
        if enhance_ai is not None
        else bool(job.get("enhance_ai", False))
    )

    set_job(job_id, status="processing", sections=resolved, cta_data=cta,
            output_path=str(new_output), work_dir=str(new_work),
            music_preset=effective_preset, enhance_ai=effective_enhance,
            log=[], error=None)

    threading.Thread(
        target=process_job,
        args=(job_id, resolved, cta, str(new_work),
              job.get("voice_audio_path"), job.get("music_path"),
              effective_preset, job.get("logo_path"),
              effective_enhance, str(new_output), None, False),
        daemon=True,
    ).start()

    return {"job_id": job_id, "status": "pending"}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
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
        "download_url": f"/api/jobs/{job_id}/download" if job["status"] == "done" else None,
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


@app.post("/api/generate-voice")
async def generate_voice_standalone(
    script: str = Form(...),
    voice_key: str = Form(...),
):
    """Genera voz con ElevenLabs y devuelve el MP3 directamente."""
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
