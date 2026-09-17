# MVL骨格コード一式(最小ループ: 生成→評価→修正)

8月の目標「10反復のスコア推移グラフ(卒論 図1)」を出すための骨格。
構成はALL-Unity版(v5.1): Blenderはパイプラインに入っていない。

```
mvl-skeleton/
├── scene/
│   ├── scene_schema.md       … シーンJSON仕様(まず読む)
│   ├── scene_example.json    … 勉強部屋のサンプルシーン(6オブジェクト)
│   └── scene_broken_test.json … わざと壊したテスト用シーン(検査の動作確認用)
├── unity/Editor/
│   ├── MVL.cs                … 共通定義(JSONミラー)
│   └── SceneBuilder.cs       … 構築→デシメーション→ベイク→8視点撮影
└── python/
    ├── orchestrator.py       … 反復ランナー(これを実行する)
    ├── machine_checks.py     … 機械検査(貫通/浮遊/範囲外/スケール/動線/欠落)
    ├── gpt_scoring.py        … VLM採点(B1〜B5)+ペア比較(順序入替)
    ├── repair.py             … 修正オペレータ(接地/押出し/再スケール/差替え/追加)
    ├── unity_bridge.py       … Unityバッチ呼び出し
    ├── plotting.py           … スコア推移グラフ(図1)
    └── prompts/              … 採点・比較プロンプト
```

## 導入手順(Windows)

### 1. Python側(5分)

```
cd python
pip install -r requirements.txt
set OPENAI_API_KEY=sk-...
```

動作確認(Unity・API不要のドライラン):

```
python orchestrator.py --scene ..\scene\scene_example.json --dry-run
```

→ 機械検査が動き、runs/ にログが出ればOK。壊れたシーンで修正ループを見るには:

```
python orchestrator.py --scene ..\scene\scene_broken_test.json --dry-run
```

→ 浮遊/貫通/範囲外/スケール逸脱が1反復で修正され、違反6→1に減るのが正常
(残る1件「monitor欠落」はassetsにGLBが無いため。実GLBを置けば自動追加される)。

### 2. Unity側(15分)

C5実験のプロジェクトを流用。Package Manager で:

1. **glTFast**: Add package by name → `com.unity.cloud.gltfast`
2. **UnityMeshSimplifier**: Add package from git URL →
   `https://github.com/Whinarn/UnityMeshSimplifier.git`
3. `unity/Editor/` の2ファイルを `Assets/Editor/` にコピー
4. コンパイルエラーが無いことを確認 → メニューに `MVL > Build From scene_example.json` が出る

### 3. アセット配置

スパコンで生成した GLB を `scene/assets/` に置く。ファイル名は
scene_example.json の `asset` / `asset_variants` と一致させる
(desk_v1.glb, desk_v2.glb, … rug_v3.glb の24個)。

### 4. 手動1回テスト(8/6マイルストーン)

Unityエディタで `MVL > Build From scene_example.json` を実行し、
capture/ に view_00〜07.png と report.json が出ることを確認。

### 5. フルループ(8/9〜)

**Unityエディタを閉じてから**(プロジェクトロックのため):

```
python orchestrator.py --scene ..\scene\scene_example.json ^
  --unity "C:\Program Files\Unity\Hub\Editor\<ver>\Editor\Unity.exe" ^
  --project "C:\path\to\UnityProject"
```

出力: `mvl-skeleton/runs/<scene_id>_<日時>/` (`--runs-dir` で変更可能)
- `iter_XX/scene.json` … 各反復のシーン(=ロールバック可能な履歴)
- `iter_XX/violations.json` / `scores.json` / `meta.json` / `capture/*.png`
- `score_trajectory.png` … **卒論 図1**
- `final_scene.json`

既存の `sao/runs/` は再現用に移動せず残し、今後の既定出力だけを `mvl-skeleton/runs/` に統一する。

APIを節約したい間は `--skip-vlm`(機械検査だけで回す)。

配置・大きさを素早く調整する間は `--fast-unity` を付ける:

```
python orchestrator.py --scene ..\scene\scene_study_seed3.json ^
  --unity "C:\Program Files\Unity\Hub\Editor\6000.5.6f1\Editor\Unity.exe" ^
  --project ..\..\XRunity --fast-unity
```

高速モードはメッシュ削減、ライトマップUV生成、ライトマップベイクを省略し、
元のGLBとリアルタイム照明で8視点を撮影する。AABBを使う配置・接地・貫通・
動線確認向け。照明と最終画質は通常モードと異なるため、成果用の最終ランでは
`--fast-unity` を外す。

