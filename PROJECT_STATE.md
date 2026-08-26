# GreatDeal / C2C Publicar — Estado del proyecto

> **Para Claude (y para gstack)**: este archivo es la memoria persistente del repo. Leelo al inicio de cada sesión antes de tocar código y actualizalo cuando cambie algo estructural. Las secciones 1–14 describen el estado **actual** (agosto 2026). Las secciones 15–17 son bitácoras históricas de mayo 2026: sirven como contexto, pero **todo lo marcado ahí como "pendiente" o "bug activo" ya está resuelto o superado**.

Última actualización: 2026-08-26 (Oscar + Claude).

---

## 1. Qué es

Plataforma C2C de real estate en Chile. El vendedor (corredor o particular, **no técnico**) entra a **vender.c2cprops.com**, carga los datos de la propiedad, sube o arma un reel vertical, le pone precio y contacto, y la propiedad queda **publicada en el marketplace C2C** (c2cprops.com). El mismo backend sigue ofreciendo el editor de reels con IA (clips por sección, música, voz, Runway, subtítulos).

**Audiencia clave**: gente sin background técnico, mayormente desde el teléfono. La UX tiene que sentirse como WhatsApp/Instagram: defaults inteligentes, complejidad escondida en "Opciones avanzadas".

---

## 2. URLs y cuentas

| Qué | Dónde |
|---|---|
| Frontend (prod) | https://vender.c2cprops.com (Vercel, deploy automático en push a `main`, ~1 min) |
| Backend API (prod) | https://greatdeal-api.onrender.com (Render, deploy automático en push a `main`, ~3–5 min). `GET /health` → `{"status":"ok"}` |
| Repo | https://github.com/mktandgrowth/greatdeal-app (público) |
| Marketplace / tasador | https://c2cprops.com · https://tasar.c2cprops.com (API de catastro `POST /api/predio`) |
| Base de datos | Supabase: tabla `properties` (publicaciones), bucket `reels` (respaldo) |
| Storage de reels | Cloudflare R2 (bucket `reels`, egress gratis) desde PR #18; Supabase Storage como respaldo |

**OJO con los accesos (26-ago-2026)**: la cuenta de Render que aloja `greatdeal-api` y la cuenta de Vercel que administra el dominio `c2cprops.com` (DNS en `ns1/ns2.vercel-dns.com`) **no son las de Oscar**. Para tocar env vars o DNS hace falta que el administrador (Vale / mktandgrowth) invite a Oscar como miembro en ambos.

---

## 3. Stack

| Componente | Tech | Hosting |
|---|---|---|
| Backend | FastAPI (Python 3.12) en Docker, FFmpeg + ffprobe dentro del container | Render (`render.yaml`, `rootDir: backend`). El plan está definido en el dashboard, no en el YAML. Si está en free, duerme tras ~15 min: el frontend lo despierta con `despertarBackend()` |
| Frontend | `frontend/index.html`, SPA única: HTML + Tailwind CDN + SortableJS + JS vanilla | Vercel (`vercel.json` sirve `frontend/` estático) |
| Datos | Supabase (`properties`, Storage) + Cloudflare R2 | externos |
| IA | ElevenLabs (voz), Runway Gen-3 Turbo (video-to-video), OpenAI (Whisper subtítulos, moderación de frames, captions) | externas |
| Verificación de contacto | Twilio Verify (WhatsApp/SMS) + Resend (mail) — ver §5 y §10 | externas |

---

## 4. Estructura del repo

```
greatdeal-app/
├── backend/
│   ├── main.py          # FastAPI: publicación, storage, OTP, moderación, jobs de reel (~2100 líneas)
│   ├── editor.py        # Pipeline FFmpeg (normalize, trim, overlay, CTA, concat, mux; escalera de calidad 1080p→540p)
│   ├── ai_features.py   # Captions, análisis de clips/calidad (OpenAI)
│   ├── subtitles.py     # Whisper + quemado de subtítulos
│   ├── voice.py         # ElevenLabs
│   ├── runway_ai.py     # Runway video-to-video por toma (REST con requests, sin SDK)
│   ├── music/           # Presets de música
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   └── index.html       # SPA completa (~5300 líneas, CRLF — ver §12)
├── render.yaml
├── vercel.json
├── DEPLOY.md
└── PROJECT_STATE.md     # ← este archivo
```

