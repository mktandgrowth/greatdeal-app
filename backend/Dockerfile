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

# Descargar Montserrat font (5 pesos) desde Github (Google Fonts repo)
RUN mkdir -p /usr/share/fonts/truetype/montserrat \
 && curl -L -o /usr/share/fonts/truetype/montserrat/Montserrat-Black.ttf \
    "https://raw.githubusercontent.com/google/fonts/main/ofl/montserrat/static/Montserrat-Black.ttf" \
 && curl -L -o /usr/share/fonts/truetype/montserrat/Montserrat-ExtraBold.ttf \
    "https://raw.githubusercontent.com/google/fonts/main/ofl/montserrat/static/Montserrat-ExtraBold.ttf" \
 && curl -L -o /usr/share/fonts/truetype/montserrat/Montserrat-SemiBold.ttf \
    "https://raw.githubusercontent.com/google/fonts/main/ofl/montserrat/static/Montserrat-SemiBold.ttf" \
 && curl -L -o /usr/share/fonts/truetype/montserrat/Montserrat-Regular.ttf \
    "https://raw.githubusercontent.com/google/fonts/main/ofl/montserrat/static/Montserrat-Regular.ttf" \
 && curl -L -o /usr/share/fonts/truetype/montserrat/Montserrat-Thin.ttf \
    "https://raw.githubusercontent.com/google/fonts/main/ofl/montserrat/static/Montserrat-Thin.ttf" \
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
