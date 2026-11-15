"""Gemini Omni 1.1 Flash로 캐릭터 8초 반복 영상을 만든다 (첫 프레임 = 끝 프레임).

검증된 레시피(~/dev/work/appintoss/tools/hero/gen_video.py)를 따른다:
Gemini API 키 경로, google-genai >= 2.0, 같은 이미지를 두 번 넣어 루프, 오디오는 후처리에서 제거.

usage: GEMINI_KEY=... gen_omni.py <jobs.json>   # [{"id","still","theme","side","out"}]
"""
import base64
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from google import genai

import os as _os
MODEL = _os.environ.get("OMNI_MODEL", "gemini-omni-1.1-flash")

SUBJECT = {
    "a": ("a matte gray clay 3D {animal} figure with a soft zero-gloss surface", "pure white (#FFFFFF)", ""),
    "b": ("a frosted translucent {animal} mascot that glows softly amber from within", "near-black charcoal (#16171A)",
          "The amber inner glow {glow} and then settles back to exactly its starting brightness."),
    "c": ("a hand-drawn editorial ink illustration of a {animal} with brush-pen linework and light gray wash; it moves like a subtly animated drawing whose lines stay clean and never boil, flicker, or redraw",
          "warm off-white paper (#F5F4EF)", ""),
    "d": ("a flat geometric vector-style {animal} made of simple solid black and gray shapes; it moves like a crisp 2D motion-graphics character whose shapes stay rigid and flat with no shading",
          "very light gray (#F4F4F5)", ""),
    # B안 증권맨: 몸 재질만 다르고 옷은 무광 차콜 + 포인트색 넥타이
    "s1": ("an anthropomorphic {animal} stockbroker mascot with a frosted translucent body that glows softly amber from within, wearing a matte charcoal suit, white shirt, and amber necktie", "near-black charcoal (#16171A)", ""),
    "s1t": ("an anthropomorphic {animal} trader mascot with a frosted translucent body that glows softly amber from within, wearing a white dress shirt, a matte charcoal vest, and {tie} necktie", "near-black charcoal (#16171A)", ""),
    "sp": ("an anthropomorphic {animal} stockbroker mascot with a frosted pearl-white body and a soft neutral inner glow, wearing matte charcoal clothing, a white shirt, and {tie} necktie", "near-black charcoal (#16171A)", ""),
}

SUIT_CONST = ("The body glow, the clothing, and the necktie keep exactly the same brightness and colour as in the first frame for the whole clip; "
              "nothing flickers, pulses, dims, or changes colour. The clothes keep their exact cut, folds, and buttons; the necktie keeps its exact shape and its exact colour from the first frame in every frame and never turns blue, purple, gray, or any other colour.")

MOTION = {
    "bull": ("bull", "brightens slightly as the hoof is planted", """Motion - confident and assertive but restrained, like a premium app mascot making its case:
- The bull shifts its weight forward, lifts one front hoof and plants it firmly once, then exhales one small soft puff of breath from its nostrils that fades away within a second.
- Its head gives one short, firm nod as if landing a point, then returns.
- Its body breathes slightly. It never walks, turns around, or leaves its spot. Its expression stays determined and its eyes stay open."""),
    "bear": ("bear", "dims slightly on the inhale", """Motion - slow, heavy, and skeptical, like a premium app mascot weighing an argument:
- The bear takes one deep, slow breath: its chest and shoulders rise and settle heavily. Its arms stay crossed the entire time.
- Its head tilts slowly to one side with a slight skeptical squint, holds for a moment, and returns.
- It never walks, uncrosses its arms, turns around, or leaves its spot. Its eyes stay open."""),
    "bull-suit": ("bull", "", """Motion - confident and assertive but restrained, like a premium app mascot making its case:
- The bull, standing upright, leans slightly forward and gives one firm downward tap in the air with its raised hand, as if landing a point, then lets the hand drift back to where it started.
- Its head gives one short, firm nod with the tap, then returns. Its other hand stays on its hip.
- Its body breathes slightly. It never walks, turns around, or leaves its spot. Its expression stays determined and its eyes stay open."""),
    "bear-suit": ("bear", "", """Motion - slow, heavy, and skeptical, like a premium app mascot weighing an argument:
- The bear, standing upright, takes one deep, slow breath: its chest and shoulders rise and settle heavily. Its arms stay crossed the entire time.
- Its head tilts slowly to one side with a slight skeptical squint, holds for a moment, and returns.
- It never walks, uncrosses its arms, turns around, or leaves its spot. Its eyes stay open."""),
}

