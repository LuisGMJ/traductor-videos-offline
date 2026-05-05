from __future__ import annotations

import tempfile
from pathlib import Path
import sys

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from translator_app.pipeline import JobConfig, MockBackend, VideoTranslatorPipeline, run_ffmpeg


def create_test_video(target: Path) -> None:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    command = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=640x360:d=4",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=channel_layout=mono:sample_rate=16000",
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
    with tempfile.TemporaryDirectory(prefix="traducir_videos_test_", dir=local_temp_root) as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        video_path = temp_dir / "sample.mp4"
        output_dir = temp_dir / "out"

        create_test_video(video_path)
        pipeline = VideoTranslatorPipeline(backend=MockBackend())
        result = pipeline.run(
            JobConfig(
                video_path=video_path,
                output_dir=output_dir,
                make_burned_video=True,
                segment_seconds=2,
            )
        )

        assert result.subtitles_path.exists(), "No se creo el archivo SRT."
        assert result.subtitled_video_path is not None and result.subtitled_video_path.exists(), "No se creo el video subtitulado."

        srt_text = result.subtitles_path.read_text(encoding="utf-8")
        assert "Hola y bienvenidos." in srt_text
        assert "Esta es una transcripcion simulada." in srt_text

        print("Smoke test OK")


if __name__ == "__main__":
    main()
