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

def ensure_terms_agreed(page):
    # 初回アクセスで利用規約ページが出ることがあるので、同意をクリックしてcookieを作る
    page.goto("https://x-arena.p-moba.net/", wait_until="domcontentloaded")
    page.wait_for_timeout(500)

    # 文字が見つかったらクリック（見つからなければ何もしない）
    try:
        if page.locator("text=利用規約に同意する").count() > 0:
            page.click("text=利用規約に同意する")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(500)
    except Exception:
        # クリック不要/構造違いでも止めない
        pass

def main():
    machines = json.loads(CONFIG.read_text(encoding="utf-8-sig"))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(viewport={"width": 1280, "height": 720})
        page = context.new_page()
        page.set_default_timeout(60000)
        page.set_default_navigation_timeout(60000)

        # ここで規約同意を済ませる（cookie確保）
        ensure_terms_agreed(page)

        for m in machines:
            no = int(m["no"])
            out = OUT_DIR / f"{no}.png"

            graph_url = f"{GRAPH_BASE}?id={no}&type=day&did=0"
            resp = page.request.get(graph_url)

            body = resp.body()
            ct = (resp.headers.get("content-type") or "").lower()

            # 画像じゃなさそうなら、内容を少しログに出して落とす（HTMLをpngとして保存しない）
            if (not resp.ok) or (("image" not in ct) and (not body.startswith(PNG_SIG))):
                head = body[:80].decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"Non-image response for {graph_url} (status={resp.status}, ct={ct}). "
                    f"Head={head!r}"
                )

            out.write_bytes(body)
            print("saved", out, "from", graph_url)

        context.close()
        browser.close()

if __name__ == "__main__":
    main()