撮影原画は1920×1080で保存する。VLM送信画像はPython側の
`VLM_MAX_IMAGE_PX` (既定1024) で独立に縮小されるため、原画解像度を変えても
採点APIへの画像サイズを別に調整できる。

小物の向き・見た目上の接地・局所的な使いやすさまで確認する場合は
`--detail-vlm` を付ける。機械違反がゼロになった候補について、全オブジェクトを
3方向から拡大撮影し、1対象ずつ別のVLMリクエストで監査する。

```
python orchestrator.py --scene ..\scene\scene_study_seed1.json ^
  --unity "C:\Program Files\Unity\Hub\Editor\6000.5.6f1\Editor\Unity.exe" ^
  --project ..\..\XRunity --detail-vlm
```

出力は `iter_XX/capture/detail/<object_id>/view_00〜02.png` と
`iter_XX/detail_audit.json`。詳細監査は全景8枚のB1〜B5採点とは分離される。
判定は `pass` / `fail` / `uncertain` として記録する。既定では監査記録だけを
残し、自動修復は行わない。詳細VLMを修復にも使う実験では
`--detail-vlm-repair` を明示し、その場合だけ信頼度0.8以上の修復可能な指摘を渡す。
API呼び出し数が対象数だけ増えるため、通常は最終確認時だけ有効にする。

監査専用を既定にした理由は、2026-08-28の機械違反ゼロの対照シーンで、
詳細VLMが浮遊・貫通を複数誤検出したため。非決定的な指摘をそのまま修復へ
渡すと、正しい幾何状態を壊す可能性がある。fail数はベスト保持の最下位
タイブレークには使うが、決定的な機械違反数・縦横比誤差より優先しない。

欠陥を仕込んだ初期シーンと機械検査結果を突き合わせ、詳細VLMの検出率を
測る場合だけ `--detail-vlm-every-iteration` を使う。この評価用オプションは
機械違反が残る反復にも監査を行うため、通常の実ランよりAPI呼び出しが増える。
ログと `meta.json` には詳細撮影の対象数・枚数・秒数、および詳細VLMの
リクエスト数・合計秒数を記録する。

複数反復の検出率・誤検出率は次のように集計する。浮遊・貫通・向きは
`物体×項目` を1判定として2×2表を作り、scaleは問いが異なるため別枠にする。
貫通の正解ラベルは実測AABBの重なりで定義する。画像のVLM監査でAABBの
偽陽性候補が見つかっても、同じVLMを評価する分母は変更しない。候補は
近似の限界として併記し、正解ラベルを変更するにはメッシュ衝突判定または
独立した人手アノテーションを用いる。

```
python detail_vlm_eval.py ^
  ..\runs\study_room_seed1_<日時>\iter_00 ^
  ..\runs\study_room_seed2_<日時>\iter_00 ^
  ..\runs\study_room_seed3_<日時>\iter_00 ^
  --csv ..\runs\detail_vlm_eval.csv
```

### 向き検出率の専用評価

通常の3シードには `chair -> desk`、`monitor -> chair`、`laptop -> chair` を宣言する。
ただし、通常配置だけでは向き違反の正例が少ないため、向き検出率の主張には使わない。
次のスクリプトは既存アセットだけを使い、desk・chair・monitor・laptopへ
seedごとに90/135/180度の既知のずれを注入する。通常シーンは変更せず、
専用コピーに4件×3シード=12件の正解ラベルがあることを機械検査で確認してから実行する。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_orientation_detection_rate.ps1
```

出力CSVでは `orientation` のTOTAL（正例12件）だけを向きの評価結果として読む。
欠陥注入によって配置条件が変わるため、同じCSVの浮遊・貫通行は主結果に使わない。

正面方向の形状推定 `upper_mesh_asymmetry` は候補生成に限定し、単独では自動回転へ
使用しない。方向性アセットを追加・変更した場合は、次のコマンドで四面図VLMを
3回実行する。形状推定とVLM多数決が一致した場合だけ確定し、不一致または多数決不能は
`orientation_unverified` として修復を停止する。実画像で確認した個別校正は
`scene/front_offsets_overrides.json` に記録する。

```powershell
python .\front_offsets.py --assets-dir ..\scene\assets\0824 `
  --vlm-verify-directional --vlm-attempts 3
```

