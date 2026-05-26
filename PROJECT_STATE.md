# GreatDeal — Estado del proyecto

> **Para Claude**: este archivo es tu memoria persistente. Léelo al inicio de cada sesión antes de tocar código. Actualizalo cuando hagas cambios estructurales importantes.

---

## 1. Qué es GreatDeal

Plataforma C2C de real estate. El usuario (corredor o vendedor particular, **no técnico**) sube los videos cortos de una propiedad, completa datos básicos, y la app le devuelve un reel listo para Instagram/TikTok con texto sobre los clips, música, CTA con precio y opcionalmente voz/logo personalizado.

**Audiencia clave**: gente sin background técnico. La UX tiene que sentirse como WhatsApp/Instagram — todo se entiende sin instructivo, defaults inteligentes, complejidad escondida en "Opciones avanzadas".

---

## 2. URLs en producción

- **Frontend**: https://greatdeal-app-7b95.vercel.app/
- **Backend API**: https://greatdeal-api.onrender.com/
- **Repo GitHub**: https://github.com/mktandgrowth/greatdeal-app
- **Render dashboard**: https://dashboard.render.com/ → `greatdeal-api`
- **Vercel dashboard**: https://vercel.com/ → `greatdeal-app`

Deploy es **automático en push a `main`**: Render redeploya backend (~3-5 min) y Vercel redeploya frontend (~1 min).

---

## 3. Stack

| Componente | Tech | Hosting | Costo |
|---|---|---|---|
| Backend | FastAPI Python | Render **Standard** | $25/mes (always-on, 2 GB RAM, 1 CPU) — Starter NO sirve (solo 512 MB), upgradeamos a Standard porque FFmpeg necesita más |
| Frontend | HTML + Tailwind CDN + SortableJS | Vercel | Free |
| Video editing | FFmpeg + ffprobe | dentro de Render container | incluido |
| Voz IA | ElevenLabs API | externa | ~$22/mes plan Creator |
| Video IA | Runway Gen-3 Turbo | externa | pay-as-you-go (~$0.05/seg) |

---

## 4. Estructura local de archivos

**Carpeta de trabajo de Vale (la que Claude debe editar)**:
```
C:\Users\vales\OneDrive\Documents\Claude\GitHub\greatdeal-app\
├── backend/
│   ├── main.py          # FastAPI app + todos los endpoints
│   ├── editor.py        # Pipeline FFmpeg (normalize, trim, overlay, CTA, etc)
│   ├── voice.py         # ElevenLabs integration + voiceover scripts
│   ├── runway_ai.py     # Runway video-to-video por toma
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   └── index.html       # Single-page SPA con todo el wizard + editor avanzado
├── vercel.json
└── PROJECT_STATE.md     # ← este archivo
```

