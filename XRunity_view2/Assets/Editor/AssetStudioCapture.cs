// AssetStudioCapture.cs — GLB単体を固定条件で8方向撮影する。
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using Debug = UnityEngine.Debug;

namespace MVL
{
    public static class AssetStudioCapture
    {
        const string ImportFolder = "Assets/MVLStudioImported";
        const string LastManifestKey = "MVL_StudioCapture_LastManifest";
        const string LastOutputKey = "MVL_StudioCapture_LastOutput";

        [Serializable]
        sealed class StudioManifest
        {
            public string assets_dir = null;
            public string[] assets = null;
            public CaptureSettings capture;
            public MaterialOverride[] material_overrides = null;
        }

        [Serializable]
        sealed class CaptureSettings
        {
            public int width = 1024;
            public int height = 1024;
            public float margin = 1.15f;
            public float elevation_deg = 25f;
        }

        [Serializable]
        sealed class MaterialOverride
        {
            public string asset = null;
            public string label = null;
            public string material = null;
            public string base_color_texture = null;
        }

        [Serializable]
        sealed class CaptureReport
        {
            public bool success;
            public string manifest;
            public string assets_dir;
            public int width;
            public int height;
            public float margin;
            public float elevation_deg;
            public string background = "linear RGB (0.5, 0.5, 0.5)";
            public string lighting = "Directional Light 1.4 at camera-relative Euler(20,30,0) + flat ambient 0.35";
            public string reflection = "uniform linear RGB (0.5, 0.5, 0.5) cubemap, intensity 0.35";
            public string mask = "white unlit asset on black background";
            public float total_seconds;
            public string error;
            public List<AssetReport> assets = new List<AssetReport>();
        }

        [Serializable]
        sealed class AssetReport
        {
            public string asset;
            public string output_folder;
            public float[] bounding_box_size;
            public float orthographic_size;
            public string material_override_label;
            public string material_override_path;
            public string base_color_texture_override_path;
            public int[] base_color_texture_override_size;
            public float capture_seconds;
            public string[] files;
            public string[] mask_files;
            public ViewReport[] views;
        }

        [Serializable]
        sealed class ViewReport
        {
            public string file;
            public string mask_file;
            public float azimuth_deg;
            public float elevation_deg;
        }

        sealed class CaptureTask
        {
            public string asset;
            public string label;
            public string material;
            public string baseColorTexture;
        }

        /// <summary>
        /// Batch entry point:
        /// Unity -batchmode -executeMethod MVL.AssetStudioCapture.Run
        ///       -manifest path -out directory
        /// </summary>
        public static void Run()
        {
            string manifest = GetArg("-manifest");
            string outDir = GetArg("-out");
            if (string.IsNullOrEmpty(manifest) || string.IsNullOrEmpty(outDir))
            {
                Debug.LogError("[MVL][Studio] -manifest と -out が必要です");
                if (Application.isBatchMode) EditorApplication.Exit(2);
                return;
            }

            int code = BuildAndCapture(manifest, outDir);
            if (Application.isBatchMode) EditorApplication.Exit(code);
        }

        [MenuItem("MVL/Studio Capture (manifest)")]
        public static void RunFromMenu()
        {
            string previousManifest = EditorPrefs.GetString(LastManifestKey, "");
            string initialDir = File.Exists(previousManifest)
                ? Path.GetDirectoryName(previousManifest)
                : "";
            string manifest = EditorUtility.OpenFilePanel(
                "Studio Capture manifest", initialDir, "json");
            if (string.IsNullOrEmpty(manifest)) return;

            string previousOutput = EditorPrefs.GetString(
                LastOutputKey, Path.Combine(Path.GetDirectoryName(manifest), "studio_capture"));
            string outDir = EditorUtility.OpenFolderPanel(
                "Studio Capture output", previousOutput, "");
            if (string.IsNullOrEmpty(outDir)) return;
            if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo())
                return;

            EditorPrefs.SetString(LastManifestKey, manifest);
            EditorPrefs.SetString(LastOutputKey, outDir);
            int code = BuildAndCapture(manifest, outDir);
            if (code == 0)
                EditorUtility.DisplayDialog(
                    "Studio Capture", "撮影が完了しました。\n" + outDir, "OK");
            else
                EditorUtility.DisplayDialog(
                    "Studio Capture", "撮影に失敗しました。Console と report.json を確認してください。", "OK");
        }

