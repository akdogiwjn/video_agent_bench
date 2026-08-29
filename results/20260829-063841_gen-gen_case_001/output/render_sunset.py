#!/usr/bin/env python3
"""Procedural sunset film renderer.

Renders 4 shots (5 s each @ 30 fps) of a sunset progression:
  shot 0: golden hour   shot 1: fiery orange/crimson
  shot 2: crimson/lavender fading   shot 3: deep indigo nightfall with stars

Frames are written as PNG sequences per shot; ffmpeg then crossfades them
into the final H.264 MP4.
"""
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np
from PIL import Image

W, H = 1280, 720
FPS = 30
SHOT_LEN = 5.0          # seconds per shot
SHOTS = 4
TOTAL = SHOTS * SHOT_LEN
NF_SHOT = int(SHOT_LEN * FPS)

NW, NH = 384, 216       # low-res cloud field resolution

OUTDIR = "/workspace/output"
FRAMES = os.path.join(OUTDIR, "frames")

# ----------------------------------------------------------------------------
# Color palettes (keyframed over global time t in [0, 1])
# SKY entries: (t, top, mid, bottom)
SKY = [
    (0.00, (62, 96, 138), (242, 166, 90), (255, 216, 155)),   # golden hour
    (0.25, (74, 59, 107), (232, 93, 60), (255, 179, 71)),     # fiery
    (0.50, (46, 42, 74), (176, 74, 107), (245, 126, 92)),     # crimson/lavender
    (0.75, (16, 24, 48), (30, 42, 74), (66, 82, 128)),        # indigo twilight
    (1.00, (8, 12, 26), (16, 22, 42), (36, 42, 70)),          # nightfall
]
CLOUD = [
    (0.00, (255, 238, 210)),
    (0.25, (255, 212, 158)),
    (0.50, (236, 156, 120)),
    (0.75, (150, 118, 148)),
    (1.00, (62, 66, 96)),
]
SUN_X = [0.52, 0.44, 0.60, 0.50]       # horizontal sun position per shot
GROUND_SEED = [7, 9, 11, 13]

# Cloud layers: fx/fy = feature size (low-res px, stretch -> wisps), octaves,
# seed, mask thresholds, opacity, drift speed (field units / s)
LAYERS = [
    dict(fx=95.0, fy=26.0, oct=4, seed=11, t0=0.40, t1=0.66, amp=0.90, sp=(0.022, 0.008)),
    dict(fx=60.0, fy=18.0, oct=4, seed=22, t0=0.54, t1=0.76, amp=0.80, sp=(0.045, 0.005)),
    dict(fx=34.0, fy=14.0, oct=3, seed=33, t0=0.60, t1=0.82, amp=0.50, sp=(0.070, 0.004)),
]

WARM = np.array([1.0, 0.72, 0.42], np.float32)      # sun glow color
WARM_DISC = np.array([1.0, 0.87, 0.62], np.float32)
RAY_COL = np.array([1.0, 0.78, 0.48], np.float32)
STAR_COL = np.array([0.88, 0.90, 1.0], np.float32)
GROUND_COL = np.array([14, 16, 26], np.float32)


def smoothstep(a, b, x):
    x = np.clip((x - a) / (b - a), 0.0, 1.0)
    return x * x * (3 - 2 * x)


def pal(t, keys):
    """Lerp keyframed palettes -> np array (C, 3)."""
    ts = np.array([k[0] for k in keys])
    cols = np.array([[k[i] for i in range(1, len(k))] for k in keys], np.float32)
    out = np.zeros((cols.shape[1], 3), np.float32)
    for c in range(cols.shape[1]):
        for ch in range(3):
            out[c, ch] = np.interp(t, ts, cols[:, c, ch])
    return out


def pal1(t, keys):
    return pal(t, keys)[0]


class Noise:
    """Seamless (tileable in both axes) value noise on the low-res grid."""

    def __init__(self, seed):
        self.rng = np.random.default_rng(seed)

    def value(self, shape, fx, fy):
        h, w = shape
        Lw = max(2, int(round(w / fx)))
        Lh = max(2, int(round(h / fy)))
        lat = self.rng.random((Lh, Lw)).astype(np.float32)
        x = np.arange(w, dtype=np.float32) * Lw / w
        y = np.arange(h, dtype=np.float32) * Lh / h
        xi = np.floor(x).astype(np.int32)
        yi = np.floor(y).astype(np.int32)
        xf = (x - xi).astype(np.float32)
        yf = (y - yi).astype(np.float32)
        xi %= Lw
        yi %= Lh
        xf = (xf * xf * (3 - 2 * xf))[None, :]
        yf = (yf * yf * (3 - 2 * yf))[:, None]
        xip = (xi + 1) % Lw
        yip = (yi + 1) % Lh
        v00 = lat[np.ix_(yi, xi)]
        v01 = lat[np.ix_(yi, xip)]
        v10 = lat[np.ix_(yip, xi)]
        v11 = lat[np.ix_(yip, xip)]
        return (v00 * (1 - xf) + v01 * xf) * (1 - yf) + (v10 * (1 - xf) + v11 * xf) * yf


