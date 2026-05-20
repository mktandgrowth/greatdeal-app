# GreatDeal · Editor v0.1

Plataforma local para editar reels inmobiliarios automáticamente.

Subes clips → eliges voz y música → te devuelve un MP4 vertical listo para Reels/TikTok con text overlays, transiciones, voiceover IA opcional y CTA card.

---

## Stack

- **Backend**: Python 3.10+ con FastAPI
- **Edición video**: FFmpeg (orquestado desde Python)
- **Voz IA**: ElevenLabs API (opcional)
- **Frontend**: HTML + Tailwind (sin framework, todo en un archivo)

---

## Setup en tu PC (Windows)

### 1. Instalar Python 3.10 o superior

Descarga desde python.org. Cuando instales, MARCA la casilla **"Add Python to PATH"**.

Verifica:
```
python --version
```

### 2. Instalar FFmpeg

**Windows:**
1. Descarga: https://www.gyan.dev/ffmpeg/builds/ → "release essentials"
2. Descomprime el ZIP
3. Mueve la carpeta `ffmpeg-X.X-essentials_build` a `C:\ffmpeg`
4. Agrega `C:\ffmpeg\bin` al PATH del sistema:
   - Buscar "Variables de entorno" en el menú inicio
   - Editar variable `Path` del usuario
   - Agregar `C:\ffmpeg\bin`
5. Cierra y reabre la terminal

Verifica:
```
ffmpeg -version
ffprobe -version
```

Ambos deben funcionar.

### 3. Clonar / copiar este proyecto

Pon esta carpeta `greatdeal-app/` donde quieras (por ejemplo `C:\Users\vale\greatdeal-app`).

### 4. Instalar dependencias Python

Abre terminal en la carpeta del proyecto:
```
cd greatdeal-app
pip install -r backend/requirements.txt
```

### 5. (Opcional) Conseguir API key de ElevenLabs

Para generar voz IA:
1. Registrate gratis en https://elevenlabs.io
2. Plan Free te da 10.000 caracteres mensuales (~10 reels)
3. Ir a Settings → API Keys → Create new key
4. Copiar la API key
5. En tu terminal, antes de levantar el servidor:

**Windows PowerShell:**
```
$env:ELEVENLABS_API_KEY = "tu_api_key_aca"
```

**Windows CMD:**
```
set ELEVENLABS_API_KEY=tu_api_key_aca
```

(Para que persista entre sesiones, agregalo a variables de entorno del sistema)

### 6. Levantar el servidor

Desde la carpeta `greatdeal-app`:
```
cd backend
python main.py
```

Deberías ver:
```
Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

### 7. Abrir el editor

Ir en el navegador a:
```
http://localhost:8000/
```

¡Listo! Subí tus clips y procesá tu primer reel.

---

## Cómo usar el editor

### Paso 1 · Subir clips
Arrastra 2-6 clips MP4/MOV. Para cada uno podés definir:
- Headline en pantalla (ej: "PIRQUE")
- Subline (ej: "a 40 min de Santiago")
- Duración a usar (cuánto del clip se incluye, en segundos)
- Orden (con flechas ↑↓)

### Paso 2 · Datos propiedad
Tipo, comuna, m², dormitorios, baños, precio, diferenciador. Esto va al CTA final y al voiceover IA si lo usas.

### Paso 3 · Voz
3 opciones:
- **Sin voz**: solo text overlays + música. Más rápido.
- **Subir mi voz**: MP3 grabado por ti o un locutor.
- **Generar con IA**: ElevenLabs te crea el voiceover. Requiere API key.

Si elegís IA, hay 4 voces pre-curadas para GreatDeal (cálida, premium, joven, hombre).

### Paso 4 · Música
- **Pad ambiente default**: generado por FFmpeg, sin claims.
- **Subir tu MP3**: lo recomendado para producción (libre de derechos).

### Paso 5 · Render
Click "Procesar reel". Tarda ~30-90 seg dependiendo de los clips. Cuando termina, podés previsualizar y descargar.

---

## Arquitectura del orquestador

```
clips raw → normalize (720x1280, color correction)
         → trim (cada clip a su duración objetivo)
         → text overlay (headline + subline en safe zone)
         → concat con xfades 0.4s
         → + CTA card 5s (generada con datos propiedad)
         → mux con música (ducking si hay voz)
         → MP4 final 720x1280
