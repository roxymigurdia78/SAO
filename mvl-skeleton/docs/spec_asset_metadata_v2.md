# 実装指示: 任意のGLBに対応するアセット配置メタデータ推定(contact_offset v2)

このファイルはコーディングAIにそのまま渡す前提の指示書です。
以下の「タスク」を、指定の受け入れ基準を満たすまで実装してください。
不明点があれば実装前に質問し、勝手な仕様変更はしないこと。

---

## 0. 前提となるシステム

Unity + Python の自律ループ(生成→評価→修正)で3D室内シーンを組み立てるパイプライン。

- `python/orchestrator.py` — ループ本体
- `python/machine_checks.py` — 決定的な機械検査(欠落/貫通/浮遊/範囲外/スケール/動線)
- `python/repair.py` — 違反に対する修正オペレータ
- `python/contact_offset.py` — **今回の拡張対象**(v1が既にある)
- `Assets/Editor/SceneBuilder.cs` — Unity側。GLBを読み、`target_dimensions.height` に合わせて一様スケールし、
  **AABBの最下端(bounds.min.y)を `position[1]` に合わせて配置する**

シーンJSONの各オブジェクトは `asset`(GLBファイル名)、`position`、`rotation_y_deg`、
`target_dimensions`、`rests_on`(親オブジェクトID)などを持つ。

## 1. v1が解いた問題と、その限界

パイプラインは長らく「AABB最下端 = 接地面」「AABB最上端 = 天面」を暗黙に仮定していた。
これは多くのアセットで成り立たず、機械検査を全部パスした状態でも人が見ると破綻する。

実例(2026-08-11に実測):

| アセット | 症状 | 実測オフセット |
|---|---|---|
| `lantern_v1.glb` | 下向きの装飾突起がAABB最下端。机に載せると本体が浮く | contact 0.093 |
| `table_v2.glb` | 背板が天板より高い。AABB上端は天板ではない。ここに物を載せると0.38m浮く | support 0.524 |

v1(`python/contact_offset.py`)はこれを、アセットごとの2つの比率で補正する:

- `contact_offset` = (実質的な接地面Y − AABB最小Y) / AABB高さ
- `support_offset` = (AABB最大Y − 実質的な天面Y) / AABB高さ

比率なのでリスケール後もそのまま使える。`scene/assets/contact_offsets.json` に保存し、
`machine_checks.contact_y()` / `support_y()` が参照する。シーンJSON側の同名キーで上書き可能。

**v1が成立しているのは、手持ちの15個のGLBがすべて「TRELLIS由来の高密度・Y-up・非圧縮・単一オブジェクト」だから。**
今後はもっと多様なGLB(手作りの低ポリ、Draco圧縮、Z-up、吊り下げ物、複数部品)が入ってくる。
v1の前提が崩れる箇所を潰し、**未知アセットでも「壊れない」ことを最優先**に一般化するのが今回のタスク。

## 2. 最優先の設計原則

> **誤ったオフセットを出すことは、オフセットを出さないことより悪い。**

`contact_offset` を過大に見積もると、オブジェクトが床や机にめり込む。これは浮遊より目立つ破綻。
したがって:

1. 推定に自信が持てない場合は **0 を返し、`needs_review: true` を立てる**(現状維持=v0の挙動に安全に退避)
2. 推定値には必ず **confidence(0.0〜1.0)** を付ける
3. 人間が上書きできる経路を必ず残す(後述の `contact_overrides.json`)
4. 「なぜその値になったか」を人間が1分で検証できる図を出す(後述の視覚レポート)

## 3. 必須要件

### R1. 頂点ではなく面積で標本化する(最重要)

v1は生の頂点座標を直接使っている。TRELLIS出力は頂点が密で均一なので偶然うまくいっているだけ。
低ポリのGLBでは、広い平面が4頂点しか持たないため断面プロファイルが完全に壊れる。

**三角形の面積に比例した重みで表面上の点をサンプリングする**方式に置き換えること。
(各三角形について面積を計算し、面積に比例した個数の点を重心座標のランダムサンプリングで生成する。
合計 20万点程度を上限とし、それを超える場合は面積重み付きで間引く)

### R2. 対応するGLB/glTFの範囲を明示し、非対応は安全に落とす

- 対応必須: `.glb`(非圧縮)、`.gltf` + 外部 `.bin`、sparse accessor、インターリーブ配置、
  ノード階層の変換行列(TRS/matrix)、複数メッシュ・複数プリミティブ
