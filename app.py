from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
import sys

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSplitter,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from translator_app.pipeline import JobConfig, OfflineBackend, VideoTranslatorPipeline, VoiceNotDetectedError
from translator_app import __version__


LANGUAGE_OPTIONS = [
    ("Auto", "auto"),
    ("Ingles", "en"),
    ("Espanol", "es"),
    ("Frances", "fr"),
    ("Aleman", "de"),
    ("Italiano", "it"),
    ("Portugues", "pt"),
]

PHASE_LABELS = {
    "Preparando motores offline...": "Preparando motor",
    "Fragmentando audio para soportar videos grandes...": "Separando audio",
    "Generando subtitulos en idioma original...": "Transcribiendo",
    "Escribiendo archivo SRT...": "Guardando SRT",
    "Generando video con subtitulos quemados...": "Renderizando video",
    "Proceso completado.": "Completado",
}

APP_STYLESHEET = """
QWidget {
    background: #f3eee7;
    color: #1b2230;
    font-family: "Segoe UI Variable Text", "Segoe UI", "SF Pro Text", sans-serif;
    font-size: 14px;
}
QMainWindow {
    background: #eee7dd;
}
QFrame#Card {
    background: #fffaf4;
    border: 1px solid #dfd2c3;
    border-radius: 22px;
}
QLabel#SectionTitle {
    font-size: 18px;
    font-weight: 700;
    color: #1c2430;
}
QLabel#SectionHint {
    color: #6a7381;
    font-size: 13px;
}
QLabel#FieldLabel {
    color: #46515e;
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
}
QLabel#ToneNotice {
    background: #fff5ea;
    border: 1px solid #efcfb5;
    border-radius: 14px;
    color: #8a532d;
    padding: 9px 12px;
}
QLabel#StatusPill {
    background: #fff6ec;
    color: #8a532d;
    border: 1px solid #e7c5a9;
    border-radius: 14px;
    padding: 8px 12px;
    font-weight: 600;
}
QLineEdit, QComboBox, QListWidget, QPlainTextEdit {
    background: #fffdf9;
    border: 1px solid #d8cdbd;
    border-radius: 16px;
    padding: 10px 12px;
    selection-background-color: #1b506f;
    selection-color: white;
}
QLineEdit:focus, QComboBox:focus, QListWidget:focus, QPlainTextEdit:focus {
    border: 2px solid #c56f3d;
}
QListWidget {
    padding: 8px;
}
QListWidget::item {
    padding: 11px 12px;
    margin: 4px 0;
    border-radius: 12px;
}
QListWidget::item:selected {
    background: #1d4c68;
    color: white;
}
QPlainTextEdit {
    background: #f8f1e7;
    border-radius: 18px;
}
QPushButton {
    border: none;
    border-radius: 16px;
    padding: 11px 16px;
    font-weight: 600;
}
QPushButton#PrimaryButton {
    background: #c56f3d;
    color: white;
}
QPushButton#PrimaryButton:hover {
    background: #af6133;
}
QPushButton#SecondaryButton {
    background: #dde7ef;
    color: #1c2430;
}
QPushButton#SecondaryButton:hover {
    background: #cfdee8;
}
QPushButton:disabled {
    background: #ddd5cb;
    color: #8f877f;
}
QCheckBox {
    spacing: 10px;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 6px;
    border: 1px solid #c56f3d;
    background: #fffaf3;
}
QCheckBox::indicator:checked {
    background: #c56f3d;
}
QSplitter::handle {
    background: transparent;
}
"""


@dataclass(slots=True)
class BatchResult:
    video_path: Path
    subtitle_name: str
    subtitled_video: str | None


@dataclass(slots=True)
class BatchIssue:
    video_name: str
    message: str
    severity: str


