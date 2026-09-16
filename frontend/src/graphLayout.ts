// A small hand-rolled force-directed layout (Fruchterman-Reingold-ish
// spring/repulsion physics), used instead of pulling in d3-force or a
// charting library -- this project's graph is a few dozen to a few hundred
// nodes at demo scale, well within range for a plain O(n^2) repulsion pass
// every frame, and NetworkGraph.tsx is the only place that needs it.

export interface SimNode {
  id: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
  community: number;
  trueLabel: string | null;
  degree: number;
  fixed: boolean; // true while the user is dragging this node
}

export interface SimEdge {
  source: SimNode;
  target: SimNode;
  type: string;
  weight: number;
}

const REPULSION = 2200;
const CENTER_STRENGTH = 0.012;
const DAMPING = 0.82;
const MAX_SPEED = 12;

// Tighter, stronger springs for the edge types that are themselves a
// suspicion signal (app.graph.builder's shared_device/repeated_counterparty)
// -- pulling those pairs closer together than an ordinary transaction makes
// the clusters they form visually denser, echoing what the graph engine
// already treats as more significant.
const EDGE_LENGTH: Record<string, number> = {
  transaction: 90,
  shared_device: 55,
  repeated_counterparty: 45,
};

const EDGE_STRENGTH: Record<string, number> = {
  transaction: 0.02,
  shared_device: 0.05,
  repeated_counterparty: 0.06,
};

export function simulateStep(nodes: SimNode[], edges: SimEdge[], width: number, height: number): void {
  const cx = width / 2;
  const cy = height / 2;

  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i];
      const b = nodes[j];
      let dx = a.x - b.x;
      let dy = a.y - b.y;
      let distSq = dx * dx + dy * dy;
      if (distSq < 1) {
        dx = Math.random() - 0.5;
        dy = Math.random() - 0.5;
        distSq = 1;
      }
      const dist = Math.sqrt(distSq);
      const force = REPULSION / distSq;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      a.vx += fx;
      a.vy += fy;
      b.vx -= fx;
      b.vy -= fy;
    }
  }

  for (const edge of edges) {
    const idealLength = EDGE_LENGTH[edge.type] ?? 90;
    const strength = EDGE_STRENGTH[edge.type] ?? 0.02;
    const dx = edge.target.x - edge.source.x;
    const dy = edge.target.y - edge.source.y;
    const dist = Math.sqrt(dx * dx + dy * dy) || 1;
    const displacement = dist - idealLength;
    const fx = (dx / dist) * displacement * strength;
    const fy = (dy / dist) * displacement * strength;
    edge.source.vx += fx;
    edge.source.vy += fy;
    edge.target.vx -= fx;
    edge.target.vy -= fy;
  }

  for (const node of nodes) {
    if (node.fixed) continue;
    node.vx += (cx - node.x) * CENTER_STRENGTH;
    node.vy += (cy - node.y) * CENTER_STRENGTH;
    node.vx *= DAMPING;
    node.vy *= DAMPING;
    const speed = Math.sqrt(node.vx * node.vx + node.vy * node.vy);
    if (speed > MAX_SPEED) {
      node.vx = (node.vx / speed) * MAX_SPEED;
      node.vy = (node.vy / speed) * MAX_SPEED;
    }
    node.x += node.vx;
    node.y += node.vy;
  }
}
