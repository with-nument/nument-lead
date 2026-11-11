'use client'

// PixelField: generated woven colour field that twists under the cursor (auth screen art panel).
// Source: pages/login-pixelfield-brief.md §3.6. The ENGINE is verbatim; keep the constants and the
// band-clear / settle logic exactly (see brief §3.4-3.5). Only the two palettes may change for nument
// (see pages/login.md §6). Wrap it in a panel whose background shows through the parted weave (#eef2ee).
import * as React from 'react';

/** Row height in CSS pixels. Rows stay uniform; only the widths vary. */
const ROW = 16;
/** Column quantisation before run-length encoding, the smallest possible cell width. */
const COL = 16;
/** Gap between stitches inside a cell. Tight enough to read as thread, loose enough to see colour. */
const STITCH = 3;

/** How far the effect reaches from the pointer, in CSS pixels. */
const RADIUS = 175;
/** Peak displacement at the pointer, in CSS pixels. */
const PUSH = 30;
/** How far the displacement rotates around the pointer, in radians, at full strength. */
const SWIRL = 0.9;
/** Spring, not exponential decay, this is what gives the cloth weight. */
const STIFFNESS = 0.16;
const DAMPING = 0.76;
/** How fast the sampled pointer catches up to the real one. Below 1 it trails, which adds drag. */
const POINTER_EASE = 0.2;
/** How fast the effect fades in on enter and out on leave, per frame. */
const INTENSITY_EASE = 0.09;

/** Two ramps, dark to light, chosen to sit against a white page. Nument: the kit indigo family and the dusk band. */
const CANOPY = ['#0d0e2b', '#141647', '#1d2068', '#2a2f8f', '#3d47b8', '#5d73d9', '#8fa7ee'];
const WATER  = ['#13121e', '#1f2140', '#2e3566', '#435091', '#6276bd', '#8da3e0', '#c2d0f7'];

interface Cell {
  x: number; y: number; w: number; color: string;
  /** Stitch direction at rest, in radians. */
  angle: number;
  /** Current offset from rest, and its spring velocity. */
  dx: number; dy: number; vx: number; vy: number;
}

/** Deterministic hash → [0,1). Seeded so the field is identical on every load. */
function hash(x: number, y: number): number {
  const n = Math.sin(x * 127.1 + y * 311.7) * 43758.5453;
  return n - Math.floor(n);
}

/** Value noise with smooth interpolation, so posterising produces flowing bands, not confetti. */
function noise(x: number, y: number): number {
  const xi = Math.floor(x), yi = Math.floor(y);
  const xf = x - xi, yf = y - yi;
  // Smoothstep on both axes, linear interpolation leaves visible diamond artefacts at the
  // lattice points once the result is quantised.
  const u = xf * xf * (3 - 2 * xf);
  const v = yf * yf * (3 - 2 * yf);
  const a = hash(xi, yi), b = hash(xi + 1, yi);
  const c = hash(xi, yi + 1), d = hash(xi + 1, yi + 1);
  return a * (1 - u) * (1 - v) + b * u * (1 - v) + c * (1 - u) * v + d * u * v;
}

