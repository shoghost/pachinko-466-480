import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

DATE = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d")
OUT_DIR = Path("screenshots") / DATE
OUT_DIR.mkdir(parents=True, exist_ok=True)

CONFIG = Path("config/machines.json")
GRAPH_BASE = "https://x-arena.p-moba.net/graph.php"

PNG_SIG = b"\x89PNG\r\n\x1a\n"
JPG_SIG = b"\xff\xd8\xff"

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

        for m in machines:
            no = int(m["no"])
            out = OUT_DIR / f"{no}.png"

            url = f"{GRAPH_BASE}?id={no}&type=day&did=0"

            # Refererを付けると弾かれにくいサイトがある
            resp = page.request.get(url, headers={"Referer": "https://x-arena.p-moba.net/"})
            body = resp.body()
            ct = (resp.headers.get("content-type") or "").lower()

            is_image = ("image" in ct) or body.startswith(PNG_SIG) or body.startswith(JPG_SIG)
            if (not resp.ok) or (not is_image):
                head = body[:120].decode("utf-8", errors="replace")
                raise RuntimeError(f"Non-image response: status={resp.status} ct={ct} head={head!r}")

            out.write_bytes(body)
            print("saved", out, "from", url, "ct=", ct)

        context.close()
        browser.close()

if __name__ == "__main__":
    main()