class BatchWorker(QThread):
    log = Signal(str)
    finished_batch = Signal(list, list)

    def __init__(self, configs: list[JobConfig], parallel_jobs: int, whisper_model_size: str) -> None:
        super().__init__()
        self.configs = configs
        self.parallel_jobs = parallel_jobs
        self.whisper_model_size = whisper_model_size

    def run(self) -> None:
        results: list[BatchResult] = []
        issues: list[BatchIssue] = []
        max_workers = min(max(self.parallel_jobs, 1), len(self.configs))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(self._process_single_video, config): config
                for config in self.configs
            }
            for future in as_completed(future_map):
                config = future_map[future]
                try:
                    results.append(future.result())
                except VoiceNotDetectedError as exc:
                    issues.append(BatchIssue(config.video_path.name, str(exc), "warning"))
                except Exception as exc:  # noqa: BLE001
                    issues.append(BatchIssue(config.video_path.name, str(exc), "error"))

        self.finished_batch.emit(results, issues)

    def _process_single_video(self, config: JobConfig) -> BatchResult:
        video_name = config.video_path.name
        logger = lambda message, name=video_name: self.log.emit(f"[{name}] {message}")
        backend = OfflineBackend(
            log=logger,
            whisper_model_size=self.whisper_model_size,
            source_language=config.source_language,
            target_language=config.target_language,
            transcribe_only=config.transcribe_only,
        )
        pipeline = VideoTranslatorPipeline(backend=backend, log=logger)
        result = pipeline.run(config)
        return BatchResult(
            video_path=config.video_path,
            subtitle_name=result.subtitles_path.name,
            subtitled_video=result.subtitled_video_path.name if result.subtitled_video_path else None,
        )


