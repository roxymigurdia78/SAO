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
MAX_CYCLE_RETRIES = 3


@dataclass
class BestState:
    """違反数、縦横比誤差の辞書順で最良の評価済みシーンを保持する。"""
    scene: object = None
    iteration: object = None
    violation_count: object = None
    aspect_ratio_error_sum: object = None

    def consider(self, scene, iteration, violation_count,
                 aspect_ratio_error_sum=None):
        """辞書順で厳密に改善した場合だけdeep copyで更新する。"""
        if self.violation_count is not None:
            if violation_count > self.violation_count:
                return False
            if violation_count == self.violation_count:
                if aspect_ratio_error_sum is None:
                    return False
                if (self.aspect_ratio_error_sum is not None
                        and aspect_ratio_error_sum >= self.aspect_ratio_error_sum - 1e-12):
                    return False
        self.scene = copy.deepcopy(scene)
        self.iteration = iteration
        self.violation_count = violation_count
        self.aspect_ratio_error_sum = aspect_ratio_error_sum
        return True

    def summary(self):
        return {
            "selection_rule": (
                "lexicographic_minimum_machine_violations_then_aspect_ratio_error"),
            "iteration": self.iteration,
            "violation_count": self.violation_count,
            "aspect_ratio_error_sum": (
                round(self.aspect_ratio_error_sum, 6)
                if self.aspect_ratio_error_sum is not None else None),
        }


def has_budget_to_evaluate_repair(iteration, max_iters):
    """今作る修正シーンを次反復で評価できるか。"""
    return iteration + 1 < max_iters


def find_repeated_repairs(applied, seen):
    repeated = []
    for message in applied:
        if message in seen:
            repeated.append(message)
    return repeated