export function PixelField({ className }: { className?: string }) {
  const canvasRef = React.useRef<HTMLCanvasElement | null>(null);
  const wrapRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    let cells: Cell[] = [];
    let base: HTMLCanvasElement | null = null;
    let frame = 0;
    let size = { width: 0, height: 0 };

    // Off-canvas by default, so the field rests flat until the pointer arrives rather than
    // twisting around the top-left corner on load.
    let pointer = { x: -9999, y: -9999 };
    const smooth = { x: -9999, y: -9999 };
    let intensity = 0;
    let targetIntensity = 0;
    let dirty = false;

    /** Fills one cell with its colour and its stitches, clipped to the cell. */
    function stitch(c: CanvasRenderingContext2D, w: number, h: number, color: string, angle: number) {
      c.beginPath();
      c.rect(-w / 2, -h / 2, w, h);
      c.clip();
      c.fillStyle = color;
      // +1 closes the hairline seams that open between neighbours at sub-pixel positions.
      c.fillRect(-w / 2 - 0.5, -h / 2 - 0.5, w + 1, h + 1);

      c.rotate(angle);
      // Half-diagonal, so the stitches still span the cell once rotated to any angle.
      const reach = Math.hypot(w, h) / 2 + 2;
      c.fillStyle = 'rgba(255,255,255,0.10)';
      for (let ly = -reach; ly < reach; ly += STITCH) c.fillRect(-reach, ly, reach * 2, 1);
      c.fillStyle = 'rgba(0,0,0,0.13)';
      for (let ly = -reach + STITCH / 2; ly < reach; ly += STITCH) c.fillRect(-reach, ly, reach * 2, 1);
    }

    function build() {
      const rect = wrap!.getBoundingClientRect();
      if (rect.width < 2 || rect.height < 2) return;
      size = { width: rect.width, height: rect.height };

      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas!.width = Math.round(rect.width * dpr);
      canvas!.height = Math.round(rect.height * dpr);
      canvas!.style.width = `${rect.width}px`;
      canvas!.style.height = `${rect.height}px`;
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);

      const cols = Math.ceil(rect.width / COL);
      const rows = Math.ceil(rect.height / ROW);
      const next: Cell[] = [];
      // Kept as a grid rather than computed inline so a run always takes the angle of the
      // square it starts on, whatever its width.
      const angles = new Float32Array(cols * rows);

      for (let row = 0; row < rows; row++) {
        const vertical = row / rows;
        let runStart = 0;
        let runColor = '';

        for (let col = 0; col <= cols; col++) {
          let color = '';
          if (col < cols) {
            // Two octaves: the coarse one lays out the large shapes, the fine one breaks up the
            // band edges so they read as torn rather than drawn with a compass.
            const n = noise(col / 9, row / 9) * 0.72 + noise(col / 3.2, row / 3.2) * 0.28;
            // The ramp boundary wanders with the noise, so canopy and water interlock instead
            // of meeting on a straight horizon.
            const ramp = vertical + (n - 0.5) * 0.42 > 0.55 ? WATER : CANOPY;
            const step = Math.min(ramp.length - 1, Math.max(0, Math.floor(n * ramp.length)));
            color = ramp[step]!;
            // Four directions rather than a continuum.
            angles[row * cols + col] = (Math.floor(hash(col, row) * 4) * Math.PI) / 4;
          }

          // Run-length encode: close the current run when the colour changes or the row ends.
          if (color !== runColor) {
            if (runColor && col > runStart) {
              next.push({
                x: runStart * COL, y: row * ROW, w: (col - runStart) * COL,
                color: runColor, angle: angles[row * cols + runStart]!,
                dx: 0, dy: 0, vx: 0, vy: 0,
              });
            }
            runStart = col;
            runColor = color;
          }
        }
      }
      cells = next;

      base = document.createElement('canvas');
      base.width = canvas!.width;
      base.height = canvas!.height;
      const bctx = base.getContext('2d');
      if (!bctx) return;
      bctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      for (const cell of cells) {
        bctx.save();
        bctx.translate(cell.x + cell.w / 2, cell.y + ROW / 2);
        stitch(bctx, cell.w, ROW, cell.color, cell.angle);
        bctx.restore();
      }
    }

    function paint() {
      if (!base) { frame = requestAnimationFrame(paint); return; }

      smooth.x += (pointer.x - smooth.x) * POINTER_EASE;
      smooth.y += (pointer.y - smooth.y) * POINTER_EASE;
      intensity += (targetIntensity - intensity) * INTENSITY_EASE;

      ctx!.setTransform(1, 0, 0, 1, 0, 0);
      ctx!.clearRect(0, 0, canvas!.width, canvas!.height);
      ctx!.drawImage(base, 0, 0);
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);

      if (intensity < 0.002) {
        // Settled. Zero every cell rather than leaving stale offsets lying around, see §3.4.
        if (dirty) {
          for (const cell of cells) { cell.dx = 0; cell.dy = 0; cell.vx = 0; cell.vy = 0; }
          dirty = false;
        }
        frame = requestAnimationFrame(paint);
        return;
      }
      dirty = true;

      // CLEAR A FULL-WIDTH BAND, NOT A CLIPPED DISC, see §3.5.
      const reach = RADIUS + PUSH + 40;
      const bandTop = Math.floor(smooth.y - reach);
      const bandBottom = Math.ceil(smooth.y + reach);
      ctx!.clearRect(0, bandTop, size.width, bandBottom - bandTop);

      for (const cell of cells) {
        const cx = cell.x + cell.w / 2;
        const cy = cell.y + ROW / 2;
        const ox = cx - smooth.x;
        const oy = cy - smooth.y;
        const dist = Math.hypot(ox, oy);
        // Reject on the ROW only. The band is full width, so a run's horizontal extent cannot
        // put it outside the cleared region.
        if (cy + ROW < bandTop || cy - ROW > bandBottom) continue;

        let targetX = 0, targetY = 0;
        if (dist < RADIUS && dist > 0.01) {
          const falloff = (1 - dist / RADIUS) ** 2 * intensity;
          const angle = SWIRL * falloff;
          const sin = Math.sin(angle), cos = Math.cos(angle);
          const ux = ox / dist, uy = oy / dist;
          const magnitude = PUSH * falloff;
          targetX = (ux * cos - uy * sin) * magnitude;
          targetY = (ux * sin + uy * cos) * magnitude;
        }

        cell.vx = (cell.vx + (targetX - cell.dx) * STIFFNESS) * DAMPING;
        cell.vy = (cell.vy + (targetY - cell.dy) * STIFFNESS) * DAMPING;
        cell.dx += cell.vx;
        cell.dy += cell.vy;

        ctx!.save();
        ctx!.translate(cx + cell.dx, cy + cell.dy);
        stitch(ctx!, cell.w, ROW, cell.color, cell.angle);
        ctx!.restore();
      }

      frame = requestAnimationFrame(paint);
    }

    function onPointerMove(event: PointerEvent) {
      const rect = canvas!.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      // First contact places the smoothed pointer outright; easing it in from -9999 would drag
      // a twist diagonally across the panel on the way to the cursor.
      if (targetIntensity === 0) { smooth.x = x; smooth.y = y; }
      pointer = { x, y };
      targetIntensity = 1;
    }
    function onPointerLeave() {
      // Intensity falls to zero in place rather than the pointer flying off-canvas, so the cloth
      // relaxes where it was grabbed instead of being dragged out of frame.
      targetIntensity = 0;
    }

    build();
    paint();
    if (!reduceMotion) {
      wrap.addEventListener('pointermove', onPointerMove);
      wrap.addEventListener('pointerleave', onPointerLeave);
    }

    const observer = new ResizeObserver(() => {
      const rect = wrap.getBoundingClientRect();
      // Only a real size change: ResizeObserver also fires on sub-pixel reflows, and rebuilding
      // re-renders every cell twice over.
      if (Math.abs(rect.width - size.width) > 1 || Math.abs(rect.height - size.height) > 1) build();
    });
    observer.observe(wrap);

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      wrap.removeEventListener('pointermove', onPointerMove);
      wrap.removeEventListener('pointerleave', onPointerLeave);
    };
  }, []);

  return (
    <div ref={wrapRef} className={className}>
      {/* aria-hidden: it carries no information, and describing a twisting colour field would
          be noise on a login form. */}
      <canvas ref={canvasRef} aria-hidden className="block h-full w-full" />
    </div>
  );
}
