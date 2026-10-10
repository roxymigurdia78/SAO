// MVLQuestFloorOrigin.cs
//
// Quest の「床」を原点にして頭の位置を測るように設定する（実行時に動く）。
// これがないと、Quest によっては頭の位置が「起動したときの頭」を原点にしてしまい、
// 部屋の床に対して目の高さがずれる（床に埋まる・浮く）。
//
// XR Rig の GameObject に付ける。MVLQuestViewerSetup が自動で付ける。

using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR;

public class MVLQuestFloorOrigin : MonoBehaviour
{
    // XR の初期化は起動直後に少し遅れることがあるので、成功するまで毎フレーム試す。
    bool done;

    void Update()
    {
        if (done) return;

        var subsystems = new List<XRInputSubsystem>();
        SubsystemManager.GetSubsystems(subsystems);
        foreach (var s in subsystems)
        {
            if (s.TrySetTrackingOriginMode(TrackingOriginModeFlags.Floor))
            {
                Debug.Log("[MVL Quest] 床を原点に設定しました");
                done = true;
            }
        }
    }
}
