"""Count official metadata, without downloading or inspecting photo pixels."""
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCES = ROOT / "sources"
PLACES_NAMES = {
    52: "bedroom", 99: "coffee_shop", 121: "dining_room",
    176: "home_office", 212: "library/indoor", 215: "living_room", 244: "office",
}
OPEN_NAMES = {
    "/m/02_58j": "Bedroom", "/m/03f6tq": "Living room",
    "/m/03d2yw": "Study", "/g/122sgqnb": "Office",
    "/m/025s4nn": "Coffeehouse", "/m/02pdnx": "Cafeteria",
    "/m/03d2wd": "Dining room", "/m/06l8d": "Restaurant",
}

places_counts = {}
for split, filename in (
    ("train", "places365_train_standard.txt"),
    ("validation", "places365_val.txt"),
):
    with (SOURCES / filename).open(encoding="utf-8") as stream:
        counter = Counter(int(line.rsplit(maxsplit=1)[1]) for line in stream if line.strip())
    places_counts[split] = counter

places_rows = [
    {"label_id": key, "category": value,
     "train": places_counts["train"][key],
     "validation": places_counts["validation"][key]}
    for key, value in PLACES_NAMES.items()
]
with (ROOT / "places365_selected_counts.csv").open("w", newline="", encoding="utf-8-sig") as stream:
    writer = csv.DictWriter(stream, fieldnames=places_rows[0].keys())
    writer.writeheader()
    writer.writerows(places_rows)

open_counts = {}
for split in ("val", "test"):
    unique_positive_ids = {key: set() for key in OPEN_NAMES}
    with (SOURCES / f"openimages-{split}-human-labels.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            label = row["LabelName"]
            if label in unique_positive_ids and float(row["Confidence"]) == 1.0:
                unique_positive_ids[label].add(row["ImageID"])
    open_counts[split] = {key: len(value) for key, value in unique_positive_ids.items()}

open_rows = [
    {"label_mid": key, "category": value,
     "validation_positive_images": open_counts["val"][key],
     "test_positive_images": open_counts["test"][key],
     "combined_positive_images": open_counts["val"][key] + open_counts["test"][key],
     "train_positive_images": "unverified"}
    for key, value in OPEN_NAMES.items()
]
with (ROOT / "openimages_selected_counts.csv").open("w", newline="", encoding="utf-8-sig") as stream:
    writer = csv.DictWriter(stream, fieldnames=open_rows[0].keys())
    writer.writeheader()
    writer.writerows(open_rows)

source_urls = {
    "places365-source-filelist.tar": "http://data.csail.mit.edu/places/places365/filelist_places365-standard.tar",
    "openimages-class-descriptions.csv": "https://storage.googleapis.com/openimages/v7/oidv7-class-descriptions.csv",
    "openimages-val-human-labels.csv": "https://storage.googleapis.com/openimages/v7/oidv7-val-annotations-human-imagelabels.csv",
    "openimages-test-human-labels.csv": "https://storage.googleapis.com/openimages/v7/oidv7-test-annotations-human-imagelabels.csv",
}
manifest = {
    "checked_date": "2026-10-09",
    "places365_selected_counts": places_rows,
    "places365_train_total": sum(places_counts["train"].values()),
    "places365_validation_total": sum(places_counts["validation"].values()),
    "openimages_selected_counts": open_rows,
    "openimages_count_definition": "Unique image IDs with human-verified Confidence == 1.0; val and test only; not a count of usable indoor photographs.",
    "source_files": [],
}
for name, url in source_urls.items():
    path = SOURCES / name
    digest = hashlib.file_digest(path.open("rb"), "sha256").hexdigest()
    manifest["source_files"].append({"filename": name, "url": url, "bytes": path.stat().st_size, "sha256": digest})
(ROOT / "count_evidence.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({key: value for key, value in manifest.items() if key != "source_files"}, ensure_ascii=False, indent=2))
