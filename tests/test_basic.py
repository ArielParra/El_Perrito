"""Pruebas unitarias básicas para El perrito."""

from pathlib import Path
import zipfile
import pytest
from PIL import Image

from perrito.cli import parse_page_range
from perrito.config import CATALOG, DEFAULT_BOOK_ID, setup_tesseract_env
from perrito.ocr import preprocess_for_ocr
from perrito.epub import build_epub_from_pages


def test_catalog_contains_default_book():
    assert DEFAULT_BOOK_ID in CATALOG
    book = CATALOG[DEFAULT_BOOK_ID]
    assert book.year == 1993
    assert book.total_pages == 260


def test_parse_page_range():
    assert parse_page_range("0-3") == [0, 1, 2, 3]
    assert parse_page_range("0, 5, 8") == [0, 5, 8]
    assert parse_page_range("1-3, 5, 7-8") == [1, 2, 3, 5, 7, 8]


def test_preprocess_for_ocr(tmp_path):
    img = Image.new("RGB", (100, 100), color="red")
    processed = preprocess_for_ocr(img)
    assert processed.mode == "L"


def test_epub_generation(tmp_path):
    # Crear dos imágenes dummy
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    img1 = Image.new("RGB", (50, 50), color="white")
    img1.save(img_dir / "000.jpg")
    img2 = Image.new("RGB", (50, 50), color="blue")
    img2.save(img_dir / "001.jpg")

    txt_dir = tmp_path / "texts"
    txt_dir.mkdir()
    (txt_dir / "000.txt").write_text("Texto portada", encoding="utf-8")
    (txt_dir / "001.txt").write_text("Párrafo de prueba", encoding="utf-8")

    epub_out = tmp_path / "salida.epub"
    build_epub_from_pages(
        images_dir=img_dir,
        texts_dir=txt_dir,
        output_epub_path=epub_out,
        title="Libro Test",
    )

    assert epub_out.exists()
    assert epub_out.stat().st_size > 0

    with zipfile.ZipFile(epub_out, "r") as zf:
        names = zf.namelist()
        assert "mimetype" in names
        assert "META-INF/container.xml" in names
        assert "EPUB/content.opf" in names
        assert "EPUB/nav.xhtml" in names

        opf = zf.read("EPUB/content.opf").decode("utf-8")
        assert 'property="rendition:layout">pre-paginated' in opf
        assert 'property="rendition:orientation">landscape' in opf
        assert 'properties="cover-image"' in opf

        page = zf.read("EPUB/pages/p0001.xhtml").decode("utf-8")
        assert 'content="width=1034, height=798"' in page
        assert "<img" in page
        assert "bg-image" in page
        assert "<p>Párrafo de prueba</p>" in page
        assert "ocr-text-overlay" in page


def test_detect_chapters_from_running_headers():
    from perrito.epub import detect_chapters

    texts = [
        "Índice 1 Paco el Chato \n7\n2 Saltan y saltan 13",
        "7\n1 Paco el Chato",
        "Libro de lecturas\n8\nPaco vivía en un rancho.",
        "1 • Paco el Chato\n9\nAl llegar a la escuela",
        "13\n2 Saltan y saltan",
        "2 • Saltan y saltan 15\nTexto",
    ]
    chapters = detect_chapters(texts)
    assert [(c.number, c.title, c.page_index) for c in chapters] == [
        (1, "Paco el Chato", 1),
        (2, "Saltan y saltan", 4),
    ]


def test_ocr_text_is_escaped_for_xhtml():
    from perrito.epub import ocr_text_to_xhtml
    out = ocr_text_to_xhtml("a <xaac & b\x0c\n\nfin")
    assert "<xaac" not in out
    assert "&lt;xaac &amp; b" in out
    assert "\x0c" not in out
    assert out.count("<p>") == 2


def test_epub_generation_with_positioned_lines(tmp_path):
    from io import BytesIO
    from perrito.epub import PageImage, PageTextLine, build_fixed_layout_epub

    buf = BytesIO()
    Image.new("RGB", (100, 77), color="white").save(buf, format="JPEG")
    img_data = buf.getvalue()

    lines = [
        PageTextLine(top_pct=10.0, left_pct=15.0, width_pct=30.0, height_pct=5.0, font_size_px=18.0, text="Paco el Chato"),
        PageTextLine(top_pct=20.0, left_pct=15.0, width_pct=40.0, height_pct=5.0, font_size_px=18.0, text="vivía en un rancho."),
    ]
    pages = [
        PageImage(data=img_data, width=100, height=77, label="1"),
        PageImage(data=img_data, width=100, height=77, label="2", lines=lines, text="Paco el Chato\nvivía en un rancho."),
    ]

    out_epub = tmp_path / "test_positioned.epub"
    build_fixed_layout_epub(pages, out_epub, title="Test Positioned")

    assert out_epub.exists()
    with zipfile.ZipFile(out_epub, "r") as zf:
        p2 = zf.read("EPUB/pages/p0001.xhtml").decode("utf-8")
        assert 'class="text-line"' in p2
        assert 'left: 15.00%' in p2
        assert 'font-size: 18.0px' in p2
        assert 'transform: scaleX(' in p2
        assert "Paco el Chato" in p2
        assert "vivía en un rancho." in p2
        assert 'properties="rendition:layout-pre-paginated rendition:orientation-landscape"' in zf.read("EPUB/content.opf").decode("utf-8")


