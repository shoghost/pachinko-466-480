import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

# Actions(UTC)でもズレにくいよう JST 固定
DATE = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d")
OUT_DIR = Path("screenshots") / DATE
OUT_DIR.mkdir(parents=True, exist_ok=True)

CONFIG = Path("config/machines.json")

def main():
    machines = json.loads(CONFIG.read_text(encoding="utf-8-sig"))

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(viewport={"width": 1280, "height": 720})
        page = context.new_page()
        page.set_default_timeout(60000)
        page.set_default_navigation_timeout(60000)

        for m in machines:
            no = int(m["no"])
            url = m["url"]
            page.goto(url, wait_until="networkidle")
            page.wait_for_timeout(1500)

            out = OUT_DIR / f"{no}.png"

            # 「画像を新しいタブで開ける」= img の可能性が高いので
            # ページ内の一番大きい img をグラフ候補として "要素スクショ" する（直GETしない）
            imgs = page.query_selector_all("img")
            best = None
            best_area = 0.0

            for img in imgs:
                try:
                    bb = img.bounding_box()
                    if not bb:
                        continue
                    area = bb["width"] * bb["height"]
                    if area > best_area:
                        best_area = area
                        best = img
                except Exception:
                    continue

            if best:
                best.screenshot(path=str(out))
                print("saved graph img", out)
            else:
                page.screenshot(path=str(out), full_page=False)
                print("saved fallback screenshot", out)

        context.close()
        browser.close()

if __name__ == "__main__":
    main()
