// Tiny deterministic force-directed simulation (no Math.random) so the network
// graph is alive AND testable: from the initial layout, nodes move toward
// equilibrium across ticks, settle, and react to drags/topology changes.

export interface SimNode {
  id: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  fixed?: boolean;
}

export interface SimEdge {
  source: string;
  target: string;
}

export interface SimOpts {
  width: number;
  height: number;
  repulsion?: number;
  spring?: number;
  restLen?: number;
  center?: number;
  damping?: number;
}

/** Deterministic initial layout: node 0 centered (orchestrator), rest on a ring. */
export function initNodes(ids: string[], width: number, height: number): SimNode[] {
  const cx = width / 2;
  const cy = height / 2;
  const r = Math.min(width, height) * 0.34;
  return ids.map((id, i) => {
    if (i === 0) return { id, x: cx, y: cy, vx: 0, vy: 0 };
    const ang = (2 * Math.PI * (i - 1)) / Math.max(1, ids.length - 1);
    return { id, x: cx + r * Math.cos(ang), y: cy + r * Math.sin(ang), vx: 0, vy: 0 };
  });
}

/** One integration step. Mutates node x/y/vx/vy in place. */
export function stepSimulation(nodes: SimNode[], edges: SimEdge[], opts: SimOpts): void {
  const {
    width,
    height,
    repulsion = 9000,
    spring = 0.025,
    restLen = 150,
    center = 0.012,
    damping = 0.82,
  } = opts;
  const byId: Record<string, SimNode> = {};
  for (const n of nodes) byId[n.id] = n;

  // Pairwise repulsion.
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i];
      const b = nodes[j];
      let dx = a.x - b.x;
      let dy = a.y - b.y;
      let d2 = dx * dx + dy * dy;
      if (d2 < 0.01) {
        dx = (i - j) * 0.5 + 0.1;
        dy = 0.1;
        d2 = dx * dx + dy * dy;
      }
      const d = Math.sqrt(d2);
      const f = repulsion / d2;
      const fx = (dx / d) * f;
      const fy = (dy / d) * f;
      a.vx += fx;
      a.vy += fy;
      b.vx -= fx;
      b.vy -= fy;
    }
  }

  // Edge springs.
  for (const e of edges) {
    const a = byId[e.source];
    const b = byId[e.target];
    if (!a || !b) continue;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
    const f = spring * (d - restLen);
    const fx = (dx / d) * f;
    const fy = (dy / d) * f;
    a.vx += fx;
    a.vy += fy;
    b.vx -= fx;
    b.vy -= fy;
  }

  // Centering + integrate + clamp.
  for (const n of nodes) {
    if (n.fixed) {
      n.vx = 0;
      n.vy = 0;
      continue;
    }
    n.vx += (width / 2 - n.x) * center;
    n.vy += (height / 2 - n.y) * center;
    n.vx *= damping;
    n.vy *= damping;
    n.x += n.vx;
    n.y += n.vy;
    n.x = Math.max(28, Math.min(width - 28, n.x));
    n.y = Math.max(28, Math.min(height - 28, n.y));
  }
}
