# unity_bridge.py — Unityバッチモード呼び出し(構築→ベイク→8視点撮影)
# Unityエディタのパスとプロジェクトパスは config.json か引数で指定する。
import json
import subprocess
import time
from pathlib import Path

DEFAULT_TIMEOUT = 30 * 60  # ベイク込みで30分上限


def build_command(unity_exe, project_path, scene_json, out_dir, log_file,
                  fast_iteration=False, detail_captures=False):
    cmd = [
        str(unity_exe),
        "-batchmode",
        "-projectPath", str(project_path),
        "-executeMethod", "MVL.BatchEntry.Run",
        "-sceneJson", str(Path(scene_json).resolve()),
        "-outDir", str(Path(out_dir).resolve()),
        "-logFile", str(log_file),
        "-quit",
    ]
    if fast_iteration:
        cmd.append("-fastIteration")
    if detail_captures:
        cmd.append("-detailCaptures")
    return cmd


def run_unity_build(unity_exe, project_path, scene_json, out_dir, log_file=None,
                    timeout=DEFAULT_TIMEOUT, fast_iteration=False,
                    detail_captures=False):
    """Unityをバッチ起動してシーン構築+撮影。成功時は report.json の dict を返す。

    注意: 同じプロジェクトを開いているUnityエディタがあると起動に失敗する(ロック)。
    実行前にエディタを閉じておくこと。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "report.json"
    if report_path.exists():
        report_path.unlink()  # 前回の残骸を消す(古いレポート誤読防止)
    log_file = log_file or str(out_dir / "unity.log")

    cmd = build_command(unity_exe, project_path, scene_json, out_dir,
                        log_file, fast_iteration=fast_iteration,
                        detail_captures=detail_captures)
    t0 = time.time()
    proc = subprocess.run(cmd, timeout=timeout)
    elapsed = time.time() - t0

    if not report_path.exists():
        raise RuntimeError(
            f"Unityがreport.jsonを出力しなかった(exit={proc.returncode}, {elapsed:.0f}秒)。"
            f"ログを確認: {log_file}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("error"):
        raise RuntimeError(f"Unity側エラー: {report['error']}(ログ: {log_file})")
    report["_elapsed_seconds"] = elapsed
    return report


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Unityバッチ構築の単体実行")
    ap.add_argument("--unity", required=True, help=r"例: C:\Program Files\Unity\Hub\Editor\6000.x\Editor\Unity.exe")
    ap.add_argument("--project", required=True)
    ap.add_argument("--scene", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--fast-unity", action="store_true",
                    help="配置確認用: メッシュ加工・UV2・ライトマップベイクを省略")
    ap.add_argument("--detail-captures", action="store_true",
                    help="全オブジェクトを対象に3方向の詳細画像を追加撮影")
    a = ap.parse_args()
    r = run_unity_build(a.unity, a.project, a.scene, a.out,
                        fast_iteration=a.fast_unity,
                        detail_captures=a.detail_captures)
    print(json.dumps(r, ensure_ascii=False, indent=2))
