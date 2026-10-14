"""Módulo de descarga de páginas escaneadas desde CONALITEG."""

import concurrent.futures
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import zipfile

from PIL import Image
from tqdm import tqdm

from .config import DEFAULT_BASE_URL, CATALOG, DEFAULT_BOOK_ID, extract_book_id, fetch_book_info


def download_single_page(
    book_id: str,
    page_number: int,
    output_dir: Path,
    base_url_pattern: str = DEFAULT_BASE_URL,
    attempts: int = 4,
    verify_image: bool = True,
) -> tuple[int, bool, str]:
    """Descarga una página individual y opcionalmente verifica que sea una imagen válida."""
    clean_id = extract_book_id(book_id)
    url = base_url_pattern.format(book_id=clean_id, page=page_number)
    filename = f"{page_number:03d}.jpg"
    target_path = output_dir / filename

    # Si ya existe y es válida, saltar descarga
    if target_path.exists() and target_path.stat().st_size > 1000:
        if verify_image:
            try:
                with Image.open(target_path) as img:
                    img.verify()
                return page_number, True, "archivo existente y verificado"
            except Exception:
                target_path.unlink(missing_ok=True)
        else:
            return page_number, True, "archivo ya existente"

    for attempt in range(attempts):
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urlopen(req, timeout=30) as response:
                data = response.read()
                content_type = response.headers.get("Content-Type", "")

            if response.status != 200 or "image" not in content_type.lower() or len(data) < 1000:
                raise ValueError(f"Respuesta inválida (HTTP {response.status}, tipo={content_type}, bytes={len(data)})")

            target_path.write_bytes(data)

            if verify_image:
                with Image.open(target_path) as img:
                    img.verify()

            return page_number, True, f"{len(data)} bytes"
        except Exception as exc:
            if attempt == attempts - 1:
                return page_number, False, str(exc)
            time.sleep(1.2 * (attempt + 1))

    return page_number, False, "error desconocido"


def download_book(
    book_id: str = DEFAULT_BOOK_ID,
    start_page: int = 0,
    end_page: int | None = None,
    output_dir: Path | None = None,
    max_workers: int = 8,
    create_zip: bool = False,
    zip_path: Path | None = None,
) -> dict:
    """Descarga concurrente del rango de páginas de un libro en CONALITEG a partir de URL o clave."""
    clean_id = extract_book_id(book_id)
    book_info = fetch_book_info(clean_id)

    if end_page is None:
        end_page = max(0, book_info.total_pages - 1)

    if output_dir is None:
        output_dir = Path(f"{clean_id}_paginas")
    output_dir.mkdir(parents=True, exist_ok=True)

    pages = list(range(start_page, end_page + 1))
    total_to_download = len(pages)

    print(f"\n📥 Iniciando descarga para '{book_info.title}' ({clean_id})")
    print(f"📖 Páginas: {start_page:03d} a {end_page:03d} ({total_to_download} páginas en total)")
    print(f"📁 Directorio de destino: {output_dir.resolve()}")

    results = {}
    failures = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {
            pool.submit(download_single_page, book_id, p, output_dir): p
            for p in pages
        }

        with tqdm(total=total_to_download, desc="Descargando páginas", unit="pág") as pbar:
            for future in concurrent.futures.as_completed(future_map):
                page_num, success, info = future.result()
                results[page_num] = (success, info)
                if not success:
                    failures.append((page_num, info))
                pbar.update(1)

    if failures:
        print(f"\n⚠️  No se pudieron descargar {len(failures)} páginas:")
        for p, err in sorted(failures):
            print(f"   - Página {p:03d}.jpg: {err}")
    else:
        print(f"\n✅ Descarga completada con éxito: {total_to_download} páginas verificadas.")

    # Generación opcional de archivo ZIP
    if create_zip:
        if zip_path is None:
            zip_path = Path(f"{book_id}_paginas.zip")
        print(f"📦 Empaquetando en ZIP: {zip_path}...")
        files = sorted(output_dir.glob("*.jpg"))
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for file_path in files:
                zf.write(file_path, arcname=file_path.name)
        print(f"✅ ZIP listo: {zip_path.resolve()} ({len(files)} imágenes)")

    return {
        "output_dir": output_dir,
        "total": total_to_download,
        "successes": total_to_download - len(failures),
        "failures": failures,
    }