class PrepareWorker(QThread):
    log = Signal(str)
    ready = Signal()
    failed = Signal(str)

    def __init__(self, whisper_model_size: str) -> None:
        super().__init__()
        self.whisper_model_size = whisper_model_size

    def run(self) -> None:
        try:
            backend = OfflineBackend(log=self.log.emit, whisper_model_size=self.whisper_model_size)
            backend.prepare()
            self.ready.emit()
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class VideoBatchWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Traductor de Videos Offline v{__version__}")
        self.resize(1200, 800)
        self.setMinimumSize(940, 680)

        self.video_paths: list[Path] = []
        self.video_status_items: dict[str, QListWidgetItem] = {}
        self.batch_worker: BatchWorker | None = None
        self.prepare_worker: PrepareWorker | None = None

        self.setStyleSheet(APP_STYLESHEET)
        self._build_ui()
        self._refresh_summary()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(22, 22, 22, 22)
        root.setSpacing(18)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        left_host = QWidget()
        left_layout = QVBoxLayout(left_host)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(18)
        left_layout.addWidget(self._build_library_card(), 1)

        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(18)
        right_layout.addWidget(self._build_progress_card())
        right_layout.addWidget(self._build_config_card(), 2)
        right_layout.addWidget(self._build_log_card(), 1)

        right_host = QScrollArea()
        right_host.setWidgetResizable(True)
        right_host.setFrameShape(QFrame.Shape.NoFrame)
        right_host.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_host.setWidget(right_container)

        splitter.addWidget(left_host)
        splitter.addWidget(right_host)
        splitter.setStretchFactor(0, 12)
        splitter.setStretchFactor(1, 10)
        splitter.setOpaqueResize(True)
        splitter.setSizes([700, 560])

    def _build_library_card(self) -> QFrame:
        frame = self._make_card()
        layout = self._card_layout(frame)
        layout.addWidget(self._section_title("Biblioteca del lote", "Agrega uno o varios videos al procesamiento."))

        self.video_list = QListWidget()
        self.video_list.setMinimumHeight(340)
        self.video_list.itemSelectionChanged.connect(self._refresh_summary)
        layout.addWidget(self.video_list, 1)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.add_button = self._make_button("Agregar videos", primary=True, icon_type=QStyle.StandardPixmap.SP_DialogOpenButton, callback=self.add_videos)
        self.remove_button = self._make_button("Quitar seleccion", icon_type=QStyle.StandardPixmap.SP_TrashIcon, callback=self.remove_selected_videos)
        self.clear_button = self._make_button("Limpiar lista", icon_type=QStyle.StandardPixmap.SP_DialogResetButton, callback=self.clear_videos)
        actions.addWidget(self.add_button)
        actions.addWidget(self.remove_button)
        actions.addWidget(self.clear_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        return frame

    def _build_progress_card(self) -> QFrame:
        frame = self._make_card()
        frame.setMinimumHeight(240)
        frame.setMaximumHeight(320)
        layout = self._card_layout(frame)
        layout.addWidget(self._section_title("Progreso por video", "Estados claros sin depender solo de la bitacora tecnica."))

        self.progress_list = QListWidget()
        self.progress_list.setMinimumHeight(160)
        layout.addWidget(self.progress_list)
        return frame

    def _build_config_card(self) -> QFrame:
        frame = self._make_card()
        frame.setMinimumHeight(460)
        layout = self._card_layout(frame)
        layout.addWidget(self._section_title("Configuracion", "El subtitulo se guarda con el mismo nombre base del video."))

        layout.addWidget(self._field_label("Carpeta de salida opcional"))
        output_row = QHBoxLayout()
        output_row.setSpacing(10)
        self.output_input = QLineEdit()
        self.output_input.setMinimumHeight(42)
        self.output_input.setPlaceholderText("Usar la carpeta original de cada video")
        self.output_input.textChanged.connect(self._refresh_summary)
        self.output_button = self._make_button("Elegir carpeta", icon_type=QStyle.StandardPixmap.SP_DirOpenIcon, callback=self.select_output_dir)
        self.output_button.setMinimumHeight(42)
        output_row.addWidget(self.output_input, 1)
        output_row.addWidget(self.output_button)
        layout.addLayout(output_row)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(2, 1)
        grid.setRowMinimumHeight(1, 44)
        grid.setRowMinimumHeight(3, 44)

        self.source_combo = QComboBox()
        self.target_combo = QComboBox()
        for label, code in LANGUAGE_OPTIONS:
            self.source_combo.addItem(label, code)
            self.target_combo.addItem(label, code)
        self.target_combo.setCurrentIndex(next(index for index, option in enumerate(LANGUAGE_OPTIONS) if option[1] == "es"))
        self.model_combo = QComboBox()
        self.model_combo.addItems(["tiny", "base", "small"])
        self.segment_input = QLineEdit("480")
        self.parallel_combo = QComboBox()
        self.parallel_combo.addItems(["1", "2", "3"])
        self.parallel_combo.setCurrentText("2")
        for widget in (
            self.source_combo,
            self.target_combo,
            self.model_combo,
            self.segment_input,
            self.parallel_combo,
        ):
            widget.setMinimumHeight(42)
        self.parallel_combo.currentTextChanged.connect(self._refresh_summary)
        self.source_combo.currentIndexChanged.connect(self._refresh_summary)
        self.target_combo.currentIndexChanged.connect(self._refresh_summary)

        grid.addWidget(self._field_label("Origen"), 0, 0)
        grid.addWidget(self._field_label("Destino"), 0, 1)
        grid.addWidget(self._field_label("Modelo"), 0, 2)
        grid.addWidget(self.source_combo, 1, 0)
        grid.addWidget(self.target_combo, 1, 1)
        grid.addWidget(self.model_combo, 1, 2)
        grid.addWidget(self._field_label("Segmento (s)"), 2, 0)
        grid.addWidget(self._field_label("Procesos"), 2, 1)
        grid.addWidget(self._field_label("Salida"), 2, 2)
        grid.addWidget(self.segment_input, 3, 0)
        grid.addWidget(self.parallel_combo, 3, 1)
        self.output_mode_label = QLabel("SRT")
        self.output_mode_label.setObjectName("ToneNotice")
        self.output_mode_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.output_mode_label.setMinimumWidth(90)
        self.output_mode_label.setMinimumHeight(42)
        grid.addWidget(self.output_mode_label, 3, 2)
        layout.addLayout(grid)

        self.transcribe_only_checkbox = QCheckBox("Solo transcribir (subtitulos en idioma original)")
        self.transcribe_only_checkbox.toggled.connect(self._refresh_summary)
        layout.addWidget(self.transcribe_only_checkbox)

        self.burned_checkbox = QCheckBox("Generar tambien video con subtitulos quemados")
        self.burned_checkbox.toggled.connect(self._refresh_summary)
        layout.addWidget(self.burned_checkbox)

        self.output_hint = QLabel("Selecciona videos para ver un ejemplo de salida.")
        self.output_hint.setObjectName("SectionHint")
        self.output_hint.setWordWrap(True)
        layout.addWidget(self.output_hint)

        actions = QGridLayout()
        actions.setHorizontalSpacing(10)
        actions.setVerticalSpacing(10)
        self.prepare_button = self._make_button("Preparar modelos", icon_type=QStyle.StandardPixmap.SP_BrowserReload, callback=self.prepare_models)
        self.start_button = self._make_button("Traducir lote", primary=True, icon_type=QStyle.StandardPixmap.SP_MediaPlay, callback=self.start_batch)
        self.prepare_button.setMinimumHeight(44)
        self.start_button.setMinimumHeight(44)
        self.status_pill = QLabel("Listo para procesar")
        self.status_pill.setObjectName("StatusPill")
        self.status_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_pill.setWordWrap(True)
        self.status_pill.setMinimumHeight(54)
        actions.addWidget(self.prepare_button, 0, 0)
        actions.addWidget(self.start_button, 0, 1)
        actions.addWidget(self.status_pill, 1, 0, 1, 2)
        actions.setColumnStretch(0, 1)
        actions.setColumnStretch(1, 1)
        layout.addLayout(actions)
        return frame

    def _build_log_card(self) -> QFrame:
        frame = self._make_card()
        frame.setMinimumHeight(220)
        layout = self._card_layout(frame)
        layout.addWidget(self._section_title("Bitacora", "Detalle tecnico por si quieres revisar cada fase del lote."))
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        layout.addWidget(self.log_output, 1)
        return frame

    def _make_card(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Card")
        return frame

    def _card_layout(self, frame: QFrame) -> QVBoxLayout:
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)
        return layout

    def _section_title(self, title_text: str, hint_text: str) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        title = QLabel(title_text)
        title.setObjectName("SectionTitle")
        hint = QLabel(hint_text)
        hint.setObjectName("SectionHint")
        hint.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(hint)
        return wrapper

    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        return label

    def _make_button(self, text: str, primary: bool = False, icon_type: QStyle.StandardPixmap | None = None, callback=None) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("PrimaryButton" if primary else "SecondaryButton")
        if icon_type is not None:
            button.setIcon(self.style().standardIcon(icon_type))
        if callback:
            button.clicked.connect(callback)
        return button

    def append_log(self, message: str) -> None:
        self.log_output.appendPlainText(message)
        scrollbar = self.log_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        self.status_pill.setText(message[:78] if len(message) > 78 else message)
        self._consume_progress_message(message)

    def _compact_status(self, message: str) -> str:
        if "Lote finalizado" in message:
            return "Finalizado"
        if "Preparando" in message:
            return "Preparando"
        if "Transcribiendo" in message:
            return "Transcribiendo"
        if "Traduciendo" in message:
            return "Traduciendo"
        if "Sin voz clara" in message or "No se detecto voz util" in message:
            return "Sin voz clara"
        return "Activo"

    def add_videos(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Selecciona uno o varios videos",
            "",
            "Videos (*.mp4 *.mkv *.mov *.avi *.webm);;Todos (*.*)",
        )
        if not paths:
            return

        for raw_path in paths:
            path = Path(raw_path)
            if path in self.video_paths:
                continue
            self.video_paths.append(path)
            item = QListWidgetItem(str(path))
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.video_list.addItem(item)
            self._set_progress_status(path.name, "En espera")

        self._refresh_summary()

    def remove_selected_videos(self) -> None:
        for item in self.video_list.selectedItems():
            path = item.data(Qt.ItemDataRole.UserRole)
            if path in self.video_paths:
                self.video_paths.remove(path)
            self.video_list.takeItem(self.video_list.row(item))
            progress_item = self.video_status_items.pop(path.name, None)
            if progress_item:
                self.progress_list.takeItem(self.progress_list.row(progress_item))
        self._refresh_summary()

    def clear_videos(self) -> None:
        self.video_paths.clear()
        self.video_list.clear()
        self.progress_list.clear()
        self.video_status_items.clear()
        self._refresh_summary()

    def select_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Selecciona la carpeta de salida")
        if path:
            self.output_input.setText(path)

    def _refresh_summary(self) -> None:
        transcribe_only = self.transcribe_only_checkbox.isChecked()
        source_code = self.source_combo.currentData()
        target_code = self.target_combo.currentData()
        self.target_combo.setEnabled(not transcribe_only)
        self.output_mode_label.setText("SRT + MP4" if self.burned_checkbox.isChecked() else "SRT")
        self.burned_checkbox.setText(
            f"Generar tambien video con subtitulos quemados ({self._language_name(source_code if transcribe_only else target_code)})"
        )
        if not self.video_paths:
            self.output_hint.setText("Selecciona videos para ver un ejemplo de salida.")
            return

        selected = self.video_list.currentItem()
        sample = selected.data(Qt.ItemDataRole.UserRole) if selected else self.video_paths[0]
        output_override = self.output_input.text().strip()
        output_folder = Path(output_override) if output_override else sample.parent
        source_name = self._language_name(source_code)
        target_name = source_name if transcribe_only else self._language_name(target_code)
        self.output_hint.setText(
            f"Ejemplo de salida: {output_folder / (sample.stem + '.srt')} | {source_name} -> {target_name}"
        )

    def set_busy(self, busy: bool) -> None:
        enabled = not busy
        for widget in (
            self.add_button,
            self.remove_button,
            self.clear_button,
            self.output_input,
            self.output_button,
            self.source_combo,
            self.target_combo,
            self.model_combo,
            self.segment_input,
            self.parallel_combo,
            self.transcribe_only_checkbox,
            self.burned_checkbox,
            self.prepare_button,
            self.start_button,
        ):
            widget.setEnabled(enabled)

    def _language_name(self, code: str) -> str:
        for label, value in LANGUAGE_OPTIONS:
            if value == code:
                return label
        return str(code).upper()

    def prepare_models(self) -> None:
        if self.prepare_worker and self.prepare_worker.isRunning():
            return
        self.set_busy(True)
        self.append_log("Preparando modelos offline...")
        self.prepare_worker = PrepareWorker(self.model_combo.currentText())
        self.prepare_worker.log.connect(self.append_log)
        self.prepare_worker.ready.connect(self._prepare_finished)
        self.prepare_worker.failed.connect(self._show_error)
        self.prepare_worker.start()

    def _prepare_finished(self) -> None:
        self.set_busy(False)
        self.append_log("Modelos offline listos.")
        QMessageBox.information(
            self,
            "Listo",
            "El modelo offline principal ya quedo preparado. Los paquetes de traduccion extra se descargan cuando el par de idiomas lo necesite.",
        )
        self._refresh_summary()

    def start_batch(self) -> None:
        if not self.video_paths:
            QMessageBox.critical(self, "Videos faltantes", "Agrega al menos un video.")
            return

        try:
            segment_seconds = int(self.segment_input.text().strip())
            parallel_jobs = int(self.parallel_combo.currentText())
            if segment_seconds <= 0 or parallel_jobs <= 0:
                raise ValueError
        except ValueError:
            QMessageBox.critical(self, "Valor invalido", "Segmento y procesos deben ser enteros positivos.")
            return

        source_language = self.source_combo.currentData()
        target_language = self.target_combo.currentData()
        transcribe_only = self.transcribe_only_checkbox.isChecked()

        configs: list[JobConfig] = []
        output_override = self.output_input.text().strip()
        for video in self.video_paths:
            if not video.exists():
                QMessageBox.critical(self, "Video faltante", f"No existe:\n{video}")
                return
            output_dir = Path(output_override) if output_override else video.parent
            configs.append(
                JobConfig(
                    video_path=video,
                    output_dir=output_dir,
                    make_burned_video=self.burned_checkbox.isChecked(),
                    segment_seconds=segment_seconds,
                    source_language=source_language,
                    target_language=target_language,
                    transcribe_only=transcribe_only,
                )
            )
            self._set_progress_status(video.name, "En cola")

        self.log_output.clear()
        self.append_log(f"Preparando lote de {len(configs)} video(s)...")
        self.set_busy(True)

        self.batch_worker = BatchWorker(configs, parallel_jobs, self.model_combo.currentText())
        self.batch_worker.log.connect(self.append_log)
        self.batch_worker.finished_batch.connect(self._batch_finished)
        self.batch_worker.start()

    def _batch_finished(self, results: list[BatchResult], issues: list[BatchIssue]) -> None:
        self.set_busy(False)
        self.append_log("Lote finalizado.")

        warnings = [item for item in issues if item.severity == "warning"]
        errors = [item for item in issues if item.severity == "error"]

        for item in results:
            self._set_progress_status(item.video_path.name, "Completado")
        for item in warnings:
            self._set_progress_status(item.video_name, "Sin voz clara")
        for item in errors:
            self._set_progress_status(item.video_name, "Error real")

        lines: list[str] = []
        if results:
            lines.append(f"Completados: {len(results)}")
            for item in results[:6]:
                lines.append(f"- {item.video_path.name} -> {item.subtitle_name}")
        if warnings:
            lines.append(f"Sin voz clara: {len(warnings)}")
            for item in warnings[:4]:
                lines.append(f"- {item.video_name}: {item.message}")
        if errors:
            lines.append(f"Errores reales: {len(errors)}")
            for item in errors[:4]:
                lines.append(f"- {item.video_name}: {item.message}")

        message = "\n".join(lines) if lines else "No hubo resultados."
        if errors:
            QMessageBox.warning(self, "Lote finalizado con avisos", message)
        elif warnings:
            QMessageBox.information(self, "Lote finalizado", message)
        else:
            QMessageBox.information(self, "Lote completado", message)

    def _show_error(self, message: str) -> None:
        self.set_busy(False)
        self.append_log("Ocurrio un error.")
        QMessageBox.critical(self, "Error", message)

    def _consume_progress_message(self, message: str) -> None:
        if not message.startswith("[") or "]" not in message:
            return
        video_name, raw_status = message[1:].split("]", 1)
        status_text = raw_status.strip()
        compact = PHASE_LABELS.get(status_text)
        if compact is None and status_text.startswith("Traduciendo subtitulos a "):
            compact = "Traduciendo"
        if compact is None and status_text.startswith("Transcribiendo fragmento"):
            compact = status_text
        if compact is None and status_text.startswith("Probando transcripcion:"):
            compact = "Buscando voz"
        if compact is None and status_text.startswith("Se generaron "):
            compact = "Audio dividido"
        if compact is None:
            return
        self._set_progress_status(video_name, compact)

    def _set_progress_status(self, video_name: str, status: str) -> None:
        item = self.video_status_items.get(video_name)
        if item is None:
            item = QListWidgetItem()
            self.video_status_items[video_name] = item
            self.progress_list.addItem(item)
        item.setText(f"{video_name}\n{status}")
        item.setIcon(self._status_icon(status))
        item.setToolTip(f"{video_name}\nEstado: {status}")

    def _status_icon(self, status: str):
        style = self.style()
        lowered = status.lower()
        if "completado" in lowered:
            return style.standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
        if "error" in lowered:
            return style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxCritical)
        if "sin voz" in lowered:
            return style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
        if "cola" in lowered or "espera" in lowered:
            return style.standardIcon(QStyle.StandardPixmap.SP_MediaPause)
        return style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload)


def run_self_check() -> int:
    backend = OfflineBackend(whisper_model_size="tiny")
    backend.prepare()
    print("self_check_ok")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-check", action="store_true", help="Prepara modelos y valida que la app carga bien.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_check:
        return run_self_check()

    app = QApplication(sys.argv)
    app.setApplicationName("TraductorVideos")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI Variable Text", 10))
    window = VideoBatchWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
