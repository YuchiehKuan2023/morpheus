import React, { useCallback, useEffect, useRef } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import type { GraphData, GraphLink, GraphNode } from '@/types';
import { NODE_BORDER_COLORS, NODE_COLORS, NODE_SIZES } from './graphConfig';

// Relationship type → colour (saturated for light background)
const LINK_COLORS: Record<string, string> = {
  GENERATED: 'rgba(99,102,241,0.85)',
  ACCESSED: 'rgba(245,158,11,0.85)',
  FROM_DEVICE: 'rgba(16,185,129,0.85)',
  USED_BROWSER: 'rgba(59,130,246,0.85)',
  ON_OS: 'rgba(139,92,246,0.85)',
  FROM_IP: 'rgba(236,72,153,0.85)',
  VIA_CLIENT: 'rgba(20,184,166,0.85)',
  FROM_LOCATION: 'rgba(249,115,22,0.85)',
};

export interface GraphVizRef {
  zoomIn: () => void;
  zoomOut: () => void;
  fitView: () => void;
  resetGraph: () => void;
}

interface Props {
  data: GraphData;
  width: number;
  height: number;
  selectedNode: GraphNode | null;
  onNodeClick: (node: GraphNode) => void;
  onNodeRightClick: (node: GraphNode) => void;
  onBackgroundClick: () => void;
  vizRef?: React.RefObject<GraphVizRef | null>;
}