### 浮遊検出率の専用評価

通常シーンにもともと含まれる少数の浮遊だけで100%という結論を出さないため、
評価専用コピーの垂直位置をいったん支持面へ正規化し、chair・backpack・monitor・laptopへ
4件×3シード=12件の浮遊を注入する。床置きと机上の物体を含み、浮遊量は
0.05〜0.50mの範囲で変える。通常シーンと本番シーンは変更しない。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_floating_detection_rate.ps1
```

`floating_detection_eval.csv` は注入した12件を正例とする。Unity実測で追加の浮遊が
見つかった場合、その物体は偽陽性率の負例から除外し、件数を `extra_machine_positives` に残す。
最終リトライ後もVLM応答が不正だった件数は `invalid_after_retries` に記録する。

## 設計メモ(なぜこうなっているか)

- **スケールはtarget_dimensions基準で強制**: TRELLISのGLB出力スケールは信用せず、
  SceneBuilderが実測幅・高さ・奥行きから各軸を個別にスケールして合わせる(サンプルGLB実測: 0.87×1.00×0.87m は
  たまたまメートルだったが保証がない)。`aspect_ratio_error` は過去ランとの互換性のため
  キー名を維持するが、現在は元GLBを目標寸法へ合わせる際の形状歪み量として解釈する。
  既存の1.35倍基準を超える場合は、より形状比の近いバリアントへの差し替え候補になる
- **デシメーション**: 1オブジェクト約14万tri→1.5万triへ(Quest 2予算)。
  ライトマップUV(UV2)はデシメーション後に生成
- **太陽はMixed固定**: RealtimeのままだとベイクされずC4の照明劣化を繰り返す
- **機械検査は実測AABB優先**: Unityのreport.jsonがあれば実測、無ければ公称
  (--dry-run時)。「検査は成果物レンダラーに対して行う」の原則
- **採否判定**: 違反件数の増加 or ペア比較(順序入替で2回聞いて一致時のみ確定)で
  悪化とみなし巻き戻し。修正オペレータの暴走を防ぐ
- **バリアント差し替えは機械検査違反ゼロの時だけ**: 修正は1テーマずつ。
  何が効いたか分からなくなるのを防ぐ
- **8月は再生成なし**: 低品質→差し替えのみ(3バリアント使い切ったらログに残して9月へ)。
  停電中でもループが完結する設計

### スケール方式の比較実験

各軸スケール（既定）と旧一様スケールを、同じ3シード・1反復で比較する:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_scale_ablation.ps1
```

各条件で機械違反数とVLMのB1/B4/B5を記録し、`scale_ablation.csv` にまとめる。
同時に、3シード共通の通常寸法を持つseed1を基準として48バリアントの
`aspect_ratio_error` 分布を `aspect_ratio_distribution.csv` に出す。
実験用の旧方式だけを単独で使う場合は `orchestrator.py --uniform-scale` を指定する。

### 詳細VLMプロンプト改訂の1シード確認（2026-09-15）

支持関係の誤検出を抑えるv2・v3をseed1の同一画像で各1回比較したが、どちらも
貫通検出率が100%から0%へ低下した。v3は浮遊の誤検出率も20%から40%へ
悪化したため開発時の候補として不採用とし、実運用はv1へ戻した。VLMの試行間変動を
評価する反復測定ではないため、一般的な性能差の主張には使わない。各候補プロンプトと比較CSVは
再現用に保存し、同一seedへの追加調整は行わない。

## 既知の未実装(9月分)

- スパコンREST API経由の追加生成(JupyterHub APIトークン要確認)
- パノラマスカイボックス(L0)・部屋殻の材質生成(L1)— いまは単色テンプレ箱
- FLUX/SDXLによる2D拡散リテクスチャ
- Quest 2ビルド(いまはPC上の撮影のみ)

## 動かないときの切り分け

| 症状 | 見る場所 |
|---|---|
| Unityが起動しない/すぐ終わる | runs/…/capture/unity.log(ライセンス・ロック・コンパイルエラー) |
| report.jsonが無い | 同上。-executeMethodの綴り、Editorフォルダ配置を確認 |
| GLBが出ない/白い | glTFastパッケージ導入済みか。Assets/MVLImported/ にインポートされているか |
| ベイクが遅い | SceneBuilder.cs の lightmapResolution を 12→8 に下げる |
| VLMがJSONを返さない | gpt_scoring.py はリトライ3回。OPENAI_MODEL を変えて試す |
