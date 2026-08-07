# Gemini Workspace Local — escritorio con memoria por conversación

Aplicación de escritorio (Python + PySide6) para hablar con Google Gemini.
Cada chat guarda su propio historial y PDFs en SQLite y los usa como memoria,
sin mezclar ni sobrescribir la memoria de otros chats.

Repositorio: https://github.com/entreunosyceros/gwl

## Requisitos

- Python 3.11+
- Una API key gratuita de [Google AI Studio](https://aistudio.google.com/apikey)
- En Linux, bandeja del sistema disponible (panel/applet de notificaciones) para el icono de tray

## Uso

El arranque recomendado crea el entorno virtual, instala dependencias y lanza la app:

```bash
cd /var/www/html/GEMINI
python3 run_app.py
```

También puedes arrancar solo la UI si el venv ya está listo:

```bash
source .venv/bin/activate
python main.py
```

En el primer arranque se abrirá la configuración para pegar tu API key.
Puedes obtenerla aquí: https://aistudio.google.com/apikey

Para salir por completo desde la terminal donde la lanzaste, usa `Ctrl+C`
(también responde a `SIGTERM`).

### Funciones

- **Nuevo chat / abrir chat**: cada conversación tiene memoria aislada
- **Buscar / renombrar / exportar**: filtra chats en la barra lateral; `F2` o menú contextual para renombrar; `Ctrl+E` exporta el chat a Markdown
- **Eliminar chat**: desde el menú, la barra, el menú contextual o la tecla Supr
- **Compositor**: redimensionable, contador de caracteres/adjuntos, miniaturas, arrastrar y soltar archivos, pegar imágenes del portapapeles, prompts rápidos
- **Adjuntar imágenes/archivos**: botón **Adjuntar** (o `Ctrl+I`) para enviarlos a Gemini con el mensaje
- **Importar PDF**: añade el texto del PDF como memoria del chat activo (distinto de adjuntar al mensaje). En PDFs grandes se indexan todas las páginas y, en cada pregunta, se envía un extracto acotado (páginas relevantes o un muestreo corto). Solo se omite la consulta al PDF en charla trivial (p. ej. «hola»). Puedes eliminar o sustituir un PDF desde la lista del panel izquierdo.
- **Cascada de respuestas**: en modo Automático: 1) PDFs del chat (si hay señal local); 2) historial local; 3) conocimiento general de Gemini (sin reenviar el PDF completo). Puedes forzar **Solo PDF**, **Solo memoria** o **Solo Gemini** desde la cabecera del chat. Bajo el nombre del asistente se indica de dónde salió la respuesta (PDF / memoria / general).
- **Acciones sobre mensajes**: en la cabecera del chat — **Copiar respuesta**, **Editar mensaje** (tu último) y **Regenerar**; también puedes cancelar una generación en curso
- **Nombre del asistente**: configurable en Configuración (por defecto «Gemini»)
- **Código en respuestas**: bloques con estilo terminal, resaltado de sintaxis, seleccionables y botón **Copiar** al portapapeles
- **Modelos gratuitos**: Gemini 3.5 Flash y Gemini 3.1 Flash-Lite
- **API key**: configurable desde Configuración (menú o barra)
- **Instrucciones de Gemini**: en Configuración puedes definir o restaurar las instrucciones generales del asistente (personalidad, tono, reglas); acceso rápido con el botón **Personalidad** en la cabecera del chat
- **Tema**: claro u oscuro (paletas separadas; selector en la barra y en Configuración)
- **Bandeja del sistema**: icono con `app/img/logo.png`; menú para mostrar/ocultar la ventana, nuevo chat, configuración, About y salir. Cerrar con la X oculta la app en la bandeja; **Salir** (menú, bandeja o `Ctrl+C`) cierra del todo. Notifica cuando llega una respuesta si la ventana no está activa.
- **Atajos**: Ayuda → Atajos de teclado (`F1`)
- **About**: menú Ayuda → Acerca de (logo, descripción y enlace al repositorio)

Tipos de adjunto admitidos: imágenes (png, jpg, gif, webp…), PDF, texto (txt, md, csv, json, html), audio (mp3, wav, ogg) y vídeo (mp4, webm, mov), hasta 20 MB por archivo.

## Datos (privados — no se suben a Git)

Todo lo sensible queda fuera del repositorio vía `.gitignore`:

| Qué | Dónde | Motivo |
|-----|--------|--------|
| API key de Gemini | `data/gemini_chat.db` (tabla `settings`) | secreto |
| Historial de chats y texto de PDFs importados | `data/gemini_chat.db` | datos locales |
| Archivos adjuntos | `data/attachments/` | datos del usuario |
| PDFs sueltos en el proyecto | cualquier `*.pdf` | no versionar documentos |

Solo se versiona `data/.gitkeep` para crear la carpeta vacía. Tras clonar, la base y la API key se generan al usar la app.

## Código

El código de la aplicación (métodos, variables, constantes y comentarios) está
en **español**, salvo lo que no se puede traducir sin romper el programa:

- overrides de Qt (`closeEvent`, `keyPressEvent`, `run` del worker)
- `objectName` usados por las hojas de estilo QSS
- nombres de clases públicas (`MainWindow`, `ChatService`, …)
- columnas SQL y campos de dataclasses alineados con la base de datos
- IDs de modelo de Gemini (`gemini-3.5-flash`, etc.) y valores de tema (`light` / `dark`)

## Licencia

Gemini Workspace Local se publica bajo la
[**GNU General Public License v3.0 o posterior**](https://www.gnu.org/licenses/gpl-3.0.html)
(`GPL-3.0-or-later`).

- Texto completo: [`LICENSE`](LICENSE)
- Copyright (C) 2026 entreunosyceros

Es software libre: puedes usarlo, estudiarlo, compartirlo y modificarlo.
Las obras derivadas deben redistribuirse también bajo GPL compatible.
El aviso de licencia también aparece en **Ayuda → Acerca de**.