Carpeta local de Oscar (foco-predator): `C:\Users\oscar\OneDrive\Documentos\GitHub\greatdeal-app`. Las rutas `C:\Users\vales\...` de las bitácoras viejas son de la máquina de Vale.

---

## 5. Variables de entorno en Render (`greatdeal-api` → Environment)

| Variable | Para qué | Estado 26-ago |
|---|---|---|
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | Publicar en `properties`, Storage de respaldo | ✅ |
| `SUPABASE_BUCKET_REELS`, `SUPABASE_MAX_MB` | Bucket/límite de reels en Supabase | opcional |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_PUBLIC_BASE`, `R2_MAX_MB` | Storage principal de reels (PR #18) | ✅ |
| `OPENAI_API_KEY` | Moderación de frames, Whisper, captions. Sin ella la moderación es fail-open | ✅ |
| `ELEVENLABS_API_KEY` | Voz IA | ✅ |
| `RUNWAY_API_KEY` | Video-to-video | ✅ |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_VERIFY_SERVICE_SID` | OTP por WhatsApp/SMS | ⏳ **pendiente** (servicio Verify ya creado, ver §10) |
| `RESEND_API_KEY`, `VERIFY_FROM_EMAIL` | OTP por mail (fallback: `SMTP_HOST/USER/PASS/PORT`) | ⏳ pendiente (dominio en Resend esperando DNS) |
| `VERIFY_TOKEN_SECRET` | Firma HMAC de los tokens de verificación (si falta usa la service-role key) | ⏳ conviene agregar |
| `HIRE_NOTIFY_EMAIL` | Destino de "Contratar grabación" | ✅ |
| `BACKEND_PUBLIC_URL` | URL pública del backend para migrar videos locales | opcional |

**Regla de oro**: el frontend nunca muestra nombres de variables de entorno al usuario (PR fix/qa-26ago); los detalles técnicos van a `console.error`.

---

## 6. Backend (`main.py`)

### Endpoints

| Grupo | Endpoints |
|---|---|
| Salud | `GET/HEAD /`, `GET/HEAD /health` |
| Publicación | `POST /api/publish` (inserta en `properties`; migra el video a R2/Supabase si es local; exige token de verificación **solo si el canal está configurado**) · `POST /api/profile/upsert` · `POST /api/lead/capture` · `POST /api/hire-request` |
| Reel listo | `POST /api/upload-ready-reel` · `POST /api/upload-chunk` + `/finish` (subida por partes) · `POST /api/moderate` (frames → OpenAI; fail-open ante errores de infraestructura, bloquea si `safe=false`) |
| OTP | `GET /api/verify/config` → `{"phone":bool,"email":bool}` · `POST /api/verify/start` · `POST /api/verify/check` (rate limit: 4/h y 1/min por destino; código de 6 dígitos; token HMAC 24 h) |
| Editor de reels | `POST /api/jobs`, `GET /api/jobs/{id}`, `/download`, `POST /reprocess`, `GET/POST /subtitles`, `GET /api/files/{name}` |
| IA | `/api/voices`, `/api/generate-voice`, `/api/script-preview`, `/api/generate-caption`, `/api/analyze-clip`, `/api/analyze-quality`, `/api/transcribe-audio`, `/api/runway/*`, `/api/music-presets`, `/api/music-preview/{key}`, `/api/cinematic-filters` |

### Pipeline FFmpeg (`editor.py`)
Vertical 9:16. Desde PR #17, **escalera de calidad**: intenta 1080p y baja solo lo necesario según memoria. Texto Poppins centrado en tercio inferior; CTA white-label (info · precio · tagline); concat por demuxer (no xfade) y ducking simple de música con voz. El texto usa `drawbox` semitransparente detrás (no `borderw`, que en mayo tumbaba el container: **ese bug está resuelto**).

