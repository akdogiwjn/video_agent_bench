#!/usr/bin/env python3
"""
Procedural sunset film — 5 shots, 20 s, 1280x720 @ 30 fps.
Shots: golden hour -> fiery orange -> crimson/lavender -> low sun rays -> indigo dusk.
Streams raw RGB frames into ffmpeg (libx264, yuv420p) -> final.mp4
Also dumps one preview PNG per shot for QA.
"""
import subprocess, sys, os
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter

W, H, FPS = 1280, 720, 30
DURATION = 20.0
TOTAL = int(DURATION * FPS)
OUT = "/workspace/output/final.mp4"
PREVIEW_DIR = os.path.dirname(os.path.abspath(__file__))
rng = np.random.default_rng(20260829)

# ----------------------------------------------------------------------------- palette
# (g, top, mid, horizon) RGB 0..255
PALETTE = [
    (0.00, (46, 90, 136), (232, 162, 74), (255, 217, 142)),
    (0.20, (58, 74, 122), (232, 106, 46), (255, 179, 92)),
    (0.40, (74, 58, 106), (200, 58, 74), (255, 140, 66)),
    (0.60, (46, 42, 90), (138, 58, 106), (232, 90, 58)),
    (0.80, (22, 20, 52), (58, 46, 92), (150, 84, 118)),
    (1.00, (10, 10, 30), (30, 30, 62), (90, 66, 108)),
]
# sun disc / glow color
SUN_COL = [(0.00, (255, 243, 196)), (0.35, (255, 200, 92)),
           (0.60, (255, 138, 60)), (0.75, (255, 90, 46))]
# sun vertical path (normalized y)
SUN_PATH = [(0.0, 0.44), (0.2, 0.40), (0.4, 0.32), (0.6, 0.22), (0.8, 0.08), (1.0, -0.14)]
SUN_X    = [(0.0, 0.50), (0.2, 0.62), (0.4, 0.36), (0.6, 0.55), (0.8, 0.50), (1.0, 0.50)]
SUN_R = 58.0

def lerp(a, b, t): return a + (b - a) * t

def interp_stops(stops, g):
    """stops: (g, rgb, [rgb, ...]) -> tuple of per-slot interpolated RGB tuples."""
    gs = [s[0] for s in stops]
    n_cols = len(stops[0]) - 1
    out = []
    for i in range(n_cols):
        col = tuple(np.interp(g, gs, [s[i + 1][c] for s in stops]) for c in range(3))
        out.append(col)
    return tuple(out)

def sky_gradient(g):
    top, mid, hor = interp_stops(PALETTE, g)
    t = np.linspace(0.0, 1.0, H)[:, None]          # 0 top -> 1 horizon
    w_top = np.clip(1.0 - t / 0.45, 0, 1) ** 1.3
    w_mid = np.clip(1.0 - np.abs(t - 0.45) / 0.45, 0, 1) ** 1.3
    w_hor = np.clip((t - 0.45) / 0.55, 0, 1) ** 1.3
    w_sum = w_top + w_mid + w_hor + 1e-9
    sky = (np.array(top)[None, :] * w_top + np.array(mid)[None, :] * w_mid
           + np.array(hor)[None, :] * w_hor) / w_sum
    sky = np.clip(sky, 0, 255)
    return np.broadcast_to(sky[:, None, :], (H, W, 3)).copy()

# ----------------------------------------------------------------------------- clouds
def make_field(low_w, low_h, sigma, seed):
    r = np.random.default_rng(seed)
    a = r.normal(size=(low_h, low_w))
    a = gaussian_filter(a, sigma=sigma, mode="wrap")
    a = (a - a.min()) / (a.ptp() + 1e-9)
    img = Image.fromarray((a * 255).astype(np.uint8), "L").resize((W, H), Image.BILINEAR)
    return np.asarray(img, dtype=np.float32) / 255.0

