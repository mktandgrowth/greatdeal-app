# Deploy en producción · Vercel + Render

Tiempo total: ~25 minutos. Costo: $0 (planes free).

---

## Resumen de la arquitectura

```
github.com/vales/greatdeal-app   ←  el código vive acá
            │
            ├──→ Vercel  ───────→ greatdeal-app.vercel.app
            │    (frontend HTML)    (lo que ven los vendedores)
            │
            └──→ Render  ───────→ greatdeal-api.onrender.com
                 (backend Python + FFmpeg)
                 │
                 └─→ ElevenLabs API (si activamos voz IA)
```

---

## Paso 1 · Subir el código a GitHub (5 min)

### 1.1 Crear el repo

1. Andá a https://github.com/new
2. Nombre: `greatdeal-app` (o el que prefieras)
3. **Visibilidad: Private** (recomendado)
4. **NO** marques "Initialize with README" (ya tengo uno)
5. Click "Create repository"

### 1.2 Subir los archivos

Tenés 2 opciones según tu nivel de comodidad con terminal:

**Opción A · Drag & drop en la web (más fácil, sin git)**
1. En la página del repo recién creado, click "uploading an existing file"
2. Arrastra TODA la carpeta `greatdeal-app/` ahí
3. Commit message: "initial commit"
4. Click "Commit changes"

**Opción B · Por terminal (recomendado si vas a iterar mucho)**
```
cd C:\Users\vales\Documents\greatdeal-app
git init
git add .
git commit -m "initial commit"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/greatdeal-app.git
git push -u origin main
```

---

## Paso 2 · Deploy del backend en Render (10 min)

### 2.1 Crear cuenta en Render

1. Andá a https://render.com
2. Sign up con GitHub (login automático, sin pass nueva)
3. Autoriza el acceso a tu repo `greatdeal-app`

### 2.2 Crear el servicio

1. En Render dashboard → click **"New +"** → **"Web Service"**
2. Conectá el repo `greatdeal-app`
3. Configurá:
   - **Name**: `greatdeal-api`
   - **Region**: Oregon (US West) — el más cercano a Chile latencia
   - **Branch**: `main`
   - **Root Directory**: `backend`
   - **Runtime**: **Docker** (Render lo detecta del Dockerfile)
   - **Plan**: **Free**
4. Click "Create Web Service"
5. Render empieza el build (5-8 min la primera vez — instala FFmpeg, descarga Poppins, etc.)
6. Cuando termine, vas a ver el log decir `Uvicorn running on http://0.0.0.0:8000`

### 2.3 Configurar ElevenLabs API key (opcional pero recomendado)

1. En el servicio recién creado → **Environment** (menú lateral)
2. Click **"Add Environment Variable"**
3. Key: `ELEVENLABS_API_KEY` · Value: tu API key de elevenlabs.io
4. Click "Save Changes" → Render redeploya automáticamente

### 2.4 Probar el backend

Cuando el deploy esté listo, vas a tener una URL tipo `https://greatdeal-api.onrender.com`. Andá a:
```
https://greatdeal-api.onrender.com/api/voices
```
Tiene que devolver el JSON con las 4 voces. Si lo ves, el backend funciona.

⚠ **Si el plan es Free**: el servicio se duerme tras 15 min sin tráfico. La primera request despierta el container y tarda ~30 seg. Para producción real, plan Starter ($7/mes) lo mantiene siempre activo.

---

## Paso 3 · Deploy del frontend en Vercel (5 min)

### 3.1 Conectar el repo

1. Andá a https://vercel.com/new
2. **Import Git Repository** → elegí `greatdeal-app`
3. Configurá:
   - **Framework Preset**: **Other** (es solo HTML estático)
   - **Root Directory**: `frontend` (importante)
   - **Build Command**: dejar vacío
   - **Output Directory**: dejar `./` o vacío
4. Click "Deploy"
5. En ~30 segundos te queda en `https://greatdeal-app.vercel.app` (o el nombre que pongas)

### 3.2 Conectar frontend → backend

El frontend ya tiene hardcoded `https://greatdeal-api.onrender.com` como backend default. **Si tu URL de Render es diferente**, editá `frontend/index.html` línea ~108 y cambiá:

```javascript
return window.GREATDEAL_API_URL || "https://greatdeal-api.onrender.com";
```

por tu URL real. Hacé commit + push y Vercel redeploya solo.

### 3.3 Configurar CORS en backend

En `backend/main.py` ya tengo `allow_origins=["*"]` (permisivo). En producción real recomiendo restringirlo a tu dominio Vercel:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://greatdeal-app.vercel.app"],
    ...
)
```

---

## Paso 4 · Probar end-to-end

1. Andá a `https://greatdeal-app.vercel.app`
2. Subí 4 clips de prueba
3. Llená los datos de la propiedad
4. Elegí voz "Sin voz" (para no gastar créditos ElevenLabs)
5. Música pad ambiente
6. Click "Procesar reel"

Render debería procesar y devolverte el MP4. Si es la primera request en 15+ min, va a tardar ~30 seg de cold start + el tiempo de procesamiento.

---

## Troubleshooting

**"Build failed: Dockerfile not found"**
→ El Root Directory en Render tiene que ser `backend`, no la raíz.

**"FFmpeg command not found" (en logs de Render)**
→ El Docker build no instaló FFmpeg correctamente. Revisá `backend/Dockerfile`.

**Frontend muestra "Failed to fetch" o CORS error**
→ La URL del backend en `index.html` está mal o el backend no está activo (cold start). Esperá 30 seg.

**El reel se procesa pero queda en "processing" para siempre**
→ Render free tier puede matar requests de larga duración. Si los videos son largos (>60s output), subí a plan Starter.

**"Job queue lost after restart"**
→ La cola de jobs es en memoria. Si Render reinicia el container, se pierde el job. En v0.2 migramos a Redis o DB persistente.

---

## Costos reales en este setup

| Servicio | Plan | Costo |
|---|---|---|
| GitHub | Free | $0 |
| Vercel | Hobby | $0 (hasta 100 GB bandwidth/mes) |
| Render | Free | $0 (con cold starts) o $7/mes Starter (siempre activo) |
| ElevenLabs | Free | $0 (10k chars/mes ≈ 10 reels) |
| Cloudflare R2 (futuro) | - | $0 (hasta 10 GB storage) |
| **Total para arrancar** | | **$0 / mes** |
| **Total producción seria** | | **~$30 / mes** (Render Starter + ElevenLabs Creator) |

---

## Próximos pasos cuando esto funcione

1. **Custom domain**: conectá `greatdeal.vercel.app` o subdomain a Vercel y Render
2. **Cloudflare R2 para storage**: en vez de guardar reels en el filesystem de Render (efímero), subirlos a R2 (10 GB free)
3. **Database**: Supabase free para guardar usuarios + jobs persistentes
4. **Auth**: Supabase Auth o Clerk para login de vendedores
5. **Pagos**: MercadoPago Chile para cobrar el video premium
6. **Webhook ElevenLabs**: cuando el voiceover esté listo, notificar al cliente
