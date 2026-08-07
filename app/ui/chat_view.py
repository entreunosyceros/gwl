"""Vista del historial de chat y compositor con adjuntos, acciones y cascada."""

from __future__ import annotations

import base64
import html
import uuid
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import (
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QGuiApplication,
    QIcon,
    QImage,
    QKeyEvent,
    QPixmap,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.config import (
    DIR_ADJUNTOS,
    EXTENSIONES_ADJUNTO_PERMITIDAS,
    MAX_ADJUNTOS_POR_MENSAJE,
    MODOS_CASCADA,
    NOMBRE_ASISTENTE_POR_DEFECTO,
    PROMPTS_RAPIDOS,
)
from app.db.repositories import Message
from app.services.attachments import resolver_ruta_almacenada
from app.services.memory import quitar_aviso_fuente
from app.ui.markdown_html import ESQUEMA_COPIAR_CODIGO, mensaje_a_html
from app.ui.theme import TEMA_POR_DEFECTO, tokens_para

_ETIQUETAS_FUENTE = {
    "pdf": "Respondió desde el PDF",
    "memory": "Respondió desde la memoria del chat",
    "gemini": "Respondió con conocimiento general",
}


class Composer(QPlainTextEdit):
    """Área de texto: Enter envía; Shift+Enter nueva línea; pega imágenes."""

    envio_solicitado = Signal()
    imagen_pegada = Signal(str)  # ruta tempfile

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (
            event.modifiers() & Qt.ShiftModifier
        ):
            self.envio_solicitado.emit()
            return
        super().keyPressEvent(event)

    def insertFromMimeData(self, source) -> None:  # noqa: N802
        if source is not None and source.hasImage():
            imagen = QImage(source.imageData())
            if not imagen.isNull():
                carpeta = DIR_ADJUNTOS / "_clipboard"
                carpeta.mkdir(parents=True, exist_ok=True)
                ruta = carpeta / f"pegado_{uuid.uuid4().hex}.png"
                if imagen.save(str(ruta), "PNG"):
                    self.imagen_pegada.emit(str(ruta))
                    return
        super().insertFromMimeData(source)


class ChatView(QWidget):
    """Transcripción HTML + barra de composición con adjuntos y acciones."""

    envio_solicitado = Signal(str, list)
    cancelar_solicitado = Signal()
    regenerar_solicitado = Signal()
    editar_mensaje_solicitado = Signal(int)
    copiado = Signal(str)
    abrir_ajustes_solicitado = Signal()
    modo_cascada_cambiado = Signal(str)

    def __init__(self, parent=None, theme: str = TEMA_POR_DEFECTO) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._tiene_mensajes = False
        self._rutas_pendientes: list[str] = []
        self._tema = theme
        self._tokens = tokens_para(theme)
        self._mensajes_en_cache: list[Message] = []
        self._bloques_codigo: list[str] = []
        self._ocupado = False
        self._num_pdfs = 0
        self._modo_cascada = "auto"
        self._nombre_asistente = NOMBRE_ASISTENTE_POR_DEFECTO
        self._id_ultimo_usuario: int | None = None
        self._id_ultimo_asistente: int | None = None
        self._texto_ultimo_asistente = ""

        self.browser = QTextBrowser()
        self.browser.setObjectName("chatView")
        self.browser.setTextInteractionFlags(
            Qt.TextSelectableByMouse
            | Qt.TextSelectableByKeyboard
            | Qt.LinksAccessibleByMouse
            | Qt.LinksAccessibleByKeyboard
        )
        self.browser.setOpenExternalLinks(False)
        self.browser.setOpenLinks(False)
        self.browser.anchorClicked.connect(self._al_clic_enlace)
        self.browser.verticalScrollBar().valueChanged.connect(self._al_scroll)

        # Cabecera
        cabecera = QFrame()
        cabecera.setObjectName("chatHeader")
        layout_cabecera = QVBoxLayout(cabecera)
        layout_cabecera.setContentsMargins(16, 12, 16, 10)
        layout_cabecera.setSpacing(6)

        fila_titulo = QHBoxLayout()
        self.titulo_cabecera = QLabel("Conversación")
        self.titulo_cabecera.setObjectName("chatHeaderTitle")
        fila_titulo.addWidget(self.titulo_cabecera, stretch=1)

        self.boton_personalidad = QPushButton("Personalidad")
        self.boton_personalidad.setObjectName("secondaryButton")
        self.boton_personalidad.setToolTip("Editar instrucciones generales de Gemini")
        self.boton_personalidad.clicked.connect(self.abrir_ajustes_solicitado.emit)
        fila_titulo.addWidget(self.boton_personalidad)

        self.boton_ir_final = QPushButton("↓ Final")
        self.boton_ir_final.setObjectName("secondaryButton")
        self.boton_ir_final.setToolTip("Ir al final del chat")
        self.boton_ir_final.clicked.connect(self.ir_al_final)
        self.boton_ir_final.setVisible(False)
        fila_titulo.addWidget(self.boton_ir_final)
        layout_cabecera.addLayout(fila_titulo)

        self.subtitulo_cabecera = QLabel("0 mensajes · 0 PDFs · modo: Automático")
        self.subtitulo_cabecera.setObjectName("chatHeaderSubtitle")
        layout_cabecera.addWidget(self.subtitulo_cabecera)

        fila_modo = QHBoxLayout()
        fila_modo.addWidget(QLabel("Fuente:"))
        self.combo_modo = QComboBox()
        for etiqueta, valor in MODOS_CASCADA:
            self.combo_modo.addItem(etiqueta, valor)
        self.combo_modo.currentIndexChanged.connect(self._al_cambiar_modo_ui)
        fila_modo.addWidget(self.combo_modo)
        fila_modo.addStretch()

        self.boton_copiar_ultima = QPushButton("Copiar respuesta")
        self.boton_copiar_ultima.setObjectName("secondaryButton")
        self.boton_copiar_ultima.setToolTip("Copia la última respuesta del asistente")
        self.boton_copiar_ultima.clicked.connect(self._copiar_ultima_respuesta)
        fila_modo.addWidget(self.boton_copiar_ultima)

        self.boton_editar_ultimo = QPushButton("Editar mensaje")
        self.boton_editar_ultimo.setObjectName("secondaryButton")
        self.boton_editar_ultimo.setToolTip("Edita tu último mensaje y reenvía")
        self.boton_editar_ultimo.clicked.connect(self._editar_ultimo_usuario)
        fila_modo.addWidget(self.boton_editar_ultimo)

        self.boton_regenerar = QPushButton("Regenerar")
        self.boton_regenerar.setObjectName("secondaryButton")
        self.boton_regenerar.setToolTip("Vuelve a generar la última respuesta")
        self.boton_regenerar.clicked.connect(self.regenerar_solicitado.emit)
        fila_modo.addWidget(self.boton_regenerar)
        layout_cabecera.addLayout(fila_modo)

        # Compositor
        self.lista_adjuntos = QListWidget()
        self.lista_adjuntos.setObjectName("attachmentList")
        self.lista_adjuntos.setMaximumHeight(88)
        self.lista_adjuntos.setIconSize(QPixmap(48, 48).size())
        self.lista_adjuntos.setVisible(False)
        self.lista_adjuntos.itemDoubleClicked.connect(self._quitar_adjunto_seleccionado)

        self.composer = Composer()
        self.composer.setObjectName("composer")
        self.composer.setPlaceholderText(
            "Escribe… Enter envía · Shift+Enter nueva línea · pega imágenes · arrastra archivos"
        )
        self.composer.setMinimumHeight(72)
        self.composer.setMaximumHeight(280)
        self.composer.resize(self.composer.width(), 120)
        self.composer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.composer.envio_solicitado.connect(self._emitir_envio)
        self.composer.imagen_pegada.connect(self._anadir_ruta_unica)
        self.composer.textChanged.connect(self._actualizar_contador)

        self.etiqueta_contador = QLabel("Adjuntos: 0/8 · caracteres: 0")
        self.etiqueta_contador.setObjectName("statusLabel")

        fila_prompts = QHBoxLayout()
        fila_prompts.setSpacing(6)
        for texto in PROMPTS_RAPIDOS:
            btn = QPushButton(texto[:22] + ("…" if len(texto) > 22 else ""))
            btn.setObjectName("secondaryButton")
            btn.setToolTip(texto)
            btn.clicked.connect(lambda checked=False, t=texto: self._insertar_prompt(t))
            fila_prompts.addWidget(btn)
        fila_prompts.addStretch()

        self.boton_adjuntar = QPushButton("Adjuntar")
        self.boton_adjuntar.setObjectName("secondaryButton")
        self.boton_adjuntar.clicked.connect(self.elegir_adjuntos)

        self.boton_quitar_adjuntos = QPushButton("Quitar")
        self.boton_quitar_adjuntos.setObjectName("secondaryButton")
        self.boton_quitar_adjuntos.setVisible(False)
        self.boton_quitar_adjuntos.clicked.connect(self.limpiar_adjuntos)

        self.boton_enviar = QPushButton("Enviar")
        self.boton_enviar.setDefault(True)
        self.boton_enviar.clicked.connect(self._emitir_envio)

        self.boton_cancelar = QPushButton("Cancelar")
        self.boton_cancelar.setObjectName("secondaryButton")
        self.boton_cancelar.setVisible(False)
        self.boton_cancelar.clicked.connect(self.cancelar_solicitado.emit)

        botones = QVBoxLayout()
        botones.setSpacing(6)
        botones.addWidget(self.boton_adjuntar)
        botones.addWidget(self.boton_quitar_adjuntos)
        botones.addStretch()
        botones.addWidget(self.boton_cancelar)
        botones.addWidget(self.boton_enviar)

        fila_compositor = QHBoxLayout()
        fila_compositor.setSpacing(12)
        fila_compositor.addWidget(self.composer, stretch=1)
        fila_compositor.addLayout(botones)

        pista = QLabel(
            "Atajos: Ctrl+I adjuntar · Ctrl+N nuevo chat · Ctrl+, ajustes · "
            "doble clic quita adjunto"
        )
        pista.setObjectName("statusLabel")
        pista.setWordWrap(True)

        barra_compositor = QFrame()
        barra_compositor.setObjectName("composerBar")
        layout_barra = QVBoxLayout(barra_compositor)
        layout_barra.setContentsMargins(16, 12, 16, 12)
        layout_barra.setSpacing(8)
        layout_barra.addLayout(fila_prompts)
        layout_barra.addWidget(self.lista_adjuntos)
        layout_barra.addLayout(fila_compositor)
        layout_barra.addWidget(self.etiqueta_contador)
        layout_barra.addWidget(pista)

        divisor = QSplitter(Qt.Vertical)
        divisor.addWidget(self.browser)
        divisor.addWidget(barra_compositor)
        divisor.setStretchFactor(0, 1)
        divisor.setStretchFactor(1, 0)
        divisor.setSizes([520, 220])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(cabecera)
        layout.addWidget(divisor, stretch=1)

    # --- API pública ---
    def establecer_titulo_chat(self, titulo: str) -> None:
        self.titulo_cabecera.setText(titulo or "Conversación")

    def establecer_resumen(
        self, num_mensajes: int, num_pdfs: int, modo_cascada: str
    ) -> None:
        self._num_pdfs = num_pdfs
        self._modo_cascada = modo_cascada
        etiqueta_modo = next(
            (e for e, v in MODOS_CASCADA if v == modo_cascada), modo_cascada
        )
        self.subtitulo_cabecera.setText(
            f"{num_mensajes} mensajes · {num_pdfs} PDFs · modo: {etiqueta_modo}"
        )
        self.combo_modo.blockSignals(True)
        for i in range(self.combo_modo.count()):
            if self.combo_modo.itemData(i) == modo_cascada:
                self.combo_modo.setCurrentIndex(i)
                break
        self.combo_modo.blockSignals(False)

    def establecer_ocupado(self, ocupado: bool, estado: str | None = None) -> None:
        self._ocupado = ocupado
        self.composer.setEnabled(not ocupado)
        self.boton_enviar.setVisible(not ocupado)
        self.boton_cancelar.setVisible(ocupado)
        self.boton_adjuntar.setEnabled(not ocupado)
        self.boton_quitar_adjuntos.setEnabled(not ocupado)
        self.lista_adjuntos.setEnabled(not ocupado)
        self.combo_modo.setEnabled(not ocupado)
        self._actualizar_botones_accion()
        if ocupado:
            self.boton_cancelar.setText(f"Cancelar ({estado})" if estado else "Cancelar")
        else:
            self.boton_enviar.setText("Enviar")

    def establecer_etiqueta_estado(self, estado: str) -> None:
        if self._ocupado:
            self.boton_cancelar.setText(f"Cancelar ({estado})")

    def establecer_tema(self, tema: str) -> None:
        self._tema = tema
        self._tokens = tokens_para(tema)
        self.renderizar_mensajes(self._mensajes_en_cache)

    def establecer_nombre_asistente(self, nombre: str) -> None:
        self._nombre_asistente = (nombre or "").strip() or NOMBRE_ASISTENTE_POR_DEFECTO
        self.renderizar_mensajes(self._mensajes_en_cache)

    def poner_texto_compositor(self, texto: str) -> None:
        self.composer.setPlainText(texto or "")
        self.composer.setFocus()
        self._actualizar_contador()

    def anadir_rutas_adjuntos(self, rutas: list[str]) -> None:
        for ruta in rutas:
            self._anadir_ruta_unica(ruta)

    def ir_al_final(self) -> None:
        self.browser.moveCursor(QTextCursor.End)
        self.boton_ir_final.setVisible(False)

    def limpiar(self) -> None:
        self._tiene_mensajes = False
        self._mensajes_en_cache = []
        self._bloques_codigo = []
        self.browser.clear()
        self.limpiar_adjuntos()

    def limpiar_adjuntos(self) -> None:
        self._rutas_pendientes.clear()
        self.lista_adjuntos.clear()
        self.lista_adjuntos.setVisible(False)
        self.boton_quitar_adjuntos.setVisible(False)
        self._actualizar_contador()

    def adjuntos_pendientes(self) -> list[str]:
        return list(self._rutas_pendientes)

    def renderizar_mensajes(self, mensajes: list[Message]) -> None:
        self._mensajes_en_cache = list(mensajes)
        self._bloques_codigo = []
        self._id_ultimo_usuario = None
        self._id_ultimo_asistente = None
        self._texto_ultimo_asistente = ""
        self.browser.clear()
        tokens = self._tokens
        if not mensajes:
            self._tiene_mensajes = False
            self.browser.setHtml(
                "<div style='margin:48px auto;max-width:520px;text-align:center;'>"
                f"<div style='font-size:28px;font-weight:750;color:{tokens.titulo_vacio};"
                "margin-bottom:10px;'>Empieza a conversar</div>"
                f"<div style='color:{tokens.cuerpo_vacio};font-size:14px;line-height:1.55;'>"
                "Adjunta archivos, importa PDFs o usa los prompts rápidos. "
                "Usa la barra superior para copiar, editar o regenerar."
                "</div></div>"
            )
            self.establecer_resumen(0, self._num_pdfs, self._modo_cascada)
            self._actualizar_botones_accion()
            return
        self._tiene_mensajes = True
        for m in mensajes:
            if m.role == "user":
                self._id_ultimo_usuario = m.id
            elif m.role == "assistant":
                self._id_ultimo_asistente = m.id
                self._texto_ultimo_asistente = m.content or ""
        partes = [self._formatear_mensaje(m) for m in mensajes]
        self.browser.setHtml(
            "<div style='max-width:900px;margin:0 auto;'>" + "".join(partes) + "</div>"
        )
        self.ir_al_final()
        self.establecer_resumen(len(mensajes), self._num_pdfs, self._modo_cascada)
        self._actualizar_botones_accion()

    def anadir_mensaje(
        self,
        rol: str,
        contenido: str,
        adjuntos: list | None = None,
        source: str = "",
        message_id: int = 0,
    ) -> None:
        falso = Message(
            id=message_id or (len(self._mensajes_en_cache) + 1),
            chat_id=0,
            role=rol,
            content=contenido,
            created_at="",
            attachments=list(adjuntos or []),
            source=source,
        )
        self._mensajes_en_cache.append(falso)
        self.renderizar_mensajes(self._mensajes_en_cache)

    def elegir_adjuntos(self) -> None:
        restantes = MAX_ADJUNTOS_POR_MENSAJE - len(self._rutas_pendientes)
        if restantes <= 0:
            return
        extensiones = " ".join(
            f"*{ext}" for ext in sorted(EXTENSIONES_ADJUNTO_PERMITIDAS)
        )
        rutas, _ = QFileDialog.getOpenFileNames(
            self,
            "Adjuntar imágenes o archivos",
            str(Path.home()),
            f"Archivos soportados ({extensiones});;Todos (*.*)",
        )
        for ruta in (rutas or [])[:restantes]:
            self._anadir_ruta_unica(ruta)

    # --- eventos ---
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            ruta = url.toLocalFile()
            if ruta:
                self._anadir_ruta_unica(ruta)

    def _al_cambiar_modo_ui(self, _index: int) -> None:
        modo = self.combo_modo.currentData()
        if modo:
            self.modo_cascada_cambiado.emit(modo)

    def _al_scroll(self, _valor: int) -> None:
        barra = self.browser.verticalScrollBar()
        cerca_final = barra.value() >= barra.maximum() - 40
        self.boton_ir_final.setVisible(not cerca_final and self._tiene_mensajes)

    def _al_clic_enlace(self, url: QUrl) -> None:
        texto = url.toString()
        if texto.startswith(f"{ESQUEMA_COPIAR_CODIGO}:"):
            try:
                indice = int(texto.split(":", 1)[1])
            except ValueError:
                return
            if 0 <= indice < len(self._bloques_codigo):
                QGuiApplication.clipboard().setText(self._bloques_codigo[indice])
                self.copiado.emit("Código copiado al portapapeles")
            return
        if url.scheme() in {"http", "https"}:
            QDesktopServices.openUrl(url)

    def _actualizar_botones_accion(self) -> None:
        libre = not self._ocupado
        self.boton_copiar_ultima.setEnabled(libre and bool(self._texto_ultimo_asistente))
        self.boton_editar_ultimo.setEnabled(
            libre and self._id_ultimo_usuario is not None
        )
        self.boton_regenerar.setEnabled(
            libre and self._id_ultimo_asistente is not None
        )

    def _copiar_ultima_respuesta(self) -> None:
        if not self._texto_ultimo_asistente:
            return
        QGuiApplication.clipboard().setText(self._texto_ultimo_asistente)
        self.copiado.emit("Respuesta copiada al portapapeles")

    def _editar_ultimo_usuario(self) -> None:
        if self._id_ultimo_usuario is None:
            return
        self.editar_mensaje_solicitado.emit(self._id_ultimo_usuario)

    def _insertar_prompt(self, texto: str) -> None:
        actual = self.composer.toPlainText().strip()
        if actual:
            self.composer.setPlainText(actual + "\n" + texto)
        else:
            self.composer.setPlainText(texto)
        self.composer.setFocus()
        self._actualizar_contador()

    def _anadir_ruta_unica(self, ruta: str) -> None:
        if len(self._rutas_pendientes) >= MAX_ADJUNTOS_POR_MENSAJE:
            return
        if not ruta or ruta in self._rutas_pendientes:
            return
        ext = Path(ruta).suffix.lower()
        if ext and ext not in EXTENSIONES_ADJUNTO_PERMITIDAS:
            return
        if not Path(ruta).is_file():
            return
        self._rutas_pendientes.append(ruta)
        self._actualizar_lista_adjuntos()

    def _quitar_adjunto_seleccionado(self, item: QListWidgetItem) -> None:
        ruta = item.data(Qt.UserRole)
        if ruta in self._rutas_pendientes:
            self._rutas_pendientes.remove(ruta)
        self._actualizar_lista_adjuntos()

    def _actualizar_lista_adjuntos(self) -> None:
        self.lista_adjuntos.clear()
        for ruta in self._rutas_pendientes:
            nombre = Path(ruta).name
            item = QListWidgetItem(nombre)
            item.setData(Qt.UserRole, ruta)
            item.setToolTip(ruta)
            if Path(ruta).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}:
                pix = QPixmap(ruta)
                if not pix.isNull():
                    item.setIcon(QIcon(pix.scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            self.lista_adjuntos.addItem(item)
        hay = bool(self._rutas_pendientes)
        self.lista_adjuntos.setVisible(hay)
        self.boton_quitar_adjuntos.setVisible(hay)
        self._actualizar_contador()

    def _actualizar_contador(self) -> None:
        n = len(self._rutas_pendientes)
        chars = len(self.composer.toPlainText())
        self.etiqueta_contador.setText(
            f"Adjuntos: {n}/{MAX_ADJUNTOS_POR_MENSAJE} · caracteres: {chars}"
        )

    def _emitir_envio(self) -> None:
        if self._ocupado:
            return
        texto = self.composer.toPlainText().strip()
        rutas = list(self._rutas_pendientes)
        if not texto and not rutas:
            return
        self.composer.clear()
        self.limpiar_adjuntos()
        self.envio_solicitado.emit(texto, rutas)

    def _formatear_mensaje(self, mensaje: Message) -> str:
        return self._formatear_mensaje_crudo(
            mensaje.role,
            mensaje.content,
            mensaje.attachments or [],
            source=mensaje.source or "",
        )

    def _envolver_burbuja(
        self,
        cuerpo: str,
        *,
        fondo: str,
        texto: str,
        borde: str | None = None,
        radio: str = "16px",
    ) -> str:
        # Qt QTextBrowser ignora a menudo padding en <div>; cellpadding es fiable.
        borde_css = f"border:1px solid {borde};" if borde else ""
        return (
            f"<table width='100%' cellspacing='0' cellpadding='14' "
            f"style='background:{fondo};color:{texto};{borde_css}"
            f"border-radius:{radio};'>"
            f"<tr><td style='padding:14px 18px;line-height:1.55;font-size:14px;'>"
            f"{cuerpo}</td></tr></table>"
        )

    def _formatear_mensaje_crudo(
        self,
        rol: str,
        contenido: str,
        adjuntos: list,
        *,
        source: str = "",
        message_id: int = 0,
        es_ultimo_asistente: bool = False,
    ) -> str:
        del message_id, es_ultimo_asistente  # acciones fuera de la burbuja
        es_usuario = rol == "user"
        etiqueta = "Tú" if es_usuario else html.escape(self._nombre_asistente)
        tokens = self._tokens
        texto_mostrar = contenido or ""
        if not es_usuario:
            texto_mostrar = quitar_aviso_fuente(texto_mostrar)
        resultado = mensaje_a_html(
            texto_mostrar,
            enriquecido=not es_usuario,
            tema=self._tema,
            indice_inicio_copia=len(self._bloques_codigo),
        )
        self._bloques_codigo.extend(resultado.bloques_codigo)
        cuerpo = resultado.html

        html_adjuntos = ""
        if adjuntos:
            trozos: list[str] = []
            for adj in adjuntos:
                nombre_archivo = html.escape(getattr(adj, "filename", str(adj)))
                mime = getattr(adj, "mime_type", "") or ""
                almacenado = getattr(adj, "stored_path", "")
                borde = (
                    tokens.burbuja_usuario_fondo
                    if es_usuario
                    else tokens.borde_imagen
                )
                if mime.startswith("image/") and almacenado:
                    ruta = resolver_ruta_almacenada(almacenado)
                    if ruta.is_file() and ruta.stat().st_size <= 2 * 1024 * 1024:
                        codificado = base64.b64encode(ruta.read_bytes()).decode("ascii")
                        trozos.append(
                            f"<div style='margin-top:12px;'>"
                            f"<img src='data:{mime};base64,{codificado}' "
                            f"style='max-width:340px;max-height:260px;"
                            f"border-radius:12px;border:1px solid {borde};' />"
                            f"<div style='opacity:0.75;font-size:12px;margin-top:6px;'>"
                            f"{nombre_archivo}</div></div>"
                        )
                        continue
                trozos.append(
                    f"<div style='margin-top:10px;font-size:12px;opacity:0.85;'>"
                    f"📎 {nombre_archivo}</div>"
                )
            html_adjuntos = "".join(trozos)

        pista_fuente = ""
        if not es_usuario and source in _ETIQUETAS_FUENTE:
            pista_fuente = (
                f"<div style='font-size:11px;font-weight:500;letter-spacing:0.02em;"
                f"color:{tokens.etiqueta_asistente};opacity:0.85;"
                f"margin:2px 0 8px 4px;'>"
                f"{html.escape(_ETIQUETAS_FUENTE[source])}</div>"
            )

        burbuja = self._envolver_burbuja(
            f"{cuerpo}{html_adjuntos}",
            fondo=(
                tokens.burbuja_usuario_fondo
                if es_usuario
                else tokens.burbuja_asistente_fondo
            ),
            texto=(
                tokens.burbuja_usuario_texto
                if es_usuario
                else tokens.burbuja_asistente_texto
            ),
            borde=None if es_usuario else tokens.borde_asistente,
            radio=(
                tokens.radio_usuario if es_usuario else tokens.radio_asistente
            ),
        )

        color_etiqueta = (
            tokens.etiqueta_usuario if es_usuario else tokens.etiqueta_asistente
        )
        cabecera = (
            f"<div style='font-size:11px;font-weight:700;letter-spacing:0.06em;"
            f"text-transform:uppercase;color:{color_etiqueta};"
            f"margin:0 0 6px 4px;'>{etiqueta}</div>"
            f"{pista_fuente}"
        )

        if es_usuario:
            return (
                f"<table width='100%' cellspacing='0' cellpadding='0' "
                f"style='margin:0 0 22px 0;'><tr>"
                f"<td width='18%'></td>"
                f"<td style='vertical-align:top;'>"
                f"{cabecera}{burbuja}"
                f"</td></tr></table>"
            )

        return (
            f"<table width='100%' cellspacing='0' cellpadding='0' "
            f"style='margin:0 0 22px 0;'><tr>"
            f"<td style='vertical-align:top;'>"
            f"{cabecera}{burbuja}"
            f"</td><td width='12%'></td></tr></table>"
        )
