# plot_figure1.py — 卒論 図1 の作図(3シード重ね + 軸別内訳)
#
# 使い方(mvl-skeleton 直下で実行):
#   python python\plot_figure1.py
#
# 出力:
#   figures\fig1a_seeds.png   … 3シード重ね(上=機械検査違反件数, 下=VLM採点平均)
#   figures\fig1b_axes.png    … 1シードのB1〜B5内訳(棒=違反件数, 線=各軸スコア)
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.family"] = ["Meiryo", "Yu Gothic", "MS Gothic", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

BASE = Path(__file__).resolve().parent.parent  # mvl-skeleton/
OUT_DIR = BASE / "figures"

# 実行ログ(必要に応じて差し替える)
RUNS = [
    ("Seed1(範囲外)", BASE / "runs/final_seed1/wizard_study_seed1_20260809_135602", "#C55A11"),
    ("Seed2(貫通・浮遊)", BASE / "runs/final_seed2c/wizard_study_seed2_20260809_165616", "#0E8A7D"),
    ("Seed3(尺度・連鎖)", BASE / "runs/final_seed3b/wizard_study_seed3_20260809_160013", "#4472C4"),
]
AXES_TARGET = 2  # 図1bに使うRUNSのインデックス(2=Seed3)

AXIS_LABELS = {
    "B1": "B1 スケール",
    "B2": "B2 照明",
    "B3": "B3 配置",
    "B4": "B4 材質",
    "B5": "B5 総合",
}
AXIS_COLORS = {
    "B1": "#4472C4",
    "B2": "#ED7D31",
    "B3": "#0E8A7D",
    "B4": "#C00000",
    "B5": "#7030A0",
}


def load_run(run_dir):
    """1実行ぶんの反復データを読む。戻り値: list[dict]"""
    run_dir = Path(run_dir)
    if not run_dir.exists():
        raise FileNotFoundError(f"実行ログが見つからない: {run_dir}")
    rows = []
    for it in sorted(run_dir.glob("iter_*"), key=lambda p: int(p.name.split("_")[1])):
        def read(name):
            f = it / name
            if not f.exists():
                return None
            return json.loads(f.read_text(encoding="utf-8"))

        vio = read("violations.json") or []
        sc = read("scores.json")
        meta = read("meta.json") or {}
        rows.append({
            "n": int(it.name.split("_")[1]),
            "violations": len(vio),
            "scores": sc,
            "mean": (sc or {}).get("mean"),
            "rolled_back": meta.get("rolled_back", False),
            "repairs": meta.get("applied_repairs", []) or [],
        })
    if not rows:
        raise ValueError(f"iter_* が無い: {run_dir}")
    return rows


def has_swap(repairs):
    return any("差し替え" in r for r in repairs)


# ---------- 図1a: 3シード重ね ----------

def fig_seeds(runs, out_path):
    fig, (ax_v, ax_s) = plt.subplots(
        2, 1, figsize=(8.2, 6.4), sharex=True,
        gridspec_kw={"height_ratios": [1, 1.15], "hspace": 0.12})

    max_n = 0
    max_v = 1
    for label, run_dir, color in runs:
        rows = load_run(run_dir)
        xs = [r["n"] for r in rows]
        vs = [r["violations"] for r in rows]
        max_n = max(max_n, max(xs))
        max_v = max(max_v, max(vs))

        # 上段: 機械検査の違反件数
        ax_v.plot(xs, vs, "o-", color=color, linewidth=2, markersize=5, label=label)

        # 下段: VLM採点(平均)
        sx = [r["n"] for r in rows if r["mean"] is not None]
        sy = [r["mean"] for r in rows if r["mean"] is not None]
        if sy:
            ax_s.plot(sx, sy, "o-", color=color, linewidth=2, markersize=5, label=label)

        # 注釈: 巻き戻し(×) / バリアント差し替え(△)
        for r in rows:
            if r["mean"] is None:
                continue
            if r["rolled_back"]:
                ax_s.plot(r["n"], r["mean"], "x", color="#404040",
                          markersize=11, markeredgewidth=2, zorder=5)
            if has_swap(r["repairs"]):
                ax_s.plot(r["n"], r["mean"], "^", color=color, markersize=9,
                          markerfacecolor="white", markeredgewidth=1.6, zorder=5)

    ax_v.set_ylabel("機械検査の違反件数")
    ax_v.set_ylim(-0.3, max_v + 0.7)
    ax_v.grid(alpha=0.25, linestyle=":")
    ax_v.legend(loc="upper right", fontsize=9, framealpha=0.9)
    ax_v.set_title("反復による空間品質の推移(3シード)")

    ax_s.set_ylabel("VLM採点 B1–B5平均(1–5)")
    ax_s.set_xlabel("反復回数")
    ax_s.set_ylim(1, 5)
    ax_s.set_xticks(range(0, max_n + 1))
    ax_s.grid(alpha=0.25, linestyle=":")

    # 注釈の凡例(下段のみ)
    handles = [
        plt.Line2D([], [], marker="^", color="#666666", linestyle="none",
                   markerfacecolor="white", markersize=9, label="バリアント差し替えを適用"),
        plt.Line2D([], [], marker="x", color="#404040", linestyle="none",
                   markersize=11, markeredgewidth=2, label="悪化検出により巻き戻し"),
    ]
    ax_s.legend(handles=handles, loc="lower right", fontsize=9, framealpha=0.9)

    fig.tight_layout()
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    return out_path


