#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""保存済みAI評価から、人間評価用のブラインド比較ページを作る。

sao直下で実行:
    python mvl-skeleton\python\make_pairs.py
    python mvl-skeleton\python\make_pairs.py --mode endpoints

出力:
    pairs.html      人間評価用ページ
    pairs_key.csv   正解キー（評価終了まで開かない）

endpointsモードは pairs_endpoints.html / pairs_endpoints_key.csv に出力する。
"""
import argparse
import csv
import html
import json
import random
import sys
from pathlib import Path
from urllib.parse import quote


def find_adjacent_candidates(runs_dir):
    """比較実行時に実際の基準だった採用済み反復と、比較対象を対応づける。"""
    candidates = []
    for run_dir in sorted(p for p in runs_dir.iterdir() if p.is_dir()):
        accepted_capture = None
        accepted_iter = None
        for iter_dir in sorted(run_dir.glob("iter_[0-9][0-9]")):
            capture_dir = iter_dir / "capture"
            images = sorted(capture_dir.glob("view_*.png"))
            if not images:
                continue

            meta_path = iter_dir / "meta.json"
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
            except (FileNotFoundError, json.JSONDecodeError):
                meta = {}

            winner = meta.get("pairwise_winner")
            if winner in ("A", "B", "tie") and accepted_capture is not None:
                candidates.append({
                    "run": run_dir.name,
                    "before": accepted_iter,
                    "after": iter_dir.name,
                    "before_capture": accepted_capture,
                    "after_capture": capture_dir,
                    "ai_winner": winner,
                })

            # 巻き戻された画像は、次回比較の基準にはならない。
            if not meta.get("rolled_back", False):
                accepted_capture = capture_dir
                accepted_iter = iter_dir.name
    return candidates


def _manifest_runs(csv_paths):
    """図1に採用されたランを、CSV記載順かつ重複なしで返す。"""
    names = []
    for path in csv_paths:
        try:
            rows = csv.DictReader(path.open(encoding="utf-8-sig"))
            for row in rows:
                name = row.get("run")
                if name and name not in names:
                    names.append(name)
        except FileNotFoundError:
            raise FileNotFoundError(f"図1の数値CSVがありません: {path}")
    return names


def _read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def find_endpoint_candidates(runs_dir, csv_paths):
    """図1採用ランのiter_00と、最後の採用済み反復を比較する。"""
    candidates = []
    for run_name in _manifest_runs(csv_paths):
        run_dir = runs_dir / run_name
        accepted = []
        for iter_dir in sorted(run_dir.glob("iter_[0-9][0-9]")):
            capture_dir = iter_dir / "capture"
            if not list(capture_dir.glob("view_*.png")):
                continue
            meta = _read_json(iter_dir / "meta.json", {})
            scores = _read_json(iter_dir / "scores.json", {}) or {}
            if not meta.get("rolled_back", False) and scores.get("total") is not None:
                accepted.append((iter_dir, capture_dir, scores))
        if len(accepted) < 2:
            print(f"警告: 端点が揃わないため除外: {run_name}", file=sys.stderr)
            continue
        before_dir, before_capture, before_scores = accepted[0]
        after_dir, after_capture, after_scores = accepted[-1]
        before_score = float(before_scores["total"])
        after_score = float(after_scores["total"])
        if after_score > before_score:
            winner = "B"
        elif before_score > after_score:
            winner = "A"
        else:
            winner = "tie"
        candidates.append({
            "run": run_name,
            "before": before_dir.name,
            "after": after_dir.name,
            "before_capture": before_capture,
            "after_capture": after_capture,
            "ai_winner": winner,
            "ai_basis": "B1-B5 total",
            "before_score": before_score,
            "after_score": after_score,
            "before_B1": float(before_scores["B1"]),
            "after_B1": float(after_scores["B1"]),
            "before_B3": float(before_scores["B3"]),
            "after_B3": float(after_scores["B3"]),
        })
    return candidates


def common_views(before_dir, after_dir, count=3):
    before = {p.name: p for p in before_dir.glob("view_*.png")}
    after = {p.name: p for p in after_dir.glob("view_*.png")}
    names = sorted(set(before) & set(after))
    if len(names) < count:
        return []
    # 視点が偏らないよう、先頭・中央・末尾を使う。
    indexes = [round(i * (len(names) - 1) / (count - 1)) for i in range(count)]
    return [(before[names[i]], after[names[i]]) for i in indexes]


def image_src(path, output_dir):
    relative = path.resolve().relative_to(output_dir.resolve())
    return quote(relative.as_posix(), safe="/._-")


def build_html(pairs, output_dir, heading, storage_namespace, answers_name,
               rubric_questions=False):
    cards = []
    for pair in pairs:
        pid = pair["pair_id"]
        left_key = "after" if pair["left_is"] == "after" else "before"
        right_key = "before" if left_key == "after" else "after"
        left = [image_src(x[left_key], output_dir) for x in pair["views"]]
        right = [image_src(x[right_key], output_dir) for x in pair["views"]]
        imgs_left = "".join(f'<img src="{html.escape(src)}" alt="{pid} 左">' for src in left)
        imgs_right = "".join(f'<img src="{html.escape(src)}" alt="{pid} 右">' for src in right)
        if rubric_questions:
            choices = f"""
  <div class="rubric-question">
    <h3>B1：物の大きさ・スケールがより自然なのは？</h3>
    <div class="choices question" data-pair="{pid}_B1" role="radiogroup" aria-label="{pid} B1の回答">
      <label><input type="radio" name="{pid}_B1" value="left"> 左</label>
      <label><input type="radio" name="{pid}_B1" value="right"> 右</label>
      <label><input type="radio" name="{pid}_B1" value="tie"> 同じくらい</label>
    </div>
  </div>
  <div class="rubric-question">
    <h3>B3：浮遊・貫通・向きの誤りが少ないのは？</h3>
    <div class="choices question" data-pair="{pid}_B3" role="radiogroup" aria-label="{pid} B3の回答">
      <label><input type="radio" name="{pid}_B3" value="left"> 左</label>
      <label><input type="radio" name="{pid}_B3" value="right"> 右</label>
      <label><input type="radio" name="{pid}_B3" value="tie"> 同じくらい</label>
    </div>
  </div>"""
        else:
            choices = f"""
  <div class="choices question" data-pair="{pid}" role="radiogroup" aria-label="{pid} の回答">
    <label><input type="radio" name="{pid}" value="left"> 左</label>
    <label><input type="radio" name="{pid}" value="right"> 右</label>
    <label><input type="radio" name="{pid}" value="tie"> どちらとも言えない</label>
  </div>"""
        cards.append(f"""
