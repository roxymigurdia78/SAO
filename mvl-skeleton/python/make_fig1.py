#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_fig1.py -- 実行ログ(runs/)から卒論図1を生成する

orchestrator.py は再実行しない。既存の runs/<run>/iter_XX/{violations.json,scores.json,meta.json}
を読むだけなので、何度でも作り直せる。

使い方:
    python make_fig1.py runs/wizard_study_seed1_20260820_164441 ^
                        runs/wizard_study_seed2_20260820_172402 ^
                        runs/wizard_study_seed3_20260820_174441 ^
                        runs/wizard_study_seed3_20260820_180741 ^
                        --out figures/fig1.png --csv figures/fig1_data.csv

出力:
    fig1.png       上段=機械検査の違反件数 / 下段=VLM平均スコア(+best-so-far)
    fig1_axes.png  B1〜B5の項目別推移(--axes 指定時)
    fig1_data.csv  図に使った数値そのもの(本文に書く数字用)
"""

import argparse
import csv
import json
import os
import re
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

# ---------------------------------------------------------------- 配色
# 検証済みカテゴリカル配色の先頭3スロット(全ペアでCVD・通常視ともに合格)
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]
INK = "#1c1c1a"
INK_MUTED = "#6b6b66"
GRID = "#e3e3df"
SURFACE = "#fcfcfb"

JP_FONTS = ["Yu Gothic", "Meiryo", "MS Gothic", "Noto Sans CJK JP",
            "Noto Sans JP", "IPAexGothic", "TakaoGothic", "Hiragino Sans"]

LABELS_JA = {
    "iter": "反復回数",
    "viol": "機械検査の違反件数",
    "score": "VLM平均スコア (B1〜B5)",
    "title_a": "機械検査で検出された違反の件数",
    "title_b": "VLM採点の平均スコア",
    "best": "\u30d9\u30b9\u30c8(\u6700\u7d42\u3092\u4e0a\u56de\u308b\u5834\u5408)",
    "rollback": "巻き戻し",
    "axes_title": "採点項目別の推移",
}
LABELS_EN = {
    "iter": "Iteration",
    "viol": "Machine-check violations",
    "score": "VLM mean score (B1-B5)",
    "title_a": "Violations detected by machine checks",
    "title_b": "VLM mean score",
    "best": "\u30d9\u30b9\u30c8(\u6700\u7d42\u3092\u4e0a\u56de\u308b\u5834\u5408)",
    "rollback": "rolled back",
    "axes_title": "Per-criterion trajectory",
}


def pick_font():
    """日本語フォントがあれば使う。無ければ英語ラベルに落とす。"""
    try:
        from matplotlib import font_manager
        have = {f.name for f in font_manager.fontManager.ttflist}
    except Exception:
        return None
    for name in JP_FONTS:
        if name in have:
            return name
    return None


# ---------------------------------------------------------------- ログ読み

def read_run(run_dir):
    """1ランのログを読む。戻り値: dict"""
    iters = sorted(
        (d for d in os.listdir(run_dir) if re.fullmatch(r"iter_\d+", d)),
        key=lambda d: int(d.split("_")[1]),
    )
    if not iters:
        raise SystemExit("iter_XX が無い: %s" % run_dir)

    rec = {"dir": run_dir, "n": [], "viol": [], "mean": [],
           "B": {k: [] for k in ("B1", "B2", "B3", "B4", "B5")},
           "rolled_back": [], "repairs": []}

    for d in iters:
        i = int(d.split("_")[1])
        p = os.path.join(run_dir, d)
        rec["n"].append(i)

        vp = os.path.join(p, "violations.json")
        rec["viol"].append(len(json.load(open(vp, encoding="utf-8")))
                           if os.path.exists(vp) else None)

        sp = os.path.join(p, "scores.json")
        if os.path.exists(sp):
            s = json.load(open(sp, encoding="utf-8"))
            m = s.get("mean")
            if m is None:
                vals = [s.get(k) for k in ("B1", "B2", "B3", "B4", "B5")]
                m = sum(vals) / 5.0 if all(v is not None for v in vals) else None
            rec["mean"].append(m)
            for k in rec["B"]:
                rec["B"][k].append(s.get(k))
        else:
            rec["mean"].append(None)
            for k in rec["B"]:
                rec["B"][k].append(None)

        mp = os.path.join(p, "meta.json")
        if os.path.exists(mp):
            mt = json.load(open(mp, encoding="utf-8"))
            rec["rolled_back"].append(bool(mt.get("rolled_back")))
            rec["repairs"].append(len(mt.get("applied_repairs", [])))
        else:
            rec["rolled_back"].append(False)
            rec["repairs"].append(0)

    # ラベル: wizard_study_seed3_20260820_180741 → "seed3"(同一seedが複数あれば時刻で区別)
    base = os.path.basename(os.path.normpath(run_dir))
    m = re.search(r"seed(\d+)", base)
    rec["seed"] = int(m.group(1)) if m else 0
    rec["stamp"] = base.split("_")[-1]
    return rec


def best_so_far(vals):
    out, best = [], None
    for v in vals:
        if v is not None:
            best = v if best is None else max(best, v)
        out.append(best)
    return out


# ---------------------------------------------------------------- 描画

def style_axis(ax, L):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
        ax.spines[side].set_linewidth(1.0)
    ax.grid(True, axis="y", color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    ax.tick_params(colors=INK_MUTED, labelsize=9, length=0)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))


def series_style(runs):
    """色は seed に紐づける(順位ではなく実体に紐づける)。同一seedの2本目は破線+白抜き。"""
    seen, styles = {}, []
    for r in runs:
        k = r["seed"]
        idx = seen.setdefault(k, len(seen))
        nth = sum(1 for s in styles if s["seed"] == k)
        styles.append({
            "seed": k,
            "color": SERIES[idx % len(SERIES)],
            "ls": "-" if nth == 0 else (0, (5, 2)),
            "fill": True if nth == 0 else False,
            "label": "seed%d" % k if nth == 0 else "seed%d (2\u56de\u76ee)" % k,
        })
    return styles


def _plot(ax, xs, ys, st, lw=2.0, ms=5):
    ax.plot(xs, ys, linestyle=st["ls"], color=st["color"], linewidth=lw,
            marker="o", markersize=ms,
            markerfacecolor=st["color"] if st["fill"] else SURFACE,
            markeredgecolor=SURFACE if st["fill"] else st["color"],
            markeredgewidth=1.5, label=st["label"], zorder=3)


def draw(runs, out, L, show_best=True):
    styles = series_style(runs)
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(7.6, 6.8), sharex=True,
        gridspec_kw={"height_ratios": [1, 1.35], "hspace": 0.26})
    fig.patch.set_facecolor(SURFACE)

    # ---- 上段: 違反件数(決定的・ノイズなし)
    style_axis(ax1, L)
    vmax = 0
    for r, st in zip(runs, styles):
        xs = [x for x, v in zip(r["n"], r["viol"]) if v is not None]
        ys = [v for v in r["viol"] if v is not None]
        if not ys:
            continue
        vmax = max(vmax, max(ys))
        _plot(ax1, xs, ys, st)
    ax1.set_ylabel(L["viol"], color=INK_MUTED, fontsize=10)
    ax1.set_title(L["title_a"], color=INK, fontsize=11.5, loc="left", pad=10)
    ax1.set_ylim(-0.35, vmax + 0.6)
    ax1.set_yticks(range(0, vmax + 1))

    # ---- 下段: VLM平均スコア(ノイズあり)
    style_axis(ax2, L)
    for r, st in zip(runs, styles):
        xs = [x for x, v in zip(r["n"], r["mean"]) if v is not None]
        ys = [v for v in r["mean"] if v is not None]
        if not ys:
            continue
        _plot(ax2, xs, ys, st)

        rb = [(x, v) for x, v, f in zip(r["n"], r["mean"], r["rolled_back"])
              if f and v is not None]
        if rb:
            ax2.plot([p[0] for p in rb], [p[1] for p in rb], linestyle="none",
                     marker="o", markersize=9, markerfacecolor="none",
                     markeredgecolor=st["color"], markeredgewidth=1.8, zorder=4)

        if show_best:
            bi = max(range(len(ys)), key=lambda i: ys[i])
            if ys[bi] > ys[-1] + 1e-9:      # 最終がベストを下回るランだけ印を出す
                ax2.plot([xs[bi]], [ys[bi]], linestyle="none", marker="*",
                         markersize=15, color=st["color"],
                         markeredgecolor=SURFACE, markeredgewidth=1.0, zorder=5)
                ax2.plot([xs[bi], xs[-1]], [ys[bi], ys[bi]], linestyle=":",
                         color=st["color"], linewidth=1.0, alpha=0.55, zorder=1)

        ax2.annotate("%.2f" % ys[-1], (xs[-1], ys[-1]),
                     textcoords="offset points", xytext=(8, 0),
                     color=INK, fontsize=9.5, va="center")

    ax2.set_ylabel(L["score"], color=INK_MUTED, fontsize=10)
    ax2.set_xlabel(L["iter"], color=INK_MUTED, fontsize=10)
    ax2.set_title(L["title_b"], color=INK, fontsize=11.5, loc="left", pad=10)
    ax2.set_ylim(1, 5)
    ax2.set_yticks([1, 2, 3, 4, 5])
    ax2.set_xlim(-0.35, max(max(r["n"]) for r in runs) + 0.75)

    from matplotlib.lines import Line2D
    handles = [Line2D([], [], color=st["color"], linestyle=st["ls"], lw=2.0,
                      marker="o", markersize=5,
                      markerfacecolor=st["color"] if st["fill"] else SURFACE,
                      markeredgecolor=SURFACE if st["fill"] else st["color"],
                      markeredgewidth=1.5, label=st["label"])
               for st in styles]
    handles += [
        Line2D([], [], color=INK_MUTED, marker="o", lw=0, markersize=9,
               markerfacecolor="none", markeredgewidth=1.8, label=L["rollback"]),
    ]
    if show_best:
        handles.append(Line2D([], [], color=INK_MUTED, marker="*", lw=0,
                              markersize=13, label=L["best"]))
    fig.legend(handles=handles, frameon=False, fontsize=9.5, labelcolor=INK_MUTED,
               loc="lower center", ncol=min(6, len(handles)),
               bbox_to_anchor=(0.5, -0.045), columnspacing=1.6, handletextpad=0.5)

    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    fig.savefig(out, dpi=300, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    print("\u56f3:", out)


def draw_axes(runs, out, L):
    """B1〜B5の項目別。ループが触れる項目と触れない項目を可視化する。"""
    keys = ["B1", "B2", "B3", "B4", "B5"]
    names = {"B1": "B1 スケール", "B2": "B2 照明", "B3": "B3 配置",
             "B4": "B4 材質", "B5": "B5 臨場感"}
    styles = series_style(runs)
    fig, axs = plt.subplots(1, 5, figsize=(12.5, 2.9), sharey=True)
    fig.patch.set_facecolor(SURFACE)
    for ax, k in zip(axs, keys):
        style_axis(ax, L)
        for r, st in zip(runs, styles):
            xs = [x for x, v in zip(r["n"], r["B"][k]) if v is not None]
            ys = [v for v in r["B"][k] if v is not None]
            _plot(ax, xs, ys, st, lw=1.8, ms=4)
        ax.set_title(names[k], color=INK, fontsize=10, loc="left", pad=6)
        ax.set_ylim(0.5, 5.5)
        ax.set_yticks([1, 2, 3, 4, 5])
        ax.set_xlabel(L["iter"], color=INK_MUTED, fontsize=9)
    axs[0].legend(frameon=False, fontsize=8, labelcolor=INK_MUTED)
    fig.suptitle(L["axes_title"], color=INK, fontsize=11, x=0.01, ha="left")
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    fig.savefig(out, dpi=300, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    print("図:", out)


def write_csv(runs, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["run", "seed", "iteration", "violations", "mean",
                    "B1", "B2", "B3", "B4", "B5", "rolled_back", "n_repairs"])
        for r in runs:
            base = os.path.basename(os.path.normpath(r["dir"]))
            for j, i in enumerate(r["n"]):
                w.writerow([base, r["seed"], i, r["viol"][j], r["mean"][j]]
                           + [r["B"][k][j] for k in ("B1", "B2", "B3", "B4", "B5")]
                           + [r["rolled_back"][j], r["repairs"][j]])
    print("数値:", path)


def summarize(runs):
    print("=" * 74)
    print("%-34s %6s %6s %6s %6s %6s" % ("run", "iters", "違反初", "違反終", "初スコア", "終スコア"))
    print("-" * 74)
    for r in runs:
        ms = [v for v in r["mean"] if v is not None]
        base = os.path.basename(os.path.normpath(r["dir"]))
        print("%-34s %6d %6s %6s %6s %6s" % (
            base[:34], len(r["n"]),
            r["viol"][0], r["viol"][-1],
            ("%.2f" % ms[0]) if ms else "-",
            ("%.2f" % ms[-1]) if ms else "-"))
        if ms:
            b = max(ms)
            if ms[-1] < b - 1e-9:
                print("      ! 最終(%.2f)がベスト(%.2f, iter %d)を下回っている"
                      % (ms[-1], b, r["mean"].index(b)))
    print("=" * 74)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+", help="runs/<run_dir> を複数")
    ap.add_argument("--out", default="figures/fig1.png")
    ap.add_argument("--axes", default="", help="項目別の図の出力先(省略時は作らない)")
    ap.add_argument("--csv", default="figures/fig1_data.csv")
    ap.add_argument("--no-best", action="store_true", help="best-so-farを描かない")
    ap.add_argument("--lang", choices=["auto", "ja", "en"], default="auto")
    args = ap.parse_args()

    font = pick_font()
    if args.lang == "ja" or (args.lang == "auto" and font):
        if not font:
            print("!! 日本語フォントが見つからないので英語ラベルにします", file=sys.stderr)
            L = LABELS_EN
        else:
            plt.rcParams["font.family"] = font
            plt.rcParams["axes.unicode_minus"] = False
            L = LABELS_JA
            print("フォント:", font)
    else:
        L = LABELS_EN

    runs = [read_run(d) for d in args.runs]
    runs.sort(key=lambda r: (r["seed"], r["stamp"]))
    summarize(runs)
    draw(runs, args.out, L, show_best=not args.no_best)
    if args.axes:
        draw_axes(runs, args.axes, L)
    write_csv(runs, args.csv)


if __name__ == "__main__":
    main()
