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

出力: `runs/<scene_id>_<日時>/`
- `iter_XX/scene.json` … 各反復のシーン(=ロールバック可能な履歴)
- `iter_XX/violations.json` / `scores.json` / `meta.json` / `capture/*.png`
- `score_trajectory.png` … **卒論 図1**
- `final_scene.json`

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

## 設計メモ(なぜこうなっているか)

- **スケールはtarget_dimensions基準で強制**: TRELLISのGLB出力スケールは信用せず、
  SceneBuilderが実測サイズから一様スケールで合わせる(サンプルGLB実測: 0.87×1.00×0.87m は
  たまたまメートルだったが保証がない)
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
