# orchestrator.py — 最小ループ(MVL)ランナー
# 生成(配置)→評価(機械検査+VLM)→修正 を最大10反復し、全ログとスコア推移グラフを出力する。
#
# 使い方(フル実行):
#   python orchestrator.py --scene ../scene/scene_example.json ^
#       --unity "C:\Program Files\Unity\Hub\Editor\6000.0.xx\Editor\Unity.exe" ^
#       --project "C:\path\to\UnityProject"
#
# ドライラン(Unity・GPT API無しでループ配線だけ検証):
#   python orchestrator.py --scene ../scene/scene_example.json --dry-run
#
# 停止条件: 機械検査違反ゼロ かつ VLMスコアの改善が2反復連続で+0.1未満 / または10反復
import argparse
import copy
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import machine_checks as mc
import repair

MAX_ITERS = 10
CONVERGE_EPS = 0.1
CONVERGE_PATIENCE = 2


@dataclass
class BestState:
    """機械違反数が最少の、評価・採用済みシーンを保持する。"""
    scene: object = None
    iteration: object = None
    violation_count: object = None

    def consider(self, scene, iteration, violation_count):
        """厳密に改善した場合だけdeep copyで更新する。"""
        if self.violation_count is not None and violation_count >= self.violation_count:
            return False
        self.scene = copy.deepcopy(scene)
        self.iteration = iteration
        self.violation_count = violation_count
        return True

    def summary(self):
        return {
            "selection_rule": "minimum_machine_violation_count",
            "iteration": self.iteration,
            "violation_count": self.violation_count,
        }


