// SceneBuilder.cs — シーンJSON → Unityシーン構築 → デシメーション → ライトマップベイク → 8視点撮影
// 置き場所: Assets/Editor/SceneBuilder.cs
//
// バッチ実行(Pythonのunity_bridge.pyが呼ぶ):
//   Unity.exe -batchmode -projectPath <proj> -executeMethod MVL.BatchEntry.Run
//     -sceneJson <path/to/scene.json> -outDir <path/to/capture_dir> -quit -logFile <log>
//
// エディタ手動実行(デバッグ用): メニュー MVL > Build From scene_example.json
//
// 依存パッケージ(Package Managerで導入):
//   - com.unity.cloud.gltfast(GLBインポート)
//   - UnityMeshSimplifier: git URL https://github.com/Whinarn/UnityMeshSimplifier.git
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;
using Debug = UnityEngine.Debug;

namespace MVL
{
    public static class BatchEntry
    {
        // バッチモードのエントリポイント
        public static void Run()
        {
            string sceneJson = GetArg("-sceneJson");
            string outDir = GetArg("-outDir");
            if (string.IsNullOrEmpty(sceneJson) || string.IsNullOrEmpty(outDir))
            {
                Debug.LogError("[MVL] -sceneJson と -outDir が必要です");
                EditorApplication.Exit(2);
                return;
            }
            bool fastIteration = HasArg("-fastIteration");
            bool detailCaptures = HasArg("-detailCaptures");
            bool uniformScale = HasArg("-uniformScale");
            int code = SceneBuilder.BuildAndCapture(
                sceneJson, outDir, fastIteration, detailCaptures, uniformScale);
            EditorApplication.Exit(code);
        }

        static string GetArg(string name)
        {
            var args = Environment.GetCommandLineArgs();
            for (int i = 0; i < args.Length - 1; i++)
                if (args[i] == name) return args[i + 1];
            return null;
        }

        static bool HasArg(string name)
        {
            foreach (var arg in Environment.GetCommandLineArgs())
                if (arg == name) return true;
            return false;
        }

        [MenuItem("MVL/Build From scene_example.json")]
        public static void RunFromMenu()
        {
            string path = EditorUtility.OpenFilePanel("scene JSON", "", "json");
            if (string.IsNullOrEmpty(path)) return;
            EditorPrefs.SetString("MVL_LastScenePath", path);   // ← 追加。選んだパスを覚える
            string outDir = Path.Combine(Path.GetDirectoryName(path), "capture");
            SceneBuilder.BuildAndCapture(path, outDir);
        }

        // 前回選んだシーンJSONを再構築(初回だけダイアログが出る)
        [MenuItem("MVL/Rebuild Last Scene %#r")]   // Ctrl+Shift+R
        public static void RebuildLast()
        {
            string path = EditorPrefs.GetString("MVL_LastScenePath", "");
            if (string.IsNullOrEmpty(path) || !File.Exists(path))
            { RunFromMenu(); return; }
            SceneBuilder.BuildAndCapture(path, Path.Combine(Path.GetDirectoryName(path), "capture"));
        }

        [MenuItem("MVL/Build LOD MVP (desk-chair-plant)")]
        public static void BuildLodMvp()
        {
            string projectRoot = Path.GetDirectoryName(Application.dataPath);
            string workspaceRoot = Path.GetDirectoryName(projectRoot);
            string path = Path.Combine(
                workspaceRoot, "mvl-skeleton", "scene", "scene_lod_mvp.json");
            if (!File.Exists(path))
            {
                Debug.LogError("[MVL][LOD] MVPシーンが見つかりません: " + path);
                return;
            }
            EditorPrefs.SetString("MVL_LastScenePath", path);
            SceneBuilder.BuildAndCapture(
                path, Path.Combine(Path.GetDirectoryName(path), "capture"));
        }
    }

    public static class SceneBuilder
    {
        // 全オブジェクトのメッシュ簡略化を一括で切り替える。
        // false: 元メッシュを維持（UV2生成とライトマップベイクは実行する）
        // true : TARGET_TRIS_PER_OBJECTを超えるメッシュを簡略化する
        const bool ENABLE_MESH_DECIMATION = false;
        const int TARGET_TRIS_PER_OBJECT = 40000; // 8月=PC撮影品質優先。Quest 2向けの15k締めは9月に実施
        // 保存する原画の解像度。VLM送信時の縮小はPython側で独立に設定する。
        const int CAPTURE_W = 1920, CAPTURE_H = 1080;