def test_clean_spanish_ocr_text():
    from perrito.ocr import clean_spanish_ocr_text

    raw = "Finalmente, hall6 otros tres ratones: Y los conto:—-Ocho...nueve...iez. comere—dijola serpiente."
    cleaned = clean_spanish_ocr_text(raw)
    assert "halló" in cleaned
    assert "contó" in cleaned
    assert "diez" in cleaned
    assert "comeré" in cleaned
    assert "dijo la" in cleaned


def test_normalize_page_font_sizes():
    from perrito.epub import PageTextLine, normalize_page_font_sizes

    lines = [
        PageTextLine(top_pct=3.0, left_pct=50.0, width_pct=3.0, height_pct=2.0, font_size_px=15.0, text="113"),
        PageTextLine(top_pct=80.0, left_pct=10.0, width_pct=30.0, height_pct=4.0, font_size_px=27.2, text="Línea 1"),
        PageTextLine(top_pct=84.0, left_pct=10.0, width_pct=30.0, height_pct=4.5, font_size_px=30.6, text="Línea 2"),
        PageTextLine(top_pct=88.0, left_pct=10.0, width_pct=30.0, height_pct=3.6, font_size_px=24.6, text="Línea 3"),
    ]
    norm = normalize_page_font_sizes(lines)
    # El encabezado/número de página debe mantener su tamaño
    assert norm[0].font_size_px == 15.0
    # Todas las líneas del cuerpo deben tener un tamaño unificado igual a la mediana (27.2)
    assert norm[1].font_size_px == 27.2
    assert norm[2].font_size_px == 27.2
    assert norm[3].font_size_px == 27.2


def test_extract_book_id_from_url():
    from perrito.config import extract_book_id

    assert extract_book_id("https://historico.conaliteg.gob.mx/H1993P1ES139.htm#page/1") == "H1993P1ES139"
    assert extract_book_id("https://historico.conaliteg.gob.mx/H1993P1ES139.htm") == "H1993P1ES139"
    assert extract_book_id("http://historico.conaliteg.gob.mx/c/H1993P1ES139/005.jpg") == "H1993P1ES139"
    assert extract_book_id("H1993P1ES139") == "H1993P1ES139"
    assert extract_book_id("h1993p1es139") == "H1993P1ES139"


def test_build_pdf_from_images(tmp_path):
    from perrito.pdf import build_pdf_from_images

    img_dir = tmp_path / "images"
    img_dir.mkdir()
    Image.new("RGB", (60, 40), color="red").save(img_dir / "000.jpg")
    Image.new("RGB", (60, 40), color="blue").save(img_dir / "001.jpg")

    pdf_out = tmp_path / "test.pdf"
    build_pdf_from_images(img_dir, pdf_out, title="Test PDF")

    assert pdf_out.exists()
    assert pdf_out.stat().st_size > 500


def test_build_searchable_pdf_with_ocr_layer(tmp_path):
    import json
    from perrito.pdf import build_pdf_from_images
    import pypdfium2 as pdfium

    img_dir = tmp_path / "images"
    img_dir.mkdir()
    Image.new("RGB", (200, 100), color="white").save(img_dir / "000.jpg")

    txt_dir = tmp_path / "texts"
    txt_dir.mkdir()
    ocr_data = {
        "page": "000",
        "lines": [
            {
                "top_pct": 20.0,
                "left_pct": 10.0,
                "width_pct": 50.0,
                "height_pct": 15.0,
                "font_size_px": 14.0,
                "text": "Texto Buscable en PDF",
            }
        ],
    }
    (txt_dir / "000.json").write_text(json.dumps(ocr_data), encoding="utf-8")

    pdf_out = tmp_path / "searchable.pdf"
    build_pdf_from_images(img_dir, pdf_out, texts_dir=txt_dir, title="Test Searchable")

    assert pdf_out.exists()
    doc = pdfium.PdfDocument(str(pdf_out))
    text = doc[0].get_textpage().get_text_range()
    assert "Texto Buscable en PDF" in text
    doc.close()



