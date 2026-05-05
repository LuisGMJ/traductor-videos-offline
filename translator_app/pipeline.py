from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Protocol

import imageio_ffmpeg

APP_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", APP_ROOT))


def get_storage_root() -> Path:
    configured = os.getenv("TRADUCIR_VIDEOS_HOME")
    if configured:
        return Path(configured)
    if getattr(sys, "frozen", False):
        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "TraducirVideos"
        return Path.home() / "AppData" / "Local" / "TraducirVideos"
    return APP_ROOT


STORAGE_ROOT = get_storage_root()
if getattr(sys, "frozen", False):
    LOCAL_ROOT = STORAGE_ROOT / "local_data"
    MODELS_ROOT = STORAGE_ROOT / "models"
else:
    LOCAL_ROOT = STORAGE_ROOT / ".local"
    MODELS_ROOT = STORAGE_ROOT / ".models"
SEEDED_ARGOS_DIR = BUNDLE_ROOT / "seed_data" / "argos-translate"
SEEDED_WHISPER_DIR = BUNDLE_ROOT / "seed_data" / "whisper"

for path in (LOCAL_ROOT / "share", LOCAL_ROOT / "config", LOCAL_ROOT / "cache", MODELS_ROOT):
    path.mkdir(parents=True, exist_ok=True)

if getattr(sys, "frozen", False):
    os.environ["XDG_DATA_HOME"] = str(LOCAL_ROOT / "share")
    os.environ["XDG_CONFIG_HOME"] = str(LOCAL_ROOT / "config")
    os.environ["XDG_CACHE_HOME"] = str(LOCAL_ROOT / "cache")
else:
    os.environ.setdefault("XDG_DATA_HOME", str(LOCAL_ROOT / "share"))
    os.environ.setdefault("XDG_CONFIG_HOME", str(LOCAL_ROOT / "config"))
    os.environ.setdefault("XDG_CACHE_HOME", str(LOCAL_ROOT / "cache"))
os.environ.setdefault("ARGOS_DEVICE_TYPE", "cpu")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from argostranslate import package as argos_package  # noqa: E402
from argostranslate import translate as argos_translate  # noqa: E402
from faster_whisper import WhisperModel  # noqa: E402


LogFn = Callable[[str], None]
LANGUAGE_NAMES = {
    "auto": "Auto",
    "en": "Ingles",
    "es": "Espanol",
    "fr": "Frances",
    "de": "Aleman",
    "it": "Italiano",
    "pt": "Portugues",
}


class VoiceNotDetectedError(RuntimeError):
    """Raised when no usable speech is detected for subtitle generation."""


@dataclass(slots=True)
class SubtitleEntry:
    index: int
    start: float
    end: float
    text: str


@dataclass(slots=True)
class TranscriptionChunkResult:
    entries: list[SubtitleEntry]
    detected_language: str | None = None


class TranslationBackend(Protocol):
    def prepare(self) -> None:
        ...

    def transcribe_chunk(self, chunk_path: Path, offset_seconds: float) -> TranscriptionChunkResult:
        ...

    def translate_entries(self, entries: list[SubtitleEntry]) -> list[SubtitleEntry]:
        ...


