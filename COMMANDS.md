# よく使うコマンド集

PowerShell 前提。断りがなければ `C:\Users\Astra\Desktop\sao` で実行する。
行末の ` は PowerShell の行継続。コピペするときは消さない。

```powershell
cd C:\Users\Astra\Desktop\sao
```

Unity と Unityプロジェクトのパスは毎回同じなので、一度だけ変数に入れておくと楽（PowerShellを閉じると消える）。

```powershell
$unity = "C:\Program Files\Unity\Hub\Editor\6000.5.6f1\Editor\Unity.exe"
$proj  = "C:\Users\Astra\Desktop\sao\XRunity"
```

---

## 1. フルループを回す（一番よく使う）

1シードを最大10反復。1反復あたりUnityが約250秒なので、5反復で25分前後。

```powershell
python mvl-skeleton\python\orchestrator.py `
  --scene mvl-skeleton\scene\scene_study_seed1.json `
  --unity $unity `
  --project $proj
```

seed2 / seed3 はファイル名を変えるだけ。3本連続で回すなら:

```powershell
foreach ($seed in 1..3) {
  python mvl-skeleton\python\orchestrator.py `
    --scene "mvl-skeleton\scene\scene_study_seed$seed.json" `
    --unity $unity --project $proj
  if ($LASTEXITCODE -ne 0) { break }
}
```

### orchestrator.py のフラグ

| フラグ | 何をするか | いつ使うか |
|---|---|---|
| `--max-iters N` | 反復上限（既定10） | 測定用に1反復だけ回すとき `--max-iters 1` |
| `--dry-run` | Unity・VLMを使わず配線確認だけ | コードを触った直後の動作確認 |
| `--skip-vlm` | VLM採点を飛ばす（機械検査のみ） | 幾何だけ見たいとき。API代を使わない |
| `--fast-unity` | メッシュ加工・UV2・ベイクを省略（約23秒/反復） | 配置だけ確認したいとき。**採点する測定には使わない** |
| `--detail-vlm` | 機械違反ゼロのときだけ詳細監査 | 最終確認 |
| `--detail-vlm-every-iteration` | 毎反復で詳細監査 | 検出率の測定用 |
| `--detail-vlm-repair` | 詳細VLMの指摘を修復に渡す | **既定OFF。誤検出20%で正しい状態を壊すので普段は使わない** |
| `--runs-dir PATH` | ログの出力先を変える | 既定は `mvl-skeleton\runs` |

---

## 2. 検出率の測定（貫通・浮遊・向き）

3シードを1反復ずつ回して集計まで一括。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File mvl-skeleton\python\run_detection_rate.ps1
```

**注意**: このスクリプトは `--detail-vlm-repair` と `--fast-unity` を付けない。
修復すると「何を検出できたか」が測れず、ベイクを飛ばすと影が変わって過去の誤検出率と条件が揃わない。

### 集計だけやり直す

```powershell
python mvl-skeleton\python\detail_vlm_eval.py `
  mvl-skeleton\runs\study_room_seed1_日時\iter_00 `
  mvl-skeleton\runs\study_room_seed2_日時\iter_00 `
  mvl-skeleton\runs\study_room_seed3_日時\iter_00 `
  --csv mvl-skeleton\runs\detail_vlm_eval_3seeds.csv
```

日時を手で打つのが面倒なら、最新のランを自動で拾う:

```powershell
$dirs = 1..3 | ForEach-Object {
  (Get-ChildItem "mvl-skeleton\runs" -Directory -Filter "study_room_seed$_*" |
    Sort-Object Name -Descending | Select-Object -First 1).FullName + "\iter_00"
}
$dirs
python mvl-skeleton\python\detail_vlm_eval.py $dirs --csv mvl-skeleton\runs\detail_vlm_eval_3seeds.csv
```

`$dirs` を一度表示しているのは、拾ったフォルダが合っているか目視するため。

見るところ:

```
[penetration] ... 検出率=
[penetration_pair] ... 検出率=
[floating] ... 検出率=
[orientation] ... 検出率=
```

**浮遊・貫通・向きの3項目だけで検出率を出す。** 大きさ・機能関係は正解ラベルの問いが違うので別枠。

### 向きの検出率（9/15に確定した 5/12 = 41.7% を取り直す）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File mvl-skeleton\python\run_orientation_detection_rate.ps1
```

欠陥入りシーンは `make_orientation_eval_scenes.py` が作る。出力は `runs\orientation_detection_日時\orientation_detection_eval.csv`。

