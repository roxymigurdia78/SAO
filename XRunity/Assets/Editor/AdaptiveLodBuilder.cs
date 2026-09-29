// AdaptiveLodBuilder.cs — AI分類済みプロファイルからUnity LODGroupを構築する。
// 初回にUV2付きメッシュと簡略化メッシュをAssetsへ保存し、以後は再利用する。
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using UnityEditor;
using UnityEngine;
using Debug = UnityEngine.Debug;

namespace MVL
{
    public sealed class AdaptiveLodResult
    {
        public string profile;
        public int sourceTriangles;
        public int[] lodTriangles;
        public int cacheHits;
        public int cacheMisses;
    }

    public static class AdaptiveLodBuilder
    {
        const string CacheRoot = "Assets/MVLGenerated/LOD";

        sealed class LodProfile
        {
            public string name;
            public int[] triangleTargets;
            public float[] screenHeights;
        }

        public static string ResolveProfile(SceneObject obj)
        {
            string requested = (obj.mesh_profile ?? "").Trim().ToLowerInvariant();
            if (requested == "fragile" || requested == "standard" ||
                requested == "robust") return requested;
            if (requested == "original" || requested == "none") return "original";

            // AI固定分類の既定値。JSONのmesh_profileで個別上書きできる。
            string cls = (obj.@class ?? "").Trim().ToLowerInvariant();
            if (cls.StartsWith("f_")) cls = cls.Substring(2);

            switch (cls)
            {
                // 細い部品・曲面・有機的な輪郭があり、削減に弱い。
                case "chair":
                case "plant":
                case "lamp":
                case "floor_lamp":
                case "lantern":
                case "backpack":
                case "monitor":
                case "mug":
                case "pen_holder":
                case "crystal":
                case "orb":
                    return "fragile";

                // 曲面や細部はあるが、画面上の占有率に応じて削減しやすい。
                case "trash_bin":
                case "laptop":
                case "stool":
                    return "standard";

                // 箱型・平面中心でシルエットが崩れにくい。
                case "desk":
                case "bookshelf":
                case "shelf":
                case "cabinet":
                case "rug":
                case "books":
                case "printer":
                case "table":
                    return "robust";
            }
            return "original";
        }

        public static bool TryBuild(GameObject root, SceneObject obj,
                                    string sourceAssetPath,
                                    out AdaptiveLodResult result)
        {
            result = null;
            var profile = GetProfile(ResolveProfile(obj));
            if (profile == null) return false;

            var sourceFilters = root.GetComponentsInChildren<MeshFilter>(true);
            if (sourceFilters.Length == 0) return false;
            var sourceRenderers = root.GetComponentsInChildren<Renderer>(true);

            int sourceTriangles = CountTriangles(sourceFilters);
            var levelObjects = new[] {
                root,
                UnityEngine.Object.Instantiate(root),
                UnityEngine.Object.Instantiate(root),
            };
            levelObjects[1].name = root.name + "_LOD1";
            levelObjects[2].name = root.name + "_LOD2";

            // 複製側は描画専用。Colliderまで複製すると物理判定が三重になる。
            for (int level = 1; level < levelObjects.Length; level++)
            {
                foreach (var collider in levelObjects[level].GetComponentsInChildren<Collider>(true))
                    UnityEngine.Object.DestroyImmediate(collider);
                levelObjects[level].transform.SetParent(root.transform, true);
            }

            var filtersByLevel = new MeshFilter[levelObjects.Length][];
            filtersByLevel[0] = sourceFilters;
            for (int level = 1; level < levelObjects.Length; level++)
                filtersByLevel[level] = levelObjects[level].GetComponentsInChildren<MeshFilter>(true);

            for (int level = 1; level < filtersByLevel.Length; level++)
                if (filtersByLevel[level].Length != sourceFilters.Length)
                    throw new InvalidOperationException(
                        $"LOD複製後のMeshFilter数が一致しません: {obj.id}");

            EnsureCacheFolders();
            string dependencyHash = AssetDatabase.GetAssetDependencyHash(sourceAssetPath).ToString();
            if (dependencyHash.Length > 12) dependencyHash = dependencyHash.Substring(0, 12);
            string assetStem = SafeName(Path.GetFileNameWithoutExtension(obj.asset));
            int cacheHits = 0, cacheMisses = 0;
            var lodTriangleCounts = new int[levelObjects.Length];

            for (int filterIndex = 0; filterIndex < sourceFilters.Length; filterIndex++)
            {
                Mesh source = sourceFilters[filterIndex].sharedMesh;
                if (source == null) continue;

                Mesh uvBase = LoadOrCreateUvBase(
                    source, assetStem, dependencyHash, filterIndex,
                    ref cacheHits, ref cacheMisses);

                for (int level = 0; level < levelObjects.Length; level++)
                {
                    Mesh levelMesh = LoadOrCreateLevelMesh(
                        uvBase, assetStem, dependencyHash, filterIndex,
                        profile.triangleTargets[level], sourceTriangles,
                        ref cacheHits, ref cacheMisses);
                    filtersByLevel[level][filterIndex].sharedMesh = levelMesh;
                    lodTriangleCounts[level] += levelMesh.triangles.Length / 3;
                }
            }

            // UnityEngine.Objectのnullは演算子オーバーロードされているため、
            // ?? ではMissingComponentを正しく判定できない。
            var lodGroup = root.GetComponent<LODGroup>();
            if (lodGroup == null)
                lodGroup = root.AddComponent<LODGroup>();
            // 切替が目視できないことをMVPで確認できたため、二重描画になる
            // CrossFadeは使わない。切替付近のフレーム落ちを優先して避ける。
            lodGroup.fadeMode = LODFadeMode.None;
            lodGroup.animateCrossFading = false;
            var lods = new LOD[levelObjects.Length];
            for (int level = 0; level < levelObjects.Length; level++)
            {
                var renderers = level == 0
                    ? sourceRenderers
                    : levelObjects[level].GetComponentsInChildren<Renderer>(true);
                lods[level] = new LOD(profile.screenHeights[level], renderers);
            }
            lodGroup.SetLODs(lods);
            lodGroup.RecalculateBounds();
            AssetDatabase.SaveAssets();

            result = new AdaptiveLodResult {
                profile = profile.name,
                sourceTriangles = sourceTriangles,
                lodTriangles = lodTriangleCounts,
                cacheHits = cacheHits,
                cacheMisses = cacheMisses,
            };
            Debug.Log($"[MVL][LOD] {obj.id}: {profile.name}, " +
                      $"tris={string.Join("/", lodTriangleCounts)}, " +
                      $"cache hit={cacheHits}, miss={cacheMisses}");
            return true;
        }

