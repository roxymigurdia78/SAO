# シーンJSON スキーマ v1.0(L3 台帳)

シーンの唯一の真実(single source of truth)。Python が読み書きし、Unity は読むだけ(+実測レポートを別ファイルに書く)。

## 座標系(重要)

- 単位: **メートル**。部屋の床の左奥隅が原点 (0,0,0)
- `x` = 幅方向、`z` = 奥行方向、`y` = 高さ(Unityと同じY-up左手系)
- `position` はオブジェクトの **底面中心**(足元)。`must_touch_floor: true` なら y=0
- `rotation_y_deg` はY軸回転のみ(8月は水平回転だけで十分)

## トップレベル

| キー | 説明 |
|---|---|
| `schema_version` | "1.0" 固定 |
| `scene_id` | 実行ログのフォルダ名になる |
| `spec` | 空間仕様書(ハード制約の源泉)。`required_objects` は機械検査(欠落チェック)が参照 |
| `room` | 部屋の寸法・入口・照明。`lighting.sun.mode` は必ず `"Mixed"`(ベイク+リアルタイムの両対応。C4実験の教訓) |
| `assets_dir` | GLB置き場(シーンJSONからの相対パス) |
| `objects` | オブジェクト台帳(下記) |
| `walkable` | 動線検査のパラメータ(エージェント半径・グリッド解像度) |
| `views` | `"auto"` なら BatchCapture が部屋寸法から8視点を自動生成。カスタムは配列で上書き |
| `history` | オーケストレータが反復ごとに追記(iteration, 適用した修正, スコア)。ロールバックはこの履歴+各反復のJSONコピーで行う |

## objects[] の各フィールド

| キー | 説明 |
|---|---|
| `id` | 一意ID。修正オペレータの対象指定に使う |
| `class` | 意味クラス(desk/chair/...)。required_objects との照合キー |
| `asset` | 現在使用中のGLBファイル名 |
| `asset_variants` | バリアントプール(3個)。低品質→差し替えオペレータがここから選ぶ |
| `position` | [x, y, z] 底面中心 |
| `rotation_y_deg` | Y軸回転(度) |
| `target_dimensions` | 望む実寸(w/h/d)。**SceneBuilderはGLBの実測サイズをこの高さに合わせて一様スケール**する(TRELLISの出力スケールは信用しない) |
| `class_height_range` | クラスとして許容される高さ範囲[m]。スケール逸脱検査が参照 |
| `must_touch_floor` | true なら浮遊検査の対象(y=0 かつ実測AABB底面が床±許容差) |
| `rests_on` | 他オブジェクトの上に載る場合の親ID(ランプ→机)。浮遊検査は親の上面を基準にする |
| `faces` | 正面を向ける対象ID。`rotation_y_deg + assets_inventory.jsonのfront_offset_deg`が対象方向から既定±45度以内か検査する |
| `faces_tolerance_deg` | `faces`の許容角度。省略時45度 |
| `near` | 近接制約。`{"target": "desk_01", "max_distance": 1.0}`の形式で水平中心間距離[m]を検査する |
| `walkable_over` | true(ラグ等)は動線検査で障害物扱いしない |
| `locked` | true なら修正オペレータは変更禁止(ハード制約「変更不可属性」) |
| `provenance` | source/prompt/generated_at。卒論の再現性記述に使う |
| `quality_score` | VLM単体採点の最新値(オーケストレータが書き込む) |

`assets_inventory.json` の各assetには任意で `front_offset_deg` を追加できる。
GLBのローカル+Z正面から見た補正角で、省略時は0度。値はアセットごとの実測後に設定する。

## Unity側の実測レポート(report.json)

SceneBuilder が配置後に `capture/report.json` を出力する:

```json
{
  "objects": [
    { "id": "desk_01", "aabb_min": [0.6, 0.0, 2.8], "aabb_max": [1.8, 0.73, 3.4],
      "triangle_count_before": 139601, "triangle_count_after": 14980 }
  ],
  "captures": ["view_00.png", "..."],
  "bake_seconds": 61.2
}
```

機械検査は **report.json の実測AABBがあればそれを優先**、無ければ target_dimensions からの公称AABBで動く(Python単体のドライラン用)。