class OfflineBackend:
    def __init__(
        self,
        log: LogFn | None = None,
        whisper_model_size: str = "tiny",
        compute_type: str = "int8",
        source_language: str = "auto",
        target_language: str = "es",
        transcribe_only: bool = False,
    ) -> None:
        self.log = log or (lambda _message: None)
        self.whisper_model_size = whisper_model_size
        self.compute_type = compute_type
        self.source_language = normalize_language_code(source_language)
        self.target_language = normalize_language_code(target_language)
        self.transcribe_only = transcribe_only
        self._whisper_model: WhisperModel | None = None
        self._translator = None
        self._detected_language: str | None = None

    def prepare(self) -> None:
        ensure_storage_dirs()
        seed_offline_assets()
        self._ensure_whisper_model()

    def transcribe_chunk(self, chunk_path: Path, offset_seconds: float) -> TranscriptionChunkResult:
        model = self._ensure_whisper_model()
        attempts = [
            {
                "language": None if self.source_language == "auto" else self.source_language,
                "vad_filter": True,
                "label": attempt_label(self.source_language, True),
            },
            {
                "language": None if self.source_language == "auto" else self.source_language,
                "vad_filter": False,
                "label": attempt_label(self.source_language, False),
            },
            {"language": None, "vad_filter": False, "label": "deteccion automatica sin filtro de voz"},
        ]

        for attempt in attempts:
            self.log(f"Probando transcripcion: {attempt['label']}...")
            segments, _info = model.transcribe(
                str(chunk_path),
                language=attempt["language"],
                vad_filter=attempt["vad_filter"],
                beam_size=5,
                condition_on_previous_text=False,
            )
            entries = segments_to_entries(segments, offset_seconds)
            detected_language = normalize_language_code(getattr(_info, "language", None))
            if entries:
                if detected_language:
                    self._detected_language = detected_language
                return TranscriptionChunkResult(entries=entries, detected_language=detected_language)

        return TranscriptionChunkResult(entries=[], detected_language=self._detected_language)

    def translate_entries(self, entries: list[SubtitleEntry]) -> list[SubtitleEntry]:
        if self.transcribe_only:
            return [
                SubtitleEntry(
                    index=item.index,
                    start=item.start,
                    end=item.end,
                    text=normalize_whitespace(item.text),
                )
                for item in entries
            ]
        translator = self._ensure_translator()
        translated: list[SubtitleEntry] = []
        for item in entries:
            translated_text = translator.translate(item.text)
            normalized_text = normalize_whitespace(translated_text)
            if self.target_language == "es":
                normalized_text = latamize_text(normalized_text)
            translated.append(
                SubtitleEntry(
                    index=item.index,
                    start=item.start,
                    end=item.end,
                    text=normalized_text,
                )
            )
        return translated

    def _ensure_whisper_model(self) -> WhisperModel:
        if self._whisper_model is None:
            whisper_dir = MODELS_ROOT / "whisper"
            whisper_dir.mkdir(parents=True, exist_ok=True)
            self.log(f"Preparando modelo de transcripcion local ({self.whisper_model_size})...")
            self._whisper_model = WhisperModel(
                self.whisper_model_size,
                device="cpu",
                compute_type=self.compute_type,
                download_root=str(whisper_dir),
            )
        return self._whisper_model

    def _ensure_translation_package(self) -> None:
        source = self.get_effective_source_language()
        target = self.target_language

        if source == target:
            return

        installed = argos_translate.get_installed_languages()
        if find_translation(installed, source, target) is not None:
            return

        self.log(
            f"Descargando paquete de traduccion offline {language_label(source)} -> {language_label(target)}..."
        )
        argos_package.update_package_index()
        installed_ok = argos_package.install_package_for_language_pair(source, target)
        if not installed_ok:
            raise RuntimeError(
                f"No hay un paquete offline disponible para traducir de {language_label(source)} a {language_label(target)}."
            )

    def _ensure_translator(self):
        if self._translator is None:
            source = self.get_effective_source_language()
            target = self.target_language
            if source == target:
                self._translator = IdentityTranslator()
                return self._translator
            self._ensure_translation_package()
            installed = argos_translate.get_installed_languages()
            translation = find_translation(installed, source, target)
            if translation is None:
                raise RuntimeError(
                    f"No se encontro el traductor offline para {language_label(source)} -> {language_label(target)}."
                )
            self._translator = translation
        return self._translator

    def get_effective_source_language(self) -> str:
        if self.source_language != "auto":
            return self.source_language
        return self._detected_language or "en"


class IdentityTranslator:
    def translate(self, text: str) -> str:
        return text


class MockBackend:
    def prepare(self) -> None:
        return

    def transcribe_chunk(self, chunk_path: Path, offset_seconds: float) -> TranscriptionChunkResult:
        duration = safe_media_duration(chunk_path, fallback=2.0)
        midpoint = min(offset_seconds + max(duration - 0.4, 0.8), offset_seconds + 1.5)
        return TranscriptionChunkResult(
            entries=[
                SubtitleEntry(index=1, start=offset_seconds, end=midpoint, text="Hello and welcome."),
                SubtitleEntry(index=2, start=midpoint, end=offset_seconds + max(duration, midpoint + 0.8), text="This is a mock transcription."),
            ],
            detected_language="en",
        )

    def translate_entries(self, entries: list[SubtitleEntry]) -> list[SubtitleEntry]:
        dictionary = {
            "Hello and welcome.": "Hola y bienvenidos.",
            "This is a mock transcription.": "Esta es una transcripcion simulada.",
        }
        return [
            SubtitleEntry(index=item.index, start=item.start, end=item.end, text=dictionary.get(item.text, item.text))
            for item in entries
        ]


@dataclass(slots=True)
class JobConfig:
    video_path: Path
    output_dir: Path
    make_burned_video: bool
    segment_seconds: int = 480
    source_language: str = "auto"
    target_language: str = "es"
    transcribe_only: bool = False


@dataclass(slots=True)
class JobResult:
    subtitles_path: Path
    subtitled_video_path: Path | None


