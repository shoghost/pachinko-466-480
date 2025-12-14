import json
import os
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

DATE = datetime.now().strftime("%Y-%m-%d")
OUT_DIR = Path("screenshots") / DATE
OUT_DIR.mkdir(parents=True, exist_ok=True)

CONFIG = Path("config/machines.json")

def main():
    machines = json.loads(CONFIG.read_text(encoding="utf-8-sig"))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 720})
        page = context.new_page()

        # ログインが必要ならここに処理を書く（必要な場合のみ）
        # page.goto("https://.../login", wait_until="networkidle")
        # page.fill("#user", os.getenv("LOGIN_USER",""))
        # page.fill("#pass", os.getenv("LOGIN_PASS",""))
        # page.click("button[type=submit]")
        # page.wait_for_load_state("networkidle")

        for m in machines:
            no = int(m["no"])
            url = m["url"]
            page.goto(url, wait_until="networkidle")
            page.wait_for_timeout(1500)
            out = OUT_DIR / f"{no}.png"
            page.screenshot(path=str(out), full_page=True)
            print("saved", out)

        context.close()
        browser.close()

if __name__ == "__main__":
    main()