**OJO**: existe también `C:\Users\vales\OneDrive\Documents\GitHub\greatdeal-app\` (versión vieja, **no editar ahí**).

---

## 5. Variables de entorno en Render

Configurar en https://dashboard.render.com/ → `greatdeal-api` → Environment:

| Variable | Para qué | Estado |
|---|---|---|
| `ELEVENLABS_API_KEY` | Generación de voz IA | ✅ configurada |
| `RUNWAY_API_KEY` | Regenerar tomas con video-to-video | ✅ configurada ($10 cargados) |
| `OPENAI_API_KEY` | Whisper para subtítulos automáticos | ⏳ pendiente agregar |

---

## 6. Arquitectura del backend

### Pipeline FFmpeg (`editor.py`)
- **Resolución**: 540x960 vertical 9:16 (optimizado para 2GB Render, no 1080x1920)
- **fps**: 30
- **Codec**: H.264 preset `ultrafast` CRF 23 (cambia a `fast` CRF 21 con `enhance_ai`)
- **Texto**: Poppins Bold 32px (headline) + Poppins Reg 20px gris claro (subline), ambos **centrados horizontal**, posicionados en **tercio inferior** (zona safe IG/TikTok). Con gradient negro detrás.
- **CTA white-label**: fondo negro puro, info en blanco arriba, precio en rectángulo blanco con texto NEGRO, tagline en gris abajo. **Sin "GREATDEAL" hardcoded** (editable por reel).
- **Música**: 5 presets sintetizados (chill, cinematic, uplifting, melancholic, corporate) o MP3 propio
- **Audio mux**: si hay voz, música baja al 25% (mix simple, no sidechain por RAM)
- **Concat**: usa demuxer (`-f concat`) en vez de xfade para no consumir RAM

### Funciones clave en `editor.py`
- `normalize_clip(input, output, enhance=False)` — escala + corrige color. Con `enhance=True` aplica color cinematográfico (denoise + boost contraste/saturación + unsharp + viñeta)
- `trim_clip(input, output, start, duration)` — recorta segmento
- `speedup_clip(input, output, speed)` — aplica `setpts=PTS/speed` (entrada usa 3x = timelapse)
- `add_text_overlay(input, output, headline, subline, duration)` — texto + gradient. Skip si ambos vacíos.
- `build_logo_slide(logo, output, duration)` — fondo negro + logo PNG centrado con fade
- `build_cta_v2(output, info, precio, tagline, duration)` — CTA white-label
- `concat_clips(clips, output)` — demuxer concat
- `synth_music_preset(preset, output, duration)` — sintetiza pad ambient según preset
- `mux_audio(video, music, voice, output)` — mux final con ducking
- `build_reel(sections, cta_data, work_dir, ...)` — **orquestador principal**

### Endpoints en `main.py`
| Método | Endpoint | Función |
|---|---|---|
| GET | `/` | Sirve frontend HTML |
| GET | `/api/voices` | Lista voces ElevenLabs curadas |
| GET | `/api/music-presets` | Lista 5 presets de música |
| GET | `/api/runway/presets` | Lista presets de estilo Runway + flag `available` |
| POST | `/api/jobs` | Crear job (multipart con sections JSON + clips + audio + logo) |
| GET | `/api/jobs/{id}` | Estado del job (status, log, error, download_url) |
| GET | `/api/jobs/{id}/download` | MP4 final |
| POST | `/api/jobs/{id}/reprocess` | Re-procesar con nuevas sections/CTA sin re-uploadear |
| POST | `/api/generate-voice` | ElevenLabs standalone (devuelve MP3 directo) |
| POST | `/api/runway/enhance-clip` | Inicia Runway video-to-video por toma |
| GET | `/api/runway/tasks/{id}` | Estado de la task Runway |
| GET | `/api/runway/tasks/{id}/download` | MP4 regenerado |
| GET | `/api/script-preview` | Preview del script de voz autogenerado |

### Job store
**In-memory dict** (no DB). Los jobs se pierden al reiniciar Render. Para producción real eventualmente migrar a Postgres/Supabase.

---

## 7. Flujo frontend (4 pasos)

### Paso 1: Videos
- Toggle "🎬 Guiado por tomas" / "⚡ Subir existentes"
- Toggle "🎬 Color cinematográfico" (filtros FFmpeg pro, NO IA generativa)
- Banner explicativo de IA real (Runway en paso 4)
- Modo **guiado**: 6 secciones con tips educativos
  - Exterior (1 toma, 3.5s)
  - Entrada (1 toma 15s a **3x** = 5s)
  - Dormitorios (1-5 tomas, 2.5s c/u)
  - Baños (1-5 tomas, 2.5s c/u)
  - Áreas comunes (1-5 tomas, 2.5s c/u)
  - Vista (1 toma, 3s)
- Modo **simple**: drop zone + grid reordenable (SortableJS)
- En cada upload: botón "📤 Subir" + "📷 Grabar" (este usa `capture="environment"` para cámara móvil nativa, **no MediaRecorder**)

### Paso 2: Datos
- Form básico: tipo, comuna, m², dorms, baños, precio
- **Preview en vivo** del cierre (fondo negro + precio en rectángulo blanco)
- Banner que avisa que música/voz están en paso 3
- Acordeón "Opciones avanzadas" para logo PNG y CTA personalizado

### Paso 3: Audio
- Banner con duración estimada del reel + caracteres recomendados (14 chars/seg)
- Música: dropdown de 5 presets o subir MP3 propio
- Voz con 4 tabs:
  - 🚫 Sin voz
  - 📤 Subir audio
  - 🎤 **Grabar acá** (MediaRecorder API real)
  - 🤖 **Generar con IA** (ElevenLabs con calculadora de caracteres en vivo)

### Paso 4: Tu reel
- Procesando → Loader → reel listo
- Botón gigante "⬇ Descargar MP4"
- Botón "🎨 Editor avanzado" → abre modal con:
  - Lista de clips reordenables (drag handles)
  - Por clip: video preview + **dual-range slider visual** para trim (no segundos numéricos)
  - Slider de velocidad 0.5x-4x
  - Botón "▶️ Previa del segmento"
  - Inputs título/subtítulo
  - **Botón "✨ Rehacer con IA (Runway)"** por clip → modal con prompt + 5 presets de estilo
- Acordeón con botones rápidos para volver a pasos del wizard
- Botón "↻ Re-procesar" manual con confirmación

---

## 8. Trabajo con Vale (workflow)

- **Vale NO es developer**. Hablamos en español, casual, sin jerga técnica innecesaria.
- **Vale tiene GitHub Desktop** y hace commit+push manualmente. Claude escribe archivos directos en su filesystem.
- **Nunca pedir credenciales** (passwords, tokens completos). Las API keys las pega ella en Render directamente.
- Claude **NO puede modificar Render ni Vercel** por su cuenta — solo guía paso a paso.
- **Sandbox bash** a veces se cae. Si pasa, usar Edit/Write/Read directamente con paths Windows.

---

## 9. Features actuales (todas en producción)

- ✅ Wizard de 4 pasos
- ✅ Modo guiado por tomas con tips educativos
- ✅ Modo simple drag-and-drop con reorder
- ✅ Multi-upload + cámara nativa móvil (`capture="environment"`)
- ✅ 5 presets de música sintetizada + subir MP3 propio
- ✅ 4 opciones de voz (none/subir/grabar/ElevenLabs)
- ✅ Calculadora de caracteres según duración del reel
- ✅ Logo PNG opcional con slide propio antes del CTA
- ✅ CTA white-label con info/precio/tagline editables
- ✅ Color cinematográfico (filtros FFmpeg pro)
- ✅ Editor avanzado con timeline tipo CapCut
- ✅ Dual-range slider visual para trim (con preview del frame)
- ✅ Reorder de clips por drag-drop
- ✅ **Runway video-to-video por toma con prompt + presets**
- ✅ **Subtítulos automáticos con OpenAI Whisper API** (toggle en paso 3, solo visible con voz)
- ✅ Ducking de música cuando hay voz (25% mientras habla, 100% sin voz)
- ✅ Re-edición y re-procesar sin perder uploads
- ✅ Error handling con detalle del backend visible al usuario

---

## 10. Pendientes / TODOs

| Prioridad | Pendiente |
|---|---|
| 🔴 ALTA | **Bug móvil**: el reel no se crea cuando se incluye audio (voz). Reproducir con screenshot del error. |
| 🟡 MEDIA | Subtítulos automáticos con OpenAI Whisper API (requiere `OPENAI_API_KEY` en Render) |
| 🟡 MEDIA | Voz con auto-calce (atempo) para que dure exacto lo del reel |
| 🟢 BAJA | Curar 4-6 voces ElevenLabs específicas para real estate Chile |
| 🟢 BAJA | Migrar in-memory job store a DB (Supabase/Postgres) |
| 🟢 BAJA | Soporte de upscaling 1080x1920 (requiere más RAM de Render) |

---

## 11. Decisiones técnicas clave (rationale)

- **540x960 vs 1080x1920**: en Render Starter (2GB RAM) el upscale a FullHD vertical hace OOM con clips de 4+. Mantenemos 540x960 hasta que migremos a plan más alto.
- **Demuxer concat vs xfade**: xfade requiere cargar dos clips simultáneos en RAM. Demuxer es streaming → seguro en 2GB.
- **ultrafast preset por default**: pierde algo de nitidez pero procesa rápido. Con `enhance_ai` sube a `fast`.
- **`capture="environment"` vs MediaRecorder para grabar video**: el primero abre la cámara nativa del móvil (mejor calidad, mejor UX). MediaRecorder es para grabar **audio** en el paso de voz.
- **Sortable.js**: 12KB, drag-drop confiable en touch + desktop. Mejor que HTML5 drag nativo en móvil.
- **No DB**: in-memory está OK para MVP. Los jobs se pierden al reiniciar Render pero el deploy ocurre solo en pushes, raro.

---

## 12. Bugs conocidos y lecciones aprendidas

### Tooling
- **Write tool tiene límite de tamaño**: archivos >1000 líneas se truncan silenciosamente. Para reescribir HTML/JS grandes, usar `cat >> file << EOF` en bash con heredocs chunked.
- **OneDrive sync**: a veces el archivo en disco no refleja inmediatamente el último Write. Si algo se ve raro, releer con Read tool antes de asumir corrupción.
- **`__pycache__` bloqueado** desde el sandbox de bash: si necesitás testar editor.py modificado, copiarlo a `/tmp` antes de importar para evitar pyc stale.
- **AskUserQuestion** a veces falla con "permission stream closed". Si pasa, hacer preguntas en texto plano y proceder con defaults sensatos.
- **CRÍTICO al reparar archivos truncados**: si vas a usar `head -n -1 file > tmp && mv tmp file && cat >> file`, el `mv` puede fallar silenciosamente (permission denied desde sandbox a OneDrive paths) y el `cat >>` se ejecuta igual, dejando código DUPLICADO al final del archivo. Después puede compilar pero fallar en runtime con IndentationError raro. **Siempre validar después con `grep -n "@app\\.\\|^if __name__" file`** para ver duplicados antes de pushear.
- **NUNCA pinear versiones de packages externos** sin verificar primero. `runwayml==3.6.0` rompió el deploy porque esa versión no existe en PyPI. Mejor usar la API REST directa con `requests` cuando es factible.

### FFmpeg
- **Escape de caracteres especiales** en drawtext: `'` → `\'`, `:` → `\:`, `%` → `\%`, `\` → `\\`. Está en `_esc()` helper.
- **Concat demuxer** requiere que todos los clips tengan **mismo codec/res/fps**. Por eso normalize ANTES de concat.

