"""Standalone Windows EXE Entry Point for AniLingo (番译姬)."""

from __future__ import annotations

import ctypes
import io
import os
import sys

# 1. Guard stdout/stderr in windowless (--noconsole) EXE mode so logging/HTTP/ONNX never hit NoneType
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

# Static hints for PyInstaller module graph analysis (never executed at startup so popup stays < 0.3s)
if False:  # pragma: no cover
    import cv2  # noqa: F401
    import ctranslate2  # noqa: F401
    import faster_whisper  # noqa: F401
    import mss  # noqa: F401
    import onnxruntime  # noqa: F401
    import pyaudiowpatch  # noqa: F401
    import rapidocr  # noqa: F401

from PySide6.QtCore import Qt
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from anilingo.main_window import MainWindow

SINGLE_INSTANCE_KEY = "AniLingo_Desktop_Panel_IPC_v1"


def main() -> int:
    # Bind custom taskbar icon identity on Windows
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AniLingo.Translator.Desktop.1.0")
    except Exception:
        pass

    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("轻译")
    app.setQuitOnLastWindowClosed(True)

    # Single-instance check: if already running, wake up existing Control Panel immediately!
    probe = QLocalSocket()
    probe.connectToServer(SINGLE_INSTANCE_KEY)
    if probe.waitForConnected(220):
        probe.write(b"SHOW_PANEL")
        probe.flush()
        probe.waitForBytesWritten(200)
        probe.disconnectFromServer()
        return 0

    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    ipc_server = QLocalServer(app)
    ipc_server.listen(SINGLE_INSTANCE_KEY)

    win = MainWindow()
    win.bring_panel_to_front()

    def _on_ipc_conn() -> None:
        conn = ipc_server.nextPendingConnection()
        if conn is not None:
            conn.waitForReadyRead(150)
            _ = conn.readAll()
            conn.close()
            win.bring_panel_to_front()

    ipc_server.newConnection.connect(_on_ipc_conn)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