        public static int BuildAndCapture(string manifestPath, string outDir)
        {
            var total = Stopwatch.StartNew();
            var report = new CaptureReport();
            SceneSetup[] previousScenes = Application.isBatchMode
                ? null
                : EditorSceneManager.GetSceneManagerSetup();
            try
            {
                manifestPath = Path.GetFullPath(manifestPath);
                outDir = Path.GetFullPath(outDir);
                report.manifest = manifestPath;
                Directory.CreateDirectory(outDir);

                if (!File.Exists(manifestPath))
                    throw new FileNotFoundException("manifest が見つかりません", manifestPath);

                var manifest = JsonUtility.FromJson<StudioManifest>(
                    File.ReadAllText(manifestPath));
                ValidateManifest(manifest);
                NormalizeCaptureSettings(manifest.capture);

                string assetsDir = ResolveAssetsDirectory(
                    manifestPath, manifest.assets_dir);
                report.assets_dir = assetsDir;
                report.width = manifest.capture.width;
                report.height = manifest.capture.height;
                report.margin = manifest.capture.margin;
                report.elevation_deg = manifest.capture.elevation_deg;

                EnsureImportFolder();
                var tasks = MakeTasks(manifest);
                foreach (var task in tasks)
                {
                    var item = CaptureOne(
                        task, assetsDir, outDir, manifest.capture);
                    report.assets.Add(item);
                    Debug.Log($"[MVL][Studio] 完了: {item.output_folder} " +
                              $"({item.capture_seconds:F2}s)");
                }

                report.success = true;
                return 0;
            }
            catch (Exception ex)
            {
                report.success = false;
                report.error = ex.ToString();
                Debug.LogError("[MVL][Studio] " + ex);
                return 1;
            }
            finally
            {
                total.Stop();
                report.total_seconds = (float)total.Elapsed.TotalSeconds;
                try
                {
                    Directory.CreateDirectory(Path.GetFullPath(outDir));
                    File.WriteAllText(
                        Path.Combine(Path.GetFullPath(outDir), "report.json"),
                        JsonUtility.ToJson(report, true));
                }
                catch (Exception writeError)
                {
                    Debug.LogError("[MVL][Studio] report.json を書けません: " + writeError);
                }
                if (previousScenes != null)
                    EditorSceneManager.RestoreSceneManagerSetup(previousScenes);
            }
        }

