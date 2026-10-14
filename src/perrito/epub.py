"""Módulo de compilación y generación de libros electrónicos en formato EPUB 3.

Genera libros en formato apaisado/rectangular (landscape) con la imagen de la página
en el fondo y el texto digitalizado (OCR) posicionado encima de la imagen, con
soporte para selección, búsqueda, lectura accesible e índice navegable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
import html
import re
import uuid
import zipfile

from ebooklib import epub
from PIL import Image

# Caracteres de control no permitidos en XML 1.0 (el OCR a veces los produce)
_INVALID_XML_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")

# Estilo visual moderno para EPUB 3 en formato horizontal (Landscape)
# Estilo visual moderno para EPUB 3 en formato horizontal (Landscape)
# con imagen de fondo a tamaño completo y texto encima de la imagen con posicionamiento exacto
LANDSCAPE_CSS = """
@font-face {
    font-family: "Quicksand";
    font-style: normal;
    font-weight: 400;
    src: url("../fonts/Quicksand.ttf") format("truetype");
}

@page {
    size: 1034px 798px landscape;
    margin: 0;
}

* {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

html, body {
    width: 1034px;
    height: 798px;
    margin: 0;
    padding: 0;
    overflow: hidden;
    background-color: #ffffff;
    font-family: "Quicksand", "Century Gothic", "Avant Garde", "Nunito", "Segoe UI", Roboto, sans-serif;
    color: #1a1a1a;
    -webkit-font-smoothing: antialiased;
}

/* Lienzo de página apaisada */
.page-canvas {
    position: relative;
    width: 1034px;
    height: 798px;
    margin: 0;
    padding: 0;
    overflow: hidden;
    background-color: #ffffff;
}

/* Imagen en el fondo abarcando todo el lienzo horizontal */
.bg-image {
    position: absolute;
    top: 0;
    left: 0;
    width: 1034px;
    height: 798px;
    object-fit: contain;
    z-index: 1;
    pointer-events: none;
    display: block;
}

/* Capa de texto posicionada exactamente encima de la imagen (seleccionable y accesible) */
.text-layer {
    position: absolute;
    top: 0;
    left: 0;
    width: 1034px;
    height: 798px;
    z-index: 2;
    pointer-events: auto;
    overflow: hidden;
}

/* Líneas con posicionamiento exacto sobre las palabras impresas */
.text-line {
    position: absolute;
    display: inline-block;
    transform-origin: 0 0;
    -webkit-transform-origin: 0 0;
    white-space: nowrap;
    overflow: visible;
    color: transparent !important;
    -webkit-text-fill-color: transparent !important;
    user-select: text;
    -webkit-user-select: text;
    cursor: text;
    font-family: "Quicksand", "Century Gothic", "Avant Garde", "Nunito", "Segoe UI", Roboto, sans-serif;
    line-height: 1;
}

/* Resaltado de selección estándar sobre el texto */
::selection {
    background: rgba(0, 102, 204, 0.35);
    color: transparent;
    -webkit-text-fill-color: transparent;
}

::-moz-selection {
    background: rgba(0, 102, 204, 0.35);
    color: transparent;
}

/* Fallback para texto OCR sin coordenadas por línea */
.ocr-text-overlay {
    position: absolute;
    top: 0;
    left: 0;
    width: 1034px;
    height: 798px;
    padding: 30px 50px;
    font-size: 19px;
    line-height: 1.5;
    color: transparent !important;
    -webkit-text-fill-color: transparent !important;
    user-select: text;
    -webkit-user-select: text;
}

.ocr-text-overlay p {
    margin-bottom: 8px;
}

/* Portada a pantalla completa */
.cover-canvas {
    position: relative;
    width: 1034px;
    height: 798px;
    background: #ffffff;
}

.cover-canvas img {
    position: absolute;
    top: 0;
    left: 0;
    width: 1034px;
    height: 798px;
    object-fit: contain;
}
"""


@dataclass(frozen=True)
class PageTextLine:
    """Una línea de texto con su posición y dimensiones relativas a la página (en porcentajes 0-100)."""

    top_pct: float
    left_pct: float
    width_pct: float
    height_pct: float
    font_size_px: float
    text: str


@dataclass
class PageImage:
    """Una página del libro: imagen ya codificada + metadatos + líneas de texto posicionadas."""

    data: bytes
    width: int
    height: int
    label: str
    media_type: str = "image/jpeg"
    text: str = ""
    lines: list[PageTextLine] = field(default_factory=list)
    extension: str = field(default="jpg")


@dataclass(frozen=True)
class Chapter:
    number: int
    title: str
    page_index: int


def clean_text(raw_text: str) -> str:
    """Elimina caracteres inválidos en XML y normaliza espacios."""
    clean = _INVALID_XML_CHARS.sub("", raw_text or "")
    clean = re.sub(r"[ \t]+", " ", clean.replace("\r", ""))
    return re.sub(r"\n{3,}", "\n\n", clean).strip()


def ocr_text_to_xhtml(raw_text: str) -> str:
    """Convierte texto OCR plano en párrafos XHTML válidos (escapando <, >, &, comillas)."""
    paragraphs = []
    for block in re.split(r"\n\s*\n", clean_text(raw_text)):
        lines = [html.escape(line.strip(), quote=True) for line in block.splitlines() if line.strip()]
        if lines:
            paragraphs.append(f"<p>{'<br/>'.join(lines)}</p>")
    return "".join(paragraphs)


_HEADER_RE = re.compile(r"(?m)^\s*(\d{1,2})\s*[•·]\s*(.+?)\s*$")
_OPENER_RE = re.compile(r"(\d{1,2})\s+([^\d•·].{2,60})")


def _squash(s: str) -> str:
    return re.sub(r"\W+", "", s.lower())


CANONICAL_LECTURAS_1993: list[tuple[int, str, int]] = [
    (1, "Paco el Chato", 7),
    (2, "Saltan y saltan", 13),
    (3, "¡Socorro!", 19),
    (4, "La cucaracha comelona", 26),
    (5, "¡No te lo creo!", 32),
    (6, "Los changuitos", 37),
    (7, "¿Qué le pasó a María?", 42),
    (8, "La estrellita fugaz", 47),
    (9, "El viaje", 52),
    (10, "La casita del caracol", 56),
    (11, "Los tres deseos", 64),
    (12, "¡A que te pego!", 71),
    (13, "El gato bombero", 76),
    (14, "Rufina la burra", 82),
    (15, "Ricitos de Oro y los tres osos", 90),
    (16, "El camión", 100),
    (17, "Cuenta ratones", 109),
    (18, "Los tres cabritos y el ogro tragón", 118),
    (19, "Un huevo saltarín", 127),
    (20, "No oigo, no oigo: soy de palo", 132),
    (21, "El malora del corral", 139),
    (22, "Mariposa de papel", 146),
    (23, "La viejita y los quesos", 153),
    (24, "El teatro", 159),
    (25, "Los pececitos de colores", 168),
    (26, "La gallinita ciega", 173),
    (27, "La tierra de arena", 177),
    (28, "La bicicleta", 184),
    (29, "Los músicos de Bremen", 188),
    (30, "Un nuevo hermanito", 195),
    (31, "El sombrero de la bruja", 200),
    (32, "Una planta en el estómago", 206),
    (33, "Los zapatos del novio", 212),
    (34, "El gato con botas", 219),
    (35, "El doctor Milolores", 226),
    (36, "¡Se cayó el circo!", 231),
    (37, "El viento", 236),
    (38, "El lobo y las cabritas", 243),
    (39, "Robinson Crusoe", 249),
]


def detect_chapters(texts: list[str]) -> list[Chapter]:
    """Detecta las lecturas a partir del índice canónico o de los encabezados de página "N • Título"."""
    # Si parece ser el libro de lecturas de 1993 (contiene "Paco el Chato" y más de 100 páginas)
    all_combined = " ".join(texts[:30]).lower()
    if "paco" in all_combined and len(texts) >= 100:
        canonical_chapters: list[Chapter] = []
        for num, title, book_page in CANONICAL_LECTURAS_1993:
            best_idx = None
            title_words = [w for w in re.sub(r"\W+", " ", title.lower()).split() if len(w) > 3]
            for cand in range(max(0, book_page - 3), min(len(texts), book_page + 4)):
                page_txt = (texts[cand] or "").lower()
                if any(w in page_txt for w in title_words):
                    best_idx = cand
                    break
            if best_idx is None and book_page < len(texts):
                best_idx = book_page
            if best_idx is not None and (not canonical_chapters or best_idx > canonical_chapters[-1].page_index):
                canonical_chapters.append(Chapter(num, title, best_idx))
        if len(canonical_chapters) >= 30:
            return canonical_chapters

    # Fallback genérico para otros libros o pruebas unitarias
    first_header: dict[int, tuple[int, str]] = {}
    for i, text in enumerate(texts):
        for m in _HEADER_RE.finditer(text or ""):
            number = int(m.group(1))
            title = re.sub(r"\s*\d+$", "", m.group(2)).strip()
            if number > 0 and title:
                first_header.setdefault(number, (i, title))

    chapters: dict[int, Chapter] = {}
    for number, (header_idx, title) in first_header.items():
        start = header_idx
        key = _squash(title)
        for j in range(max(0, header_idx - 4), header_idx + 1):
            lines = [l for l in (texts[j] or "").splitlines() if l.strip()]
            squashed = {_squash(l) for l in lines if "•" not in l}
            opener = re.compile(r"\d{1,2}" + re.escape(key))
            if any(opener.fullmatch(s) for s in squashed) or (key in squashed and len(lines) <= 4):
                start = j
                break
        chapters[number] = Chapter(number, title, start)

    for i, text in enumerate(texts):
        lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
        if not 1 <= len(lines) <= 4:
            continue
        for line in lines:
            m = _OPENER_RE.fullmatch(line)
            if m and not re.search(r"\d$", m.group(2)):
                number = int(m.group(1))
                if number not in chapters:
                    chapters[number] = Chapter(number, m.group(2).strip(), i)

    ordered: list[Chapter] = []
    for ch in sorted(chapters.values(), key=lambda c: c.number):
        if not ordered or (ch.page_index > ordered[-1].page_index):
            ordered.append(ch)
    return ordered


def fix_epub_spine_properties(epub_path: Path) -> None:
    """Inyecta propiedades landscape fixed-layout en cada itemref del spine en content.opf."""
    with zipfile.ZipFile(epub_path, "r") as zin:
        items = {item.filename: zin.read(item.filename) for item in zin.infolist()}

    opf_names = [name for name in items if name.endswith(".opf")]
    if not opf_names:
        return
    opf_name = opf_names[0]
    opf_content = items[opf_name].decode("utf-8")

    # Inyectar properties en cada itemref del spine
    new_opf = re.sub(
        r'<itemref idref="([^"]+)"(/?>)',
        r'<itemref idref="\1" properties="rendition:layout-pre-paginated rendition:orientation-landscape"\2',
        opf_content,
    )
    items[opf_name] = new_opf.encode("utf-8")

    # Re-escribir el archivo EPUB manteniendo mimetype al inicio sin compresión (estándar OCF)
    with zipfile.ZipFile(epub_path, "w") as zout:
        if "mimetype" in items:
            zout.writestr("mimetype", items.pop("mimetype"), compress_type=zipfile.ZIP_STORED)
        for name, data in items.items():
            zout.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)


def normalize_page_font_sizes(lines: list[PageTextLine]) -> list[PageTextLine]:
    """Uniforma el tamaño de fuente para que todo el texto del cuerpo en la página tenga tamaño consistente."""
    if not lines:
        return lines

    header_indices = set()
    title_indices = set()
    body_indices = set()

    for idx, line in enumerate(lines):
        clean_str = line.text.strip()
        h = line.font_size_px
        if clean_str.isdigit() or (("libro de lecturas" in clean_str.lower() or "•" in clean_str) and h < 20.0):
            header_indices.add(idx)
        elif h > 38.0 or line.height_pct > 6.0:
            title_indices.add(idx)
        else:
            body_indices.add(idx)

    if body_indices:
        import statistics

        body_sizes = [lines[i].font_size_px for i in body_indices]
        median_size = round(statistics.median(body_sizes), 1)
        median_size = max(18.0, min(30.0, median_size))

        norm_lines = []
        for idx, line in enumerate(lines):
            if idx in body_indices:
                norm_lines.append(
                    PageTextLine(
                        top_pct=line.top_pct,
                        left_pct=line.left_pct,
                        width_pct=line.width_pct,
                        height_pct=line.height_pct,
                        font_size_px=median_size,
                        text=line.text,
                    )
                )
            else:
                norm_lines.append(line)
        return norm_lines

    return lines


_FONT_CACHE: dict[int, object] = {}


def _get_font(font_path: Path, size_px: float):
    """Obtiene y cachea una instancia de ImageFont para medir anchos de texto."""
    if not font_path.exists():
        return None
    sz = max(8, int(round(size_px)))
    if sz not in _FONT_CACHE:
        try:
            from PIL import ImageFont

            _FONT_CACHE[sz] = ImageFont.truetype(str(font_path), sz)
        except Exception:
            return None
    return _FONT_CACHE.get(sz)


def build_fixed_layout_epub(
    pages: list[PageImage],
    output_epub_path: Path,
    title: str,
    author: str = "SEP / CONALITEG",
    language: str = "es",
    chapters: list[Chapter] | None = None,
    canvas_width: int = 1034,
    canvas_height: int = 798,
) -> Path:
    """Genera un EPUB 3 horizontal (landscape) con imágenes en el fondo y texto encima."""
    if not pages:
        raise ValueError("No hay páginas para generar el EPUB")
    output_epub_path.parent.mkdir(parents=True, exist_ok=True)

    book = epub.EpubBook()
    book.set_identifier(f"urn:uuid:{uuid.uuid4()}")
    book.set_title(title)
    book.set_language(language)
    book.add_author(author)

    # Metadatos estándar de orientación horizontal (Landscape) y diseño fijo
    book.add_metadata(None, "meta", "pre-paginated", {"property": "rendition:layout"})
    book.add_metadata(None, "meta", "landscape", {"property": "rendition:orientation"})
    book.add_metadata(None, "meta", "none", {"property": "rendition:spread"})

    # Incorporar tipografía geométrica Quicksand embebida para garantizar fidelidad en cualquier dispositivo
    font_file = Path(__file__).parent / "assets" / "fonts" / "Quicksand.ttf"
    if font_file.exists():
        font_item = epub.EpubItem(
            uid="font_quicksand",
            file_name="fonts/Quicksand.ttf",
            media_type="font/ttf",
            content=font_file.read_bytes(),
        )
        book.add_item(font_item)

    css = epub.EpubItem(
        uid="style_landscape",
        file_name="style/landscape.css",
        media_type="text/css",
        content=LANDSCAPE_CSS,
    )
    book.add_item(css)

    docs: list[epub.EpubHtml] = []
    for idx, page in enumerate(pages):
        img_name = f"images/p{idx:04d}.{page.extension}"
        if idx == 0:
            # Portada del libro
            img_item = epub.EpubCover(uid="cover-img", file_name=img_name)
            img_item.media_type = page.media_type
            img_item.content = page.data
            book.add_metadata(None, "meta", "", {"name": "cover", "content": "cover-img"})
        else:
            img_item = epub.EpubItem(
                uid=f"img_{idx:04d}",
                file_name=img_name,
                media_type=page.media_type,
                content=page.data,
            )
        book.add_item(img_item)

        cleaned_text = clean_text(page.text)
        alt = html.escape(re.sub(r"\s+", " ", cleaned_text or f"Página {page.label}"), quote=True)
        doc = epub.EpubHtml(title=f"Página {page.label}", file_name=f"pages/p{idx:04d}.xhtml", lang=language)
        doc.add_meta(name="viewport", content=f"width={canvas_width}, height={canvas_height}")
        doc.add_link(href="../style/landscape.css", rel="stylesheet", type="text/css")

        if idx == 0:
            # 1. Portada: imagen a pantalla completa
            doc.content = f"""<div class="page-canvas cover-canvas">
  <img class="bg-image" src="../{img_name}" alt="{alt}" />
</div>"""
        else:
            # 2. Página de contenido: imagen completa en el fondo + capa de texto encima
            text_overlay_block = ""
            if page.lines:
                norm_lines = normalize_page_font_sizes(page.lines)
                spans = []
                for line in norm_lines:
                    cleaned_line = clean_text(line.text)
                    escaped_line = html.escape(cleaned_line, quote=True)
                    if not escaped_line:
                        continue

                    # Escalamiento horizontal exacto para alinear con las letras originales de la imagen
                    target_w = (line.width_pct / 100.0) * canvas_width
                    font_obj = _get_font(font_file, line.font_size_px)
                    scale_css = ""
                    if font_obj and target_w > 0:
                        try:
                            bbox = font_obj.getbbox(cleaned_line)
                            natural_w = max(1, bbox[2] - bbox[0])
                            scale_x = target_w / natural_w
                            if 0.25 <= scale_x <= 3.0:
                                scale_css = f" transform: scaleX({scale_x:.4f}); -webkit-transform: scaleX({scale_x:.4f});"
                        except Exception:
                            pass

                    # Ajuste fino vertical (+1.8px) para alinear la línea base de la fuente con las letras de la imagen
                    adj_top_pct = line.top_pct + (1.8 / canvas_height * 100.0)

                    style = (
                        f"top: {adj_top_pct:.2f}%; left: {line.left_pct:.2f}%; "
                        f"font-size: {line.font_size_px:.1f}px;{scale_css}"
                    )
                    spans.append(f'    <span class="text-line" style="{style}">{escaped_line}</span>')
                if spans:
                    text_overlay_block = '  <div class="text-layer">\n' + "\n".join(spans) + "\n  </div>"
            elif cleaned_text:
                paragraphs = []
                for block in re.split(r"\n\s*\n", cleaned_text):
                    lines = [html.escape(line.strip(), quote=True) for line in block.splitlines() if line.strip()]
                    if lines:
                        paragraphs.append(f"<p>{'<br/>'.join(lines)}</p>")
                if paragraphs:
                    text_html = "".join(paragraphs)
                    text_overlay_block = f"""  <div class="text-layer">
    <div class="ocr-text-overlay">
      {text_html}
    </div>
  </div>"""

            doc.content = f"""<div class="page-canvas">
  <img class="bg-image" src="../{img_name}" alt="{alt}" />
{text_overlay_block}
</div>"""

        book.add_item(doc)
        docs.append(doc)

    # Índice de navegación TOC
    if chapters:
        toc_entries = [epub.Link("pages/p0000.xhtml", "Portada", "toc_cover")]
        toc_entries += [
            epub.Link(docs[c.page_index].file_name, f"{c.number}. {c.title}", f"toc_{c.number}")
            for c in chapters
            if c.page_index < len(docs)
        ]
        book.toc = toc_entries
    else:
        book.toc = [d for i, d in enumerate(docs) if i % 10 == 0 or i == len(docs) - 1]

    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = docs

    print(f"📚 Escribiendo archivo EPUB (horizontal apaisado, {len(pages)} páginas): {output_epub_path}...")
    epub.write_epub(str(output_epub_path), book, {"epub3_pages": False})

    # Post-procesamiento para inyectar propiedades landscape en el spine
    fix_epub_spine_properties(output_epub_path)

    size_mb = output_epub_path.stat().st_size / (1024 * 1024)
    print(f"✅ ¡EPUB generado exitosamente! Tamaño: {size_mb:.2f} MB ({len(pages)} páginas)")
    return output_epub_path


def _image_page(path: Path, label: str, text: str = "", lines: list[PageTextLine] | None = None) -> PageImage:
    data = path.read_bytes()
    with Image.open(BytesIO(data)) as im:
        width, height = im.size
        fmt = (im.format or "JPEG").upper()
    media_type, ext = ("image/png", "png") if fmt == "PNG" else ("image/jpeg", "jpg")
    return PageImage(
        data=data,
        width=width,
        height=height,
        label=label,
        media_type=media_type,
        text=text,
        lines=lines or [],
        extension=ext,
    )


def build_epub_from_pages(
    images_dir: Path,
    texts_dir: Path | None,
    output_epub_path: Path,
    title: str = "Español. Primer Grado. Lecturas (1993)",
    author: str = "SEP / CONALITEG",
    cover_page: int = 0,
) -> Path:
    """Genera el EPUB horizontal con imágenes en el fondo y texto encima para todas las páginas."""
    import json

    image_files = sorted(list(images_dir.glob("*.jpg")) + list(images_dir.glob("*.png")))
    if not image_files:
        raise FileNotFoundError(f"No se encontraron imágenes en {images_dir}")

    # Colocar la portada al inicio si existe
    cover_name = f"{cover_page:03d}"
    image_files.sort(key=lambda p: (p.stem != cover_name, p.stem))

    pages: list[PageImage] = []
    for img_path in image_files:
        text = ""
        lines: list[PageTextLine] = []
        if texts_dir:
            json_path = texts_dir / f"{img_path.stem}.json"
            if json_path.exists():
                try:
                    data = json.loads(json_path.read_text(encoding="utf-8"))
                    text = data.get("text", "")
                    for l in data.get("lines", []):
                        lines.append(
                            PageTextLine(
                                top_pct=float(l["top_pct"]),
                                left_pct=float(l["left_pct"]),
                                width_pct=float(l["width_pct"]),
                                height_pct=float(l["height_pct"]),
                                font_size_px=float(l["font_size_px"]),
                                text=str(l["text"]),
                            )
                        )
                except Exception:
                    pass

            if not text:
                txt_path = texts_dir / f"{img_path.stem}.txt"
                if txt_path.exists():
                    text = txt_path.read_text(encoding="utf-8", errors="replace")

        label = str(int(img_path.stem)) if img_path.stem.isdigit() else img_path.stem
        pages.append(_image_page(img_path, label, text=text, lines=lines))

    chapters = detect_chapters([p.text for p in pages])
    print(f"📑 Lecturas detectadas para el índice: {len(chapters)}")
    return build_fixed_layout_epub(pages, output_epub_path, title=title, author=author, chapters=chapters)