def fbm(shape, fx, fy, octaves, seed):
    n = Noise(seed)
    out = np.zeros(shape, np.float32)
    amp, f, norm = 1.0, 1.0, 0.0
    for _ in range(octaves):
        out += amp * n.value(shape, fx * f, fy * f)
        norm += amp
        amp *= 0.5
        f *= 2.0
    return out / norm


def ground_top(seed, w=W, base=34.0, amp=30.0):
    """Per-column y of the silhouette ridge top."""
    rng = np.random.default_rng(seed)
    L = 48
    lat = rng.random(L).astype(np.float32)
    x = np.arange(w, dtype=np.float32) * L / w
    xi = np.floor(x).astype(np.int32) % L
    xf = x - xi
    xf = xf * xf * (3 - 2 * xf)
    v0 = lat[xi]
    v1 = lat[(xi + 1) % L]
    return H - base - amp * (v0 + (v1 - v0) * xf)


def star_field(seed, n=240):
    rng = np.random.default_rng(seed)
    xs = rng.random(n) * W
    ys = rng.random(n) * H * 0.62
    ph = rng.random(n) * 2 * np.pi
    mag = 0.5 + rng.random(n) * 0.5
    return xs, ys, ph, mag


def sun_params(t):
    if t < 0.6:
        y = 0.56 + (1.20 - 0.56) * (t / 0.6) * 0.9
    else:
        y = 1.136 + 0.12 * (t - 0.6) / 0.4
    inten = 1.0 if t < 0.55 else max(0.0, 1.0 - (t - 0.55) / 0.30)
    sigma = 220.0 - 130.0 * min(1.0, t / 0.6)
    if t > 0.6:
        sigma = 90.0 - 50.0 * (t - 0.6) / 0.4
    disc_r = max(6.0, 44.0 - 60.0 * t)
    return y, inten, sigma, disc_r


# ----------------------------------------------------------------------------