### Jobs
In-memory (`JOBS` dict con lock). Se pierden al reiniciar Render. Las publicaciones sí persisten (Supabase).

---

## 7. Frontend: wizard de publicación (3 pasos visuales, 4 internos)

`state.step` va 1–4; el stepper muestra 3: **Datos** (step 1) → **Video** (steps 2 y 3) → **Precio** (step 4). Modos de video (`state.upload_mode`): `ready_reel` ("Ya tengo mi reel", salta de 2 a 4), `guided` ("Armar mi reel con IA": secciones, audio, generación), `hire` ("Contratar grabación": formulario), `simple`.

### Paso 1 · Datos
- Vender / Arrendar · Dirección + depto + comuna · **"Buscar en catastro"** (`tasar.c2cprops.com/api/predio`, trae m², tipo y ROL del SII; botón con estado de carga y timeout 20 s).
- Tipo: Casa, Departamento, Sitio, Parcela, Oficina, Industrial.
- **Departamento**: "m² útiles" + "m² terraza (opcional)" + "m² totales" (readonly, `updTotalesDepto()`), sin "m² terreno". Otros tipos: "m² útiles / construidos" + "m² terreno". Los m² se clampean a ≥ 0 (`min="0"` + `Math.max` en el cálculo).
- Características por tipo: depto agrega salón multiuso y estacionamiento de visita; "bodega" quedó fuera de la UI (se conserva en `featureMap`/`_valid_features` por publicaciones viejas).
- **Preview del cierre del reel** en vivo (`updPreviewInfo()`): depto con terraza anuncia m² totales; el resto, útiles. Preview, placeholder del campo "Info" y `buildCtaData()` salen de la misma función `ctaInfoDefault(p)` (PR #20).
- **Validación al continuar** (`validarPaso1`, PR fix/qa-26ago): dirección, comuna y tipo obligatorios; m² útiles > 0. Mensajes inline (`showNavError`), nunca `alert()`.

### Paso 2 · Video
- Un solo botón "📤 Seleccionar video" (input sin `accept`: abre el explorador del sistema, donde conviven teléfono y Drive/Dropbox). No existe "Desde la nube".
- Antes de moderar/subir: `despertarBackend()` (pings a `/health` hasta 90 s, mensaje "Despertando el servidor…") y `fetchReintento()` (1 reintento ante corte de red).
- Moderación automática con mensajes por etapa; subida por chunks con progreso.
- Modo guiado: secciones (exterior, entrada 3x, dormitorios, baños, áreas, vista), audio (música preset/propia, voz: sin/subir/grabar/IA), subtítulos Whisper, Runway por toma, editor avanzado con trim visual.

### Paso 3 · Precio y publicar
- Precio en UF (o vía tasador de Valentina: vuelve con `?precio_uf=&volver=1&contacto=`), nombre, WhatsApp/teléfono/mail, método de contacto, ubicación "vanity" (`#pf-vanity`; no hay campo título: el título se arma solo).
- **Validación de teléfono** (`telefonoValido`): `+56 9 XXXX XXXX` o 9 dígitos.
- OTP de 6 dígitos ("Enviar código" / "Verificar") **solo cuando `/api/verify/config` reporta el canal activo**; si no, el backend no lo exige (fail-open, ver §10).
- "🚀 Publicar en C2C marketplace" → `POST /api/publish`. Payload incluye `terraza_m2` (null si no es depto) y `terreno_m2` (null para deptos). Error de red/backend: mensaje genérico al usuario, detalle en consola.

### Header
Nav "Comprar · Publicar · ✦ Mi asistente IA ▾" (dropdown con Ayuda en tu compra / venta y "Editor de videos" → `/?mode=editor`). En ≤ 420 px los links van dentro del dropdown y el botón queda "✦ ▾" (PR #19 + fix/qa-26ago). `aria-label` y cierre con Escape.

### Estado local
Borrador en `localStorage.greatdeal_state_v1` (se restaura al abrir; los videos no). Cualquier evento `input` disparado por script lo sobrescribe: en QA, respaldar antes.

---

## 8. Cómo se trabaja (agosto 2026)

- **Oscar** trabaja desde Claude Code en la app de escritorio de Claude, con **gstack** instalado (`/qa`, `/review`, `/ship`, `/cso`). La sesión debe abrirse **en la carpeta del repo**; si no, `/qa` queda en modo solo-reporte.
- Flujo: prompt con el fix → revisar diff → `/review` → `/ship` (pushea la rama; no hay `gh`, el PR se abre desde el link `compare` en Chrome) → merge en GitHub → verificación en producción.
- **Vale** pushea con GitHub Desktop; el repo local no tiene credential helper.
- Nunca pedir ni manejar credenciales; las API keys se pegan en Render directamente.
- Contexto adicional vive en el proyecto "IA prop" de Claude (`greatdeal-contexto.md`, `qa-greatdeal-*.md`, `otp-config-greatdeal.md`).

---

## 9. Historial de PRs recientes

| PR | Fecha | Qué |
|---|---|---|
| #12 | 16-ago | Terraza + m² totales en depto; características por tipo; columna `terraza_m2` en Supabase |
| #13 | 16-ago | Botón único de video; `despertarBackend`, `fetchReintento`; moderación fail-open; fin del "Failed to fetch" |
| #16 | ago | Fixes de publicación |
| #17 | ago | Escalera de calidad FFmpeg (1080p primero) |
| #18 | ago | Cloudflare R2 como destino de reels, Supabase de respaldo |
| #19 | 25-ago | Header móvil ≤ 420 px sin desborde |
| #20 | 25-ago | Cierre del reel con m² totales + refresco en vivo; `min="0"`; aria-label; Escape |
| fix/qa-26ago | 26-ago | 9 commits del QA de gstack: validación paso 1 y teléfono, contraste en tema oscuro, sin nombres de env vars en errores, links del header en el dropdown móvil, clamp de m², loading + timeout del catastro |

---

## 10. Pendientes (26-ago-2026)

| Prioridad | Pendiente | Estado |
|---|---|---|
| 🔴 ALTA | **Activar OTP**: hoy `/api/verify/config` = `{phone:false,email:false}` → cualquiera publica con contacto inventado. Twilio: servicio Verify "C2C props" creado (SID en `otp-config-greatdeal.md`), faltan las 3 env vars en Render. Resend: dominio agregado, faltan 3 registros DNS en Vercel. | Bloqueado por acceso a Render/Vercel (§2) |
| 🔴 ALTA | Publicación real desde el teléfono y confirmar `terraza_m2` en Supabase; ver "Despertando el servidor…" con Render dormido | Prueba manual |
| 🟡 MEDIA | `?mode=editor` (link "Editor de videos" del asistente): la app ignora el parámetro y pide la dirección. Implementar: entrar directo a Video con "Armar mi reel con IA", datos opcionales hasta publicar | Decidido implementar |
| 🟡 MEDIA | Catastro devuelve predios reales para direcciones inexistentes, sin estado vacío; "✓ Sí, usar estos datos" puede confirmar un ROL ajeno → umbral de coincidencia (backend tasar) | |
| 🟡 MEDIA | Sitio y Oficina reusan el formulario de Casa (piden dormitorios/piscina a un terreno) | |
| 🟢 BAJA | Accesibilidad: `<label for>`, `aria-live`, `aria-pressed` en los 25 toggles; target táctil del botón asistente ≥ 44×44 | Un PR dedicado |
| 🟢 BAJA | Copy "paso 4" en wizard de 3; placeholder "Comuna · Ej: Vitacur" cortado; stepper móvil con conector colgando; Tailwind por CDN en prod; errores en `alert()` con JSON crudo | |
| 🟢 BAJA | Reel queda público en storage antes del OTP; borrar rastro `reels/ready_d4731ae46941.mp4` del QA | |
| 🟢 BAJA | Jobs en memoria → DB; voz con auto-calce (atempo) | histórico |

---

## 11. Decisiones técnicas clave

- **Fail-open deliberado** en OTP y moderación: sin env vars el deploy sigue funcionando; se endurece solo al configurar los servicios.
- **R2 antes que Supabase Storage** para reels: egress gratis; Supabase queda de respaldo.
- **Un solo botón de video sin `accept`**: el selector del sistema ya integra Drive/Dropbox/OneDrive en el teléfono; el segundo botón confundía.
- **Sin `alert()` para validaciones**: en móvil tapa el formulario y pierde el foco; se usan mensajes inline.
- **Concat por demuxer, no xfade**; **`drawbox` en vez de `borderw`** (CPU); **escalera de calidad** en vez de resolución fija.
- **Una sola fuente para el texto del cierre** (`ctaInfoDefault`): preview, placeholder y reel no pueden divergir.

---

## 12. Bugs conocidos y lecciones aprendidas

### Repo / tooling
- **`frontend/index.html` usa CRLF** (con algún CR huérfano embebido). Editarlo con herramientas que preserven bytes; nunca reescribirlo entero (un editor que normalice a LF genera un diff de 5000 líneas).
- Claude Code en la carpeta equivocada (`G:\Mi unidad\Claude`) → gstack no puede commitear. Abrir la sesión en el repo.
- Chrome renombra descargas repetidas (`index_5.html`): al subir archivos por la web de GitHub, revisar que el PR reemplace `frontend/index.html` y no agregue uno nuevo (pasó en PR #19).
- Las bitácoras §15–17 mencionan archivos truncados y `head/mv` peligrosos: eran problemas del sandbox de mayo; validar con `grep -n "@app\.\|^if __name__"` sigue siendo buena práctica.

### App
- La app usa `alert()`/`confirm()`/`beforeunload` en varios flujos: automatizaciones de navegador se congelan si no los sobreescriben (`window.alert = () => {}`, `onbeforeunload = null`).
- Render free duerme: la primera request tras 15 min tarda 30–90 s (`despertarBackend` lo cubre; en QA, hacer `GET /health` antes).
- El error de "Supabase no configurada" ya no se muestra al usuario; si aparece en consola, faltan `SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY`.

### FFmpeg / móvil
- Escape en drawtext (`_esc()`); concat requiere mismo codec/res/fps (normalize antes).
- iOS Safari MediaRecorder solo `audio/mp4`; audios grabados pesados rompen uploads lentos.

---

## 13. Costos operativos

| Item | Costo |
|---|---|
| Render (`greatdeal-api`) | según plan actual del dashboard (free duerme; Starter $7; Standard $25 con 2 GB para FFmpeg) |
| Vercel | $0 |
| Supabase | free tier |
| Cloudflare R2 | $0 hasta 10 GB |
| ElevenLabs | ~$22/mes (Creator) |
| Runway | pay-as-you-go (~$0.05/seg) |
| OpenAI | pay-as-you-go (moderación + Whisper) |
| Twilio Verify | ~$0.05 por verificación + saldo cargado (USD 20) |
| Resend | $0 hasta 3.000 mails/mes |

---

## 14. Checklist al inicio de sesión

1. Leer este archivo (secciones 1–12).
2. `git pull origin main` — los merges se hacen por la web de GitHub, el clon local suele estar atrás.
3. Abrir la sesión de Claude Code en la carpeta del repo.
4. Si se va a probar producción: `GET https://greatdeal-api.onrender.com/health` primero.
5. Ediciones a `frontend/index.html`: incrementales y preservando CRLF.
6. Antes del PR: `/review`; después del deploy: `/qa https://vender.c2cprops.com` con los flujos que tocó el cambio.
7. Al cerrar: actualizar §9 y §10 de este archivo si cambió algo.

---

# Bitácoras históricas (mayo 2026) — solo contexto, no vigentes

> Todo lo listado abajo como "pendiente", "bug activo" o "pendiente de push" **ya fue resuelto o reemplazado** por el estado descrito arriba. En particular: el bug de Render reiniciándose con FFmpeg (`borderw`) está resuelto (`editor.py` usa `drawbox`), Whisper está integrado, y el wizard de 4 pasos de reel fue reemplazado por el wizard de publicación de 3 pasos.

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

---

## 17. Sesión 3 — 2026-05-28 — Música real Pixabay + Editar subtítulos + Fix Runway modal + UX post-render

### Lo que se logró hoy

- **Música real precargada (#86)**: reemplazado el sintetizador (que sonaba como sinusoides/vibraciones) por sistema de **archivos mp3 reales bundleados al repo en `backend/music/`**. Orden de prioridad en `download_music_track()`: (1) archivo en `backend/music/{preset_key}.mp3`, (2) cache en `/app/music_cache/`, (3) descarga desde URL del preset (Mixkit con headers de navegador), (4) fallback al sintetizador.
- **5 tracks de Pixabay agregados** (Vale los descargó, todos cinematográficos/strings): asignados a `cinematic_view`, `elegant_piano`, `warm_acoustic`, `dreaming_big`, `corporate_inspiring`. Los 5 restantes (lofi, tech_house, happy_summer, urban_hiphop, chill_hiphop) caen al sintetizado hasta que Vale baje música de otros géneros.
- **Mixkit no funciona desde Render** (HTTP 403 hotlinking). Probamos con User-Agent + Referer + Origin headers — sigue bloqueando IPs de datacenter. Por eso vamos por el approach de mp3 bundleados al repo.
- **Editor de subtítulos post-Whisper (#88)**: nuevo modal "✍️ Editar subtítulos" que aparece en la pantalla del reel cuando hay voz. Backend guarda `subs_segments.json` después de Whisper; endpoint `GET /api/jobs/{id}/subtitles` devuelve los segments; `POST /api/jobs/{id}/subtitles` recibe edits y re-quema sobre `_pre_subs.mp4` (sin reprocesar todo, ~30s).
- **Opacidad fondo subtítulos (#87)**: bajada de `&H80` (50% opaco) a `&HCC` (20% opaco). Tamaño reducido a 34px, padding (Outline) a 10.
- **UX post-render rediseñado (#89)**: la pantalla "Tu reel está listo" ahora tiene una grilla visible de 4 botones grandes (Editor avanzado / Editar subtítulos / Cambiar música o voz / Cambiar datos o títulos) en vez de estar todo enterrado en un `<details>` accordion. Botón "↻ Re-generar reel" amarillo prominente. "Empezar otro reel" con confirmación en accordion al fondo.
- **🔴 Fix bug Runway modal vacío**: `renderRunwayModal()` solo buscaba el clip en `state.editor_clips`. Cuando se abría desde paso 1 (guided o simple), el clip estaba en `state.sections[].clips` o `state.simple_clips` → find retornaba undefined → modal renderizaba `""` → "no pasa nada" al apretar el botón. Fix: usar `state.runway_active_dataUrl/fileName` que ya se pre-guarda al abrir el modal.

### 🟡 PENDIENTE DE PUSH al cierre — IMPORTANTE

Vale tiene TODO el código modificado + 5 mp3 sin renombrar en disco. Mañana lo primero es renombrar y pushear.

**Archivos modificados (sin pushear):**
- `backend/editor.py` — MUSIC_PRESETS con URLs Mixkit, `download_music_track()` con prioridad a `backend/music/`, `_synth_fallback_track()`, default cambiado a `cinematic_view`
- `backend/main.py` — `/api/music-preview` con fallback a synth, endpoints GET/POST `/api/jobs/{id}/subtitles`, `Body` import, default cambiado a `cinematic_view`
- `backend/subtitles.py` — ASS BackColour más transparente (`&HCC`), `apply_auto_subtitles` guarda segments JSON, nueva función `reapply_edited_subtitles()`
- `frontend/index.html` — Paso 4 rediseñado con grilla de acciones, `openSubtitleEditor()` + `renderSubtitleEditorModal()` + `saveEditedSubtitles()`, fix `renderRunwayModal()` para los 3 sources, default `music_preset: "cinematic_view"`
- `backend/music/README.md` — instrucciones para subir mp3
- `backend/music/*.mp3` — 7 archivos descargados de Pixabay (con nombres originales largos, falta renombrar)

### Primer paso de mañana — BLOQUE PARA PEGAR EN POWERSHELL

Vale debe pegar este bloque completo en PowerShell. Renombra los 5 mp3, borra los 2 sobrantes (duplicados cinemáticos), commit y push:

```powershell
cd C:\Users\vales\OneDrive\Documents\Claude\GitHub\greatdeal-app\backend\music
Rename-Item "petrushkasound-strings-cinematic-461974.mp3" "cinematic_view.mp3"
Rename-Item "marry077-romantic-cinematic-strings-453922.mp3" "elegant_piano.mp3"
Rename-Item "farran_ez-string-violin-cello-loop-456150.mp3" "warm_acoustic.mp3"
Rename-Item "nastelbom-cinematic-music-495885.mp3" "dreaming_big.mp3"
Rename-Item "nastelbom-epic-cinematic-2-507930.mp3" "corporate_inspiring.mp3"
Remove-Item "sutton-cinematic-dramatic-cinematic-journey-529854.mp3"
Remove-Item "grand_project-deep-epic-cinematic-when-time-collapses_medium-501530.mp3"
cd C:\Users\vales\OneDrive\Documents\Claude\GitHub\greatdeal-app
git add -A
git commit -m "musica real Pixabay + fix runway modal + editar subs + UX post-render"
git push
```

Después esperar ~3-5 min el redeploy de Render y validar end-to-end.

### Pendientes priorizados para mañana

🔴 **ALTA**
1. **Push del bloque de arriba** — sin esto nada de hoy llega a producción
2. **Validar end-to-end**: generar un reel con voz para probar los 5 nuevos tracks reales, el editor de subtítulos, el modal Runway desde paso 1, y el nuevo UX post-render
3. **Vale baja 5 mp3 más** (lofi, tech house, ukulele, hip hop, chill hop) para cubrir los 5 presets restantes — opcional, no urgente

🟡 **MEDIA**
- Bug móvil #60 — re-validar el editor avanzado en celular (ahora que cambiamos UX)
- Persistencia de jobs (#61) — los jobs se pierden con cada restart de Render; el editor de subtítulos necesita que el job esté vivo

🟢 **BAJA**
- ElevenLabs (#24)
- Sistema de Proyectos (#61)

### Cosas aprendidas hoy

- **Mixkit bloquea hotlinking desde IPs de datacenter** aunque mandes User-Agent de Chrome. La solución es bundlear los mp3 con el repo (`backend/music/`) o usar Pixabay (que sí permite hotlinking explícitamente).
- **`COPY . .` en el Dockerfile** copia automáticamente `backend/music/*.mp3` al container. Sin cambios al Dockerfile.
- **Path real del repo de Vale**: `C:\Users\vales\OneDrive\Documents\Claude\GitHub\greatdeal-app\` (con `Claude\` en el medio). La carpeta `C:\Users\vales\OneDrive\Documents\GitHub\greatdeal-app\` está vacía — fue confusión mía en una sesión anterior. **Siempre usar el path con `Claude\`**.
- **Bug clásico de render selectivo**: cuando una función de render espera datos de un solo lugar pero el state puede venir de varios (múltiples sources), `find().return ""` causa "nothing happens" sin errores en consola. Solución: render desde datos pre-guardados en state genérico, no buscando en arrays específicos.
- **El sintetizador FFmpeg con sinusoides puede sonar como vibraciones**, no como música. Para una app que devuelve "calidad pro" no es aceptable como output principal — solo como fallback de emergencia.

### Estado del repo al cierre

- 7 mp3 en `backend/music/` con nombres originales de Pixabay (sin renombrar)
- 5 archivos `.py` y 1 `.html` modificados (sin commit)
- 1 archivo nuevo: `backend/music/README.md`
- 0 commits/pushes hechos esta sesión
- Producción sigue en el estado de la sesión 2 (sin las mejoras de hoy)

---

*Última actualización: 2026-05-28 fin de día — todo listo en disco, push pendiente, retomar mañana con el bloque PowerShell*
