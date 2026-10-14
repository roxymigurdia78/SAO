"""わざと壊した部屋を、今の物差し（L1〜L4）が見分けられるかを確かめる

目的: 「数字は良くなったのに、見た目はなんとも言えない」の原因が物差しにあるかを確かめる。
      目で見て明らかに違う部屋を作り、L1〜L4 がその違いを拾えるかを見る。
      拾えなければ、「今の物差しは○○の違いを検出できない」という具体的な課題になる。

作る版（同じ部屋・同じ視点。元のシーンから1か所だけ変える）:
  A 基準          そのまま
  B 家具の影なし  家具が影を落とさない（壁の影は残すので、光漏れは起きない）
  C 窓の光なし    太陽 0（天井照明だけ）
  D 平坦に近い    太陽 0 ＋ 家具の影なし

  B が本命。C・D は「明るさが大きく変わる版」で、L1〜L4 が反応して当然の対照。

使い方（sao フォルダで。Unity エディタは閉じておく）:
  python mvl-skeleton\\python\\defect_test.py --scene research\\light_loop\\lightloop_20261013_180234\\best_scene.json
  # 撮影済みなら測るだけ:
  python mvl-skeleton\\python\\defect_test.py --runs A=<ラン名> B=<ラン名> C=<ラン名> D=<ラン名>

前提: MVL.cs の Lighting に furniture_shadows を足し、SceneBuilder.cs がそれを読むこと
"""
import argparse
import copy
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from light_metrics import load, metrics                 # noqa: E402
from light_loop import CHECKS, SAO, SKELETON, capture, measure  # noqa: E402

DEFAULT_REF = SAO / "research" / "light_loop" / "ref_home_office_n100_seed0.json"   # 1回目と同じ物差し


def variants(base):
    """元のシーンから、1か所だけ変えた版を作る"""
    def edit(f):
        s = copy.deepcopy(base)
        f(s["room"]["lighting"])
        return s
    return {
        "A": ("基準", edit(lambda L: L.update(furniture_shadows=True))),
        "B": ("家具の影なし", edit(lambda L: L.update(furniture_shadows=False))),
        "C": ("窓の光なし", edit(lambda L: (L.update(furniture_shadows=True), L["sun"].update(intensity=0.0)))),
        "D": ("平坦に近い", edit(lambda L: (L.update(furniture_shadows=False), L["sun"].update(intensity=0.0)))),
    }


def room_values(capture_dir):
    """全景8枚の L1〜L4（視点ごと）"""
    views = sorted(Path(capture_dir).glob("view_*.png"))
    return [metrics(load(v)) for v in views]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", help="元にするシーンJSON")
    ap.add_argument("--runs", nargs="+", help="撮影済みのラン（A=名前 B=名前 ...）。指定すると撮影しない")
    ap.add_argument("--ref", default=str(DEFAULT_REF), help="物差しJSON（既定は1回目と同じ全写真の物差し）")
    a = ap.parse_args()
    ref = json.loads(Path(a.ref).read_text(encoding="utf-8"))

    # 撮る or 撮影済みを使う
    if a.runs:
        runs = dict(r.split("=", 1) for r in a.runs)
        labels = {"A": "基準", "B": "家具の影なし", "C": "窓の光なし", "D": "平坦に近い"}
    else:
        if not a.scene:
            raise SystemExit("--scene か --runs が必要です")
        base = json.loads(Path(a.scene).read_text(encoding="utf-8"))
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        runs, labels = {}, {}
        for key, (label, scene) in variants(base).items():
            print(f"\n=== {key} {label} を撮影 ===")
            runs[key] = capture(scene, f"defect_{stamp}_{key}").name
            labels[key] = label

    # 測る
    cap = {k: SKELETON / "runs" / r / "iter_00" / "capture" for k, r in runs.items()}
    vals = {k: room_values(d) for k, d in cap.items()}
    med = {k: {m: float(np.median([v[m] for v in vals[k]])) for m in CHECKS} for k in vals}

    print(f"\n物差し: {Path(a.ref).name}")
    print("\n[1] 各版の値（8視点の中央値）と外れ具合")
    print(f"{'版':14s}" + "".join(f"{m:>16s}" for m in CHECKS) + f"{'外れ具合':>10s}")
    for k in runs:
        score, _ = measure(cap[k], ref)
        print(f"{k} {labels[k]:12s}" + "".join(f"{med[k][m]:>16.4g}" for m in CHECKS) + f"{score:>10.3f}")

    print("\n[2] 基準(A)からの動き ÷ 写真の範囲の幅（P90−P10）")
    print("    0.1 なら「範囲の幅の1割だけ動いた」。小さいほど、物差しがその違いに鈍い")
    print(f"{'版':14s}" + "".join(f"{m:>16s}" for m in CHECKS))
    for k in runs:
        if k == "A":
            continue
        row = ""
        for m in CHECKS:
            lo, hi = ref[m][:2]
            row += f"{(med[k][m] - med['A'][m]) / (hi - lo):>+16.3f}"
        print(f"{k} {labels[k]:12s}" + row)

    print("\n[3] 視点ごとの L3（メリハリ）  ※影の有無が一番出そうな項目")
    print(f"{'版':14s}" + "".join(f"{'v' + str(i):>8s}" for i in range(len(vals['A']))))
    for k in runs:
        print(f"{k} {labels[k]:12s}" + "".join(f"{v['L3_rms_rel']:>8.3f}" for v in vals[k]))

    names = ",".join(runs.values())
    print(f"\n目で見比べる:\n  .\\mvl-skeleton\\python\\open_many.ps1 -Names {names}")
    out = SAO / "research" / "defect_test" / f"defect_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"ref": a.ref, "runs": runs, "labels": labels, "median": med,
                               "per_view": vals}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"記録: {out}")


if __name__ == "__main__":
    main()
