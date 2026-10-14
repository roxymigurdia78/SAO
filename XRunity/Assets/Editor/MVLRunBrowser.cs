// MVLRunBrowser.cs — メニュー「MVL → ラン一覧」
// 保存されたラン(Assets/MVLRuns/*.unity)を選んで、その部屋を Play モードで歩く。
// ターミナルからは mvl-skeleton/python/open_runs.ps1 で Unity を起動してこの画面を開ける。
// 歩く操作は FlyCamera: 右クリック+マウスで視点 / WASD 移動 / Q E 上下 / Shift 加速
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

public class MVLRunBrowser : EditorWindow
{
    const string RunsDir = "Assets/MVLRuns";
    Vector2 scroll;
    string filter = "";

    [MenuItem("MVL/ラン一覧")]
    public static void Open() => GetWindow<MVLRunBrowser>("MVL ラン一覧");

    void OnGUI()
    {
        if (!Directory.Exists(RunsDir))
        {
            EditorGUILayout.HelpBox("まだ保存されたランがありません。orchestrator.py でランを回すと、ここに並びます。", MessageType.Info);
            return;
        }
        if (EditorApplication.isPlaying)
            EditorGUILayout.HelpBox("Play 中です。別のランを見るときは Play を止めてから「歩く」を押してください。", MessageType.Info);

        EditorGUILayout.LabelField("操作: 右クリック+マウスで視点 / WASD 移動 / Q E 上下 / Shift 加速", EditorStyles.miniLabel);
        EditorGUILayout.LabelField("注意: ランを回す(バッチ実行)前に Unity を閉じること", EditorStyles.miniLabel);
        filter = EditorGUILayout.TextField("名前で絞り込み", filter);

        var scenes = Directory.GetFiles(RunsDir, "*.unity")
                              .Where(s => string.IsNullOrEmpty(filter) ||
                                          Path.GetFileName(s).IndexOf(filter, System.StringComparison.OrdinalIgnoreCase) >= 0)
                              .OrderByDescending(File.GetLastWriteTime)
                              .ToArray();

        scroll = EditorGUILayout.BeginScrollView(scroll);
        foreach (var s in scenes)
        {
            EditorGUILayout.BeginHorizontal();
            EditorGUILayout.LabelField(File.GetLastWriteTime(s).ToString("MM/dd HH:mm"), GUILayout.Width(80));
            EditorGUILayout.LabelField(Path.GetFileNameWithoutExtension(s));
            GUI.enabled = !EditorApplication.isPlaying;
            if (GUILayout.Button("歩く", GUILayout.Width(60)))
            {
                if (EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo())
                {
                    EditorSceneManager.OpenScene(s.Replace('\\', '/'));
                    EditorApplication.isPlaying = true;
                }
            }
            GUI.enabled = true;
            EditorGUILayout.EndHorizontal();
        }
        EditorGUILayout.EndScrollView();
    }
}