        public static int BuildAndCapture(string sceneJsonPath, string outDir,
                                          bool fastIteration = false,
                                          bool detailCaptures = false,
                                          bool uniformScale = false)
        {
            var report = new BuildReport();
            var totalSw = Stopwatch.StartNew();
            report.fast_iteration = fastIteration;
            report.scale_mode = uniformScale ? "uniform" : "per_axis";
            report.capture_width = CAPTURE_W;
            report.capture_height = CAPTURE_H;
            try
            {
                Directory.CreateDirectory(outDir);
                string json = File.ReadAllText(sceneJsonPath);
                var scene = JsonUtility.FromJson<SceneJson>(json);
                report.scene_id = scene.scene_id;
                string assetsDirAbs = Path.Combine(Path.GetDirectoryName(Path.GetFullPath(sceneJsonPath)), scene.assets_dir ?? "assets");

                // 1) 新規シーン
                var newScene = UnityEditor.SceneManagement.EditorSceneManager.NewScene(
                    UnityEditor.SceneManagement.NewSceneSetup.EmptyScene,
                    UnityEditor.SceneManagement.NewSceneMode.Single);

                // 2) 部屋の殻(L1簡易版: 床+壁4面+天井。8月はテンプレート箱、材質は9月に生成置換)
                BuildRoomShell(scene.room, sceneJsonPath, report);

                // 3) 照明(太陽=Mixed必須。C4の教訓: Realtimeのままだとベイクされない)
                SetupLighting(scene.room.lighting, fastIteration);

                // 4) GLBをAssets配下へコピー → glTFastインポート → 配置
                string importFolder = "Assets/MVLImported";
                if (!AssetDatabase.IsValidFolder(importFolder))
                    AssetDatabase.CreateFolder("Assets", "MVLImported");

                var geometrySw = Stopwatch.StartNew();
                foreach (var obj in scene.objects)
                {
                    var or = PlaceObject(obj, assetsDirAbs, importFolder,
                                         fastIteration, uniformScale);
                    if (or != null) report.objects.Add(or);
                }
                report.geometry_seconds = (float)geometrySw.Elapsed.TotalSeconds;
                 UnityEditor.SceneManagement.EditorSceneManager.SaveScene(
                 UnityEngine.SceneManagement.SceneManager.GetActiveScene(),
                    "Assets/MVL_Temp.unity");

                // 5) ライトマップベイク(同期)
                if (!fastIteration)
                {
                    var sw = Stopwatch.StartNew();
                    BakeLightmaps();
                    report.bake_seconds = (float)sw.Elapsed.TotalSeconds;
                }

                // 6) 8視点撮影(実測AABBを渡してカメラの家具メリ込みを回避)
                var captureSw = Stopwatch.StartNew();
                report.captures = CaptureViews(scene, outDir, report.objects);
                if (detailCaptures)
                {
                    var detailCaptureSw = Stopwatch.StartNew();
                    report.detail_captures = CaptureDetailViews(
                        scene, outDir, report.objects);
                    report.detail_capture_seconds =
                        (float)detailCaptureSw.Elapsed.TotalSeconds;
                }
                report.capture_seconds = (float)captureSw.Elapsed.TotalSeconds;

                // 6.5) カメラとベイク結果を含めた状態で再保存
                //      97行目の保存は配置直後なので、カメラもライトマップも入っていない。
                //      ここで保存し直すと、Unityで MVL_Temp.unity を開くだけで
                //      Gameビューに部屋が映り、そのまま歩き回れる。
                UnityEditor.SceneManagement.EditorSceneManager.SaveScene(
                    UnityEngine.SceneManagement.SceneManager.GetActiveScene(),
                    "Assets/MVL_Temp.unity");

                // 7) レポート出力
                report.total_seconds = (float)totalSw.Elapsed.TotalSeconds;
                WriteReport(report, outDir);
                string mode = fastIteration ? "高速" : "通常";
                Debug.Log($"[MVL] 完了({mode}): {report.captures.Count}枚撮影, " +
                          $"配置{report.geometry_seconds:F1}秒, " +
                          $"ベイク{report.bake_seconds:F1}秒, " +
                          $"撮影{report.capture_seconds:F1}秒, " +
                          $"詳細撮影{report.detail_capture_seconds:F1}秒");
                return 0;
            }
            catch (Exception e)
            {
                Debug.LogError("[MVL] 失敗: " + e);
                report.error = e.Message;
                try { WriteReport(report, outDir); } catch { }
                return 1;
            }
        }

