import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

# JSTで日付フォルダ作る
DATE = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d")
OUT_DIR = Path("screenshots") / DATE
OUT_DIR.mkdir(parents=True, exist_ok=True)

CONFIG = Path("config/machines.json")

GRAPH_BASE = "https://x-arena.p-moba.net/graph.php"

def main():
    machines = json.loads(CONFIG.read_text(encoding="utf-8-sig"))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(viewport={"width": 1280, "height": 720})
        page = context.new_page()
        page.set_default_timeout(60000)
        page.set_default_navigation_timeout(60000)

        for m in machines:
            no = int(m["no"])

            # あなたが使いたい日次グラフ
            graph_url = f"{GRAPH_BASE}?id={no}&type=day&did=0"

            out = OUT_DIR / f"{no}.png"

            resp = page.request.get(graph_url)
            if not resp.ok:
                raise RuntimeError(f"Failed to fetch {graph_url}: {resp.status} {resp.status_text}")

            out.write_bytes(resp.body())
            print("saved", out, "from", graph_url)

        context.close()
        browser.close()

if __name__ == "__main__":
    main()