        static LodProfile GetProfile(string name)
        {
            if (name == "fragile")
                return new LodProfile {
                    name = "fragile",
                    triangleTargets = new[] { int.MaxValue, 100000, 60000 },
                    screenHeights = new[] { 0.15f, 0.05f, 0.015f },
                };
            if (name == "standard")
                return new LodProfile {
                    name = "standard",
                    triangleTargets = new[] { int.MaxValue, 60000, 30000 },
                    screenHeights = new[] { 0.15f, 0.05f, 0.015f },
                };
            if (name == "robust")
                return new LodProfile {
                    name = "robust",
                    triangleTargets = new[] { int.MaxValue, 40000, 20000 },
                    screenHeights = new[] { 0.15f, 0.05f, 0.015f },
                };
            return null;
        }

        static Mesh LoadOrCreateUvBase(Mesh source, string stem, string hash,
                                       int filterIndex,
                                       ref int hits, ref int misses)
        {
            string path = $"{CacheRoot}/{stem}_{hash}_m{filterIndex}_uv2.asset";
            Mesh cached = AssetDatabase.LoadAssetAtPath<Mesh>(path);
            if (cached != null) { hits++; return cached; }

            misses++;
            var sw = Stopwatch.StartNew();
            Mesh mesh = UnityEngine.Object.Instantiate(source);
            mesh.name = source.name + "_uv2";
            if (mesh.uv2 == null || mesh.uv2.Length == 0)
            {
                // TRELLIS由来GLBのUV0はテクスチャアトラス用に展開済み。
                // これをUV2へ複製すれば、14万ポリゴンで数分～十数分かかる
                // GenerateSecondaryUVSetを毎アセット実行せずに済む。
                var primaryUv = mesh.uv;
                if (primaryUv != null && primaryUv.Length == mesh.vertexCount)
                {
                    mesh.uv2 = primaryUv;
                    Debug.Log($"[MVL][LOD] UV0をUV2へ再利用: {stem} " +
                              $"mesh#{filterIndex} ({source.triangles.Length / 3} tris)");
                }
                else
                {
                    Debug.Log($"[MVL][LOD] UV2生成開始(UV0なし): {stem} " +
                              $"mesh#{filterIndex} ({source.triangles.Length / 3} tris)");
                    Unwrapping.GenerateSecondaryUVSet(mesh);
                }
            }
            AssetDatabase.CreateAsset(mesh, path);
            Debug.Log($"[MVL][LOD] UV2生成完了: {stem} mesh#{filterIndex} " +
                      $"{sw.Elapsed.TotalSeconds:F1}秒");
            return mesh;
        }

        static Mesh LoadOrCreateLevelMesh(Mesh uvBase, string stem, string hash,
                                          int filterIndex, int targetTotal,
                                          int sourceTotal,
                                          ref int hits, ref int misses)
        {
            if (targetTotal == int.MaxValue || sourceTotal <= targetTotal)
                return uvBase;

            string path = $"{CacheRoot}/{stem}_{hash}_m{filterIndex}_{targetTotal}.asset";
            Mesh cached = AssetDatabase.LoadAssetAtPath<Mesh>(path);
            if (cached != null) { hits++; return cached; }

            misses++;
            float quality = Mathf.Clamp01((float)targetTotal / sourceTotal);
            var simplifier = new UnityMeshSimplifier.MeshSimplifier();
            simplifier.Initialize(uvBase);
            simplifier.SimplifyMesh(quality);
            Mesh mesh = simplifier.ToMesh();
            mesh.name = uvBase.name + "_lod_" + targetTotal;
            AssetDatabase.CreateAsset(mesh, path);
            return mesh;
        }

        static int CountTriangles(IEnumerable<MeshFilter> filters)
        {
            int total = 0;
            foreach (var filter in filters)
                if (filter.sharedMesh != null)
                    total += filter.sharedMesh.triangles.Length / 3;
            return total;
        }

        static void EnsureCacheFolders()
        {
            if (!AssetDatabase.IsValidFolder("Assets/MVLGenerated"))
                AssetDatabase.CreateFolder("Assets", "MVLGenerated");
            if (!AssetDatabase.IsValidFolder(CacheRoot))
                AssetDatabase.CreateFolder("Assets/MVLGenerated", "LOD");
        }

        static string SafeName(string value)
        {
            foreach (char c in Path.GetInvalidFileNameChars())
                value = value.Replace(c, '_');
            return value.Replace(' ', '_');
        }
    }
}
