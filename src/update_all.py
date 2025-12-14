from __future__ import annotations

from pathlib import Path
import pandas as pd

from process_screenshot import extract_series_from_image

ROOT = Path(".")
SS_DIR = ROOT / "screenshots"
DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"

POINTS_PER_DAY = 720

def day_points_to_timestamps(date_str: str, n: int) -> pd.DatetimeIndex:
    start = pd.Timestamp(date_str + " 00:00:00")
    end = pd.Timestamp(date_str + " 23:59:59")
    return pd.date_range(start, end, periods=n)

def update_machine_series(machine_no: int, values: pd.Series) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    out_csv = DATA_DIR / f"series_{machine_no}.csv"

    new_df = pd.DataFrame({"ts": values.index.astype(str), "value": values.values})
    if out_csv.exists():
        old = pd.read_csv(out_csv)
        merged = pd.concat([old, new_df], ignore_index=True)
        merged = merged.drop_duplicates(subset=["ts"], keep="last").sort_values("ts")
        merged.to_csv(out_csv, index=False, encoding="utf-8-sig")
    else:
        new_df.to_csv(out_csv, index=False, encoding="utf-8-sig")

def build_docs(machine_nos: list[int]) -> None:
    import plotly.graph_objects as go

    DOCS_DIR.mkdir(exist_ok=True)

    made = []
    links = []

    for m in machine_nos:
        csv_path = DATA_DIR / f"series_{m}.csv"
        if not csv_path.exists():
            continue

        df = pd.read_csv(csv_path)
        df["ts"] = pd.to_datetime(df["ts"])

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df["ts"], y=df["value"], mode="lines", name=str(m)))
        fig.update_layout(
            title=f"Machine {m}",
            xaxis=dict(rangeslider=dict(visible=True), title="time"),
            yaxis=dict(title="difference"),
            height=650,
        )

        out_html = DOCS_DIR / f"{m}.html"
        fig.write_html(str(out_html), include_plotlyjs="cdn")
        made.append(m)
        links.append(f'<li><a href="./{m}.html">{m}</a></li>')

    if made:
        first = made[0]
        options = "\n".join([f'<option value="{m}.html">{m}</option>' for m in made])

        dashboard_html = f'''<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8" />
  <title>Pachinko Dashboard</title>
  <style>
    body {{ font-family: sans-serif; margin: 12px; }}
    .bar {{ display:flex; gap:12px; align-items:center; flex-wrap:wrap; }}
    select {{ font-size: 16px; padding: 6px; }}
    iframe {{ width: 100%; height: 780px; border: 1px solid #ccc; border-radius: 8px; }}
  </style>
</head>
<body>
  <h2>Pachinko Dashboard（台番切り替え）</h2>
  <div class="bar">
    <label>台番：</label>
    <select id="machine">{options}</select>
  </div>
  <p style="color:#666;"> グラフ内のレンジスライダーで過去へ遡れます</p>
  <iframe id="view" src="{first}.html"></iframe>
  <script>
    const sel = document.getElementById("machine");
    const view = document.getElementById("view");
    sel.value = "{first}.html";
    sel.addEventListener("change", () => {{ view.src = sel.value; }});
  </script>
</body>
</html>'''
        (DOCS_DIR / "dashboard.html").write_text(dashboard_html, encoding="utf-8")

    dash_link = '<p><a href="./dashboard.html"> 台番を切り替える（ダッシュボード）</a></p>' if made else ""
    (DOCS_DIR / "index.html").write_text(
        "<html><body><h2>Pachinko Reports</h2>"
        + dash_link
        + "<ul>" + "\n".join(links) + "</ul></body></html>",
        encoding="utf-8",
    )

def main():
    if not SS_DIR.exists():
        print("no screenshots/")
        return

    machine_set = set()

    for day_dir in sorted([p for p in SS_DIR.iterdir() if p.is_dir()]):
        date_str = day_dir.name
        for img_path in sorted(day_dir.glob("*.*")):
            try:
                machine_no = int(img_path.stem)  # 466.png 形式
            except ValueError:
                continue

            res = extract_series_from_image(img_path, points_per_day=POINTS_PER_DAY)
            ts = day_points_to_timestamps(date_str, POINTS_PER_DAY)
            series = pd.Series(res.series, index=ts)

            update_machine_series(machine_no, series)
            machine_set.add(machine_no)

    build_docs(sorted(machine_set))

if __name__ == "__main__":
    main()