def save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="生成→評価→修正の自律ループ")
    ap.add_argument("--scene", required=True, help="初期シーンJSON")
    ap.add_argument("--unity", help="Unity.exe のパス")
    ap.add_argument("--project", help="Unityプロジェクトのパス")
    ap.add_argument("--max-iters", type=int, default=MAX_ITERS)
    ap.add_argument("--dry-run", action="store_true", help="Unity/GPT無しで配線検証(公称AABBのみ)")
    ap.add_argument("--skip-vlm", action="store_true", help="GPT採点を飛ばす(機械検査のみで回す)")
    ap.add_argument("--runs-dir", default="runs")
    args = ap.parse_args()

    if not args.dry_run and (not args.unity or not args.project):
        ap.error("フル実行には --unity と --project が必要(配線検証だけなら --dry-run)")

    scene_path = Path(args.scene)
    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    # assets_dirを絶対パス化(シーンJSONはruns/にコピーされるため、元の場所基準で解決)
    scene["assets_dir"] = str((scene_path.parent / scene.get("assets_dir", "assets")).resolve())
    assets_dir = scene_path.parent / scene.get("assets_dir", "assets")

    # 接地/天面オフセットの実測(未計測のGLBだけ。表が無いと従来通りAABB基準になる)
    try:
        import contact_offset
        contact_offset.measure_dir(scene["assets_dir"])
    except Exception as e:
        print(f"[MVL] 接地オフセットの実測に失敗(AABB基準で続行): {e}")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path(args.runs_dir) / f"{scene.get('scene_id', 'scene')}_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"[MVL] 実行ログ: {run_dir}")

    prev_scene = None       # 直前の採用シーン(巻き戻し用)
    prev_captures = None    # 直前の採用シーンの画像(ペア比較用)
    prev_mean = None
    prev_violation_count = None
    stall = 0
    prev_applied = []
    best = BestState()

    for i in range(args.max_iters):
        it_dir = run_dir / f"iter_{i:02d}"
        cap_dir = it_dir / "capture"
        it_dir.mkdir(parents=True, exist_ok=True)
        save_json(it_dir / "scene.json", scene)
        meta = {"iteration": i, "rolled_back": False, "applied_repairs": []}

        # --- 1) 構築+撮影(Unity) ---
        report = None
        captures = []
        if not args.dry_run:
            import unity_bridge
            report = unity_bridge.run_unity_build(args.unity, args.project,
                                                 it_dir / "scene.json", cap_dir)
            captures = sorted(cap_dir.glob("view_*.png"))
            print(f"[iter {i}] 撮影 {len(captures)}枚 / ベイク {report.get('bake_seconds', 0):.0f}秒")

        # --- 2a) 機械検査 ---
        violations = mc.run_all(scene, report)
        save_json(it_dir / "violations.json", violations)
        print(f"[iter {i}] 機械検査: 違反 {len(violations)} 件")
        for v in violations:
            print(f"    - {v['type']}: {v.get('detail', '')}")

        # --- 2b) VLM採点 ---
        scores = None
        worst = None
        if captures and not args.skip_vlm:
            import gpt_scoring
            scores = gpt_scoring.score_scene([str(p) for p in captures], scene)
            worst = scores.get("worst_object")
            save_json(it_dir / "scores.json", scores)
            print(f"[iter {i}] VLM: 平均 {scores['mean']:.2f} " +
                  " ".join(f"{k}={scores.get(k)}" for k in ("B1", "B2", "B3", "B4", "B5")))

        # --- 3) 採否判定(前反復と比較。悪化なら巻き戻し) ---
        if prev_scene is not None:
            worsened = len(violations) > prev_violation_count
            if not worsened and len(violations) == prev_violation_count and captures and prev_captures and not args.skip_vlm:
                import gpt_scoring
                winner = gpt_scoring.pairwise([str(p) for p in prev_captures],
                                              [str(p) for p in captures], scene)
                worsened = (winner == "A")  # A=前バージョンの方が良い
                meta["pairwise_winner"] = winner
            if worsened:
                print(f"[iter {i}] 悪化を検出 → 巻き戻し")
                meta["rolled_back"] = True
                # この反復で適用した修正は悪化を招いたので、以後試さない
                failed = scene.setdefault("_failed_repairs", [])
                for a in (prev_applied or []):
                    if a not in failed:
                        failed.append(a)
                # 巻き戻す(今の状態は捨てるが、記録だけ引き継ぐため退避)
                discarded = scene
                scene = copy.deepcopy(prev_scene)
                scene["_failed_repairs"] = list(discarded.get("_failed_repairs", []))
                for o_new in scene["objects"]:
                    o_old = next((o for o in discarded["objects"] if o["id"] == o_new["id"]), None)
                    if o_old and "_tried_variants" in o_old:
                        o_new["_tried_variants"] = list(o_old["_tried_variants"])
                save_json(it_dir / "meta.json", meta)
                continue

        # 採用: この反復を基準に更新
        prev_scene = copy.deepcopy(scene)
        prev_captures = captures or prev_captures
        prev_violation_count = len(violations)

        # 機械違反数が過去最少なら、評価済みの現在シーンをラチェット保持する。
        # 同数では更新せず、先に到達した安定状態を残す。
        meta["is_best"] = best.consider(scene, i, len(violations))
        meta["best_violation_count"] = best.violation_count
        if meta["is_best"]:
            save_json(run_dir / "best_scene.json", best.scene)
            save_json(run_dir / "best_summary.json", best.summary())
            print(f"[iter {i}] ベスト更新: 機械違反 {best.violation_count} 件")

        # --- 4) 停止判定 ---
        mean = scores["mean"] if scores else None
        if len(violations) == 0:
            if mean is None:
                print(f"[iter {i}] 違反ゼロ(VLM無し)→ 停止")
                save_json(it_dir / "meta.json", meta)
                break
            if prev_mean is not None and mean - prev_mean < CONVERGE_EPS:
                stall += 1
            else:
                stall = 0
            if stall >= CONVERGE_PATIENCE:
                print(f"[iter {i}] 違反ゼロ・スコア収束 → 停止")
                save_json(it_dir / "meta.json", meta)
                break
        prev_mean = mean if mean is not None else prev_mean

        # --- 5) 修正 ---
        new_scene, applied = repair.apply_repairs(scene, violations, worst, assets_dir)
        meta["applied_repairs"] = applied
        prev_applied = applied
        save_json(it_dir / "meta.json", meta)
        if not applied:
            print(f"[iter {i}] 適用可能な修正なし → 停止")
            break
        print(f"[iter {i}] 修正 {len(applied)} 件:")
        for a in applied:
            print(f"    * {a}")
        new_scene.setdefault("history", []).append(
            {"iteration": i, "repairs": applied,
             "violations": len(violations), "vlm_mean": mean})
        scene = new_scene

    # --- 6) スコア推移グラフ(卒論 図1) ---
    try:
        import plotting
        out = plotting.plot_run(run_dir)
        print(f"[MVL] グラフ出力: {out}")
    except Exception as e:
        print(f"[MVL] グラフ生成失敗(後で plotting.py 単体で再実行可): {e}")

    # 最後に適用しただけの未評価シーンではなく、評価・採用済みの最少違反状態を返す。
    final_scene = best.scene if best.scene is not None else scene
    save_json(run_dir / "final_scene.json", final_scene)
    if best.scene is not None:
        save_json(run_dir / "best_summary.json", best.summary())
        print(f"[MVL] ベスト採用: iter_{best.iteration:02d} / "
              f"機械違反 {best.violation_count} 件")
    else:
        print("[MVL] 警告: 評価済みシーンなし。入力シーンを最終出力に使用")
    print(f"[MVL] 完了。最終シーン: {run_dir / 'final_scene.json'}")


if __name__ == "__main__":
    main()