# ---------- 図1b: 軸別内訳 ----------

def fig_axes(label, run_dir, out_path):
    rows = load_run(run_dir)
    xs = [r["n"] for r in rows]
    vs = [r["violations"] for r in rows]

    fig, ax1 = plt.subplots(figsize=(8.2, 4.8))
    ax1.bar(xs, vs, color="#BFBFBF", alpha=0.65, width=0.55,
            label="機械検査の違反件数", zorder=1)
    ax1.set_xlabel("反復回数")
    ax1.set_ylabel("機械検査の違反件数", color="#595959")
    ax1.tick_params(axis="y", labelcolor="#595959")
    ax1.set_ylim(0, max(vs) + 1)
    ax1.set_xticks(xs)

    ax2 = ax1.twinx()
    for key in ("B1", "B2", "B3", "B4", "B5"):
        px = [r["n"] for r in rows if r["scores"] and r["scores"].get(key) is not None]
        py = [r["scores"][key] for r in rows if r["scores"] and r["scores"].get(key) is not None]
        if not py:
            continue
        ax2.plot(px, py, "o-", color=AXIS_COLORS[key], linewidth=1.9,
                 markersize=5, label=AXIS_LABELS[key], zorder=3)
    ax2.set_ylabel("VLM採点(1–5)")
    ax2.set_ylim(0.8, 5.2)
    ax2.set_yticks([1, 2, 3, 4, 5])
    ax2.grid(alpha=0.2, linestyle=":")

    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax2.legend(h2 + h1, l2 + l1, loc="lower right", fontsize=8.5,
               ncol=2, framealpha=0.9)

    ax1.set_title(f"評価軸ごとの推移({label})")
    fig.tight_layout()
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    return out_path


def main():
    OUT_DIR.mkdir(exist_ok=True)
    p1 = fig_seeds(RUNS, OUT_DIR / "fig1a_seeds.png")
    label, run_dir, _ = RUNS[AXES_TARGET]
    p2 = fig_axes(label, run_dir, OUT_DIR / "fig1b_axes.png")
    print(f"[fig] {p1}")
    print(f"[fig] {p2}")

    # 数値サマリ(図の説明文を書くときの материал)
    print("\n--- サマリ ---")
    for label, run_dir, _ in RUNS:
        rows = load_run(run_dir)
        v0, vN = rows[0]["violations"], rows[-1]["violations"]
        means = [r["mean"] for r in rows if r["mean"] is not None]
        rb = sum(1 for r in rows if r["rolled_back"])
        sw = sum(1 for r in rows if has_swap(r["repairs"]))
        print(f"{label}: 反復{len(rows)} / 違反 {v0}→{vN} / "
              f"VLM {means[0]:.2f}→{means[-1]:.2f}(最大{max(means):.2f}) / "
              f"巻き戻し{rb}回 / 差し替え{sw}回")


if __name__ == "__main__":
    main()