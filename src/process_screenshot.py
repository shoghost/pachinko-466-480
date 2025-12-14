from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np
import pandas as pd


@dataclass
class ExtractResult:
    series: np.ndarray          # shape: (N,)
    daily_final: float
    daily_max: float
    daily_min: float


def _find_white_panel(img_bgr: np.ndarray) -> np.ndarray:
    """外側の黒枠などを除いて、白いパネル部分を自動で切り出す。"""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    _, th = cv2.threshold(gray, 235, 255, cv2.THRESH_BINARY)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15)), iterations=2)
    contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return img_bgr
    c = max(contours, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(c)
    return img_bgr[y:y + h, x:x + w]


def _detect_tick_y_positions(panel_bgr: np.ndarray) -> List[int]:
    """
    左端の目盛り（30000, 25000, ... -30000）の“文字がある高さ”を検出してY座標リスト化。
    目盛りの高さが取れれば、y→値の変換が超安定する。
    """
    gray = cv2.cvtColor(panel_bgr, cv2.COLOR_BGR2GRAY)
    left = gray[:, :90]  # ラベル領域
    _, inv = cv2.threshold(left, 200, 255, cv2.THRESH_BINARY_INV)

    row = inv.sum(axis=1).astype(float)
    # 軽く平滑化
    kernel = np.ones(9) / 9
    smooth = np.convolve(row, kernel, mode="same")

    thr = smooth.max() * 0.25
    peaks = []
    for i in range(2, len(smooth) - 2):
        if smooth[i] > thr and smooth[i] > smooth[i - 1] and smooth[i] >= smooth[i + 1]:
            peaks.append(i)

    # 近いピークをクラスタリング
    clusters: List[List[int]] = []
    for p in peaks:
        if not clusters or p - clusters[-1][-1] > 15:
            clusters.append([p])
        else:
            clusters[-1].append(p)

    ys = sorted(int(np.mean(c)) for c in clusters)

    # だいたい 13本（30000〜-30000, 5000刻み）が期待値
    if len(ys) < 9:
        raise RuntimeError(f"tick detection failed: got {len(ys)} ticks")
    return ys


def _y_to_value_fn(tick_y: List[int]) -> callable:
    """
    tick_y（上→下）に対して、値（30000→-30000）を対応させて
    y座標→値へ線形補間する関数を返す。
    """
    # 上から下へ 5000刻みを仮定（このタイプのグラフなら固定のはず）
    # tick数が13のとき：30000,25000,...,-30000
    step = 5000
    top_value = 30000
    values = [top_value - step * i for i in range(len(tick_y))]
    ty = np.array(tick_y, dtype=float)
    tv = np.array(values, dtype=float)

    def f(y: float) -> float:
        if y <= ty[0]:
            return float(tv[0])
        if y >= ty[-1]:
            return float(tv[-1])
        i = int(np.searchsorted(ty, y) - 1)

        # ★追加：念のため境界クランプ
        if i >= len(ty) - 1:
            i = len(ty) - 2
        if i < 0:
            i = 0

        y0, y1 = ty[i], ty[i + 1]
        v0, v1 = tv[i], tv[i + 1]
        return float(v0 + (v1 - v0) * ((y - y0) / (y1 - y0)))

    return f


def extract_series_from_image(img_path: Path, points_per_day: int = 720) -> ExtractResult:
    """
    スクショ1枚から、1日分の時系列（points_per_day点）を推定して返す。
    """
    img = cv2.imread(str(img_path))
    if img is None:
        raise RuntimeError(f"failed to read: {img_path}")

    panel = _find_white_panel(img)
    tick_y = _detect_tick_y_positions(panel)
    y_to_val = _y_to_value_fn(tick_y)

    gray = cv2.cvtColor(panel, cv2.COLOR_BGR2GRAY)

    # y軸の縦線を探して、プロット領域の左端を決める（見つからない場合は固定で逃がす）
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=80, minLineLength=200, maxLineGap=10)
    x_axis = 60
    if lines is not None:
        for x1, y1, x2, y2 in lines[:, 0]:
            if abs(x1 - x2) < 3 and abs(y1 - y2) > 200:
                x_axis = int((x1 + x2) / 2)
                break

    x0 = x_axis + 2
    x1 = panel.shape[1] - 10
    y0 = max(0, tick_y[0] - 5)
    y1 = min(panel.shape[0], tick_y[-1] + 5)

    # ピンク線抽出（HSVでマゼンタ系）
    hsv = cv2.cvtColor(panel, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (140, 60, 60), (179, 255, 255))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)), iterations=1)

    ys = []
    for xx in range(x0, x1):
        col = mask[y0:y1, xx]
        idx = np.where(col > 0)[0]
        if len(idx) == 0:
            ys.append(np.nan)
        else:
            ys.append(float(np.median(idx) + y0))
    s = pd.Series(np.array(ys, dtype=float)).interpolate(limit_direction="both")
    y_series = s.to_numpy()

    v_series = np.array([y_to_val(y) for y in y_series], dtype=float)

    # 点数を固定（連結しやすくする）
    if len(v_series) != points_per_day:
        xi = np.linspace(0, len(v_series) - 1, points_per_day)
        v_series = np.interp(xi, np.arange(len(v_series)), v_series)

    return ExtractResult(
        series=v_series,
        daily_final=float(v_series[-1]),
        daily_max=float(np.max(v_series)),
        daily_min=float(np.min(v_series)),
    )
