"""Diálogo para configurar la API key de Gemini, el modelo, el tema y las instrucciones."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from app.config import (
    INSTRUCCION_GENERAL_POR_DEFECTO,
    MAX_CARACTERES_INSTRUCCION_SISTEMA,
    MAX_CARACTERES_NOMBRE_ASISTENTE,
    MODELOS_GRATUITOS,
    NOMBRE_ASISTENTE_POR_DEFECTO,
    URL_CLAVE_API,
)
from app.ui.theme import TEMAS


class SettingsDialog(QDialog):
    """Formulario modal de API key, modelo, tema e instrucciones generales."""

    def __init__(
        self,
        parent=None,
        *,
        api_key: str = "",
        model: str = "",
        theme: str = "dark",
        system_instruction: str = "",
        assistant_name: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configuración")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setMinimumHeight(600)
        self.resize(560, 660)

        titulo = QLabel("Configuración")
        titulo.setObjectName("dialogTitle")

        etiqueta_ayuda = QLabel(
            "Necesitas una API key gratuita de Google AI Studio "
            "para chatear con Gemini. Puedes personalizar las instrucciones "
            "generales que Gemini recibe en cada respuesta."
        )
        etiqueta_ayuda.setWordWrap(True)

        self.etiqueta_enlace = QLabel(
            f'<a href="{URL_CLAVE_API}">Obtener API key en Google AI Studio</a>'
        )
        self.etiqueta_enlace.setObjectName("linkLabel")
        self.etiqueta_enlace.setOpenExternalLinks(False)
        self.etiqueta_enlace.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.etiqueta_enlace.linkActivated.connect(self._abrir_pagina_clave_api)

        boton_abrir = QPushButton("Abrir página de API key")
        boton_abrir.setObjectName("secondaryButton")
        boton_abrir.clicked.connect(self._abrir_pagina_clave_api)

        fila_enlace = QHBoxLayout()
        fila_enlace.addWidget(self.etiqueta_enlace)
        fila_enlace.addStretch()
        fila_enlace.addWidget(boton_abrir)

        self.edit_clave_api = QLineEdit(api_key)
        self.edit_clave_api.setEchoMode(QLineEdit.Password)
        self.edit_clave_api.setPlaceholderText("Pega aquí tu API key…")

        self.mostrar_clave = QCheckBox("Mostrar API key")
        self.mostrar_clave.toggled.connect(self._alternar_visibilidad_clave)

        self.combo_modelo = QComboBox()
        indice_modelo = 0
        for i, (etiqueta, valor) in enumerate(MODELOS_GRATUITOS):
            self.combo_modelo.addItem(etiqueta, valor)
            if valor == model:
                indice_modelo = i
        self.combo_modelo.setCurrentIndex(indice_modelo)

        self.combo_tema = QComboBox()
        indice_tema = 0
        for i, (etiqueta, valor) in enumerate(TEMAS):
            self.combo_tema.addItem(etiqueta, valor)
            if valor == theme:
                indice_tema = i
        self.combo_tema.setCurrentIndex(indice_tema)

        self.edit_nombre_asistente = QLineEdit(
            (assistant_name or "").strip() or NOMBRE_ASISTENTE_POR_DEFECTO
        )
        self.edit_nombre_asistente.setPlaceholderText(NOMBRE_ASISTENTE_POR_DEFECTO)
        self.edit_nombre_asistente.setMaxLength(MAX_CARACTERES_NOMBRE_ASISTENTE)

        texto_inicial = (system_instruction or "").strip() or INSTRUCCION_GENERAL_POR_DEFECTO
        self.edit_instrucciones = QPlainTextEdit()
        self.edit_instrucciones.setPlainText(texto_inicial)
        self.edit_instrucciones.setPlaceholderText(
            "Instrucciones generales para Gemini…"
        )
        self.edit_instrucciones.setMinimumHeight(160)

        etiqueta_instrucciones = QLabel(
            "Instrucciones generales para Gemini (personalidad, tono, reglas…). "
            "La app añade automáticamente las reglas de cascada PDF → memoria → Gemini."
        )
        etiqueta_instrucciones.setWordWrap(True)
        etiqueta_instrucciones.setObjectName("statusLabel")

        boton_restaurar = QPushButton("Restaurar instrucciones predeterminadas")
        boton_restaurar.setObjectName("secondaryButton")
        boton_restaurar.clicked.connect(self._restaurar_instrucciones)

        formulario = QFormLayout()
        formulario.addRow("API key:", self.edit_clave_api)
        formulario.addRow("", self.mostrar_clave)
        formulario.addRow("Modelo (gratis):", self.combo_modelo)
        formulario.addRow("Tema de la interfaz:", self.combo_tema)
        formulario.addRow("Nombre del asistente:", self.edit_nombre_asistente)

        botones = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        botones.accepted.connect(self._al_aceptar)
        botones.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(titulo)
        layout.addWidget(etiqueta_ayuda)
        layout.addLayout(fila_enlace)
        layout.addSpacing(8)
        layout.addLayout(formulario)
        layout.addSpacing(10)
        layout.addWidget(etiqueta_instrucciones)
        layout.addWidget(self.edit_instrucciones, stretch=1)
        layout.addWidget(boton_restaurar)
        layout.addWidget(botones)

    def _alternar_visibilidad_clave(self, marcado: bool) -> None:
        """Muestra u oculta el texto de la API key."""
        self.edit_clave_api.setEchoMode(
            QLineEdit.Normal if marcado else QLineEdit.Password
        )

    def _abrir_pagina_clave_api(self, _enlace: str | None = None) -> None:
        """Abre la página de Google AI Studio para crear una API key."""
        QDesktopServices.openUrl(QUrl(URL_CLAVE_API))

    def _restaurar_instrucciones(self) -> None:
        """Vuelve a cargar el texto de instrucciones por defecto."""
        self.edit_instrucciones.setPlainText(INSTRUCCION_GENERAL_POR_DEFECTO)

    def _al_aceptar(self) -> None:
        """Valida la API key y la longitud de las instrucciones."""
        if not self.edit_clave_api.text().strip():
            QMessageBox.warning(
                self,
                "API key requerida",
                "Introduce una API key válida.\n\n"
                f"Puedes crearla en:\n{URL_CLAVE_API}",
            )
            return
        instrucciones = self.edit_instrucciones.toPlainText()
        if len(instrucciones) > MAX_CARACTERES_INSTRUCCION_SISTEMA:
            QMessageBox.warning(
                self,
                "Instrucciones demasiado largas",
                f"El máximo es {MAX_CARACTERES_INSTRUCCION_SISTEMA} caracteres "
                f"(ahora hay {len(instrucciones)}).",
            )
            return
        nombre = self.edit_nombre_asistente.text().strip()
        if not nombre:
            QMessageBox.warning(
                self,
                "Nombre del asistente",
                "El nombre del asistente no puede estar vacío.",
            )
            return
        self.accept()

    def clave_api(self) -> str:
        """Devuelve la API key introducida (sin espacios extremos)."""
        return self.edit_clave_api.text().strip()

    def modelo_seleccionado(self) -> str:
        """Id del modelo gratuito seleccionado en el combo."""
        return self.combo_modelo.currentData()

    def tema_seleccionado(self) -> str:
        """Id del tema de interfaz seleccionado (`light` / `dark`)."""
        return self.combo_tema.currentData()

    def nombre_asistente(self) -> str:
        """Nombre visible del asistente en el chat."""
        return (
            self.edit_nombre_asistente.text().strip() or NOMBRE_ASISTENTE_POR_DEFECTO
        )

    def instrucciones_sistema(self) -> str:
        """Texto de instrucciones generales para Gemini."""
        return self.edit_instrucciones.toPlainText().strip()
