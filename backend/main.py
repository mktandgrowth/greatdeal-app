"""
GreatDeal · Backend FastAPI
Endpoints:
  GET  /                          → sirve el frontend HTML
  GET  /api/voices                → lista de voces curadas
  POST /api/jobs                  → crea un job de edición (upload de clips + datos propiedad)
  GET  /api/jobs/{job_id}         → estado de un job
  GET  /api/jobs/{job_id}/download → descarga el MP4 final
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

from editor import build_reel
from voice import list_voices, generate_voiceover, build_voiceover_script

# Paths
ROOT = Path(__file__).parent.parent
UPLOAD_DIR = ROOT / "uploads"
OUTPUT_DIR = ROOT / "outputs"
FRONTEND_DIR = ROOT / "frontend"
WORK_DIR = ROOT / "work"

for p in [UPLOAD_DIR, OUTPUT_DIR, WORK_DIR]:
    p.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="GreatDeal Editor API", version="0.1")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# In-memory job store (v0.1)
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


def set_job(job_id: str, **updates):
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(updates)
            JOBS[job_id]["updated"] = datetime.utcnow().isoformat()


@app.get("/")
async def root():
    """Serve the frontend HTML."""
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return JSONResponse({"error": "frontend/index.html not found"}, status_code=404)


@app.get("/api/voices")
async def voices():
    """Return curated voice list."""
    return {"voices": list_voices()}


@app.post("/api/jobs")
async def create_job(
    property_data: str = Form(...),
    clips: list[UploadFile] = File(...),
    music: Optional[UploadFile] = File(None),
    voice_audio: Optional[UploadFile] = File(None),
    voice_key: Optional[str] = Form(None),
    generate_voice: bool = Form(False),
):
    """
    Create a new editing job.

    Multipart form:
      - property_data: JSON string with property info + clips_meta (headlines, trim ranges)
      - clips: list of MP4 files
      - music: optional MP3 (else synth ambient)
      - voice_audio: optional MP3 voiceover from user
      - voice_key: optional voice ID to generate with ElevenLabs
      - generate_voice: bool, if true generate voiceover from property_data via ElevenLabs
    """
    try:
        data = json.loads(property_data)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"Invalid property_data JSON: {e}")

    job_id = uuid.uuid4().hex[:12]
    job_upload = UPLOAD_DIR / job_id
    job_upload.mkdir(parents=True, exist_ok=True)

    # Save clips
    clip_paths = []
    for i, c in enumerate(clips, start=1):
        ext = Path(c.filename).suffix or ".mp4"
        path = job_upload / f"clip_{i}{ext}"
        with open(path, "wb") as f:
            shutil.copyfileobj(c.file, f)
        clip_paths.append(str(path))

    # Save uploaded music
    music_path = None
    if music:
        ext = Path(music.filename).suffix or ".mp3"
        music_path = job_upload / f"music{ext}"
        with open(music_path, "wb") as f:
            shutil.copyfileobj(music.file, f)
        music_path = str(music_path)

    # Save uploaded voice audio
    voice_audio_path = None
    if voice_audio:
        ext = Path(voice_audio.filename).suffix or ".mp3"
        voice_audio_path = job_upload / f"voice{ext}"
        with open(voice_audio_path, "wb") as f:
            shutil.copyfileobj(voice_audio.file, f)
        voice_audio_path = str(voice_audio_path)

    # Build clips_meta — either provided in property_data or auto-default
    clips_meta = data.get("clips_meta")
    if not clips_meta:
        # Sensible defaults: 4s each, no headlines
        clips_meta = [
            {"trim_start": 0, "trim_duration": min(4, 5), "headline": "", "subline": ""}
            for _ in clip_paths
        ]
    # Attach input_path to each meta
    for meta, path in zip(clips_meta, clip_paths):
        meta["input_path"] = path

    output_path = OUTPUT_DIR / f"reel_{job_id}.mp4"
    work_dir = WORK_DIR / job_id

    job = {
        "id": job_id,
        "status": "pending",
        "created": datetime.utcnow().isoformat(),
        "property": data,
        "clips_meta": clips_meta,
        "voice_key": voice_key,
        "voice_audio_path": voice_audio_path,
        "music_path": music_path,
        "output_path": str(output_path),
        "log": [],
        "error": None,
    }
    with JOBS_LOCK:
        JOBS[job_id] = job

    # Run processing in background thread
    threading.Thread(
        target=process_job,
        args=(job_id, clips_meta, data, str(work_dir),
              voice_audio_path, music_path, str(output_path),
              voice_key, generate_voice),
        daemon=True,
    ).start()

    return {"job_id": job_id, "status": "pending"}


def process_job(job_id, clips_meta, property_data, work_dir,
                voice_audio_path, music_path, output_path,
                voice_key, generate_voice):
    """Background processing pipeline."""
    set_job(job_id, status="processing")

    # Step 0: if no voice audio uploaded but user wants voice → generate with ElevenLabs
    if not voice_audio_path and generate_voice and voice_key:
        script = build_voiceover_script(property_data)
        gen_path = Path(work_dir) / "voiceover.mp3"
        gen_path.parent.mkdir(parents=True, exist_ok=True)
        ok, err = generate_voiceover(script, voice_key, str(gen_path))
        if not ok:
            set_job(job_id, status="error", error=f"voiceover gen: {err}")
            return
        voice_audio_path = str(gen_path)
        set_job(job_id, voice_audio_path=voice_audio_path)

    # Step 1: build reel
    result = build_reel(
        clips=clips_meta,
        property_data=property_data,
        work_dir=work_dir,
        voice_audio_path=voice_audio_path,
        music_path=music_path,
        output_path=output_path,
    )

    if result.get("success"):
        set_job(job_id, status="done", log=result.get("log", []), duration=result.get("duration"))
    else:
        set_job(job_id, status="error", error=result.get("error", "unknown"),
                log=result.get("log", []))


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    # Return a safe subset (no internal paths)
    return {
        "id": job["id"],
        "status": job["status"],
        "created": job["created"],
        "updated": job.get("updated"),
        "log": job.get("log", []),
        "error": job.get("error"),
        "duration": job.get("duration"),
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
    return FileResponse(path, media_type="video/mp4", filename=f"greatdeal_reel_{job_id}.mp4")


@app.get("/api/script-preview")
async def script_preview(comuna: str = "", m2: str = "", dorms: str = "",
                          banos: str = "", precio_uf: str = "", diferenciador: str = "",
                          tipo: str = "casa"):
    """Preview the auto-generated voiceover script for given property data."""
    data = {
        "tipo": tipo, "comuna": comuna, "m2": m2, "dorms": dorms,
        "banos": banos, "precio_uf": precio_uf, "diferenciador": diferenciador,
    }
    return {"script": build_voiceover_script(data)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