        static AssetReport CaptureOne(
            CaptureTask task, string assetsDir, string outRoot,
            CaptureSettings settings)
        {
            string source = Path.GetFullPath(Path.Combine(assetsDir, task.asset));
            if (!IsInsideDirectory(source, assetsDir) || !File.Exists(source))
                throw new FileNotFoundException("GLB が見つかりません", source);

            EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

            GameObject instance = null;
            GameObject cameraObject = null;
            GameObject lightObject = null;
            RenderTexture target = null;
            Texture2D pixels = null;
            Material maskMaterial = null;
            List<Material> transientMaterials = null;
            int[] overrideTextureSize = null;
            Cubemap neutralReflection = null;
            var previousReflectionMode = RenderSettings.defaultReflectionMode;
            Texture previousCustomReflection = RenderSettings.customReflectionTexture;
            float previousReflectionIntensity = RenderSettings.reflectionIntensity;
            try
            {
                lightObject = ConfigureFixedEnvironment(out neutralReflection);
                instance = ImportAndInstantiate(source);
                if (!string.IsNullOrEmpty(task.material))
                    ApplyMaterialOverride(instance, task.material);
                else if (!string.IsNullOrEmpty(task.baseColorTexture))
                    transientMaterials = ApplyBaseColorTextureOverride(
                        instance, task.baseColorTexture, out overrideTextureSize);

                Bounds bounds = MeasureBounds(instance);
                if (bounds.size.sqrMagnitude < 1e-10f)
                    throw new InvalidOperationException(
                        "Renderer bounds が空です: " + task.asset);

                // 原点や床へ寄せず、AABB中心だけをワールド原点へ置く。
                // 背景以外の物体を作らないため、影は対象表面にだけ現れる。
                instance.transform.position -= bounds.center;
                bounds = MeasureBounds(instance);

                float longest = Mathf.Max(
                    bounds.size.x, Mathf.Max(bounds.size.y, bounds.size.z));
                float aspect = (float)settings.width / settings.height;
                float orthoSize = longest * settings.margin * 0.5f;
                if (aspect < 1f) orthoSize /= aspect;

                string stem = SafeFileName(Path.GetFileNameWithoutExtension(task.asset));
                string folderName = string.IsNullOrEmpty(task.label)
                    ? stem
                    : stem + "__" + SafeFileName(task.label);
                string outputDir = Path.Combine(outRoot, folderName);
                Directory.CreateDirectory(outputDir);
                foreach (string legacyName in new[] { "front.png", "side.png", "back.png" })
                {
                    string legacyPath = Path.Combine(outputDir, legacyName);
                    if (File.Exists(legacyPath)) File.Delete(legacyPath);
                }

                cameraObject = new GameObject("Studio Camera");
                var camera = cameraObject.AddComponent<Camera>();
                camera.orthographic = true;
                camera.orthographicSize = orthoSize;
                camera.aspect = aspect;
                camera.nearClipPlane = 0.01f;
                camera.clearFlags = CameraClearFlags.SolidColor;
                camera.backgroundColor = new Color(0.5f, 0.5f, 0.5f, 1f);
                camera.allowHDR = false;
                camera.allowMSAA = true;

                target = new RenderTexture(
                    settings.width, settings.height, 24, RenderTextureFormat.ARGB32);
                target.antiAliasing = 1;
                target.Create();
                pixels = new Texture2D(
                    settings.width, settings.height, TextureFormat.RGB24, false);
                camera.targetTexture = target;

                float distance = Mathf.Max(longest * 2f, 1f);
                camera.farClipPlane = distance * 3f + longest;
                var azimuths = new[] { 0f, 45f, 90f, 135f, 180f, 225f, 270f, 315f };
                var files = new string[azimuths.Length];
                var maskFiles = new string[azimuths.Length];
                var views = new ViewReport[azimuths.Length];
                maskMaterial = CreateMaskMaterial();
                var captureWatch = Stopwatch.StartNew();

                // URP/GLBの初回描画ではshaderの準備中で対象が写らないことがある。
                // 方位角0度と同じ条件で1枚捨て、準備完了後に8枚を保存する。
                Vector3 warmupDirection = OrbitDirection(
                    azimuths[0], settings.elevation_deg);
                camera.transform.position = bounds.center + warmupDirection * distance;
                camera.transform.LookAt(bounds.center, Vector3.up);
                AlignLightToCamera(lightObject, camera);
                camera.Render();

                for (int i = 0; i < azimuths.Length; i++)
                {
                    Vector3 direction = OrbitDirection(
                        azimuths[i], settings.elevation_deg);
                    camera.transform.position = bounds.center + direction * distance;
                    camera.transform.LookAt(bounds.center, Vector3.up);
                    AlignLightToCamera(lightObject, camera);
                    string file = $"azimuth_{azimuths[i]:000}.png";
                    string maskFile = $"azimuth_{azimuths[i]:000}_mask.png";
                    WritePng(camera, target, pixels,
                        Path.Combine(outputDir, file));
                    WriteMaskPng(instance, maskMaterial, camera, target, pixels,
                        Path.Combine(outputDir, maskFile));
                    files[i] = file;
                    maskFiles[i] = maskFile;
                    views[i] = new ViewReport {
                        file = file,
                        mask_file = maskFile,
                        azimuth_deg = azimuths[i],
                        elevation_deg = settings.elevation_deg
                    };
                }
                captureWatch.Stop();

                return new AssetReport
                {
                    asset = task.asset,
                    output_folder = folderName,
                    bounding_box_size = new[] {
                        bounds.size.x, bounds.size.y, bounds.size.z },
                    orthographic_size = orthoSize,
                    material_override_label = task.label,
                    material_override_path = task.material,
                    base_color_texture_override_path = task.baseColorTexture,
                    base_color_texture_override_size = overrideTextureSize,
                    capture_seconds = (float)captureWatch.Elapsed.TotalSeconds,
                    files = files,
                    mask_files = maskFiles,
                    views = views
                };
            }
            finally
            {
                RenderTexture.active = null;
                if (cameraObject != null)
                {
                    var camera = cameraObject.GetComponent<Camera>();
                    if (camera != null) camera.targetTexture = null;
                }
                if (target != null)
                {
                    target.Release();
                    UnityEngine.Object.DestroyImmediate(target);
                }
                if (pixels != null) UnityEngine.Object.DestroyImmediate(pixels);
                if (maskMaterial != null)
                    UnityEngine.Object.DestroyImmediate(maskMaterial);
                RenderSettings.defaultReflectionMode = previousReflectionMode;
                RenderSettings.customReflectionTexture = previousCustomReflection;
                RenderSettings.reflectionIntensity = previousReflectionIntensity;
                if (neutralReflection != null)
                    UnityEngine.Object.DestroyImmediate(neutralReflection);
                if (cameraObject != null) UnityEngine.Object.DestroyImmediate(cameraObject);
                if (lightObject != null) UnityEngine.Object.DestroyImmediate(lightObject);
                if (instance != null) UnityEngine.Object.DestroyImmediate(instance);
                if (transientMaterials != null)
                    foreach (var material in transientMaterials)
                        if (material != null)
                            UnityEngine.Object.DestroyImmediate(material);
            }
        }

