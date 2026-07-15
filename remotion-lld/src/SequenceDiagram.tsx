import React from "react";
import {
  AbsoluteFill,
  useCurrentFrame,
  interpolate,
  spring,
  useVideoConfig,
} from "remotion";

export interface StepData {
  from: number;
  to: number;
  label: string;
  detail?: string;
}

export interface SequenceData {
  id: string;
  title: string;
  actors: string[];
  subtitle: string;
  steps: StepData[];
  durationInFrames: number;
}

// ─── Color Theme ──────────────────────────────────────────

const THEME = {
  background: "#0f0f1a",
  primary: "#6366f1",
  secondary: "#22c55e",
  accent: "#f59e0b",
  text: "#e2e8f0",
  actorBg: "#1e1b4b",
  arrowLine: "#a5b4fc",
  arrowHead: "#818cf8",
  labelBg: "#312e81",
  detailText: "#94a3b8",
};

const BOX_WIDTH = 200;
const ARROW_START_Y = 190;
const BOTTOM_PADDING = 40;

function getLayout(totalActors: number) {
  const totalWidth = totalActors * BOX_WIDTH;
  const startX = (1920 - totalWidth) / 2;
  return { startX, totalWidth };
}

function getStepSpacing(stepCount: number) {
  const availableHeight = 1080 - ARROW_START_Y - BOTTOM_PADDING;
  return Math.max(75, Math.min(140, Math.floor(availableHeight / stepCount)));
}

// ─── Actor Header ─────────────────────────────────────────