```

Cada paso es independiente, registrado en `job.log` para debugging.

---

## Estructura del proyecto

```
greatdeal-app/
├── backend/
│   ├── main.py            ← FastAPI server (endpoints HTTP)
│   ├── editor.py          ← Pipeline FFmpeg (sin red, todo local)
│   ├── voice.py           ← Integración ElevenLabs
│   └── requirements.txt
├── frontend/
│   └── index.html         ← UI completa (Tailwind CDN, sin build)
├── uploads/               ← Clips subidos por usuario (auto-creado)
├── outputs/               ← MP4s finales generados (auto-creado)
├── work/                  ← Archivos intermedios (auto-creado, podés borrar)
└── README.md
```

---

## API endpoints (para integrar)

| Método | Path | Descripción |
|---|---|---|
| GET | `/` | Sirve frontend HTML |
| GET | `/api/voices` | Lista voces curadas |
| POST | `/api/jobs` | Crea job (multipart: clips, property_data JSON, music, voice_audio) |
| GET | `/api/jobs/{id}` | Estado del job |
| GET | `/api/jobs/{id}/download` | Descarga MP4 final |
| GET | `/api/script-preview?...` | Preview del voiceover auto-generado |

---

## Costos reales por reel (cuando esté en producción)

| Componente | Costo |
|---|---|
| Edición FFmpeg en server | $0.02 |
| Voz IA ElevenLabs (Creator $22/mes incluye ~1000 reels) | ~$0.02 |
| Música de Mubert (si activamos) | $0.10 |
| Storage (R2) | $0.001 |
| **Total** | **~$0.15** |

Cobras 3 UF (~$115 USD). Margen >99%.

---

## Limitaciones de v0.1 (lo que falta)

- ❌ Sin autenticación (cualquiera puede usar el server local)
- ❌ Sin pagos integrados
- ❌ Cola de jobs en memoria (se pierden si reinicia el server)
- ❌ Storage local solamente (no cloud)
- ❌ Subtítulos animados karaoke todavía no implementados
- ❌ Music ducking básico (necesita afinar parámetros del sidechain compressor)
- ❌ Sin estabilización con vidstab (toma 2x más tiempo)

Todo esto se agrega en v0.2 cuando pase a la nube.

---

## Troubleshooting

**"ModuleNotFoundError: No module named 'fastapi'"**
→ Activá tu entorno Python y corré `pip install -r backend/requirements.txt`

**"ffmpeg: command not found" o "ffprobe not found"**
→ FFmpeg no está en el PATH. Volvé al paso 2 del setup.

**"Address already in use" al levantar el server**
→ Otro proceso usa el puerto 8000. Cerralo o cambiá el puerto en main.py.

**El reel sale sin voz cuando elegí IA**
→ Falta la ELEVENLABS_API_KEY. Revisá la variable de entorno. Ver paso 5 del setup.

**Los videos del browser no se previsualizan**
→ Algunos navegadores no rinden MOV de iPhone. Usá Chrome o convertí a MP4 antes.

---

## Próximos pasos (roadmap inmediato)

1. **Probar v0.1 con propiedades reales** — subir clips de 3-5 propiedades y validar output
2. **Curar 6-8 voces ElevenLabs definitivas** — probar voces específicas, anotar voice_ids
3. **Implementar subtítulos karaoke** — transcribir voz con Whisper, generar ASS file con animación palabra-por-palabra
4. **Pasar a la nube** — Vercel para frontend, Railway/Render para backend Python, R2 para storage
5. **Agregar auth + pagos** — Supabase Auth + Stripe/MercadoPago