        static GameObject ConfigureFixedEnvironment(out Cubemap neutralReflection)
        {
            RenderSettings.ambientMode = AmbientMode.Flat;
            RenderSettings.ambientLight = Color.white * 0.35f;
            RenderSettings.ambientIntensity = 1f;
            RenderSettings.skybox = null;
            RenderSettings.fog = false;

            neutralReflection = CreateNeutralReflectionCubemap();
            RenderSettings.defaultReflectionMode = DefaultReflectionMode.Custom;
            RenderSettings.customReflectionTexture = neutralReflection;
            RenderSettings.reflectionIntensity = 0.35f;

            var lightObject = new GameObject("Studio Directional Light");
            var light = lightObject.AddComponent<Light>();
            light.type = LightType.Directional;
            light.color = Color.white;
            light.intensity = 1.4f;
            light.shadows = LightShadows.Soft;
            return lightObject;
        }

        static Cubemap CreateNeutralReflectionCubemap()
        {
            const int size = 16;
            var cubemap = new Cubemap(size, TextureFormat.RGBA32, false, true)
            {
                name = "MVL Neutral Studio Reflection"
            };
            var pixels = new Color[size * size];
            var neutral = new Color(0.5f, 0.5f, 0.5f, 1f);
            for (int i = 0; i < pixels.Length; i++) pixels[i] = neutral;
            foreach (CubemapFace face in new[] {
                CubemapFace.PositiveX, CubemapFace.NegativeX,
                CubemapFace.PositiveY, CubemapFace.NegativeY,
                CubemapFace.PositiveZ, CubemapFace.NegativeZ })
            {
                cubemap.SetPixels(pixels, face);
            }
            cubemap.Apply(false, true);
            return cubemap;
        }

        static void AlignLightToCamera(GameObject lightObject, Camera camera)
        {
            // Directional Light の +Z は光線が進む向き。
            // カメラ基準で右下へ傾けると、見かけの光源は左上手前になる。
            // カメラの方位と一緒に回すことで、全8方向の相対照明を揃える。
            lightObject.transform.rotation =
                camera.transform.rotation * Quaternion.Euler(20f, 30f, 0f);
        }

        static Vector3 OrbitDirection(float azimuthDeg, float elevationDeg)
        {
            float elevationRad = elevationDeg * Mathf.Deg2Rad;
            Vector3 horizontal = Quaternion.Euler(0f, azimuthDeg, 0f)
                                 * Vector3.forward;
            return horizontal * Mathf.Cos(elevationRad)
                   + Vector3.up * Mathf.Sin(elevationRad);
        }

