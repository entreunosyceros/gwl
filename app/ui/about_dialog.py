"""Diálogo Acerca de Gemini Workspace Local."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from app.config import (
    AVISO_LICENCIA,
    DESCRIPCION_APP,
    NOMBRE_APP,
    RUTA_LOGO,
    URL_GITHUB,
    URL_LICENCIA,
)


class AboutDialog(QDialog):
    """Muestra logo, descripción, licencia y enlace al repositorio."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Acerca de — {NOMBRE_APP}")
        self.setModal(True)
        self.setMinimumSize(460, 480)
        self.resize(480, 520)

        logo = QLabel()
        logo.setObjectName("aboutLogo")
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet(
            "QLabel#aboutLogo {"
            "  border: 3px solid #dc2626;"
            "  border-radius: 8px;"
            "  padding: 8px;"
            "  background: transparent;"
            "}"
        )
        if RUTA_LOGO.is_file():
            pixmap = QPixmap(str(RUTA_LOGO))
            if not pixmap.isNull():
                logo.setPixmap(
                    pixmap.scaled(
                        200,
                        200,
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )
                )
        else:
            logo.setText("(logo no encontrado)")

        logo_wrap = QHBoxLayout()
        logo_wrap.addStretch()
        logo_wrap.addWidget(logo)
        logo_wrap.addStretch()

        descripcion = QLabel(DESCRIPCION_APP)
        descripcion.setWordWrap(True)
        descripcion.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        descripcion.setObjectName("statusLabel")
        descripcion.setStyleSheet("font-size: 13px; line-height: 1.45;")
        descripcion.setMinimumHeight(90)

        # Aviso corto de copyright / GPL visible al usuario final.
        licencia = QLabel(AVISO_LICENCIA)
        licencia.setWordWrap(True)
        licencia.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        licencia.setObjectName("statusLabel")
        licencia.setStyleSheet("font-size: 11px; line-height: 1.4; opacity: 0.9;")

        boton_github = QPushButton("Ver en GitHub")
        boton_github.clicked.connect(self._abrir_github)

        boton_licencia = QPushButton("Licencia GPL")
        boton_licencia.setObjectName("secondaryButton")
        boton_licencia.clicked.connect(self._abrir_licencia)

        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.setObjectName("secondaryButton")
        boton_cerrar.clicked.connect(self.accept)

        botones = QHBoxLayout()
        botones.addStretch()
        botones.addWidget(boton_github)
        botones.addWidget(boton_licencia)
        botones.addWidget(boton_cerrar)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.addLayout(logo_wrap)
        layout.addWidget(descripcion)
        layout.addWidget(licencia, stretch=1)
        layout.addSpacing(4)
        layout.addLayout(botones)

    def _abrir_github(self) -> None:
        """Abre la URL del proyecto en el navegador."""
        QDesktopServices.openUrl(QUrl(URL_GITHUB))

    def _abrir_licencia(self) -> None:
        """Abre el texto oficial de la GPL-3.0."""
        QDesktopServices.openUrl(QUrl(URL_LICENCIA))
