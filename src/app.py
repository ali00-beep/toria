"""Qt-интерфейс управления голосовым ассистентом."""

import json
import os
import sys
import urllib.request
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QProcess, QPropertyAnimation, QTimer, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QDoubleSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
ENV_PATH = ROOT / ".env"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Голосовой ассистент")
        self.resize(1050, 720)
        self.config = self.load_config()
        self.env = self.load_env()
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.readyReadStandardError.connect(self.read_output)
        self.process.finished.connect(lambda: self.set_status("ждёт", "#8792a2"))
        self.status_label = QLabel("ждёт")
        self.status_dot = QLabel("●")
        self.status_animation = None
        self.build_ui()
        self.apply_style()

    @staticmethod
    def load_config():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def load_env():
        values = {}
        if ENV_PATH.exists():
            for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    key, value = line.split("=", 1)
                    values[key.strip()] = value.strip()
        return values

    def build_ui(self):
        central = QWidget()
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(18, 18, 18, 18)
        header = QHBoxLayout()
        title = QLabel("Голосовой ассистент")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.status_dot)
        header.addWidget(self.status_label)
        root_layout.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.build_home(), "Главная")
        self.tabs.addTab(self.build_settings(), "Настройки")
        self.tabs.addTab(self.build_voice(), "Голос")
        self.tabs.addTab(self.build_stt(), "Распознавание")
        root_layout.addWidget(self.tabs)
        save = QPushButton("Сохранить настройки")
        save.setObjectName("primary")
        save.clicked.connect(self.save_settings)
        root_layout.addWidget(save, alignment=Qt.AlignRight)
        self.setCentralWidget(central)

    def build_home(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        card = QFrame()
        card.setObjectName("card")
        buttons = QHBoxLayout(card)
        self.start_button = QPushButton("▶  Запустить")
        self.stop_button = QPushButton("■  Остановить")
        self.start_button.clicked.connect(self.start_assistant)
        self.stop_button.clicked.connect(self.stop_assistant)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)
        buttons.addStretch()
        buttons.addWidget(QLabel(f"Горячая клавиша: {self.config.get('hotkey', 'F9')}"))
        layout.addWidget(card)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Здесь появится журнал работы ассистента...")
        layout.addWidget(self.log)
        return page

    def build_settings(self):
        page = QWidget()
        layout = QHBoxLayout(page)
        self.dispatcher_group = self.build_model_group("Диспетчер", "dispatcher")
        self.executor_group = self.build_model_group("Исполнитель", "executor")
        layout.addWidget(self.dispatcher_group)
        layout.addWidget(self.executor_group)
        return page

    def build_model_group(self, title, section):
        group = QGroupBox(title)
        form = QFormLayout(group)
        current = self.config.get(section, {})
        prefix = section + "_"
        provider = QComboBox(); provider.addItems(["ollama", "api"])
        provider.setCurrentText("ollama" if current.get("provider") == "ollama" else "api")
        url = QLineEdit(current.get("base_url", ""))
        model = QLineEdit(current.get("model", ""))
        temperature = QDoubleSpinBox(); temperature.setRange(0, 2); temperature.setSingleStep(0.1); temperature.setValue(float(current.get("temperature", 0.2)))
        key_env = QLineEdit(current.get("api_key_env", f"{section.upper()}_API_KEY"))
        key = QLineEdit(self.env.get(key_env.text(), "")); key.setEchoMode(QLineEdit.Password)
        check = QPushButton("Проверить соединение")
        check.clicked.connect(lambda: self.check_connection(url.text(), provider.currentText(), title))
        self.__dict__[prefix + "provider"] = provider
        self.__dict__[prefix + "url"] = url
        self.__dict__[prefix + "model"] = model
        self.__dict__[prefix + "temperature"] = temperature
        self.__dict__[prefix + "key_env"] = key_env
        self.__dict__[prefix + "key"] = key
        form.addRow("Провайдер", provider); form.addRow("Адрес", url); form.addRow("Модель", model)
        form.addRow("Температура", temperature); form.addRow("Переменная ключа", key_env); form.addRow("Ключ API", key)
        form.addRow(check)
        return group

    def build_voice(self):
        page = QWidget(); form = QFormLayout(page); cfg = self.config.get("tts", {})
        self.tts_engine = QComboBox(); self.tts_engine.addItems(["edge", "windows"]); self.tts_engine.setCurrentText(cfg.get("engine", "edge"))
        self.tts_voice = QLineEdit(cfg.get("voice", "ru-RU-SvetlanaNeural")); self.tts_speed = QDoubleSpinBox(); self.tts_speed.setRange(0.5, 2); self.tts_speed.setValue(float(cfg.get("speed", 1.0)))
        test = QPushButton("Проверить голос"); test.clicked.connect(self.test_voice)
        form.addRow("Движок", self.tts_engine); form.addRow("Голос", self.tts_voice); form.addRow("Скорость", self.tts_speed); form.addRow(test)
        return page

    def build_stt(self):
        page = QWidget(); form = QFormLayout(page)
        self.whisper_model = QComboBox(); self.whisper_model.addItems(["small", "medium"]); self.whisper_model.setCurrentText(self.config.get("whisper_model", "small"))
        self.whisper_device = QComboBox(); self.whisper_device.addItems(["cuda", "cpu"]); self.whisper_device.setCurrentText(self.config.get("whisper_device", "cpu"))
        self.initial_prompt = QLineEdit(self.config.get("initial_prompt", ""))
        form.addRow("Модель Whisper", self.whisper_model); form.addRow("Устройство", self.whisper_device); form.addRow("Initial prompt", self.initial_prompt)
        return page

    def apply_style(self):
        self.setStyleSheet("""
        QWidget { background: #111827; color: #e5e7eb; font-size: 14px; }
        QMainWindow { background: #111827; }
        #title { font-size: 25px; font-weight: 700; color: #f9fafb; }
        #card, QGroupBox { background: #1f2937; border: 1px solid #374151; border-radius: 12px; padding: 12px; }
        QGroupBox { margin-top: 10px; font-weight: 700; }
        QPushButton { background: #374151; border: 0; border-radius: 8px; padding: 10px 16px; }
        QPushButton:hover { background: #4b5563; }
        #primary { background: #2563eb; font-weight: 700; }
        #primary:hover { background: #3b82f6; }
        QLineEdit, QComboBox, QDoubleSpinBox, QPlainTextEdit { background: #0b1220; border: 1px solid #4b5563; border-radius: 7px; padding: 7px; }
        QTabBar::tab { background: #1f2937; padding: 10px 16px; margin-right: 2px; }
        QTabBar::tab:selected { background: #2563eb; }
        """)

    def set_status(self, text, color):
        self.status_label.setText(text)
        self.status_dot.setStyleSheet(f"color: {color}; font-size: 20px;")
        if self.status_animation:
            self.status_animation.stop()
        self.status_animation = QPropertyAnimation(self.status_dot, b"windowOpacity", self)
        self.status_animation.setDuration(700); self.status_animation.setStartValue(0.35); self.status_animation.setEndValue(1.0)
        self.status_animation.setEasingCurve(QEasingCurve.InOutQuad); self.status_animation.start()

    def start_assistant(self):
        if self.process.state() != QProcess.NotRunning:
            return
        python_path = ROOT / ".venv" / "Scripts" / "python.exe"
        self.process.setProgram(str(python_path if python_path.exists() else sys.executable))
        self.process.setArguments(["-u", str(ROOT / "src" / "record.py")])
        environment = self.process.processEnvironment(); environment.insert("PYTHONIOENCODING", "utf-8")
        environment.insert("HOME", str(Path.home()))
        environment.insert("USERPROFILE", str(Path.home()))
        self.process.setProcessEnvironment(environment)
        self.process.start(); self.set_status("ждёт", "#22c55e"); self.append_log("Ассистент запускается...")

    def stop_assistant(self):
        if self.process.state() != QProcess.NotRunning:
            self.process.terminate()
            if not self.process.waitForFinished(1500): self.process.kill()
        self.set_status("ждёт", "#8792a2"); self.append_log("Ассистент остановлен")

    def read_output(self):
        data = self.process.readAllStandardOutput().data().decode("utf-8", errors="replace")
        if data:
            for line in data.splitlines():
                self.append_log(line)
                if "Запись..." in line: self.set_status("слушает", "#f59e0b")
                elif "Исполнитель работает" in line: self.set_status("исполнитель работает", "#a78bfa")
                elif "думает" in line or "Распознано" in line: self.set_status("думает", "#60a5fa")
                elif "Скажу:" in line or "начала звука" in line: self.set_status("говорит", "#22c55e")

    def append_log(self, text): self.log.appendPlainText(text)

    def check_connection(self, url, provider, title):
        try:
            target = url.rstrip("/").replace("/v1", "") + "/api/tags" if provider == "ollama" else url.rstrip("/") + "/models"
            with urllib.request.urlopen(target, timeout=10) as response: ok = response.status == 200
            QMessageBox.information(self, title, "Соединение OK" if ok else "Не удалось проверить соединение")
        except Exception as error: QMessageBox.warning(self, title, f"Ошибка соединения:\n{error}")

    def test_voice(self):
        from tts import SpeechManager
        SpeechManager({"engine": self.tts_engine.currentText(), "voice": self.tts_voice.text(), "speed": self.tts_speed.value()}).speak("Проверка голоса")

    def save_settings(self):
        for section in ("dispatcher", "executor"):
            prefix = section + "_"; current = self.config.setdefault(section, {})
            current.update(provider=getattr(self, prefix + "provider").currentText(), base_url=getattr(self, prefix + "url").text(), model=getattr(self, prefix + "model").text(), temperature=getattr(self, prefix + "temperature").value())
            if getattr(self, prefix + "provider").currentText() == "api":
                env_name = getattr(self, prefix + "key_env").text(); current["api_key_env"] = env_name; self.env[env_name] = getattr(self, prefix + "key").text()
        self.config["tts"] = {"engine": self.tts_engine.currentText(), "voice": self.tts_voice.text(), "speed": self.tts_speed.value()}
        self.config.update(whisper_model=self.whisper_model.currentText(), whisper_device=self.whisper_device.currentText(), initial_prompt=self.initial_prompt.text())
        CONFIG_PATH.write_text(json.dumps(self.config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        ENV_PATH.write_text("\n".join(f"{key}={value}" for key, value in self.env.items()) + "\n", encoding="utf-8")
        QMessageBox.information(self, "Настройки", "Настройки сохранены. Для применения моделей и голоса перезапустите ассистента.")

    def closeEvent(self, event): self.stop_assistant(); event.accept()


if __name__ == "__main__":
    application = QApplication(sys.argv)
    window = MainWindow(); window.show()
    sys.exit(application.exec())
