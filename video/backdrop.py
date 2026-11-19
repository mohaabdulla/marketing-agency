"""Animated brand backdrops for storyboard scenes that have no photo or footage.

A still gradient stays still however slowly the camera zooms into it (no detail moves), so scenes
built from it read as frozen. Here the backdrop itself moves, the way motion-graphics templates do it:
a soft brand-coloured light drifts across the frame, outline shapes float and turn slowly, and the
accent rule draws itself in. Every position is drawn at sub-pixel precision (OpenCV fixed-point
coordinates), so slow movement glides instead of stepping a whole pixel at a time."""
import math
import subprocess

import numpy as np

SHIFT = 4                      # fixed-point bits: coordinates are drawn at 1/16 px
ONE = 1 << SHIFT


def _rgb(hex_colour):
    return np.array(list(bytes.fromhex(hex_colour.lstrip('#'))), np.float32)


def _ease_out(u):
    u = min(1.0, max(0.0, u))
    return 1 - (1 - u) ** 3


def _gradient(w, h, primary, accent, style):
    """The same vertical brand gradient as the still backdrop (video.sequence.sequence_backdrop)."""
    alpha = np.zeros((h, 1, 1), np.float32) if style == 'minimal' else (.07 + .18 * np.arange(h, dtype=np.float32) / h)[:, None, None]
    return (1 - alpha) * primary + alpha * accent * np.ones((1, w, 1), np.float32)


def _glow(radius):
    """A soft round light (Gaussian falloff), used as an additive highlight."""
    axis = np.linspace(-1, 1, 2 * radius, dtype=np.float32)
    distance = axis[None, :] ** 2 + axis[:, None] ** 2
    return np.exp(-distance * 3.2)[:, :, None]


def frames(w, h, brand, index, style='brand-gradient', line_y=.72, seconds=5.0, fps=30):
    """Yield the backdrop frames (BGR uint8)."""
    import cv2
    # Colours in OpenCV's BGR order from the start, so frames need no channel swap.
    primary, accent = _rgb(brand['primary_hex'])[::-1].copy(), _rgb(brand['secondary_hex'])[::-1].copy()
    # Dither: soft dark gradients quantised to 8 bits show rings (banding). A fixed, faint noise of about
    # one level breaks the rings up; it is invisible as texture and does not flicker because it never moves.
    noise = np.repeat(np.random.default_rng(7).uniform(-.9, .9, (h, w, 1)).astype(np.float32), 3, axis=2)
    # The gradient and the light have no fine detail: they are computed at a quarter of the size and enlarged
    # (smoothly) for each frame, which is ~10x cheaper than full-size arithmetic.
    q = 4
    sw, sh = max(2, w // q), max(2, h // q)
    base = _gradient(sw, sh, primary, accent, style)
    total = max(1, round(seconds * fps))
    radius = max(2, int(max(w, h) * .45) // q)
    light = _glow(radius) * accent * (.10 if style == 'minimal' else .16)
    accent_bgr = tuple(float(c) for c in accent)
    stroke = max(2, w // 250)
    # Start points depend on the scene number so consecutive scenes do not repeat the same layout.
    shapes = [] if style == 'minimal' else [
        dict(x=w * (.12 + ((n + index) % 5) * .19), y=h * (.22 + (n % 3) * .12), r=min(w, h) * (.06 + n * .018),
             vx=w * .010 * (1 if (n + index) % 2 else -1), vy=-h * .012, spin=(8 + 4 * n) * (1 if n % 2 else -1), start=30 + 70 * n)
        for n in range(5 if style == 'geometric' else 3)]
    phase = index * 1.7
    for frame_number in range(total):
        t = frame_number / fps
        u = frame_number / max(1, total - 1)
        small = base.copy()
        # The light travels a slow arc across the upper half of the frame.
        cx = int(sw * (.25 + .5 * u if index % 2 == 0 else .75 - .5 * u))
        cy = int(sh * (.35 + .08 * math.sin(phase + 2 * math.pi * u * .5)))
        x0, y0, x1, y1 = cx - radius, cy - radius, cx + radius, cy + radius
        sx0, sy0, sx1, sy1 = max(0, x0), max(0, y0), min(sw, x1), min(sh, y1)
        if sx1 > sx0 and sy1 > sy0:
            small[sy0:sy1, sx0:sx1] += light[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0]
        # OpenCV's add and saturating conversion: ~10x faster than the NumPy equivalents at 1080p.
        image = cv2.convertScaleAbs(cv2.add(cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC), noise))
        for shape in shapes:
            centre = (round((shape['x'] + shape['vx'] * t) * ONE), round((shape['y'] + shape['vy'] * t) * ONE))
            r = shape['r']
            angle = shape['start'] + shape['spin'] * t
            if style == 'geometric':
                corners = cv2.boxPoints(((centre[0] / ONE, centre[1] / ONE), (2 * r, 2 * r), angle))
                cv2.polylines(image, [np.round(corners * ONE).astype(np.int32)], True, accent_bgr, stroke, cv2.LINE_AA, SHIFT)
            else:
                cv2.ellipse(image, centre, (round(r * ONE), round(r * ONE)), angle, 0, 270, accent_bgr, stroke, cv2.LINE_AA, SHIFT)
        if line_y is not None:
            # The accent rule draws itself in from the reading side over the first 0.8 s.
            span = .8 * w * _ease_out(t / .8)
            y = round(h * line_y * ONE)
            cv2.line(image, (round(w * .1 * ONE), y), (round((w * .1 + span) * ONE), y), accent_bgr,
                     max(3, w // 150), cv2.LINE_AA, SHIFT)
        yield image


def render(path, canvas, brand, index, style='brand-gradient', line_y=.72, seconds=5.0):
    """Encode the animated backdrop as a near-lossless H.264 clip at the canvas size and frame rate."""
    from video.ffmpeg import binary
    w, h, fps = canvas.width, canvas.height, canvas.fps
    process = subprocess.Popen([binary('ffmpeg'), '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{w}x{h}',
                                '-r', str(fps), '-i', '-', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '12',
                                '-pix_fmt', 'yuv420p', str(path)], stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for image in frames(w, h, brand, index, style, line_y, seconds, fps):
            process.stdin.write(image.tobytes())
        process.stdin.close()
        error = process.stderr.read().decode(errors='replace')
        if process.wait(timeout=300):
            raise RuntimeError('Could not encode the animated backdrop: ' + error[-400:])
    finally:
        if process.poll() is None:
            process.kill()
        process.stderr.close()
    return path