const ActorHeader: React.FC<{
  name: string;
  index: number;
  totalActors: number;
}> = ({ name, index, totalActors }) => {
  const frame = useCurrentFrame();
  const delay = index * 5;
  const opacity = interpolate(frame, [delay, delay + 10], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const y = interpolate(frame, [delay, delay + 10], [-30, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const { startX } = getLayout(totalActors);
  const x = startX + index * BOX_WIDTH + BOX_WIDTH / 2;

  return (
    <div
      style={{
        position: "absolute",
        top: 100,
        left: x - BOX_WIDTH / 2,
        width: BOX_WIDTH,
        height: 60,
        opacity,
        transform: `translateY(${y}px)`,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: THEME.actorBg,
        borderRadius: 12,
        border: `2px solid ${THEME.primary}`,
        boxShadow: `0 0 20px ${THEME.primary}33`,
      }}
    >
      <span
        style={{
          color: THEME.text,
          fontWeight: 700,
          fontSize: 16,
          textAlign: "center",
          padding: "0 8px",
          lineHeight: "1.2",
        }}
      >
        {name}
      </span>
    </div>
  );
};

// ─── Actor Lifeline ────────────────────────────────────────

const Lifeline: React.FC<{
  index: number;
  totalActors: number;
  lifelineHeight: number;
}> = ({ index, totalActors, lifelineHeight }) => {
  const { startX } = getLayout(totalActors);
  const x = startX + index * BOX_WIDTH + BOX_WIDTH / 2;

  return (
    <div
      style={{
        position: "absolute",
        top: ARROW_START_Y - 30,
        left: x - 1,
        width: 2,
        height: lifelineHeight,
        background: `linear-gradient(to bottom, ${THEME.primary}44, ${THEME.primary}22, ${THEME.primary}44)`,
        opacity: 0.35,
      }}
    />
  );
};

// ─── Arrow Animation ──────────────────────────────────────

const AnimatedArrow: React.FC<{
  step: StepData;
  stepIndex: number;
  totalActors: number;
  stepSpacing: number;
}> = ({ step, stepIndex, totalActors, stepSpacing }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const { startX } = getLayout(totalActors);
  const arrowY = ARROW_START_Y + stepIndex * stepSpacing;
  const fromX = startX + step.from * BOX_WIDTH + BOX_WIDTH / 2;
  const toX = startX + step.to * BOX_WIDTH + BOX_WIDTH / 2;
  const midX = (fromX + toX) / 2;

  const stepStart = stepIndex * 20;
  const localFrame = frame - stepStart;

  const arrowProgress = spring({
    frame: localFrame,
    fps,
    config: { damping: 15, stiffness: 120 },
  });

  const labelOpacity = interpolate(
    localFrame,
    [12, 20],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  if (localFrame < 0) return null;

  const isSelfLoop = step.from === step.to;
  const isRight = fromX <= toX;
  const arrowMidY = stepSpacing / 2;

  return (
    <div
      style={{
        position: "absolute",
        top: arrowY,
        left: 0,
        width: 1920,
        height: stepSpacing,
      }}
    >
      <svg width={1920} height={stepSpacing} style={{ position: "absolute", top: 0, left: 0 }}>
        {isSelfLoop ? (
          <>
            <path
              d={`M ${fromX} ${arrowMidY + 10} C ${fromX + 80} ${-10}, ${fromX + 80} ${-10}, ${fromX} ${arrowMidY - 14}`}
              fill="none"
              stroke={THEME.arrowLine}
              strokeWidth={2}
              strokeDasharray={arrowProgress > 0.95 ? 'none' : `${arrowProgress * 80} 80`}
              opacity={Math.min(1, arrowProgress * 1.5)}
            />
            {arrowProgress > 0.95 && (
              <polygon
                points={`${fromX - 6},${arrowMidY - 14} ${fromX + 6},${arrowMidY - 14} ${fromX},${arrowMidY - 22}`}
                fill={THEME.arrowHead}
              />
            )}
          </>
        ) : (
          <>
            {/* Arrow line — smoothly extends from source to target */}
            <line
              x1={fromX}
              y1={arrowMidY}
              x2={fromX + (toX - fromX) * Math.min(1, arrowProgress)}
              y2={arrowMidY}
              stroke={THEME.arrowLine}
              strokeWidth={2.5}
              strokeLinecap="round"
            />
            {/* Arrowhead — appears when line is nearly complete */}
            {arrowProgress > 0.95 && (
              <polygon
                points={
                  isRight
                    ? `${toX - 8},${arrowMidY - 6} ${toX - 8},${arrowMidY + 6} ${toX + 4},${arrowMidY}`
                    : `${toX + 8},${arrowMidY - 6} ${toX + 8},${arrowMidY + 6} ${toX - 4},${arrowMidY}`
                }
                fill={THEME.arrowHead}
              />
            )}
          </>
        )}
      </svg>

      {/* Label — centered above the arrow line */}
      <div
        style={{
          position: "absolute",
          top: 2,
          left: midX,
          transform: "translateX(-50%)",
          backgroundColor: THEME.labelBg,
          color: THEME.text,
          padding: "4px 12px",
          borderRadius: 6,
          fontSize: 13,
          fontWeight: 600,
          whiteSpace: "nowrap",
          border: `1px solid ${THEME.primary}55`,
          opacity: labelOpacity,
          boxShadow: `0 2px 8px ${THEME.primary}22`,
          zIndex: 10,
        }}
      >
        {step.label}
      </div>

      {/* Detail — centered below the arrow line */}
      {step.detail && (
        <div
          style={{
            position: "absolute",
            top: arrowMidY + 8,
            left: midX,
            transform: "translateX(-50%)",
            color: THEME.detailText,
            fontSize: 11,
            whiteSpace: "nowrap",
            opacity: Math.max(0, labelOpacity - 0.2),
            letterSpacing: 0.3,
          }}
        >
          {step.detail}
        </div>
      )}
    </div>
  );
};

// ─── Main Component ───────────────────────────────────────

export const SequenceDiagram: React.FC<{
  sequence: SequenceData;
}> = ({ sequence }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  const stepSpacing = getStepSpacing(sequence.steps.length);

  const lifelineHeight = Math.max(
    820,
    sequence.steps.length * stepSpacing + 60
  );

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
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundImage: `linear-gradient(${THEME.primary}08 1px, transparent 1px), linear-gradient(90deg, ${THEME.primary}08 1px, transparent 1px)`,
          backgroundSize: "40px 40px",
          opacity: 0.5,
        }}
      />

      <div
        style={{
          position: "absolute",
          top: 25,
          left: 0,
          right: 0,
          textAlign: "center",
          opacity: titleOpacity,
          transform: `translateY(${titleY}px)`,
        }}
      >
        <h1
          style={{
            color: THEME.text,
            fontSize: 28,
            fontWeight: 700,
            margin: 0,
            letterSpacing: -0.5,
          }}
        >
          {sequence.title}
        </h1>
        <p
          style={{
            color: THEME.detailText,
            fontSize: 14,
            margin: "8px 0 0",
            opacity: subtitleOpacity,
          }}
        >
          {sequence.subtitle}
        </p>
      </div>

      {sequence.actors.map((actor, i) => (
        <ActorHeader
          key={`header-${i}`}
          name={actor}
          index={i}
          totalActors={sequence.actors.length}
        />
      ))}

      {sequence.actors.map((_, i) => (
        <Lifeline
          key={`line-${i}`}
          index={i}
          totalActors={sequence.actors.length}
          lifelineHeight={lifelineHeight}
        />
      ))}

      {sequence.steps.map((step, i) => (
        <AnimatedArrow
          key={`step-${i}`}
          step={step}
          stepIndex={i}
          totalActors={sequence.actors.length}
          stepSpacing={stepSpacing}
        />
      ))}

      <div
        style={{
          position: "absolute",
          bottom: 0,
          left: 0,
          right: 0,
          height: 3,
          background: `${THEME.primary}33`,
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${progress * 100}%`,
            background: `linear-gradient(90deg, ${THEME.primary}, ${THEME.secondary})`,
            transition: "width 0.1s linear",
            borderRadius: "0 2px 2px 0",
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
        REMOTION • LLD
      </div>
    </AbsoluteFill>
  );
};
