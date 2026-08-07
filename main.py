#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Gemini Workspace Local
# Copyright (C) 2026 entreunosyceros
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Punto de entrada de la aplicación de escritorio Gemini Workspace Local."""

from __future__ import annotations

import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from app.config import DIR_DATOS, NOMBRE_APP, RUTA_LOGO
from app.db.database import Database
from app.services.chat_service import ChatService
from app.ui.main_window import MainWindow


def main() -> int:
    """Inicializa BD, servicio, ventana y el bucle de eventos de Qt."""
    DIR_DATOS.mkdir(parents=True, exist_ok=True)

    app = QApplication(sys.argv)
    app.setApplicationName(NOMBRE_APP)
    app.setOrganizationName("GeminiWorkspaceLocal")
    if RUTA_LOGO.is_file():
        app.setWindowIcon(QIcon(str(RUTA_LOGO)))

    # Mantener el proceso vivo si la ventana solo se oculta en la bandeja.
    if QSystemTrayIcon.isSystemTrayAvailable():
        app.setQuitOnLastWindowClosed(False)

    bd = Database()
    bd.conectar()
    servicio = ChatService(bd)

    ventana = MainWindow(servicio)
    ventana.show()

    def _salir_por_senal(*_args) -> None:
        ventana.preparar_salida()
        app.quit()

    signal.signal(signal.SIGINT, _salir_por_senal)
    signal.signal(signal.SIGTERM, _salir_por_senal)
    # Permitir que el bucle de Qt procese a menudo los manejadores de señales de Python.
    temporizador_senal = QTimer()
    temporizador_senal.start(200)
    temporizador_senal.timeout.connect(lambda: None)

    codigo = app.exec()
    bd.cerrar()
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
