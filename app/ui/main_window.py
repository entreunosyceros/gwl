"""Ventana principal: barra lateral de chats, transcripción, ajustes e importación PDF."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QSystemTrayIcon,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from app.config import MODELOS_GRATUITOS, NOMBRE_APP, RUTA_LOGO
from app.services.attachments import AttachmentError
from app.services.chat_service import ChatService
from app.services.gemini_client import GeminiError
from app.services.pdf_importer import PdfImportError
from app.ui.about_dialog import AboutDialog
from app.ui.chat_view import ChatView
from app.ui.settings_dialog import SettingsDialog
from app.ui.theme import TEMAS, ruta_hoja_estilos


class SendWorker(QObject):
    """Trabajador en hilo secundario que genera o regenera la respuesta."""

    terminado = Signal(object)
    fallido = Signal(str)
    estado_cambiado = Signal(str)

    def __init__(
        self,
        servicio: ChatService,
        id_chat: int,
        *,
        regenerar: bool = False,
    ) -> None:
        super().__init__()
        self.servicio = servicio
        self.id_chat = id_chat
        self.regenerar = regenerar

    @Slot()
    def run(self) -> None:
        # Debe llamarse ``run``: es el punto de entrada del hilo Qt.
        try:
            if self.regenerar:
                respuesta = self.servicio.regenerar_respuesta(
                    self.id_chat,
                    al_cambiar_fase=self.estado_cambiado.emit,
                )
            else:
                respuesta = self.servicio.generar_respuesta_asistente(
                    self.id_chat,
                    al_cambiar_fase=self.estado_cambiado.emit,
                )
            self.terminado.emit(respuesta)
        except Exception as exc:  # noqa: BLE001
            self.fallido.emit(str(exc))


class ImportPdfWorker(QObject):
    """Importa o sustituye un PDF en segundo plano con progreso por página."""

    progreso = Signal(int, int)  # página actual, total
    terminado = Signal(object)
    fallido = Signal(str)

    def __init__(
        self,
        servicio: ChatService,
        id_chat: int,
        ruta: str,
        *,
        id_documento_sustituir: int | None = None,
    ) -> None:
        super().__init__()
        self.servicio = servicio
        self.id_chat = id_chat
        self.ruta = ruta
        self.id_documento_sustituir = id_documento_sustituir

    @Slot()
    def run(self) -> None:
        try:
            def al_progreso(actual: int, total: int) -> None:
                self.progreso.emit(actual, total)

            if self.id_documento_sustituir is not None:
                doc = self.servicio.sustituir_pdf_documento(
                    self.id_chat,
                    self.id_documento_sustituir,
                    self.ruta,
                    al_progreso=al_progreso,
                )
            else:
                doc = self.servicio.importar_pdf(
                    self.id_chat,
                    self.ruta,
                    al_progreso=al_progreso,
                )
            self.terminado.emit(doc)
        except Exception as exc:  # noqa: BLE001
            self.fallido.emit(str(exc))


class MainWindow(QMainWindow):
    """Ventana principal de la aplicación de escritorio."""

    def __init__(self, servicio: ChatService) -> None:
        super().__init__()
        self.servicio = servicio
        self.id_chat_actual: int | None = None
        self._hilo: QThread | None = None
        self._trabajador: SendWorker | None = None
        self._hilo_pdf: QThread | None = None
        self._trabajador_pdf: ImportPdfWorker | None = None
        self._dialogo_progreso_pdf: QProgressDialog | None = None
        self._importacion_es_sustitucion = False
        self._forzar_salida = False
        self.bandeja: QSystemTrayIcon | None = None

        self.setWindowTitle(NOMBRE_APP)
        self.resize(1180, 760)
        self.setMinimumSize(900, 560)
        if RUTA_LOGO.is_file():
            self.setWindowIcon(QIcon(str(RUTA_LOGO)))
        self._cargar_estilos()
        self._construir_menu()
        self._construir_barra()
        self._construir_central()
        self._configurar_bandeja()
        self._actualizar_chats(seleccionar_primero=True)

        ajustes = self.servicio.obtener_ajustes()
        self.chat_view.establecer_tema(ajustes.theme)
        self.chat_view.establecer_nombre_asistente(ajustes.assistant_name)
        if not ajustes.api_key:
            self.abrir_ajustes(forzar=True)

    def _cargar_estilos(self) -> None:
        """Carga la hoja de estilos QSS del tema guardado."""
        tema = self.servicio.obtener_ajustes().theme
        ruta = ruta_hoja_estilos(tema)
        if ruta.is_file():
            self.setStyleSheet(ruta.read_text(encoding="utf-8"))

    def aplicar_tema(self, tema: str) -> None:
        """Persiste el tema, reaplica QSS y actualiza la vista de chat."""
        guardado = self.servicio.establecer_tema(tema)
        ruta = ruta_hoja_estilos(guardado.theme)
        if ruta.is_file():
            self.setStyleSheet(ruta.read_text(encoding="utf-8"))
        self.chat_view.establecer_tema(guardado.theme)
        self._sincronizar_combo_tema(guardado.theme)
        self.statusBar().showMessage(
            f"Tema: {'Claro' if guardado.theme == 'light' else 'Oscuro'}"
        )

    def _construir_menu(self) -> None:
        """Crea la barra de menús (Archivo, Configuración, Ayuda)."""
        menu_archivo = self.menuBar().addMenu("&Archivo")
        accion_nuevo = QAction("Nuevo chat", self)
        accion_nuevo.setShortcut(QKeySequence.New)
        accion_nuevo.triggered.connect(self.crear_chat)
        menu_archivo.addAction(accion_nuevo)

        accion_eliminar_chat = QAction("Eliminar chat…", self)
        accion_eliminar_chat.setShortcut(QKeySequence.Delete)
        accion_eliminar_chat.triggered.connect(self.eliminar_chat_seleccionado)
        menu_archivo.addAction(accion_eliminar_chat)

        accion_importar = QAction("Importar PDF (memoria)…", self)
        accion_importar.setShortcut("Ctrl+Shift+I")
        accion_importar.triggered.connect(self.importar_pdf)
        menu_archivo.addAction(accion_importar)

        accion_adjuntar = QAction("Adjuntar al mensaje…", self)
        accion_adjuntar.setShortcut("Ctrl+I")
        accion_adjuntar.triggered.connect(self.adjuntar_archivos)
        menu_archivo.addAction(accion_adjuntar)

        accion_exportar = QAction("Exportar chat (Markdown)…", self)
        accion_exportar.setShortcut("Ctrl+E")
        accion_exportar.triggered.connect(self.exportar_chat_actual)
        menu_archivo.addAction(accion_exportar)

        accion_renombrar = QAction("Renombrar chat…", self)
        accion_renombrar.setShortcut("F2")
        accion_renombrar.triggered.connect(self.renombrar_chat_seleccionado)
        menu_archivo.addAction(accion_renombrar)
        menu_archivo.addSeparator()

        accion_salir = QAction("Salir", self)
        accion_salir.setShortcut(QKeySequence.Quit)
        accion_salir.triggered.connect(self.salir_app)
        menu_archivo.addAction(accion_salir)

        menu_config = self.menuBar().addMenu("&Configuración")
        accion_api = QAction("API key, modelo y tema…", self)
        accion_api.setShortcut("Ctrl+,")
        accion_api.triggered.connect(lambda: self.abrir_ajustes(forzar=False))
        menu_config.addAction(accion_api)

        menu_tema = menu_config.addMenu("Tema")
        for etiqueta, valor in TEMAS:
            accion = QAction(etiqueta, self)
            accion.triggered.connect(
                lambda checked=False, t=valor: self.aplicar_tema(t)
            )
            menu_tema.addAction(accion)

        menu_ayuda = self.menuBar().addMenu("&Ayuda")
        accion_atajos = QAction("Atajos de teclado…", self)
        accion_atajos.setShortcut("F1")
        accion_atajos.triggered.connect(self.mostrar_atajos)
        menu_ayuda.addAction(accion_atajos)
        accion_about = QAction("Acerca de", self)
        accion_about.triggered.connect(self.abrir_about)
        menu_ayuda.addAction(accion_about)

    def _construir_barra(self) -> None:
        """Barra de herramientas con acciones rápidas y combos de modelo/tema."""
        barra = QToolBar("Principal")
        barra.setMovable(False)
        self.addToolBar(barra)

        btn_nuevo = QAction("Nuevo chat", self)
        btn_nuevo.triggered.connect(self.crear_chat)
        barra.addAction(btn_nuevo)

        btn_eliminar_chat = QAction("Eliminar chat", self)
        btn_eliminar_chat.triggered.connect(self.eliminar_chat_seleccionado)
        barra.addAction(btn_eliminar_chat)

        btn_pdf = QAction("Importar PDF", self)
        btn_pdf.triggered.connect(self.importar_pdf)
        barra.addAction(btn_pdf)

        btn_adjuntar = QAction("Adjuntar", self)
        btn_adjuntar.triggered.connect(self.adjuntar_archivos)
        barra.addAction(btn_adjuntar)

        btn_ajustes = QAction("Configuración", self)
        btn_ajustes.triggered.connect(lambda: self.abrir_ajustes(forzar=False))
        barra.addAction(btn_ajustes)

        barra.addSeparator()
        barra.addWidget(QLabel(" Modelo: "))

        self.combo_modelo = QComboBox()
        ajustes = self.servicio.obtener_ajustes()
        seleccionado = 0
        for i, (etiqueta, valor) in enumerate(MODELOS_GRATUITOS):
            self.combo_modelo.addItem(etiqueta, valor)
            if valor == ajustes.model:
                seleccionado = i
        self.combo_modelo.setCurrentIndex(seleccionado)
        self.combo_modelo.currentIndexChanged.connect(self._al_cambiar_modelo)
        barra.addWidget(self.combo_modelo)

        barra.addWidget(QLabel(" Tema: "))
        self.combo_tema = QComboBox()
        tema_seleccionado = 0
        for i, (etiqueta, valor) in enumerate(TEMAS):
            self.combo_tema.addItem(etiqueta, valor)
            if valor == ajustes.theme:
                tema_seleccionado = i
        self.combo_tema.setCurrentIndex(tema_seleccionado)
        self.combo_tema.currentIndexChanged.connect(self._al_cambiar_tema)
        barra.addWidget(self.combo_tema)

    def _construir_central(self) -> None:
        """Construye la barra lateral, la lista de PDFs y la vista de chat."""
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(220)
        sidebar.setMaximumWidth(320)

        layout_lateral = QVBoxLayout(sidebar)
        layout_lateral.setContentsMargins(0, 0, 0, 0)
        layout_lateral.setSpacing(0)

        fila_marca = QHBoxLayout()
        fila_marca.setContentsMargins(16, 16, 16, 0)
        fila_marca.setSpacing(10)

        etiqueta_logo = QLabel()
        etiqueta_logo.setObjectName("brandLogo")
        if RUTA_LOGO.is_file():
            pixmap = QPixmap(str(RUTA_LOGO))
            if not pixmap.isNull():
                etiqueta_logo.setPixmap(
                    pixmap.scaled(36, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
        fila_marca.addWidget(etiqueta_logo)

        texto_marca = QVBoxLayout()
        texto_marca.setSpacing(0)
        marca = QLabel(NOMBRE_APP)
        marca.setObjectName("brandTitle")
        marca.setStyleSheet("padding: 0; font-size: 15px;")
        sub_marca = QLabel("Memoria por conversación")
        sub_marca.setObjectName("brandSubtitle")
        sub_marca.setStyleSheet("padding: 0;")
        texto_marca.addWidget(marca)
        texto_marca.addWidget(sub_marca)
        fila_marca.addLayout(texto_marca, stretch=1)
        layout_lateral.addLayout(fila_marca)

        titulo = QLabel("Conversaciones")
        titulo.setObjectName("sidebarTitle")
        layout_lateral.addWidget(titulo)

        self.busqueda_chats = QLineEdit()
        self.busqueda_chats.setPlaceholderText("Buscar chats…")
        self.busqueda_chats.setClearButtonEnabled(True)
        self.busqueda_chats.textChanged.connect(self._filtrar_chats)
        layout_busqueda = QHBoxLayout()
        layout_busqueda.setContentsMargins(8, 0, 8, 8)
        layout_busqueda.addWidget(self.busqueda_chats)
        layout_lateral.addLayout(layout_busqueda)

        self.lista_chats = QListWidget()
        self.lista_chats.currentItemChanged.connect(self._al_seleccionar_chat)
        self.lista_chats.setContextMenuPolicy(Qt.CustomContextMenu)
        self.lista_chats.customContextMenuRequested.connect(self._menu_contextual_chat)
        layout_lateral.addWidget(self.lista_chats, stretch=1)

        botones_chat = QHBoxLayout()
        botones_chat.setContentsMargins(8, 4, 8, 4)
        botones_chat.setSpacing(6)
        self.boton_nuevo_chat = QPushButton("Nuevo")
        self.boton_nuevo_chat.setObjectName("secondaryButton")
        self.boton_nuevo_chat.clicked.connect(self.crear_chat)
        self.boton_eliminar_chat = QPushButton("Eliminar")
        self.boton_eliminar_chat.setObjectName("secondaryButton")
        self.boton_eliminar_chat.clicked.connect(self.eliminar_chat_seleccionado)
        botones_chat.addWidget(self.boton_nuevo_chat)
        botones_chat.addWidget(self.boton_eliminar_chat)
        layout_lateral.addLayout(botones_chat)

        botones_chat2 = QHBoxLayout()
        botones_chat2.setContentsMargins(8, 0, 8, 8)
        botones_chat2.setSpacing(6)
        self.boton_renombrar_chat = QPushButton("Renombrar")
        self.boton_renombrar_chat.setObjectName("secondaryButton")
        self.boton_renombrar_chat.clicked.connect(self.renombrar_chat_seleccionado)
        self.boton_exportar_chat = QPushButton("Exportar")
        self.boton_exportar_chat.setObjectName("secondaryButton")
        self.boton_exportar_chat.clicked.connect(self.exportar_chat_actual)
        botones_chat2.addWidget(self.boton_renombrar_chat)
        botones_chat2.addWidget(self.boton_exportar_chat)
        layout_lateral.addLayout(botones_chat2)

        titulo_docs = QLabel("PDFs en memoria")
        titulo_docs.setObjectName("sidebarTitle")
        layout_lateral.addWidget(titulo_docs)

        self.lista_docs = QListWidget()
        self.lista_docs.setObjectName("docList")
        self.lista_docs.setMaximumHeight(140)
        layout_lateral.addWidget(self.lista_docs)

        botones_doc = QHBoxLayout()
        botones_doc.setContentsMargins(8, 4, 8, 8)
        botones_doc.setSpacing(6)
        self.boton_eliminar_pdf = QPushButton("Eliminar")
        self.boton_eliminar_pdf.setObjectName("secondaryButton")
        self.boton_eliminar_pdf.clicked.connect(self.eliminar_pdf_seleccionado)
        self.boton_sustituir_pdf = QPushButton("Sustituir")
        self.boton_sustituir_pdf.setObjectName("secondaryButton")
        self.boton_sustituir_pdf.clicked.connect(self.sustituir_pdf_seleccionado)
        botones_doc.addWidget(self.boton_eliminar_pdf)
        botones_doc.addWidget(self.boton_sustituir_pdf)
        layout_lateral.addLayout(botones_doc)

        self.etiqueta_docs = QLabel("Sin PDFs en este chat")
        self.etiqueta_docs.setObjectName("statusLabel")
        self.etiqueta_docs.setWordWrap(True)
        layout_lateral.addWidget(self.etiqueta_docs)

        ajustes = self.servicio.obtener_ajustes()
        self.chat_view = ChatView(theme=ajustes.theme)
        self.chat_view.envio_solicitado.connect(self.enviar_mensaje)
        self.chat_view.cancelar_solicitado.connect(self.cancelar_generacion)
        self.chat_view.regenerar_solicitado.connect(self.regenerar_respuesta)
        self.chat_view.editar_mensaje_solicitado.connect(self.editar_mensaje)
        self.chat_view.copiado.connect(self._al_copiado)
        self.chat_view.abrir_ajustes_solicitado.connect(
            lambda: self.abrir_ajustes(forzar=False)
        )
        self.chat_view.modo_cascada_cambiado.connect(self._al_cambiar_modo_cascada)

        divisor = QSplitter()
        divisor.addWidget(sidebar)
        divisor.addWidget(self.chat_view)
        divisor.setStretchFactor(0, 0)
        divisor.setStretchFactor(1, 1)
        divisor.setSizes([240, 860])

        contenedor = QWidget()
        layout = QHBoxLayout(contenedor)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(divisor)
        self.setCentralWidget(contenedor)

        self.statusBar().showMessage("Listo")

    def _actualizar_chats(
        self,
        seleccionar_primero: bool = False,
        seleccionar_id: int | None = None,
    ) -> None:
        """Recarga la lista de chats y selecciona uno concreto o el primero."""
        anterior = seleccionar_id if seleccionar_id is not None else self.id_chat_actual
        self.lista_chats.blockSignals(True)
        self.lista_chats.clear()

        chats = self.servicio.listar_chats()
        if not chats:
            chat = self.servicio.crear_chat()
            chats = [chat]

        filtro = (self.busqueda_chats.text() if hasattr(self, "busqueda_chats") else "").strip().lower()
        fila_objetivo = 0
        visibles = 0
        for chat in chats:
            if filtro and filtro not in (chat.title or "").lower():
                continue
            item = QListWidgetItem(chat.title)
            item.setData(Qt.UserRole, chat.id)
            self.lista_chats.addItem(item)
            if anterior is not None and chat.id == anterior:
                fila_objetivo = visibles
            elif seleccionar_primero and visibles == 0 and anterior is None:
                fila_objetivo = 0
            visibles += 1

        self.lista_chats.blockSignals(False)
        if visibles:
            self.lista_chats.setCurrentRow(fila_objetivo)
        elif not filtro:
            # Sin filtro y sin ítems: no debería ocurrir tras crear chat por defecto
            pass

    def _filtrar_chats(self, _texto: str = "") -> None:
        """Reaplica el filtro de búsqueda manteniendo el chat actual si es posible."""
        self._actualizar_chats(seleccionar_id=self.id_chat_actual)

    def _id_chat_de_item(self, item: QListWidgetItem | None) -> int | None:
        """Extrae el id de chat almacenado en el UserRole del ítem."""
        if item is None:
            return None
        valor = item.data(Qt.UserRole)
        return int(valor) if valor is not None else None

    def _al_seleccionar_chat(
        self,
        actual: QListWidgetItem | None,
        _anterior: QListWidgetItem | None,
    ) -> None:
        """Cambia el chat activo al seleccionar un ítem de la lista."""
        id_chat = self._id_chat_de_item(actual)
        if id_chat is None:
            return
        self.id_chat_actual = id_chat
        self._cargar_chat_actual()

    def _cargar_chat_actual(self) -> None:
        """Carga mensajes, documentos y título del chat seleccionado."""
        if self.id_chat_actual is None:
            self.chat_view.limpiar()
            self._actualizar_documentos([])
            return
        mensajes = self.servicio.obtener_mensajes(self.id_chat_actual)
        docs = self.servicio.obtener_documentos(self.id_chat_actual)
        self._actualizar_documentos(docs)
        chat = self.servicio.obtener_chat(self.id_chat_actual)
        titulo = chat.title if chat else "Chat"
        ajustes = self.servicio.obtener_ajustes()
        self.chat_view.establecer_titulo_chat(titulo)
        self.chat_view.establecer_nombre_asistente(ajustes.assistant_name)
        self.chat_view.establecer_resumen(
            len(mensajes), len(docs), ajustes.cascade_mode or "auto"
        )
        self.chat_view.renderizar_mensajes(mensajes)
        self.statusBar().showMessage(f"Chat: {titulo}")

    def _actualizar_documentos(self, docs) -> None:
        """Rellena la lista de PDFs en memoria del chat actual."""
        self.lista_docs.clear()
        for doc in docs:
            paginas = self._pista_num_paginas(doc.text_content)
            etiqueta = doc.filename if not paginas else f"{doc.filename} ({paginas} pág.)"
            item = QListWidgetItem(etiqueta)
            item.setData(Qt.UserRole, doc.id)
            item.setToolTip(
                "PDF de memoria de este chat.\n"
                "Puedes eliminarlo o sustituirlo por otro."
            )
            self.lista_docs.addItem(item)
        hay_docs = bool(docs)
        self.boton_eliminar_pdf.setEnabled(hay_docs)
        self.boton_sustituir_pdf.setEnabled(hay_docs)
        if hay_docs:
            self.etiqueta_docs.setText(
                f"{len(docs)} PDF(s) en memoria de este chat. "
                "Se consultan páginas relevantes en cada pregunta."
            )
        else:
            self.etiqueta_docs.setText("Sin PDFs en este chat")

    @staticmethod
    def _pista_num_paginas(texto: str) -> str | None:
        """Intenta deducir el número de páginas desde el texto importado."""
        coincidencia = re.search(r"páginas=(\d+)", texto or "")
        if coincidencia:
            return coincidencia.group(1)
        paginas = re.findall(r"^--- Página (\d+) ---", texto or "", flags=re.MULTILINE)
        if paginas:
            return str(len(paginas))
        return None

    def crear_chat(self) -> None:
        """Crea una conversación nueva con memoria aislada."""
        chat = self.servicio.crear_chat()
        self._actualizar_chats(seleccionar_id=chat.id)
        self.statusBar().showMessage("Nueva conversación creada (memoria aislada)")

    def eliminar_chat_seleccionado(self) -> None:
        """Pide confirmación y elimina el chat seleccionado (y su memoria)."""
        item = self.lista_chats.currentItem()
        id_chat = self._id_chat_de_item(item)
        if id_chat is None:
            QMessageBox.information(
                self,
                "Eliminar chat",
                "Selecciona un chat de la lista para eliminarlo.",
            )
            return

        titulo = item.text() if item else "este chat"
        confirmar = QMessageBox.question(
            self,
            "Eliminar chat",
            f'¿Eliminar el chat "{titulo}"?\n\n'
            "Se borrarán su historial, PDFs de memoria y adjuntos. "
            "Esta acción no se puede deshacer.",
        )
        if confirmar != QMessageBox.Yes:
            return

        era_actual = self.id_chat_actual == id_chat
        self.servicio.eliminar_chat(id_chat)

        restantes = self.servicio.listar_chats()
        if not restantes:
            nuevo = self.servicio.crear_chat()
            self.id_chat_actual = nuevo.id
            self._actualizar_chats(seleccionar_id=nuevo.id)
            self.statusBar().showMessage("Chat eliminado; se creó uno nuevo")
            return

        id_seleccion = restantes[0].id
        if era_actual:
            self.id_chat_actual = id_seleccion
        self._actualizar_chats(
            seleccionar_id=id_seleccion if era_actual else self.id_chat_actual
        )
        self.statusBar().showMessage("Chat eliminado")

    def _menu_contextual_chat(self, pos) -> None:
        """Menú contextual sobre un ítem de la lista de chats."""
        item = self.lista_chats.itemAt(pos)
        if item is None:
            return
        self.lista_chats.setCurrentItem(item)
        menu = QMenu(self)
        accion_renombrar = menu.addAction("Renombrar…")
        accion_exportar = menu.addAction("Exportar Markdown…")
        menu.addSeparator()
        accion_eliminar = menu.addAction("Eliminar chat…")
        elegido = menu.exec(self.lista_chats.mapToGlobal(pos))
        if elegido == accion_renombrar:
            self.renombrar_chat_seleccionado()
        elif elegido == accion_exportar:
            self.exportar_chat_actual()
        elif elegido == accion_eliminar:
            self.eliminar_chat_seleccionado()

    def renombrar_chat_seleccionado(self) -> None:
        """Pide un nuevo título para el chat seleccionado."""
        item = self.lista_chats.currentItem()
        id_chat = self._id_chat_de_item(item)
        if id_chat is None:
            QMessageBox.information(
                self, "Renombrar", "Selecciona un chat de la lista."
            )
            return
        actual = item.text() if item else ""
        nuevo, ok = QInputDialog.getText(
            self,
            "Renombrar chat",
            "Nuevo título:",
            text=actual,
        )
        if not ok:
            return
        self.servicio.renombrar_chat(id_chat, nuevo)
        self._actualizar_chats(seleccionar_id=id_chat)
        if self.id_chat_actual == id_chat:
            self.chat_view.establecer_titulo_chat(nuevo.strip() or "Sin título")
        self.statusBar().showMessage("Chat renombrado")

    def exportar_chat_actual(self) -> None:
        """Exporta el chat activo a un archivo Markdown."""
        if self.id_chat_actual is None:
            QMessageBox.information(self, "Exportar", "No hay chat activo.")
            return
        chat = self.servicio.obtener_chat(self.id_chat_actual)
        sugerido = (chat.title if chat else "chat").replace("/", "-")[:60]
        ruta, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar chat",
            str(Path.home() / f"{sugerido}.md"),
            "Markdown (*.md);;Todos (*.*)",
        )
        if not ruta:
            return
        try:
            contenido = self.servicio.exportar_chat_markdown(self.id_chat_actual)
            Path(ruta).write_text(contenido, encoding="utf-8")
        except (GeminiError, OSError) as exc:
            QMessageBox.critical(self, "Exportar", str(exc))
            return
        self.statusBar().showMessage(f"Chat exportado a {ruta}")

    def mostrar_atajos(self) -> None:
        """Diálogo de ayuda con atajos de teclado."""
        QMessageBox.information(
            self,
            "Atajos de teclado",
            "Ctrl+N — Nuevo chat\n"
            "Supr — Eliminar chat\n"
            "F2 — Renombrar chat\n"
            "Ctrl+E — Exportar chat (Markdown)\n"
            "Ctrl+I — Adjuntar archivo\n"
            "Ctrl+Shift+I — Importar PDF\n"
            "Ctrl+, — Configuración\n"
            "Enter — Enviar mensaje\n"
            "Shift+Enter — Nueva línea\n"
            "F1 — Esta ayuda\n"
            "Ctrl+Q / Ctrl+C (terminal) — Salir",
        )

    def _configurar_bandeja(self) -> None:
        """Icono de bandeja del sistema para ocultar/mostrar la ventana."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        icono = QIcon(str(RUTA_LOGO)) if RUTA_LOGO.is_file() else self.windowIcon()
        self.bandeja = QSystemTrayIcon(icono, self)
        self.bandeja.setToolTip(NOMBRE_APP)

        menu = QMenu()
        accion_mostrar = QAction("Mostrar ventana", self)
        accion_mostrar.triggered.connect(self.mostrar_desde_bandeja)
        menu.addAction(accion_mostrar)

        accion_ocultar = QAction("Ocultar ventana", self)
        accion_ocultar.triggered.connect(self.hide)
        menu.addAction(accion_ocultar)
        menu.addSeparator()

        accion_nuevo = QAction("Nuevo chat", self)
        accion_nuevo.triggered.connect(self._bandeja_nuevo_chat)
        menu.addAction(accion_nuevo)

        accion_ajustes = QAction("Configuración…", self)
        accion_ajustes.triggered.connect(self._bandeja_abrir_ajustes)
        menu.addAction(accion_ajustes)

        accion_about = QAction("Acerca de", self)
        accion_about.triggered.connect(self._bandeja_abrir_about)
        menu.addAction(accion_about)
        menu.addSeparator()

        accion_salir = QAction("Salir", self)
        accion_salir.triggered.connect(self.salir_app)
        menu.addAction(accion_salir)

        self.bandeja.setContextMenu(menu)
        self.bandeja.activated.connect(self._al_activar_bandeja)
        self.bandeja.show()

    def mostrar_desde_bandeja(self) -> None:
        """Restaura y activa la ventana principal."""
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def preparar_salida(self) -> None:
        """Marca salida real (no minimizar a bandeja) y oculta el icono."""
        self._forzar_salida = True
        if self.bandeja is not None:
            self.bandeja.hide()

    def salir_app(self) -> None:
        """Cierra la aplicación por completo."""
        self.preparar_salida()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        # Si hay bandeja visible, ocultar en lugar de salir.
        if (
            not self._forzar_salida
            and self.bandeja is not None
            and self.bandeja.isVisible()
        ):
            event.ignore()
            self.hide()
            return
        event.accept()

    def _al_activar_bandeja(self, motivo: QSystemTrayIcon.ActivationReason) -> None:
        """Clic / doble clic en la bandeja: alterna visibilidad de la ventana."""
        if motivo in (
            QSystemTrayIcon.Trigger,
            QSystemTrayIcon.DoubleClick,
        ):
            if self.isVisible():
                self.hide()
            else:
                self.mostrar_desde_bandeja()

    def _bandeja_nuevo_chat(self) -> None:
        self.mostrar_desde_bandeja()
        self.crear_chat()

    def _bandeja_abrir_ajustes(self) -> None:
        self.mostrar_desde_bandeja()
        self.abrir_ajustes(forzar=False)

    def _bandeja_abrir_about(self) -> None:
        self.mostrar_desde_bandeja()
        self.abrir_about()

    def abrir_about(self) -> None:
        """Muestra el diálogo Acerca de."""
        dialogo = AboutDialog(self)
        dialogo.exec()

    def abrir_ajustes(self, forzar: bool = False) -> None:
        """Abre el diálogo de configuración; ``forzar`` avisa si falta API key."""
        ajustes = self.servicio.obtener_ajustes()
        dialogo = SettingsDialog(
            self,
            api_key=ajustes.api_key,
            model=ajustes.model,
            theme=ajustes.theme,
            system_instruction=ajustes.system_instruction,
            assistant_name=ajustes.assistant_name,
        )
        if dialogo.exec():
            guardado = self.servicio.guardar_ajustes(
                dialogo.clave_api(),
                dialogo.modelo_seleccionado(),
                dialogo.tema_seleccionado(),
                dialogo.instrucciones_sistema(),
                assistant_name=dialogo.nombre_asistente(),
            )
            self._sincronizar_combo_modelo(guardado.model)
            self.aplicar_tema(guardado.theme)
            self.chat_view.establecer_nombre_asistente(guardado.assistant_name)
            self.statusBar().showMessage("Configuración guardada")
        elif forzar and not ajustes.api_key:
            QMessageBox.information(
                self,
                "API key pendiente",
                "Puedes configurar la API key más tarde desde Configuración.\n"
                "Sin ella no podrás enviar mensajes a Gemini.",
            )

    def _sincronizar_combo_modelo(self, modelo: str) -> None:
        """Alinea el combo de la barra con el modelo persistido."""
        self.combo_modelo.blockSignals(True)
        for i in range(self.combo_modelo.count()):
            if self.combo_modelo.itemData(i) == modelo:
                self.combo_modelo.setCurrentIndex(i)
                break
        self.combo_modelo.blockSignals(False)

    def _sincronizar_combo_tema(self, tema: str) -> None:
        """Alinea el combo de la barra con el tema persistido."""
        self.combo_tema.blockSignals(True)
        for i in range(self.combo_tema.count()):
            if self.combo_tema.itemData(i) == tema:
                self.combo_tema.setCurrentIndex(i)
                break
        self.combo_tema.blockSignals(False)

    def _al_cambiar_modelo(self, _indice: int) -> None:
        modelo = self.combo_modelo.currentData()
        if modelo:
            self.servicio.establecer_modelo(modelo)
            self.statusBar().showMessage(f"Modelo: {self.combo_modelo.currentText()}")

    def _al_cambiar_tema(self, _indice: int) -> None:
        tema = self.combo_tema.currentData()
        if tema:
            self.aplicar_tema(tema)

    def importar_pdf(self) -> None:
        """Importa un PDF como memoria del chat actual."""
        if self.id_chat_actual is None:
            QMessageBox.warning(self, "Sin chat", "Crea o abre un chat primero.")
            return
        if self._hilo_pdf is not None and self._hilo_pdf.isRunning():
            QMessageBox.information(
                self,
                "Importar PDF",
                "Ya hay una importación de PDF en curso.",
            )
            return
        ruta, _ = QFileDialog.getOpenFileName(
            self,
            "Importar PDF como memoria",
            str(Path.home()),
            "PDF (*.pdf)",
        )
        if not ruta:
            return
        self._iniciar_importacion_pdf(ruta, id_documento_sustituir=None)

    def sustituir_pdf_seleccionado(self) -> None:
        """Sustituye el PDF seleccionado por otro fichero."""
        if self.id_chat_actual is None:
            return
        if self._hilo_pdf is not None and self._hilo_pdf.isRunning():
            QMessageBox.information(
                self,
                "Sustituir PDF",
                "Ya hay una importación de PDF en curso.",
            )
            return
        id_doc = self._id_documento_seleccionado()
        if id_doc is None:
            QMessageBox.information(
                self,
                "PDF",
                "Selecciona un PDF de la lista para sustituirlo.",
            )
            return
        ruta, _ = QFileDialog.getOpenFileName(
            self,
            "Sustituir PDF de memoria",
            str(Path.home()),
            "PDF (*.pdf)",
        )
        if not ruta:
            return
        self._iniciar_importacion_pdf(ruta, id_documento_sustituir=id_doc)

    def _iniciar_importacion_pdf(
        self,
        ruta: str,
        *,
        id_documento_sustituir: int | None,
    ) -> None:
        """Lanza el trabajador de importación y muestra la barra de progreso."""
        if self.id_chat_actual is None:
            return
        self._importacion_es_sustitucion = id_documento_sustituir is not None
        nombre = Path(ruta).name
        titulo = (
            "Sustituyendo PDF"
            if self._importacion_es_sustitucion
            else "Importando PDF"
        )
        self.statusBar().showMessage(f"{titulo}: {nombre}…")

        dialogo = QProgressDialog(
            f"Extrayendo texto de «{nombre}»…",
            None,
            0,
            100,
            self,
        )
        dialogo.setWindowTitle(titulo)
        dialogo.setWindowModality(Qt.WindowModal)
        dialogo.setMinimumDuration(0)
        dialogo.setAutoClose(False)
        dialogo.setAutoReset(False)
        dialogo.setMinimumWidth(420)
        dialogo.setValue(0)
        dialogo.setLabelText(f"Preparando «{nombre}»…")
        dialogo.show()
        self._dialogo_progreso_pdf = dialogo

        self._hilo_pdf = QThread(self)
        self._trabajador_pdf = ImportPdfWorker(
            self.servicio,
            self.id_chat_actual,
            ruta,
            id_documento_sustituir=id_documento_sustituir,
        )
        self._trabajador_pdf.moveToThread(self._hilo_pdf)
        self._hilo_pdf.started.connect(self._trabajador_pdf.run)
        self._trabajador_pdf.progreso.connect(self._al_progreso_pdf)
        self._trabajador_pdf.terminado.connect(self._al_pdf_importado)
        self._trabajador_pdf.fallido.connect(self._al_pdf_fallido)
        self._trabajador_pdf.terminado.connect(self._hilo_pdf.quit)
        self._trabajador_pdf.fallido.connect(self._hilo_pdf.quit)
        self._hilo_pdf.finished.connect(self._limpiar_trabajador_pdf)
        self._hilo_pdf.start()

    @Slot(int, int)
    def _al_progreso_pdf(self, actual: int, total: int) -> None:
        dialogo = self._dialogo_progreso_pdf
        if dialogo is None:
            return
        tope = max(total, 1)
        dialogo.setMaximum(tope)
        dialogo.setValue(min(actual, tope))
        if actual <= 0:
            dialogo.setLabelText("Abriendo PDF…")
        else:
            dialogo.setLabelText(f"Extrayendo texto… página {actual} de {tope}")
        self.statusBar().showMessage(f"Importando PDF… {actual}/{tope}")

    @Slot(object)
    def _al_pdf_importado(self, doc) -> None:
        self._cerrar_dialogo_progreso_pdf()
        self._cargar_chat_actual()
        paginas = self._pista_num_paginas(doc.text_content) or "?"
        if self._importacion_es_sustitucion:
            QMessageBox.information(
                self,
                "PDF sustituido",
                f'Ahora la memoria usa "{doc.filename}" ({paginas} páginas).',
            )
            self.statusBar().showMessage(f'PDF sustituido por "{doc.filename}"')
        else:
            QMessageBox.information(
                self,
                "PDF importado",
                f'Se importó "{doc.filename}" ({paginas} páginas) como memoria '
                "de este chat.\n"
                "En cada pregunta se enviarán las páginas más relevantes "
                "(no solo el inicio del documento).\n"
                "No afecta a otras conversaciones.",
            )
            self.statusBar().showMessage(f'PDF "{doc.filename}" importado')

    @Slot(str)
    def _al_pdf_fallido(self, error: str) -> None:
        self._cerrar_dialogo_progreso_pdf()
        titulo = (
            "Error al sustituir PDF"
            if self._importacion_es_sustitucion
            else "Error al importar PDF"
        )
        QMessageBox.critical(self, titulo, error)
        self.statusBar().showMessage(titulo)

    def _cerrar_dialogo_progreso_pdf(self) -> None:
        dialogo = self._dialogo_progreso_pdf
        self._dialogo_progreso_pdf = None
        if dialogo is not None:
            dialogo.reset()
            dialogo.hide()
            dialogo.deleteLater()

    def _limpiar_trabajador_pdf(self) -> None:
        if self._trabajador_pdf is not None:
            self._trabajador_pdf.deleteLater()
            self._trabajador_pdf = None
        if self._hilo_pdf is not None:
            self._hilo_pdf.deleteLater()
            self._hilo_pdf = None

    def _id_documento_seleccionado(self) -> int | None:
        """Id del PDF seleccionado en la lista de documentos."""
        item = self.lista_docs.currentItem()
        if item is None:
            return None
        valor = item.data(Qt.UserRole)
        return int(valor) if valor is not None else None

    def eliminar_pdf_seleccionado(self) -> None:
        """Elimina de la memoria el PDF seleccionado."""
        if self.id_chat_actual is None:
            return
        id_doc = self._id_documento_seleccionado()
        if id_doc is None:
            QMessageBox.information(
                self,
                "PDF",
                "Selecciona un PDF de la lista para eliminarlo.",
            )
            return
        item = self.lista_docs.currentItem()
        nombre = item.text() if item else "este PDF"
        confirmar = QMessageBox.question(
            self,
            "Eliminar PDF",
            f'¿Eliminar "{nombre}" de la memoria de este chat?\n'
            "Podrás importar otro después.",
        )
        if confirmar != QMessageBox.Yes:
            return
        try:
            eliminado = self.servicio.eliminar_documento(
                id_doc, chat_id=self.id_chat_actual
            )
        except PdfImportError as exc:
            QMessageBox.warning(self, "PDF", str(exc))
            return
        if not eliminado:
            QMessageBox.warning(self, "PDF", "No se pudo eliminar el PDF.")
            return
        self._cargar_chat_actual()
        self.statusBar().showMessage("PDF eliminado de la memoria del chat")

    def adjuntar_archivos(self) -> None:
        """Delegado: abre el selector de adjuntos de la vista de chat."""
        self.chat_view.elegir_adjuntos()

    def enviar_mensaje(
        self, texto: str, rutas_adjuntos: list | None = None
    ) -> None:
        """Guarda el mensaje del usuario y lanza el trabajador de respuesta."""
        if self.id_chat_actual is None:
            return
        ajustes = self.servicio.obtener_ajustes()
        if not ajustes.api_key:
            self.abrir_ajustes(forzar=True)
            ajustes = self.servicio.obtener_ajustes()
            if not ajustes.api_key:
                return

        rutas = list(rutas_adjuntos or [])
        try:
            mensaje = self.servicio.agregar_mensaje_usuario(
                self.id_chat_actual,
                texto,
                rutas,
            )
        except (GeminiError, AttachmentError) as exc:
            QMessageBox.warning(self, "Mensaje", str(exc))
            return

        self.chat_view.anadir_mensaje(
            "user",
            mensaje.content,
            mensaje.attachments or [],
            message_id=mensaje.id,
        )
        self._actualizar_chats(seleccionar_id=self.id_chat_actual)
        self._iniciar_generacion(regenerar=False)

    def _iniciar_generacion(self, *, regenerar: bool = False) -> None:
        """Lanza el hilo de generación o regeneración."""
        if self.id_chat_actual is None:
            return
        if self._hilo is not None and self._hilo.isRunning():
            return
        self.chat_view.establecer_ocupado(True, "Recordando")
        self.statusBar().showMessage(
            "Regenerando…" if regenerar else "Recordando…"
        )
        self._hilo = QThread(self)
        self._trabajador = SendWorker(
            self.servicio, self.id_chat_actual, regenerar=regenerar
        )
        self._trabajador.moveToThread(self._hilo)
        self._hilo.started.connect(self._trabajador.run)
        self._trabajador.estado_cambiado.connect(self._al_estado_envio)
        self._trabajador.terminado.connect(self._al_envio_terminado)
        self._trabajador.fallido.connect(self._al_envio_fallido)
        self._trabajador.terminado.connect(self._hilo.quit)
        self._trabajador.fallido.connect(self._hilo.quit)
        self._hilo.finished.connect(self._limpiar_trabajador)
        self._hilo.start()

    def cancelar_generacion(self) -> None:
        """Solicita cancelar la generación en curso."""
        self.servicio.solicitar_cancelacion()
        self.statusBar().showMessage("Cancelando…")

    def regenerar_respuesta(self) -> None:
        """Borra la última respuesta del asistente y genera otra."""
        if self.id_chat_actual is None:
            return
        if self._hilo is not None and self._hilo.isRunning():
            return
        ajustes = self.servicio.obtener_ajustes()
        if not ajustes.api_key:
            self.abrir_ajustes(forzar=True)
            if not self.servicio.obtener_ajustes().api_key:
                return
        self._iniciar_generacion(regenerar=True)

    def editar_mensaje(self, message_id: int) -> None:
        """Elimina desde el mensaje de usuario y lo pone en el compositor."""
        if self.id_chat_actual is None:
            return
        if self._hilo is not None and self._hilo.isRunning():
            QMessageBox.information(
                self,
                "Editar",
                "Espera a que termine la generación o cancélala primero.",
            )
            return
        try:
            texto = self.servicio.reeditar_desde_mensaje(
                self.id_chat_actual, message_id
            )
        except GeminiError as exc:
            QMessageBox.warning(self, "Editar", str(exc))
            return
        self._cargar_chat_actual()
        self._actualizar_chats(seleccionar_id=self.id_chat_actual)
        self.chat_view.poner_texto_compositor(texto or "")
        self.statusBar().showMessage(
            "Mensaje listo para editar. Envía de nuevo cuando quieras."
        )

    def _al_cambiar_modo_cascada(self, modo: str) -> None:
        """Persiste el modo de cascada elegido en la cabecera del chat."""
        guardado = self.servicio.establecer_modo_cascada(modo)
        if self.id_chat_actual is not None:
            mensajes = self.servicio.obtener_mensajes(self.id_chat_actual)
            docs = self.servicio.obtener_documentos(self.id_chat_actual)
            self.chat_view.establecer_resumen(
                len(mensajes), len(docs), guardado.cascade_mode or "auto"
            )
        self.statusBar().showMessage(
            f"Modo de fuente: {self.chat_view.combo_modo.currentText()}"
        )

    @Slot(str)
    def _al_copiado(self, mensaje: str) -> None:
        self.statusBar().showMessage(mensaje, 2500)

    @Slot(str)
    def _al_estado_envio(self, estado: str) -> None:
        self.chat_view.establecer_etiqueta_estado(estado)
        self.statusBar().showMessage(f"{estado}…")

    @Slot(object)
    def _al_envio_terminado(self, respuesta) -> None:
        self._cargar_chat_actual()
        self.chat_view.establecer_ocupado(False)
        self._actualizar_chats(seleccionar_id=self.id_chat_actual)
        fuente = getattr(respuesta, "source", "") or ""
        etiqueta = {"pdf": "PDF", "memory": "Memoria", "gemini": "Gemini"}.get(
            fuente, ""
        )
        msg = (
            f"Respuesta recibida ({etiqueta})"
            if etiqueta
            else "Respuesta recibida"
        )
        self.statusBar().showMessage(msg)
        if (
            self.bandeja is not None
            and (not self.isVisible() or not self.isActiveWindow())
        ):
            self.bandeja.showMessage(
                NOMBRE_APP,
                msg,
                QSystemTrayIcon.Information,
                4000,
            )

    @Slot(str)
    def _al_envio_fallido(self, error: str) -> None:
        self.chat_view.establecer_ocupado(False)
        self._cargar_chat_actual()
        self._actualizar_chats(seleccionar_id=self.id_chat_actual)
        if "cancelad" in error.lower():
            self.statusBar().showMessage("Generación cancelada")
            return
        titulo = "Error de Gemini" if "Gemini" in error or "API" in error else "Error"
        QMessageBox.critical(self, titulo, error)
        self.statusBar().showMessage("Error al enviar")

    def _limpiar_trabajador(self) -> None:
        """Libera el trabajador y el hilo tras terminar el envío."""
        if self._trabajador is not None:
            self._trabajador.deleteLater()
            self._trabajador = None
        if self._hilo is not None:
            self._hilo.deleteLater()
            self._hilo = None