### Móvil
- **iOS Safari MediaRecorder** soporta solo `audio/mp4` (no webm). El código tiene fallback.
- **El archivo de voz grabado puede ser pesado** y romper uploads en redes móviles lentas.

---

## 13. Costos operativos estimados

| Item | Costo | Notas |
|---|---|---|
| Render Starter | $7/mes | Always-on, sin cold starts |
| ElevenLabs Creator | $22/mes | 100k chars/mes incluidos |
| Runway créditos | pay-as-you-go | ~$0.05/seg Gen-3 Turbo. 100 tomas de 3s = ~$15 |
| Vercel | $0 | Free tier alcanza |
| Cloudflare R2 (futuro) | $0 | Hasta 10GB gratis para outputs persistentes |
| **TOTAL estimado** | **~$30-50/mes** | Sin contar Runway por reel |

---

## 14. Cómo retomar el proyecto (checklist al inicio de sesión)

1. **Leer este archivo completo** primero
2. Chequear que los 3 archivos críticos no estén truncados:
   - `backend/main.py` (~400 líneas)
   - `backend/editor.py` (~350 líneas)
   - `frontend/index.html` (~1100 líneas)
3. Verificar git status en GitHub Desktop antes de empezar (pueden haber cambios sin pushear)
4. Si Vale reporta un bug, **pedirle screenshot del error** que aparece en pantalla (la app ahora muestra el detalle del backend)
5. Si va a tocar el frontend grande: hacer Edits incrementales, **nunca Write completo** del index.html
6. Al terminar, recordarle a Vale los pasos de deploy:
   1. GitHub Desktop → Review changes
   2. Commit con mensaje claro
   3. Push origin
   4. Esperar Render (3-5 min) y Vercel (~1 min)
   5. Ctrl+Shift+R en el navegador para limpiar caché

