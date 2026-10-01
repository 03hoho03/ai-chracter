"""Export original transparent stickers as 2x lossless WebP assets."""

import json
from pathlib import Path

from PIL import Image

source_dir = Path(__file__).resolve().parent
output_dir = source_dir.parent.parent / "public" / "comment-stickers"
output_dir.mkdir(parents=True, exist_ok=True)

for asset in json.loads((source_dir / "manifest.json").read_text()):
    source = Image.open(source_dir / asset["source"]).convert("RGBA")
    assert source.getchannel("A").getextrema() == (0, 255), asset["id"]
    # Resize the whole square canvas; preserve every gesture and its padding.
    output = source.resize((256, 256), Image.Resampling.LANCZOS)
    path = output_dir / f"{asset['id']}.webp"
    output.save(path, format="WEBP", lossless=True, exact=True, method=6)
    decoded = Image.open(path).convert("RGBA")
    assert decoded.tobytes() == output.tobytes(), asset["id"]
    print(f"{asset['id']}: 256x256 RGBA, {path.stat().st_size} bytes, exact lossless")
