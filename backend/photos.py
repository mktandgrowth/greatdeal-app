"""
GreatDeal · Fotos → clips de video (modo "Tengo solo fotos")

Convierte cada foto en un clip MP4 corto con movimiento suave (Ken Burns)
para que entre al MISMO pipeline de reels que los videos (build_reel).

Composición (vertical 9:16):
  - Fondo: la misma foto escalada a cubrir el cuadro, difuminada y oscurecida.
  - Encima: la foto completa (sin recortar) centrada.
  - Movimiento: zoom lento de ~8% alternando dirección según el índice.

No usa IA generativa: el reel muestra exactamente lo que hay en las fotos.
"""
import subprocess
from pathlib import Path

try:
    from PIL import Image, ImageOps, ImageFilter, ImageEnhance
    PIL_OK = True
except Exception:  # pragma: no cover
    PIL_OK = False

# HEIC/HEIF (fotos de iPhone). Si pillow-heif no está, esas fotos fallan con
# un mensaje claro en vez de romper todo el job.
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIF_OK = True
except Exception:  # pragma: no cover
    HEIF_OK = False

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}

# Lienzo intermedio 1080x1920. El reel final sale en 540x960 (editor.W/H);
# hacer el zoom sobre un lienzo 2x más grande evita el "temblor" de zoompan.
CANVAS_W, CANVAS_H = 1080, 1920
OUT_W, OUT_H = 540, 960
FPS = 30
MAX_SIDE = 2160          # reducir fotos gigantes antes de procesar (RAM de Render)
ZOOM_AMOUNT = 0.08       # 8% de zoom a lo largo del clip


def is_image_file(path_or_name: str) -> bool:
    return Path(str(path_or_name)).suffix.lower() in IMAGE_EXTS


def _compose_canvas(src_path: str, out_jpg: str) -> tuple[bool, str]:
    """Arma el lienzo vertical (fondo difuminado + foto completa encima)."""
    if not PIL_OK:
        return False, "Pillow no está instalado en el servidor"
    try:
        img = Image.open(src_path)
        # JPEG: decodificar directo a menor tamaño (ahorra mucha RAM)
        try:
            img.draft("RGB", (MAX_SIDE, MAX_SIDE))
        except Exception:
            pass
        img = ImageOps.exif_transpose(img)  # fotos de celular vienen rotadas por EXIF
        img = img.convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    except Exception as e:
        ext = Path(src_path).suffix.lower()
        if ext in (".heic", ".heif") and not HEIF_OK:
            return False, "No se pueden leer fotos HEIC en el servidor. Convertilas a JPG e intentá de nuevo."
        return False, f"No se pudo leer la foto ({Path(src_path).name}): {e}"

    w, h = img.size
    if w < 50 or h < 50:
        return False, f"La foto {Path(src_path).name} es demasiado chica"

    # Fondo: cubrir el lienzo, blur fuerte, oscurecer
    cover = max(CANVAS_W / w, CANVAS_H / h)
    bg = img.resize((max(1, int(w * cover)), max(1, int(h * cover))), Image.BILINEAR)
    left = (bg.width - CANVAS_W) // 2
    top = (bg.height - CANVAS_H) // 2
    bg = bg.crop((left, top, left + CANVAS_W, top + CANVAS_H))
    bg = bg.resize((CANVAS_W // 8, CANVAS_H // 8), Image.BILINEAR)  # blur barato
    bg = bg.filter(ImageFilter.GaussianBlur(6))
    bg = bg.resize((CANVAS_W, CANVAS_H), Image.BILINEAR)
    bg = ImageEnhance.Brightness(bg).enhance(0.55)

    # Foto completa encima (encajada, sin recortar)
    fit = min(CANVAS_W / w, CANVAS_H / h)
    fg = img.resize((max(1, int(w * fit)), max(1, int(h * fit))), Image.LANCZOS)
    bg.paste(fg, ((CANVAS_W - fg.width) // 2, (CANVAS_H - fg.height) // 2))

    try:
        bg.save(out_jpg, "JPEG", quality=92)
    except Exception as e:
        return False, f"No se pudo preparar la foto: {e}"
    finally:
        img.close()
    return True, ""


def _motion_filter(index: int, frames: int) -> str:
    """Filtro zoompan: alterna 4 movimientos para que no se vean todas iguales."""
    z_in = f"1+{ZOOM_AMOUNT}*on/{frames}"
    z_out = f"{1 + ZOOM_AMOUNT}-{ZOOM_AMOUNT}*on/{frames}"
    center_x = "iw/2-(iw/zoom/2)"
    center_y = "ih/2-(ih/zoom/2)"
    mode = index % 4
    if mode == 0:      # acercar al centro
        z, x, y = z_in, center_x, center_y
    elif mode == 1:    # alejar desde el centro
        z, x, y = z_out, center_x, center_y
    elif mode == 2:    # paneo izquierda → derecha con zoom fijo
        z = f"{1 + ZOOM_AMOUNT}"
        x = f"(iw-iw/zoom)*on/{frames}"
        y = center_y
    else:              # paneo derecha → izquierda con zoom fijo
        z = f"{1 + ZOOM_AMOUNT}"
        x = f"(iw-iw/zoom)*(1-on/{frames})"
        y = center_y
    return (
        f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={OUT_W}x{OUT_H}:fps={FPS},"
        f"format=yuv420p"
    )


def photo_to_clip(src_path: str, out_mp4: str, duration: float = 3.5,
                  index: int = 0) -> tuple[bool, str]:
    """Convierte UNA foto en un clip MP4 vertical con movimiento suave."""
    duration = max(1.5, min(float(duration or 3.5), 8.0))
    canvas = str(Path(out_mp4).with_suffix(".canvas.jpg"))
    ok, err = _compose_canvas(src_path, canvas)
    if not ok:
        return False, err

    frames = int(round(duration * FPS))
    cmd = [
        "ffmpeg", "-y",
        "-i", canvas,
        "-vf", _motion_filter(index, frames),
        "-frames:v", str(frames),
        "-r", str(FPS),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-an",
        "-threads", "2",
        out_mp4,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=180)
    except Exception as e:
        return False, f"FFmpeg no respondió: {e}"
    finally:
        try:
            Path(canvas).unlink()
        except Exception:
            pass
    if proc.returncode != 0 or not Path(out_mp4).exists():
        tail = (proc.stderr or b"").decode(errors="ignore")[-400:]
        return False, f"FFmpeg falló convirtiendo la foto: {tail}"
    return True, ""


def convert_photos_in_place(clip_paths: list[str], durations: dict[int, float]) -> tuple[bool, str]:
    """Reemplaza en `clip_paths` cada foto por su clip MP4 (de a una, para cuidar RAM).

    durations: {file_index: segundos que necesita ese clip} (sale de las secciones).
    """
    photo_idx = 0
    for i, p in enumerate(clip_paths):
        if not is_image_file(p):
            continue
        out = str(Path(p).with_suffix("")) + "_photo.mp4"
        # Un poco más largo que el recorte pedido, para que el trim nunca quede corto
        dur = float(durations.get(i, 3.5)) + 0.3
        ok, err = photo_to_clip(p, out, duration=dur, index=photo_idx)
        if not ok:
            return False, f"Foto {i + 1}: {err}"
        clip_paths[i] = out
        photo_idx += 1
        try:
            Path(p).unlink()  # liberar disco
        except Exception:
            pass
    return True, ""
