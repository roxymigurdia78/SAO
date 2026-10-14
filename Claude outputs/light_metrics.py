"""光のループの「ものさし」お試し（引き継ぎ書 §12.3）

目的: 実写の室内写真（Places365 home_office）で L1〜L4 の P10〜P90 を出し、
      今の部屋の全景8枚を「同じ大きさ・同じ関数」で計算して並べる。

L1 色温度    : 平均色(線形RGB) → XYZ → xy → McCamy の式で K
L2 明るさ    : 輝度(ガンマ後のY', 0〜1)の中央値
L3 コントラスト: 輝度の標準偏差
L4 白飛び/黒つぶれ: 輝度 >=0.99 / <=0.01 の画素の割合（合計と内訳）

使い方:
  python light_metrics.py --photo-dir <data_256/h/home_office> [--n 100 --seed 0]
                          --room-dir <run>/capture --out <出力フォルダ>
写真: Places365-Standard 学習用 data_256 の home_office（5000枚）から seed 固定で n 枚
"""
import argparse
import csv
from pathlib import Path

import numpy as np
from PIL import Image

SIZE = 256  # Places365 val_256 は縦横比を無視して 256x256。全景も同じ縮め方にそろえる


# ---- 1枚を読む（写真も全景もこの関数を通る） ----
def load(path):
    img = Image.open(path).convert("RGB")
    if img.size != (SIZE, SIZE):
        img = img.resize((SIZE, SIZE), Image.BICUBIC)
    return np.asarray(img, dtype=np.float64) / 255.0  # sRGB(ガンマ後) 0〜1


def srgb_to_linear(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


# ---- L1〜L4 ----
def cct_mccamy(rgb_srgb):
    lin = srgb_to_linear(rgb_srgb).reshape(-1, 3).mean(axis=0)  # 平均は線形空間で取る
    M = np.array([[0.4124, 0.3576, 0.1805],    # sRGB(D65) → XYZ
                  [0.2126, 0.7152, 0.0722],
                  [0.0193, 0.1192, 0.9505]])
    X, Y, Z = M @ lin
    s = X + Y + Z
    if s <= 0:
        return float("nan")
    x, y = X / s, Y / s
    n = (x - 0.3320) / (0.1858 - y)
    return 449 * n**3 + 3525 * n**2 + 6823.3 * n + 5520.33


def metrics(rgb):
    luma = rgb @ np.array([0.2126, 0.7152, 0.0722])  # Y'（ガンマ後の輝度）
    hi = float((luma >= 0.99).mean())
    lo = float((luma <= 0.01).mean())
    return {
        "L1_cct_K": cct_mccamy(rgb),
        "L2_median": float(np.median(luma)),
        "L3_std": float(luma.std()),
        "L3_logstd": float(np.log(luma + 0.01).std()),  # 明るさに左右されにくいコントラスト
        "L4_clip": hi + lo,
        "L4_hi": hi,
        "L4_lo": lo,
    }


KEYS = ["L1_cct_K", "L2_median", "L3_std", "L3_logstd", "L4_clip", "L4_hi", "L4_lo"]


# ---- 写真の選び出し（フォルダから n 枚、seed 固定で再現可能） ----
def pick_photos(photo_dir, n, seed):
    files = sorted(Path(photo_dir).glob("*.jpg"))
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(files), size=n, replace=False)
    return [files[i] for i in sorted(idx)]


def write_rows(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["image"] + KEYS)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--photo-dir", required=True)  # 例: data_256\h\home_office
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--room-dir", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    # 写真
    photos = pick_photos(a.photo_dir, a.n, a.seed)
    print(f"photos: {len(photos)} 枚 (seed={a.seed})")
    photo = [{"image": p.name, **metrics(load(p))} for p in photos]
    write_rows(out / "photos_metrics.csv", photo)

    # 全景8枚
    views = sorted(Path(a.room_dir).glob("view_*.png"))
    print(f"room: {len(views)} 枚")
    room = [{"image": v.name, **metrics(load(v))} for v in views]
    write_rows(out / "room_metrics.csv", room)

    # 範囲と並べる
    with open(out / "summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["metric", "photo_P10", "photo_P50", "photo_P90",
                    "room_min", "room_median", "room_max", "room_in_range"])
        for k in KEYS:
            p = np.array([r[k] for r in photo], dtype=float)
            r = np.array([x[k] for x in room], dtype=float)
            p10, p50, p90 = np.nanpercentile(p, [10, 50, 90])
            if k.startswith("L4"):
                inside = int((r <= p90).sum())  # L4 は上限だけ見る（少ないのは違反にしない）
            else:
                inside = int(((r >= p10) & (r <= p90)).sum())
            w.writerow([k, f"{p10:.4g}", f"{p50:.4g}", f"{p90:.4g}",
                        f"{r.min():.4g}", f"{np.median(r):.4g}", f"{r.max():.4g}",
                        f"{inside}/{len(r)}"])
    print((out / "summary.csv").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