def render_frame(s, ts, gtop, stars):
    t = (s * SHOT_LEN + ts) / TOTAL
    top, mid, bot = pal(t, SKY)
    cloud_base = pal1(t, CLOUD)
    sun_y, inten, sigma, disc_r = sun_params(t)
    sun_x = SUN_X[s] * W
    sun_y_px = sun_y * H

    # --- sky gradient -------------------------------------------------------
    h = np.linspace(0.0, 1.0, H, dtype=np.float32)[:, None]
    sky = np.where(h < 0.5,
                   bot + (mid - bot) * (h * 2.0),
                   mid + (top - mid) * ((h - 0.5) * 2.0))
    sky = np.broadcast_to(sky[:, None, :], (H, W, 3)).copy()

    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d2 = (xx - sun_x) ** 2 + (yy - sun_y_px) ** 2

    # --- sun glow / disc / god rays ----------------------------------------
    if inten > 0.01:
        glow = np.exp(-d2 / (2.0 * sigma ** 2))
        core = np.exp(-d2 / (2.0 * (max(disc_r * 0.35, 3.0)) ** 2))
        sky += (glow * inten)[..., None] * WARM
        sky += (core * inten * 1.3)[..., None] * WARM_DISC
        if sun_y_px < H:
            disc = d2 < disc_r ** 2
            sky += (disc * inten * 1.6)[..., None] * WARM_DISC
        a = np.arctan2(yy - sun_y_px, xx - sun_x)
        streak = np.maximum(0.0, np.cos(6.0 * a)) ** 20
        fall = np.exp(-np.sqrt(d2) / 500.0)
        sky += (streak * fall * 0.13 * inten)[..., None] * RAY_COL

    glow_norm = np.exp(-d2 / (2.0 * (sigma * 1.4) ** 2))

    # --- clouds -------------------------------------------------------------
    for L in LAYERS:
        field = fbm((NH, NW), L["fx"], L["fy"], L["oct"], L["seed"])
        rx = int(L["sp"][0] * ts * NW)
        ry = int(L["sp"][1] * ts * NH)
        if rx:
            field = np.roll(field, rx, axis=1)
        if ry:
            field = np.roll(field, ry, axis=0)
        mask = smoothstep(L["t0"], L["t1"], field).astype(np.float32)
        mimg = Image.fromarray((mask * 255.0).astype(np.uint8)).resize((W, H), Image.LANCZOS)
        mask = np.asarray(mimg, np.float32) / 255.0
        lit = 0.50 + 0.50 * glow_norm * inten
        col = cloud_base[None, None, :] * lit[..., None] * 1.12
        col *= (0.78 + 0.22 * (yy / H))[..., None]          # darker lower edges
        alpha = (mask * L["amp"])[..., None]
        sky = sky * (1.0 - alpha) + col * alpha

    # --- stars --------------------------------------------------------------
    sa = smoothstep(0.62, 0.82, t)
    if sa > 0.005:
        st = np.zeros((H, W, 3), np.float32)
        r2 = disc_r if disc_r > 6 else 6.0
        rad = int(max(2, r2 * 0.12))
        s = 2 * rad + 1
        yy0, xx0 = np.mgrid[-rad:rad + 1, -rad:rad + 1].astype(np.float32)
        stamp = np.exp(-(xx0 ** 2 + yy0 ** 2) / (2.0 * (rad * 0.55) ** 2))
        stamp = stamp[..., None] * STAR_COL[None, None, :]
        for k in range(len(stars[0])):
            tw = 0.55 + 0.45 * np.sin(ts * 3.0 + stars[2][k])
            b = stars[3][k] * tw * sa
            if b < 0.04:
                continue
            xc, yc = int(stars[0][k]), int(stars[1][k])
            x0, y0 = xc - rad, yc - rad
            x1, y1 = xc + rad + 1, yc + rad + 1
            if x0 < 0 or y0 < 0 or x1 > W or y1 > H:
                continue
            st[y0:y1, x0:x1] += stamp * b
        sky += st

    # --- ground silhouette --------------------------------------------------
    gmask = yy >= gtop[None, :]
    sky = np.where(gmask[..., None], GROUND_COL, sky)
    rim = (yy >= gtop[None, :]) & (yy < gtop[None, :] + 3.0)
    gtop_glow = np.exp(-((gtop - sun_y_px) ** 2) / (2.0 * sigma ** 2)) * inten
    sky += (rim[..., None] * (WARM * 0.9) * gtop_glow[None, :, None])

    # --- vignette -----------------------------------------------------------
    r = np.sqrt(((xx - W / 2.0) / (W / 2.0)) ** 2 + ((yy - H / 2.0) / (H / 2.0)) ** 2)
    sky *= (1.0 - 0.16 * np.clip(r, 0.0, 1.2) ** 2.2)[..., None]

    img = Image.fromarray(np.clip(sky, 0, 255).astype(np.uint8), "RGB")

    # --- camera: subtle zoom per shot ---------------------------------------
    if s % 2 == 0:
        z = 1.0 + 0.05 * smoothstep(0.0, SHOT_LEN, ts)
    else:
        z = 1.05 - 0.05 * smoothstep(0.0, SHOT_LEN, ts)
    dx = 8.0 * math.sin(ts * 0.7 + s * 1.3)
    cw, ch = W / z, H / z
    x0 = int(min(max(W / 2 + dx - cw / 2, 0), W - cw))
    y0 = int(min(max(H / 2 - ch / 2, 0), H - ch))
    img = img.crop((x0, y0, x0 + int(cw), y0 + int(ch))).resize((W, H), Image.LANCZOS)
    return img


def render_shot(s):
    out = os.path.join(FRAMES, f"shot{s}")
    os.makedirs(out, exist_ok=True)
    gtop = ground_top(GROUND_SEED[s])
    stars = star_field(500 + s * 101)
    for i in range(NF_SHOT):
        ts = i / FPS
        img = render_frame(s, ts, gtop, stars)
        img.save(os.path.join(out, f"{i:04d}.png"))
        if i % 50 == 0:
            print(f"shot {s}: {i}/{NF_SHOT}", flush=True)
    print(f"shot {s} done", flush=True)
    return s


def main():
    os.makedirs(FRAMES, exist_ok=True)
    with ProcessPoolExecutor(max_workers=4) as ex:
        list(ex.map(render_shot, range(SHOTS)))
    print("ALL SHOTS RENDERED", flush=True)


if __name__ == "__main__":
    main()