# layers: (low_w, low_h, sigma, thresh, gamma, alpha, y_center, y_sigma, base_color, speed_px, morph)
LAYERS = [
    (128, 720, (1.4, 0.5), 0.55, 1.8, 0.50, 0.62, 0.20, (215, 178, 150), 26, 0.7),
    (96, 720,  (1.4, 0.6), 0.62, 2.2, 0.55, 0.45, 0.15, (190, 150, 140), -38, 1.0),
    (64, 720,  (1.2, 0.8), 0.58, 1.6, 0.42, 0.28, 0.12, (235, 190, 165), 52, 1.4),
]
SHOT_MULT = [(1.0, 1.0), (1.3, 1.1), (0.8, 1.15), (1.2, 1.0), (0.6, 0.85)]  # speed, alpha
SHOT_ZOOM = [(1.00, 1.04), (1.00, 1.06), (1.05, 1.00), (1.00, 1.05), (1.03, 1.08)]  # start,end

fields = []
for li, (lw, lh, sig, *_) in enumerate(LAYERS):
    fields.append((make_field(lw, lh, sig, 100 + li), make_field(lw, lh, sig, 200 + li)))

def cloud_mask(layer_i, g, shot):
    (_, _, _, thresh, gamma, alpha, yc, ys, base, speed, morph) = LAYERS[layer_i]
    sp_m, al_m = SHOT_MULT[shot]
    f1, f2 = fields[layer_i]
    w = 0.5 + 0.5 * np.sin(2 * np.pi * (g * morph + 0.3 * layer_i))
    o1 = int(g * speed * sp_m * W) % W
    o2 = int(-g * speed * sp_m * 0.6 * W) % W
    field = (1 - w) * np.roll(f1, o1) + w * np.roll(f2, o2)
    m = np.clip((field - thresh) / (1 - thresh), 0, 1) ** gamma
    y = np.arange(H) / H
    env = np.exp(-0.5 * ((y - yc) / ys) ** 2)[:, None]
    return m * env, np.array(base, dtype=np.float32), alpha * al_m

def interp_color(stops, g):
    return np.array(interp_stops([(a, b) for a, b in stops], g)[0], dtype=np.float32)

# ----------------------------------------------------------------------------- stars
N_STARS = 220
star_y = rng.uniform(0.02, 0.62, N_STARS) * H
star_x = rng.uniform(0.0, 1.0, N_STARS) * W
star_s = rng.uniform(0.6, 1.6, N_STARS)
star_p = rng.uniform(0, 2 * np.pi, N_STARS)

# ----------------------------------------------------------------------------- frame
yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)

