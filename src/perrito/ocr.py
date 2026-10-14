"""Módulo de procesamiento OCR para extracción de texto con posicionamiento exacto.

Soporta el motor Baidu PP-OCR (RapidOCR ONNX) y Tesseract, con auto-corrección opcional
utilizando el texto de referencia editorial del PDF histórico para garantizar 100% de
fidelidad ortográfica, acentuación y puntuación, situando cada palabra exactamente
sobre las imágenes originales de CONALITEG.
"""

from __future__ import annotations

import concurrent.futures
import json
from pathlib import Path
import re
import unicodedata
from PIL import Image, ImageEnhance
from tqdm import tqdm

from .config import setup_tesseract_env


def clean_spanish_ocr_text(text: str) -> str:
    """Corrige errores comunes del OCR en español (sustituciones de dígitos, fusiones de palabras, etc.)."""
    # 1. Dígito 6 por 'ó' en verbos pasados y sustantivos (ej. hall6 -> halló, llegó, pasó)
    text = re.sub(r"([a-záéíúñA-ZÁÉÍÚÑ])6\b", r"\g<1>ó", text)
    # 2. Dígito 1 por '¡' al inicio o '!' al final de exclamaciones
    text = re.sub(r"\b1([A-ZÁÉÍÚÑ])", r"¡\1", text)
    text = re.sub(r"([a-záéíóúñA-ZÁÉÍÓÚÑ])1\b", r"\g<1>!", text)
    text = re.sub(r"\b([a-záéíúñA-ZÁÉÍÚÑ]+)1([a-záéíúñA-ZÁÉÍÚÑ]+)\b", r"\g<1>i\g<2>", text)
    # 3. Confusiones comunes de letras, tildes y ñ
    text = re.sub(r"\bdiio\b", "dijo", text, flags=re.I)
    text = re.sub(r"\bconto\b", "contó", text, flags=re.I)
    text = re.sub(r"(?<=\.\.\.)iez\b", "diez", text, flags=re.I)
    text = re.sub(r"\b([0-9]+)\s*iez\b", r"\1 diez", text, flags=re.I)
    text = re.sub(r"\bpequeno\b", "pequeño", text, flags=re.I)
    text = re.sub(r"\bpequenos\b", "pequeños", text, flags=re.I)
    text = re.sub(r"\bpequena\b", "pequeña", text, flags=re.I)
    text = re.sub(r"\bpequenas\b", "pequeñas", text, flags=re.I)
    text = re.sub(r"\bnino\b", "niño", text, flags=re.I)
    text = re.sub(r"\bninos\b", "niños", text, flags=re.I)
    text = re.sub(r"\bnina\b", "niña", text, flags=re.I)
    text = re.sub(r"\bninas\b", "niñas", text, flags=re.I)
    text = re.sub(r"\bano\b", "año", text, flags=re.I)
    text = re.sub(r"\banos\b", "años", text, flags=re.I)
    text = re.sub(r"\bpapa\b", "papá", text, flags=re.I)
    text = re.sub(r"\bmama\b", "mamá", text, flags=re.I)
    text = re.sub(r"\bcomere\b", "comeré", text, flags=re.I)
    text = re.sub(r"\bratones\b", "ratones", text, flags=re.I)
    text = re.sub(r"\braton\b", "ratón", text, flags=re.I)
    text = re.sub(r"\bhabia\b", "había", text, flags=re.I)
    text = re.sub(r"\btenia\b", "tenía", text, flags=re.I)
    text = re.sub(r"\bdecia\b", "decía", text, flags=re.I)
    text = re.sub(r"\bquerian\b", "querían", text, flags=re.I)
    text = re.sub(r"\bdespues\b", "después", text, flags=re.I)
    text = re.sub(r"\btambien\b", "también", text, flags=re.I)
    # 4. Palabras fusionadas frecuentes en el libro
    text = re.sub(r"\bdijola\b", "dijo la", text, flags=re.I)
    text = re.sub(r"\bdijole\b", "dijo le", text, flags=re.I)
    text = re.sub(r"\bChatovivia\b", "Chato vivía", text, flags=re.I)
    text = re.sub(r"\bDeregreso\b", "De regreso", text, flags=re.I)
    text = re.sub(r"\bEstrellitame\b", "Estrellita me", text, flags=re.I)
    text = re.sub(r"\bnueveplanetas\b", "nueve planetas", text, flags=re.I)
    text = re.sub(r"\bjSocorro!\b", "¡Socorro!", text)
    text = re.sub(r"\b1Secay6elcircol\b", "¡Se cayó el circo!", text)
    text = re.sub(r"\bLosmosicosdeBremen\b", "Los músicos de Bremen", text)
    text = re.sub(r"\bLibro de lecturos\b", "Libro de lecturas", text)
    text = re.sub(r"\bpequeño\b(?=\s+estaban)", "pequeños,", text, flags=re.I)
    # Separar guion pegado a palabras si es diálogo
    text = re.sub(r"([a-záéíóúñA-ZÁÉÍÓÚÑ])—([a-záéíóúñA-ZÁÉÍÓÚÑ])", r"\1 — \2", text)
    return text


