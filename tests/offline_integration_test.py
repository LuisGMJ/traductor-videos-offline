from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from translator_app.pipeline import JobConfig, OfflineBackend, VideoTranslatorPipeline, run_ffmpeg


def create_spoken_wav(target: Path) -> None:
    text = "Hello friends. This video explains local translation."
    command = (
        "Add-Type -AssemblyName System.Speech; "
        "$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$speaker.Rate = 0; "
        f"$speaker.SetOutputToWaveFile('{target}'); "
        f"$speaker.Speak('{text}'); "
        "$speaker.Dispose();"
    )
    completed = subprocess.run(
        ["powershell", "-Command", command],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    if completed.returncode != 0 or not target.exists():
        raise RuntimeError(completed.stderr or "No se pudo crear el audio de prueba.")


def create_test_video(audio_path: Path, target: Path) -> None:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    command = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=640x360:d=6",
        "-i",
        str(audio_path),
        "-shortest",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(target),
    ]
    run_ffmpeg(command)


def main() -> None:
    local_temp_root = ROOT / ".tmp_tests"
    local_temp_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="traducir_videos_real_", dir=local_temp_root) as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        audio_path = temp_dir / "speech.wav"
        video_path = temp_dir / "sample.mp4"
        output_dir = temp_dir / "out"

        create_spoken_wav(audio_path)
        create_test_video(audio_path, video_path)

        backend = OfflineBackend(whisper_model_size="tiny")
        pipeline = VideoTranslatorPipeline(backend=backend)
        result = pipeline.run(
            JobConfig(
                video_path=video_path,
                output_dir=output_dir,
                make_burned_video=False,
                segment_seconds=30,
            )
        )

        assert result.subtitles_path.exists(), "No se creo el archivo SRT."
        srt_text = result.subtitles_path.read_text(encoding="utf-8").lower()
        print(srt_text)
        assert len(srt_text.strip()) > 0, "El SRT quedo vacio."
        expected_fragments = ("hola", "amigos", "video", "vídeo", "tradu", "local")
        assert any(fragment in srt_text for fragment in expected_fragments), "La traduccion no contiene contenido reconocible."

        print("Offline integration test OK")


if __name__ == "__main__":
    main()
