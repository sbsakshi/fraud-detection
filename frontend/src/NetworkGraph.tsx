import { useEffect, useRef, useState } from "react";
import { fetchGraph, type GraphSnapshot } from "./api";
import { simulateStep, type SimEdge, type SimNode } from "./graphLayout";
import { MOCK_GRAPH } from "./mockData";

const POLL_INTERVAL_MS = 5000;

// Cycled by `community % length` (app/graph/analysis.py's Louvain
// communities, computed fresh on every /graph poll) -- purely a stable
// grouping key for clustering colors, not itself a fraud signal.
const COMMUNITY_PALETTE = [
  "#5b8cff", "#e0463d", "#34d0a2", "#dd8a1f", "#b26fff",
  "#f2c94c", "#4ad2e0", "#ff6fae", "#7fd35a", "#c81e3a",
];

const EDGE_COLOR: Record<string, string> = {
  transaction: "rgba(139,163,199,0.28)",
  shared_device: "rgba(224,70,61,0.6)",
  repeated_counterparty: "rgba(178,111,255,0.6)",
};

interface Transform {
  scale: number;
  tx: number;
  ty: number;
}

function communityColor(community: number): string {
  if (community < 0) return "#8b93a7";
  return COMMUNITY_PALETTE[community % COMMUNITY_PALETTE.length];
}

function toGraphCoords(clientX: number, clientY: number, canvas: HTMLCanvasElement, t: Transform) {
  const rect = canvas.getBoundingClientRect();
  return { x: (clientX - rect.left - t.tx) / t.scale, y: (clientY - rect.top - t.ty) / t.scale };
}

function findNodeAt(nodes: SimNode[], x: number, y: number): SimNode | null {
  let best: SimNode | null = null;
  let bestDist = Infinity;
  for (const n of nodes) {
    const dist = Math.hypot(n.x - x, n.y - y);
    if (dist <= n.radius + 4 && dist < bestDist) {
      best = n;
      bestDist = dist;
    }
  }
  return best;
}

function isNeighbor(nodeId: string, focusId: string, edges: SimEdge[]): boolean {
  return edges.some(
    (e) => (e.source.id === focusId && e.target.id === nodeId) || (e.target.id === focusId && e.source.id === nodeId)
  );
}

function mergeGraph(existing: Map<string, SimNode>, snapshot: GraphSnapshot, width: number, height: number): SimEdge[] {
  const degree = new Map<string, number>();
  for (const e of snapshot.edges) {
    degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
    degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
  }

  const nextIds = new Set(snapshot.nodes.map((n) => n.id));
  for (const id of Array.from(existing.keys())) {
    if (!nextIds.has(id)) existing.delete(id);
  }

  for (const n of snapshot.nodes) {
    const nodeDegree = degree.get(n.id) ?? 0;
    const radius = 4 + Math.min(14, Math.sqrt(nodeDegree + 1) * 3);
    const prior = existing.get(n.id);
    if (prior) {
      prior.community = n.community;
      prior.trueLabel = n.trueLabel;
      prior.degree = nodeDegree;
      prior.radius = radius;
    } else {
      // New nodes ease in from a random point near the center rather than
      // all stacking at the origin, so the layout doesn't visibly "explode"
      // outward every time the feed adds an account.
      const angle = Math.random() * Math.PI * 2;
      const r = Math.random() * 80;
      existing.set(n.id, {
        id: n.id,
        x: width / 2 + Math.cos(angle) * r,
        y: height / 2 + Math.sin(angle) * r,
        vx: 0,
        vy: 0,
        radius,
        community: n.community,
        trueLabel: n.trueLabel,
        degree: nodeDegree,
        fixed: false,
      });
    }
  }

  const edges: SimEdge[] = [];
  for (const e of snapshot.edges) {
    const source = existing.get(e.source);
    const target = existing.get(e.target);
    if (source && target) edges.push({ source, target, type: e.type, weight: e.weight });
  }
  return edges;
}

interface NetworkGraphProps {
  selectedUpiId: string | null;
  onSelectAccount: (upiId: string | null) => void;
}