        static GameObject ImportAndInstantiate(string source)
        {
            string assetPath = ImportFolder + "/" + Path.GetFileName(source);
            string absoluteDestination = Path.Combine(
                Path.GetDirectoryName(Application.dataPath), assetPath);
            File.Copy(source, absoluteDestination, true);
            AssetDatabase.ImportAsset(
                assetPath, ImportAssetOptions.ForceSynchronousImport);
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(assetPath);
            if (prefab == null)
                throw new InvalidOperationException("GLB のインポートに失敗: " + source);
            var instance = (GameObject)UnityEngine.Object.Instantiate(prefab);
            instance.name = Path.GetFileNameWithoutExtension(source);
            return instance;
        }

        static void ApplyMaterialOverride(GameObject instance, string materialPath)
        {
            string path = materialPath.Replace('\\', '/');
            if (!path.StartsWith("Assets/", StringComparison.Ordinal))
                throw new ArgumentException(
                    "material は Assets/ から始まるUnityパスで指定してください: " +
                    materialPath);
            var material = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (material == null)
                throw new FileNotFoundException(
                    "material override が見つかりません", materialPath);

            int slots = 0;
            foreach (var renderer in instance.GetComponentsInChildren<Renderer>(true))
            {
                var replacements = new Material[renderer.sharedMaterials.Length];
                for (int i = 0; i < replacements.Length; i++)
                    replacements[i] = material;
                renderer.sharedMaterials = replacements;
                slots += replacements.Length;
            }
            if (slots == 0)
                throw new InvalidOperationException(
                    "material を適用できるRendererがありません: " + instance.name);
        }

        static List<Material> ApplyBaseColorTextureOverride(
            GameObject instance, string texturePath, out int[] textureSize)
        {
            string path = texturePath.Replace('\\', '/');
            if (!path.StartsWith("Assets/", StringComparison.Ordinal))
                throw new ArgumentException(
                    "base_color_texture は Assets/ から始まるUnityパスで指定してください: " +
                    texturePath);

            var importer = AssetImporter.GetAtPath(path) as TextureImporter;
            if (importer == null)
                throw new FileNotFoundException(
                    "baseColor texture importer が見つかりません", texturePath);
            bool reimport = false;
            if (importer.maxTextureSize < 4096)
            {
                importer.maxTextureSize = 4096;
                reimport = true;
            }
            if (!importer.sRGBTexture)
            {
                importer.sRGBTexture = true;
                reimport = true;
            }
            if (!importer.mipmapEnabled)
            {
                importer.mipmapEnabled = true;
                reimport = true;
            }
            if (reimport) importer.SaveAndReimport();

            var texture = AssetDatabase.LoadAssetAtPath<Texture2D>(path);
            if (texture == null)
                throw new FileNotFoundException(
                    "baseColor texture が見つかりません", texturePath);
            textureSize = new[] { texture.width, texture.height };
            if (texture.width < 4096 || texture.height < 4096)
                throw new InvalidOperationException(
                    "4倍baseColorがUnityで4096x4096として読み込まれていません: " +
                    texturePath + $" ({texture.width}x{texture.height})");

            var created = new List<Material>();
            int slots = 0;
            foreach (var renderer in instance.GetComponentsInChildren<Renderer>(true))
            {
                var originals = renderer.sharedMaterials;
                var replacements = new Material[originals.Length];
                for (int i = 0; i < originals.Length; i++)
                {
                    if (originals[i] == null)
                    {
                        replacements[i] = null;
                        continue;
                    }
                    var clone = new Material(originals[i])
                    {
                        name = originals[i].name + "__baseColorOverride"
                    };
                    bool assigned = false;
                    if (clone.HasProperty("_BaseMap"))
                    {
                        clone.SetTexture("_BaseMap", texture);
                        assigned = true;
                    }
                    if (clone.HasProperty("_MainTex"))
                    {
                        clone.SetTexture("_MainTex", texture);
                        assigned = true;
                    }
                    if (!assigned)
                        throw new InvalidOperationException(
                            "baseColorプロパティがないMaterialです: " + originals[i].name);
                    replacements[i] = clone;
                    created.Add(clone);
                    slots++;
                }
                renderer.sharedMaterials = replacements;
            }
            if (slots == 0)
                throw new InvalidOperationException(
                    "baseColorを差し替えられるMaterialがありません: " + instance.name);
            return created;
        }

