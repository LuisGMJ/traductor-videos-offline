# Traductor de Videos Offline

Aplicacion de escritorio para transcribir, subtitular y traducir videos de forma local, sin depender de servicios de pago ni subir archivos a la nube.

El proyecto esta orientado a un flujo simple: cargar uno o varios videos, procesarlos por lote y obtener archivos `.srt` listos para usar o una version exportada del video con subtitulos incrustados.

## Resumen

- Procesamiento por lote de videos locales.
- Transcripcion offline con modelos de IA.
- Traduccion local a varios idiomas, segun disponibilidad del paquete offline.
- Generacion de subtitulos `.srt` con el mismo nombre base del video.
- Exportacion opcional de video con subtitulos quemados.
- Base multiplataforma para Windows, macOS y Linux.

## Descarga

La distribucion recomendada para Windows es el instalador publicado en la seccion `Releases` del repositorio.

Artefactos de distribucion:

- `TraductorVideos-Setup-vX.Y.Z.exe`: instalador para usuarios finales.
- `TraductorVideos-windows-vX.Y.Z.zip`: paquete portable para uso manual o tecnico.

## Caracteristicas principales

- Interfaz de escritorio construida con `PySide6`.
- Soporte para archivos pesados mediante fragmentacion de audio.
- Modo `Solo transcribir` para generar subtitulos en el idioma original.
- Seleccion de idioma de origen y destino.
- Seleccion de modelo de transcripcion (`tiny`, `base`, `small`).
- Procesamiento paralelo de multiples videos.
- Manejo mas claro de casos donde no se detecta voz util.

## Flujo de procesamiento

1. Se agrega uno o varios videos al lote.
2. La app extrae y divide el audio en fragmentos manejables.
3. `faster-whisper` realiza la transcripcion local.
4. Si el idioma destino es distinto, `Argos Translate` traduce el texto.
5. Se genera un archivo `.srt` con el mismo nombre base del video.
6. Opcionalmente se exporta un `.mp4` con subtitulos incrustados.

## Salidas generadas

- `video.mp4`
- `video.srt`
- `video.subtitulado.mp4`

## Idiomas

La transcripcion se apoya en `faster-whisper`, que admite varios idiomas de entrada.

La traduccion depende de los paquetes offline disponibles en `Argos Translate`. La interfaz contempla actualmente:

- Auto
- Ingles
- Espanol
- Frances
- Aleman
- Italiano
- Portugues

## Modelos de transcripcion

- `tiny`: mas rapido y ligero.
- `base`: equilibrio entre velocidad y precision.
- `small`: mejor precision, con mayor consumo de recursos.

## Requisitos

- Windows 10/11, macOS o Linux
- Python 3.11 o superior para ejecutar desde codigo fuente
- Conexion a internet solo para preparar modelos o paquetes offline no incluidos

## Stack tecnico

- `Python`
- `PySide6`
- `faster-whisper`
- `Argos Translate`
- `FFmpeg`
- `PyInstaller`

## Desarrollo local

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python app.py
```

## Empaquetado

Build de la aplicacion:

```powershell
python -m pip install -r requirements-build.txt
build_exe.bat
```

Build del instalador de Windows:

```powershell
build_release.bat
build_installer.bat
```

## Verificacion

Prueba de humo:

```powershell
python tests\smoke_test.py
```

Chequeo rapido de carga:

```powershell
python app.py --self-check
```

## Notas

- El build de Windows se distribuye en formato `onedir` por estabilidad.
- La app puede sembrar modelos iniciales para evitar una primera descarga en ciertos pares de idiomas.
- El rendimiento depende de la calidad del audio y de la potencia del equipo.
- Los binarios finales se generan de forma nativa en su propio sistema operativo.
