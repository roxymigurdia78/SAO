# Adaptive LOD MVP

`desk`、`chair`、`plant` の3種類で、近距離の見た目を維持しながら
画面上で小さくなった物体のポリゴン数を下げる最小実装。

## 実行

Unityで既存の処理が終わり、スクリプトのコンパイルが完了してから
`MVL > Build LOD MVP (desk-chair-plant)` を選ぶ。

初回は各GLBのUV2とLODメッシュを生成する。生成GLBにUV0がある場合は
UV2へ複製して利用し、重い自動UV展開は行わない。UV0がない例外だけ
Unityの自動UV2生成へフォールバックする。
生成物は `Assets/MVLGenerated/LOD/` に保存され、同じGLBを使う2回目以降は
キャッシュが利用される。GLBが変更されると依存関係ハッシュが変わり、別キャッシュを生成する。

## プロファイル

シーンJSONの各オブジェクトに `mesh_profile` を指定する。

- `fragile`: 近距離=元メッシュ、中距離=10万、遠距離=6万
- `standard`: 近距離=元メッシュ、中距離=6万、遠距離=3万
- `robust`: 近距離=元メッシュ、中距離=4万、遠距離=2万
- `original`: LODを作らず元メッシュを使う

未指定時はクラス名から次の固定分類を使う。JSONに `mesh_profile` があれば
個別指定を優先し、未知のクラスは安全側で `original` とする。

- `fragile`: chair, plant, lamp, floor_lamp, lantern, backpack, monitor,
  mug, pen_holder, crystal, orb
- `standard`: trash_bin, laptop, stool
- `robust`: desk, bookshelf, shelf, cabinet, rug, books, printer, table

## 目視確認

Playモードで物体へ近づいたり離れたりして、次を確認する。

1. 近距離の輪郭が元メッシュと同程度か
2. 中・遠距離で荒さが見えないか
3. LOD切替時のポッピングが目立たないか

Hierarchyで対象を選び、`LOD Group` コンポーネントのプレビューをドラッグすると、
各LODを強制表示して比較できる。

ビルドレポートには `mesh_profile`、`lod_triangle_counts`、
`lod_cache_hits`、`lod_cache_misses` が記録される。
