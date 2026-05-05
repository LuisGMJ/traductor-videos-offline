# Changelog

Todos los cambios importantes de este proyecto se documentan aqui.

El formato sigue una adaptacion simple de [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y usa versionado semantico.

## [1.0.1] - 2026-05-04

### Agregado
- Instalador de Windows en formato `Setup.exe` listo para distribuir a usuarios no tecnicos.
- Script `build_installer` para generar el instalador a partir de la release ZIP.

### Mejorado
- Flujo de publicacion para adjuntar un instalador como asset principal en GitHub Releases.

## [1.0.0] - 2026-05-04

### Agregado
- Interfaz de escritorio multiplataforma con `PySide6`.
- Procesamiento por lote de multiples videos.
- Transcripcion local con `faster-whisper`.
- Traduccion offline con `Argos Translate`.
- Modo `Solo transcribir` para generar subtitulos en el mismo idioma del audio.
- Generacion de subtitulos `.srt` con el mismo nombre base del video.
- Exportacion opcional de video con subtitulos quemados.
- Script de release para generar un ZIP versionado listo para GitHub Releases.

### Mejorado
- Manejo mas claro de videos sin voz util o con voz poco detectable.
- Distribucion visual y responsiva del panel principal.
- Empaquetado en modo `onedir` con activos offline sembrados para la primera ejecucion.