- 対応任意: `KHR_draco_mesh_compression`、`EXT_meshopt_compression`
  → `trimesh` などが import できる環境ならそれで読み、無ければ **例外にせず**
  `method: "unsupported"`, `contact_offset: 0`, `needs_review: true` を記録して次のアセットへ進む
- 1つのアセットの失敗が全体の計測を止めてはならない

### R3. 上下軸の検証

glTFはY-upだが、Z-upで出力される生成物が混ざる。Y-upでないアセットに対して垂直方向の解析をすると
結果は完全な嘘になる。

- 各軸について「その軸を上とみなしたときの断面プロファイルの平坦性」を評価し、
  Y軸が最も「立っている」向きでないアセットには `axis_warning: true` を立てる
- 自動で回転を補正してはいけない(Unity側の配置と食い違うため)。警告と `needs_review` に留める

### R4. 支持面は「1枚」ではなく「候補リスト」

本棚は棚板ごとに載置面があり、机は天板1枚、椅子は座面1枚。v1は「最も高い大面積の断面」1つしか返さない。
現に `shelf_v1.glb` は support 0.000(= AABB上端)になっていて、棚板の存在を捉えていない。

以下を返すこと:

```
support_planes: [
  {"y_frac": 0.98, "area_frac": 0.62, "clearance_frac": 0.02, "confidence": 0.8},
  {"y_frac": 0.71, "area_frac": 0.55, "clearance_frac": 0.24, "confidence": 0.7},
  ...
]
```

- `y_frac`: AABB下端からの高さ比
- `area_frac`: その面の水平投影面積 / フットプリント面積
- `clearance_frac`: その面の直上にある空きの高さ比(物を置ける余裕。棚板の判定に必須)
- 既存の `support_offset` は「`clearance_frac` が十分ある面のうち最も高いもの」として後方互換で残す

### R5. 接地タイプの分類

すべてのアセットが床に置かれるわけではない(シャンデリア、壁掛け、吊りランタン)。
底面に接地しうる構造が無いアセットに対して接地面を捏造してはいけない。

`ground_type` を推定して記録する: `"floor"`(自立)/ `"tabletop"`(小物)/ `"hanging"`(吊り・上部に環や取付部)/ `"unknown"`

- 判定材料の例: 最下部の断面の広がり、重心の高さ、上端付近の環状構造の有無、全体のアスペクト比
- `"hanging"` / `"unknown"` の場合は `contact_offset` を推定せず 0 + `needs_review`

### R6. キャッシュはファイル名ではなく内容ハッシュで

v1は「ファイル名がテーブルにあれば再計測しない」。9月にアセットを再生成すると、
**同名だが中身が違うGLBに古いオフセットが適用される**。これは静かに壊れる最悪の形。

- 各エントリに `sha256`(先頭16桁で可)と `schema_version`、`method` とそのパラメータを記録する
- ハッシュ不一致、または `schema_version` / `method` パラメータの不一致を検出したら自動で再計測する

### R7. 人間による上書き経路

`scene/assets/contact_overrides.json` を新設する(手書き、ツールは**絶対に上書きしない**)。
優先順位は **シーンJSONのオブジェクト指定 > contact_overrides.json > contact_offsets.json > 0.0**。
`contact_offset.lookup()` をこの優先順位に対応させること。

### R8. 視覚レポート

アセットが増えると数値だけでは検証できない。`--report out.png` で、
各アセットについて **側面から見た点群投影に、推定した接地面・天面・支持面候補を水平線で重ねた図**を
一覧(コンタクトシート)として出力すること。1アセット1パネル、`needs_review` は枠を強調。

これが今回いちばん重要な成果物。**「機械検査が通っても目視で破綻が見つかる」という
このプロジェクト固有の問題に対して、目視を数十アセット分まとめて高速化する装置**として作ること。

### R9. 呼び出し側の追従

- `machine_checks.py`: `needs_review: true` のアセットについては、
  浮遊判定の許容差 `REST_TOL` を広げる(例: 2倍)か、違反の `detail` に「オフセット未確定」を明記する。
  自信の無い推定で強制的にsnapさせないこと
- `repair.py`: 既存の「`position[1] = 目標面 − 接地オフセット`」の計算はそのまま維持
- `orchestrator.py`: 起動時の自動計測(未計測・ハッシュ不一致のみ)はそのまま維持

