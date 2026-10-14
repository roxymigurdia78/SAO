using System;
using System.IO;
using UnityEditor;
using UnityEngine;

/// <summary>
/// MVLImported以下へ読み込まれるテクスチャに、Quest向けの設定を自動適用します。
/// </summary>
public sealed class MVLTextureImportSettings : AssetPostprocessor
{
    private const string TargetFolder = "Assets/MVLImported/";
    private const int MaxTextureSize = 4096;

    private void OnPreprocessTexture()
    {
        // 対象フォルダを限定する。
        // MVLGeneratedなど、別用途のテクスチャ設定を誤って変更しないためです。
        if (!assetPath.StartsWith(TargetFolder, StringComparison.Ordinal))
        {
            return;
        }

        if (assetImporter is not TextureImporter textureImporter)
        {
            return;
        }

        // 4096の元画像を縮小せず、遠距離では軽いMipレベルを使えるようにする。
        // Streaming Mipmapsを有効にすると、必要なMipレベルだけを読み込みやすくなります。
        textureImporter.maxTextureSize = MaxTextureSize;
        textureImporter.mipmapEnabled = true;
        textureImporter.streamingMipmaps = true;

        // metallicRoughnessは色ではなく数値データなので、sRGB変換を無効にする。
        // baseColorなど、それ以外の画像は色テクスチャとしてsRGBを有効にします。
        string fileName = Path.GetFileNameWithoutExtension(assetPath);
        bool isMetallicRoughness = fileName.IndexOf(
            "metallicRoughness",
            StringComparison.OrdinalIgnoreCase) >= 0;
        textureImporter.sRGBTexture = !isMetallicRoughness;

        // Quest向けのAndroid設定を上書きする。
        // 4096を維持しつつ、ASTC 6x6で画質とメモリ使用量のバランスを取ります。
        TextureImporterPlatformSettings androidSettings =
            textureImporter.GetPlatformTextureSettings("Android");
        androidSettings.name = "Android";
        androidSettings.overridden = true;
        androidSettings.maxTextureSize = MaxTextureSize;
        androidSettings.format = TextureImporterFormat.ASTC_6x6;
        textureImporter.SetPlatformTextureSettings(androidSettings);

        // Consoleで、対象画像と実際に指定した設定を1行で確認できるようにする。
        Debug.Log(
            $"[MVLTextureImportSettings] {assetPath}: " +
            $"Max Size={MaxTextureSize}, Mip Maps=On, Streaming Mipmaps=On, " +
            $"Android=ASTC 6x6/{MaxTextureSize}, " +
            $"sRGB={(textureImporter.sRGBTexture ? "On" : "Off")}");
    }
}