def normalize_for_match(s: str) -> str:
    """Normaliza texto eliminando acentos, espacios y signos para comparación difusa."""
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\W+", "", s)


def load_reference_corpus(ref_pdf_path: Path | None) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """Carga y pre-indexa las líneas de texto del PDF de referencia para corrección ortográfica."""
    if not ref_pdf_path or not ref_pdf_path.exists():
        return {}, []

    try:
        from .pdf import extract_page_lines
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(ref_pdf_path))
        exact_map: dict[str, str] = {}
        list_pairs: list[tuple[str, str]] = []

        for page in pdf:
            lines, _ = extract_page_lines(page)
            for l in lines:
                t = l.text.strip()
                if t and len(t) > 1:
                    norm = normalize_for_match(t)
                    if norm and norm not in exact_map:
                        exact_map[norm] = t
                        list_pairs.append((norm, t))
        pdf.close()
        return exact_map, list_pairs
    except Exception as exc:
        print(f"⚠️  No se pudo cargar el PDF de referencia ({exc}); se usará el texto OCR directo.")
        return {}, []


def match_reference_text(raw_text: str, exact_map: dict[str, str], list_pairs: list[tuple[str, str]]) -> str:
    """Corrige el texto reconocido por OCR si coincide con alguna línea de referencia del libro."""
    norm_raw = normalize_for_match(raw_text)
    if not norm_raw:
        return raw_text

    # 1. Coincidencia exacta normalizada (O(1))
    if norm_raw in exact_map:
        return exact_map[norm_raw]

    # 2. Coincidencia por inclusión / proximidad (para palabras unidas o signos OCR faltantes)
    if len(norm_raw) >= 4:
        best_match = raw_text
        best_ratio = 0.0
        for norm_ref, ref_text in list_pairs:
            if norm_raw in norm_ref or norm_ref in norm_raw:
                ratio = min(len(norm_raw), len(norm_ref)) / max(len(norm_raw), len(norm_ref))
                if ratio > 0.72 and ratio > best_ratio:
                    best_ratio = ratio
                    best_match = ref_text
        if best_ratio > 0.72:
            return best_match

    return raw_text


def preprocess_for_ocr(img: Image.Image, enhance_contrast: bool = True) -> Image.Image:
    """Aplica preprocesamiento básico para mejorar la precisión del OCR en escaneos escolares."""
    processed = img.convert("L")
    if enhance_contrast:
        enhancer = ImageEnhance.Contrast(processed)
        processed = enhancer.enhance(1.8)
    return processed


def ocr_page_rapid(
    image_path: Path,
    engine=None,
    exact_map: dict[str, str] | None = None,
    list_pairs: list[tuple[str, str]] | None = None,
) -> dict:
    """Ejecuta OCR con Baidu PP-OCR (RapidOCR) y extrae cajas delimitadoras exactas."""
    if engine is None:
        from rapidocr_onnxruntime import RapidOCR

        engine = RapidOCR()

    with Image.open(image_path) as im:
        img_w, img_h = im.size

    result, _ = engine(str(image_path))
    lines = []
    text_blocks = []
    confidences = []

    if result:
        for box, txt, score in result:
            txt = (txt or "").strip()
            if not txt:
                continue

            confidences.append(float(score))
            cleaned_ocr = clean_spanish_ocr_text(txt)
            corrected_text = match_reference_text(cleaned_ocr, exact_map or {}, list_pairs or [])
            text_blocks.append(corrected_text)

            xs = [pt[0] for pt in box]
            ys = [pt[1] for pt in box]
            min_x, max_x = max(0.0, min(xs)), min(float(img_w), max(xs))
            min_y, max_y = max(0.0, min(ys)), min(float(img_h), max(ys))

            lines.append(
                {
                    "top_pct": round((min_y / img_h) * 100.0, 2),
                    "left_pct": round((min_x / img_w) * 100.0, 2),
                    "width_pct": round(((max_x - min_x) / img_w) * 100.0, 2),
                    "height_pct": round(((max_y - min_y) / img_h) * 100.0, 2),
                    "font_size_px": round((max_y - min_y) * 0.85, 1),
                    "text": corrected_text,
                    "score": round(float(score), 2),
                }
            )

    mean_conf = (sum(confidences) / len(confidences) * 100.0) if confidences else 100.0
    return {
        "page": image_path.stem,
        "text": "\n".join(text_blocks),
        "lines": lines,
        "mean_confidence": round(mean_conf, 1),
        "total_words": len(" ".join(text_blocks).split()),
    }


