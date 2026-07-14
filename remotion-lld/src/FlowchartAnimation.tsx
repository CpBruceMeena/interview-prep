import React, { useRef, useEffect, useState } from "react";
import {
  AbsoluteFill,
  useCurrentFrame,
  interpolate,
  spring,
  useVideoConfig,
} from "remotion";

// ─── Types ────────────────────────────────────────────────

export interface FlowchartNode {
  id: string;
  label: string;
  x: number;
  y: number;
  width: number;
  height: number;
  type: "start" | "process" | "decision" | "end";
}

export interface FlowchartEdge {
  from: string;
  to: string;
  label?: string;
  path: string;
}

export interface FlowchartData {
  id: string;
  title: string;
  subtitle: string;
  nodes: FlowchartNode[];
  edges: FlowchartEdge[];
  durationInFrames: number;
}

// ─── Theme ────────────────────────────────────────────────

const THEME = {
  background: "#0D0E15",
  nodeBg: "#1a1b2e",
  nodeBorder: "#2a2b4e",
  text: "#e2e8f0",
  accent: "#00D2FF",
  accentGlow: "rgba(0, 210, 255, 0.3)",
  green: "#22c55e",
  greenGlow: "rgba(34, 197, 94, 0.3)",
  orange: "#f59e0b",
  orangeGlow: "rgba(245, 158, 11, 0.3)",
  edgeColor: "#4a4b6e",
  edgeActive: "#00D2FF",
  detailText: "#64748b",
  glowSize: 20,
};

// ─── Flowchart Node Component ────────────────────────────