<section class="pair" data-pair="{pid}">
  <h2>{pid}</h2>
  <div class="sides">
    <div><h3>左</h3><div class="views">{imgs_left}</div></div>
    <div><h3>右</h3><div class="views">{imgs_right}</div></div>
  </div>
  {choices}
</section>""")

    page = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__HEADING__</title>
<style>
body{font-family:system-ui,sans-serif;margin:0;background:#f4f5f7;color:#202124}
main{max-width:1500px;margin:auto;padding:24px}.note{background:#fff7d6;padding:12px 16px;border-radius:8px}
.pair{background:white;margin:24px 0;padding:18px;border-radius:12px;box-shadow:0 2px 8px #0002}
.pair h2{margin:0 0 8px}.sides{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.sides h3{text-align:center;margin:4px}.views{display:grid;grid-template-columns:repeat(3,1fr);gap:5px}
.views img{display:block;width:100%;height:auto;background:#ddd}.choices{text-align:center;padding-top:16px}
.choices label{display:inline-block;margin:4px;padding:10px 16px;border:1px solid #aaa;border-radius:8px;cursor:pointer}
.choices label:has(input:checked){background:#dcecff;border-color:#3578c8}
.rubric-question{margin-top:18px;padding-top:8px;border-top:1px solid #ddd}.rubric-question h3{text-align:center}
#finish{font-size:1.1rem;padding:12px 22px}#result{width:100%;min-height:190px;margin-top:12px;font-family:monospace}
@media(max-width:800px){.sides{grid-template-columns:1fr}.views{grid-template-columns:1fr}}
</style></head><body><main>
<h1>__HEADING__</h1>
<p class="note">各組について、空間としてより良い方を直感で選んでください。左右のどちらが修正前かは伏せてあります。</p>
""" + "\n".join(cards) + """
<button id="finish" type="button">回答をまとめる</button>
<p id="status" aria-live="polite"></p><textarea id="result" readonly placeholder="すべて回答すると、ここにCSV行が表示されます"></textarea>
<script>
const cards = [...document.querySelectorAll('.question')];
const storageKey = 'blind-pair-answers:__STORAGE__';

function saveAnswers() {
  const saved = {};
  cards.forEach(c => {
    const picked = c.querySelector('input:checked');
    if (picked) saved[c.dataset.pair] = picked.value;
  });
  localStorage.setItem(storageKey, JSON.stringify(saved));
}

function restoreAnswers() {
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || '{}');
    cards.forEach(c => {
      const value = saved[c.dataset.pair];
      const input = value && c.querySelector(`input[value="${value}"]`);
      if (input) input.checked = true;
    });
  } catch (_) {}
}

cards.forEach(c => c.addEventListener('change', saveAnswers));
restoreAnswers();

document.getElementById('finish').addEventListener('click', () => {
  const missing = cards.filter(c => !c.querySelector('input:checked'));
  if (missing.length) {
    document.getElementById('status').textContent = `未回答が ${missing.length} 組あります。`;
    missing[0].scrollIntoView({behavior:'smooth', block:'center'});
    return;
  }
  const lines = cards.map(c => `${c.dataset.pair},${c.querySelector('input:checked').value}`);
  saveAnswers();
  const box = document.getElementById('result'); box.value = lines.join(String.fromCharCode(10)); box.select();
  document.getElementById('status').textContent = '下の行をコピーし、__ANSWER_NAME__ として保存してください。';
});
</script></main></body></html>"""
    return (page
            .replace("__HEADING__", html.escape(heading))
            .replace("__STORAGE__", html.escape(storage_namespace))
            .replace("__ANSWER_NAME__", html.escape(answers_name)))


