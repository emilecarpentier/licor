"""Make an unprocessed-pixel contact sheet for independent manual annotation."""

import argparse
from pathlib import Path

from PIL import Image, ImageDraw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frames", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    frames = sorted(args.frames.glob("frame_*.png"), key=lambda p: float(p.stem[6:]))
    sheet = Image.new("RGB", (970, 110 * len(frames)), "white")
    draw = ImageDraw.Draw(sheet)
    for index, frame in enumerate(frames):
        y = index * 110
        draw.text((5, y + 35), frame.stem[6:] + " s", fill="black")
        with Image.open(frame) as image:
            for x, box in ((90, (1698, 25, 1905, 70)), (525, (1635, 1018, 1850, 1050))):
                crop = image.crop(box)
                sheet.paste(crop.resize((crop.width * 2, crop.height * 2)), (x, y))
    sheet.save(args.output)


if __name__ == "__main__":
    main()