---

## 15. Sesión 2026-05-26 — Runway + Whisper + bug Render reiniciándose

### Lo que se logró hoy

- ✅ **Runway video-to-video integrado**: módulo `runway_ai.py` con `requests` (no SDK), endpoint `/api/runway/enhance-clip`, modal en editor avanzado con 5 presets de estilo. RUNWAY_API_KEY configurada en Render con $10 de saldo.
- ✅ **OpenAI Whisper subtítulos automáticos**: módulo `subtitles.py`, transcripción + ASS file + burn-in con FFmpeg. Toggle 🔤 que aparece cuando hay voz. OPENAI_API_KEY cargada en Render con saldo.
- ✅ **Voz movida a post-render** (paso 4): textarea con contador dinámico de caracteres basado en duración REAL del reel, 4 opciones (sin voz / subir / grabar / Eleven). Botón "Aplicar voz al reel".
- ✅ **Backend reprocess acepta voice_audio + music nuevos**: para que aplicar voz post-render reuse los videos ya subidos.
- ✅ **Texto centrado verticalmente**: en `add_text_overlay`, el título/subtítulo ahora aparece en el centro vertical para dejar espacio abajo a los subtítulos automáticos.
- ✅ **Fixes UX importantes**:
  - Bug textarea que no dejaba escribir prompts/guiones (era por `render()` destructivo en oninput) → fix con `updateCharCounter()` y `updateRunwayPromptCounter()` que solo actualizan el span sin re-renderear
  - Tab "Generar con IA" se oculta si ElevenLabs no está configurada
  - Polling resiliente: `visibilitychange` listener reanuda polling cuando volvés a la app después de bloquear cel
  - Detector de 404 silencioso: si Render reinicia y el job se pierde, después de 3 intentos avisa "El servidor se reinició, volvé a procesar"
