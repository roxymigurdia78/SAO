"""物差しの候補を、わざと壊した部屋（defect_test の A〜D）で比べる

目的: 「どこに光が当たっているか」の違いを拾える指標を選ぶ。
      撮影済みの A〜D をそのまま使う（新しい撮影はしない）。

比べる指標（どれも写真と部屋の両方に同じ計算ができるもの）:
  今の物差し  L1 色温度 / L2 明るさの中央値 / L3 σ/μ / L4 白飛び
  候補 C1  明るい部分の明るさ      Y'（ガンマ後の輝度）の上位5%（P95）
  候補 C2  明るい部分の面積        線形輝度 Y が中央値の2倍以上の画素の割合
  候補 C3  明るさの偏り            画面を3×3に分け、一番明るいマス÷一番暗いマス（log2）
  候補 C4  境目の強さ              Y' の隣どうしの差の平均
  候補 C5  GCF                     Global Contrast Factor（Matković et al. 2005）
                                   9段階の解像度で局所コントラストを測り、重み付きで足す

判定の仕方（視点ごとに対にして比べる。8視点の中央値どうしは比べない）:
  動き   = （壊した版の値 − A の値）÷ 写真の P90−P10        … 視点ごと
  一貫性 = 8視点のうち、同じ向きに動いた視点の数
  → 動きが大きく、一貫性が高い指標ほど、その違いを拾えている

使い方（sao フォルダで）:
  python mvl-skeleton\\python\\metric_candidates.py --defect research\\defect_test\\defect_20261014_174732.json

出力: research\\defect_test\\candidates_<日時>.json
      research\\defect_test\\diff_<版>.png   … A との明るさの差の地図（どこが変わったか）
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from light_metrics import load, metrics, pick_photos, srgb_to_linear   # noqa: E402

SAO = Path(__file__).resolve().parents[2]
RUNS = SAO / "mvl-skeleton" / "runs"
OUT = SAO / "research" / "defect_test"
LUMA = np.array([0.2126, 0.7152, 0.0722])

BASE_KEYS = ["L1_cct_ohno_K", "L2_median", "L3_rms_rel", "L4_clip"]
NEW_KEYS = ["C1_p95", "C2_bright_area", "C3_grid_log2", "C4_edge", "C5_gcf"]
NAMES = {"L1_cct_ohno_K": "L1 色温度", "L2_median": "L2 明るさ", "L3_rms_rel": "L3 σ/μ",
         "L4_clip": "L4 白飛び", "C1_p95": "C1 明るい部分", "C2_bright_area": "C2 明るい面積",
         "C3_grid_log2": "C3 偏り3×3", "C4_edge": "C4 境目", "C5_gcf": "C5 GCF"}


# ======================================================================
# 1. 候補の指標
# ======================================================================
def gcf(rgb):
    """Global Contrast Factor（Matković, Neumann, Neumann, Purgathofer, Szirmay-Kalos 2005）
    1. 線形輝度 → 知覚の明るさ L = 100*sqrt(Y)
    2. 各解像度で、上下左右との差の平均（局所コントラスト）を画像全体で平均 → C_i
    3. 解像度を半分ずつ（2×2平均）にして9段階。重み w_i を掛けて足す"""
    L = 100.0 * np.sqrt(srgb_to_linear(rgb) @ LUMA)
    total = 0.0
    for i in range(1, 10):
        h, w = L.shape
        if h < 2 or w < 2:
            c = 0.0
        else:
            d = np.zeros_like(L)
            n = np.zeros_like(L)
            dv = np.abs(L[1:, :] - L[:-1, :])
            dh = np.abs(L[:, 1:] - L[:, :-1])
            d[1:, :] += dv; n[1:, :] += 1
            d[:-1, :] += dv; n[:-1, :] += 1
            d[:, 1:] += dh; n[:, 1:] += 1
            d[:, :-1] += dh; n[:, :-1] += 1
            c = float((d / n).mean())
        x = i / 9.0
        total += ((-0.406385 * x + 0.334573) * x + 0.0877526) * c
        h2, w2 = L.shape[0] // 2, L.shape[1] // 2          # 次の解像度（2×2の平均）
        if h2 >= 1 and w2 >= 1:
            L = L[:h2 * 2, :w2 * 2].reshape(h2, 2, w2, 2).mean(axis=(1, 3))
    return total


def candidates(rgb):
    luma = rgb @ LUMA                          # Y'（ガンマ後）
    Y = srgb_to_linear(rgb) @ LUMA             # 線形
    med = np.median(Y)
    h, w = Y.shape
    cells = [Y[r * h // 3:(r + 1) * h // 3, c * w // 3:(c + 1) * w // 3].mean()
             for r in range(3) for c in range(3)]
    eps = 1e-4
    edge = (np.abs(np.diff(luma, axis=0)).mean() + np.abs(np.diff(luma, axis=1)).mean()) / 2
    return {
        "C1_p95": float(np.percentile(luma, 95)),
        "C2_bright_area": float((Y >= 2 * med).mean()) if med > 0 else float("nan"),
        "C3_grid_log2": float(np.log2((max(cells) + eps) / (min(cells) + eps))),
        "C4_edge": float(edge),
        "C5_gcf": gcf(rgb),
    }


def all_metrics(path):
    rgb = load(path)
    m = metrics(rgb)
    return {**{k: m[k] for k in BASE_KEYS}, **candidates(rgb)}


# ======================================================================
# 2. 差の地図（どこが変わったか）
# ======================================================================
def diff_map(dir_a, dir_x, out_png):
    """A と X の Y' の差を、視点ごとに並べた画像。赤=X が明るい / 青=X が暗い"""
    tiles = []
    for va in sorted(Path(dir_a).glob("view_*.png")):
        a = np.asarray(Image.open(va).convert("RGB"), dtype=float) / 255 @ LUMA
        x = np.asarray(Image.open(Path(dir_x) / va.name).convert("RGB"), dtype=float) / 255 @ LUMA
        d = np.clip((x - a) / 0.3, -1, 1)                 # ±0.3 で色が振り切れる
        rgb = np.stack([np.clip(d, 0, 1), np.zeros_like(d), np.clip(-d, 0, 1)], -1)
        gray = np.stack([a] * 3, -1) * 0.35               # 元の部屋をうっすら重ねる
        img = np.clip(gray + rgb, 0, 1)
        tiles.append(Image.fromarray((img * 255).astype(np.uint8)).resize((480, 270)))
    cols = 4
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (480 * cols, 270 * rows))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % cols) * 480, (i // cols) * 270))
    sheet.save(out_png)


# ======================================================================
# 3. 本体
# ======================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--defect", required=True, help="defect_test.py が出した記録JSON")
    ap.add_argument("--photo-dir", default=str(SAO / "research" / "data_256" / "h" / "home_office"))
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    rec = json.loads(Path(a.defect).read_text(encoding="utf-8"))
    runs, labels = rec["runs"], rec["labels"]
    keys = BASE_KEYS + NEW_KEYS

    # 写真の範囲（今の物差しと同じ100枚）
    photos = [all_metrics(p) for p in pick_photos(a.photo_dir, a.n, a.seed)]
    width = {}
    print(f"写真 {len(photos)} 枚の範囲")
    for k in keys:
        p10, p90 = np.nanpercentile([p[k] for p in photos], [10, 90])
        width[k] = p90 - p10
        print(f"  {NAMES[k]:12s} P10 {p10:10.4g}  P90 {p90:10.4g}")

    # 部屋（視点ごと）
    cap = {k: RUNS / r / "iter_00" / "capture" for k, r in runs.items()}
    room = {k: [all_metrics(v) for v in sorted(d.glob("view_*.png"))] for k, d in cap.items()}
    n_view = len(room["A"])

    print("\n動き（視点ごとに A と対にした差 ÷ 写真の幅）の平均 ／ 最大 ／ 同じ向きの視点数")
    result = {}
    for x in runs:
        if x == "A":
            continue
        print(f"\n[{x} {labels[x]}]")
        result[x] = {}
        for k in keys:
            d = np.array([(room[x][i][k] - room["A"][i][k]) / width[k] for i in range(n_view)])
            same = int(max((d > 0).sum(), (d < 0).sum()))
            result[x][k] = {"per_view": d.tolist(), "mean": float(d.mean()),
                            "max_abs": float(np.abs(d).max()), "same_sign": same}
            print(f"  {NAMES[k]:12s} 平均 {d.mean():+7.3f}  最大 {np.abs(d).max():6.3f}  "
                  f"同じ向き {same}/{n_view}")
        diff_map(cap["A"], cap[x], OUT / f"diff_{x}.png")

    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"candidates_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps({"defect": a.defect, "photo_width": width, "result": result,
                               "room": room}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n記録: {out}")
    print(f"差の地図: {OUT / 'diff_B.png'} ほか（赤=A より明るい / 青=A より暗い）")


if __name__ == "__main__":
    main()
