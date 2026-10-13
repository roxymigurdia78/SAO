# 室内照明の研究に取り入れる外部データ・ツール

確認日: 2026-10-10。公式配布ページ、論文、公開ソースとライセンス、現在のローカル実装を照合した調査。実行していないツールの性能や、未取得の画像の品質は確認済みとして扱わない。

外部から取り入れる価値はある。既存の Unity パイプラインを使いながら、色の計算、材質の参照値、測光データ、探索の比較対象を取り入れる構成を勧める。以下の「組み込みやすさ」と優先順位は、このプロジェクトに対する判断であり、配布元が保証する性能ではない。

| 名前 | URL | 何に使えるか | ライセンス | Unity/Pythonへの組み込みやすさ | 確度 |
| --- | --- | --- | --- | --- | --- |
| Laval Photometric Indoor HDR / Beyond the Pixel | [公式](https://lvsn.github.io/beyondthepixel/)・[コードと許諾](https://github.com/lvsn/beyondthepixel/blob/main/LICENSE.txt) | 校正された室内の輝度・色・照度の参照 | リポジトリは研究等の非商用利用可。全画像の配布条件は不明 | 中。EXR読込、撮影条件との対応付けが必要 | 校正・形式・公開split確認済み。全データ取得とEULA未確認 |
| Theta Dataset | [同論文の公式配布](https://lvsn.github.io/beyondthepixel/) | 別カメラの校正HDRとJPEGを用いた小規模検証 | データ固有の条件は不明 | 中。74枚、配布リンクあり | 枚数と校正確認済み。取得・許諾未検証 |
| 北方建築の測光画像データ | [Mendeley公式](https://data.mendeley.com/datasets/gpd7r5tngg/1) | HDR画像と実測照度CSVの照合 | データはCC BY 4.0 | 中。室内7地点なので動作確認向き | 内容・枚数・データ許諾確認済み。色校正の詳細不明 |
| PanDORA | [公式](https://lvsn.github.io/pandora/dataset/index.html) | 室内の位置ごとのHDR、露出情報、透視投影画像 | 独自許諾。引用付きで研究等可、再配布禁止 | 中。EXR/PNG/JSONを利用可能 | 14シーン・195 HDR確認済み。絶対測光校正は不明 |
| Infinigen Indoors | [indoors-stable](https://github.com/princeton-vl/infinigen/tree/indoors-stable)・[許諾](https://github.com/princeton-vl/infinigen/blob/indoors-stable/LICENSE) | 窓・器具の寸法、配置制約、初期値の参考 | 本体BSD-3-Clause。別依存の許諾は別 | 規則の移植は中、全体導入は難 | 下記の具体的なコード値確認済み。現実の規格値である根拠は不明 |
| Holodeck | [公式コード](https://github.com/allenai/Holodeck)・[許諾](https://github.com/allenai/Holodeck/blob/main/LICENSE) | 部屋と開口の関係、簡単な照明配置の比較対象 | コードApache-2.0。モデルの許諾は個別 | 規則の移植は中、全体導入は難 | 窓・ドア・照明実装確認済み |
| Physically Based | [公式](https://physicallybased.info/about/)・[API/許諾](https://github.com/AntonPalmqvist/physically-based-api) | 材質の色、roughness、IOR、光源の仕様など | データCC0 1.0。プレビュー用shader ballは別許諾 | 易。JSONを取得して必要項目を対応付ける | JSON、色空間、参照リンク、許諾確認済み |
| colour-science | [公式コード](https://github.com/colour-science/colour)・[OhnoのAPI](https://colour.readthedocs.io/en/latest/generated/colour.temperature.uv_to_CCT_Ohno2013.html) | 自作CCT計算の置換、CCTとDuvの計算 | BSD-3-Clause | 易。Pythonの色計算部分に導入 | APIと許諾確認済み。この環境への導入未実施 |
| Peli / Reinhardの指標 | [Peli 1990](https://pelilab.partners.org/papers/ContrastJOSA.pdf)・[Reinhard 2002](https://pages.cs.wisc.edu/~lizhang/courses/cs766-2007f/projects/hdr/Reinhard2002PTR.pdf) | コントラスト・明るさの定義と引用元 | 論文の定義を引用。外部実装の許諾は対象外 | 易。ただし入力の線形性と尺度を明記する | RMSと対数平均確認済み。現行logstdと同一定義の出典は不明 |
| IndoorLightEditing | [論文](https://arxiv.org/abs/2205.09343)・[公式コード](https://github.com/ViLab-UCSD/IndoorLightEditing) | 窓・ランプを推定して再照明する関連研究 | コードMIT。外部データ等は別確認 | 難。深度・マスク・専用レンダラ等が必要 | 論文・コード・本体許諾確認済み。実行未検証 |
| Adjoint Light Tracing | [論文](https://arxiv.org/abs/2310.02043)・[著者のコード保存版](https://github.com/david-hahn/AdjointLightTracing-backup) | 器具の位置・向き・強さ・色を最適化する関連研究 | 保存版GPL-3.0 | 難。Unityとは異なるレンダラ | 論文と保存版の許諾確認済み。現行環境でのビルド不明 |
| Optuna | [Ask-and-Tell](https://optuna.readthedocs.io/en/stable/tutorial/20_recipes/009_ask_and_tell.html)・[許諾](https://github.com/optuna/optuna/blob/master/LICENSE) | JSONのつまみを提案する既存探索法、比較実験 | MIT | 易〜中。現在の撮影と測定を呼び出す橋渡しが必要 | APIと許諾確認済み。Unity接続未実施 |
| pyiqa | [公式コード](https://github.com/chaofengc/IQA-PyTorch)・[許諾](https://github.com/chaofengc/IQA-PyTorch/blob/main/LICENSE) | BRISQUE等の画像品質を補助列として測る | 現行本体はPolyForm Noncommercial 1.0.0。重みは個別確認 | 中。PyTorchと重みの追加が必要 | 指標提供と本体許諾確認済み。照明写実性の尺度としては未検証 |
| glTFastの発光処理 | [公式実装](https://github.com/Unity-Technologies/com.unity.cloud.gltfast/blob/main/Packages/com.unity.cloud.gltfast/Runtime/Scripts/Material/ShaderGraphMaterialGenerator.cs) | 現在の発光処理の不一致を調べる | 現在導入済みの6.19.0はApache-2.0 | 易。キーワードの対応を直す候補 | ローカルと公開ソースの一致確認済み。表示テスト未実施 |

## 1. Laval: 元のHDRと測光校正版を区別する

元の Laval Indoor HDR がそのまま絶対的な光の強さを記録している、という前の説明は修正が必要。ICCV 2023の Beyond the Pixel は、既存の未校正HDRに、RAWの段階露光と色彩照度計を用いて校正係数を与えた研究である。目的に合う候補は、この **Laval Photometric Indoor HDR**。HDRというファイル形式だけで、自動露出・ホワイトバランス・カメラ応答の問題が解決したとは言えない。[公式説明](https://lvsn.github.io/beyondthepixel/)、[論文](https://arxiv.org/abs/2304.12372)

公開された分割リストを集計すると、train 1,889、test 237、val 236、合計2,362件で、リストを合わせたファイル名にも重複はなかった。公開処理は線形EXRを読む。古い論文の「2,100以上」という概数と混ぜず、この調査では分割リストの件数を記録する。[train](https://github.com/lvsn/beyondthepixel/blob/main/Learning%20Tasks/util/train.txt)、[test](https://github.com/lvsn/beyondthepixel/blob/main/Learning%20Tasks/util/test.txt)、[val](https://github.com/lvsn/beyondthepixel/blob/main/Learning%20Tasks/util/val.txt)、[読込処理](https://github.com/lvsn/beyondthepixel/blob/main/Learning%20Tasks/prepare_dataset.py)

公式ページは全データの入手案内と100パノラマのサンプルを hdrdb.com の配布ページに案内している。今回はその配布ページを取得できず、全画像の最新EULA、申請手順、ダウンロードの実行可否は不明。公開コードのライセンスは学術・非営利・政府支援研究等の非商用利用を認めるが、それだけで別配布の全画像の許諾を確定しない。[公式案内](https://lvsn.github.io/beyondthepixel/)、[コードの許諾](https://github.com/lvsn/beyondthepixel/blob/main/LICENSE.txt)

組み込み案: まず少数の校正画像で読み込みを確認し、画像の見た目の比較と、物理的な輝度・照度の比較を設計する。現在の `light_metrics.py` は8ビット画像を0〜1に変換し、L2〜L4はガンマ後の画素で計算している。校正EXRの線形値をそのまま同じ閾値で比べることはできない。露出、ホワイトバランス、トーンマッピング、色空間を記録し、パノラマから同等の視野の画像を作る工程が必要になる。これは本調査の設計提案。

参照分布への適性: 校正版は輝度・色の検証に有望。ただし、全室内の分布が書斎の分布と等しいかは不明。部屋の種類、昼夜、窓の有無を確認した選別が必要で、画像統計の範囲内に入ることだけから「写実的」と結論することはできない。

## 2. 代替の室内HDR・測光データ

Theta Datasetは、同研究がRicoh Theta Z1で撮影した74枚の測光校正HDRと対応LDR JPEG。公式ページに直接配布リンクがあり、別カメラでも動くかの検証に使える。データ固有の許諾文書は今回独立に確認できていない。[公式配布](https://lvsn.github.io/beyondthepixel/)

北方建築のデータは13地点、うち室内7・屋外6。段階露光、HDR・トーンマップ画像、輝度の解析画像、パノラマに加え、放射計で測ったluxとEMLのCSVがある。**データの許諾はCC BY 4.0**。室内の大きな参照分布を作る用途には少ないが、画像処理と実測値の対応を確認する用途に向く。RGBの絶対色校正やCCTの信頼性の詳細は不明。[公式データ・許諾](https://data.mendeley.com/datasets/gpd7r5tngg/1)

PanDORAは14室内シーン、195のGT HDRパノラマ（EXR）、2台の360度カメラの異なる露出の入力、撮影設定JSON、透視投影のGT画像を公開。研究・教育・商業研究等を引用付きで認め、再配布・ミラーは禁止する独自許諾。絶対輝度cd/m²や色の測光校正は配布説明から確認できなかったため、Laval測光校正版と同じ扱いにはしない。195視点を195の独立した部屋とも数えない。[公式データ・許諾](https://lvsn.github.io/pandora/dataset/index.html)

## 3. Infinigen Indoorsから借りられる具体的な規則

現行mainは2.0のプレビューに向けて構成が変わっている。既存の室内生成を調べるため、公式が案内する `indoors-stable` ブランチを読んだ。本体はBSD-3-Clauseだが、GPLの別サブモジュール等まで同じ許諾とみなさない。[公式README](https://github.com/princeton-vl/infinigen)、[本体許諾](https://github.com/princeton-vl/infinigen/blob/indoors-stable/LICENSE)

| 対象 | コードで確認した規則・値 | 出典 |
| --- | --- | --- |
| 通常の窓の開口 | `window_height`（下側の高さを決める値）0.8〜1.2m、縦寸法1.0〜1.5m、壁端の余白0.2〜0.25mが初期分布。天井高さ等に応じ縦寸法を補正 | [RoomConstants](https://github.com/princeton-vl/infinigen/blob/indoors-stable/infinigen/core/constraints/constraint_language/constants.py) |
| 窓の位置と幅 | 外壁を分割して開口を作る。通常窓の幅は `door_width` から「壁区間の長さ−余白×2」までの範囲で取り、端に収まる位置を選ぶ。パノラマ窓は区間中央に配置 | [solidifier.py](https://github.com/princeton-vl/infinigen/blob/indoors-stable/infinigen/core/constraints/example_solver/room/solidifier.py) |
| 窓モデルの寸法 | 部屋生成では開口の幅・高さをWindowFactoryへ渡す。Factoryを単独で寸法なしで使う場合の幅・高さ1〜4mを、通常の室内生成の窓寸法と混同しない | [decorate.py](https://github.com/princeton-vl/infinigen/blob/indoors-stable/infinigen/core/constraints/example_solver/room/decorate.py)、[window.py](https://github.com/princeton-vl/infinigen/blob/indoors-stable/infinigen/assets/objects/windows/window.py) |
| 点光源 | Blenderのenergyに40〜100、光源半径0.02〜0.03m、色温度は平均4700K・標準偏差700Kの分布を3500〜6500Kで制限 | [indoor_lights.py](https://github.com/princeton-vl/infinigen/blob/indoors-stable/infinigen/assets/lighting/indoor_lights.py) |
| 卓上ランプ | 点光源のenergyを半分にする。色温度は元の0.6倍、下限2500K。器具のシェード内部に光源を配置 | [lamp.py](https://github.com/princeton-vl/infinigen/blob/indoors-stable/infinigen/assets/objects/lamp/lamp.py) |
| 天井器具の寸法 | ランダムな半径0.10〜0.25m。高さは0.07〜0.15mの分布に0.7を掛ける。器具とPointLampFactoryを組み合わせる | [ceiling_lights.py](https://github.com/princeton-vl/infinigen/blob/indoors-stable/infinigen/assets/objects/lamp/ceiling_lights.py) |
| 配置制約 | 通常の部屋の天井灯1〜4個、面積に対する個数の目標0.08〜0.15個/m²。壁から離す・器具同士を離す得点と、室内光源間の最小距離1m以上の制約。部屋種別の例外あり | [home.py](https://github.com/princeton-vl/infinigen/blob/indoors-stable/infinigen_examples/constraints/home.py) |

これらは「Infinigenで採用された生成規則」として引用できる。実測した住宅の分布、建築規格、写実性を保証する閾値であることは確認できない。またBlenderのenergyをUnityのintensityへ直接コピーする対応は確認できない。こちらでは寸法と配置制約を初期候補に使い、強さは同じUnity環境で検証するのが適切。

メッシュのFBX等への書き出しは公式にあるが、全シーンではUSDが主な対応で、マテリアルの書き出しには制限がある。照明・半透明・発光まで同じ結果になるとは限らないため、全パイプライン導入より規則を移す方が、このプロジェクトの変更量は小さい。[公式の書き出し説明](https://github.com/princeton-vl/infinigen/blob/indoors-stable/docs/ExportingToExternalFileFormats.md)

## 4. Holodeckの窓・ドア・照明

窓はLLMの提案を受け、外壁とアセットを対応付ける。候補壁からドアのある壁を除き、幅2m未満を除外し、方向ごとに最も広い壁を選ぶ。ドアは部屋間の共有壁、接続、開口ポリゴンとアセットの位置を扱う。壁幅に収まる条件や、部屋を接続する処理がある。[windows.py](https://github.com/allenai/Holodeck/blob/main/ai2holodeck/generation/windows.py)、[doors.py](https://github.com/allenai/Holodeck/blob/main/ai2holodeck/generation/doors.py)

照明は比較的簡単で、Directional Lightのintensityは0.35。各部屋の床ポリゴンの重心にPoint Lightを置き、天井または天井器具の0.2m下、intensity 0.75、range 15、RGB (1, 0.855, 0.722)、soft shadowとする。これらはシミュレータの初期設定であり、物理的に正しい室内照度の根拠ではない。[lights.py](https://github.com/allenai/Holodeck/blob/main/ai2holodeck/generation/lights.py)

コードはApache-2.0。AI2-THORの環境やアセットが必要で、現在のScene JSONにそのまま入るツールではない。アセットの個別許諾は本体コードの許諾とは別に確認する。[公式コード](https://github.com/allenai/Holodeck)、[本体許諾](https://github.com/allenai/Holodeck/blob/main/LICENSE)

## 5. Physically Basedの中身・許諾・引用

v2の公開JSONには材質の色、色空間、metalness、roughness、IOR・complex IOR、transmission等があり、項目ごとにreferencesを持つ。確認時点のmaterialsは116項目、lightsourcesは25項目。光源には色温度、intensityとunit（例: lm）、光源サイズ等がある。材質の色には`srgb-linear`や`acescg`の指定があり、色空間を無視してUnityの表示色にコピーしない。[材質JSON](https://github.com/AntonPalmqvist/physically-based-api/blob/main/deploy/v2/materials.json)、[光源JSON](https://github.com/AntonPalmqvist/physically-based-api/blob/main/deploy/v2/lightsources.json)

データはCC0 1.0。すべての値が同じ精度の測定値であるとは限らず、公式も出発点・既存素材の検証用と説明している。「材質の許容範囲」を一つの固定値から作るより、各項目の原資料と表面仕上げを確認して幅を決める用途に向く。[APIの許諾](https://github.com/AntonPalmqvist/physically-based-api)、[公式説明](https://physicallybased.info/about/)

論文では使用項目のReferencesにある元資料を引用するのが勧められている。サイト自体も引用でき、著者はAnton Palmqvist、題名はPhysically Based - The PBR Values Database、確認日は2026-10-10として記録できる。API値と元資料の版も保存すると再現しやすい。[公式の引用案内](https://physicallybased.info/about/)

## 6. 指標の定義: 引用できるものと未確認のもの

Peli (1990), *Contrast in complex images*, JOSA A 7(10), 2032–2040の式(4)は、0〜1の正規化グレーレベルの平均を引いたRMS、すなわち標準偏差を示す。したがって現在の `L3_std` の形式にも既存の根拠がある。「標準偏差だから自作で不適切」とは言えない。ただし、その一値だけでは空間的な影の配置や知覚上の写実性を表せない。[原論文、式(4)](https://pelilab.partners.org/papers/ContrastJOSA.pdf)

Reinhard et al. (2002), *Photographic Tone Reproduction for Digital Images* は、対数平均輝度を `exp(mean(log(delta + L)))` と定義する。これはシーンのkeyの近似として使う明るさの代表値で、コントラストの標準偏差ではない。さらにトーンマッピングのパラメータa（通常0.18）は別の量。元の式はworld luminanceを入力にしており、現在のガンマ後画像への適用はその入力規約まで同じではない。[原論文、式(1)・(2)](https://pages.cs.wisc.edu/~lizhang/courses/cs766-2007f/projects/hdr/Reinhard2002PTR.pdf)

現行の `std(log(Y' + 0.01))` と同じ「ガンマ後の画像全体・固定0.01・標準偏差」という組合せを標準指標として裏付ける原典は、今回確認できなかった。対数を使う既存のコントラスト研究があることだけから、同一定義とは言えない。例えばLindgren et al. (2007)はフィルタ応答の絶対値の対数を使うもので、現在の計算とは異なる。[原論文](https://www.cs.helsinki.fi/u/ahyvarin/papers/Lindgren07SCIA.pdf)

数学上、正の線形輝度Lに対する `std(log(L))` は、Lを一定倍しても変わらない。固定の0.01を足す現行式やトーンマッピング後画像では、その性質がそのまま成立しない。この性質は式からの判断であり、現在の指標が人の写実性判断と一致するという実証ではない。今回の5条件の結果だけで「新しいL3の方が良い」と確定するのは早い。

colour-scienceにはMcCamyのxy→CCTと、OhnoのCIE UCS uv→CCT・Duvがある。入力座標の違いに注意する。ライブラリへの置換は数式実装を借りる効果があるが、写真の平均色には壁・家具の反射色とカメラ処理が混ざるため、照明自体のCCTを測定したことにはならない。L1を続けるなら「画像平均色から計算したCCT」と明記し、Duv等で計算の適用範囲を点検する案がある。[McCamy API](https://colour.readthedocs.io/en/latest/generated/colour.temperature.xy_to_CCT_McCamy1992.html)、[Ohno API](https://colour.readthedocs.io/en/latest/generated/colour.temperature.uv_to_CCT_Ohno2013.html)、[ライブラリ](https://github.com/colour-science/colour)

既存の撮影画像は再計算に使える。ただし定義や入力処理を変えた場合、写真側の参照範囲と生成画像の測定値は両方作り直し、旧結果を同じ指標の結果として混ぜない。

## 7. 既存の照明調整研究と探索ライブラリ

Li et al. (2022), *Physically-Based Editing of Indoor Scene Lighting from a Single Image* は、一枚の画像、深度、見える窓・ランプのマスク等から、材質や見える/見えない光源を推定して再照明する。現在のJSONのつまみを一段動かす方法とは入力と構成が異なるが、窓とランプを分けた光源表現や関連研究の説明に役立つ。公式実装はMIT、専用の描画・学習環境が必要。[論文](https://arxiv.org/abs/2205.09343)、[公式実装](https://github.com/ViLab-UCSD/IndoorLightEditing)

Lipp et al., *View-Independent Adjoint Light Tracing for Lighting Design Optimization* は、3D形状上の目的に対して器具の位置・向き・強度・色を最適化する手法。画像統計への一致を写実性とみなす現在の評価とは異なる。元の公開先は調査時に空で、著者によるコード保存版は存在しGPL-3.0だった。現在のWindows/Unity環境で動くかは未確認。[論文](https://arxiv.org/abs/2310.02043)、[著者保存版](https://github.com/david-hahn/AdjointLightTracing-backup)、[許諾](https://github.com/david-hahn/AdjointLightTracing-backup/blob/main/LICENSE)

追加で有望なのはOptuna。Ask-and-Tellなら「パラメータを提案する→既存Unity処理で撮る→測定結果を返す」という接続ができ、描画の勾配を必要としない。MIT。これは既存APIから判断した接続案であり、このプロジェクトで性能確認をした結果ではない。[公式API](https://optuna.readthedocs.io/en/stable/tutorial/20_recipes/009_ask_and_tell.html)、[許諾](https://github.com/optuna/optuna/blob/master/LICENSE)

研究上は、独自の一段ずつの修正ループと既存探索法を、同じ初期値・範囲・撮影回数で比べる案が有効。既存ライブラリを使う範囲と研究の主張は一緒に決める必要がある。「ループを自作した」だけで新規性が成立するとは限らない。評価対象の部屋・視点を探索に使ったものから分け、主観的な写実性判断との対応も検証する、というのが本調査からの提案。

pyiqaはBRISQUE等を実装済みで、補助的な画質列を追加する負担を減らせる。ただし画質スコアを室内照明の物理的な妥当性や写実性の正解として扱う根拠は確認できない。現行本体の許諾はMITではなくPolyForm Noncommercial 1.0.0で、モデル重みには別の条件があり得る。[公式実装](https://github.com/chaofengc/IQA-PyTorch)、[本体許諾](https://github.com/chaofengc/IQA-PyTorch/blob/main/LICENSE)

## 8. glTFastの発光: 名前は合っているが有効化の違いがある

このプロジェクトに入っているglTFastは6.19.0。ローカルの `MaterialProperty.cs` は `emissiveFactor` と `emissiveTexture` を定義し、`ShaderGraphMaterialGenerator.cs` は発光色を設定した後に **`_EMISSIVE`** を有効にする。公開ソースでも同じ処理を確認した。[公式のマテリアル生成処理](https://github.com/Unity-Technologies/com.unity.cloud.gltfast/blob/main/Packages/com.unity.cloud.gltfast/Runtime/Scripts/Material/ShaderGraphMaterialGenerator.cs)

こちらの `SceneBuilder.cs` は `emissiveFactor` を設定するが、有効化は `_EMISSION` だけ。glTFastの分岐で `_EMISSIVE` を有効にすることが、まず試すべき修正候補。URP/Litの分岐では `_EMISSION` を扱う。`HasProperty`がtrueというログは、プロパティの存在を示すだけで、発光の機能が有効になった証拠にはならない。公開ソースとの不一致は確認済みだが、これが現在の画面の不発光の唯一の原因かは表示テストが必要。

Editorで光ってビルドでだけ消える場合には、発光を含むShader Variantの除去も次の候補になる。公式リポジトリにその症状の報告があるが、その報告の条件と現在の実行条件が一致するかは未確認。[公式リポジトリの報告](https://github.com/Unity-Technologies/com.unity.cloud.gltfast/issues/52)

確認すべき箇所: `XRunity/Assets/Editor/SceneBuilder.cs` の発光処理（667〜678行付近）、`XRunity/Library/PackageCache/com.unity.cloud.gltfast@92828f845157/Runtime/Scripts/Material/ShaderGraphMaterialGenerator.cs`（100行、446〜447行）、同ディレクトリの `MaterialProperty.cs`（46〜48行）。この調査ではコード変更とUnityの表示テストは行っていない。

## 優先度の高い3つ

1. **colour-scienceと指標の原典**: 少ない変更で計算と説明を整えられ、L1の意味とL3の根拠を先に確定できる。
2. **Laval測光校正版などの測光データ**: JPEGの見た目の分布だけに頼る評価から、光の値を検証する足場を作れる。まず取得条件と少数画像での接続を確認する。
3. **Physically Based**: CC0のJSONと原資料を使って、材質・光源の初期値を具体的に検証でき、導入の手間が小さい。

探索法の比較まで進む際の次候補はOptuna。InfinigenとHolodeckは配置規則の参考、専用の逆レンダリング研究は関連研究として読む価値がある。最終的な研究の主張、指標の採否、Unityでの見た目の評価はユーザーが判断する。
