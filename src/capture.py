import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

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

            # ページ内の img を全部見て「一番大きい画像」をグラフ候補として保存
            imgs = page.query_selector_all("img")
            best_area = 0.0
            best_src = None

            for img in imgs:
                try:
                    bb = img.bounding_box()
                    if not bb:
                        continue
                    area = bb["width"] * bb["height"]
                    src = img.get_attribute("src")
                    if not src:
                        continue
                    if area > best_area:
                        best_area = area
                        best_src = src
                except Exception:
                    continue

            if best_src:
                graph_url = urljoin(page.url, best_src)
                resp = page.request.get(graph_url)
                if not resp.ok:
                    raise RuntimeError(
                        f"Failed to fetch {graph_url}: {resp.status} {resp.status_text}"
                    )
                out.write_bytes(resp.body())
                print("saved graph image", out, "from", graph_url)
            else:
                page.screenshot(path=str(out), full_page=False)
                print("saved fallback screenshot", out)

        context.close()
        browser.
python -m py_compile .\src\capture.py
git add src/capture.py
git commit -m "Fix capture.py syntax and response check"
git push
cd $HOME\Desktop\pachinko-466-480
Select-String -Path .\src\capture.py -Pattern "resp.ok"
cd $HOME\Desktop\pachinko-466-480
Select-String -Path .\src\capture.py -Pattern "resp.ok"

cd $HOME\Desktop\pachinko-466-480
Select-String -Path .\src\capture.py -Pattern "resp.ok"
cd $HOME\Desktop\pachinko-466-480
@'
import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

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

        for m in machines:
            no = int(m["no"])
            url = m["url"]
            page.goto(url, wait_until="networkidle")
            page.wait_for_timeout(1500)
            out = OUT_DIR / f"{no}.png"

            imgs = page.query_selector_all("img")
            best_area = 0.0
            best_src = None

            for img in imgs:
                try:
                    bb = img.bounding_box()
                    if not bb:
                        continue
                    area = bb["width"] * bb["height"]
                    src = img.get_attribute("src")
                    if not src:
                        continue
                    if area > best_area:
                        best_area = area
                        best_src = src
                except Exception:
                    continue

            if best_src:
                graph_url = urljoin(page.url, best_src)
                resp = page.request.get(graph_url)
                if not resp.ok:
                    raise RuntimeError(f"Failed to fetch {graph_url}: {resp.status} {resp.status_text}")
                out.write_bytes(resp.body())
                print("saved graph image", out, "from", graph_url)
            else:
                page.screenshot(path=str(out), full_page=False)
                print("saved fallback screenshot", out)

        context.close()
        browser.close()

if __name__ == "__main__":
    main()