- ✅ **CSS móvil mejorado**: thumbs del dual-range de 22px → 32px (touch target adecuado), `touch-action: pan-x`, `-webkit-overflow-scrolling: touch`
- ✅ **Fix CRÍTICO del deploy**: archivo `main.py` tenía endpoints duplicados (líneas 573-628) residuo de reparación de truncado de sesiones anteriores. Causaba `IndentationError` y `==> Exited with status 1` en Render. Borrados los duplicados.
- ✅ **Reemplazo de `runwayml==3.6.0`** por `requests` directo a la REST API de Runway (el package del SDK no existía con esa versión y rompía `pip install`).

### 🔴 BUG ACTIVO al cierre de la sesión (pendiente de mañana)

**Síntoma**: Render reinicia solo cada ~2 minutos, exactamente cuando arranca FFmpeg en cualquier job. Los reels nunca se completan.

**Patrón en logs**:
```
[ffmpeg] normalize clip_000.mp4...
POST /api/jobs 200 OK
==> Instance srv-... restarted    ← Render mata el proceso
```

**Causa probable**: el cambio que hice al `add_text_overlay` agregando `borderw=3:bordercolor=black@0.85` consumía demasiada CPU. FFmpeg con border renderiza el texto múltiples veces (~8x para un border de 3px). En Render Starter (0.5 vCPU) eso saturaba el CPU y disparaba reinicio.

