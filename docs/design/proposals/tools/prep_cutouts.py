"""누끼 정리: 거의 투명한 픽셀 0으로, 여백 잘라 720px, 아바타용 얼굴 크롭 160px.

usage: prep_cutouts.py   (gen/r1, gen/r2 → assets/<theme>/)
"""
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = {"bull": "gen/r1/{k}-bull.png", "bear": "gen/r2/{k}-bear.png", "owl": "gen/r2/{k}-owl.png"}
# 얼굴 찾기 영역 (알파 bbox 대비 비율: x0, y0, x1, y1)
FACE = {"bull": (0.45, 0.0, 1.0, 0.55), "bear": (0.15, 0.0, 0.85, 0.36), "owl": (0.0, 0.0, 1.0, 0.5)}


def clean(im: Image.Image) -> Image.Image:
    a = np.asarray(im).copy()
    a[a[..., 3] < 6] = 0
    return Image.fromarray(a)


def main() -> None:
    for k in "abcd":
        out = ROOT / "assets" / k
        out.mkdir(parents=True, exist_ok=True)
        for name, pat in SRC.items():
            im = clean(Image.open(ROOT / pat.format(k=k)).convert("RGBA"))
            bb = im.getchannel("A").point(lambda v: 255 if v > 20 else 0).getbbox()
            body = im.crop(bb)
            pad = int(max(body.size) * 0.04)
            canvas = Image.new("RGBA", (body.width + pad * 2, body.height + pad * 2), (0, 0, 0, 0))
            canvas.alpha_composite(body, (pad, pad))
            canvas.thumbnail((720, 720), Image.LANCZOS)
            canvas.save(out / f"{name}.png", optimize=True)
            # 얼굴: 지정 영역 안의 알파 bbox 중심으로 정사각 크롭
            x0, y0, x1, y1 = FACE[name]
            region = (int(body.width * x0), int(body.height * y0), int(body.width * x1), int(body.height * y1))
            sub = body.crop(region)
            sb = sub.getchannel("A").point(lambda v: 255 if v > 20 else 0).getbbox()
            cx = region[0] + (sb[0] + sb[2]) / 2
            cy = region[1] + (sb[1] + sb[3]) / 2
            side = max(sb[2] - sb[0], sb[3] - sb[1]) * (1.2 if name == "owl" else 1.08)
            box = (int(cx - side / 2), int(cy - side / 2), int(cx + side / 2), int(cy + side / 2))
            face = Image.new("RGBA", (box[2] - box[0], box[3] - box[1]), (0, 0, 0, 0))
            face.alpha_composite(body.crop((max(box[0], 0), max(box[1], 0), min(box[2], body.width), min(box[3], body.height))),
                                 (max(-box[0], 0), max(-box[1], 0)))
            face.resize((160, 160), Image.LANCZOS).save(out / f"{name}-face.png", optimize=True)
        print(k, "ok")


if __name__ == "__main__":
    main()
