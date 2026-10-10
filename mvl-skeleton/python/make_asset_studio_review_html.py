"""48アセットを単独判定するブラインドHTMLビューアを生成する。"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
from pathlib import Path
from urllib.parse import quote


ASSET_PATTERN = re.compile(r"^(?P<class_name>.+)_v(?P<version>[123])$")
AZIMUTHS = (0, 45, 90, 135, 180, 225, 270, 315)
EXAMPLE_ASSETS = ("monitor_v1", "printer_v1", "desk_v1", "laptop_v1")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
RECORD_SUFFIXES = {".json", ".jsonl", ".csv", ".tsv", ".txt", ".md", ".yaml", ".yml"}
SKIP_DIRECTORY_NAMES = {
    ".git", ".idea", ".vs", ".vscode", "Library", "Temp", "Logs",
    "obj", "bin", "node_modules", "__pycache__", "studio_review_sheets",
}


def discover_assets(capture_root: Path) -> list[dict[str, object]]:
    assets: list[dict[str, object]] = []
    for directory in sorted(capture_root.iterdir(), key=lambda path: path.name.lower()):
        if not directory.is_dir() or "__" in directory.name:
            continue
        match = ASSET_PATTERN.match(directory.name)
        if match is None:
            continue
        images = [directory / f"azimuth_{azimuth:03d}.png" for azimuth in AZIMUTHS]
        missing = [path.name for path in images if not path.is_file()]
        if missing:
            raise FileNotFoundError(
                f"8方向画像が揃っていません: {directory} missing={missing}"
            )
        assets.append(
            {
                "asset": directory.name,
                "class": match.group("class_name"),
                "directory": directory,
                "images": images,
            }
        )
    if len(assets) != 48:
        raise ValueError(f"撮影済みアセットが48個ではありません: {len(assets)}")
    return assets


def should_skip(path: Path, excluded_roots: tuple[Path, ...]) -> bool:
    if any(part in SKIP_DIRECTORY_NAMES for part in path.parts):
        return True
    resolved = path.resolve()
    return any(resolved == root or root in resolved.parents for root in excluded_roots)


def iter_repository_files(
    repo_root: Path, suffixes: set[str], excluded_roots: tuple[Path, ...]
):
    for path in repo_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        if should_skip(path, excluded_roots):
            continue
        yield path


def mentioned_assets(text: str, asset_names: list[str]) -> list[str]:
    lowered = text.lower()
    return [
        asset
        for asset in asset_names
        if asset.lower() in lowered or f"{asset.lower()}.glb" in lowered
    ]


def resolve_image_reference(raw: str, source: Path, repo_root: Path) -> Path | None:
    value = raw.strip().strip('"\'').replace("file:///", "")
    if not any(value.lower().endswith(suffix) for suffix in IMAGE_SUFFIXES):
        return None
    value = value.replace("\\", os.sep).replace("/", os.sep)
    candidate = Path(value)
    choices = [candidate] if candidate.is_absolute() else [
        source.parent / candidate,
        repo_root / candidate,
        repo_root / "images" / candidate,
    ]
    for choice in choices:
        try:
            resolved = choice.resolve()
        except OSError:
            continue
        if resolved.is_file() and (
            resolved == repo_root or repo_root in resolved.parents
        ):
            return resolved
    return None


def image_strings(values: list[str]) -> list[str]:
    return [
        value
        for value in values
        if any(value.lower().strip().endswith(suffix) for suffix in IMAGE_SUFFIXES)
    ]


def flatten_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        result: list[str] = []
        for child in value.values():
            result.extend(flatten_strings(child))
        return result
    if isinstance(value, list):
        result = []
        for child in value:
            result.extend(flatten_strings(child))
        return result
    return []


def add_record_candidates(
    value: object,
    source: Path,
    repo_root: Path,
    asset_names: list[str],
    candidates: dict[str, list[tuple[int, Path, str, Path]]],
) -> None:
    if isinstance(value, dict):
        strings = flatten_strings(value)
        mentions = mentioned_assets("\n".join(strings), asset_names)
        references = image_strings(strings)
        # 1レコードが1アセットだけを指す場合のみ対応付ける。
        if len(mentions) == 1 and references:
            for raw in references:
                resolved = resolve_image_reference(raw, source, repo_root)
                if resolved is not None:
                    candidates[mentions[0]].append(
                        (80, resolved, "manifest/json record", source)
                    )
        for child in value.values():
            add_record_candidates(
                child, source, repo_root, asset_names, candidates
            )
    elif isinstance(value, list):
        for child in value:
            add_record_candidates(
                child, source, repo_root, asset_names, candidates
            )


def discover_input_images(
    repo_root: Path,
    assets: list[dict[str, object]],
    capture_root: Path,
    review_output_root: Path,
) -> tuple[dict[str, Path | None], list[dict[str, str]]]:
    asset_names = [str(asset["asset"]) for asset in assets]
    candidates: dict[str, list[tuple[int, Path, str, Path]]] = {
        name: [] for name in asset_names
    }
    excluded_roots = (capture_root.resolve(), review_output_root.resolve())

    # 最も強い証拠: 画像ファイル名自体に完全なアセット名が含まれる。
    for image in iter_repository_files(repo_root, IMAGE_SUFFIXES, excluded_roots):
        lowered_stem = image.stem.lower()
        for asset in asset_names:
            if asset.lower() in lowered_stem:
                candidates[asset].append((100, image.resolve(), "filename", image))

    for record in iter_repository_files(repo_root, RECORD_SUFFIXES, excluded_roots):
        try:
            if record.suffix.lower() == ".json":
                parsed = json.loads(record.read_text(encoding="utf-8-sig"))
                add_record_candidates(
                    parsed, record, repo_root, asset_names, candidates
                )
                continue
            if record.suffix.lower() in {".csv", ".tsv"}:
                delimiter = "\t" if record.suffix.lower() == ".tsv" else ","
                with record.open("r", encoding="utf-8-sig", errors="replace", newline="") as stream:
                    for row in csv.DictReader(stream, delimiter=delimiter):
                        strings = [value for value in row.values() if value]
                        mentions = mentioned_assets("\n".join(strings), asset_names)
                        if len(mentions) != 1:
                            continue
                        for raw in image_strings(strings):
                            resolved = resolve_image_reference(raw, record, repo_root)
                            if resolved is not None:
                                candidates[mentions[0]].append(
                                    (75, resolved, "csv record", record)
                                )
                continue

            lines = record.read_text(
                encoding="utf-8-sig", errors="replace"
            ).splitlines()
            for index, line in enumerate(lines):
                mentions = mentioned_assets(line, asset_names)
                if len(mentions) != 1:
                    continue
                context = " ".join(lines[max(0, index - 2): index + 3])
                for raw in re.findall(
                    r"[^\s\"'<>|,;]+\.(?:png|jpe?g|webp|bmp)",
                    context,
                    flags=re.IGNORECASE,
                ):
                    resolved = resolve_image_reference(raw, record, repo_root)
                    if resolved is not None:
                        candidates[mentions[0]].append(
                            (60, resolved, "text context", record)
                        )
        except (OSError, UnicodeError, json.JSONDecodeError, csv.Error):
            continue

    selected: dict[str, Path | None] = {}
    rows: list[dict[str, str]] = []
    for asset in asset_names:
        unique: dict[Path, tuple[int, Path, str, Path]] = {}
        for item in candidates[asset]:
            previous = unique.get(item[1])
            if previous is None or item[0] > previous[0]:
                unique[item[1]] = item
        ranked = sorted(unique.values(), key=lambda item: (-item[0], str(item[1]).lower()))
        if ranked:
            best = ranked[0]
            selected[asset] = best[1]
            rows.append(
                {
                    "asset": asset,
                    "input_image": best[1].relative_to(repo_root).as_posix(),
                    "evidence": best[2],
                    "source_record": best[3].relative_to(repo_root).as_posix(),
                }
            )
        else:
            selected[asset] = None
            rows.append(
                {
                    "asset": asset,
                    "input_image": "なし",
                    "evidence": "",
                    "source_record": "",
                }
            )
    return selected, rows


def browser_path(path: Path, html_dir: Path) -> str:
    relative = os.path.relpath(path, html_dir).replace("\\", "/")
    return quote(relative, safe="/.:@")


def write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_html(data: list[dict[str, object]]) -> str:
    encoded = json.dumps(data, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Studio material review</title>
<style>
:root {{ color-scheme: dark; font-family: system-ui, sans-serif; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: #181818; color: #f5f5f5; }}
header {{ position: sticky; top: 0; z-index: 5; display: grid;
  grid-template-columns: auto 1fr auto auto; align-items: center;
  gap: 12px; padding: 12px 20px; background: #101010ee;
  border-bottom: 1px solid #444; }}
h1 {{ margin: 0; text-align: center; font-size: clamp(20px, 3vw, 34px); }}
button {{ border: 1px solid #777; border-radius: 8px; background: #292929; color: white;
  padding: 10px 18px; font-size: 16px; cursor: pointer; }}
button:hover {{ background: #3b3b3b; }}
#export {{ border-color: #5aa970; background: #235d34; }}
#export:hover {{ background: #2f7845; }}
main {{ padding: 16px; }}
.content {{ display: block; }}
.content.has-reference {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 4fr);
  gap: 16px; align-items: start; }}
.reference {{ position: sticky; top: 84px; background: #242424; border-radius: 10px;
  overflow: hidden; }}
.reference h2 {{ margin: 0 0 10px; font-size: 18px; }}
.reference h2 {{ padding: 10px 12px 0; }}
.reference img {{ display: block; width: 100%; aspect-ratio: 1; object-fit: contain;
  background: #888; }}
.grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }}
.view {{ position: relative; padding: 0; overflow: hidden; background: #888;
  border: 1px solid #555; border-radius: 8px; }}
.view img {{ display: block; width: 100%; aspect-ratio: 1; object-fit: contain; }}
.azimuth {{ position: absolute; left: 8px; bottom: 8px; padding: 3px 7px;
  border-radius: 5px; background: #000b; font: 600 14px ui-monospace, monospace; }}
.review {{ margin-top: 18px; padding: 18px; border: 1px solid #555;
  border-radius: 10px; background: #222; }}
.review-grid {{ display: grid; grid-template-columns: repeat(3, minmax(240px, 1fr));
  gap: 18px; }}
.wide-question {{ grid-column: 1 / -1; }}
.example-note {{ margin: 0 0 14px; padding: 10px 12px; border-radius: 7px;
  background: #5b4a18; color: #fff0b0; font-weight: 700; }}
fieldset {{ margin: 0; padding: 14px; border: 1px solid #666; border-radius: 8px; }}
legend {{ padding: 0 6px; font-weight: 700; }}
.choices {{ display: flex; flex-wrap: wrap; gap: 10px; }}
.choice {{ display: inline-flex; align-items: center; gap: 7px; padding: 9px 12px;
  border: 1px solid #666; border-radius: 7px; background: #303030; cursor: pointer; }}
.choice:has(input:checked) {{ border-color: #8dc6ff; background: #234766; }}
.choice input {{ width: 19px; height: 19px; margin: 0; }}
.hint {{ margin: 10px 0 0; color: #bbb; font-size: 14px; }}
.memo-label {{ display: block; margin-top: 16px; font-weight: 700; }}
textarea {{ width: 100%; min-height: 92px; margin-top: 7px; resize: vertical;
  border: 1px solid #666; border-radius: 8px; padding: 10px; background: #151515;
  color: white; font: inherit; }}
.saved {{ min-height: 1.4em; margin: 8px 0 0; color: #9bd4aa; }}
#modal {{ position: fixed; inset: 0; z-index: 20; display: none; align-items: center;
  justify-content: center; background: #000e; padding: 16px; }}
#modal.open {{ display: flex; }}
#modal img {{ width: min(1024px, 92vw); height: min(1024px, 88vh); object-fit: contain; }}
#modalLabel {{ position: absolute; top: 18px; left: 20px; font: 600 20px ui-monospace, monospace; }}
#close {{ position: absolute; top: 14px; right: 18px; }}
@media (max-width: 900px) {{
  header {{ grid-template-columns: 1fr 1fr; }}
  h1 {{ grid-column: 1 / -1; grid-row: 1; }}
  .content.has-reference {{ display: block; }}
  .reference {{ position: static; margin-bottom: 16px; }}
  .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
  .review-grid {{ grid-template-columns: 1fr; }}
  .wide-question {{ grid-column: auto; }}
}}
</style>
</head>
<body>
<header>
  <button id="previous">前のアセット</button>
  <h1 id="heading"></h1>
  <button id="next">次のアセット</button>
  <button id="export">CSVを書き出す</button>
</header>
<main><div id="content" class="content"></div></main>
<div id="modal" role="dialog" aria-modal="true">
  <div id="modalLabel"></div><button id="close">閉じる</button><img id="modalImage" alt="">
</div>
<script>
const assets = {encoded};
let assetIndex = 0;
let viewIndex = 0;
const content = document.getElementById('content');
const heading = document.getElementById('heading');
const modal = document.getElementById('modal');
const modalImage = document.getElementById('modalImage');
const modalLabel = document.getElementById('modalLabel');
const storageKey = 'mvl-studio-material-review-v2';
let reviews = loadReviews();

function loadReviews() {{
  try {{ return JSON.parse(localStorage.getItem(storageKey) || '{{}}'); }}
  catch (_error) {{ return {{}}; }}
}}
function currentReview() {{
  const id = assets[assetIndex].anon_id;
  if (!reviews[id]) reviews[id] = {{
    detail_lost: '', flat_surface: '', smeared_azimuths: [], color_shift: '', memo: ''
  }};
  return reviews[id];
}}
function saveReviews(message) {{
  localStorage.setItem(storageKey, JSON.stringify(reviews));
  const status = document.getElementById('saved');
  if (status) status.textContent = message || '入力内容を保存しました';
}}

function renderAsset() {{
  const asset = assets[assetIndex];
  heading.textContent = `${{asset.class_name}} ${{asset.anon_id}}`
    + (asset.is_example ? '（練習用）' : '');
  content.className = asset.reference ? 'content has-reference' : 'content';
  content.replaceChildren();
  if (asset.reference) {{
    const panel = document.createElement('aside'); panel.className = 'reference';
    const title = document.createElement('h2'); title.textContent = '入力画像（参考）';
    const image = document.createElement('img'); image.src = asset.reference; image.alt = '入力画像';
    panel.append(title, image); content.append(panel);
  }}
  const grid = document.createElement('section'); grid.className = 'grid';
  asset.views.forEach((view, index) => {{
    const button = document.createElement('button'); button.className = 'view';
    const image = document.createElement('img'); image.src = view.src; image.alt = `${{view.azimuth}}度`;
    const label = document.createElement('span'); label.className = 'azimuth';
    label.textContent = String(view.azimuth).padStart(3, '0') + '°';
    button.append(image, label); button.addEventListener('click', () => openModal(index));
    grid.append(button);
  }});
  content.append(grid);
  content.append(buildReviewForm(asset));
}}

function buildReviewForm(asset) {{
  const review = currentReview();
  const section = document.createElement('section'); section.className = 'review';
  if (asset.is_example) {{
    const note = document.createElement('p'); note.className = 'example-note';
    note.textContent = 'これは判定練習用です。集計から除外されます。';
    section.append(note);
  }}
  const layout = document.createElement('div'); layout.className = 'review-grid';

  layout.append(
    buildTriStateQuestion(
      'detail_lost', '入力画像にあった細部が消えているか',
      '模様、部品、境界など、入力画像で確認できる細部と比較します。', review
    ),
    buildTriStateQuestion(
      'flat_surface', '入力画像より表面がのっぺりしているか',
      '凹凸感や材質感が弱く、平坦に見えるかを比較します。', review
    ),
    buildTriStateQuestion(
      'color_shift', '色が明らかに違うか',
      '照明差では説明できない大きな色の違いを判定します。', review
    )
  );

  const smeared = document.createElement('fieldset'); smeared.className = 'wide-question';
  smeared.innerHTML = '<legend>特定方向だけ汚れ・にじみがある場合</legend>';
  const smearedChoices = document.createElement('div'); smearedChoices.className = 'choices';
  const values = asset.views.map(view => String(view.azimuth));
  [...values, 'なし'].forEach(value => {{
    const label = document.createElement('label'); label.className = 'choice';
    const input = document.createElement('input'); input.type = 'checkbox'; input.value = value;
    input.checked = review.smeared_azimuths.includes(value);
    input.addEventListener('change', () => {{
      if (value === 'なし' && input.checked) review.smeared_azimuths = ['なし'];
      else if (value !== 'なし' && input.checked)
        review.smeared_azimuths = [...review.smeared_azimuths.filter(item => item !== 'なし'), value];
      else review.smeared_azimuths = review.smeared_azimuths.filter(item => item !== value);
      saveReviews(); renderAsset();
    }});
    label.append(input, document.createTextNode(value === 'なし' ? value : value.padStart(3, '0') + '°'));
    smearedChoices.append(label);
  }});
  smeared.append(smearedChoices);
  layout.append(smeared); section.append(layout);

  const memoLabel = document.createElement('label'); memoLabel.className = 'memo-label';
  memoLabel.textContent = 'メモ';
  const memo = document.createElement('textarea'); memo.value = review.memo;
  memo.placeholder = '気になった点があれば記入';
  memo.addEventListener('input', () => {{ review.memo = memo.value; saveReviews(); }});
  const saved = document.createElement('p'); saved.id = 'saved'; saved.className = 'saved';
  section.append(memoLabel, memo, saved);
  return section;
}}

function buildTriStateQuestion(field, legendText, hintText, review) {{
  const question = document.createElement('fieldset');
  const legend = document.createElement('legend'); legend.textContent = legendText;
  const choices = document.createElement('div'); choices.className = 'choices';
  [['yes', 'Yes'], ['no', 'No'], ['unsure', 'Unsure']].forEach(([value, text]) => {{
    const label = document.createElement('label'); label.className = 'choice';
    const input = document.createElement('input'); input.type = 'radio';
    input.name = field; input.value = value; input.checked = review[field] === value;
    input.addEventListener('change', () => {{ review[field] = value; saveReviews(); }});
    label.append(input, document.createTextNode(text)); choices.append(label);
  }});
  const hint = document.createElement('p'); hint.className = 'hint'; hint.textContent = hintText;
  question.append(legend, choices, hint);
  return question;
}}
function openModal(index) {{ viewIndex = index; modal.classList.add('open'); renderModal(); }}
function renderModal() {{
  const view = assets[assetIndex].views[viewIndex];
  modalImage.src = view.src; modalLabel.textContent = String(view.azimuth).padStart(3, '0') + '°';
}}
function closeModal() {{ modal.classList.remove('open'); }}
document.getElementById('previous').addEventListener('click', () => {{
  assetIndex = (assetIndex - 1 + assets.length) % assets.length; renderAsset();
}});
document.getElementById('next').addEventListener('click', () => {{
  assetIndex = (assetIndex + 1) % assets.length; renderAsset();
}});
document.getElementById('export').addEventListener('click', () => {{
  const header = [
    'anon_id', 'class', 'is_example', 'detail_lost(yes/no/unsure)',
    'flat_surface(yes/no/unsure)', 'smeared_azimuths',
    'color_shift(yes/no/unsure)', 'memo'
  ];
  const escapeCsv = value => '"' + String(value ?? '').replaceAll('"', '""') + '"';
  const lines = [header.map(escapeCsv).join(',')];
  assets.forEach(asset => {{
    const review = reviews[asset.anon_id] || {{
      detail_lost: '', flat_surface: '', smeared_azimuths: [], color_shift: '', memo: ''
    }};
    const smeared = review.smeared_azimuths.includes('なし')
      ? 'なし'
      : asset.views.map(view => String(view.azimuth))
          .filter(value => review.smeared_azimuths.includes(value)).join(',');
    lines.push([
      asset.anon_id, asset.class_name, asset.is_example ? 'yes' : 'no',
      review.detail_lost, review.flat_surface, smeared, review.color_shift, review.memo
    ].map(escapeCsv).join(','));
  }});
  const csvText = String.fromCharCode(0xfeff)
    + lines.join(String.fromCharCode(13, 10));
  const blob = new Blob([csvText], {{ type: 'text/csv;charset=utf-8' }});
  const link = document.createElement('a'); link.href = URL.createObjectURL(blob);
  link.download = 'studio_review_completed.csv'; link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}});
document.getElementById('close').addEventListener('click', closeModal);
modal.addEventListener('click', event => {{ if (event.target === modal) closeModal(); }});
document.addEventListener('keydown', event => {{
  if (!modal.classList.contains('open')) return;
  if (event.key === 'Escape') closeModal();
  if (event.key === 'ArrowLeft') {{ viewIndex = (viewIndex + 7) % 8; renderModal(); }}
  if (event.key === 'ArrowRight') {{ viewIndex = (viewIndex + 1) % 8; renderModal(); }}
}});
renderAsset();
</script>
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="単独判定用HTMLビューアを生成する")
    parser.add_argument("capture_root", type=Path)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--html", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--input-map", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260930)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    capture_root = args.capture_root.resolve()
    html_path = args.html.resolve()
    assets = discover_assets(capture_root)
    references, input_rows = discover_input_images(
        repo_root, assets, capture_root, html_path.parent
    )

    randomizer = random.Random(args.seed)
    asset_lookup = {str(asset["asset"]): asset for asset in assets}
    missing_examples = [name for name in EXAMPLE_ASSETS if name not in asset_lookup]
    if missing_examples:
        raise ValueError(f"練習用アセットが見つかりません: {missing_examples}")
    example_assets = [asset_lookup[name] for name in EXAMPLE_ASSETS]
    review_assets = [
        asset for asset in assets if str(asset["asset"]) not in EXAMPLE_ASSETS
    ]
    randomizer.shuffle(review_assets)
    assets = example_assets + review_assets
    html_data: list[dict[str, object]] = []
    key_rows: list[dict[str, object]] = []
    template_rows: list[dict[str, object]] = []
    for order, asset in enumerate(assets, start=1):
        asset_name = str(asset["asset"])
        anon_id = f"#{order:02d}"
        class_name = str(asset["class"])
        is_example = asset_name in EXAMPLE_ASSETS
        views = [
            {
                "azimuth": azimuth,
                "src": browser_path(path, html_path.parent),
            }
            for azimuth, path in zip(AZIMUTHS, asset["images"], strict=True)
        ]
        reference = references[asset_name]
        html_data.append(
            {
                "anon_id": anon_id,
                "class_name": class_name,
                "is_example": is_example,
                "views": views,
                "reference": browser_path(reference, html_path.parent)
                if reference is not None
                else "",
            }
        )
        key_rows.append(
            {
                "anon_id": anon_id,
                "class": class_name,
                "asset": asset_name,
                "display_order": order,
                "is_example": "yes" if is_example else "no",
            }
        )
        template_rows.append(
            {
                "anon_id": anon_id,
                "class": class_name,
                "is_example": "yes" if is_example else "no",
                "detail_lost(yes/no/unsure)": "",
                "flat_surface(yes/no/unsure)": "",
                "smeared_azimuths": "",
                "color_shift(yes/no/unsure)": "",
                "memo": "",
            }
        )

    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(build_html(html_data), encoding="utf-8")
    write_csv(
        args.key.resolve(),
        ("anon_id", "class", "asset", "display_order", "is_example"),
        key_rows,
    )
    write_csv(
        args.template.resolve(),
        (
            "anon_id", "class", "is_example",
            "detail_lost(yes/no/unsure)",
            "flat_surface(yes/no/unsure)",
            "smeared_azimuths",
            "color_shift(yes/no/unsure)",
            "memo",
        ),
        template_rows,
    )
    write_csv(
        args.input_map.resolve(),
        ("asset", "input_image", "evidence", "source_record"),
        input_rows,
    )
    found = sum(row["input_image"] != "なし" for row in input_rows)
    print(f"HTML: {html_path}")
    print(f"Assets: {len(assets)}")
    print(f"Input images found: {found}/{len(input_rows)}")
    print(f"Input map: {args.input_map.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
