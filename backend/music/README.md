# 🎵 Música para los presets de GreatDeal

El backend busca aquí PRIMERO los mp3 de cada preset, antes de intentar descargarlos de internet.

## Cómo agregar las pistas

1. Descargá un mp3 desde cualquier fuente libre de derechos (Pixabay, Mixkit, FreePD, YouTube Audio Library, etc.)
2. Renombralo **exactamente** con la clave del preset (case-sensitive, sin acentos)
3. Ponelo en esta carpeta
4. `git add backend/music/*.mp3 && git commit && git push`

## Lista de archivos esperados

| Archivo | Mood | Buscá en Pixabay/Mixkit |
|---------|------|--------------------------|
| `cinematic_view.mp3` | 🎬 Cinematográfico — vista | "cinematic strings", "epic landscape" |
| `elegant_piano.mp3` | 🎹 Piano elegante | "elegant piano", "emotional piano" |
| `warm_acoustic.mp3` | 🌅 Cálido acústico | "warm acoustic guitar", "acoustic folk" |
| `happy_summer.mp3` | ☀️ Verano alegre | "happy ukulele", "summer pop" |
| `corporate_inspiring.mp3` | 💼 Corporate inspiracional | "corporate motivational", "inspiring business" |
| `dreaming_big.mp3` | ✨ Sueños grandes | "inspirational uplifting", "emotional cinematic" |
| `lofi_chill.mp3` | 🌙 Lo-fi chill | "lo-fi chill", "relaxing beats" |
| `tech_house.mp3` | ⚡ Tech house | "tech house", "modern electronic" |
| `urban_hiphop.mp3` | 🏙️ Urban hip-hop | "urban hip hop", "trap beat" |
| `chill_hiphop.mp3` | 🎧 Chill hip-hop | "chill hip hop", "lo-fi rap" |

## Requisitos técnicos

- Formato: **MP3**
- Duración: **30–90 segundos** (se loopea automáticamente para reels más largos)
- Calidar: 128kbps+ es suficiente
- Tamaño: idealmente < 2MB cada uno (mantener el deploy liviano)

## Importante

- Solo música **libre para uso comercial sin atribución requerida** (Pixabay, Mixkit, FreePD, YouTube Audio Library Free).
- Si falta algún archivo, el backend intenta descargarlo de la URL del preset; si falla, sintetiza una versión simple.

## Fuentes recomendadas

- **Pixabay Music** — https://pixabay.com/music/ (free for commercial use, no attribution)
- **YouTube Audio Library** — Studio → Audio Library → Free Music
- **FreePD** — https://freepd.com/ (CC0 public domain)
- **Mixkit** — https://mixkit.co/free-stock-music/ (free for commercial use)
