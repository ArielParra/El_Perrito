"""Módulo de compilación y manipulación de archivos PDF.

Permite generar documentos PDF de alta calidad a partir de las imágenes escaneadas
de CONALITEG, incorporando una capa invisible de texto OCR seleccionable y buscable
(formato Sandwich / Searchable PDF), idéntico al estándar de preservación digital.
"""

from __future__ import annotations

import json
from pathlib import Path
from PIL import Image
from tqdm import tqdm


def build_pdf_from_images(
    images_dir: Path,
    output_pdf_path: Path,
    texts_dir: Path | None = None,
    title: str = "Español. Primer Grado. Lecturas (1993)",
    author: str = "SEP / CONALITEG",
) -> Path:
    """Genera un archivo PDF de alta fidelidad a partir de las imágenes de la carpeta.

    Si se proporciona `texts_dir` con archivos JSON del OCR, inserta una capa
    de texto invisible (render mode 3) alineada con precisión sobre cada palabra,
    permitiendo seleccionar, copiar y buscar texto directamente en el PDF.
    """
    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    image_files = sorted(list(images_dir.glob("*.jpg")) + list(images_dir.glob("*.png")))
    if not image_files:
        raise FileNotFoundError(f"No se encontraron imágenes JPG o PNG en {images_dir}")

    has_ocr_layer = texts_dir is not None and texts_dir.exists() and any(texts_dir.glob("*.json"))

    if has_ocr_layer:
        print(f"\n📄 Compilando PDF buscable con capa de texto OCR a partir de {len(image_files)} páginas...")
        try:
            return _build_searchable_pdf_reportlab(
                image_files=image_files,
                texts_dir=texts_dir,
                output_pdf_path=output_pdf_path,
                title=title,
                author=author,
            )
        except Exception as exc:
            print(f"⚠️  Aviso: ReportLab reportó un error ({exc}). Usando empaquetado directo con img2pdf...")

    # Fallback sin capa de texto o si no hay OCR disponible
    print(f"\n📄 Compilando PDF a partir de {len(image_files)} páginas...")
    return _build_image_only_pdf(
        image_files=image_files,
        output_pdf_path=output_pdf_path,
        title=title,
        author=author,
    )


def _build_searchable_pdf_reportlab(
    image_files: list[Path],
    texts_dir: Path,
    output_pdf_path: Path,
    title: str,
    author: str,
) -> Path:
    """Genera el PDF con imagen de fondo y capa de texto OCR invisible (modo 3 de PDF)."""
    from reportlab.pdfgen import canvas

    with Image.open(image_files[0]) as first_im:
        default_w, default_h = first_im.size

    c = canvas.Canvas(str(output_pdf_path), pagesize=(default_w, default_h))
    c.setTitle(title)
    c.setAuthor(author)
    c.setCreator("PDF epub")
    c.setSubject("Catálogo Histórico CONALITEG")

    for img_path in tqdm(image_files, desc="Generando páginas PDF con texto"):
        with Image.open(img_path) as im:
            img_w, img_h = im.size

        c.setPageSize((img_w, img_h))

        # 1. Dibujar imagen de escaneo original
        c.drawImage(str(img_path), 0, 0, width=img_w, height=img_h)

        # 2. Inyectar capa de texto invisible (modo 3) posicionada exactamente
        json_path = texts_dir / f"{img_path.stem}.json"
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                for line in data.get("lines", []):
                    text = line.get("text", "").strip()
                    if not text:
                        continue

                    # Coordenadas relativas en porcentaje convertidas a píxeles
                    x = (line["left_pct"] / 100.0) * img_w
                    y_top = (line["top_pct"] / 100.0) * img_h
                    w = (line["width_pct"] / 100.0) * img_w
                    h = (line["height_pct"] / 100.0) * img_h

                    # En PDF el origen Y=0 es la esquina inferior izquierda.
                    # Calculamos la línea base exacta restando el margen superior.
                    baseline_y = img_h - (y_top + h * 0.82)
                    font_size = max(6.0, h * 0.85)

                    # Ajuste de escala horizontal para coincidencia exacta con el escaneo
                    natural_w = c.stringWidth(text, "Helvetica", font_size)
                    horiz_scale = (w / natural_w * 100.0) if natural_w > 0 else 100.0
                    horiz_scale = max(25.0, min(300.0, horiz_scale))

                    # Operador PDF de texto invisible (3 Tr): seleccionable y buscable
                    t = c.beginText()
                    t.setTextRenderMode(3)  # Invisible
                    t.setFont("Helvetica", font_size)
                    t.setHorizScale(horiz_scale)
                    t.setTextOrigin(x, baseline_y)
                    t.textOut(text)
                    c.drawText(t)
            except Exception:
                pass

        c.showPage()

    c.save()

    size_mb = output_pdf_path.stat().st_size / (1024 * 1024)
    print(f"✅ ¡PDF buscable generado exitosamente! Tamaño: {size_mb:.2f} MB ({len(image_files)} páginas)")
    print(f"📁 Ruta del archivo PDF: {output_pdf_path.resolve()}")
    return output_pdf_path


def _build_image_only_pdf(
    image_files: list[Path],
    output_pdf_path: Path,
    title: str,
    author: str,
) -> Path:
    """Fallback usando img2pdf o Pillow cuando no se requiere capa OCR."""
    try:
        import img2pdf

        pdf_bytes = img2pdf.convert(
            [str(p) for p in image_files],
            title=title,
            author=author,
            producer="PDF epub (CONALITEG)",
        )
        output_pdf_path.write_bytes(pdf_bytes)
    except Exception as exc:
        print(f"   (Aviso: img2pdf reportó '{exc}', usando fallback con Pillow...)")
        imgs = []
        for p in image_files:
            with Image.open(p) as im:
                imgs.append(im.convert("RGB"))
        if imgs:
            imgs[0].save(
                output_pdf_path,
                "PDF",
                resolution=150.0,
                save_all=True,
                append_images=imgs[1:],
                title=title,
                author=author,
            )

    size_mb = output_pdf_path.stat().st_size / (1024 * 1024)
    print(f"✅ ¡PDF generado exitosamente! Tamaño: {size_mb:.2f} MB ({len(image_files)} páginas)")
    print(f"📁 Ruta del archivo PDF: {output_pdf_path.resolve()}")
    return output_pdf_path
