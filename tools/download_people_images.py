"""Descarga fotografías con personas desde Wikimedia Commons.

Guarda thumbnails moderados para no llenar el NVMe y genera manifest.csv con
la atribución/licencia devuelta por Commons. Las imágenes deben revisarse antes
de usarlas para evaluar precisión; una búsqueda textual no es ground truth.
"""

import argparse
import csv
import html
import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "AEYE-YOLO-benchmark/1.0 (local research test dataset)"
QUERIES = (
    "people working indoors filetype:bitmap",
    "retail workers people filetype:bitmap",
    "warehouse workers people filetype:bitmap",
    "people walking indoors filetype:bitmap",
    "office workers people filetype:bitmap",
)
ALLOWED_MIME = {"image/jpeg": ".jpg", "image/png": ".png"}


def open_with_retry(request, timeout, attempts=6):
    """Respeta límites 429 y reintenta errores temporales con backoff."""
    for attempt in range(attempts):
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            retryable = error.code == 429 or 500 <= error.code < 600
            if not retryable or attempt == attempts - 1:
                raise
            try:
                wait = float(error.headers.get("Retry-After", ""))
            except ValueError:
                wait = min(60.0, 2.0 ** attempt)
            wait = max(2.0, min(wait, 120.0))
            print(f"Wikimedia respondió HTTP {error.code}; reintento en {wait:.0f}s...")
            time.sleep(wait)
        except urllib.error.URLError:
            if attempt == attempts - 1:
                raise
            wait = min(30.0, 2.0 ** attempt)
            print(f"Error temporal de red; reintento en {wait:.0f}s...")
            time.sleep(wait)


def plain(metadata, key):
    """Extrae texto plano de un campo de metadatos HTML de Commons."""
    value = metadata.get(key, {}).get("value", "")
    return re.sub(r"<[^>]+>", "", html.unescape(value)).strip()


def commons_search(query, limit=30):
    """Busca imagenes en Commons y devuelve paginas con datos de licencia."""
    params = urllib.parse.urlencode({
        "action": "query",
        "format": "json",
        "formatversion": 2,
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": 6,
        "gsrlimit": limit,
        "prop": "imageinfo",
        "iiprop": "url|mime|size|extmetadata",
        "iiurlwidth": 1280,
        "iiextmetadatafilter": "Artist|LicenseShortName|LicenseUrl|Credit",
    })
    request = urllib.request.Request(f"{API}?{params}", headers={"User-Agent": USER_AGENT})
    with open_with_retry(request, timeout=30) as response:
        payload = json.load(response)
    return payload.get("query", {}).get("pages", [])


def download(url, destination):
    """Descarga una imagen respetando el User-Agent y la politica de reintentos."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with open_with_retry(request, timeout=60) as response:
        destination.write_bytes(response.read())


def main():
    """Construye un dataset reproducible y escribe su manifiesto de atribucion."""
    parser = argparse.ArgumentParser(description="Descargar imágenes de personas para benchmark")
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--output", default="test_images/people")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--delay", type=float, default=2.0,
                        help="Espera entre descargas para respetar Wikimedia")
    args = parser.parse_args()
    if not 1 <= args.count <= 100:
        raise ValueError("count debe estar entre 1 y 100")

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    candidates = []
    seen = set()
    for query in QUERIES:
        for page in commons_search(query):
            info_rows = page.get("imageinfo") or []
            if not info_rows:
                continue
            info = info_rows[0]
            mime = info.get("mime")
            url = info.get("thumburl") or info.get("url")
            if mime not in ALLOWED_MIME or not url or url in seen:
                continue
            if info.get("width", 0) < 300 or info.get("height", 0) < 300:
                continue
            seen.add(url)
            candidates.append((page, info, mime, url))

    random.Random(args.seed).shuffle(candidates)
    if len(candidates) < args.count:
        raise RuntimeError(f"Commons devolvió solo {len(candidates)} imágenes utilizables")

    rows = []
    candidate_index = 0
    index = 1
    while index <= args.count and candidate_index < len(candidates):
        page, info, mime, url = candidates[candidate_index]
        candidate_index += 1
        filename = f"person_{index:03d}{ALLOWED_MIME[mime]}"
        destination = output / filename
        existing = destination.is_file() and destination.stat().st_size > 0
        if existing:
            print(f"[{index}/{args.count}] ya existe, se conserva: {destination}")
        else:
            print(f"[{index}/{args.count}] {page['title']} -> {destination}")
            try:
                download(url, destination)
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
                print(f"ADVERTENCIA: se omite {page['title']}: {error}")
                continue
            if args.delay > 0:
                time.sleep(args.delay)
        metadata = info.get("extmetadata", {})
        rows.append({
            "filename": filename,
            "title": page["title"],
            "source_page": info.get("descriptionurl", ""),
            "download_url": url,
            "artist": plain(metadata, "Artist"),
            "license": plain(metadata, "LicenseShortName"),
            "license_url": plain(metadata, "LicenseUrl"),
            "credit": plain(metadata, "Credit"),
        })
        index += 1

    if len(rows) < args.count:
        raise RuntimeError(f"Solo se pudieron preparar {len(rows)} de {args.count} imágenes")

    manifest = output / "manifest.csv"
    with manifest.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"Listo: {len(rows)} imágenes en {output}")
    print(f"Licencias y fuentes: {manifest}")
    print("Revisá visualmente las imágenes y descartá las que no tengan personas claras.")


if __name__ == "__main__":
    main()