### 浮遊の検出率（11/12 = 91.7%）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File mvl-skeleton\python\run_floating_detection_rate.ps1
```

シーン生成は `make_floating_eval_scenes.py`、集計は `floating_injection_eval.py`。出力は `runs\floating_detection_日時\floating_detection_eval.csv`。

### 貫通のペア単位だけ確認する

```powershell
python mvl-skeleton\python\run_penetration_pair_audit.py
```

### スケール方式の比較（一様 vs 各軸）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File mvl-skeleton\python\run_scale_ablation.ps1
```

集計は `scale_ablation_eval.py`。出力は `runs\scale_ablation_日時\`。

### 採点表プロンプトの改訂を試す

```powershell
python mvl-skeleton\python\run_prompt_revision_eval.py
```

**9/15にv2・v3を試して両方棄却、v1維持。** 詳細VLM監査のプロンプトは凍結済みなので、いま回すのは記録の再現目的だけ。

---

## 3. 機械検査だけ3シード一括（VLMを使わない）

API代がかからない。幾何だけ確認したいときに一番速い選択。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File mvl-skeleton\python\run_geometry_validation.ps1
```

---

## 4. 図1を作り直す

```powershell
python mvl-skeleton\python\make_fig1.py `
  mvl-skeleton\runs\study_room_seed1_20260828_081701 `
  mvl-skeleton\runs\study_room_seed2_20260828_083531 `
  mvl-skeleton\runs\study_room_seed3_20260828_090641 `
  --out mvl-skeleton\figures\fig1_study.png `
  --axes mvl-skeleton\figures\fig1_study_axes.png `
  --csv mvl-skeleton\figures\fig1_study_data.csv
```

**この3本は8月版（一様スケール時代）のラン。** 現行条件とは別物なので、図1として使うならその旨を論文に書く。

---

## 5. GLBの正面方向を推定する（front_offset_deg）

`assets_inventory.json` を**上書きする**ので、先に `git commit` しておく。

```powershell
cd C:\Users\Astra\Desktop\sao\mvl-skeleton\python
python front_offsets.py --assets-dir ..\scene\assets\0824
cd C:\Users\Astra\Desktop\sao
```

結果は `scene\assets\0824\front_offsets_report.json`。
`unresolved` に残ったアセットは `scene\front_offsets_overrides.json` の `assets` に手で角度を書いて、もう一度実行する（Unityの+Zが0度）。

---

## 6. テストを回す

```powershell
cd C:\Users\Astra\Desktop\sao\mvl-skeleton\python
python -m unittest discover -p "test_*.py" -v
cd C:\Users\Astra\Desktop\sao
```

1ファイルだけ:

```powershell
python -m unittest -v mvl-skeleton\python\test_detail_vlm_eval.py
```

コードを触ったら、**回す前にまずこれ**。

---

## 7. 結果の見どころ

ランのフォルダ `mvl-skeleton\runs\<ラン名>\` の中身。

| ファイル | 中身 |
|---|---|
| `best_summary.json` | ベストに選ばれた反復、違反数、縦横比誤差 |
| `final_scene.json` | 最終出力のシーン。Unityで開くならこれ |
| `score_trajectory.png` | スコアと違反数の推移グラフ |
| `iter_NN\violations.json` | その反復の機械検査違反（検出率の正解ラベル） |
| `iter_NN\scores.json` | B1〜B5の採点 |
| `iter_NN\detail_audit.json` | 詳細VLM監査の全判定 |
| `iter_NN\meta.json` | 適用した修正、撮影枚数、所要秒数 |
| `iter_NN\capture\` | 撮影画像（全景8枚＋詳細48枚）と `unity.log` |

Unityが動かないときは `iter_NN\capture\unity.log` を見る。

---

## 8. git

```powershell
git add -A
git commit -m "何を変えたか1行"
git push
```

**毎日コミットする。** 2台運用しているので、これが生命線。

---

## 9. 環境変数（VLMの採点器を切り替える）

コード変更なしで切り替わる。PowerShellを閉じても残したいなら `setx`。

```powershell
$env:OPENAI_BASE_URL = "..."
$env:OPENAI_MODEL    = "qwen3.5:35b"
$env:OPENAI_API_KEY  = "..."
```

**APIキーをコードに直接書かない。**

---

## 使わないもの・気をつけるもの

- `--detail-vlm-repair` — 既定OFFのまま。測定を壊す
- `--fast-unity` — 採点する測定には使わない。影が変わる
- `prompts\` の中身 — 詳細VLM監査ぶんは2026-09-15に凍結。触ると検出率3項目が測り直しになる
- `scene_study_seed1〜3.json` — 本番シーン確定後は触らない
