# GreatDeal · Backend Dockerfile
# Container con Python 3.12 + FFmpeg + fonts Google (Poppins)

FROM python:3.12-slim

# Instalar FFmpeg + libvidstab + fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-dejavu \
    fontconfig \
    curl \
    unzip \
 && rm -rf /var/lib/apt/lists/*

# Descargar fonts: Montserrat (legacy) + Cormorant Garamond (titulos branded) + Inter (body/subs)
# IMPORTANTE: nada de comentarios bash dentro del RUN multilinea — rompe el build.
RUN mkdir -p /usr/share/fonts/truetype/montserrat \
              /usr/share/fonts/truetype/cormorant \
              /usr/share/fonts/truetype/inter \
 && curl -L -o /usr/share/fonts/truetype/montserrat/Montserrat-Black.ttf \
    "https://raw.githubusercontent.com/google/fonts/main/ofl/montserrat/static/Montserrat-Black.ttf" \
 && curl -L -o /usr/share/fonts/truetype/montserrat/Montserrat-Bold.ttf \
    "https://raw.githubusercontent.com/google/fonts/main/ofl/montserrat/static/Montserrat-Bold.ttf" \
 && curl -L -o /usr/share/fonts/truetype/montserrat/Montserrat-SemiBold.ttf \
    "https://raw.githubusercontent.com/google/fonts/main/ofl/montserrat/static/Montserrat-SemiBold.ttf" \
 && curl -L -o /usr/share/fonts/truetype/montserrat/Montserrat-Regular.ttf \
    "https://raw.githubusercontent.com/google/fonts/main/ofl/montserrat/static/Montserrat-Regular.ttf" \
 && curl -L -o /usr/share/fonts/truetype/montserrat/Montserrat-Thin.ttf \
    "https://raw.githubusercontent.com/google/fonts/main/ofl/montserrat/static/Montserrat-Thin.ttf" \
 && curl -L -o /usr/share/fonts/truetype/cormorant/CormorantGaramond-Bold.ttf \
    "https://raw.githubusercontent.com/google/fonts/main/ofl/cormorantgaramond/CormorantGaramond-Bold.ttf" \
 && curl -L -o /usr/share/fonts/truetype/cormorant/CormorantGaramond-SemiBold.ttf \
    "https://raw.githubusercontent.com/google/fonts/main/ofl/cormorantgaramond/CormorantGaramond-SemiBold.ttf" \
 && curl -L -o /usr/share/fonts/truetype/cormorant/CormorantGaramond-Medium.ttf \
    "https://raw.githubusercontent.com/google/fonts/main/ofl/cormorantgaramond/CormorantGaramond-Medium.ttf" \
 && curl -L -o /usr/share/fonts/truetype/inter/Inter-Regular.ttf \
    "https://raw.githubusercontent.com/rsms/inter/master/docs/font-files/Inter-Regular.ttf" \
 && curl -L -o /usr/share/fonts/truetype/inter/Inter-Medium.ttf \
    "https://raw.githubusercontent.com/rsms/inter/master/docs/font-files/Inter-Medium.ttf" \
 && curl -L -o /usr/share/fonts/truetype/inter/Inter-SemiBold.ttf \
    "https://raw.githubusercontent.com/rsms/inter/master/docs/font-files/Inter-SemiBold.ttf" \
 && fc-cache -f

WORKDIR /app

# Instalar dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código del backend
COPY . .

# Crear carpetas de trabajo
RUN mkdir -p /app/uploads /app/outputs /app/work

# Render usa la variable PORT
ENV PORT=8000
EXPOSE 8000

# Arrancar uvicorn — bind a 0.0.0.0 para que sea accesible desde fuera del container
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