## 4. 出力スキーマ(`contact_offsets.json`)

```json
{
  "_meta": {
    "schema_version": 2,
    "method": "surface_sampling+spread_profile",
    "params": {"n_slabs": 64, "tau_body": 0.10, "tau_support": 0.35, "periphery": 0.20},
    "updated_at": "2026-08-12 10:00:00"
  },
  "lantern_v1.glb": {
    "sha256": "a1b2c3d4e5f6a7b8",
    "contact_offset": 0.0928,
    "support_offset": 0.3176,
    "support_planes": [{"y_frac": 0.68, "area_frac": 0.41, "clearance_frac": 0.0, "confidence": 0.6}],
    "ground_type": "tabletop",
    "confidence": 0.82,
    "needs_review": false,
    "aabb_height": 1.0015,
    "samples": 200000,
    "measured_at": "2026-08-12"
  }
}
```

既存キー(`contact_offset`, `support_offset`, `method`, `measured_at`)は名前も意味も変えないこと。
`schema_version` が無い旧テーブルは読み込めるが、全エントリを再計測対象とする。

## 5. 受け入れ基準

### A. 現行15アセットで回帰しないこと

`scene/assets/` の現行アセットに対する v1 の実測値。v2 はこれを再現すること(許容差 ±0.02)。

| asset | contact | support |
|---|---|---|
| chair_v1/v2/v3.glb | 0.000 | 0.635(座面) |
| crystal_v1.glb | 0.000 | 0.222 |
| lantern_v1.glb | 0.093 | 0.318 |
| plant_v1.glb | 0.000 | 0.032 |
| plant_v2.glb | 0.000 | 0.143 |
| shelf_v1/v2/v3.glb | 0.000 | 0.000 |
| stool_v1/v2/v3.glb | 0.000 | 0.000 |
| table_v1.glb | 0.000 | 0.000 |
| table_v2.glb | 0.000 | **0.524** |

例外として `shelf_v*.glb` は R4 により `support_planes` に棚板が複数現れること(support_offset自体は0のままでよい)。

### B. 合成メッシュのテストを拡張する

`python/test_contact_offset.py` に既存8件のテストがある。これを維持したうえで、
**低ポリ版**(各形状を数十三角形で表現したもの)を追加し、R1が効いていることを示すこと。
低ポリ版で v1 のアルゴリズムが失敗し、v2 が成功することをテストで明示する。

さらに以下のケースを追加:

- Z-up で作った机 → `axis_warning: true`
- 上端に環だけがある吊りランタン → `ground_type: "hanging"`、`contact_offset: 0`
- 棚板3枚の本棚 → `support_planes` の長さ 3
- 頂点0/NaNを含む壊れたメッシュ → 例外を投げず `needs_review: true`

### C. 実シーンでの検証

`runs/final_seed2c/wizard_study_seed2_20260809_165616/` の `final_scene.json` と
`iter_03/capture/report.json` を入力に `machine_checks.run_all()` を実行し、
`lantern_01` に対して **`floating` +0.429m 相当** の違反が検出されること(v1と同じ結論)。
`repair.apply_repairs()` 適用後、`lantern_01.position[1]` が 0.30 付近になること。

### D. 性能

70MB級のGLBを含む15アセットの全再計測が、常識的なノートPCで **3分以内**に完了すること。

## 6. やってはいけないこと

- Unity側(`SceneBuilder.cs`)の配置・スケール規則を変更すること。
  「AABB最下端を`position[1]`に合わせる」「AABB全高を`target_dimensions.height`に合わせる」は
  今回は**前提として固定**。これらの見直しは別タスク
- `machine_checks.py` の検査項目を増やすこと(意味的な向きの検査などは別タスク)
- 重い依存を必須にすること。`numpy` は可。`trimesh` 等は**任意(あれば使う)**に留める
- `contact_overrides.json` をツールから書き換えること
- 既存の日本語コメント・メッセージを英語化すること

## 7. 成果物

1. `python/contact_offset.py`(v2に更新。CLIは `--force` / `--asset` / `--verbose` を維持し `--report` を追加)
2. `python/test_contact_offset.py`(テスト拡張。`python test_contact_offset.py` で全通過)
3. `scene/assets/contact_offsets.json`(再生成)
4. `scene/assets/contact_overrides.json`(空のひな形 + コメント代わりの `_meta`)
5. 変更点と、`needs_review` になったアセットの一覧を書いた短い実行結果メモ