def main():
    root_default = Path(__file__).resolve().parents[2]
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=Path, default=root_default / "runs")
    ap.add_argument("--output-dir", type=Path, default=root_default)
    ap.add_argument("--mode", choices=("adjacent", "endpoints", "rubric"),
                    default="adjacent")
    ap.add_argument("--count", type=int,
                    help="抽出数（省略時: adjacent=10、endpoints=全ラン）")
    ap.add_argument("--seed", type=int, default=20260809,
                    help="抽出と左右入れ替えの固定シード")
    args = ap.parse_args()

    if not args.runs.is_dir():
        print(f"runsディレクトリがありません: {args.runs}", file=sys.stderr)
        return 2
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.mode in ("endpoints", "rubric"):
        manifests = [
            root_default / "mvl-skeleton" / "figures" / "fig1_study_data.csv",
            root_default / "mvl-skeleton" / "figures" / "fig1_data.csv",
        ]
        try:
            candidates = find_endpoint_candidates(args.runs, manifests)
        except FileNotFoundError as exc:
            print(exc, file=sys.stderr)
            return 2
        if args.mode == "rubric":
            output_stem = "pairs_rubric"
            answers_name = "answers_rubric.csv"
            heading = "B1・B3採点基準のブラインド比較（端点7組）"
        else:
            output_stem = "pairs_endpoints"
            answers_name = "answers_endpoints.csv"
            heading = "開始前と終了後のブラインド比較（端点7組）"
        count = args.count if args.count is not None else len(candidates)
    else:
        candidates = find_adjacent_candidates(args.runs)
        output_stem = "pairs"
        answers_name = "answers.csv"
        heading = "修正前後のブラインド比較（隣接反復）"
        count = args.count if args.count is not None else 10
    usable = []
    for c in candidates:
        views = common_views(c["before_capture"], c["after_capture"])
        if views:
            c["views"] = [{"before": a, "after": b} for a, b in views]
            usable.append(c)
    print(f"比較候補: {len(usable)} 組")
    if len(usable) < count:
        print(f"画像の揃った候補が{count}組未満です。", file=sys.stderr)
        return 2

    rng = random.Random(args.seed)
    chosen = rng.sample(usable, count)
    pairs = []
    for i, c in enumerate(chosen, 1):
        c["pair_id"] = f"pair_{i:02d}"
        c["left_is"] = rng.choice(("before", "after"))
        pairs.append(c)

    key_path = args.output_dir / f"{output_stem}_key.csv"
    with key_path.open("w", newline="", encoding="utf-8-sig") as f:
        fields = ["pair_id", "left_is", "ai_winner", "run", "before", "after"]
        if args.mode == "rubric":
            fields += ["criterion", "display_pair", "before_score", "after_score"]
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            rows = []
            for pair in pairs:
                for criterion in ("B1", "B3"):
                    before_value = pair[f"before_{criterion}"]
                    after_value = pair[f"after_{criterion}"]
                    winner = ("B" if after_value > before_value else
                              "A" if before_value > after_value else "tie")
                    rows.append({
                        "pair_id": f"{pair['pair_id']}_{criterion}",
                        "display_pair": pair["pair_id"],
                        "criterion": criterion,
                        "left_is": pair["left_is"],
                        "ai_winner": winner,
                        "run": pair["run"],
                        "before": pair["before"],
                        "after": pair["after"],
                        "before_score": before_value,
                        "after_score": after_value,
                    })
            writer.writerows(rows)
        else:
            if args.mode == "endpoints":
                fields += ["ai_basis", "before_score", "after_score"]
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(pairs)

    html_path = args.output_dir / f"{output_stem}.html"
    namespace = f"{args.mode}:{args.seed}:" + ",".join(c["run"] for c in pairs)
    html_path.write_text(build_html(
        pairs, args.output_dir, heading, namespace, answers_name,
        rubric_questions=(args.mode == "rubric")), encoding="utf-8")
    print(f"生成: {html_path}")
    print(f"生成: {key_path}（判定終了まで開かないでください）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