class VideoTranslatorPipeline:
    def __init__(self, backend: TranslationBackend, log: LogFn | None = None) -> None:
        self.backend = backend
        self.log = log or (lambda _message: None)
        self.ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())

    def run(self, config: JobConfig) -> JobResult:
        config.output_dir.mkdir(parents=True, exist_ok=True)
        base_name = config.video_path.stem
        subtitles_path = config.output_dir / f"{base_name}.srt"
        subtitled_video_path = config.output_dir / f"{base_name}.subtitulado.mp4"
        temp_root = config.output_dir / ".work_tmp"
        temp_root.mkdir(parents=True, exist_ok=True)

        self.log("Preparando motores offline...")
        self.backend.prepare()

        self.log("Fragmentando audio para soportar videos grandes...")
        with tempfile.TemporaryDirectory(prefix="video_translate_", dir=temp_root) as temp_dir_raw:
            temp_dir = Path(temp_dir_raw)
            chunk_paths = self._create_audio_chunks(config.video_path, temp_dir, config.segment_seconds)
            if not chunk_paths:
                raise RuntimeError("No se pudo generar ningun fragmento de audio.")

            self.log(f"Se generaron {len(chunk_paths)} fragmentos de audio.")

            all_entries: list[SubtitleEntry] = []
            offset = 0.0
            for chunk_index, chunk_path in enumerate(chunk_paths, start=1):
                self.log(f"Transcribiendo fragmento {chunk_index}/{len(chunk_paths)}...")
                transcribed = self.backend.transcribe_chunk(chunk_path, offset)
                all_entries.extend(transcribed.entries)
                offset += safe_media_duration(chunk_path, fallback=float(config.segment_seconds))

            if not all_entries:
                raise VoiceNotDetectedError(
                    "No se detecto voz util para subtitular en ese video. "
                    "Puede ser un clip sin dialogo, con solo musica/efectos, audio muy bajo o voz poco clara."
                )

            target_label = language_label(config.target_language)
            if config.transcribe_only:
                self.log("Generando subtitulos en idioma original...")
            elif normalize_language_code(config.target_language) == "es":
                self.log("Traduciendo subtitulos a espanol latino...")
            else:
                self.log(f"Traduciendo subtitulos a {target_label.lower()}...")
            translated_entries = self.backend.translate_entries(reindex_entries(all_entries))

            self.log("Escribiendo archivo SRT...")
            write_srt(subtitles_path, translated_entries)

            video_output: Path | None = None
            if config.make_burned_video:
                self.log("Generando video con subtitulos quemados...")
                self._burn_subtitles(config.video_path, subtitles_path, subtitled_video_path)
                video_output = subtitled_video_path

        self.log("Proceso completado.")
        return JobResult(subtitles_path=subtitles_path, subtitled_video_path=video_output)

    def _create_audio_chunks(self, video_path: Path, temp_dir: Path, segment_seconds: int) -> list[Path]:
        output_pattern = temp_dir / "chunk_%04d.mp3"
        command = [
            str(self.ffmpeg),
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "48k",
            "-f",
            "segment",
            "-segment_time",
            str(segment_seconds),
            "-reset_timestamps",
            "1",
            str(output_pattern),
        ]
        run_ffmpeg(command)
        return [path for path in sorted(temp_dir.glob("chunk_*.mp3")) if path.stat().st_size > 1024]

    def _burn_subtitles(self, video_path: Path, subtitles_path: Path, output_path: Path) -> None:
        subtitles_filter = format_subtitles_filter_filename(subtitles_path.name)
        command = [
            str(self.ffmpeg),
            "-y",
            "-i",
            str(video_path),
            "-vf",
            f"subtitles=filename='{subtitles_filter}'",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(output_path),
        ]
        run_ffmpeg(command, cwd=subtitles_path.parent)


def ensure_storage_dirs() -> None:
    (LOCAL_ROOT / "share").mkdir(parents=True, exist_ok=True)
    (LOCAL_ROOT / "config").mkdir(parents=True, exist_ok=True)
    (LOCAL_ROOT / "cache").mkdir(parents=True, exist_ok=True)
    MODELS_ROOT.mkdir(parents=True, exist_ok=True)


def seed_offline_assets() -> None:
    copy_seed_dir(SEEDED_ARGOS_DIR, LOCAL_ROOT / "share" / "argos-translate")
    copy_seed_dir(SEEDED_WHISPER_DIR, MODELS_ROOT / "whisper")


def copy_seed_dir(source: Path, target: Path) -> None:
    if not source.exists() or target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)


def find_translation(languages, from_code: str, to_code: str):
    from_language = next((lang for lang in languages if lang.code == from_code), None)
    to_language = next((lang for lang in languages if lang.code == to_code), None)
    if from_language is None or to_language is None:
        return None
    return from_language.get_translation(to_language)