export default function NetworkGraph({ selectedUpiId, onSelectAccount }: NetworkGraphProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const nodesById = useRef(new Map<string, SimNode>());
  const edgesRef = useRef<SimEdge[]>([]);
  const transformRef = useRef<Transform>({ scale: 1, tx: 0, ty: 0 });
  const hoveredIdRef = useRef<string | null>(null);
  const draggingRef = useRef<SimNode | null>(null);
  const panningRef = useRef<{ lastX: number; lastY: number } | null>(null);
  const movedRef = useRef(false);
  const selectedUpiIdRef = useRef(selectedUpiId);
  selectedUpiIdRef.current = selectedUpiId;

  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [nodeCount, setNodeCount] = useState(0);
  const usingMockRef = useRef(false);

  // Poll the backend and merge into the persistent sim-node map -- kept
  // separate from the render loop below so a slow/failed fetch never stalls
  // the animation. If the backend is unreachable, or reachable but hasn't
  // scored anything yet, seed the graph with demo data once so the panel
  // isn't empty; a later successful poll with real nodes replaces it.
  useEffect(() => {
    let cancelled = false;

    function seedMock(width: number, height: number) {
      usingMockRef.current = true;
      edgesRef.current = mergeGraph(nodesById.current, MOCK_GRAPH as GraphSnapshot, width, height);
      setStatus("ready");
      setNodeCount(nodesById.current.size);
    }

    async function poll() {
      const canvas = canvasRef.current;
      const width = canvas?.clientWidth ?? 600;
      const height = canvas?.clientHeight ?? 360;
      try {
        const snapshot = await fetchGraph();
        if (cancelled) return;
        if (snapshot.nodes.length > 0) {
          usingMockRef.current = false;
          edgesRef.current = mergeGraph(nodesById.current, snapshot, width, height);
          setStatus("ready");
          setNodeCount(nodesById.current.size);
        } else if (nodesById.current.size === 0 && !usingMockRef.current) {
          seedMock(width, height);
        }
      } catch {
        if (cancelled) return;
        if (nodesById.current.size === 0 && !usingMockRef.current) {
          seedMock(width, height);
        } else if (!usingMockRef.current) {
          setStatus("error");
        }
      }
    }

    poll();
    const handle = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(handle);
    };
  }, []);

  // The render/physics loop, plus all mouse/wheel interaction -- set up once
  // and reading refs each frame, so it never needs to restart when data or
  // selection changes.
  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    function resize() {
      if (!canvas || !container) return;
      canvas.width = container.clientWidth;
      canvas.height = container.clientHeight;
    }
    resize();
    window.addEventListener("resize", resize);

    function handleMouseDown(evt: MouseEvent) {
      if (!canvas) return;
      movedRef.current = false;
      const { x, y } = toGraphCoords(evt.clientX, evt.clientY, canvas, transformRef.current);
      const hit = findNodeAt(Array.from(nodesById.current.values()), x, y);
      if (hit) {
        hit.fixed = true;
        draggingRef.current = hit;
      } else {
        panningRef.current = { lastX: evt.clientX, lastY: evt.clientY };
      }
    }

    function handleMouseMove(evt: MouseEvent) {
      if (!canvas) return;
      movedRef.current = true;
      if (draggingRef.current) {
        const { x, y } = toGraphCoords(evt.clientX, evt.clientY, canvas, transformRef.current);
        draggingRef.current.x = x;
        draggingRef.current.y = y;
        draggingRef.current.vx = 0;
        draggingRef.current.vy = 0;
      } else if (panningRef.current) {
        const dx = evt.clientX - panningRef.current.lastX;
        const dy = evt.clientY - panningRef.current.lastY;
        transformRef.current = { ...transformRef.current, tx: transformRef.current.tx + dx, ty: transformRef.current.ty + dy };
        panningRef.current = { lastX: evt.clientX, lastY: evt.clientY };
      } else {
        const { x, y } = toGraphCoords(evt.clientX, evt.clientY, canvas, transformRef.current);
        const hit = findNodeAt(Array.from(nodesById.current.values()), x, y);
        hoveredIdRef.current = hit?.id ?? null;
        canvas.style.cursor = hit ? "pointer" : "grab";
      }
    }

    function endInteraction(evt: MouseEvent) {
      if (draggingRef.current) {
        draggingRef.current.fixed = false;
        if (!movedRef.current && canvas) {
          const { x, y } = toGraphCoords(evt.clientX, evt.clientY, canvas, transformRef.current);
          const hit = findNodeAt(Array.from(nodesById.current.values()), x, y);
          if (hit) onSelectAccount(selectedUpiIdRef.current === hit.id ? null : hit.id);
        }
        draggingRef.current = null;
      }
      panningRef.current = null;
    }

    function handleWheel(evt: WheelEvent) {
      if (!canvas) return;
      evt.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const mouseX = evt.clientX - rect.left;
      const mouseY = evt.clientY - rect.top;
      const t = transformRef.current;
      const zoomFactor = evt.deltaY < 0 ? 1.1 : 1 / 1.1;
      const newScale = Math.min(4, Math.max(0.25, t.scale * zoomFactor));
      const graphX = (mouseX - t.tx) / t.scale;
      const graphY = (mouseY - t.ty) / t.scale;
      transformRef.current = { scale: newScale, tx: mouseX - graphX * newScale, ty: mouseY - graphY * newScale };
    }

    function handleMouseLeave() {
      hoveredIdRef.current = null;
      if (draggingRef.current) draggingRef.current.fixed = false;
      draggingRef.current = null;
      panningRef.current = null;
    }

    canvas.addEventListener("mousedown", handleMouseDown);
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", endInteraction);
    canvas.addEventListener("mouseleave", handleMouseLeave);
    canvas.addEventListener("wheel", handleWheel, { passive: false });

    const ctx = canvas.getContext("2d");
    let raf = 0;

    function frame() {
      const nodes = Array.from(nodesById.current.values());
      const edges = edgesRef.current;
      if (canvas && ctx) {
        simulateStep(nodes, edges, canvas.width, canvas.height);
        draw(ctx, canvas, nodes, edges, transformRef.current, hoveredIdRef.current, selectedUpiIdRef.current);
      }
      raf = requestAnimationFrame(frame);
    }
    raf = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      canvas.removeEventListener("mousedown", handleMouseDown);
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", endInteraction);
      canvas.removeEventListener("mouseleave", handleMouseLeave);
      canvas.removeEventListener("wheel", handleWheel);
    };
  }, [onSelectAccount]);

  function draw(
    ctx: CanvasRenderingContext2D,
    canvas: HTMLCanvasElement,
    nodes: SimNode[],
    edges: SimEdge[],
    t: Transform,
    hoveredId: string | null,
    selectedId: string | null
  ) {
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = "#0b0f16";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.translate(t.tx, t.ty);
    ctx.scale(t.scale, t.scale);

    for (const e of edges) {
      const dim = selectedId != null && e.source.id !== selectedId && e.target.id !== selectedId;
      ctx.strokeStyle = dim ? "rgba(139,163,199,0.05)" : (EDGE_COLOR[e.type] ?? "rgba(139,163,199,0.25)");
      const baseWidth = e.type === "transaction" ? 0.4 + Math.log2(e.weight + 1) * 0.4 : 1.3;
      ctx.lineWidth = Math.min(3, baseWidth) / t.scale;
      ctx.beginPath();
      ctx.moveTo(e.source.x, e.source.y);
      ctx.lineTo(e.target.x, e.target.y);
      ctx.stroke();
    }

    for (const n of nodes) {
      const dim = selectedId != null && n.id !== selectedId && !isNeighbor(n.id, selectedId, edges);
      const color = communityColor(n.community);
      ctx.globalAlpha = dim ? 0.22 : 1;

      const glow = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, n.radius * 2.6);
      glow.addColorStop(0, color);
      glow.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.radius * 2.6, 0, Math.PI * 2);
      ctx.fill();

      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.radius, 0, Math.PI * 2);
      ctx.fill();

      if (n.id === selectedId || n.id === hoveredId) {
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 1.5 / t.scale;
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }

    const labelId = hoveredId ?? selectedId;
    if (labelId) {
      const n = nodes.find((nn) => nn.id === labelId);
      if (n) {
        ctx.font = `${12 / t.scale}px "SF Mono", Consolas, monospace`;
        ctx.fillStyle = "#e6e9ef";
        ctx.textAlign = "center";
        ctx.fillText(n.id, n.x, n.y - n.radius - 8 / t.scale);
      }
    }
  }

  return (
    <div>
      <div className="graph-canvas-wrap" ref={containerRef}>
        <canvas ref={canvasRef} />
        {status === "error" && nodeCount === 0 && (
          <div className="graph-overlay-msg">Can't reach the backend's /graph endpoint.</div>
        )}
        {status === "ready" && nodeCount === 0 && (
          <div className="graph-overlay-msg">No accounts have transacted yet -- score a transaction to see it here.</div>
        )}
      </div>
      <div className="graph-legend">
        <span><i className="graph-legend-swatch" style={{ background: EDGE_COLOR.transaction }} /> transaction</span>
        <span><i className="graph-legend-swatch" style={{ background: "rgba(224,70,61,0.9)" }} /> shared device</span>
        <span><i className="graph-legend-swatch" style={{ background: "rgba(178,111,255,0.9)" }} /> repeated counterparty</span>
        <span className="graph-legend-hint">colors = detected clusters &middot; scroll to zoom &middot; drag to pan/move nodes &middot; click a node to focus the feed below</span>
      </div>
    </div>
  );
}