TEMPLATE = """[# Sources <FIRST_FRAME>@Image1 <LAST_FRAME>@Image2]
A premium character idle animation, 8 seconds, single unbroken locked-off shot, designed as a seamless loop: the video must start on the provided first frame and end on the identical last frame.
Scene: {subject}, standing in front of a flat, completely uniform {bg} backdrop with only the faint floor mark already in the first frame. No room, no horizon, no texture, no particles, no dust, no bokeh.
{motion}
- {glow_line}
- THE BACKGROUND IS COMPLETELY FROZEN. Treat the flat backdrop as a still photograph pinned in place for all 8 seconds: it must not drift, pulse, brighten, darken, or change colour, and nothing new may appear in it.
- The character keeps its exact design, material, colours, line style, and proportions in every frame. Nothing melts, stretches, wobbles, or changes shape. Horns, ears, and claws keep their exact shape.
Camera: locked-off tripod, absolutely no camera movement, no zoom, no pan, no parallax.
Lighting: constant soft even light for the whole clip, no light sweeps, no lens flares, no sparkles, no exposure changes.
In a single continuous shot, no scene cuts. Keep the character, framing, and background exactly as in the first frame. No new objects, no text on screen.
No dialogue, no music, no sound effects, completely silent.
The motion is slowest at the start and at the end. Over the last two seconds the character eases back to its exact starting pose, so the final frame matches the first frame for a perfect loop."""


def prompt_for(theme: str, side: str, const_glow: bool = False, tie: str = "an amber orange (#FF8A3D)") -> str:
    animal, glow, motion = MOTION[side]
    subj, bg, glow_tpl = SUBJECT[theme]
    glow_line = glow_tpl.format(glow=glow) if glow_tpl else "No glow, sparkle, or light effect appears at any time."
    if const_glow:
        glow_line = "The amber inner glow stays exactly as bright and as amber as in the first frame for the whole clip; it never flickers, pulses, dims, switches off, or turns gray."
    if side.endswith("-suit"):
        glow_line = SUIT_CONST
    return TEMPLATE.format(subject=subj.format(animal=animal, tie=tie), bg=bg, motion=motion, glow_line=glow_line)


def find_video(obj):
    if isinstance(obj, dict):
        if obj.get("type") == "video" and (obj.get("data") or obj.get("uri")):
            return obj
        for v in obj.values():
            r = find_video(v)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_video(v)
            if r:
                return r
    return None


def run(job: dict, key: str) -> str:
    client = genai.Client(api_key=key)
    b64 = base64.b64encode(Path(job["still"]).read_bytes()).decode()
    out = Path(job["out"])
    out.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    it = client.interactions.create(
        model=MODEL,
        input=[{"type": "image", "data": b64, "mime_type": "image/png"},
               {"type": "image", "data": b64, "mime_type": "image/png"},
               {"type": "text", "text": prompt_for(job["theme"], job["side"], job.get("const_glow", False), job.get("tie", "an amber orange (#FF8A3D)"))}],
        response_format={"type": "video", "resolution": job.get("resolution", "720p"), "aspect_ratio": "16:9"},
        api_version="v1beta",  # SDK 3.0 기본값 v1 경로에서는 생성 단계가 404를 낸다
    )
    vid = getattr(it, "output_video", None)
    data = getattr(vid, "data", None) if vid else None
    uri = getattr(vid, "uri", None) if vid else None
    if not data and not uri:
        dump = it.model_dump() if hasattr(it, "model_dump") else {}
        Path(str(out) + ".json").write_text(json.dumps(dump, default=str)[:4000])
        v = find_video(dump)
        data, uri = (v or {}).get("data"), (v or {}).get("uri")
    if data:
        out.write_bytes(base64.b64decode(data) if isinstance(data, str) else data)
    elif uri:
        import urllib.request
        sep = "&" if "?" in uri else "?"
        urllib.request.urlretrieve(uri if "key=" in uri else f"{uri}{sep}key={key}", out)
    else:
        return f"{job['id']}: no video (see {out}.json)"
    return f"{job['id']}: ok {out.stat().st_size // 1024} KB {round(time.time() - t0)}s"


def main() -> None:
    import os
    key = os.environ.get("GEMINI_KEY", "")
    if not key:
        sys.exit("GEMINI_KEY not set")
    jobs = json.loads(Path(sys.argv[1]).read_text())
    if len(sys.argv) > 2 and sys.argv[2] == "--print":
        print(prompt_for(jobs[0]["theme"], jobs[0]["side"]))
        return
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(run, j, key) for j in jobs]
        for j, f in zip(jobs, futs):
            try:
                print(f.result(), flush=True)
            except Exception as exc:  # noqa: BLE001 - report every job
                print(f"{j['id']}: FAILED {type(exc).__name__}: {str(exc)[:300]}", flush=True)


if __name__ == "__main__":
    main()
