import React from "react";
import {
  AbsoluteFill,
  useCurrentFrame,
  interpolate,
  spring,
  useVideoConfig,
} from "remotion";

// ─── Types ────────────────────────────────────────────────

export interface ClassData {
  id: string;
  name: string;
  stereotype?: string;
  fields: string[];
  methods: string[];
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface RelationshipData {
  from: string;
  to: string;
  type: "inheritance" | "composition" | "aggregation" | "association" | "dependency";
  label?: string;
  fromMultiplicity?: string;
  toMultiplicity?: string;
}

export interface ClassDiagramData {
  id: string;
  title: string;
  subtitle: string;
  classes: ClassData[];
  relationships: RelationshipData[];
  durationInFrames: number;
}

// ─── Theme ────────────────────────────────────────────────

const THEME = {
  background: "#0D0E15",
  classHeaderBg: "linear-gradient(135deg, #1a1b4e, #2a1b5e)",
  classBodyBg: "#15162a",
  border: "#3a3b6e",
  borderActive: "#818cf8",
  text: "#e2e8f0",
  textDim: "#94a3b8",
  textAccent: "#a5b4fc",
  fieldColor: "#22c55e",
  methodColor: "#f59e0b",
  stereotypeColor: "#64748b",
  inheritanceArrow: "#818cf8",
  compositionArrow: "#22c55e",
  aggregationArrow: "#f59e0b",
  associationArrow: "#94a3b8",
  dependencyArrow: "#ef4444",
  glowColor: "rgba(129, 140, 248, 0.3)",
  gridBg: "rgba(129, 140, 248, 0.04)",
};

// ─── Arrow Head SVG Generators ───────────────────────────

const ARROW_HEAD_SIZE = 10;

function getArrowHead(type: string, color: string): React.ReactNode {
  switch (type) {
    case "inheritance":
      // Empty triangle
      return (
        <polygon
          points={`0,0 ${-ARROW_HEAD_SIZE * 1.5},${-ARROW_HEAD_SIZE / 2} ${-ARROW_HEAD_SIZE * 1.5},${ARROW_HEAD_SIZE / 2}`}
          fill="none"
          stroke={color}
          strokeWidth={2}
        />
      );
    case "composition":
      // Filled diamond
      return (
        <polygon
          points={`0,0 ${-ARROW_HEAD_SIZE},${-ARROW_HEAD_SIZE * 0.6} ${-ARROW_HEAD_SIZE * 2},0 ${-ARROW_HEAD_SIZE},${ARROW_HEAD_SIZE * 0.6}`}
          fill={color}
          stroke={color}
          strokeWidth={1}
        />
      );
    case "aggregation":
      // Empty diamond
      return (
        <polygon
          points={`0,0 ${-ARROW_HEAD_SIZE},${-ARROW_HEAD_SIZE * 0.6} ${-ARROW_HEAD_SIZE * 2},0 ${-ARROW_HEAD_SIZE},${ARROW_HEAD_SIZE * 0.6}`}
          fill="none"
          stroke={color}
          strokeWidth={2}
        />
      );
    case "dependency":
      // Dashed arrow with open head
      return (
        <polygon
          points={`0,0 ${-ARROW_HEAD_SIZE},${-ARROW_HEAD_SIZE / 2} ${-ARROW_HEAD_SIZE},${ARROW_HEAD_SIZE / 2}`}
          fill="none"
          stroke={color}
          strokeWidth={2}
        />
      );
    default:
      // Simple arrow for association
      return (
        <polygon
          points={`0,0 ${-ARROW_HEAD_SIZE * 1.2},${-ARROW_HEAD_SIZE / 2} ${-ARROW_HEAD_SIZE * 1.2},${ARROW_HEAD_SIZE / 2}`}
          fill={color}
          stroke={color}
          strokeWidth={1}
        />
      );
  }
}

function getRelationshipColor(type: string): string {
  switch (type) {
    case "inheritance": return THEME.inheritanceArrow;
    case "composition": return THEME.compositionArrow;
    case "aggregation": return THEME.aggregationArrow;
    case "dependency": return THEME.dependencyArrow;
    default: return THEME.associationArrow;
  }
}

function getRelationshipLabel(type: string): string {
  switch (type) {
    case "inheritance": return "◁▷ inherits";
    case "composition": return "◆ contains";
    case "aggregation": return "◇ has";
    case "dependency": return "- - -> uses";
    default: return "——— associates";
  }
}

// ─── Relationship Line Calculator ────────────────────────

interface LineCoords {
  fromX: number;
  fromY: number;
  toX: number;
  toY: number;
  midX: number;
  midY: number;
  angle: number;
}

function calculateLineCoords(
  fromClass: ClassData,
  toClass: ClassData,
): LineCoords {
  const fromCx = fromClass.x + fromClass.width / 2;
  const fromCy = fromClass.y + fromClass.height / 2;
  const toCx = toClass.x + toClass.width / 2;
  const toCy = toClass.y + toClass.height / 2;

  // Calculate angle and find intersection with class border
  const dx = toCx - fromCx;
  const dy = toCy - fromCy;
  const angle = Math.atan2(dy, dx);

  // Find intersection points with class borders
  const fromIntersect = getBorderIntersection(fromClass, angle);
  const toIntersect = getBorderIntersection(toClass, angle + Math.PI);

  const fromX = fromCx + Math.cos(angle) * fromIntersect;
  const fromY = fromCy + Math.sin(angle) * fromIntersect;
  const toX = toCx + Math.cos(angle + Math.PI) * toIntersect;
  const toY = toCy + Math.sin(angle + Math.PI) * toIntersect;

  return {
    fromX, fromY, toX, toY,
    midX: (fromX + toX) / 2,
    midY: (fromY + toY) / 2,
    angle,
  };
}

function getBorderIntersection(cls: ClassData, angle: number): number {
  // Calculate distance to border in the given direction
  const hw = cls.width / 2;
  const hh = cls.height / 2;
  const cos = Math.abs(Math.cos(angle));
  const sin = Math.abs(Math.sin(angle));

  if (cos * hh > sin * hw) {
    // Intersects left/right
    return hw / cos;
  }
  // Intersects top/bottom
  return hh / sin;
}

// ─── Class Box Component ─────────────────────────────────

const ClassBox: React.FC<{
  classData: ClassData;
  index: number;
  totalClasses: number;
  activeClassIds: Set<string>;
  highlightedRelId: string | null;
}> = ({ classData, index, totalClasses, activeClassIds, highlightedRelId }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const delay = index * 15;
  const isActive = activeClassIds.has(classData.id);
  const isHighlighted = highlightedRelId !== null && isActive;

  const boxOpacity = interpolate(frame, [delay, delay + 10], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const boxScale = spring({
    frame: frame - delay,
    fps,
    config: { damping: 12, stiffness: 100 },
  });

  const yOffset = interpolate(frame, [delay, delay + 15], [40, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const borderColor = isHighlighted
    ? THEME.borderActive
    : isActive
    ? THEME.borderActive
    : THEME.border;

  // Field/method animation inside the box
  const fieldDelay = delay + 10;
  const methodDelay = fieldDelay + classData.fields.length * 3 + 5;

  return (
    <div
      style={{
        position: "absolute",
        left: classData.x,
        top: classData.y + yOffset,
        width: classData.width,
        opacity: boxOpacity,
        transform: `scale(${boxScale})`,
        borderRadius: 12,
        border: `2px solid ${borderColor}`,
        overflow: "hidden",
        boxShadow: isHighlighted
          ? `0 0 30px ${THEME.glowColor}, 0 0 60px ${THEME.glowColor}`
          : isActive
          ? `0 0 15px ${THEME.glowColor}`
          : `0 4px 12px rgba(0,0,0,0.3)`,
        zIndex: 10,
      }}
    >
      {/* Class name header */}
      <div
        style={{
          background: THEME.classHeaderBg,
          padding: "8px 12px",
          textAlign: "center",
          borderBottom: `1px solid ${THEME.border}`,
        }}
      >
        {classData.stereotype && (
          <div
            style={{
              color: THEME.stereotypeColor,
              fontSize: 10,
              fontStyle: "italic",
              marginBottom: 2,
            }}
          >
            &lt;&lt;{classData.stereotype}&gt;&gt;
          </div>
        )}
        <div
          style={{
            color: THEME.textAccent,
            fontSize: 14,
            fontWeight: 700,
            letterSpacing: 0.5,
          }}
        >
          {classData.name}
        </div>
      </div>

      {/* Fields section */}
      {classData.fields.length > 0 && (
        <div
          style={{
            padding: "6px 12px",
            borderBottom: `1px solid ${THEME.border}`,
          }}
        >
          {classData.fields.map((field, fi) => {
            const fDelay = fieldDelay + fi * 3;
            const fOpacity = interpolate(frame, [fDelay, fDelay + 5], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
            const fX = interpolate(frame, [fDelay, fDelay + 5], [-20, 0], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
            return (
              <div
                key={`field-${fi}`}
                style={{
                  opacity: fOpacity,
                  transform: `translateX(${fX}px)`,
                  color: THEME.fieldColor,
                  fontSize: 11,
                  fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
                  padding: "1px 0",
                  lineHeight: 1.6,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {field}
              </div>
            );
          })}
        </div>
      )}

      {/* Methods section */}
      {classData.methods.length > 0 && (
        <div style={{ padding: "6px 12px" }}>
          {classData.methods.map((method, mi) => {
            const mDelay = methodDelay + mi * 3;
            const mOpacity = interpolate(frame, [mDelay, mDelay + 5], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
            const mX = interpolate(frame, [mDelay, mDelay + 5], [-20, 0], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
            return (
              <div
                key={`method-${mi}`}
                style={{
                  opacity: mOpacity,
                  transform: `translateX(${mX}px)`,
                  color: THEME.methodColor,
                  fontSize: 11,
                  fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
                  padding: "1px 0",
                  lineHeight: 1.6,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {method}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

// ─── Animated Relationship Line ──────────────────────────

const RelationshipLine: React.FC<{
  relationship: RelationshipData;
  index: number;
  classes: ClassData[];
  activeRelIndex: number;
}> = ({ relationship, index, classes, activeRelIndex }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const fromClass = classes.find(c => c.id === relationship.from);
  const toClass = classes.find(c => c.id === relationship.to);
  if (!fromClass || !toClass) return null;

  const coords = calculateLineCoords(fromClass, toClass);
  const color = getRelationshipColor(relationship.type);

  const delay = classes.length * 15 + index * 12;
  const localFrame = frame - delay;

  if (localFrame < 0) return null;

  const isActive = index === activeRelIndex;

  const lineProgress = spring({
    frame: localFrame,
    fps,
    config: { damping: 15, stiffness: 80 },
  });

  const opacity = interpolate(localFrame, [0, 10], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const labelOpacity = interpolate(localFrame, [15, 25], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <svg
      width={1920}
      height={1080}
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        zIndex: 5,
        opacity,
        pointerEvents: "none",
      }}
    >
      {/* Animated line drawing */}
      <line
        x1={coords.fromX}
        y1={coords.fromY}
        x2={coords.fromX + (coords.toX - coords.fromX) * lineProgress}
        y2={coords.fromY + (coords.toY - coords.fromY) * lineProgress}
        stroke={color}
        strokeWidth={isActive ? 3 : 2}
        strokeDasharray={relationship.type === "dependency" ? "6 4" : "none"}
        strokeLinecap="round"
        opacity={lineProgress}
      />

      {/* Arrow head at end (show when line is fully drawn) */}
      {lineProgress > 0.98 && (
        <g
          transform={`translate(${coords.toX}, ${coords.toY}) rotate(${coords.angle * 180 / Math.PI})`}
        >
          {getArrowHead(relationship.type, color)}
        </g>
      )}

      {/* Multiplicity labels */}
      {relationship.fromMultiplicity && (
        <text
          x={coords.fromX + (coords.toX - coords.fromX) * 0.15}
          y={coords.fromY + (coords.toY - coords.fromY) * 0.15 - 8}
          fill={THEME.textDim}
          fontSize={9}
          textAnchor="middle"
          opacity={labelOpacity}
        >
          {relationship.fromMultiplicity}
        </text>
      )}
      {relationship.toMultiplicity && (
        <text
          x={coords.fromX + (coords.toX - coords.fromX) * 0.85}
          y={coords.fromY + (coords.toY - coords.fromY) * 0.85 - 8}
          fill={THEME.textDim}
          fontSize={9}
          textAnchor="middle"
          opacity={labelOpacity}
        >
          {relationship.toMultiplicity}
        </text>
      )}

      {/* Relationship label */}
      <g opacity={labelOpacity}>
        <rect
          x={coords.midX - 55}
          y={coords.midY - 9}
          width={110}
          height={18}
          rx={4}
          fill={THEME.classHeaderBg}
          stroke={color}
          strokeWidth={0.5}
          opacity={0.9}
        />
        <text
          x={coords.midX}
          y={coords.midY + 4}
          fill={color}
          fontSize={9}
          fontWeight={600}
          textAnchor="middle"
        >
          {relationship.label || getRelationshipLabel(relationship.type)}
        </text>
      </g>
    </svg>
  );
};

// ─── Legend ───────────────────────────────────────────────

const RelationshipLegend: React.FC<{
  frame: number;
  delay: number;
}> = ({ frame, delay }) => {
  const opacity = interpolate(frame, [delay, delay + 15], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const items = [
    { type: "inheritance", label: "Inheritance", color: THEME.inheritanceArrow, symbol: "◁▷" },
    { type: "composition", label: "Composition", color: THEME.compositionArrow, symbol: "◆" },
    { type: "aggregation", label: "Aggregation", color: THEME.aggregationArrow, symbol: "◇" },
    { type: "association", label: "Association", color: THEME.associationArrow, symbol: "→" },
    { type: "dependency", label: "Dependency", color: THEME.dependencyArrow, symbol: "- - →" },
  ];

  return (
    <div
      style={{
        position: "absolute",
        top: 90,
        right: 30,
        opacity,
        backgroundColor: "rgba(21, 22, 42, 0.85)",
        borderRadius: 8,
        border: `1px solid ${THEME.border}`,
        padding: "8px 12px",
        zIndex: 20,
      }}
    >
      <div style={{ color: THEME.textDim, fontSize: 9, fontWeight: 600, marginBottom: 4 }}>
        LEGEND
      </div>
      {items.map((item, i) => (
        <div
          key={i}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "2px 0",
          }}
        >
          <span style={{ color: item.color, fontSize: 11, fontWeight: 700, width: 22 }}>
            {item.symbol}
          </span>
          <span style={{ color: THEME.textDim, fontSize: 9 }}>{item.label}</span>
        </div>
      ))}
    </div>
  );
};

// ─── Main Component ──────────────────────────────────────

export const ClassDiagramAnimation: React.FC<{
  diagram: ClassDiagramData;
}> = ({ diagram }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  // Calculate which classes are active and which relationship is highlighted
  const classesFrameBudget = diagram.classes.length * 15;
  const currentActiveCount = Math.min(
    Math.max(0, Math.floor(frame / 15)),
    diagram.classes.length
  );
  const activeClassIds = new Set(
    diagram.classes.slice(0, currentActiveCount).map(c => c.id)
  );

  // Active relationship index (after all classes have appeared)
  const relStartFrame = diagram.classes.length * 15;
  const relFrameBudget = diagram.relationships.length * 12;
  const activeRelIndex = Math.min(
    Math.max(-1, Math.floor((frame - relStartFrame) / 12)),
    diagram.relationships.length - 1
  );

  const highlightedRelId = activeRelIndex >= 0
    ? `rel-${activeRelIndex}`
    : null;

  // Title animation
  const titleOpacity = interpolate(frame, [0, 15], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const titleY = interpolate(frame, [0, 15], [-20, 0], {
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
          backgroundImage: `
            linear-gradient(${THEME.gridBg} 1px, transparent 1px),
            linear-gradient(90deg, ${THEME.gridBg} 1px, transparent 1px)
          `,
          backgroundSize: "40px 40px",
          opacity: 0.5,
        }}
      />

      {/* Top-right subtle glow */}
      <div
        style={{
          position: "absolute",
          top: -200,
          right: -200,
          width: 600,
          height: 600,
          borderRadius: "50%",
          background: "radial-gradient(circle, rgba(129,140,248,0.06) 0%, transparent 70%)",
          pointerEvents: "none",
        }}
      />

      {/* Title */}
      <div
        style={{
          position: "absolute",
          top: 32,
          left: 0,
          right: 0,
          textAlign: "center",
          opacity: titleOpacity,
          transform: `translateY(${titleY}px)`,
          zIndex: 5,
        }}
      >
        <h1
          style={{
            color: THEME.text,
            fontSize: 24,
            fontWeight: 700,
            margin: 0,
            letterSpacing: -0.5,
          }}
        >
          {diagram.title}
        </h1>
        <p
          style={{
            color: THEME.textDim,
            fontSize: 13,
            margin: "4px 0 0",
            opacity: subtitleOpacity,
          }}
        >
          {diagram.subtitle}
        </p>
      </div>

      {/* Legend */}
      <RelationshipLegend frame={frame} delay={10} />

      {/* Relationships (draw behind classes) */}
      {diagram.relationships.map((rel, i) => (
        <RelationshipLine
          key={`rel-${i}`}
          relationship={rel}
          index={i}
          classes={diagram.classes}
          activeRelIndex={activeRelIndex}
        />
      ))}

      {/* Class boxes */}
      {diagram.classes.map((cls, i) => (
        <ClassBox
          key={cls.id}
          classData={cls}
          index={i}
          totalClasses={diagram.classes.length}
          activeClassIds={activeClassIds}
          highlightedRelId={highlightedRelId}
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
          background: `${THEME.borderActive}22`,
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${progress * 100}%`,
            background: `linear-gradient(90deg, ${THEME.borderActive}, #22c55e)`,
            transition: "width 0.1s linear",
          }}
        />
      </div>

      <div
        style={{
          position: "absolute",
          bottom: 12,
          right: 20,
          color: THEME.textDim,
          fontSize: 11,
          opacity: 0.4,
          letterSpacing: 1,
        }}
      >
        REMOTION • CLASS DIAGRAM
      </div>
    </AbsoluteFill>
  );
};
