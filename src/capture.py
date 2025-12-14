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
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png" if is_png else ".jpg", delete=False) as tmp:
            tmp.write(body)
            tmp_path = Path(tmp.name)
        
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
        if tmp_path is not None:
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


def capture_graph_via_detail_page(page, no: int, detail_url: str, max_retries: int = 3) -> tuple[bytes, str]:
    """
    Method 1: Navigate to detail page and intercept graph.php request
    Method 2: Take screenshot of graph element as fallback
    
    Returns: (image_bytes, method_used)
    """
    for attempt in range(max_retries):
        try:
            # Method 1: Try to intercept the graph image request
            intercepted_data = None
            
            def handle_response(response):
                nonlocal intercepted_data
                if "graph.php" in response.url and response.ok:
                    try:
                        content_type = (response.headers.get("content-type") or "").lower()
                        body = response.body()
                        # Check if it's actually an image
                        if ("image" in content_type) or body.startswith(PNG_SIG) or body.startswith(JPG_SIG):
                            if len(body) >= MIN_IMAGE_SIZE:  # Quick size check
                                intercepted_data = body
                    except Exception as e:
                        # Failed to capture this response, will try next one or fallback
                        print(f"    Warning: Failed to process response for machine {no}: {e}")
            
            listener_added = False
            try:
                page.on("response", handle_response)
                listener_added = True
            except Exception as e:
                print(f"    Warning: Failed to add response listener for machine {no}: {e}")
            
            try:
                # Navigate to the detail page
                page.goto(detail_url, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)  # Wait for graph to load
                
                # Check if we intercepted the image
                if intercepted_data:
                    print(f"  Machine {no}: Captured via Method 1 (network interception)")
                    return (intercepted_data, "method1_intercept")
                
                # Method 2: Screenshot fallback
                # Look for the graph image element
                img_selectors = [
                    f'img[src*="graph.php"][src*="id={no}"]',
                    'img[src*="graph.php"]',
                    '#graph_img',
                    '.graph-image'
                ]
                
                graph_element = None
                for selector in img_selectors:
                    try:
                        if page.locator(selector).count() > 0:
                            graph_element = page.locator(selector).first
                            break
                    except Exception:
                        continue
                
                if graph_element:
                    # Take screenshot of the graph element
                    screenshot_bytes = graph_element.screenshot()
                    print(f"  Machine {no}: Captured via Method 2 (element screenshot)")
                    return (screenshot_bytes, "method2_screenshot")
                
                # If no specific element found, try to find the graph in a broader area
                # Look for a container that might have the graph
                container_selectors = [
                    '.graph-container',
                    '#graph_area',
                    'div:has(img[src*="graph.php"])'
                ]
                
                for selector in container_selectors:
                    try:
                        if page.locator(selector).count() > 0:
                            container = page.locator(selector).first
                            screenshot_bytes = container.screenshot()
                            print(f"  Machine {no}: Captured via Method 2 (container screenshot)")
                            return (screenshot_bytes, "method2_screenshot")
                    except Exception:
                        continue
                
            finally:
                if listener_added:
                    try:
                        page.remove_listener("response", handle_response)
                    except Exception:
                        pass  # Best effort cleanup
            
            # If we get here, neither method worked
            if attempt < max_retries - 1:
                print(f"  Machine {no}: Attempt {attempt + 1} failed, retrying...")
                page.wait_for_timeout(1000)
            else:
                raise RuntimeError(
                    f"Failed to capture graph for machine {no} after {max_retries} attempts. "
                    f"Detail URL: {detail_url}"
                )
                
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"  Machine {no}: Attempt {attempt + 1} error: {e}, retrying...")
                page.wait_for_timeout(1000)
            else:
                raise
    
    raise RuntimeError(f"Failed to capture graph for machine {no} after all retries")

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
        # Allow some duplicates (e.g., maintenance periods), but fail if too many
        MAX_ALLOWED_DUPLICATES = 3

        for m in machines:
            no = int(m["no"])
            detail_url = m.get("url", f"https://x-arena.p-moba.net/game_machine_detail.php?id={no}")
            out = OUT_DIR / f"{no}.png"

            # Use the new method: navigate to detail page and capture graph
            body, method = capture_graph_via_detail_page(page, no, detail_url)
            
            # Validate image data (size, format, cv2 readability, dimensions)
            validate_image_data(body, detail_url)

            # Check for duplicate content (too many duplicates indicates error)
            content_hash = hashlib.sha256(body).hexdigest()
            if content_hash in downloaded_hashes:
                prev_nos = downloaded_hashes[content_hash]
                prev_nos.append(no)
                
                # Warn about duplicate but only fail if too many
                print(f"Warning: machine {no} has identical content to machine(s) {prev_nos[:-1]}")
                
                if len(prev_nos) > MAX_ALLOWED_DUPLICATES:
                    raise RuntimeError(
                        f"Too many duplicate images detected ({len(prev_nos)} machines with same content: {prev_nos}). "
                        f"This may indicate an error page or system-wide issue. Hash: {content_hash[:16]}..."
                    )
            else:
                downloaded_hashes[content_hash] = [no]

            # Save the validated image
            out.write_bytes(body)
            print(f"  Saved {out} (size={len(body)} bytes, method={method})")

        context.close()
        browser.close()

if __name__ == "__main__":
    main()
