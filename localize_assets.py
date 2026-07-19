#!/usr/bin/env python3
"""
Localiza assets de Framer (imagenes, fuentes, videos, y sobre todo los
modulos .mjs que arman el sitio) que quedaron referenciados con URL
completa (framerusercontent.com, etc.) despues de exportar, y los
reemplaza por copias locales dentro del repo.

Iterativo: los .mjs descargados pueden importar otros .mjs remotos, asi
que se repite el escaneo sobre los archivos recien descargados hasta que
no aparezcan URLs nuevas.

Pensado para correr dentro de un GitHub Action (ver
.github/workflows/localize-framer-assets.yml), asi la descarga la hace
el runner de GitHub (con internet sin restricciones) y no tu maquina.
"""
import os
import re
import hashlib
import urllib.request
import urllib.parse

FRAMER_DOMAINS = [
    "framerusercontent.com",
    "framerstatic.com",
    "framercdn.com",
    "framer.app",
    "framer.com",
    "events.framer.com",
    "api.framer.com",
    "jspm.io",
]

# Extensiones donde buscamos URLs (incluye .mjs: los modulos remotos
# pueden importar a su vez otros modulos remotos)
SCAN_EXTS = (".html", ".htm", ".css", ".js", ".mjs", ".json")

ASSET_DIR = "assets/framer"
MAX_ITERATIONS = 6

URL_PATTERN = re.compile(
    r'https?://[^\s"\')]+(?:' + "|".join(re.escape(d) for d in FRAMER_DOMAINS) + r')[^\s"\')]*'
)


def find_files(root="."):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in (".git", "node_modules", ".github")
        ]
        for f in filenames:
            if f.lower().endswith(SCAN_EXTS):
                yield os.path.join(dirpath, f)


def local_filename(url):
    parsed = urllib.parse.urlparse(url)
    base = os.path.basename(parsed.path) or "file"
    name, ext = os.path.splitext(base)
    if not ext:
        ext = ".mjs" if "sites/" in parsed.path else ""
    h = hashlib.md5(url.encode()).hexdigest()[:8]
    return f"{name}-{h}{ext}"


def find_urls_in_files(files):
    urls = set()
    for path in files:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                content = fh.read()
        except OSError:
            continue
        urls.update(URL_PATTERN.findall(content))
    return urls


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp, open(dest, "wb") as out:
        out.write(resp.read())


def replace_in_files(files, url_map):
    changed_files = []
    for path in files:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                content = fh.read()
        except OSError:
            continue
        original = content
        for url, local_path in url_map.items():
            if local_path:
                content = content.replace(url, local_path)
        if content != original:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
            changed_files.append(path)
    return changed_files


PROMO_START = '<div class="framer-wctl1-container">'
PROMO_END = '<div id="template-overlay"></div><!--/$--></div>'
PROMO_PATTERN = re.compile(re.escape(PROMO_START) + r'.*?' + re.escape(PROMO_END), re.DOTALL)


def remove_promo_widget(files):
    """Borra el widget 'Remix for $0 / All Templates' (avathiery.com) de las
    paginas HTML exportadas. Es contenido publicitario del template gratuito,
    no del sitio del cliente."""
    removed_from = []
    for path in files:
        if not path.lower().endswith((".html", ".htm")):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                content = fh.read()
        except OSError:
            continue
        new_content, n = PROMO_PATTERN.subn("", content)
        if n:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(new_content)
            removed_from.append((path, n))
    return removed_from


def main():
    os.makedirs(ASSET_DIR, exist_ok=True)
    all_url_map = {}

    print("Buscando el widget promocional del template...")
    removed = remove_promo_widget(list(find_files(".")))
    if removed:
        for path, n in removed:
            print(f"  Borrado widget 'Remix for $0' en: {path} ({n} ocurrencia(s))")
    else:
        print("  No se encontro el widget (o ya fue borrado antes).")

    for iteration in range(1, MAX_ITERATIONS + 1):
        files = list(find_files("."))
        urls = find_urls_in_files(files)
        new_urls = [u for u in urls if u not in all_url_map]

        if not new_urls:
            print(f"Iteracion {iteration}: no hay URLs nuevas de Framer. Listo.")
            break

        print(f"Iteracion {iteration}: {len(new_urls)} URLs nuevas encontradas.")

        for url in new_urls:
            dest = os.path.join(ASSET_DIR, local_filename(url))
            try:
                print(f"  Descargando: {url}")
                download(url, dest)
                all_url_map[url] = "/" + dest.replace(os.sep, "/")
            except Exception as e:
                print(f"  ERROR con {url}: {e}")
                all_url_map[url] = None

        files = list(find_files("."))
        changed = replace_in_files(files, all_url_map)
        for path in changed:
            print(f"  Actualizado: {path}")
    else:
        print(f"Se alcanzo el limite de {MAX_ITERATIONS} iteraciones. Revisa manualmente si quedan URLs sueltas.")

    print("Proceso terminado.")


if __name__ == "__main__":
    main()
