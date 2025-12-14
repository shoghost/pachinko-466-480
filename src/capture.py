import hashlib
import json
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import cv2
from playwright.sync_api import sync_playwright

DATE = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d")
OUT_DIR = Path("screenshots") / DATE
OUT_DIR.mkdir(parents=True, exist_ok=True)

CONFIG = Path("config/machines.json")
GRAPH_BASE = "https://x-arena.p-moba.net/graph.php"

PNG_SIG = b"\x89PNG\r\n\x1a\n"
JPG_SIG = b"\xff\xd8\xff"

# Minimum file size (1KB) to detect error pages/corrupted downloads
MIN_IMAGE_SIZE = 1024
# Minimum image dimensions to ensure valid graph images
MIN_IMAGE_WIDTH = 400
MIN_IMAGE_HEIGHT = 300

def validate_image_data(body: bytes, url: str) -> None:
    """
    Validate that downloaded data is a proper image file.
    Raises RuntimeError if validation fails.
    """
    # Check file size
    if len(body) < MIN_IMAGE_SIZE:
        raise RuntimeError(
            f"Image too small: {len(body)} bytes (minimum {MIN_IMAGE_SIZE} bytes). "
            f"URL: {url}"
        )
    
    # Check magic bytes
    is_png = body.startswith(PNG_SIG)
    is_jpg = body.startswith(JPG_SIG)
    
    if not (is_png or is_jpg):
        head = body[:120].decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Invalid image format (not PNG/JPG). URL: {url}, head={head!r}"
        )
    
    # Write to temporary location and verify cv2 can read it
    with tempfile.NamedTemporaryFile(suffix=".png" if is_png else ".jpg", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    
    try:
        tmp_path.write_bytes(body)
        img = cv2.imread(str(tmp_path))
        
        if img is None:
            raise RuntimeError(
                f"cv2.imread() failed to read the image. URL: {url}"
            )
        
        # Check image dimensions
        height, width = img.shape[:2]
        if width < MIN_IMAGE_WIDTH or height < MIN_IMAGE_HEIGHT:
            raise RuntimeError(
                f"Image dimensions too small: {width}x{height} "
                f"(minimum {MIN_IMAGE_WIDTH}x{MIN_IMAGE_HEIGHT}). URL: {url}"
            )
    finally:
        try:
            tmp_path.unlink()
        except Exception:
            pass  # Best effort cleanup


def ensure_terms_agreed(page):
    # 規約があると画像がHTMLで返ってくることがあるので、先にトップへ一度行く
    page.goto("https://x-arena.p-moba.net/", wait_until="domcontentloaded")
    page.wait_for_timeout(500)
    try:
        if page.locator("text=利用規約に同意する").count() > 0:
            page.click("text=利用規約に同意する")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(500)
    except Exception:
        pass

def main():
    machines = json.loads(CONFIG.read_text(encoding="utf-8-sig"))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(viewport={"width": 1280, "height": 720})
        page = context.new_page()
        page.set_default_timeout(60000)
        page.set_default_navigation_timeout(60000)

        ensure_terms_agreed(page)

        # Track downloaded content to detect duplicates
        downloaded_hashes = {}

        for m in machines:
            no = int(m["no"])
            out = OUT_DIR / f"{no}.png"

            url = f"{GRAPH_BASE}?id={no}&type=day&did=0"

            # Refererを付けると弾かれにくいサイトがある
            resp = page.request.get(url, headers={"Referer": "https://x-arena.p-moba.net/"})
            body = resp.body()
            ct = (resp.headers.get("content-type") or "").lower()

            # Check HTTP status and Content-Type
            is_image = ("image" in ct) or body.startswith(PNG_SIG) or body.startswith(JPG_SIG)
            if (not resp.ok) or (not is_image):
                head = body[:120].decode("utf-8", errors="replace")
                raise RuntimeError(f"Non-image response: status={resp.status} ct={ct} head={head!r}")

            # Validate image data (size, format, cv2 readability, dimensions)
            validate_image_data(body, url)

            # Check for duplicate content (all files having same hash indicates error)
            content_hash = hashlib.sha256(body).hexdigest()
            if content_hash in downloaded_hashes:
                prev_no = downloaded_hashes[content_hash]
                raise RuntimeError(
                    f"Duplicate image detected: machine {no} has identical content to machine {prev_no}. "
                    f"This may indicate an error page or incorrect data. Hash: {content_hash[:16]}..."
                )
            downloaded_hashes[content_hash] = no

            # Save the validated image
            out.write_bytes(body)
            print("saved", out, "from", url, "ct=", ct, f"size={len(body)} bytes")

        context.close()
        browser.close()

if __name__ == "__main__":
    main()
