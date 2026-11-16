import { useEffect, useMemo, useRef } from "react";
import type { Graph, GraphNode } from "../api/types";

/* ------------------------------------------------------------------ canvas plumbing */

export const FONT = `-apple-system, BlinkMacSystemFont, "SF Pro Text", Inter, sans-serif`;

/** Fits a canvas to its box at device resolution and runs `draw` every frame. */
export function useCanvas(draw: (ctx: CanvasRenderingContext2D, w: number, h: number, t: number) => void) {
  const ref = useRef<HTMLCanvasElement>(null);
  const drawRef = useRef(draw);
  drawRef.current = draw;
  useEffect(() => {
    const c = ref.current!;
    const ctx = c.getContext("2d")!;
    let w = 0, h = 0, raf = 0;
    const fit = () => {
      const r = c.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      w = r.width; h = r.height;
      c.width = Math.round(w * dpr); c.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(c);
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const loop = (ms: number) => {
      ctx.clearRect(0, 0, w, h);
      drawRef.current(ctx, w, h, still ? 0 : ms / 1000);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => { cancelAnimationFrame(raf); ro.disconnect(); };
  }, []);
  return ref;
}

export function scoreColor(s: number | null): string {
  const v = s ?? 0;
  if (v >= 0.7) return "#f0524d";
  if (v >= 0.55) return "#f07b2e";
  if (v >= 0.35) return "#f5a524";
  if (v >= 0.15) return "#ecc94b";
  return "#6c8fc7";
}

export function glow(ctx: CanvasRenderingContext2D, x: number, y: number, r: number, color: string, alpha: number) {
  const g = ctx.createRadialGradient(x, y, 0, x, y, r);
  g.addColorStop(0, color + Math.round(alpha * 255).toString(16).padStart(2, "0"));
  g.addColorStop(1, color + "00");
  ctx.fillStyle = g;
  ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
}

/* ------------------------------------------------------------------ account constellation */

interface SimNode extends GraphNode { x: number; y: number; vx: number; vy: number; deg: number; r: number; pinned?: boolean }

function buildSim(graph: Graph, center: string) {
  const deg = new Map<string, number>();
  const adj = new Map<string, Set<string>>();
  for (const n of graph.nodes) adj.set(n.id, new Set());
  for (const e of graph.edges) {
    deg.set(e.source, (deg.get(e.source) ?? 0) + 1);
    deg.set(e.target, (deg.get(e.target) ?? 0) + 1);
    adj.get(e.source)?.add(e.target);
    adj.get(e.target)?.add(e.source);
  }
  const nodes: SimNode[] = graph.nodes.map((n, i) => {
    const d = deg.get(n.id) ?? 0;
    const a = i * 2.399963; // golden angle: an even, deterministic spread to start from
    const rad = n.id === center ? 0 : 90 + 26 * Math.sqrt(i + 1);
    return { ...n, x: Math.cos(a) * rad, y: Math.sin(a) * rad, vx: 0, vy: 0, deg: d, r: n.id === center ? 11 : 4.5 + Math.min(7, Math.sqrt(d) * 1.6) };
  });
  const index = new Map(nodes.map((n) => [n.id, n]));
  const links = graph.edges.flatMap((e) => { const a = index.get(e.source), b = index.get(e.target); return a && b ? [{ a, b, e }] : []; });
  return { nodes, links, adj };
}

export default function GraphScene({ graph, center, selected, onSelect, onRecenter, payment, compact }: {
  graph: Graph; center: string; selected: string; onSelect: (id: string) => void; onRecenter: (id: string) => void; payment?: { from: string; to: string } | null; compact?: boolean;
}) {
  const sim = useMemo(() => buildSim(graph, center), [graph, center]);
  const st = useRef({ k: 1, tx: 0, ty: 0, auto: true, alpha: 1, hover: null as SimNode | null, drag: null as null | { node: SimNode | null; x: number; y: number; moved: boolean } });
  const simRef = useRef(sim);
  simRef.current = sim;
  useEffect(() => { st.current.alpha = 1; st.current.auto = true; }, [sim]);

  const canvasRef = useCanvas((ctx, w, h, t) => {
    const s = st.current;
    const { nodes, links, adj } = sim;
    const dense = nodes.length > 40;

    // physics: repulsion, springs along links, a weak pull to the middle
    const alpha = Math.max(s.alpha, 0.012);
    for (let i = 0; i < nodes.length; i++) {
      const a = nodes[i];
      for (let j = i + 1; j < nodes.length; j++) {
        const b = nodes[j];
        let dx = a.x - b.x, dy = a.y - b.y;
        const d2 = dx * dx + dy * dy + 0.5;
        const f = (2400 * alpha) / d2, d = Math.sqrt(d2);
        dx = (dx / d) * f; dy = (dy / d) * f;
        a.vx += dx; a.vy += dy; b.vx -= dx; b.vy -= dy;
      }
    }
    for (const { a, b } of links) {
      const dx = b.x - a.x, dy = b.y - a.y, d = Math.sqrt(dx * dx + dy * dy) || 1;
      const f = (d - 70) * 0.012 * alpha;
      a.vx += (dx / d) * f; a.vy += (dy / d) * f; b.vx -= (dx / d) * f; b.vy -= (dy / d) * f;
    }
    for (const n of nodes) {
      n.vx -= n.x * 0.004 * alpha; n.vy -= n.y * 0.004 * alpha;
      n.vx *= 0.82; n.vy *= 0.82;
      if (!n.pinned) { n.x += n.vx; n.y += n.vy; }
    }
    s.alpha *= 0.994;

    // frame the constellation until the user takes over the camera
    if (s.auto && nodes.length) {
      let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
      for (const n of nodes) { x0 = Math.min(x0, n.x); x1 = Math.max(x1, n.x); y0 = Math.min(y0, n.y); y1 = Math.max(y1, n.y); }
      const k = Math.min(2.4, Math.max(0.2, Math.min((w - (compact ? 140 : 440)) / Math.max(x1 - x0, 80), (h - (compact ? 110 : 240)) / Math.max(y1 - y0, 80))));
      s.k += (k - s.k) * 0.08;
      s.tx += ((compact ? 0 : -160) - ((x0 + x1) / 2) * s.k - s.tx) * 0.08;
      s.ty += ((compact ? 0 : 14) - ((y0 + y1) / 2) * s.k - s.ty) * 0.08;
    }

    ctx.save();
    ctx.translate(w / 2 + s.tx, h / 2 + s.ty);
    ctx.scale(s.k, s.k);
    const focus = s.hover?.id ?? selected;
    const near = adj.get(focus);

    links.forEach(({ a, b, e }, i) => {
      const lit = e.source === focus || e.target === focus;
      const pay = !!payment && e.type === "transaction" && ((e.source === payment.from && e.target === payment.to) || (e.source === payment.to && e.target === payment.from));
      ctx.strokeStyle = lit ? "rgba(130,180,255,0.9)" : `rgba(150,170,230,${dense ? 0.1 : 0.2})`;
      if (focus && !lit) ctx.globalAlpha = 0.35;
      ctx.lineWidth = (lit ? 1.6 : 0.8) + Math.min(2.5, Math.log2(e.weight + 1) / 2);
      if (pay) { ctx.strokeStyle = `rgba(255,255,255,${0.7 + 0.3 * Math.sin(t * 6)})`; ctx.lineWidth = 3.5; ctx.globalAlpha = 1; }
      ctx.setLineDash(e.type === "shared_device" ? [6, 5] : e.type === "repeated_counterparty" ? [1.5, 5] : []);
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
      ctx.globalAlpha = 1;
      if (e.type === "transaction") { // money moving, source -> target
        const p = (t * 0.22 + i * 0.37) % 1;
        ctx.fillStyle = lit ? "#fff" : scoreColor(a.max_score);
        ctx.globalAlpha = focus && !lit ? 0.25 : 0.95;
        ctx.beginPath(); ctx.arc(a.x + (b.x - a.x) * p, a.y + (b.y - a.y) * p, lit ? 2.6 : 1.9, 0, Math.PI * 2); ctx.fill();
        ctx.globalAlpha = 1;
      }
    });
    ctx.setLineDash([]);

    nodes.forEach((n, i) => {
      const x = n.x + Math.sin(t * 0.8 + i) * 1.1, y = n.y + Math.cos(t * 0.7 + i * 1.7) * 1.1;
      const c = scoreColor(n.max_score);
      const dim = !!focus && n.id !== focus && !near?.has(n.id);
      ctx.globalAlpha = dim ? 0.3 : 1;
      glow(ctx, x, y, n.r * 4.2, c, 0.38);
      if ((n.max_score ?? 0) >= 0.55) { // risk ring, breathing
        ctx.strokeStyle = c; ctx.lineWidth = 1;
        ctx.globalAlpha = (dim ? 0.3 : 1) * (0.55 - 0.35 * Math.sin(t * 2 + i));
        ctx.beginPath(); ctx.arc(x, y, n.r + 5 + 2.5 * Math.sin(t * 2 + i), 0, Math.PI * 2); ctx.stroke();
        ctx.globalAlpha = dim ? 0.3 : 1;
      }
      ctx.fillStyle = c;
      ctx.beginPath(); ctx.arc(x, y, n.r, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "rgba(255,255,255,0.55)";
      ctx.beginPath(); ctx.arc(x - n.r * 0.28, y - n.r * 0.3, n.r * 0.38, 0, Math.PI * 2); ctx.fill();
      if (n.account_type === "merchant") { ctx.strokeStyle = "rgba(255,255,255,.85)"; ctx.lineWidth = 1.4; ctx.strokeRect(x - n.r - 3, y - n.r - 3, (n.r + 3) * 2, (n.r + 3) * 2); }
      if (n.known_fraud) { ctx.strokeStyle = "#e0436f"; ctx.lineWidth = 2; ctx.setLineDash([3, 3]); ctx.beginPath(); ctx.arc(x, y, n.r + 8, 0, Math.PI * 2); ctx.stroke(); ctx.setLineDash([]); }
      if (n.id === selected || n.id === center) { ctx.strokeStyle = "#fff"; ctx.lineWidth = n.id === selected ? 2.2 : 1.2; ctx.beginPath(); ctx.arc(x, y, n.r + 3, 0, Math.PI * 2); ctx.stroke(); }
      const label = n.id === focus || n.id === center || near?.has(n.id) || (!dense && s.k > 0.8) || (s.k > 1.6 && (n.max_score ?? 0) >= 0.55);
      if (label) {
        ctx.font = `500 ${11.5 / s.k}px ${FONT}`; ctx.textAlign = "center"; ctx.fillStyle = "rgba(255,255,255,0.92)";
        ctx.fillText(n.id, x, y - n.r - 9 / s.k);
      }
      ctx.globalAlpha = 1;
    });
    ctx.restore();
  });

  /* interaction: hover, drag a node, pan the background, wheel-zoom, click to inspect, double-click to re-centre */
  const world = (e: { clientX: number; clientY: number }) => {
    const r = canvasRef.current!.getBoundingClientRect(), s = st.current;
    return { x: (e.clientX - r.left - r.width / 2 - s.tx) / s.k, y: (e.clientY - r.top - r.height / 2 - s.ty) / s.k };
  };
  const pick = (e: { clientX: number; clientY: number }) => {
    const p = world(e), pad = 6 / st.current.k;
    const ns = simRef.current.nodes;
    for (let i = ns.length - 1; i >= 0; i--) if ((ns[i].x - p.x) ** 2 + (ns[i].y - p.y) ** 2 < (ns[i].r + pad) ** 2) return ns[i];
    return null;
  };
  useEffect(() => {
    const c = canvasRef.current!;
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      const s = st.current, r = c.getBoundingClientRect();
      const k = Math.min(4, Math.max(0.15, s.k * Math.exp(-e.deltaY * 0.0015)));
      const cx = e.clientX - r.left - r.width / 2, cy = e.clientY - r.top - r.height / 2;
      s.tx = cx - ((cx - s.tx) * k) / s.k; s.ty = cy - ((cy - s.ty) * k) / s.k; s.k = k; s.auto = false;
    };
    c.addEventListener("wheel", wheel, { passive: false });
    return () => c.removeEventListener("wheel", wheel);
  }, [canvasRef]);

  return (
    <canvas ref={canvasRef} aria-label={`Account network around ${center}: ${graph.nodes.length} accounts, ${graph.edges.length} links`} role="img"
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture(e.pointerId);
        const node = pick(e);
        if (node) { node.pinned = true; st.current.alpha = Math.max(st.current.alpha, 0.35); }
        st.current.drag = { node, x: e.clientX, y: e.clientY, moved: false };
      }}
      onPointerMove={(e) => {
        const s = st.current, d = s.drag;
        if (!d) { s.hover = pick(e); e.currentTarget.style.cursor = s.hover ? "pointer" : "grab"; return; }
        const dx = e.clientX - d.x, dy = e.clientY - d.y;
        if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
        if (d.node) { const p = world(e); d.node.x = p.x; d.node.y = p.y; d.node.vx = d.node.vy = 0; s.alpha = Math.max(s.alpha, 0.3); }
        else { s.tx += dx; s.ty += dy; s.auto = false; d.x = e.clientX; d.y = e.clientY; }
      }}
      onPointerUp={() => {
        const d = st.current.drag;
        if (d?.node) { d.node.pinned = false; if (!d.moved) onSelect(d.node.id); }
        st.current.drag = null;
      }}
      onPointerLeave={() => { st.current.hover = null; }}
      onDoubleClick={(e) => { const n = pick(e); if (n) onRecenter(n.id); }}
    />
  );
}