        static void WritePng(
            Camera camera, RenderTexture target, Texture2D pixels, string path)
        {
            camera.Render();
            var previous = RenderTexture.active;
            RenderTexture.active = target;
            pixels.ReadPixels(
                new Rect(0, 0, target.width, target.height), 0, 0, false);
            pixels.Apply(false, false);
            File.WriteAllBytes(path, pixels.EncodeToPNG());
            RenderTexture.active = previous;
        }

        static Material CreateMaskMaterial()
        {
            Shader shader = Shader.Find("Universal Render Pipeline/Unlit");
            if (shader == null) shader = Shader.Find("Unlit/Color");
            if (shader == null)
                throw new InvalidOperationException(
                    "白黒マスク用のUnlit shaderが見つかりません");

            var material = new Material(shader) { name = "MVL Studio Mask" };
            if (material.HasProperty("_BaseColor"))
                material.SetColor("_BaseColor", Color.white);
            if (material.HasProperty("_Color"))
                material.SetColor("_Color", Color.white);
            return material;
        }

        static void WriteMaskPng(
            GameObject instance, Material maskMaterial,
            Camera camera, RenderTexture target, Texture2D pixels, string path)
        {
            var originalBackground = camera.backgroundColor;
            var originals = new Dictionary<Renderer, Material[]>();
            try
            {
                camera.backgroundColor = Color.black;
                foreach (var renderer in instance.GetComponentsInChildren<Renderer>(true))
                {
                    var original = renderer.sharedMaterials;
                    originals[renderer] = original;
                    var replacements = new Material[original.Length];
                    for (int i = 0; i < replacements.Length; i++)
                        replacements[i] = maskMaterial;
                    renderer.sharedMaterials = replacements;
                }
                WritePng(camera, target, pixels, path);
            }
            finally
            {
                foreach (var item in originals)
                    if (item.Key != null) item.Key.sharedMaterials = item.Value;
                camera.backgroundColor = originalBackground;
            }
        }

        static Bounds MeasureBounds(GameObject instance)
        {
            var renderers = instance.GetComponentsInChildren<Renderer>(true);
            if (renderers.Length == 0)
                return new Bounds(instance.transform.position, Vector3.zero);
            var bounds = renderers[0].bounds;
            for (int i = 1; i < renderers.Length; i++)
                bounds.Encapsulate(renderers[i].bounds);
            return bounds;
        }

