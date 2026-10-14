"""Configuración general y catálogo de libros históricos de CONALITEG."""

from dataclasses import dataclass
from pathlib import Path
import os

DEFAULT_BASE_URL = "https://historico.conaliteg.gob.mx/c/{book_id}/{page:03d}.jpg"

# Ruta para tessdata local si existe en el proyecto
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOCAL_TESSDATA = PROJECT_ROOT / "tessdata"


@dataclass(frozen=True)
class BookMetadata:
    id: str
    title: str
    grade: str
    year: int
    total_pages: int
    cover_page: int = 0
    description: str = ""


# Catálogo inicial de libros históricos destacados
CATALOG: dict[str, BookMetadata] = {
    "H1993P1ES139": BookMetadata(
        id="H1993P1ES139",
        title="Español. Primer Grado. Lecturas (El libro del perrito)",
        grade="1° Primaria",
        year=1993,
        total_pages=260,
        cover_page=0,
        description="Libro clásico de lecturas de la generación 1993 con Paco el Chato, Los changuitos y más.",
    ),
}

# AVISO DE COMPATIBILIDAD:
# Solo "Español. Primer Grado. Lecturas" (H1993P1ES139) fue probado;
# los demás libros del acervo CONALITEG podrían funcionar pero no se probarán.
DEFAULT_BOOK_ID = "H1993P1ES139"
CLAVES_URL = "https://historico.conaliteg.gob.mx/claves.json"


def extract_book_id(url_or_id: str) -> str:
    """Extrae la clave del libro (ej. 'H1993P1ES139') a partir de una URL o clave directa."""
    import re

    raw = (url_or_id or "").strip()
    if not raw:
        return DEFAULT_BOOK_ID

    # Caso 1: URL con .htm (ej. https://historico.conaliteg.gob.mx/H1993P1ES139.htm#page/1)
    m = re.search(r"/([A-Za-z0-9_]+)\.htm", raw, re.I)
    if m:
        return m.group(1).upper()

    # Caso 2: URL con /c/{book_id}/ (ej. https://historico.conaliteg.gob.mx/c/H1993P1ES139/001.jpg)
    m = re.search(r"/c/([A-Za-z0-9_]+)/", raw, re.I)
    if m:
        return m.group(1).upper()

    # Caso 3: Clave directa alfanumérica típica (ej. H1993P1ES139)
    m = re.search(r"\b([A-Z0-9]{6,20})\b", raw, re.I)
    if m:
        return m.group(1).upper()

    return raw


def fetch_book_info(url_or_id: str, timeout: float = 6.0) -> BookMetadata:
    """Obtiene metadatos del libro desde el catálogo local o mediante consulta remota a claves.json."""
    import json
    import re
    from urllib.request import Request, urlopen

    book_id = extract_book_id(url_or_id)
    if book_id in CATALOG:
        return CATALOG[book_id]

    total_pages = 260
    title = f"Libro {book_id}"

    # 1. Intentar consultar total de páginas en claves.json
    try:
        req = Request(CLAVES_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if book_id in data:
                total_pages = int(data[book_id].get("ag_pages", 260))
    except Exception:
        pass

    # 2. Intentar consultar título de la página HTML
    try:
        page_url = f"https://historico.conaliteg.gob.mx/{book_id}.htm"
        req = Request(page_url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            m_title = re.search(r"<title>(.*?)(?:\.:|\.\s*:|CONALITEG|</title>)", html, re.I)
            if m_title and m_title.group(1).strip():
                title = m_title.group(1).strip()
    except Exception:
        pass

    return BookMetadata(
        id=book_id,
        title=title,
        grade="",
        year=1993 if "1993" in book_id else 0,
        total_pages=total_pages,
        description="Libro histórico CONALITEG (no probado)",
    )


def setup_tesseract_env() -> str:
    """Configura la variable de entorno TESSDATA_PREFIX si existe la carpeta local tessdata."""
    if LOCAL_TESSDATA.exists() and (LOCAL_TESSDATA / "spa.traineddata").exists():
        os.environ["TESSDATA_PREFIX"] = str(LOCAL_TESSDATA)
        return str(LOCAL_TESSDATA)
    return os.environ.get("TESSDATA_PREFIX", "")
