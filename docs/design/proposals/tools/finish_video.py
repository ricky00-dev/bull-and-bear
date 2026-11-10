"""Omni 원본을 웹용 루프로 마감한다 (~/dev/work/appintoss/tools/hero/finish_loop.py 방식).

1. 캐릭터 주변 타원 마스크 밖은 첫 프레임 스틸 픽셀로 고정 (배경이 페이지 색과 정확히 같게)
2. 첫 프레임과 가장 비슷한 후반 프레임에서 잘라 끊김 없는 루프
3. 960x540 h264 crf24 무음 + 포스터(인코딩본 프레임 0)

usage: finish_video.py <raw.mp4> <still.png> <out_dir> <name>
"""
import glob
import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageFilter


def main() -> None:
    raw, still_path, out_dir, name = sys.argv[1:5]
    os.makedirs(out_dir, exist_ok=True)
    still_img = Image.open(still_path).convert("RGB")
    W, H = still_img.size
    still = np.asarray(still_img, dtype=np.float32)
    bg = still[4, 4]
    diff = np.abs(still - bg).sum(axis=2) > 18
    ys, xs = np.nonzero(diff)
    cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
    rx = (xs.max() - xs.min()) / 2 + W * 0.13
    ry = (ys.max() - ys.min()) / 2 + H * 0.10
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2)
    t = np.clip((r - 0.92) / 0.16, 0, 1)
    m = (1 - t * t * (3 - 2 * t))[..., None]

    with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as tf:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", raw, "-vf", f"scale={W}:{H}", f"{td}/f_%04d.png"], check=True)
        files = sorted(glob.glob(f"{td}/f_*.png"))
        F = [np.asarray(Image.open(f).convert("RGB"), dtype=np.float32) for f in files]
        n = len(F)
        if len(sys.argv) > 7:  # 처음 자세로 안 돌아오는 테이크: [s, j) 구간 + 끝 K프레임을 시작과 겹쳐 섞기
            s, j, K = (int(v) for v in sys.argv[5:8])
            frames = [F[i] for i in range(s + K, j - K)] + [F[j - K + i] * (1 - (i + 1) / (K + 1)) + F[s + i] * ((i + 1) / (K + 1)) for i in range(K)]
            closure = float(np.abs(F[j] - F[s]).mean())
        else:
            j = min(range(int(n * 0.6), n), key=lambda k: float(np.abs(F[k] - F[0]).mean()))
            closure = float(np.abs(F[j] - F[0]).mean())
            frames = F[:j]  # j는 0과 같으므로 빼서 이음매에 같은 프레임이 두 번 나오지 않게
        # 영상 안쪽 배경이 스틸보다 미세하게 다른 색으로 렌더되면 경계가 원처럼 보인다.
        # 마스크 안쪽 고리 중 스틸에서 배경이던 픽셀로 프레임별 색 차이를 재서 전체에 보정한다.
        ring = (r > 0.62) & (r < 0.9) & (np.abs(still - bg).sum(axis=2) < 6)
        # 바꿔 넣을 바탕: 스틸에서 캐릭터가 있던 자리는 순수 바탕색 (스틸 픽셀을 쓰면 처음 자세가 잔상으로 남는다)
        char = Image.fromarray((np.abs(still - bg).sum(axis=2) > 18).astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(9))
        clean_bg = np.where((np.asarray(char) > 0)[..., None], bg, still)
        for i, f in enumerate(frames):
            model_bg = np.median(f[ring], axis=0)
            # 배경에 가까운 픽셀(비네팅·색 틀어짐)은 스틸 바탕으로, 캐릭터·발광은 그대로 (부드러운 키)
            k = np.clip((np.abs(f - model_bg).sum(axis=2, keepdims=True) - 8) / 22, 0, 1)
            f = clean_bg * (1 - k) + (f + (bg - model_bg)) * k
            out = f * m + still * (1 - m)
            Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save(f"{tf}/f_{i:04d}.png")
        j = len(frames)
        mp4 = f"{out_dir}/{name}.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "24", "-i", f"{tf}/f_%04d.png",
                        "-vf", "scale=960:540:flags=lanczos", "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
                        "-crf", "24", "-preset", "slow", "-an", "-movflags", "+faststart", mp4], check=True)
    poster = f"{out_dir}/{name}-poster.jpg"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", mp4, "-frames:v", "1", "-q:v", "3", poster], check=True)
    edge = np.asarray(Image.open(poster).convert("RGB"), dtype=np.float32)
    corner = edge[3, 3].round().astype(int).tolist()
    print(f"{name}: frames {n}->{j} closure {closure:.2f}/255 corner {corner} bg {bg.round().astype(int).tolist()} {os.path.getsize(mp4) // 1024}KB")


if __name__ == "__main__":
    main()
