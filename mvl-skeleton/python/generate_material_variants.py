"""Generate material-focused reference images for TRELLIS in timestamped batches."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path


CLASS_PROMPTS = {
    "desk": "modern wooden study desk, contemporary design",
    "chair": "modern office chair",
    "bookshelf": "modern tall wooden bookshelf filled with books",
    "lamp": "modern desk lamp with a metal shade",
    "plant": "potted plant in a modern ceramic pot",
    "books": "stack of hardcover books",
    "monitor": "modern computer monitor on a stand",
    "rug": "modern woven area rug, viewed at a slight angle",
    "laptop": "modern open laptop computer, contemporary design",
    "mug": "modern ceramic coffee mug",
    "pen_holder": "modern desk pen holder filled with pens and pencils",
    "printer": "modern compact inkjet printer",
    "floor_lamp": "modern floor lamp with a fabric shade",
    "cabinet": "modern small three-drawer storage cabinet, light wood",
    "trash_bin": "modern small waste basket",
    "backpack": "modern school backpack, standing upright",
}

MATERIAL_ANCHOR = (
    ", physically plausible materials with material-specific surface detail and microtexture, "
    "such as wood grain, woven fibers, brushed metal, ceramic glaze, paper texture, or leaf "
    "veins as appropriate, realistic roughness variation, subtle accurate specular highlights, "
    "natural small imperfections, no uniform plastic appearance"
)

IMAGE_SUFFIX = (
    ", single object, centered, full object visible, isolated on a pure white background, "
    "front three-quarter view, studio product photography lighting, sharp focus, crisp details, "
    "clean silhouette, simple readable shape, no text, no watermark, no extra objects, "
    "no environment, not cropped"
)


def load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE entries without overwriting existing environment values."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def make_run_dir(output_root: Path, timestamp: str) -> Path:
    base = output_root / f"{timestamp}_material_variants"
    candidate = base
    suffix = 2
    while candidate.exists():
        candidate = output_root / f"{base.name}_{suffix:02d}"
        suffix += 1
    return candidate


def build_plan(classes: list[str], start_variant: int, variants: int, run_dir: Path) -> list[dict]:
    plan = []
    for asset_class in classes:
        prompt = CLASS_PROMPTS[asset_class] + MATERIAL_ANCHOR + IMAGE_SUFFIX
        for variant in range(start_variant, start_variant + variants):
            name = f"{asset_class}_v{variant}"
            plan.append(
                {
                    "name": name,
                    "class": asset_class,
                    "variant": variant,
                    "prompt": prompt,
                    "output": str((run_dir / f"{name}.png").resolve()),
                    "status": "planned",
                }
            )
    return plan


def save_manifest(path: Path, manifest: dict) -> None:
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def generate_one(client, model: str, quality: str, size: str, prompt: str, output: Path) -> None:
    kwargs = {"model": model, "prompt": prompt, "size": size, "n": 1}
    if model.startswith("gpt-image"):
        kwargs["quality"] = quality
    else:
        kwargs["response_format"] = "b64_json"
        kwargs["quality"] = "standard"
    response = client.images.generate(**kwargs)
    output.write_bytes(base64.b64decode(response.data[0].b64_json))
    usage = getattr(response, "usage", None)
    if usage:
        print(f"    usage: {usage}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate material-realistic reference images for new TRELLIS asset variants."
    )
    parser.add_argument(
        "--classes",
        nargs="+",
        choices=sorted(CLASS_PROMPTS),
        default=["plant", "books", "floor_lamp"],
        help="Asset classes to generate (default: plant books floor_lamp).",
    )
    parser.add_argument("--start-variant", type=int, default=4)
    parser.add_argument("--variants", type=int, default=3)
    parser.add_argument("--model", default="gpt-image-2")
    parser.add_argument("--quality", choices=["low", "medium", "high"], default="low")
    parser.add_argument("--size", default="1024x1024")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds between API calls.")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "images",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the plan without calling the API.")
    args = parser.parse_args()
    if args.start_variant < 1:
        parser.error("--start-variant must be at least 1")
    if args.variants < 1:
        parser.error("--variants must be at least 1")
    if args.delay < 0:
        parser.error("--delay cannot be negative")
    return args


def main() -> int:
    args = parse_args()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = make_run_dir(args.output_root.resolve(), timestamp)
    plan = build_plan(args.classes, args.start_variant, args.variants, run_dir)

    print(f"Output: {run_dir}")
    print(f"Plan: {len(args.classes)} classes x {args.variants} variants = {len(plan)} images")
    for item in plan:
        print(f"  {item['name']}.png")

    if args.dry_run:
        print("Dry run: API was not called and no files were created.")
        return 0

    load_env_file(Path(__file__).with_name(".env"))
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set in the environment or mvl-skeleton/python/.env", file=sys.stderr)
        return 2

    from openai import OpenAI

    run_dir.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "model": args.model,
        "quality": args.quality,
        "size": args.size,
        "classes": args.classes,
        "start_variant": args.start_variant,
        "variants_per_class": args.variants,
        "material_anchor": MATERIAL_ANCHOR.lstrip(", "),
        "output_dir": str(run_dir),
        "assets": plan,
    }
    manifest_path = run_dir / "manifest.json"
    save_manifest(manifest_path, manifest)

    client = OpenAI()
    failures = 0
    for index, item in enumerate(plan, start=1):
        output = Path(item["output"])
        print(f"[{index}/{len(plan)}] Generating {output.name} ...")
        try:
            generate_one(client, args.model, args.quality, args.size, item["prompt"], output)
            item["status"] = "success"
        except Exception as exc:
            failures += 1
            item["status"] = "failed"
            item["error"] = str(exc)
            print(f"    failed: {exc}", file=sys.stderr)
        save_manifest(manifest_path, manifest)
        if index < len(plan) and args.delay:
            time.sleep(args.delay)

    succeeded = len(plan) - failures
    print(f"Complete: success={succeeded} failed={failures}")
    print(f"Manifest: {manifest_path}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
