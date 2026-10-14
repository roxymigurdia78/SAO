import os
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

import argparse
import json
import traceback
from pathlib import Path

from PIL import Image
from trellis2.pipelines import Trellis2ImageTo3DPipeline
import o_voxel


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def safe_name(path: Path) -> str:
    return path.stem.replace(" ", "_")


def export_glb(mesh, glb_path, decimation_target, texture_size):
    glb = o_voxel.postprocess.to_glb(
        vertices=mesh.vertices,
        faces=mesh.faces,
        attr_volume=mesh.attrs,
        coords=mesh.coords,
        attr_layout=mesh.layout,
        voxel_size=mesh.voxel_size,
        aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
        decimation_target=decimation_target,
        texture_size=texture_size,
        remesh=True,
        remesh_band=1,
        remesh_project=0,
        verbose=True,
    )

    # Unity/glTFast対策：
    # WebP拡張 EXT_texture_webp を使わない
    glb.export(str(glb_path), extension_webp=False)


def main():
    parser = argparse.ArgumentParser(
        description="Batch convert images to Unity-friendly GLB using TRELLIS.2."
    )
    parser.add_argument(
        "--input-dir",
        required=True,
        help="Directory containing input images."
    )
    parser.add_argument(
        "--output-dir",
        default="generated_glbs",
        help="Directory to save GLB files."
    )
    parser.add_argument(
        "--decimation-target",
        type=int,
        default=150000,
        help="Target face count for GLB postprocess."
    )
    parser.add_argument(
        "--texture-size",
        type=int,
        default=4096,
        help="Texture size for GLB export."
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip images if the output GLB already exists."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of images to process."
    )

    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)

    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    images = sorted(
        p for p in input_dir.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    )

    if args.limit is not None:
        images = images[:args.limit]

    if not images:
        raise RuntimeError(f"No image files found in: {input_dir}")

    print("Input directory:", input_dir)
    print("Output directory:", output_dir)
    print("Image count:", len(images))
    print("Decimation target:", args.decimation_target)
    print("Texture size:", args.texture_size)

    print("Loading TRELLIS.2 pipeline once...")
    pipeline = Trellis2ImageTo3DPipeline.from_pretrained("microsoft/TRELLIS.2-4B")
    pipeline.cuda()
    print("Pipeline loaded.")

    manifest = {
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "decimation_target": args.decimation_target,
        "texture_size": args.texture_size,
        "assets": []
    }

    for i, image_path in enumerate(images, start=1):
        name = safe_name(image_path)
        glb_path = output_dir / f"{name}.glb"

        print("=" * 80)
        print(f"[{i}/{len(images)}] Processing:", image_path)
        print("Output:", glb_path)

        if args.skip_existing and glb_path.exists():
            print("Skipping existing:", glb_path)
            manifest["assets"].append({
                "name": name,
                "input_image": str(image_path),
                "glb": str(glb_path),
                "status": "skipped_existing"
            })
            continue

        try:
            image = Image.open(image_path).convert("RGBA")

            print("Running TRELLIS.2...")
            mesh = pipeline.run(image)[0]
            print(mesh.voxel_size)
            
            print("Simplifying mesh for nvdiffrast limit...")
            mesh.simplify(16777216)

            print("Exporting GLB...")
            export_glb(
                mesh=mesh,
                glb_path=glb_path,
                decimation_target=args.decimation_target,
                texture_size=args.texture_size,
            )

            print("Saved:", glb_path)

            manifest["assets"].append({
                "name": name,
                "input_image": str(image_path),
                "glb": str(glb_path),
                "status": "success",
                "suggested_position": [0, 0, 0],
                "suggested_scale": 1.0
            })

        except Exception as e:
            print("ERROR while processing:", image_path)
            print(type(e).__name__, e)
            traceback.print_exc()

            manifest["assets"].append({
                "name": name,
                "input_image": str(image_path),
                "glb": str(glb_path),
                "status": "failed",
                "error": f"{type(e).__name__}: {e}"
            })

        manifest_path = output_dir / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
    print("=" * 80)
    print("Batch done.")
    print("Manifest saved:", manifest_path)


if __name__ == "__main__":
    main()
