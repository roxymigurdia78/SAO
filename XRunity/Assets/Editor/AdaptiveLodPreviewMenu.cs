// AdaptiveLodPreviewMenu.cs — 選択中オブジェクトのLODをSceneビューで強制表示する。
using UnityEditor;
using UnityEngine;

namespace MVL
{
    public static class AdaptiveLodPreviewMenu
    {
        [MenuItem("MVL/LOD Preview/Auto (Selected)")]
        static void Auto() => ForceSelected(-1);

        [MenuItem("MVL/LOD Preview/LOD 0 - Near (Selected)")]
        static void Lod0() => ForceSelected(0);

        [MenuItem("MVL/LOD Preview/LOD 1 - Middle (Selected)")]
        static void Lod1() => ForceSelected(1);

        [MenuItem("MVL/LOD Preview/LOD 2 - Far (Selected)")]
        static void Lod2() => ForceSelected(2);

        [MenuItem("MVL/LOD Preview/Auto (Selected)", true)]
        [MenuItem("MVL/LOD Preview/LOD 0 - Near (Selected)", true)]
        [MenuItem("MVL/LOD Preview/LOD 1 - Middle (Selected)", true)]
        [MenuItem("MVL/LOD Preview/LOD 2 - Far (Selected)", true)]
        static bool ValidateSelection()
        {
            return FindSelectedGroup() != null;
        }

        static void ForceSelected(int lodIndex)
        {
            var group = FindSelectedGroup();
            if (group == null)
            {
                Debug.LogWarning("[MVL][LOD] LODGroupを持つ物体を選択してください");
                return;
            }

            group.ForceLOD(lodIndex);
            SceneView.RepaintAll();
            string mode = lodIndex < 0 ? "Auto" : "LOD " + lodIndex;
            Debug.Log($"[MVL][LOD] {group.gameObject.name}: preview={mode}");
        }

        static LODGroup FindSelectedGroup()
        {
            if (Selection.activeGameObject == null) return null;
            return Selection.activeGameObject.GetComponentInParent<LODGroup>();
        }
    }
}