export default function GraphVisualization({
  data,
  width,
  height,
  selectedNode,
  onNodeClick,
  onNodeRightClick,
  onBackgroundClick,
  vizRef,
}: Props) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const fgRef = useRef<any>(null);
  // True whenever a data change or explicit reset should trigger a fit once the
  // force simulation settles (onEngineStop).
  const needsFitRef = useRef(false);
  // Lerped scale for the selected node's radius (1.0 → 1.25 on select, back on deselect)
  const currentScaleRef = useRef(1.0);
  const lerpRafRef = useRef<number | null>(null);
  // Captures the live node object (with current x/y) each frame so onRenderFramePost
  // can draw the selected node on top without stale position from React state
  const selectedNodeLiveRef = useRef<(GraphNode & { x: number; y: number; fx?: number }) | null>(
    null
  );
  // Labels are hidden until the first zoomToFit completes to avoid cluttered text during layout
  const labelsReadyRef = useRef(false);

  // Expose zoom controls to parent via vizRef
  useEffect(() => {
    if (!vizRef) return;
    vizRef.current = {
      zoomIn: () => fgRef.current?.zoom(fgRef.current.zoom() * 1.4, 300),
      zoomOut: () => fgRef.current?.zoom(fgRef.current.zoom() * 0.7, 300),
      fitView: () => fgRef.current?.zoomToFit(400, 40),
      resetGraph: () => {
        // Unpin all nodes and reheat
        data.nodes.forEach((n: GraphNode & { fx?: number; fy?: number }) => {
          n.fx = undefined;
          n.fy = undefined;
        });
        needsFitRef.current = true;
        fgRef.current?.d3ReheatSimulation();
      },
    };
  }, [vizRef, data.nodes]);

  // Reheat on data change and mark that a fit is needed once settled
  useEffect(() => {
    if (fgRef.current) {
      needsFitRef.current = true;
      labelsReadyRef.current = false;
      fgRef.current.d3ReheatSimulation();
    }
  }, [data]);

  const handleEngineStop = useCallback(() => {
    if (needsFitRef.current) {
      needsFitRef.current = false;
      labelsReadyRef.current = true;
      fgRef.current?.zoomToFit(400, 40);
    }
  }, []);

  // Lerp currentScaleRef toward 1.25 on select, 1.0 on deselect.
  // Runs ~15 frames then stops — does not keep the simulation alive indefinitely.
  useEffect(() => {
    const target = selectedNode ? 1.25 : 1.0;
    if (lerpRafRef.current !== null) {
      cancelAnimationFrame(lerpRafRef.current);
      lerpRafRef.current = null;
    }
    const step = () => {
      const diff = target - currentScaleRef.current;
      if (Math.abs(diff) < 0.004) {
        currentScaleRef.current = target;
        fgRef.current?.resumeAnimation();
        lerpRafRef.current = null;
        return;
      }
      currentScaleRef.current += diff * 0.18;
      fgRef.current?.resumeAnimation();
      lerpRafRef.current = requestAnimationFrame(step);
    };
    lerpRafRef.current = requestAnimationFrame(step);
    return () => {
      if (lerpRafRef.current !== null) {
        cancelAnimationFrame(lerpRafRef.current);
        lerpRafRef.current = null;
      }
    };
  }, [selectedNode]);

  // Draws the selected node AFTER all others so it always appears on top.
  // Reads from selectedNodeLiveRef which is populated each frame by drawNode
  // using the live (mutated-in-place) object force-graph provides — no stale positions.
  const drawSelectedNodeOnTop = useCallback(
    (ctx: CanvasRenderingContext2D, globalScale: number) => {
      const n = selectedNodeLiveRef.current;
      if (!n || !selectedNode) return;

      const label = (n.label ?? 'Unknown') as GraphNode['label'];
      const color = NODE_COLORS[label] ?? NODE_COLORS.Unknown;
      const borderColor = NODE_BORDER_COLORS[label] ?? NODE_BORDER_COLORS.Unknown;
      const baseSize = NODE_SIZES[label] ?? 5;
      const r = baseSize * currentScaleRef.current;

      ctx.globalAlpha = 0.75;
      ctx.beginPath();
      ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.globalAlpha = 1.0;

      ctx.strokeStyle = borderColor;
      ctx.lineWidth = 1.2 / globalScale;
      ctx.stroke();

      if (n.fx !== undefined) {
        ctx.beginPath();
        ctx.arc(n.x + r * 0.7, n.y - r * 0.7, 2.5 / globalScale, 0, 2 * Math.PI);
        ctx.fillStyle = '#facc15';
        ctx.fill();
      }

      if (labelsReadyRef.current) {
        const LABEL_PX = 11;
        const fontSize = LABEL_PX / globalScale;
        const text = String(n.name ?? n.id);
        const topOfLabel = n.y + r + 2 / globalScale;
        // Must set font BEFORE measureText
        ctx.font = `bold ${fontSize}px sans-serif`;
        const textW = ctx.measureText(text).width;
        const padH = 5 / globalScale;
        const padV = 2.5 / globalScale;
        const bw = textW + padH * 2;
        const bh = fontSize + padV * 2;
        const br = 3.5 / globalScale;
        const bx = n.x - bw / 2;
        const by = topOfLabel;
        ctx.beginPath();
        ctx.moveTo(bx + br, by);
        ctx.lineTo(bx + bw - br, by);
        ctx.arcTo(bx + bw, by, bx + bw, by + bh, br);
        ctx.lineTo(bx + bw, by + bh - br);
        ctx.arcTo(bx + bw, by + bh, bx + bw - br, by + bh, br);
        ctx.lineTo(bx + br, by + bh);
        ctx.arcTo(bx, by + bh, bx, by + bh - br, br);
        ctx.lineTo(bx, by + br);
        ctx.arcTo(bx, by, bx + br, by, br);
        ctx.closePath();
        ctx.fillStyle = '#e1f2ae'; // brand-pale-lime
        ctx.fill();
        ctx.fillStyle = '#0f1729'; // brand-black
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.fillText(text, n.x, by + padV);
        ctx.textBaseline = 'alphabetic';
      }
    },
    [selectedNode]
  );

  const drawNode = useCallback(
    (node: object, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const n = node as GraphNode & { x: number; y: number; fx?: number };
      const isSelected = selectedNode?.id === n.id;

      if (isSelected) {
        // Store the live node object (force-graph keeps x/y up-to-date on it).
        // drawSelectedNodeOnTop will draw it last via onRenderFramePost.
        selectedNodeLiveRef.current = n;
        return;
      }

      const label = (n.label ?? 'Unknown') as GraphNode['label'];
      const color = NODE_COLORS[label] ?? NODE_COLORS.Unknown;
      const borderColor = NODE_BORDER_COLORS[label] ?? NODE_BORDER_COLORS.Unknown;
      const baseSize = NODE_SIZES[label] ?? 5;

      ctx.globalAlpha = 0.75;
      ctx.beginPath();
      ctx.arc(n.x, n.y, baseSize, 0, 2 * Math.PI);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.globalAlpha = 1.0;

      ctx.strokeStyle = borderColor;
      ctx.lineWidth = 1.2 / globalScale;
      ctx.stroke();

      if (n.fx !== undefined) {
        ctx.beginPath();
        ctx.arc(n.x + baseSize * 0.7, n.y - baseSize * 0.7, 2.5 / globalScale, 0, 2 * Math.PI);
        ctx.fillStyle = '#facc15';
        ctx.fill();
      }

      if (labelsReadyRef.current) {
        const LABEL_PX = 11;
        const fontSize = LABEL_PX / globalScale;
        ctx.font = `${fontSize}px sans-serif`;
        ctx.fillStyle = '#374151';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.fillText(String(n.name ?? n.id), n.x, n.y + baseSize + 2 / globalScale);
        ctx.textBaseline = 'alphabetic';
      }
    },
    [selectedNode]
  );

  const drawLink = useCallback(
    (link: object, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const l = link as GraphLink & {
        source: { x: number; y: number };
        target: { x: number; y: number };
      };
      const color = LINK_COLORS[l.type ?? ''] ?? 'rgba(156,163,175,0.35)';
      const src = l.source;
      const tgt = l.target;
      if (!src || !tgt) return;

      ctx.strokeStyle = color;
      ctx.lineWidth = 1 / globalScale;
      ctx.beginPath();
      ctx.moveTo(src.x, src.y);
      ctx.lineTo(tgt.x, tgt.y);
      ctx.stroke();

      // Relationship type label at midpoint — only when zoomed in
      if (globalScale > 2 && l.type) {
        const mx = (src.x + tgt.x) / 2;
        const my = (src.y + tgt.y) / 2;
        const fontSize = 4 / globalScale;
        ctx.font = `${fontSize}px sans-serif`;
        ctx.fillStyle = 'rgba(71,85,105,0.8)';
        ctx.textAlign = 'center';
        ctx.fillText(l.type, mx, my);
      }
    },
    []
  );

  const handleNodeClick = useCallback(
    (node: object) => onNodeClick(node as GraphNode),
    [onNodeClick]
  );

  const handleNodeRightClick = useCallback(
    (node: object, evt: MouseEvent) => {
      evt.preventDefault();
      onNodeRightClick(node as GraphNode);
    },
    [onNodeRightClick]
  );

  const handleNodeDragEnd = useCallback((node: object) => {
    const n = node as GraphNode & { x: number; y: number; fx?: number; fy?: number };
    n.fx = n.x;
    n.fy = n.y;
  }, []);

  return (
    <div style={{ width, height, background: '#f8fafc' }}>
      <ForceGraph2D
        ref={fgRef}
        graphData={data as Parameters<typeof ForceGraph2D>[0]['graphData']}
        width={width}
        height={height}
        backgroundColor="#f8fafc"
        nodeCanvasObject={drawNode}
        nodeCanvasObjectMode={() => 'replace'}
        nodePointerAreaPaint={(node, color, ctx) => {
          const n = node as GraphNode & { x: number; y: number };
          const size = NODE_SIZES[(n.label ?? 'Unknown') as GraphNode['label']] ?? 5;
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.arc(n.x, n.y, size * 2, 0, 2 * Math.PI);
          ctx.fill();
        }}
        linkCanvasObject={drawLink}
        linkCanvasObjectMode={() => 'replace'}
        onNodeClick={handleNodeClick}
        onNodeRightClick={handleNodeRightClick}
        onNodeDragEnd={handleNodeDragEnd}
        onBackgroundClick={onBackgroundClick}
        onEngineStop={handleEngineStop}
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        onRenderFramePost={drawSelectedNodeOnTop as any}
        cooldownTicks={120}
        d3AlphaDecay={0.02}
        d3VelocityDecay={0.3}
        enableNodeDrag
      />
    </div>
  );
}