        // ---------- 部屋の殻 ----------
        static void BuildRoomShell(Room room, string sceneJsonPath,
                                   BuildReport report)
        {
            float w = room.bounds.width, d = room.bounds.depth, h = room.bounds.height;
            var floorMat = MakeMat(new Color(0.55f, 0.42f, 0.28f)); // 仮: 木目調ブラウン
            var wallMat = MakeMat(new Color(0.93f, 0.91f, 0.86f));  // 仮: オフホワイト
            var ceilingMat = wallMat;
            var northMat = wallMat;
            var southMat = wallMat;
            var westMat = wallMat;
            var eastMat = wallMat;

            float tile = room.texture_tile_m > 0f ? room.texture_tile_m : 2.0f;
            if (room.texture_tile_m <= 0f)
                Debug.LogWarning("[MVL] texture_tile_m は正数である必要があります。既定値 2.0m を使います。");

            if (!string.IsNullOrWhiteSpace(room.floor_texture))
            {
                var texture = ImportShellTexture(
                    room.floor_texture, "floor", sceneJsonPath, out var assetPath);
                var tiling = new Vector2(w / tile, d / tile);
                floorMat = MakeTexturedMat(texture, tiling);
                AddShellTextureReport(report, "Floor", room.floor_texture,
                                      assetPath, tiling);
            }

            if (!string.IsNullOrWhiteSpace(room.ceiling_texture))
            {
                var texture = ImportShellTexture(
                    room.ceiling_texture, "ceiling", sceneJsonPath, out var assetPath);
                var tiling = new Vector2(w / tile, d / tile);
                ceilingMat = MakeTexturedMat(texture, tiling);
                AddShellTextureReport(report, "Ceiling", room.ceiling_texture,
                                      assetPath, tiling);
            }

            if (!string.IsNullOrWhiteSpace(room.wall_texture))
            {
                var texture = ImportShellTexture(
                    room.wall_texture, "wall", sceneJsonPath, out var assetPath);
                var northSouthTiling = new Vector2(w / tile, h / tile);
                var eastWestTiling = new Vector2(d / tile, h / tile);

                // 各壁を独立したマテリアルにして、向きごとの寸法を反映する。
                northMat = MakeTexturedMat(texture, northSouthTiling);
                southMat = MakeTexturedMat(texture, northSouthTiling);
                westMat = MakeTexturedMat(texture, eastWestTiling);
                eastMat = MakeTexturedMat(texture, eastWestTiling);
                AddShellTextureReport(report, "Wall_N", room.wall_texture,
                                      assetPath, northSouthTiling);
                AddShellTextureReport(report, "Wall_S", room.wall_texture,
                                      assetPath, northSouthTiling);
                AddShellTextureReport(report, "Wall_W", room.wall_texture,
                                      assetPath, eastWestTiling);
                AddShellTextureReport(report, "Wall_E", room.wall_texture,
                                      assetPath, eastWestTiling);
            }

            MakeBox("Floor", new Vector3(w / 2, -0.05f, d / 2), new Vector3(w, 0.1f, d), floorMat);
            MakeBox("Ceiling", new Vector3(w / 2, h + 0.05f, d / 2), new Vector3(w, 0.1f, d), ceilingMat);
            MakeBox("Wall_N", new Vector3(w / 2, h / 2, d + 0.05f), new Vector3(w, h, 0.1f), northMat);
            MakeBox("Wall_S", new Vector3(w / 2, h / 2, -0.05f), new Vector3(w, h, 0.1f), southMat);
            MakeBox("Wall_W", new Vector3(-0.05f, h / 2, d / 2), new Vector3(0.1f, h, d), westMat);
            MakeBox("Wall_E", new Vector3(w + 0.05f, h / 2, d / 2), new Vector3(0.1f, h, d), eastMat);
        }

        static Material MakeMat(Color c)
        {
            var shader = Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard");
            var m = new Material(shader);
            m.color = c;
            return m;
        }

        static Material MakeTexturedMat(Texture2D texture, Vector2 tiling)
        {
            var m = MakeMat(Color.white);
            string textureProperty = m.HasProperty("_BaseMap")
                ? "_BaseMap"
                : "_MainTex";
            m.SetTexture(textureProperty, texture);
            m.SetTextureScale(textureProperty, tiling);
            return m;
        }

