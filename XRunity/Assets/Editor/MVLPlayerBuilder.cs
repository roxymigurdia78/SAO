// MVLPlayerBuilder.cs — 保存したランのシーン(Assets/MVLRuns/*.unity)を、単体で動く exe にする
// 目的: before / after の2つの部屋を、2つのウィンドウで同時に開いて歩き比べる
//       (Unity エディタは同じプロジェクトを2つ同時に開けないため、exe にして並べる)
// 呼び出し: mvl-skeleton/python/open_two.ps1 から batchmode で
//   -executeMethod MVLPlayerBuilder.BuildFromArgs -runScene Assets/MVLRuns/<名前>.unity -outExe <...>/Room.exe
using System;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEngine;

public static class MVLPlayerBuilder
{
    public static void BuildFromArgs()
    {
        string scene = Arg("-runScene");
        string exe = Arg("-outExe");
        bool ok = scene != null && exe != null && Build(scene, exe);
        EditorApplication.Exit(ok ? 0 : 1);
    }

    public static bool Build(string scenePath, string exePath)
    {
        // ウィンドウ表示・サイズ変更可・タイトル=ラン名 にしてビルドし、終わったら元の設定に戻す
        var oldMode = PlayerSettings.fullScreenMode;
        int oldW = PlayerSettings.defaultScreenWidth, oldH = PlayerSettings.defaultScreenHeight;
        bool oldResize = PlayerSettings.resizableWindow;
        string oldName = PlayerSettings.productName;
        try
        {
            PlayerSettings.fullScreenMode = FullScreenMode.Windowed;
            PlayerSettings.defaultScreenWidth = 960;
            PlayerSettings.defaultScreenHeight = 540;
            PlayerSettings.resizableWindow = true;
            PlayerSettings.productName = System.IO.Path.GetFileNameWithoutExtension(scenePath); // ウィンドウのタイトルになる

            // 未保存の設定(URP の Default Volume Profile など)を先に保存する。
            // 10/13: 最初の書き出しで URP の後処理・SSAO の資源が入らず、部屋が描画されない exe ができたため
            AssetDatabase.SaveAssets();

            var report = BuildPipeline.BuildPlayer(new BuildPlayerOptions
            {
                scenes = new[] { scenePath },
                locationPathName = exePath,
                target = BuildTarget.StandaloneWindows64,
                options = BuildOptions.None
            });
            Debug.Log($"[MVL] player build: {report.summary.result} {exePath} ({report.summary.totalTime})");
            return report.summary.result == BuildResult.Succeeded;
        }
        finally
        {
            PlayerSettings.fullScreenMode = oldMode;
            PlayerSettings.defaultScreenWidth = oldW;
            PlayerSettings.defaultScreenHeight = oldH;
            PlayerSettings.resizableWindow = oldResize;
            PlayerSettings.productName = oldName;
        }
    }

    static string Arg(string name)
    {
        var a = Environment.GetCommandLineArgs();
        for (int i = 0; i < a.Length - 1; i++)
            if (a[i] == name) return a[i + 1];
        return null;
    }
}
