
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
score_pairs.py -- 人間の判定とAIの判定を突き合わせて一致率を出す

使い方(sao 直下で):
    python mvl-skeleton\\python\\score_pairs.py
    (pairs_key.csv と answers.csv を読む)

answers.csv は pairs.html の「回答をまとめる」で出た行をそのまま保存したもの:
    pair_01,left
    pair_02,tie
    ...
"""
import argparse
import csv
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default="pairs_key.csv")
    ap.add_argument("--answers", default="answers.csv")
    args = ap.parse_args()

    try:
        key = {r["pair_id"]: r for r in csv.DictReader(open(args.key, encoding="utf-8-sig"))}
    except FileNotFoundError:
        print("%s がありません。先に make_pairs.py を実行してください。" % args.key, file=sys.stderr)
        return 2

    ans = {}
    try:
        for line in open(args.answers, encoding="utf-8-sig"):
            line = line.strip()
            if not line or "," not in line:
                continue
            pid, v = [x.strip() for x in line.split(",")[:2]]
            if pid in key and v in ("left", "right", "tie"):
                ans[pid] = v
    except FileNotFoundError:
        print("%s がありません。pairs.html の回答を保存してください。" % args.answers, file=sys.stderr)
        return 2

    print("=" * 78)
    print("%-9s %-7s %-7s %-6s  %s" % ("pair", "あなた", "AI", "一致", "元の実行"))
    print("-" * 78)

    n = agree = 0
    both_decided = both_agree = 0
    h_tie = a_tie = 0
    conf = {}
    criterion_stats = {}

    for pid, k in key.items():
        if pid not in ans:
            continue
        n += 1
        # 人間の「左/右」を、修正前(before)/修正後(after)へ翻訳する
        v = ans[pid]
        if v == "tie":
            human = "tie"
        else:
            picked_after = (v == "left") == (k["left_is"] == "after")
            human = "after" if picked_after else "before"
        # AIの A=修正前 / B=修正後
        ai = {"A": "before", "B": "after"}.get(k["ai_winner"], "tie")

        ok = (human == ai)
        agree += ok
        criterion = k.get("criterion", "").strip()
        if criterion:
            stat = criterion_stats.setdefault(
                criterion, {"n": 0, "agree": 0, "human_tie": 0, "ai_tie": 0})
            stat["n"] += 1
            stat["agree"] += int(ok)
            stat["human_tie"] += int(human == "tie")
            stat["ai_tie"] += int(ai == "tie")
        if human == "tie": h_tie += 1
        if ai == "tie": a_tie += 1
        if human != "tie" and ai != "tie":
            both_decided += 1
            both_agree += ok
        conf[(human, ai)] = conf.get((human, ai), 0) + 1

        print("%-9s %-7s %-7s %-6s  %s %s→%s" % (
            pid, {"before": "前", "after": "後", "tie": "同じ"}[human],
            {"before": "前", "after": "後", "tie": "同じ"}[ai],
            "○" if ok else "×", k["run"][:28], k["before"], k["after"]))

    if n == 0:
        print("突き合わせられる回答がありません。", file=sys.stderr)
        return 2

    missing = len(key) - n
    if missing:
        print(f"警告: {missing} 組が未回答または無効なため、回答済みの分だけ集計します。")

    print("=" * 78)
    print("回答数            : %d 組" % n)
    print("完全一致          : %d / %d  (%.0f%%)" % (agree, n, 100.0 * agree / n))
    if both_decided:
        print("両者が決めた分のみ: %d / %d  (%.0f%%)"
              % (both_agree, both_decided, 100.0 * both_agree / both_decided))
    print("「同じ」の割合    : あなた %d/%d, AI %d/%d" % (h_tie, n, a_tie, n))
    if criterion_stats:
        print("-" * 78)
        print("項目別:")
        for criterion in sorted(criterion_stats):
            stat = criterion_stats[criterion]
            print("  %s: %d / %d  (%.0f%%), 同じ: あなた %d, AI %d" % (
                criterion, stat["agree"], stat["n"],
                100.0 * stat["agree"] / stat["n"],
                stat["human_tie"], stat["ai_tie"]))
    print("-" * 78)
    print("内訳 (あなた → AI):")
    lbl = {"before": "前", "after": "後", "tie": "同じ"}
    for h in ("after", "before", "tie"):
        row = "  %-4s : " % lbl[h]
        row += "  ".join("%s %d" % (lbl[a], conf.get((h, a), 0)) for a in ("after", "before", "tie"))
        print(row)
    print("=" * 78)

    r = 100.0 * agree / n
    if r >= 70:
        print("判断: AIの判定はあなたの感覚とおおむね一致している。採点表を凍結してよい。")
    elif r >= 50:
        print("判断: 微妙。tieが多いなら採点表のアンカーが曖昧な可能性がある。")
    else:
        print("判断: 一致が低い。プロンプトか採点表を見直したほうがよい。凍結は待つこと。")
    print("凍結したら、その日付を手順書に書き、以後 prompts/ を触らないこと。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
