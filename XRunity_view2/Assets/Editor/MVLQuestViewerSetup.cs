// MVLQuestViewerSetup.cs
//
// SceneBuilder が作った部屋（Assets/MVL_Temp.unity）から、Quest で見るためのシーンを作る。
//
// メニュー: MVL → Quest → ビューア用シーンを作る
//
// やること:
//   1. MVL_Temp.unity を Assets/Scenes/QuestView.unity としてコピーして開く
//   2. PC 用のカメラ（撮影用カメラ・FlyCamera）を消す
//   3. 「XR Rig」を入口に置く（中に、頭の動きで動くカメラ）
//   4. ビルドするシーンを QuestView.unity だけにする
//
// 注意:
//   - ライトマップ（焼いた影）は MVL_Temp のものを共有している。このプロジェクトで
//     SceneBuilder を動かし直すと、QuestView の影も変わる。
//   - 入口の位置は、部屋を作ったときのシーンJSON の room.entrance から読む。

using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.XR;

namespace MVL
{
    public static class MVLQuestViewerSetup
    {
        const string SourceScene = "Assets/MVL_Temp.unity";
        const string QuestScene = "Assets/Scenes/QuestView.unity";

        // 入口からどれだけ部屋の内側に立つか（m）。入口ぴったりだと壁が近すぎるため。
        const float StepInside = 0.6f;

        [MenuItem("MVL/Quest/ビューア用シーンを作る")]
        public static void CreateViewerScene()
        {
            // ---------- 入口の位置をシーンJSONから読む ----------
            string start = Path.Combine(
                Path.GetDirectoryName(Path.GetDirectoryName(Application.dataPath)),
                "mvl-skeleton", "scene");
            string jsonPath = EditorUtility.OpenFilePanel(
                "部屋を作ったときのシーンJSONを選ぶ（入口の位置に使う）", start, "json");
            if (string.IsNullOrEmpty(jsonPath)) return;

            var sceneJson = JsonUtility.FromJson<SceneJson>(File.ReadAllText(jsonPath));
            var entrance = sceneJson?.room?.entrance;
            // entrance.position は [x, z]（床の上の位置）。無ければ部屋の真ん中。
            Vector3 spawn;
            float yaw;
            if (entrance != null && entrance.position != null && entrance.position.Length >= 2)
            {
                yaw = entrance.facing_deg;
                spawn = new Vector3(entrance.position[0], 0f, entrance.position[1])
                        + Quaternion.Euler(0f, yaw, 0f) * Vector3.forward * StepInside;
            }
            else
            {
                var b = sceneJson.room.bounds;
                spawn = new Vector3(b.width / 2f, 0f, b.depth / 2f);
                yaw = 0f;
            }

            // ---------- 部屋のシーンをコピーして開く ----------
            if (!File.Exists(SourceScene))
            {
                EditorUtility.DisplayDialog("MVL Quest", SourceScene + " がありません。先に部屋を作ってください。", "OK");
                return;
            }
            if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            if (!AssetDatabase.IsValidFolder("Assets/Scenes")) AssetDatabase.CreateFolder("Assets", "Scenes");
            AssetDatabase.DeleteAsset(QuestScene);               // 前に作ったものがあれば作り直す
            AssetDatabase.CopyAsset(SourceScene, QuestScene);
            var scene = EditorSceneManager.OpenScene(QuestScene, OpenSceneMode.Single);

            // ---------- PC 用のカメラを消す ----------
            // Quest では頭の動きで動くカメラを使うので、撮影用・FlyCamera のカメラは要らない。
            int removed = 0;
            foreach (var cam in Object.FindObjectsByType<Camera>(FindObjectsInactive.Include, FindObjectsSortMode.None))
            {
                Object.DestroyImmediate(cam.gameObject);
                removed++;
            }

            // ---------- XR Rig を置く ----------
            // XR Rig = 床の上の「立ち位置」。Quest の床の原点がここに来る。
            // その子の Main Camera が、頭の位置と向きで毎フレーム動く。
            var rig = new GameObject("XR Rig");
            rig.transform.SetPositionAndRotation(spawn, Quaternion.Euler(0f, yaw, 0f));
            rig.AddComponent<MVLQuestFloorOrigin>();

            var camGo = new GameObject("Main Camera");
            camGo.tag = "MainCamera";
            camGo.transform.SetParent(rig.transform, false);
            var camera = camGo.AddComponent<Camera>();
            camera.nearClipPlane = 0.05f;   // 物に顔を近づけても切れにくくする
            camGo.AddComponent<AudioListener>();

            // TrackedPoseDriver: Quest の頭の位置・向きを、このカメラに毎フレーム写す部品。
            var tpd = camGo.AddComponent<TrackedPoseDriver>();
            tpd.trackingType = TrackedPoseDriver.TrackingType.RotationAndPosition;
            tpd.positionInput = new InputActionProperty(new InputAction(
                "HeadPosition", InputActionType.Value, "<XRHMD>/centerEyePosition", expectedControlType: "Vector3"));
            tpd.rotationInput = new InputActionProperty(new InputAction(
                "HeadRotation", InputActionType.Value, "<XRHMD>/centerEyeRotation", expectedControlType: "Quaternion"));

            // ---------- 保存して、ビルド対象にする ----------
            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene);
            EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(QuestScene, true) };

            Debug.Log($"[MVL Quest] {QuestScene} を作りました。カメラ {removed} 個を削除、" +
                      $"XR Rig を {spawn}（向き {yaw}°）に配置。ビルド対象をこのシーンだけにしました。");
        }
    }
}
