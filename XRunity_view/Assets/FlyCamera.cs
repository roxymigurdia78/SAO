// FlyCamera.cs — Playモードで部屋を歩き回る簡易カメラ
// 置き場所: Assets/FlyCamera.cs(Editorフォルダの外!)
// 操作: 右クリック押しっぱなし+マウスで視点 / WASD移動 / Q下降 E上昇 / Shift加速
using UnityEngine;
#if ENABLE_INPUT_SYSTEM
using UnityEngine.InputSystem;
#endif

public class FlyCamera : MonoBehaviour
{
    public float moveSpeed = 2.0f;
    public float fastMultiplier = 3.0f;
    public float lookSensitivity = 0.15f;

    float yaw, pitch;

    void Start()
    {
        var e = transform.eulerAngles;
        yaw = e.y;
        pitch = e.x > 180 ? e.x - 360 : e.x;
    }

    void Update()
    {
#if ENABLE_INPUT_SYSTEM
        var kb = Keyboard.current;
        var mouse = Mouse.current;
        if (kb == null || mouse == null) return;

        if (mouse.rightButton.isPressed)
        {
            var d = mouse.delta.ReadValue();
            yaw += d.x * lookSensitivity;
            pitch = Mathf.Clamp(pitch - d.y * lookSensitivity, -89f, 89f);
            transform.rotation = Quaternion.Euler(pitch, yaw, 0);
        }

        var dir = Vector3.zero;
        if (kb.wKey.isPressed) dir += transform.forward;
        if (kb.sKey.isPressed) dir -= transform.forward;
        if (kb.aKey.isPressed) dir -= transform.right;
        if (kb.dKey.isPressed) dir += transform.right;
        if (kb.eKey.isPressed) dir += Vector3.up;
        if (kb.qKey.isPressed) dir -= Vector3.up;
        float speed = moveSpeed * (kb.leftShiftKey.isPressed ? fastMultiplier : 1f);
#else
        if (Input.GetMouseButton(1))
        {
            yaw += Input.GetAxis("Mouse X") * lookSensitivity * 10f;
            pitch = Mathf.Clamp(pitch - Input.GetAxis("Mouse Y") * lookSensitivity * 10f, -89f, 89f);
            transform.rotation = Quaternion.Euler(pitch, yaw, 0);
        }
        var dir = transform.forward * Input.GetAxis("Vertical") + transform.right * Input.GetAxis("Horizontal");
        if (Input.GetKey(KeyCode.E)) dir += Vector3.up;
        if (Input.GetKey(KeyCode.Q)) dir -= Vector3.up;
        float speed = moveSpeed * (Input.GetKey(KeyCode.LeftShift) ? fastMultiplier : 1f);
#endif
        if (dir.sqrMagnitude > 0.001f)
            transform.position += dir.normalized * speed * Time.deltaTime;
    }
}