        static List<CaptureTask> MakeTasks(StudioManifest manifest)
        {
            var result = new List<CaptureTask>();
            foreach (string asset in manifest.assets)
            {
                bool hasOverrides = false;
                if (manifest.material_overrides != null)
                {
                    foreach (var item in manifest.material_overrides)
                    {
                        if (item == null || !AssetNamesEqual(item.asset, asset))
                            continue;
                        hasOverrides = true;
                        if (string.IsNullOrWhiteSpace(item.label))
                            throw new ArgumentException(
                                "material override の label が空です: " + asset);
                        bool hasMaterial = !string.IsNullOrWhiteSpace(item.material);
                        bool hasTexture = !string.IsNullOrWhiteSpace(
                            item.base_color_texture);
                        if (hasMaterial && hasTexture)
                            throw new ArgumentException(
                                "material と base_color_texture は同時指定できません: " +
                                asset);
                        result.Add(new CaptureTask {
                            asset = asset,
                            label = item.label.Trim(),
                            material = hasMaterial ? item.material.Trim() : null,
                            baseColorTexture = hasTexture
                                ? item.base_color_texture.Trim()
                                : null
                        });
                    }
                }
                if (!hasOverrides)
                    result.Add(new CaptureTask { asset = asset });
            }

            var folders = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var item in result)
            {
                string folder = SafeFileName(Path.GetFileNameWithoutExtension(item.asset));
                if (!string.IsNullOrEmpty(item.label))
                    folder += "__" + SafeFileName(item.label);
                if (!folders.Add(folder))
                    throw new ArgumentException("出力フォルダが重複します: " + folder);
            }
            return result;
        }

        static void ValidateManifest(StudioManifest manifest)
        {
            if (manifest == null)
                throw new ArgumentException("manifest JSONを読み取れません");
            if (string.IsNullOrWhiteSpace(manifest.assets_dir))
                throw new ArgumentException("assets_dir が必要です");
            if (manifest.assets == null || manifest.assets.Length == 0)
                throw new ArgumentException("assets が1件以上必要です");
            foreach (string asset in manifest.assets)
            {
                if (string.IsNullOrWhiteSpace(asset))
                    throw new ArgumentException("assets に空の値があります");
                if (!string.Equals(
                    Path.GetExtension(asset), ".glb", StringComparison.OrdinalIgnoreCase))
                    throw new ArgumentException("GLB以外は撮影できません: " + asset);
            }
            if (manifest.capture == null) manifest.capture = new CaptureSettings();
        }

        static void NormalizeCaptureSettings(CaptureSettings settings)
        {
            if (settings.width <= 0) settings.width = 1024;
            if (settings.height <= 0) settings.height = 1024;
            if (settings.margin <= 0f) settings.margin = 1.15f;
            if (settings.width > 8192 || settings.height > 8192)
                throw new ArgumentOutOfRangeException(
                    "capture", "width/height は8192以下にしてください");
            if (settings.margin < 1f)
                throw new ArgumentOutOfRangeException(
                    "capture.margin", "margin は1.0以上にしてください");
            if (settings.elevation_deg <= -89f || settings.elevation_deg >= 89f)
                throw new ArgumentOutOfRangeException(
                    "capture.elevation_deg",
                    "elevation_deg は-89より大きく89より小さくしてください");
        }

        static string ResolveAssetsDirectory(string manifestPath, string value)
        {
            if (Path.IsPathRooted(value))
            {
                string absolute = Path.GetFullPath(value);
                if (Directory.Exists(absolute)) return absolute;
            }

            string manifestRelative = Path.GetFullPath(Path.Combine(
                Path.GetDirectoryName(manifestPath), value));
            if (Directory.Exists(manifestRelative)) return manifestRelative;

            string projectRoot = Path.GetDirectoryName(Application.dataPath);
            string workspaceRoot = Path.GetDirectoryName(projectRoot);
            string workspaceRelative = Path.GetFullPath(Path.Combine(workspaceRoot, value));
            if (Directory.Exists(workspaceRelative)) return workspaceRelative;

            string skeletonRelative = Path.GetFullPath(Path.Combine(
                workspaceRoot, "mvl-skeleton", value));
            if (Directory.Exists(skeletonRelative)) return skeletonRelative;

            throw new DirectoryNotFoundException(
                "assets_dir が見つかりません: " + value);
        }

        static bool AssetNamesEqual(string left, string right)
        {
            return string.Equals(
                (left ?? "").Replace('\\', '/'),
                (right ?? "").Replace('\\', '/'),
                StringComparison.OrdinalIgnoreCase);
        }

        static void EnsureImportFolder()
        {
            string projectRoot = Path.GetDirectoryName(Application.dataPath);
            Directory.CreateDirectory(Path.Combine(projectRoot, ImportFolder));
            AssetDatabase.Refresh();
        }

        static bool IsInsideDirectory(string path, string directory)
        {
            string root = Path.GetFullPath(directory)
                .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
                + Path.DirectorySeparatorChar;
            return Path.GetFullPath(path).StartsWith(
                root, StringComparison.OrdinalIgnoreCase);
        }

        static string SafeFileName(string value)
        {
            if (string.IsNullOrWhiteSpace(value)) return "unnamed";
            foreach (char c in Path.GetInvalidFileNameChars())
                value = value.Replace(c, '_');
            value = value.Trim().TrimEnd('.');
            return string.IsNullOrEmpty(value) ? "unnamed" : value;
        }

        static string GetArg(string name)
        {
            string[] args = Environment.GetCommandLineArgs();
            for (int i = 0; i < args.Length - 1; i++)
                if (string.Equals(args[i], name, StringComparison.OrdinalIgnoreCase))
                    return args[i + 1];
            return null;
        }
    }
}