def scene_state_key(scene):
    """見た目と機械検査に影響するシーン状態を比較用に正規化する。"""
    objects = []
    for obj in sorted(scene.get("objects", []), key=lambda value: value.get("id", "")):
        dimensions = obj.get("target_dimensions") or {}
        objects.append({
            "id": obj.get("id"),
            "asset": obj.get("asset"),
            "position": [round(float(v), 4) for v in obj.get("position", [])],
            "rotation_y_deg": round(float(obj.get("rotation_y_deg", 0)), 4),
            "target_dimensions": {
                key: round(float(dimensions[key]), 4)
                for key in ("width", "height", "depth") if key in dimensions
            },
        })
    return json.dumps(objects, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def retry_after_cycle(prev_scene, cycle_scene, previous_records, violations,
                      worst_object, assets_dir, visual_defects,
                      seen_scene_states, asset_dimensions=None,
                      max_retries=MAX_CYCLE_RETRIES):
    """循環を作った修正を禁止し、直前の採用シーンから代替案を作る。"""
    initial_repeated_from = seen_scene_states.get(scene_state_key(cycle_scene))
    memory_scene = copy.deepcopy(cycle_scene)
    records_to_ban = list(previous_records or [])
    banned_repairs = []

    for attempt in range(1, max_retries + 1):
        banned_repairs.extend(
            repair.add_failed_repairs(memory_scene, records_to_ban))
        base_scene = repair.merge_repair_memory(
            copy.deepcopy(prev_scene), memory_scene)
        candidate, applied, records = repair.apply_repairs(
            base_scene, violations, worst_object, assets_dir,
            visual_defects=visual_defects,
            asset_dimensions=asset_dimensions,
            return_records=True)

        if not applied:
            return {
                "scene": base_scene,
                "applied": [],
                "records": [],
                "banned_repairs": banned_repairs,
                "fallback_reason": "scene_state_cycle",
                "repeated_from_iteration": initial_repeated_from,
                "retry_count": attempt,
                "stop_reason": "exhausted_after_cycle",
            }

        candidate_key = scene_state_key(candidate)
        if candidate_key not in seen_scene_states:
            return {
                "scene": candidate,
                "applied": applied,
                "records": records,
                "banned_repairs": banned_repairs,
                "fallback_reason": "scene_state_cycle",
                "repeated_from_iteration": initial_repeated_from,
                "retry_count": attempt,
                "stop_reason": None,
            }

        # 代替案自体が既知状態なら、その修正も禁止して再試行する。
        memory_scene = candidate
        records_to_ban = records

    return {
        "scene": repair.merge_repair_memory(
            copy.deepcopy(prev_scene), memory_scene),
        "applied": [],
        "records": [],
        "banned_repairs": banned_repairs,
        "fallback_reason": "scene_state_cycle",
        "repeated_from_iteration": initial_repeated_from,
        "retry_count": max_retries,
        "stop_reason": "cycle_retry_limit",
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
    asset_dimensions = repair.load_asset_dimensions(assets_dir)

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
    prev_violations = []
    prev_worst = None
    prev_visual_defects = []
    stall = 0
    prev_applied = []
    prev_applied_records = []
    seen_repairs = set()
    seen_scene_states = {}
    best = BestState()

    for i in range(args.max_iters):
        it_dir = run_dir / f"iter_{i:02d}"
        cap_dir = it_dir / "capture"
        it_dir.mkdir(parents=True, exist_ok=True)
        save_json(it_dir / "scene.json", scene)
        meta = {"iteration": i, "rolled_back": False, "applied_repairs": []}

        # A→B→Aのような逆向きの修正は、修正文の完全一致では検出できない。
        # 過去と同じ可視状態に戻ったら、原因のID+opを禁止して撮影前に代替案を作る。
        state_key = scene_state_key(scene)
        repeated_from = seen_scene_states.get(state_key)
        if repeated_from is not None:
            save_json(it_dir / "cycle_scene.json", scene)
            result = retry_after_cycle(
                prev_scene, scene, prev_applied_records, prev_violations,
                prev_worst, assets_dir, prev_visual_defects,
                seen_scene_states, asset_dimensions=asset_dimensions)
            meta["fallback_reason"] = result["fallback_reason"]
            meta["repeated_from_iteration"] = result["repeated_from_iteration"]
            meta["banned_repairs"] = result["banned_repairs"]
            meta["cycle_retry_count"] = result["retry_count"]
            meta["fallback_repairs"] = result["applied"]
            if result["stop_reason"]:
                meta["stop_reason"] = result["stop_reason"]
                scene = result["scene"]
                save_json(it_dir / "scene.json", scene)
                save_json(it_dir / "meta.json", meta)
                print(f"[iter {i}] 循環後の代替修正なし → {result['stop_reason']}")
                break

            scene = result["scene"]
            prev_applied = result["applied"]
            prev_applied_records = result["records"]
            state_key = scene_state_key(scene)
            save_json(it_dir / "scene.json", scene)
            print(f"[iter {i}] iter_{repeated_from:02d}と同じ状態を再検出"
                  f" → 禁止後に修正を再生成")
            for message in prev_applied:
                print(f"    * {message}")
        seen_scene_states[state_key] = i

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
        visual_defects = []
        if captures and not args.skip_vlm:
            import gpt_scoring
            scores = gpt_scoring.score_scene([str(p) for p in captures], scene)
            worst = scores.get("worst_object")
            visual_defects = scores.get("b3_defects", [])
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
                # この反復で適用した修正は悪化を招いたのでID+op単位で禁止する。
                meta["banned_repairs"] = repair.add_failed_repairs(
                    scene, prev_applied_records)
                # 巻き戻す(今の状態は捨てるが、記録だけ引き継ぐため退避)
                discarded = scene
                scene = repair.merge_repair_memory(
                    copy.deepcopy(prev_scene), discarded)
                save_json(it_dir / "meta.json", meta)
                continue

        # 採用: この反復を基準に更新
        prev_scene = copy.deepcopy(scene)
        prev_captures = captures or prev_captures
        prev_violation_count = len(violations)
        prev_violations = copy.deepcopy(violations)
        prev_worst = copy.deepcopy(worst)
        prev_visual_defects = copy.deepcopy(visual_defects)

        # 機械違反数を第一キー、縦横比誤差合計を第二キーにする。
        # 両方が同じ場合だけ先着を残す。VLMスコアは選定に使わない。
        aspect_error_sum = repair.total_aspect_ratio_error(
            scene, asset_dimensions)
        meta["aspect_ratio_error_sum"] = aspect_error_sum
        meta["is_best"] = best.consider(
            scene, i, len(violations), aspect_error_sum)
        meta["best_violation_count"] = best.violation_count
        meta["best_aspect_ratio_error_sum"] = best.aspect_ratio_error_sum
        if meta["is_best"]:
            save_json(run_dir / "best_scene.json", best.scene)
            save_json(run_dir / "best_summary.json", best.summary())
            aspect_text = (f" / 縦横比誤差 {aspect_error_sum:.3f}"
                           if aspect_error_sum is not None else "")
            print(f"[iter {i}] ベスト更新: 機械違反 "
                  f"{best.violation_count} 件{aspect_text}")

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

        # 最終反復で修正を作っでも次のUnity評価ができない。
        # 未評価シーンをログや履歴に残さず、評価済みの現在状態で停止する。
        if not has_budget_to_evaluate_repair(i, args.max_iters):
            meta["stop_reason"] = "iteration_limit_before_repair"
            save_json(it_dir / "meta.json", meta)
            print(f"[iter {i}] 次の評価予算なし → 修正を作らず停止")
            break

        # --- 5) 修正 ---
        new_scene, applied, applied_records = repair.apply_repairs(
            scene, violations, worst, assets_dir,
            visual_defects=visual_defects,
            asset_dimensions=asset_dimensions,
            return_records=True)
        repeated = find_repeated_repairs(applied, seen_repairs)
        meta["applied_repairs"] = applied
        meta["repeated_repairs"] = repeated
        if repeated:
            meta["proposed_repairs"] = applied
            # 修正文の重複だけでは停止せず、次反復のシーン循環判定に委ねる。

        seen_repairs.update(applied)
        prev_applied = applied
        prev_applied_records = applied_records
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
              f"機械違反 {best.violation_count} 件 / "
              f"縦横比誤差 {best.aspect_ratio_error_sum}")
    else:
        print("[MVL] 警告: 評価済みシーンなし。入力シーンを最終出力に使用")
    print(f"[MVL] 完了。最終シーン: {run_dir / 'final_scene.json'}")


if __name__ == "__main__":
    main()
