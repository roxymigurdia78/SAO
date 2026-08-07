# plotting.py — スコア推移グラフ(卒論 図1 になるやつ)
# 横軸=反復、左軸=機械検査の違反件数(棒)、右軸=VLM採点B1〜B5平均(折れ線)
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.family"] = ["Meiryo", "Yu Gothic", "MS Gothic", "sans-serif"]


def plot_run(run_dir, out_path=None):
    run_dir = Path(run_dir)
    iters = sorted(run_dir.glob("iter_*"), key=lambda p: int(p.name.split("_")[1]))
    xs, violations, vlm_means, rolled_back = [], [], [], []
    for it in iters:
        n = int(it.name.split("_")[1])
        vio = json.loads((it / "violations.json").read_text(encoding="utf-8")) if (it / "violations.json").exists() else []
        score = json.loads((it / "scores.json").read_text(encoding="utf-8")) if (it / "scores.json").exists() else None
        meta = json.loads((it / "meta.json").read_text(encoding="utf-8")) if (it / "meta.json").exists() else {}
        xs.append(n)
        violations.append(len(vio))
        vlm_means.append(score.get("mean") if score else None)
        rolled_back.append(meta.get("rolled_back", False))

    fig, ax1 = plt.subplots(figsize=(8, 4.5))
    ax1.bar(xs, violations, color="#C55A11", alpha=0.75, label="機械検査の違反件数")
    ax1.set_xlabel("反復回数")
    ax1.set_ylabel("違反件数", color="#C55A11")
    ax1.tick_params(axis="y", labelcolor="#C55A11")
    ax1.set_xticks(xs)
    ax1.set_ylim(bottom=0)

    ax2 = ax1.twinx()
    vx = [x for x, v in zip(xs, vlm_means) if v is not None]
    vy = [v for v in vlm_means if v is not None]
    if vy:
        ax2.plot(vx, vy, "o-", color="#0E8A7D", linewidth=2, label="VLM採点(B1–B5平均)")
    ax2.set_ylabel("VLM採点(1–5)", color="#0E8A7D")
    ax2.tick_params(axis="y", labelcolor="#0E8A7D")
    ax2.set_ylim(1, 5)

    for x, rb in zip(xs, rolled_back):
        if rb:
            ax1.annotate("巻き戻し", (x, 0.1), ha="center", fontsize=8, color="#595959")

    ax1.set_title("自律ループによる空間品質の推移")
    fig.tight_layout()
    out_path = out_path or run_dir / "score_trajectory.png"
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    return str(out_path)


if __name__ == "__main__":
    import sys
    print(plot_run(sys.argv[1]))
