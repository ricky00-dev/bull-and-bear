"""캐릭터 누끼를 가안별 무대 색 16:9 캔버스에 얹어 Omni 첫/끝 프레임을 만든다.

usage: compose_stills.py <cutout.png> <theme a|b|c|d> <out.png>
"""
import sys

from PIL import Image, ImageDraw, ImageFilter

STAGE = {"a": "#FFFFFF", "b": "#16171A", "c": "#F5F4EF", "d": "#F4F4F5"}
W, H = 1280, 720


def main() -> None:
    src, theme, out = sys.argv[1], sys.argv[2], sys.argv[3]
    cut = Image.open(src).convert("RGBA")
    cut = cut.crop(cut.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox())
    target_h = int(H * 0.74)
    cut = cut.resize((round(cut.width * target_h / cut.height), target_h), Image.LANCZOS)
    canvas = Image.new("RGBA", (W, H), STAGE[theme])
    foot = H - int(H * 0.11)
    x = (W - cut.width) // 2
    # 바닥 표식: 가안의 히어로 바닥과 같은 언어
    floor = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(floor)
    fw = int(cut.width * 0.78)
    box = (W // 2 - fw // 2, foot - 16, W // 2 + fw // 2, foot + 16)
    if theme == "a":
        d.ellipse(box, fill=(17, 19, 24, 34)); floor = floor.filter(ImageFilter.GaussianBlur(12))
    elif theme == "b":
        glow = tuple(int(v) for v in sys.argv[4].split(",")) if len(sys.argv) > 4 else (255, 138, 61)
        d.ellipse(box, fill=(*glow, 40)); floor = floor.filter(ImageFilter.GaussianBlur(18))
    elif theme == "c":
        d.line((x - 40, foot, x + cut.width + 40, foot), fill=(20, 20, 20, 255), width=2)
    else:
        d.rounded_rectangle((box[0], foot - 6, box[2], foot + 6), radius=6, fill=(228, 228, 231, 255))
    canvas.alpha_composite(floor)
    canvas.alpha_composite(cut, (x, foot - cut.height + 6))
    canvas.convert("RGB").save(out)


if __name__ == "__main__":
    main()
