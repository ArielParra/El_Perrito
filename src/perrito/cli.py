"""Punto de entrada de línea de comandos (CLI) unificado para PDF epub.

Generador de archivos PDF y EPUB 3 a partir de URLs o claves del catálogo
histórico de CONALITEG (ej. https://historico.conaliteg.gob.mx/H1993P1ES139.htm#page/1).

AVISO DE COMPATIBILIDAD:
Solo "Español. Primer Grado. Lecturas" (Generación 1993, clave H1993P1ES139) fue probado;
los demás libros de CONALITEG podrían funcionar con su URL o clave, pero no se probarán.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .config import CATALOG, DEFAULT_BOOK_ID, extract_book_id, fetch_book_info
from .download import download_book
from .ocr import ocr_batch
from .epub import build_epub_from_pages
from .pdf import build_pdf_from_images


def parse_page_range(range_str: str) -> list[int]:
    """Parsea una lista o rango de páginas como '0-4' o '0,1,2,5'."""
    pages = set()
    for part in range_str.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            pages.update(range(int(start), int(end) + 1))
        elif part.isdigit():
            pages.add(int(part))
    return sorted(list(pages))


def cmd_download(args) -> int:
    target = args.url or args.book or DEFAULT_BOOK_ID
    book_id = extract_book_id(target)
    out_dir = Path(args.out) if args.out else Path(f"{book_id}_paginas")

    download_book(
        book_id=book_id,
        start_page=args.start,
        end_page=args.end,
        output_dir=out_dir,
        max_workers=args.workers,
        create_zip=args.zip,
        zip_path=Path(args.zip_name) if args.zip_name else None,
    )
    return 0


def cmd_pdf(args) -> int:
    target = args.url or args.book or DEFAULT_BOOK_ID
    book_id = extract_book_id(target)
    book_info = fetch_book_info(book_id)

    images_dir = Path(args.images) if args.images else Path(f"{book_id}_paginas")
    if not images_dir.exists() or not any(images_dir.glob("*.jpg")):
        print(f"📥 Imágenes no encontradas en '{images_dir}'. Descargando automáticamente...")
        download_book(book_id=book_id, output_dir=images_dir)

    default_out = "dist/Espanol_Lecturas_1993_1er_Grado.pdf" if book_id == DEFAULT_BOOK_ID else f"dist/{book_id}.pdf"
    out_pdf = Path(args.out) if args.out else Path(default_out)
    title = args.title or book_info.title
    author = args.author
    texts_dir = Path(args.texts) if getattr(args, "texts", None) else Path("ocr_texto")

    # Si no existen coordenadas OCR y el usuario no indicó --no-ocr, ejecutar OCR primero
    no_ocr = getattr(args, "no_ocr", False)
    if not no_ocr and not (texts_dir.exists() and any(texts_dir.glob("*.json"))):
        print("🔍 Coordenadas OCR no encontradas. Ejecutando Baidu PP-OCR para capa de texto en el PDF...")
        ocr_batch(
            images_dir=images_dir,
            output_dir=texts_dir,
            engine="rapid",
            force=False,
        )

    build_pdf_from_images(
        images_dir=images_dir,
        output_pdf_path=out_pdf,
        texts_dir=texts_dir if not no_ocr else None,
        title=title,
        author=author,
    )
    return 0


def cmd_ocr(args) -> int:
    images_dir = Path(args.images)
    if not images_dir.exists():
        print(f"❌ Error: La carpeta de imágenes '{images_dir}' no existe. Ejecuta 'download' primero.")
        return 1

    pages = parse_page_range(args.pages) if args.pages else None
    output_dir = Path(args.out)
    ref_pdf = Path(args.ref_pdf) if args.ref_pdf and Path(args.ref_pdf).exists() else None

    ocr_batch(
        images_dir=images_dir,
        output_dir=output_dir,
        pages=pages,
        engine=args.engine,
        lang=args.lang,
        psm=args.psm,
        preprocess=not args.no_preprocess,
        max_workers=args.workers,
        ref_pdf=ref_pdf,
        force=args.force,
    )
    return 0


def cmd_build(args) -> int:
    target = getattr(args, "url", None) or getattr(args, "book", None) or DEFAULT_BOOK_ID
    book_id = extract_book_id(target)
    book_info = fetch_book_info(book_id)

    images_dir = Path(args.images) if args.images else Path(f"{book_id}_paginas")
    if not images_dir.exists() or not any(images_dir.glob("*.jpg")):
        print(f"📥 Imágenes no encontradas en '{images_dir}'. Descargando automáticamente...")
        download_book(book_id=book_id, output_dir=images_dir)

    default_out = "dist/Espanol_Lecturas_1993_1er_Grado.epub" if book_id == DEFAULT_BOOK_ID else f"dist/{book_id}.epub"
    output_epub = Path(args.out) if args.out else Path(default_out)
    title = args.title or book_info.title
    texts_dir = Path(args.texts)
    ref_pdf = Path(args.ref_pdf) if args.ref_pdf and Path(args.ref_pdf).exists() else None

    # Verificar si ya existen los archivos JSON con coordenadas del OCR
    has_json_coords = texts_dir.exists() and any(texts_dir.glob("*.json"))
    if not has_json_coords:
        print("🔍 Coordenadas OCR no encontradas. Ejecutando Baidu PP-OCR con cajas delimitadoras...")
        ocr_batch(
            images_dir=images_dir,
            output_dir=texts_dir,
            engine="rapid",
            ref_pdf=ref_pdf,
            force=False,
        )

    print(f"📚 Compilando EPUB a partir de las imágenes ({images_dir}) y texto posicionado ({texts_dir})...")
    build_epub_from_pages(
        images_dir=images_dir,
        texts_dir=texts_dir,
        output_epub_path=output_epub,
        title=title,
        author=args.author,
    )
    return 0


def cmd_info(args) -> int:
    print("\n" + "=" * 70)
    print("📖 El perrito 🐶 - Catálogo de libros históricos de CONALITEG")
    print("⚠️  AVISO: Solo 'Español. Primer Grado. Lecturas' (1993) fue probado;")
    print("   los demás libros podrían funcionar con su URL pero no se probarán.")
    print("=" * 70)

    if args.url:
        book_id = extract_book_id(args.url)
        meta = fetch_book_info(book_id)
        print(f"\n🔍 Información extraída para la URL/clave '{args.url}':")
        print(f"   • Clave: {meta.id}")
        print(f"   • Título: {meta.title}")
        print(f"   • Total de páginas estimadas: {meta.total_pages}")
        print(f"   • Carpeta sugerida de imágenes: {meta.id}_paginas")
        return 0

    for book_id, meta in CATALOG.items():
        print(f"\n  • [{book_id}] {meta.title}")
        print(f"    - Grado: {meta.grade} | Año: {meta.year} | Total de páginas: {meta.total_pages}")
        print(f"    - Descripción: {meta.description}")
        print(f"    - URL directa: https://historico.conaliteg.gob.mx/{book_id}.htm#page/1")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="perrito",
        description="El perrito 🐶 - Generador de archivos PDF y EPUB a partir de URLs o claves de CONALITEG",
        epilog="Ejemplo: perrito pdf --url https://historico.conaliteg.gob.mx/H1993P1ES139.htm#page/1",
    )
    subparsers = parser.add_subparsers(dest="command", help="Comando a ejecutar")

    # Subcomando: download
    p_dl = subparsers.add_parser("download", help="Descargar imágenes de las páginas del libro (URL o clave)")
    p_dl.add_argument("url_pos", nargs="?", default=None, help="Opcional: URL de CONALITEG o clave del libro")
    p_dl.add_argument("--url", default=None, help="URL de CONALITEG (ej. https://historico.conaliteg.gob.mx/H1993P1ES139.htm#page/1)")
    p_dl.add_argument("--book", default=None, help=f"Clave del libro en CONALITEG (por defecto: {DEFAULT_BOOK_ID})")
    p_dl.add_argument("--start", type=int, default=0, help="Página inicial (por defecto: 0)")
    p_dl.add_argument("--end", type=int, default=None, help="Página final (por defecto: última según catálogo)")
    p_dl.add_argument("--out", default=None, help="Carpeta de salida para las imágenes")
    p_dl.add_argument("--workers", type=int, default=8, help="Número de hilos concurrentes para la descarga")
    p_dl.add_argument("--zip", action="store_true", help="Crear archivo ZIP con todas las imágenes")
    p_dl.add_argument("--zip-name", default=None, help="Nombre del archivo ZIP si se especifica --zip")
    p_dl.set_defaults(func=lambda args: _dispatch_with_pos(args, cmd_download))

    # Subcomando: pdf (generar PDF a partir de URL o carpeta de imágenes)
    p_pdf = subparsers.add_parser("pdf", help="Generar documento PDF de alta calidad a partir de URL o imágenes")
    p_pdf.add_argument("url_pos", nargs="?", default=None, help="Opcional: URL de CONALITEG o clave del libro")
    p_pdf.add_argument("--url", default=None, help="URL de CONALITEG (ej. https://historico.conaliteg.gob.mx/H1993P1ES139.htm#page/1)")
    p_pdf.add_argument("--book", default=None, help=f"Clave del libro (por defecto: {DEFAULT_BOOK_ID})")
    p_pdf.add_argument("--images", default=None, help="Carpeta con las imágenes (por defecto: {book_id}_paginas)")
    p_pdf.add_argument("--texts", default="ocr_texto", help="Carpeta con los archivos JSON del OCR para inyectar capa de texto buscable")
    p_pdf.add_argument("--no-ocr", action="store_true", help="No inyectar capa de texto OCR en el PDF (solo imágenes)")
    p_pdf.add_argument("--out", default=None, help="Ruta del archivo PDF de salida")
    p_pdf.add_argument("--title", default=None, help="Título del documento PDF")
    p_pdf.add_argument("--author", default="SEP / CONALITEG", help="Autor o entidad editora")
    p_pdf.set_defaults(func=lambda args: _dispatch_with_pos(args, cmd_pdf))

    # Subcomando: ocr
    p_ocr = subparsers.add_parser("ocr", help="Reconocer texto de las páginas usando OCR en español")
    p_ocr.add_argument("--images", default=f"{DEFAULT_BOOK_ID}_paginas", help="Carpeta con las imágenes JPG")
    p_ocr.add_argument("--out", default="ocr_texto", help="Carpeta donde guardar los archivos de texto y coordenadas")
    p_ocr.add_argument("--engine", default="rapid", choices=["rapid", "tesseract"], help="Motor OCR a usar (por defecto: rapid / Baidu PP-OCR)")
    p_ocr.add_argument("--pages", default=None, help="Páginas específicas a procesar (ej. '0-4' o '0,1,5')")
    p_ocr.add_argument("--ref-pdf", default=None, help="Opcional: PDF de referencia")
    p_ocr.add_argument("--force", action="store_true", help="Forzar re-ejecución del OCR incluso si ya existen los archivos")
    p_ocr.add_argument("--lang", default="spa", help="Idioma para Tesseract (por defecto: spa)")
    p_ocr.add_argument("--psm", type=int, default=6, help="Page segmentation mode para Tesseract (por defecto: 6)")
    p_ocr.add_argument("--workers", type=int, default=4, help="Número de hilos concurrentes para OCR (por defecto: 4)")
    p_ocr.add_argument("--no-preprocess", action="store_true", help="Desactivar preprocesamiento de contraste")
    p_ocr.set_defaults(func=cmd_ocr)

    # Subcomando: build (compilar EPUB)
    p_build = subparsers.add_parser("build", help="Compilar archivo EPUB con imágenes y textos")
    _setup_build_args(p_build)
    p_build.set_defaults(func=lambda args: _dispatch_with_pos(args, cmd_build))

    # Subcomando: epub (alias directo de build)
    p_epub = subparsers.add_parser("epub", help="Compilar archivo EPUB con imágenes y textos (alias de build)")
    _setup_build_args(p_epub)
    p_epub.set_defaults(func=lambda args: _dispatch_with_pos(args, cmd_build))

    # Subcomando: info
    p_info = subparsers.add_parser("info", help="Ver información del catálogo o consultar una URL")
    p_info.add_argument("url_pos", nargs="?", default=None, help="Opcional: URL o clave de libro a consultar")
    p_info.add_argument("--url", default=None, help="URL de CONALITEG a consultar")
    p_info.set_defaults(func=lambda args: _dispatch_with_pos(args, cmd_info))

    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0

    return args.func(args)


def _setup_build_args(p_sub):
    p_sub.add_argument("url_pos", nargs="?", default=None, help="Opcional: URL de CONALITEG o clave del libro")
    p_sub.add_argument("--url", default=None, help="URL de CONALITEG (ej. https://historico.conaliteg.gob.mx/H1993P1ES139.htm#page/1)")
    p_sub.add_argument("--book", default=None, help=f"Clave del libro (por defecto: {DEFAULT_BOOK_ID})")
    p_sub.add_argument("--images", default=None, help="Carpeta con las imágenes oficiales de CONALITEG")
    p_sub.add_argument("--texts", default="ocr_texto", help="Carpeta con los textos y cajas delimitadoras del OCR")
    p_sub.add_argument("--out", default=None, help="Ruta del archivo EPUB generado")
    p_sub.add_argument("--title", default=None, help="Título del libro")
    p_sub.add_argument("--author", default="SEP / CONALITEG", help="Autor o entidad editora")
    p_sub.add_argument("--ref-pdf", default=None, help="Opcional: PDF de referencia")


def _dispatch_with_pos(args, target_func):
    if hasattr(args, "url_pos") and args.url_pos and not getattr(args, "url", None) and not getattr(args, "book", None):
        if "http" in args.url_pos or "/" in args.url_pos:
            args.url = args.url_pos
        else:
            args.book = args.url_pos
    return target_func(args)


if __name__ == "__main__":
    sys.exit(main())