        static Texture2D ImportShellTexture(string relativePath, string surface,
                                            string sceneJsonPath,
                                            out string assetPath)
        {
            if (Path.IsPathRooted(relativePath))
                throw new ArgumentException(
                    $"{surface}_texture は mvl-skeleton からの相対パスで指定してください: {relativePath}");

            string skeletonRoot = FindMvlSkeletonRoot(sceneJsonPath);
            string rootWithSeparator = skeletonRoot.TrimEnd(
                Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
                + Path.DirectorySeparatorChar;
            string sourcePath = Path.GetFullPath(Path.Combine(
                skeletonRoot,
                relativePath.Replace('/', Path.DirectorySeparatorChar)));
            if (!sourcePath.StartsWith(rootWithSeparator,
                                       StringComparison.OrdinalIgnoreCase))
                throw new ArgumentException(
                    $"{surface}_texture が mvl-skeleton の外を指しています: {relativePath}");
            if (!File.Exists(sourcePath))
                throw new FileNotFoundException(
                    $"{surface}_texture が見つかりません", sourcePath);

            EnsureAssetFolder("Assets/MVLGenerated");
            EnsureAssetFolder("Assets/MVLGenerated/Shell");
            string fileName = surface + "_" + Path.GetFileName(sourcePath);
            assetPath = "Assets/MVLGenerated/Shell/" + fileName;
            string destinationPath = Path.Combine(
                Application.dataPath, "MVLGenerated", "Shell", fileName);
            File.Copy(sourcePath, destinationPath, true);
            AssetDatabase.ImportAsset(
                assetPath,
                ImportAssetOptions.ForceSynchronousImport
                | ImportAssetOptions.ForceUpdate);

            var importer = AssetImporter.GetAtPath(assetPath) as TextureImporter;
            if (importer == null)
                throw new InvalidOperationException(
                    $"テクスチャとしてインポートできませんでした: {assetPath}");
            if (importer.wrapMode != TextureWrapMode.Repeat)
            {
                importer.wrapMode = TextureWrapMode.Repeat;
                importer.SaveAndReimport();
            }

            var texture = AssetDatabase.LoadAssetAtPath<Texture2D>(assetPath);
            if (texture == null)
                throw new InvalidOperationException(
                    $"テクスチャを読み込めませんでした: {assetPath}");
            return texture;
        }

        static string FindMvlSkeletonRoot(string sceneJsonPath)
        {
            var directory = new DirectoryInfo(
                Path.GetDirectoryName(Path.GetFullPath(sceneJsonPath)));
            while (directory != null)
            {
                if (string.Equals(directory.Name, "mvl-skeleton",
                                  StringComparison.OrdinalIgnoreCase))
                    return directory.FullName;
                directory = directory.Parent;
            }
            throw new DirectoryNotFoundException(
                "scene JSON は mvl-skeleton 配下に置いてください。");
        }

        static void EnsureAssetFolder(string assetPath)
        {
            if (AssetDatabase.IsValidFolder(assetPath)) return;
            string parent = Path.GetDirectoryName(assetPath).Replace('\\', '/');
            string folderName = Path.GetFileName(assetPath);
            EnsureAssetFolder(parent);
            AssetDatabase.CreateFolder(parent, folderName);
        }

        static void AddShellTextureReport(BuildReport report, string surface,
                                          string sourceImage, string assetPath,
                                          Vector2 tiling)
        {
            report.shell_textures.Add(new ShellTextureReport {
                surface = surface,
                source_image = sourceImage.Replace('\\', '/'),
                imported_asset = assetPath,
                tiling = new[] { tiling.x, tiling.y },
            });
        }

        static GameObject MakeBox(string name, Vector3 center, Vector3 size, Material mat)
        {
            var go = GameObject.CreatePrimitive(PrimitiveType.Cube);
            go.name = name;
            go.transform.position = center;
            go.transform.localScale = size;
            go.GetComponent<Renderer>().sharedMaterial = mat;
            GameObjectUtility.SetStaticEditorFlags(go, StaticEditorFlags.ContributeGI);
            return go;
        }

        // ---------- 照明 ----------
        static void SetupLighting(Lighting lighting, bool fastIteration)
        {
            var go = new GameObject("Sun");
            var light = go.AddComponent<Light>();
            light.type = LightType.Directional;
            light.lightmapBakeType = fastIteration
                ? LightmapBakeType.Realtime
                : LightmapBakeType.Mixed;
            var s = lighting?.sun;
            if (s != null)
            {
                if (s.rotation_euler_deg != null && s.rotation_euler_deg.Length >= 2)
                    go.transform.rotation = Quaternion.Euler(s.rotation_euler_deg[0], s.rotation_euler_deg[1],
                        s.rotation_euler_deg.Length > 2 ? s.rotation_euler_deg[2] : 0);
                light.intensity = s.intensity;
                if (ColorUtility.TryParseHtmlString("#" + (s.color_hex ?? "FFFFFF"), out var c)) light.color = c;
            }
            RenderSettings.ambientMode = AmbientMode.Flat;
            RenderSettings.ambientLight = Color.white * (lighting?.ambient_intensity ?? 1.0f) * 0.35f;
        }

        // ---------- 配置 ----------
        static ObjectReport PlaceObject(SceneObject obj, string assetsDirAbs,
                                        string importFolder, bool fastIteration,
                                        bool uniformScale)
        {
            string src = Path.Combine(assetsDirAbs, obj.asset);
            if (!File.Exists(src)) { Debug.LogWarning($"[MVL] GLBなし: {src}(スキップ)"); return null; }

            // Assets配下へコピー → glTFastのScriptedImporterが取り込む
            string dst = $"{importFolder}/{Path.GetFileName(obj.asset)}";
            File.Copy(src, dst, true);
            AssetDatabase.ImportAsset(dst, ImportAssetOptions.ForceSynchronousImport);
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(dst);
            if (prefab == null) { Debug.LogWarning($"[MVL] インポート失敗: {dst}"); return null; }

            var inst = (GameObject)UnityEngine.Object.Instantiate(prefab);
            inst.name = obj.id;

            // 比較実験では旧方式の一様スケールも選べる。既定は各軸スケール。
            var bounds = MeasureBounds(inst);
            if (obj.target_dimensions != null)
            {
                const float MinDimension = 1e-4f;
                if (uniformScale)
                {
                    float measured = bounds.size.y;
                    float target = obj.target_dimensions.height;
                    // ラグ等の薄物は高さ基準が不安定なので幅基準にする。
                    if (target < 0.1f)
                    {
                        measured = Mathf.Max(bounds.size.x, bounds.size.z);
                        target = Mathf.Max(obj.target_dimensions.width,
                                           obj.target_dimensions.depth);
                    }
                    if (measured > MinDimension && target > MinDimension)
                        inst.transform.localScale = Vector3.one *
                            (target / measured);
                }
                else
                {
                    var measured = bounds.size;
                    var target = obj.target_dimensions;
                    var scale = inst.transform.localScale;
                    if (measured.x > MinDimension && target.width > MinDimension)
                        scale.x *= target.width / measured.x;
                    if (measured.y > MinDimension && target.height > MinDimension)
                        scale.y *= target.height / measured.y;
                    if (measured.z > MinDimension && target.depth > MinDimension)
                        scale.z *= target.depth / measured.z;
                    inst.transform.localScale = scale;
                }
            }

            // 回転 → 底面中心をposition[x,z]、底面をposition[y]に合わせる
            inst.transform.rotation = Quaternion.Euler(0, obj.rotation_y_deg, 0);
            bounds = MeasureBounds(inst);
            var p = obj.position;
            var offset = new Vector3(p[0] - bounds.center.x, p[1] - bounds.min.y, p[2] - bounds.center.z);
            inst.transform.position += offset;

            // 高速モードは配置確認用。元メッシュのまま撮影し、UV2生成を省く。
            int before, after;
            AdaptiveLodResult lodResult = null;
            if (fastIteration)
            {
                before = CountTriangles(inst);
                after = before;
            }
            else if (AdaptiveLodBuilder.TryBuild(inst, obj, dst, out lodResult))
            {
                before = lodResult.sourceTriangles;
                after = lodResult.lodTriangles[0];
                GameObjectUtility.SetStaticEditorFlags(inst, StaticEditorFlags.ContributeGI);
                foreach (Transform t in inst.GetComponentsInChildren<Transform>(true))
                    GameObjectUtility.SetStaticEditorFlags(
                        t.gameObject, StaticEditorFlags.ContributeGI);
            }
            else
            {
                DecimateAndUnwrap(inst, out before, out after);
                GameObjectUtility.SetStaticEditorFlags(inst, StaticEditorFlags.ContributeGI);
                foreach (Transform t in inst.GetComponentsInChildren<Transform>(true))
                    GameObjectUtility.SetStaticEditorFlags(
                        t.gameObject, StaticEditorFlags.ContributeGI);
            }

            bounds = MeasureBounds(inst);
            return new ObjectReport
            {
                id = obj.id,
                aabb_min = new[] { bounds.min.x, bounds.min.y, bounds.min.z },
                aabb_max = new[] { bounds.max.x, bounds.max.y, bounds.max.z },
                triangle_count_before = before,
                triangle_count_after = after,
                mesh_profile = lodResult?.profile ?? AdaptiveLodBuilder.ResolveProfile(obj),
                lod_triangle_counts = lodResult?.lodTriangles,
                lod_cache_hits = lodResult?.cacheHits ?? 0,
                lod_cache_misses = lodResult?.cacheMisses ?? 0
            };
        }

        static Bounds MeasureBounds(GameObject go)
        {
            var rends = go.GetComponentsInChildren<Renderer>(true);
            if (rends.Length == 0) return new Bounds(go.transform.position, Vector3.zero);
            var b = rends[0].bounds;
            foreach (var r in rends) b.Encapsulate(r.bounds);
            return b;
        }

        static int CountTriangles(GameObject go)
        {
            int total = 0;
            foreach (var filter in go.GetComponentsInChildren<MeshFilter>(true))
                if (filter.sharedMesh != null)
                    total += filter.sharedMesh.triangles.Length / 3;
            return total;
        }

        static void DecimateAndUnwrap(GameObject go, out int trisBefore, out int trisAfter)
        {
            trisBefore = 0; trisAfter = 0;
            var filters = go.GetComponentsInChildren<MeshFilter>(true);
            int totalTris = 0;
            foreach (var f in filters) if (f.sharedMesh != null) totalTris += f.sharedMesh.triangles.Length / 3;
            trisBefore = totalTris;
            float quality = totalTris > TARGET_TRIS_PER_OBJECT ? (float)TARGET_TRIS_PER_OBJECT / totalTris : 1f;

            foreach (var f in filters)
            {
                if (f.sharedMesh == null) continue;
                Mesh mesh = f.sharedMesh;
                if (ENABLE_MESH_DECIMATION && quality < 1f)
                {
                    var simplifier = new UnityMeshSimplifier.MeshSimplifier();
                    simplifier.Initialize(mesh);
                    simplifier.SimplifyMesh(quality);
                    mesh = simplifier.ToMesh();
                    mesh.name = f.sharedMesh.name + "_dec";
                }
                else
                {
                    mesh = UnityEngine.Object.Instantiate(mesh); // 共有アセットを直接触らない
                }
                if (!ENABLE_MESH_DECIMATION || mesh.vertexCount <= 60000)
                    {
                        Unwrapping.GenerateSecondaryUVSet(mesh);
                    }
                    else
                    {
                        Debug.LogWarning($"[MVL] UV2スキップ(頂点{mesh.vertexCount}): {mesh.name} — 追加デシメーション");
                        var extra = new UnityMeshSimplifier.MeshSimplifier();
                        extra.Initialize(mesh);
                        extra.SimplifyMesh(50000f / mesh.vertexCount); // 頂点5万目安まで追加間引き
                        mesh = extra.ToMesh();
                        Unwrapping.GenerateSecondaryUVSet(mesh);
                    }
                f.sharedMesh = mesh;
                trisAfter += mesh.triangles.Length / 3;
            }
        }

        // ---------- ベイク ----------
        static void BakeLightmaps()
        {
            var ls = new LightingSettings
            {
                lightmapper = LightingSettings.Lightmapper.ProgressiveGPU,
                directSampleCount = 16,
                indirectSampleCount = 64,
                environmentSampleCount = 64,
                lightmapMaxSize = 1024,
                lightmapResolution = 12, // texels/unit — 品質と時間のトレードオフ(~1分/部屋狙い)
                ao = true
            };
            Lightmapping.lightingSettings = ls;
            bool ok = Lightmapping.Bake(); // 同期ベイク
            if (!ok) Debug.LogWarning("[MVL] ベイクが失敗(照明なしで続行)");
        }

        // ---------- 撮影 ----------
        // カメラ位置が家具のAABB内にあれば、部屋中心方向へ逃がす(view_04の本棚メリ込み対策)
        static Vector3 AvoidObstacles(Vector3 pos, List<ObjectReport> objs, Vector3 roomCenter)
        {
            if (objs == null) return pos;
            for (int iter = 0; iter < 20; iter++)
            {
                bool inside = false;
                foreach (var o in objs)
                {
                    if (o.aabb_min == null || o.aabb_max == null) continue;
                    if (pos.x > o.aabb_min[0] - 0.15f && pos.x < o.aabb_max[0] + 0.15f &&
                        pos.y > o.aabb_min[1] - 0.05f && pos.y < o.aabb_max[1] + 0.05f &&
                        pos.z > o.aabb_min[2] - 0.15f && pos.z < o.aabb_max[2] + 0.15f)
                    { inside = true; break; }
                }
                if (!inside) return pos;
                var dir = roomCenter - pos; dir.y = 0;
                if (dir.sqrMagnitude < 1e-4f) dir = Vector3.forward;
                pos += dir.normalized * 0.25f;
            }
            return pos;
        }

        static List<string> CaptureViews(SceneJson scene, string outDir, List<ObjectReport> placed)
        {
            var files = new List<string>();
            float w = scene.room.bounds.width, d = scene.room.bounds.depth, h = scene.room.bounds.height;
            var center = new Vector3(w / 2, 1.2f, d / 2);
            const float EYE = 1.6f; // 目線高さ
            const float INSET = 0.45f;

            var poses = new List<(Vector3 pos, Vector3 lookAt)>();
            // 入口から
            var e = scene.room.entrance;
            var ePos = e != null && e.position != null && e.position.Length >= 2
                ? new Vector3(e.position[0], EYE, e.position[1]) : new Vector3(w / 2, EYE, INSET);
            poses.Add((ePos, center));
            // 4隅から中心へ
            poses.Add((new Vector3(INSET, EYE, INSET), center));
            poses.Add((new Vector3(w - INSET, EYE, INSET), center));
            poses.Add((new Vector3(INSET, EYE, d - INSET), center));
            poses.Add((new Vector3(w - INSET, EYE, d - INSET), center));
            // 主要オブジェクト2つの近接(検査用クローズアップ)
            var targets = CloseupTargets(scene, 2);
            foreach (var t in targets)
            {
                var dir = (new Vector3(w / 2, 0, d / 2) - new Vector3(t.x, 0, t.z)).normalized;
                if (dir.sqrMagnitude < 1e-4f) dir = Vector3.forward;
                poses.Add((t + dir * 1.3f + Vector3.up * (EYE - t.y), t));
            }
            // 俯瞰(デバッグ用: 配置関係の検査に有効 — Blender実験で実証済み)
            poses.Add((new Vector3(w / 2, h - 0.1f, d / 2), new Vector3(w / 2, 0, d / 2 + 0.01f)));

            var camGo = new GameObject("CaptureCam");
            var cam = camGo.AddComponent<Camera>();
            cam.fieldOfView = 75f; // 垂直FOV(水平換算で約90°)
            cam.nearClipPlane = 0.05f;

            var rt = new RenderTexture(CAPTURE_W, CAPTURE_H, 24);
            var tex = new Texture2D(CAPTURE_W, CAPTURE_H, TextureFormat.RGB24, false);

            // ウォームアップ: ベイク直後の1発目は古い環境情報を掴むことがあるので捨てレンダリング
            cam.transform.position = center + Vector3.up;
            cam.transform.LookAt(center);
            cam.targetTexture = rt;
            cam.Render();

            for (int i = 0; i < poses.Count && i < 8; i++)
            {
                cam.transform.position = AvoidObstacles(poses[i].pos, placed, center);
                cam.transform.LookAt(poses[i].lookAt);
                cam.targetTexture = rt;
                cam.Render();
                RenderTexture.active = rt;
                tex.ReadPixels(new Rect(0, 0, CAPTURE_W, CAPTURE_H), 0, 0);
                tex.Apply();
                string file = Path.Combine(outDir, $"view_{i:D2}.png");
                File.WriteAllBytes(file, tex.EncodeToPNG());
                files.Add(Path.GetFileName(file));
            }
            RenderTexture.active = null;
            cam.targetTexture = null;
            UnityEngine.Object.DestroyImmediate(rt);
            // カメラは削除せず入口視点に残す(Gameビューに部屋が映る/"No cameras rendering"対策)
            camGo.name = "Main Camera";
            camGo.tag = "MainCamera";
            cam.transform.position = AvoidObstacles(poses[0].pos, placed, center);
            cam.transform.LookAt(poses[0].lookAt);
            if (camGo.GetComponent<FlyCamera>() == null)
                camGo.AddComponent<FlyCamera>(); // Playモードで歩き回れるように
            return files;
        }

        static List<Vector3> CloseupTargets(SceneJson scene, int n)
        {
            var list = new List<(float vol, Vector3 c)>();
            foreach (var o in scene.objects)
            {
                if (o.target_dimensions == null || o.position == null) continue;
                float vol = o.target_dimensions.width * o.target_dimensions.height * o.target_dimensions.depth;
                list.Add((vol, new Vector3(o.position[0], o.position[1] + o.target_dimensions.height * 0.6f, o.position[2])));
            }
            list.Sort((a, b) => b.vol.CompareTo(a.vol));
            var result = new List<Vector3>();
            for (int i = 0; i < Mathf.Min(n, list.Count); i++) result.Add(list[i].c);
            return result;
        }

        static List<DetailCaptureReport> CaptureDetailViews(
            SceneJson scene, string outDir, List<ObjectReport> placed)
        {
            var results = new List<DetailCaptureReport>();
            if (scene.objects == null || placed == null) return results;

            var reports = new Dictionary<string, ObjectReport>();
            foreach (var report in placed)
                if (report != null && !string.IsNullOrEmpty(report.id))
                    reports[report.id] = report;

            float w = scene.room.bounds.width;
            float d = scene.room.bounds.depth;
            float h = scene.room.bounds.height;
            var roomCenter = new Vector3(w / 2, 1.2f, d / 2);
            var detailRoot = Path.Combine(outDir, "detail");
            Directory.CreateDirectory(detailRoot);

            var camGo = new GameObject("DetailCaptureCam");
            var cam = camGo.AddComponent<Camera>();
            cam.fieldOfView = 55f;
            cam.nearClipPlane = 0.03f;
            var rt = new RenderTexture(CAPTURE_W, CAPTURE_H, 24);
            var tex = new Texture2D(
                CAPTURE_W, CAPTURE_H, TextureFormat.RGB24, false);
            cam.targetTexture = rt;

            foreach (var obj in scene.objects)
            {
                if (obj == null || string.IsNullOrEmpty(obj.id)
                    || !reports.TryGetValue(obj.id, out var report)
                    || report.aabb_min == null || report.aabb_max == null)
                    continue;

                var mn = new Vector3(
                    report.aabb_min[0], report.aabb_min[1], report.aabb_min[2]);
                var mx = new Vector3(
                    report.aabb_max[0], report.aabb_max[1], report.aabb_max[2]);
                var center = (mn + mx) * 0.5f;
                var size = mx - mn;
                float radius = Mathf.Max(size.x, Mathf.Max(size.y, size.z));
                float distance = Mathf.Clamp(radius * 2.2f, 1.15f, 2.8f);

                // 壁際の物体でも最初の画像は必ず部屋側から見る。残り2枚は
                // 左右55度に振り、正面・背面・接地面の手掛かりを増やす。
                var inward = roomCenter - center;
                inward.y = 0;
                if (inward.sqrMagnitude < 1e-4f) inward = Vector3.back;
                inward.Normalize();
                var directions = new[] {
                    inward,
                    Quaternion.Euler(0, 55, 0) * inward,
                    Quaternion.Euler(0, -55, 0) * inward,
                };

                string safeId = SafeFileName(obj.id);
                string objectDir = Path.Combine(detailRoot, safeId);
                Directory.CreateDirectory(objectDir);
                var detail = new DetailCaptureReport {
                    object_id = obj.id,
                    object_class = obj.@class,
                };
                AddRelatedId(detail.related_ids, obj.rests_on);
                AddRelatedId(detail.related_ids, obj.faces);
                if (obj.near != null) AddRelatedId(
                    detail.related_ids, obj.near.target);

                for (int i = 0; i < directions.Length; i++)
                {
                    var pos = center + directions[i] * distance;
                    pos.y = Mathf.Clamp(
                        center.y + Mathf.Max(0.18f, size.y * 0.22f),
                        0.25f, h - 0.15f);
                    pos.x = Mathf.Clamp(pos.x, 0.12f, w - 0.12f);
                    pos.z = Mathf.Clamp(pos.z, 0.12f, d - 0.12f);
                    cam.transform.position = AvoidObstacles(
                        pos, placed, roomCenter);
                    cam.transform.LookAt(center);
                    cam.Render();
                    RenderTexture.active = rt;
                    tex.ReadPixels(
                        new Rect(0, 0, CAPTURE_W, CAPTURE_H), 0, 0);
                    tex.Apply();
                    string file = Path.Combine(objectDir, $"view_{i:D2}.png");
                    File.WriteAllBytes(file, tex.EncodeToPNG());
                    detail.files.Add(Path.Combine(
                        "detail", safeId, $"view_{i:D2}.png"));
                }
                results.Add(detail);
            }

            RenderTexture.active = null;
            cam.targetTexture = null;
            UnityEngine.Object.DestroyImmediate(rt);
            UnityEngine.Object.DestroyImmediate(camGo);
            return results;
        }

        static string SafeFileName(string value)
        {
            foreach (char c in Path.GetInvalidFileNameChars())
                value = value.Replace(c, '_');
            return value;
        }

        static void AddRelatedId(List<string> values, string value)
        {
            if (!string.IsNullOrEmpty(value) && !values.Contains(value))
                values.Add(value);
        }

        static void WriteReport(BuildReport report, string outDir)
        {
            Directory.CreateDirectory(outDir);
            File.WriteAllText(Path.Combine(outDir, "report.json"), JsonUtility.ToJson(report, true));
        }
    }
}
