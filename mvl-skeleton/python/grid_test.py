"""明るさの偏り（2×2・3×3・4×4）が、日なた・影の変化を「正しい場所で」拾えるかのテスト

目的: 物差しに「光がどこに当たっているか」を足す前に、候補が狙った変化を拾えるかを確かめる。
      撮影済みの defect_test（A 基準 / B 家具の影なし / C 窓の光なし / D 平坦に近い）を使う。新しい撮影はしない。

偏りの計算（写真にも部屋にも同じ計算）:
  画面を n×n のマスに分け、マスごとに線形輝度 Y の平均を出す
  偏り = log2( 一番明るいマス ÷ 一番暗いマス )

判定（10/14 決定。結果を見る前に決めた基準）:
  変化のある視点 : A との差 |ΔY'| が 0.05 以上の画素が 1% 以上ある視点
  拾えた         : 変化のある視点で
                   ① |偏りの差| ÷ 写真の P90−P10 が 0.2 以上
                   ② 一番変化したマスが、偏りを決めているマス（A か壊した版の、最も明るい/暗いマス）に入っている
  L1〜L4 も同じ表に並べる（場所の判定はできないので ① だけ）

使い方（sao フォルダで）:
  python mvl-skeleton\\python\\grid_test.py --defect research\\defect_test\\defect_20261014_174732.json

出力: research\\defect_test\\grid_<日時>.json      … 視点ごと・マスごとの値を全部
      research\\defect_test\\grid_map_<版>.png      … A との差の地図（赤=明るくなった/青=暗くなった）＋3×3の線
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from light_metrics import load, metrics, pick_photos, srgb_to_linear   # noqa: E402  同じ読み込み・同じ計算

SAO = Path(__file__).resolve().parents[2]
RUNS = SAO / "mvl-skeleton" / "runs"
OUT = SAO / "research" / "defect_test"
LUMA = np.array([0.2126, 0.7152, 0.0722])
GRIDS = [2, 3, 4]
L_KEYS = ["L1_cct_ohno_K", "L2_median", "L3_rms_rel", "L4_clip"]
EPS = 1e-4

PASS = 0.2           # 拾えた: 写真の幅の 0.2 以上（10/14 決定）
DIFF_PIX = 0.05      # 変化した画素: |ΔY'| がこれ以上
DIFF_FRAC = 0.01     # 変化のある視点: 変化した画素がこの割合以上


# ======================================================================
# 1. 偏り
# ======================================================================
def cell_means(Y, n):
    h, w = Y.shape
    return np.array([[Y[r * h // n:(r + 1) * h // n, c * w // n:(c + 1) * w // n].mean()
                      for c in range(n)] for r in range(n)])


def bias(rgb, n):
    """偏り・マスの値・一番明るいマス・一番暗いマス（マス番号は 左上=0 から横に数える）"""
    Y = srgb_to_linear(rgb) @ LUMA
    cells = cell_means(Y, n)
    flat = cells.ravel()
    return {"bias": float(np.log2((flat.max() + EPS) / (flat.min() + EPS))),
            "cells": cells.tolist(), "max_cell": int(flat.argmax()), "min_cell": int(flat.argmin())}


def measure(rgb):
    m = metrics(rgb)
    return {**{k: m[k] for k in L_KEYS}, **{f"G{n}": bias(rgb, n) for n in GRIDS}}


def value(m, key):
    return m[key]["bias"] if key.startswith("G") else m[key]


# ======================================================================
# 2. どこが変わったか
# ======================================================================
def change(rgb_a, rgb_x, n):
    """変化した画素の割合と、マスごとの変化量の割合（どのマスが一番変わったか）"""
    d = np.abs(rgb_x @ LUMA - rgb_a @ LUMA)                       # Y' の差
    frac = float((d >= DIFF_PIX).mean())
    share = cell_means(d, n).ravel()
    share = share / share.sum() if share.sum() > 0 else share
    return frac, share


def save_map(rgbs_a, rgbs_x, out_png, n=3):
    tiles = []
    for a, x in zip(rgbs_a, rgbs_x):
        d = np.clip((x @ LUMA - a @ LUMA) / 0.3, -1, 1)
        img = np.clip(np.stack([a @ LUMA] * 3, -1) * 0.35
                      + np.stack([np.clip(d, 0, 1), np.zeros_like(d), np.clip(-d, 0, 1)], -1), 0, 1)
        t = Image.fromarray((img * 255).astype(np.uint8)).resize((480, 270))
        dr = ImageDraw.Draw(t)
        for i in range(1, n):
            dr.line([(480 * i // n, 0), (480 * i // n, 270)], fill=(255, 255, 0))
            dr.line([(0, 270 * i // n), (480, 270 * i // n)], fill=(255, 255, 0))
        tiles.append(t)
    sheet = Image.new("RGB", (480 * 4, 270 * ((len(tiles) + 3) // 4)))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % 4) * 480, (i // 4) * 270))
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
    keys = L_KEYS + [f"G{n}" for n in GRIDS]

    # 写真の範囲（今の物差しと同じ100枚）
    photos = [measure(load(p)) for p in pick_photos(a.photo_dir, a.n, a.seed)]
    width = {}
    print(f"写真 {len(photos)} 枚の範囲")
    for k in keys:
        p10, p90 = np.nanpercentile([value(p, k) for p in photos], [10, 90])
        width[k] = float(p90 - p10)
        print(f"  {k:14s} P10 {p10:9.4g}  P90 {p90:9.4g}")

    # 部屋
    imgs = {x: [load(v) for v in sorted((RUNS / r / "iter_00" / "capture").glob("view_*.png"))]
            for x, r in runs.items()}
    room = {x: [measure(im) for im in imgs[x]] for x in runs}
    n_view = len(imgs["A"])

    record = {"defect": a.defect, "rule": {"pass": PASS, "diff_pix": DIFF_PIX, "diff_frac": DIFF_FRAC},
              "photo_width": width, "variants": {}}
    for x in runs:
        if x == "A":
            continue
        print(f"\n==================== {x} {labels[x]} ====================")
        rows = []
        for i in range(n_view):
            frac, _ = change(imgs["A"][i], imgs[x][i], 3)
            rows.append({"view": i, "changed_frac": frac, "has_change": frac >= DIFF_FRAC})
        changed = [r["view"] for r in rows if r["has_change"]]
        print(f"変化のある視点: {len(changed)}/{n_view}  " +
              "  ".join(f"v{r['view']}:{r['changed_frac']*100:.1f}%" for r in rows))

        summary = {}
        print(f"\n{'指標':14s}{'拾えた':>8s}{'動きの平均':>12s}{'動きの最大':>12s}   ※動き＝差÷写真の幅（変化のある視点だけ）")
        for k in keys:
            det, moves = 0, []
            for i in changed:
                mv = (value(room[x][i], k) - value(room["A"][i], k)) / width[k]
                moves.append(mv)
                ok = abs(mv) >= PASS
                if ok and k.startswith("G"):
                    n = int(k[1:])
                    _, share = change(imgs["A"][i], imgs[x][i], n)
                    top = int(share.argmax())
                    who = {room["A"][i][k]["max_cell"], room["A"][i][k]["min_cell"],
                           room[x][i][k]["max_cell"], room[x][i][k]["min_cell"]}
                    ok = top in who
                det += ok
            mv = np.array(moves) if moves else np.array([0.0])
            summary[k] = {"detected": det, "of": len(changed), "moves": mv.tolist()}
            print(f"{k:14s}{f'{det}/{len(changed)}':>8s}{mv.mean():>+12.3f}{np.abs(mv).max():>12.3f}")

        # マスの細かい内訳（偏りの3種類だけ）
        print("\n視点ごとの内訳（偏り）: 動き / 一番変化したマス / 偏りを決めているマス(A 明,暗 → 壊した版 明,暗) / 判定")
        for n in GRIDS:
            k = f"G{n}"
            print(f"  [{n}×{n}]")
            for i in changed:
                _, share = change(imgs["A"][i], imgs[x][i], n)
                top = int(share.argmax())
                ra, rx = room["A"][i][k], room[x][i][k]
                mv = (rx["bias"] - ra["bias"]) / width[k]
                who = {ra["max_cell"], ra["min_cell"], rx["max_cell"], rx["min_cell"]}
                verdict = "拾えた" if abs(mv) >= PASS and top in who else (
                    "場所が違う" if abs(mv) >= PASS else "動きが小さい")
                print(f"    v{i}: {mv:+.3f}  変化マス {top}（{share[top]*100:.0f}%）  "
                      f"A {ra['max_cell']},{ra['min_cell']} → {rx['max_cell']},{rx['min_cell']}  {verdict}")

        save_map(imgs["A"], imgs[x], OUT / f"grid_map_{x}.png")
        record["variants"][x] = {"label": labels[x], "views": rows, "summary": summary,
                                 "room_A": room["A"], "room_x": room[x]}

    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"grid_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n記録: {out}")
    print(f"差の地図: {OUT / 'grid_map_C.png'} ほか（赤=明るくなった / 青=暗くなった / 黄線=3×3）")
    print("マス番号: 左上=0 から横に数える（3×3 なら 上段 0 1 2 / 中段 3 4 5 / 下段 6 7 8）")


if __name__ == "__main__":
    main()
