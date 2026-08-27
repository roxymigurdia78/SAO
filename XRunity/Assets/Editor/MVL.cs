// MVL.cs — 最小ループ用 共通定義(シーンJSONのC#側ミラー)
// 置き場所: Assets/Editor/MVL.cs
// 依存: com.unity.cloud.gltfast, UnityMeshSimplifier (git: https://github.com/Whinarn/UnityMeshSimplifier.git)
using System;
using System.Collections.Generic;

namespace MVL
{
    [Serializable] public class SceneSpec
    {
        public string space_type;
        public string theme;
    }

    [Serializable] public class SunLight
    {
        public float[] rotation_euler_deg;
        public float intensity = 1.0f;
        public string color_hex = "FFFFFF";
        public string mode = "Mixed";
    }

    [Serializable] public class Lighting
    {
        public SunLight sun;
        public float ambient_intensity = 1.0f;
    }

    [Serializable] public class Bounds3
    {
        public float width;
        public float depth;
        public float height;
    }

    [Serializable] public class Entrance
    {
        public float[] position; // [x, z]
        public float facing_deg;
    }

    [Serializable] public class Room
    {
        public Bounds3 bounds;
        public float floor_y;
        public Entrance entrance;
        public string wall_material;
        public string floor_material;
        public Lighting lighting;
    }

    [Serializable] public class Dimensions
    {
        public float width;
        public float height;
        public float depth;
    }

    [Serializable] public class SceneObject
    {
        public string id;
        public string @class;
        public string asset;
        public float[] position;      // [x, y, z] 底面中心
        public float rotation_y_deg;
        public Dimensions target_dimensions;
        public bool must_touch_floor = true;
        public string rests_on;
        public bool walkable_over = false;
        public bool locked = false;
    }

    [Serializable] public class SceneJson
    {
        public string schema_version;
        public string scene_id;
        public SceneSpec spec;
        public Room room;
        public string assets_dir;
        public List<SceneObject> objects;
    }

    // ---- report.json(Unity → Python への実測レポート)----
    [Serializable] public class ObjectReport
    {
        public string id;
        public float[] aabb_min;
        public float[] aabb_max;
        public int triangle_count_before;
        public int triangle_count_after;
    }

    [Serializable] public class BuildReport
    {
        public string scene_id;
        public List<ObjectReport> objects = new List<ObjectReport>();
        public List<string> captures = new List<string>();
        public bool fast_iteration;
        public float geometry_seconds;
        public float bake_seconds;
        public float capture_seconds;
        public float total_seconds;
        public string error; // 失敗時のみ
    }
}
