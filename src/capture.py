import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

# JST固定で日付フォルダ
DATE = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d")
OUT_DIR = Path("screenshots") / DATE
OUT_DIR.mkdir(parents=True, exist_ok=True)

CONFIG = Path("config/machines.json")
GRAPH_BASE = "https://x-arena.p-moba.net/graph.php"

def ensure_terms_agreed(page):
    # 規約同意が必要な場合に備えて一度トップへ
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

            # あなたが使いたい日次グラフ
            graph_url = f"{GRAPH_BASE}?id={no}&type=day&did=0"

            page.goto(graph_url, wait_until="networkidle")
            page.wait_for_timeout(500)

            # 画像ページを「スクショ」するので必ずPNGになる
            page.screenshot(path=str(out), full_page=True)
            print("saved", out, "from", graph_url)

        context.close()
        browser.close()

if __name__ == "__main__":
    main()
