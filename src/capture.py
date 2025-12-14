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
GIF87_SIG = b"GIF87a"
GIF89_SIG = b"GIF89a"

# Minimum file size (1KB) to detect error pages/corrupted downloads
MIN_IMAGE_SIZE = 1024
# Minimum image dimensions to ensure valid graph images
MIN_IMAGE_WIDTH = 400
MIN_IMAGE_HEIGHT = 300

# Wait time for graph to load on detail page (milliseconds)
GRAPH_LOAD_WAIT_MS = 2000
# Wait time between retries (milliseconds)
RETRY_WAIT_MS = 1000

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
    is_gif = body.startswith(GIF87_SIG) or body.startswith(GIF89_SIG)
    
    if not (is_png or is_jpg or is_gif):
        head = body[:120].decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Invalid image format (not PNG/JPG/GIF). URL: {url}, head={head!r}"
        )
    
    # Write to temporary location and verify cv2 can read it
    tmp_path = None
    try:
        suffix = ".png" if is_png else (".gif" if is_gif else ".jpg")
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
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


def ensure_terms_agreed(page, target_url=None):
    """
    規約同意を確認し、必要であれば同意する。
    target_url が指定されている場合、同意後にそのURLにアクセスする。
    """
    # 現在のページまたはトップページで規約同意ボタンをチェック
    try:
        if page.locator("text=利用規約に同意する").count() > 0:
            page.click("text=利用規約に同意する")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1000)
            
            # 同意後、target_url があれば再度アクセス
            if target_url:
                page.goto(target_url, wait_until="networkidle")
                page.wait_for_timeout(500)
    except Exception:
        pass


def capture_graph_direct(page, no: int, max_retries: int = 3) -> tuple[bytes, str]:
    """
    graph.php に直接アクセスして画像を取得する。
    規約同意が必要な場合は自動的に同意してリトライする。
    
    Returns: (image_bytes, method_used)
    """
    # Try day graphs (most common type)
    # Structured as a list for potential future extensibility (week, month types)
    graph_types = ["day"]
    
    for graph_type in graph_types:
        graph_url = f"{GRAPH_BASE}?id={no}&type={graph_type}&did=0"
        
        for attempt in range(max_retries):
            try:
                # Navigate to graph URL
                response = page.goto(graph_url, wait_until="domcontentloaded")
                page.wait_for_timeout(500)
                
                # Check if we were redirected to terms agreement page
                if page.locator("text=利用規約に同意する").count() > 0:
                    # Terms agreement required - agree and retry
                    ensure_terms_agreed(page, graph_url)
                    response = page.goto(graph_url, wait_until="domcontentloaded")
                    page.wait_for_timeout(500)
                
                # Get the response body
                if response and response.ok:
                    body = response.body()
                    
                    # Check if it's a valid image
                    if body and len(body) >= MIN_IMAGE_SIZE:
                        is_png = body.startswith(PNG_SIG)
                        is_jpg = body.startswith(JPG_SIG)
                        is_gif = body.startswith(GIF87_SIG) or body.startswith(GIF89_SIG)
                        
                        if is_png or is_jpg or is_gif:
                            print(f"  Machine {no}: Captured via direct access (graph.php)")
                            return (body, "method0_direct")
                
                # If we get here, the response was not valid
                if attempt < max_retries - 1:
                    print(f"  Machine {no}: Direct access attempt {attempt + 1} failed, retrying...")
                    page.wait_for_timeout(RETRY_WAIT_MS)
                    
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"  Machine {no}: Direct access attempt {attempt + 1} error: {str(e)}, retrying...")
                    page.wait_for_timeout(RETRY_WAIT_MS)
    
    # If we get here, direct access failed
    raise RuntimeError(f"Failed to capture graph directly for machine {no}")


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
                # Match graph.php with query parameters for the specific machine
                # Explicitly exclude game_machine_detail.php to avoid capturing wrong content
                if ("graph.php" in response.url and f"id={no}" in response.url 
                    and "game_machine_detail" not in response.url and response.ok):
                    try:
                        content_type = (response.headers.get("content-type") or "").lower()
                        body = response.body()
                        # Check if it's actually an image (PNG, JPG, or GIF)
                        is_image = (("image" in content_type) or 
                                    body.startswith(PNG_SIG) or 
                                    body.startswith(JPG_SIG) or
                                    body.startswith(GIF87_SIG) or 
                                    body.startswith(GIF89_SIG))
                        if is_image and len(body) >= MIN_IMAGE_SIZE:  # Quick size check
                            intercepted_data = body
                    except Exception as e:
                        # Failed to capture this response, will try next one or fallback
                        print(f"  Warning: Failed to process response for machine {no}: {e}")
            
            try:
                page.on("response", handle_response)
            except Exception as e:
                print(f"  Warning: Failed to add response listener for machine {no}: {e}")
            
            # Navigate to the detail page
            page.goto(detail_url, wait_until="domcontentloaded")
            page.wait_for_timeout(500)
            
            # Check for terms agreement on detail page
            ensure_terms_agreed(page, detail_url)
            
            page.wait_for_timeout(GRAPH_LOAD_WAIT_MS)  # Wait for graph to load
            
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
                '#graph_area'
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
            
            # If we get here, neither method worked
            if attempt < max_retries - 1:
                print(f"  Machine {no}: Attempt {attempt + 1} failed, retrying...")
                page.wait_for_timeout(RETRY_WAIT_MS)
            else:
                raise RuntimeError(
                    f"Failed to capture graph for machine {no} after {max_retries} attempts. "
                    f"Detail URL: {detail_url}"
                )
                
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"  Machine {no}: Attempt {attempt + 1} error: {e}, retrying...")
                page.wait_for_timeout(RETRY_WAIT_MS)
            else:
                raise

def main():
    machines = json.loads(CONFIG.read_text(encoding="utf-8-sig"))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(viewport={"width": 1280, "height": 720})
        page = context.new_page()
        page.set_default_timeout(60000)
        page.set_default_navigation_timeout(60000)

        # Ensure terms are agreed on top page first
        page.goto("https://x-arena.p-moba.net/", wait_until="domcontentloaded")
        page.wait_for_timeout(500)
        ensure_terms_agreed(page)

        # Track downloaded content to detect duplicates
        downloaded_hashes = {}
        # Allow some duplicates (e.g., maintenance periods), but fail if too many
        MAX_ALLOWED_DUPLICATES = 3

        for m in machines:
            no = int(m["no"])
            detail_url = m.get("url", f"https://x-arena.p-moba.net/game_machine_detail.php?id={no}")
            out = OUT_DIR / f"{no}.png"

            # Try to capture graph - first directly, then via detail page
            body = None
            method = None
            
            try:
                # Method 0: Try direct access to graph.php
                body, method = capture_graph_direct(page, no)
            except Exception as e:
                print(f"  Machine {no}: Direct access failed ({str(e)}), trying detail page method...")
                # Method 1 & 2: Fallback to detail page approach
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