**Fix aplicado pero NO PUSHEADO al cierre**: quité el `borderw`, lo reemplacé por un drawbox semi-transparente sutil detrás del texto (mucho más liviano) + sombra fuerte. El cambio está en `backend/editor.py` en disco de Vale pero NO en producción.

### Primer paso mañana

1. Vale hace **commit + push** de los cambios pendientes en GitHub Desktop. El archivo crítico es `backend/editor.py` (el fix sin borderw). Probablemente también haya cambios en `frontend/index.html` y `PROJECT_STATE.md`.
2. Esperar Render ~3 min hasta "Live"
3. Probar reel simple (sin features) en PC primero → si funciona, está resuelto
4. Si SIGUE fallando, ir a Render → Logs → buscar líneas justo antes del `==> Instance restarted` para identificar la causa real (OOM, segfault, timeout)

### Tareas pendientes priorizadas (post-fix)

🔴 **ALTA**
- Validar que el fix del borderw arregla los restarts (push pendiente)
- Persistencia de jobs (jobs viven en memoria → se pierden con cada restart de Render). Opción más simple: persistent disk en Render ($1/mes/GB) + JSON file. Opción profesional: Supabase DB.

🟡 **MEDIA**
- Bug móvil del editor avanzado (#60) — probar después del fix actual
- Sistema de Proyectos (#61) — Vale quiere guardar reels para seguir trabajando otro día
- Voz con auto-calce (atempo) cuando dura más/menos que el video

🟢 **BAJA**
- Curar voces ElevenLabs (Vale aún no configuró ELEVENLABS_API_KEY — opcional)

### Cosas aprendidas hoy

- **Nunca pinear versiones de packages externos sin verificar PyPI**. `runwayml==3.6.0` no existía y rompió el deploy. Si una integración tiene API REST simple, mejor usar `requests` directo.
- **Cuidado con `borderw` en FFmpeg drawtext**: visualmente queda lindo pero multiplica el costo CPU por ~8x. En servers con 0.5 vCPU, puede causar timeouts/restarts.
- **Runway tiene DOS plataformas separadas**: `app.runwayml.com` (editor visual) y `dev.runwayml.com` (developer API). Las API keys NO son intercambiables. La de developer empieza con `key_...`. Los créditos también son separados.
- **`render()` destructivo en `oninput` de textareas en JS plano**: si el oninput dispara render completo, la textarea se destruye y se pierde el focus en cada tecla. Fix: actualizar solo el span del contador con DOM manipulation, no llamar render.
- **JavaScript se pausa en mobile cuando bloqueás la pantalla**. Polling se corta. Solución: `visibilitychange` listener que reanuda cuando volvés.

### Estado del repo al cierre

Archivos modificados pendientes de push (en `C:\Users\vales\OneDrive\Documents\Claude\GitHub\greatdeal-app\`):
- `backend/editor.py` (fix sin borderw)
- `backend/main.py` (reprocess con voice/music + endpoints Runway + Whisper integration)
- `backend/subtitles.py` (nuevo - Whisper)
- `backend/runway_ai.py` (rewritten con requests)
- `backend/requirements.txt` (sin runwayml)
- `frontend/index.html` (texto centrado + polling resiliente + 404 detector + dual-range móvil + Runway modal + voz post-render + textarea fix + visibilitychange)
- `PROJECT_STATE.md` (este archivo)

---

## 16. Sesión 2 — 2026-05-27 — Fixes producción + Runway optimizado + estilo final

### Lo que se logró hoy

- ✅ **Identificamos el bug del Render reiniciándose**: era OOM porque el plan "Starter" de Render es solo **512 MB de RAM** (yo había dicho mal que era 2 GB). FFmpeg + Python necesita más.
- ✅ **Upgrade a Render Standard ($25/mes, 2 GB RAM, 1 CPU)** — único cambio que resolvió de raíz los crashes.
- ✅ **Fix Runway duration**: Gen-3 Turbo solo acepta `duration=5` o `duration=10`. Estábamos mandando valores dinámicos (3, 4, 7) que daban HTTP 400.
- ✅ **Runway optimizado para costo**: siempre genera 5 seg ($0.25 fijo, el mínimo). Si el clip dura menos (ej. 3 seg), backend recorta el output Runway a 3 seg con FFmpeg `-t`. Costo mantenido, duración real respetada.
- ✅ **Subtítulos estilo TikTok palabra por palabra**: Whisper con `timestamp_granularities=word`. Cada palabra aparece sincronizada con fade rápido de 80ms.
- ✅ **CTA elegante**: rectángulo del precio más pequeño (320x80 en vez de 420x120), opacidad blanca 92%, fontsize 36 (era 48). Tagline "Vivir distinto" eliminado como default — si está vacío, no aparece.
- ✅ **Safe zone Instagram**: subtítulos movidos a MarginV 260 (texto base en y≈700, dentro de zona segura). MarginL/R aumentados a 100 para evitar barra derecha de IG.
- ✅ **Texto centrado verticalmente** en clips (Vale lo pidió hace varias iteraciones).
- ✅ **Cambio de tipografía a Montserrat** (en lugar de Poppins):
  - **SemiBold** → títulos clip (38px) y precio CTA
  - **Regular** → subtítulos clip (24px), info CTA, tagline
  - **Thin** → subtítulos hablados Whisper (44px, estilo elegante)
  - Todo blanco con sombra negra fuerte (no más borde)
- ✅ **Fix bug textarea Runway prompt** que no dejaba escribir (era el mismo bug del render destructivo, resuelto con `updateRunwayPromptCounter()`).
- ✅ **Endpoint HEAD /** para que Render health checks no devuelvan 405.
- ✅ **subprocess sin capture_output**: stdout=DEVNULL (anti-OOM por pre-alloc de buffers).
- ✅ **Detector de jobs perdidos**: si el server reinicia y el job_id devuelve 404, después de 3 intentos avisa al usuario.
- ✅ **Polling resiliente móvil**: `visibilitychange` listener reanuda polling cuando volvés a la app.

### Tipografías finales en producción

| Elemento | Fuente | Tamaño | Color |
|---|---|---|---|
| Título clip | Montserrat SemiBold | 38px | Blanco + sombra negra (3px, 95% opaca) |
| Subtítulo clip | Montserrat Regular | 24px | Blanco + sombra negra (2px, 90%) |
| Subtítulos hablados Whisper | Montserrat Thin | 44px | Blanco + sombra fuerte (4px, 50%) |
| CTA info | Montserrat Regular | 28px | Blanco |
| CTA precio | Montserrat SemiBold | 36px | Negro sobre rectángulo blanco 92% |
| CTA tagline | Montserrat Regular | 26px | Gris claro (#cbd5e1) — opcional |

### Costos operativos actualizados

| Item | Costo | Notas |
|---|---|---|
| Render **Standard** | **$25/mes** | 2 GB RAM, 1 CPU, always-on (subimos de Starter $7 que era 512 MB insuficiente) |
| Vercel Hobby | $0 | Frontend estático |
| OpenAI Whisper | ~$0.003/reel con voz | Cobra solo si activan subtítulos automáticos |
| Runway Gen-3 Turbo | **$0.25 por toma regenerada** (fijo) | Siempre 5 seg, recortamos al largo real |
| ElevenLabs | (opcional, no configurado) | Vale aún no agregó ELEVENLABS_API_KEY |
| **Total fijo mensual** | **$25/mes** | Más uso variable |

### 🟡 PENDIENTE de PUSH al cierre de la sesión

Vale tiene muchos cambios acumulados en disco que NO están en producción. Mañana lo PRIMERO es hacer el push:

**Archivos modificados pendientes** (en `C:\Users\vales\OneDrive\Documents\Claude\GitHub\greatdeal-app\`):
- `backend/Dockerfile` (Montserrat en lugar de Poppins)
- `backend/editor.py` (Montserrat fonts, sombras fuertes, sin gradient, CTA rectángulo compacto con opacidad)
- `backend/main.py` (target_duration en endpoints Runway, HEAD endpoints)
- `backend/runway_ai.py` (target_duration param, normalize con -t)
- `backend/subtitles.py` (Montserrat Thin, word-level timestamps, safe zone IG)
- `frontend/index.html` (Runway dur=5 fijo + targetDur, fix textarea Runway, tagline vacío, preview CTA actualizado)
- `PROJECT_STATE.md` (este archivo)

**Commit recomendado**: `feat: Montserrat + Runway 5s recorte + subtítulos TikTok + CTA elegante + safe zone IG`

### Primer paso de mañana

1. Vale hace **push** de todo lo acumulado
2. Esperar Render ~5-7 min (rebuild Docker con Montserrat tarda más)
3. Validar en `https://greatdeal-api.onrender.com/api/music-presets` que esté Live
4. Generar reel completo con voz + subtítulos para validar todo lo nuevo:
   - Tipografía Montserrat
   - Subtítulos palabra por palabra elegante (Thin)
   - CTA compacto con opacidad
   - Todo dentro de safe zone IG
5. Mandar screenshot del resultado para validar visualmente

### Tareas pendientes priorizadas

🔴 **ALTA**
- Push pendiente y validar end-to-end
- Persistencia de jobs (#61) — jobs en memoria se pierden con cada restart de Render. Solución más simple: persistent disk en Render ($1/mes/GB) + JSON file. Profesional: Supabase DB.

🟡 **MEDIA**
- Sistema de Proyectos (#61) — guardar reels para retomar otro día
- Bug móvil editor avanzado (#60) — re-validar después de los CSS fixes
- Bug móvil audio reel (#56) — re-validar

🟢 **BAJA**
- ElevenLabs (#24) — opcional, Vale no lo configuró
- Subtítulos karaoke estilo más avanzado (highlight palabra por palabra dentro de la frase)

### Cosas aprendidas hoy

- **Render Starter es 512 MB, NO 2 GB**. El plan con 2 GB es **Standard ($25/mes)**. Yo confundí esto durante varias sesiones — disculpas. Cualquier app que use FFmpeg + Python necesita Standard mínimo.
- **Runway Gen-3 Turbo SOLO acepta duration=5 o 10**. No valores arbitrarios. Si necesitás otra duración, generás el mínimo y recortás con FFmpeg `-t` después.
- **El plan workspace de Render (Hobby/Pro/Scale) y el Instance Type del servicio (Free/Starter/Standard/Pro) son cosas DIFERENTES**. Workspace controla features org-level (SSO, audit logs); Instance Type controla la RAM/CPU del servicio.
- **Whisper API soporta `timestamp_granularities[]`** — clave para subtítulos palabra-por-palabra estilo TikTok. Hay que mandar el parámetro 2 veces si querés ambos (word + segment).
- **Subprocess con `capture_output=True` puede causar OOM** en containers con poca RAM porque Python pre-aloca buffers para stdout/stderr. Si no necesitás stdout, mandar `stdout=DEVNULL`.
- **Safe zone Instagram en reels verticales**: y entre 144 y 720 (de 960 total). Lateral: 60-440 (deja 100px a la derecha para botones IG). Cualquier texto fuera de esto se tapa.
- **ASS subtitle MarginV** = distancia desde el bottom, no desde el top.

---

*Última actualización: 2026-05-27 fin de día — todo listo, falta push y validar mañana*