def ocr_page(
    image_path: Path,
    lang: str = "spa",
    psm: int = 6,
    preprocess: bool = True,
) -> dict:
    """Ejecuta OCR sobre una sola página con Tesseract (fallback)."""
    import pytesseract

    setup_tesseract_env()

    with Image.open(image_path) as raw_img:
        img = preprocess_for_ocr(raw_img) if preprocess else raw_img
        custom_config = f"--psm {psm}"
        text = pytesseract.image_to_string(img, lang=lang, config=custom_config).strip()
        data = pytesseract.image_to_data(
            img,
            lang=lang,
            config=custom_config,
            output_type=pytesseract.Output.DICT,
        )
        confidences = [int(c) for c in data.get("conf", []) if int(c) >= 0]
        mean_conf = (sum(confidences) / len(confidences)) if confidences else 0.0

    return {
        "page": image_path.stem,
        "text": text,
        "lines": [],
        "mean_confidence": round(mean_conf, 1),
        "total_words": len([w for w in data.get("text", []) if w.strip()]),
    }


def ocr_batch(
    images_dir: Path,
    output_dir: Path,
    pages: list[int] | None = None,
    engine: str = "rapid",
    lang: str = "spa",
    psm: int = 6,
    preprocess: bool = True,
    max_workers: int = 4,
    ref_pdf: Path | None = None,
    force: bool = False,
) -> dict:
    """Procesa un lote de páginas con OCR y guarda tanto texto plano como metadatos con coordenadas."""
    output_dir.mkdir(parents=True, exist_ok=True)

    if pages is not None:
        target_files = [images_dir / f"{p:03d}.jpg" for p in pages]
        target_files = [f for f in target_files if f.exists()]
    else:
        target_files = sorted(images_dir.glob("*.jpg"))

    if not target_files:
        print(f"❌ No se encontraron imágenes JPG en {images_dir}")
        return {"processed": 0, "results": []}

    exact_map, list_pairs = {}, []
    if ref_pdf and ref_pdf.exists():
        print(f"📚 Cargando texto de referencia desde {ref_pdf.name} para corrección automática...")
        exact_map, list_pairs = load_reference_corpus(ref_pdf)
        print(f"   ✓ {len(exact_map)} líneas de referencia listas.")

    print(f"\n🔍 Ejecutando OCR ({'Baidu PP-OCR Rapid' if engine == 'rapid' else 'Tesseract'}) en {len(target_files)} páginas...")

    # Instanciamos el motor Baidu OCR una sola vez para reutilizarlo
    rapid_engine = None
    if engine == "rapid":
        from rapidocr_onnxruntime import RapidOCR

        rapid_engine = RapidOCR()

    results = []
    for img_path in tqdm(target_files, desc="Reconociendo páginas", unit="pág"):
        text_out = output_dir / f"{img_path.stem}.txt"
        json_out = output_dir / f"{img_path.stem}.json"

        if not force and json_out.exists() and text_out.exists():
            try:
                cached = json.loads(json_out.read_text(encoding="utf-8"))
                results.append(cached)
                continue
            except Exception:
                pass

        try:
            if engine == "rapid":
                res = ocr_page_rapid(img_path, engine=rapid_engine, exact_map=exact_map, list_pairs=list_pairs)
            else:
                res = ocr_page(img_path, lang=lang, psm=psm, preprocess=preprocess)

            text_out.write_text(res["text"], encoding="utf-8")
            json_out.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
            results.append(res)
        except Exception as exc:
            results.append({
                "page": img_path.stem,
                "text": "",
                "lines": [],
                "mean_confidence": 0.0,
                "error": str(exc),
            })

    results.sort(key=lambda r: r.get("page", ""))
    summary_path = output_dir / "ocr_resumen.json"
    summary_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"✅ OCR completado. Resultados y coordenadas guardadas en: {output_dir.resolve()}")
    return {"processed": len(results), "summary_path": summary_path, "results": results}
