"""Rain-field motion estimation using tiled FFT phase correlation.

For every pair of consecutive frames we estimate a displacement per tile (so a front can move
differently from a storm cell 100 km away), convert to pixels/minute, average across pairs,
fill empty tiles from the global vector and median-smooth. Cost: ~50 small FFTs per frame pair.
"""
import numpy as np

TILE = 128
STRIDE = 64
MIN_RAIN_FRACTION = 0.01


def _window(n):
    w = np.hanning(n)
    return np.outer(w, w)


_WIN = {}


def phase_shift(a, b):
    """Shift (dy, dx) such that b(y, x) ~= a(y - dy, x - dx). Returns (dy, dx, peak)."""
    n = a.shape[0]
    win = _WIN.setdefault(a.shape, _window(n) if a.shape[0] == a.shape[1] else np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1])))
    fa = np.fft.fft2(a * win)
    fb = np.fft.fft2(b * win)
    r = fb * np.conj(fa)
    r /= np.abs(r) + 1e-9
    corr = np.fft.ifft2(r).real
    iy, ix = np.unravel_index(np.argmax(corr), corr.shape)
    peak = corr[iy, ix]

    def sub(c_m, c_0, c_p):
        d = c_m - 2 * c_0 + c_p
        return 0.0 if abs(d) < 1e-12 else 0.5 * (c_m - c_p) / d

    h, w = corr.shape
    dy = iy + sub(corr[(iy - 1) % h, ix], corr[iy, ix], corr[(iy + 1) % h, ix])
    dx = ix + sub(corr[iy, (ix - 1) % w], corr[iy, ix], corr[iy, (ix + 1) % w])
    if dy > h / 2:
        dy -= h
    if dx > w / 2:
        dx -= w
    return dy, dx, peak


def _field(x):
    return np.log1p(x.astype(np.float32))


def estimate(frames, minutes, max_px_per_min):
    """frames: list of rate grids (oldest first); minutes: their times in minutes.

    Returns dict(vx, vy) arrays of shape (ny, nx) at tile centres in px/min (x east, y down),
    plus 'global' (vx, vy) and 'centres' (1-D pixel coords of tile centres).
    """
    size = frames[0].shape[0]
    starts = list(range(0, size - TILE + 1, STRIDE))
    centres = np.array(starts, dtype=np.float32) + TILE / 2
    n = len(starts)
    acc_x = np.zeros((n, n)); acc_y = np.zeros((n, n)); cnt = np.zeros((n, n))
    g_x = g_y = g_n = 0.0

    for k in range(1, len(frames)):
        dt_min = minutes[k] - minutes[k - 1]
        if dt_min <= 0 or dt_min > 20:
            continue
        a, b = _field(frames[k - 1]), _field(frames[k])
        if (a > 0).mean() > 0.002 and (b > 0).mean() > 0.002:
            dy, dx, _ = phase_shift(a, b)
            vx, vy = dx / dt_min, dy / dt_min
            if np.hypot(vx, vy) <= max_px_per_min:
                g_x += vx; g_y += vy; g_n += 1
        for j, y0 in enumerate(starts):
            for i, x0 in enumerate(starts):
                ta = a[y0:y0 + TILE, x0:x0 + TILE]
                tb = b[y0:y0 + TILE, x0:x0 + TILE]
                if (ta > 0).mean() < MIN_RAIN_FRACTION or (tb > 0).mean() < MIN_RAIN_FRACTION:
                    continue
                dy, dx, peak = phase_shift(ta, tb)
                vx, vy = dx / dt_min, dy / dt_min
                if np.hypot(vx, vy) > max_px_per_min or peak < 0.05:
                    continue
                acc_x[j, i] += vx; acc_y[j, i] += vy; cnt[j, i] += 1

    gvx = g_x / g_n if g_n else 0.0
    gvy = g_y / g_n if g_n else 0.0
    with np.errstate(invalid="ignore", divide="ignore"):
        vx = np.where(cnt > 0, acc_x / np.maximum(cnt, 1), np.nan)
        vy = np.where(cnt > 0, acc_y / np.maximum(cnt, 1), np.nan)
    vx = _smooth(np.where(np.isnan(vx), gvx, vx), cnt)
    vy = _smooth(np.where(np.isnan(vy), gvy, vy), cnt)
    return {
        "vx": vx.astype(np.float32),
        "vy": vy.astype(np.float32),
        "centres": centres,
        "global": (float(gvx), float(gvy)),
        "tiles_with_motion": int((cnt > 0).sum()),
    }


def _smooth(v, cnt):
    """3x3 median, which removes single bad tiles without blurring a real front."""
    p = np.pad(v, 1, mode="edge")
    stack = np.stack([p[dy:dy + v.shape[0], dx:dx + v.shape[1]] for dy in range(3) for dx in range(3)])
    return np.median(stack, axis=0)


def velocity_at(motion, col, row):
    """Bilinear interpolation of the tile velocity field at pixel (col, row)."""
    c = motion["centres"]

    def idx(p):
        p = float(np.clip(p, c[0], c[-1]))
        i = int(np.searchsorted(c, p, side="right") - 1)
        i = min(max(i, 0), len(c) - 2)
        t = (p - c[i]) / (c[i + 1] - c[i])
        return i, t

    i, tx = idx(col)
    j, ty = idx(row)

    def interp(f):
        return ((1 - tx) * (1 - ty) * f[j, i] + tx * (1 - ty) * f[j, i + 1]
                + (1 - tx) * ty * f[j + 1, i] + tx * ty * f[j + 1, i + 1])

    return float(interp(motion["vx"])), float(interp(motion["vy"]))