def render(g):
    shot = min(int(g * 5), 4)
    sky = sky_gradient(g)
    img = sky.copy()

    # clouds
    for li in range(len(LAYERS)):
        m, base, alpha = cloud_mask(li, g, shot)
        # warm tint near sun
        sx = float(np.interp(g, [s[0] for s in SUN_X], [s[1] for s in SUN_X]) * W)
        sy = float(np.interp(g, [s[0] for s in SUN_PATH], [s[1] for s in SUN_PATH]) * H)
        d2 = (xx - sx) ** 2 + (yy - sy) ** 2
        warm = np.exp(-d2 / (2 * 300.0 ** 2)) * 0.85
        col = base[None, None, :] * (1 - warm[..., None]) \
            + interp_color([(0.0, (255, 200, 120)), (1.0, (255, 120, 70))], g)[None, None, :] * warm[..., None]
        a = (alpha * m)[..., None]
        img = img * (1 - a) + col * a

    # sun
    sy = float(np.interp(g, [s[0] for s in SUN_PATH], [s[1] for s in SUN_PATH]) * H)
    sx = float(np.interp(g, [s[0] for s in SUN_X], [s[1] for s in SUN_X]) * W)
    d2 = (xx - sx) ** 2 + (yy - sy) ** 2
    sun_col = interp_color(SUN_COL, g)
    glow_a = np.clip(1.0 - (g - 0.80) / 0.20, 0, 1)
    img += (np.exp(-d2 / (2 * 150.0 ** 2)) * glow_a)[..., None] * sun_col * 0.55
    vis = sy > -SUN_R * 0.25
    if vis:
        disc = d2 < SUN_R ** 2
        img += disc[..., None] * np.clip(sun_col * 1.6, 0, 255)

    # god rays (low sun only)
    if sy < 0.45 * H and sy > 0.02 * H:
        ang = np.arctan2(yy - sy, xx - sx) + 0.25 * g
        rays = (0.5 + 0.5 * np.cos(7.0 * ang)) ** 5 * np.exp(-d2 / (2 * 420.0 ** 2))
        ra = 0.16 * np.clip((0.25 - sy / H) / 0.20, 0, 1) * glow_a
        img += rays[..., None] * interp_color([(0.0, (255, 220, 150)), (1.0, (255, 140, 80))], g) * ra

    # stars
    if g > 0.70:
        sa = np.clip((g - 0.70) / 0.12, 0, 1)
        for i in range(N_STARS):
            tw = 0.5 + 0.5 * np.sin(2 * np.pi * (g * 9 + star_p[i]))
            y0, x0 = int(star_y[i]), int(star_x[i])
            r = star_s[i]
            y1, y2 = max(0, y0 - 2), min(H, y0 + 3)
            x1, x2 = max(0, x0 - 2), min(W, x0 + 3)
            sub = img[y1:y2, x1:x2]
            sub += 200 * sa * (0.35 + 0.65 * tw)

    # vignette
    d2n = ((xx - W / 2) ** 2 / (W / 2) ** 2 + (yy - H / 2) ** 2 / (H / 2) ** 2)
    img *= (1.0 - 0.16 * np.clip(d2n - 0.35, 0, 1) / 0.65)[..., None]

    # shot zoom (push-in / pull-back)
    z0, z1 = SHOT_ZOOM[shot]
    loc = g * 5 - shot
    z = lerp(z0, z1, np.clip(loc, 0, 1))
    cw, ch = int(W / z), int(H / z)
    x0, y0 = (W - cw) // 2, (H - ch) // 2
    img = np.asarray(Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
                     .crop((x0, y0, x0 + cw, y0 + ch)).resize((W, H), Image.BILINEAR),
                     dtype=np.float32)
    return np.clip(img, 0, 255).astype(np.uint8)

# ----------------------------------------------------------------------------- encode
BOUND = [4, 8, 12, 16]          # shot cuts
T = 0.25                        # half-width of crossfade (s)

def frame_at(t):
    g = t / DURATION
    for b in BOUND:
        if abs(t - b) < T:
            k = (t - (b - T)) / (2 * T)
            k = k * k * (3 - 2 * k)
            A = render((b - T) / DURATION)
            B = render((b + T) / DURATION)
            return (A * (1 - k) + B * k).astype(np.uint8)
    return render(g)

# previews
for i, g in enumerate([0.06, 0.26, 0.46, 0.66, 0.93]):
    Image.fromarray(render(g)).save(os.path.join(PREVIEW_DIR, f"preview_shot{i+1}.png"))

cmd = ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
       "-r", str(FPS), "-i", "-", "-an",
       "-c:v", "libx264", "-preset", "medium", "-crf", "18",
       "-pix_fmt", "yuv420p", "-movflags", "+faststart", OUT]
proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL)
fade_in = 0.4
fade_out = 0.8
for i in range(TOTAL):
    t = i / FPS
    f = frame_at(t).astype(np.float32)
    if t < fade_in:
        f *= t / fade_in
    if t > DURATION - fade_out:
        f *= max(0.0, (DURATION - t) / fade_out)
    proc.stdin.write(f.astype(np.uint8).tobytes())
    if i % 150 == 0:
        print(f"frame {i}/{TOTAL}", flush=True)
proc.stdin.close()
rc = proc.wait()
print("ffmpeg exit:", rc)
sys.exit(rc)
