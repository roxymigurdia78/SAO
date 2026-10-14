# 室内写真データセット調査の集計根拠

確認日: 2026-10-09

このフォルダのCSVは写真の画素を計測した結果ではなく、公式配布メタデータの集計です。画像そのもののダウンロード、実写判定、CLIPによる選別、画像ライセンスの個別照合は実行していません。

## Places365 Standard

- `places365_selected_counts.csv`: 関係する7分類の学習用・検証用枚数。
- 公式ファイル一覧: http://data.csail.mit.edu/places/places365/filelist_places365-standard.tar
- 全学習用1,803,460件、全検証用36,500件を集計。
- 分類IDは公式の `categories_places365.txt` に対応する。
- この結果は公式Standard版の件数。Hugging Face各ミラーに同じ画像・同じ分類がすべて含まれることを照合した結果ではない。

## Open Images V7

- `openimages_selected_counts.csv`: 指定したMIDの人手確認ラベルで、Confidenceが1.0の一意な画像ID数。
- 検証用: https://storage.googleapis.com/openimages/v7/oidv7-val-annotations-human-imagelabels.csv
- 評価用: https://storage.googleapis.com/openimages/v7/oidv7-test-annotations-human-imagelabels.csv
- MID一覧: https://storage.googleapis.com/openimages/v7/oidv7-class-descriptions.csv
- 学習用の分類別件数は未確認。
- ラベルが付いた写真が研究に使える室内全景であること、実写であること、256px以上であることは別途確認が必要。
- 0件は、そのファイルに人手確認の正例がなかったという意味であり、その種類の写真が存在しないことを意味しない。
- 複数ラベルが同じ画像に付くため、分類間の件数は合計して総画像数にできない。

## SUN397の部分統計

`sources/sun397-statistics.json` はHugging Faceが最初の一部だけから計算した統計（partial=true、12,870件）です。全108,754件の分類別枚数として使えません。全画像版の関係する部屋別件数は未確認です。

## 再現と出典

- `count_evidence.json`: 件数、公式URL、取得したファイルのSHA-256。
- `count_metadata.py`: Python標準ライブラリだけで公式一覧を再集計する補助ファイル。
- この調査でモデルの学習は行っていません。
- 取得可能であることやミラーに付いたライセンス表示だけでは、元の写真の利用許諾を確認したことにはなりません。
