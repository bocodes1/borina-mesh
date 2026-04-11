"use client";

import { useEffect, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { api } from "@/lib/api";
import { subscribeToActivity } from "@/lib/activity";
import type { Agent } from "@/lib/types";

function buildLayout(agents: Agent[]): { nodes: Node[]; edges: Edge[] } {
  const center = agents.find((a) => a.id === "ceo");
  const others = agents.filter((a) => a.id !== "ceo");

  const nodes: Node[] = [];
  const edges: Edge[] = [];
  const radius = 280;

  if (center) {
    nodes.push({
      id: center.id,
      position: { x: 400, y: 300 },
      data: { label: `${center.emoji}  ${center.name}` },
      className: "react-flow__node-ceo",
      style: {
        background: "hsl(263 85% 65% / 0.2)",
        border: "2px solid hsl(263 85% 65%)",
        borderRadius: "14px",
        padding: "14px 22px",
        color: "white",
        fontSize: "15px",
        fontWeight: 600,
      },
    });
  }

  others.forEach((agent, i) => {
    const angle = (i / others.length) * Math.PI * 2 - Math.PI / 2;
    const x = 400 + Math.cos(angle) * radius;
    const y = 300 + Math.sin(angle) * radius;
    const isRunning = agent.status === "running";
    nodes.push({
      id: agent.id,
      position: { x, y },
      data: {
        label: `${agent.emoji}  ${agent.name}${isRunning ? "\n⚡ " + (agent.current_task || "working...").slice(0, 40) : ""}`,
      },
      style: {
        background: isRunning ? "hsl(142 76% 36% / 0.2)" : "hsl(215 20% 65% / 0.1)",
        border: `2px solid ${isRunning ? "hsl(142 76% 36%)" : "hsl(215 20% 65% / 0.3)"}`,
        borderRadius: "12px",
        padding: "12px 18px",
        color: "white",
        fontSize: "13px",
        fontWeight: 500,
        whiteSpace: "pre-line" as const,
      },
    });

    if (center) {
      edges.push({
        id: `${center.id}-${agent.id}`,
        source: center.id,
        target: agent.id,
        animated: false,
        style: { stroke: "hsl(240 3.7% 25%)", strokeWidth: 1 },
      });
    }
  });

  return { nodes, edges };
}

export function NetworkGraph() {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const refresh = () => {
      api.listAgents().then((agents) => {
        const { nodes: n, edges: e } = buildLayout(agents);
        setNodes(n);
        setEdges(e);
        setLoading(false);
      });
    };
    refresh();
    const interval = setInterval(refresh, 5000);
    return () => clearInterval(interval);
  }, [setNodes, setEdges]);

  useEffect(() => {
    const unsubscribe = subscribeToActivity((event) => {
      setEdges((prev) =>
        prev.map((edge) => {
          if (edge.source === "ceo" && edge.target === event.agent_id) {
            return {
              ...edge,
              animated: event.kind === "started" || event.kind === "streaming",
              style: {
                ...edge.style,
                stroke: event.kind === "failed" ? "hsl(0 84% 60%)" : event.kind === "completed" ? "hsl(142 76% 45%)" : "hsl(263 85% 65%)",
                strokeWidth: 2,
              },
            };
          }
          return edge;
        })
      );

      if (event.kind === "completed" || event.kind === "failed") {
        setTimeout(() => {
          setEdges((prev) =>
            prev.map((edge) =>
              edge.source === "ceo" && edge.target === event.agent_id
                ? { ...edge, animated: false, style: { stroke: "hsl(240 3.7% 25%)", strokeWidth: 1 } }
                : edge
            )
          );
        }, 3000);
      }
    });
    return unsubscribe;
  }, [setEdges]);

  if (loading) {
    return <div className="h-[700px] rounded-xl glass flex items-center justify-center text-muted-foreground">Loading network...</div>;
  }

  return (
    <div className="h-[700px] rounded-xl glass overflow-hidden">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={20} size={1} color="hsl(240 3.7% 20%)" />
        <Controls className="!bg-card !border-border" />
        <MiniMap
          nodeColor="hsl(263 85% 65%)"
          maskColor="hsl(240 10% 3.9% / 0.8)"
          className="!bg-card !border-border"
        />
      </ReactFlow>
    </div>
  );
}