const FlowchartNodeComponent: React.FC<{
  node: FlowchartNode;
  stepIndex: number;
  currentNode: number;
  totalNodes: number;
}> = ({ node, stepIndex, currentNode }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const delay = stepIndex * 30;

  const opacity = interpolate(frame, [delay, delay + 10], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const isActive = stepIndex === currentNode;
  const isHighlighted = stepIndex <= currentNode;

  const scaleSpring = spring({
    frame: frame - delay,
    fps,
    config: { damping: 10, stiffness: 130 },
  });
  const scaleVal = isActive ? 1 + scaleSpring * 0.08 : 1;

  const borderColor = isActive
    ? THEME.accent
    : isHighlighted
    ? THEME.green
    : THEME.nodeBorder;

  const glowColor = isActive
    ? THEME.accentGlow
    : isHighlighted
    ? THEME.greenGlow
    : "transparent";

  const getShapeStyle = (type: string) => {
    switch (type) {
      case "start":
      case "end":
        return { borderRadius: 50 };
      case "decision":
        return { clipPath: "polygon(50% 0%, 100% 50%, 50% 100%, 0% 50%)" };
      default:
        return { borderRadius: 12 };
    }
  };

  return (
    <div
      style={{
        position: "absolute",
        left: node.x,
        top: node.y,
        width: node.width,
        height: node.height,
        opacity: opacity * (isHighlighted ? 1 : 0.4),
        transform: `scale(${scaleVal})`,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        ...getShapeStyle(node.type),
        backgroundColor: THEME.nodeBg,
        border: `2px solid ${borderColor}`,
        boxShadow: isActive
          ? `0 0 ${THEME.glowSize}px ${glowColor}, 0 0 ${THEME.glowSize * 2}px ${glowColor}`
          : `0 0 ${THEME.glowSize * 0.5}px ${glowColor}`,
        zIndex: 10,
      }}
    >
      <span
        style={{
          color: THEME.text,
          fontWeight: 700,
          fontSize: 14,
          textAlign: "center",
          padding: "0 12px",
          lineHeight: "1.3",
          ...(node.type === "decision" ? { transform: "rotate(-45deg)" } : {}),
        }}
      >
        {node.label}
      </span>
    </div>
  );
};

// ─── Data Packet (travels along SVG path) ────────────────

const DataPacket: React.FC<{
  d: string;
  progress: number;
  pathId: string;
}> = ({ d, progress, pathId }) => {
  const [pos, setPos] = useState({ x: 0, y: 0 });

  useEffect(() => {
    const hiddenPath = document.getElementById(pathId) as SVGPathElement | null;
    if (hiddenPath) {
      try {
        const len = hiddenPath.getTotalLength();
        const point = hiddenPath.getPointAtLength(len * Math.min(progress, 0.999));
        setPos({ x: point.x, y: point.y });
      } catch {
        // Path not ready yet
      }
    }
  }, [progress, pathId]);

  return (
    <>
      {pos.x > 0 && pos.y > 0 && (
        <>
          <div
            style={{
              position: "absolute",
              left: pos.x - 6,
              top: pos.y - 6,
              width: 12,
              height: 12,
              borderRadius: "50%",
              backgroundColor: THEME.accent,
              boxShadow: `0 0 16px ${THEME.accent}, 0 0 32px ${THEME.accent}`,
              zIndex: 20,
            }}
          />
          <div
            style={{
              position: "absolute",
              left: pos.x - 12,
              top: pos.y - 12,
              width: 24,
              height: 24,
              borderRadius: "50%",
              backgroundColor: THEME.accent,
              opacity: 0.2,
              zIndex: 19,
            }}
          />
        </>
      )}
    </>
  );
};

// ─── Animated Edge ───────────────────────────────────────

// Generate unique path ID for DataPacket to reference
const EDGE_PATH_PREFIX = "fc-edge-path-";

const AnimatedEdge: React.FC<{
  edge: FlowchartEdge;
  edgeIndex: number;
  currentNode: number;
}> = ({ edge, edgeIndex, currentNode }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const delay = edgeIndex * 30 + 20;
  const localFrame = frame - delay;

  if (localFrame < 0) return null;

  const pathProgress = spring({
    frame: localFrame - 5,
    fps,
    config: { damping: 15, stiffness: 80 },
  });

  const packetProgress = spring({
    frame: localFrame - 15,
    fps,
    config: { damping: 12, stiffness: 60 },
  });

  const opacity = interpolate(localFrame, [0, 10], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Estimate path length for stroke-dashoffset animation
  const estimatedLen = 500;
  const drawnLen = estimatedLen * pathProgress;

  const isCurrentEdge = edgeIndex <= currentNode && edgeIndex >= currentNode - 1;

  return (
    <div style={{ position: "absolute", top: 0, left: 0, width: 1920, height: 1080, zIndex: 5 }}>
      <svg width={1920} height={1080} style={{ position: "absolute", top: 0, left: 0 }}>
        <defs>
          <filter id="glow-packet" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <path id={`${EDGE_PATH_PREFIX}${edgeIndex}`} d={edge.path} />
        </defs>

        {/* Base edge */}
        <path
          d={edge.path}
          fill="none"
          stroke={isCurrentEdge ? THEME.accent : THEME.edgeColor}
          strokeWidth={isCurrentEdge ? 2.5 : 1.5}
          strokeDasharray={isCurrentEdge ? "6 4" : "none"}
          opacity={opacity}
          strokeLinecap="round"
        />

        {/* Drawing animation */}
        <path
          d={edge.path}
          fill="none"
          stroke={THEME.accent}
          strokeWidth={4}
          strokeDasharray={estimatedLen}
          strokeDashoffset={estimatedLen - drawnLen}
          opacity={opacity * 0.7}
          strokeLinecap="round"
          filter="url(#glow-packet)"
        />

        {/* Edge label */}
        {edge.label && (
          <text
            fontSize={11}
            fontWeight={500}
            fill={THEME.detailText}
            opacity={opacity * 0.8}
          >
            <textPath href={`#${EDGE_PATH_PREFIX}${edgeIndex}`} startOffset="50%">
              {edge.label}
            </textPath>
          </text>
        )}
      </svg>

      {/* Data packet */}
      {isCurrentEdge && packetProgress > 0 && packetProgress < 1 && (
        <DataPacket
          d={edge.path}
          progress={packetProgress}
          pathId={`${EDGE_PATH_PREFIX}${edgeIndex}`}
        />
      )}
    </div>
  );
};

// ─── Main Flowchart Component ────────────────────────────

export const FlowchartAnimation: React.FC<{
  flowchart: FlowchartData;
}> = ({ flowchart }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  const currentNode = Math.min(
    Math.floor(frame / 45),
    flowchart.nodes.length - 1
  );

  const titleOpacity = interpolate(frame, [0, 15], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const subtitleOpacity = interpolate(frame, [10, 25], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const progress = frame / durationInFrames;

  return (
    <AbsoluteFill
      style={{
        backgroundColor: THEME.background,
        fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
        overflow: "hidden",
      }}
    >
      {/* Grid background */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundImage: `linear-gradient(${THEME.accent}06 1px, transparent 1px), linear-gradient(90deg, ${THEME.accent}06 1px, transparent 1px)`,
          backgroundSize: "40px 40px",
          opacity: 0.5,
        }}
      />

      {/* Title */}
      <div
        style={{
          position: "absolute",
          top: 40,
          left: 0,
          right: 0,
          textAlign: "center",
          opacity: titleOpacity,
        }}
      >
        <h1
          style={{
            color: THEME.text,
            fontSize: 26,
            fontWeight: 700,
            margin: 0,
            letterSpacing: -0.5,
          }}
        >
          {flowchart.title}
        </h1>
        <p
          style={{
            color: THEME.detailText,
            fontSize: 14,
            margin: "4px 0 0",
            opacity: subtitleOpacity,
          }}
        >
          {flowchart.subtitle}
        </p>
      </div>

      {/* Edges */}
      {flowchart.edges.map((edge, i) => (
        <AnimatedEdge
          key={`edge-${i}`}
          edge={edge}
          edgeIndex={i}
          currentNode={currentNode}
        />
      ))}

      {/* Nodes */}
      {flowchart.nodes.map((node, i) => (
        <FlowchartNodeComponent
          key={node.id}
          node={node}
          stepIndex={i}
          currentNode={currentNode}
          totalNodes={flowchart.nodes.length}
        />
      ))}

      {/* Progress bar */}
      <div
        style={{
          position: "absolute",
          bottom: 0,
          left: 0,
          right: 0,
          height: 3,
          background: `${THEME.accent}22`,
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${progress * 100}%`,
            background: `linear-gradient(90deg, ${THEME.accent}, ${THEME.green})`,
            transition: "width 0.1s linear",
          }}
        />
      </div>

      <div
        style={{
          position: "absolute",
          bottom: 12,
          right: 20,
          color: THEME.detailText,
          fontSize: 11,
          opacity: 0.4,
          letterSpacing: 1,
        }}
      >
        REMOTION • FLOWCHART
      </div>
    </AbsoluteFill>
  );
};