def latamize_text(text: str) -> str:
    replacements = {
        "vosotros": "ustedes",
        "Vosotros": "Ustedes",
        "ordenador": "computadora",
        "Ordenador": "Computadora",
        "movil": "celular",
        "Movil": "Celular",
        "coche": "auto",
        "Coche": "Auto",
        "vale": "esta bien",
        "Vale": "Esta bien",
    }
    result = text
    for source, target in replacements.items():
        result = result.replace(source, target)
    return result


def run_ffmpeg(command: list[str], cwd: Path | None = None) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, cwd=str(cwd) if cwd else None)
    if completed.returncode != 0:
        raise RuntimeError(clean_ffmpeg_error(completed.stderr))


def clean_ffmpeg_error(stderr: str) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    tail = lines[-12:]
    return "\n".join(tail) or "ffmpeg fallo sin mensaje de error."


def get_media_duration(path: Path) -> float:
    completed = subprocess.run(
        [str(Path(imageio_ffmpeg.get_ffmpeg_exe())), "-i", str(path), "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    combined = f"{completed.stdout}\n{completed.stderr}"
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", combined)
    if not match:
        raise RuntimeError(f"No se pudo leer la duracion de {path.name}.")
    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = float(match.group(3))
    return hours * 3600 + minutes * 60 + seconds


def safe_media_duration(path: Path, fallback: float) -> float:
    try:
        return get_media_duration(path)
    except RuntimeError:
        return fallback


def normalize_whitespace(text: str) -> str:
    return " ".join(text.replace("\r", " ").replace("\n", " ").split()).strip()


def normalize_language_code(code: str | None) -> str:
    if not code:
        return "auto"
    normalized = code.strip().lower()
    aliases = {
        "english": "en",
        "spanish": "es",
        "espanol": "es",
        "español": "es",
        "french": "fr",
        "german": "de",
        "deutsch": "de",
        "italian": "it",
        "portuguese": "pt",
    }
    return aliases.get(normalized, normalized)


def language_label(code: str) -> str:
    normalized = normalize_language_code(code)
    return LANGUAGE_NAMES.get(normalized, normalized.upper())


def attempt_label(source_language: str, vad_filter: bool) -> str:
    source = normalize_language_code(source_language)
    if source == "auto":
        base = "deteccion automatica"
    else:
        base = f"voz en {language_label(source).lower()}"
    suffix = "con filtro de voz" if vad_filter else "sin filtro de voz"
    return f"{base} {suffix}"


def segments_to_entries(segments: Iterable[object], offset_seconds: float) -> list[SubtitleEntry]:
    entries: list[SubtitleEntry] = []
    for idx, segment in enumerate(segments, start=1):
        text = normalize_whitespace(getattr(segment, "text", ""))
        if not is_useful_subtitle_text(text):
            continue
        start = float(getattr(segment, "start", 0.0)) + offset_seconds
        end = float(getattr(segment, "end", start + 1.0)) + offset_seconds
        if end <= start:
            end = start + 1.0
        entries.append(SubtitleEntry(index=idx, start=start, end=end, text=text))
    return entries


def is_useful_subtitle_text(text: str) -> bool:
    if not text:
        return False
    lowered = text.strip().lower()
    blocked = {
        "[music]",
        "[applause]",
        "[laughter]",
        "[noise]",
        "[silence]",
        "...",
    }
    return lowered not in blocked


def reindex_entries(entries: Iterable[SubtitleEntry]) -> list[SubtitleEntry]:
    return [
        SubtitleEntry(index=index, start=item.start, end=item.end, text=item.text)
        for index, item in enumerate(entries, start=1)
    ]


def format_timestamp(seconds: float) -> str:
    total_milliseconds = max(0, int(round(seconds * 1000)))
    hours = total_milliseconds // 3_600_000
    minutes = (total_milliseconds % 3_600_000) // 60_000
    secs = (total_milliseconds % 60_000) // 1000
    milliseconds = total_milliseconds % 1000
    return f"{hours:02}:{minutes:02}:{secs:02},{milliseconds:03}"


def write_srt(path: Path, entries: list[SubtitleEntry]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for index, entry in enumerate(entries, start=1):
            handle.write(f"{index}\n")
            handle.write(f"{format_timestamp(entry.start)} --> {format_timestamp(entry.end)}\n")
            handle.write(f"{entry.text}\n\n")


def format_subtitles_filter_filename(filename: str) -> str:
    return filename.replace("\\", "/").replace("'", r"\'").replace("[", "\\[").replace("]", "\\]").replace(",", "\\,")
