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

const BOX_WIDTH = 180;
const ARROW_START_Y = 180;
const STEP_SPACING = 70;

function getLayout(totalActors: number) {
  const totalWidth = totalActors * BOX_WIDTH;
  const startX = (1920 - totalWidth) / 2;
  return { startX, totalWidth };
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
        top: 80,
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
        top: ARROW_START_Y - 35,
        left: x - 1,
        width: 2,
        height: lifelineHeight,
        background: `linear-gradient(to bottom, ${THEME.primary}44, ${THEME.primary}22, ${THEME.primary}44)`,
        opacity: 0.4,
      }}
    />
  );
};

// ─── Arrow Animation ──────────────────────────────────────

const AnimatedArrow: React.FC<{
  step: StepData;
  stepIndex: number;
  totalActors: number;
}> = ({ step, stepIndex, totalActors }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const { startX } = getLayout(totalActors);
  const arrowY = ARROW_START_Y + stepIndex * STEP_SPACING;
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
    [10, 18],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  if (localFrame < 0) return null;

  const isSelfLoop = step.from === step.to;
  const isRight = fromX <= toX;

  return (
    <div
      style={{
        position: "absolute",
        top: arrowY,
        left: 0,
        width: 1920,
        height: STEP_SPACING,
        opacity: labelOpacity,
      }}
    >
      {isSelfLoop ? (
        <svg width={1920} height={STEP_SPACING} style={{ position: "absolute", top: 0, left: 0 }}>
          <path
            d={`M ${fromX} ${STEP_SPACING} C ${fromX + 80} ${-20}, ${fromX + 80} ${-20}, ${fromX} ${0}`}
            fill="none"
            stroke={THEME.arrowLine}
            strokeWidth={2}
            strokeDasharray={arrowProgress * 100}
            opacity={arrowProgress}
          />
          <polygon
            points={`${fromX - 6},${2} ${fromX + 6},${2} ${fromX},${-6}`}
            fill={THEME.arrowHead}
            opacity={arrowProgress}
          />
        </svg>
      ) : (
        <svg width={1920} height={STEP_SPACING} style={{ position: "absolute", top: 0, left: 0 }}>
          <line
            x1={fromX}
            y1={STEP_SPACING / 2}
            x2={fromX + (toX - fromX) * arrowProgress}
            y2={STEP_SPACING / 2}
            stroke={THEME.arrowLine}
            strokeWidth={2.5}
          />
          {arrowProgress > 0.9 && (
            <>
              <line
                x1={toX}
                y1={STEP_SPACING / 2}
                x2={fromX + (toX - fromX) * 0.9}
                y2={STEP_SPACING / 2}
                stroke={THEME.arrowLine}
                strokeWidth={2.5}
              />
              <polygon
                points={
                  isRight
                    ? `${toX - 8},${STEP_SPACING / 2 - 6} ${toX - 8},${STEP_SPACING / 2 + 6} ${toX + 4},${STEP_SPACING / 2}`
                    : `${toX + 8},${STEP_SPACING / 2 - 6} ${toX + 8},${STEP_SPACING / 2 + 6} ${toX - 4},${STEP_SPACING / 2}`
                }
                fill={THEME.arrowHead}
              />
            </>
          )}
        </svg>
      )}

      <div
        style={{
          position: "absolute",
          top: 2,
          left: midX - 10,
          transform: "translateX(-50%)",
          backgroundColor: THEME.labelBg,
          color: THEME.text,
          padding: "3px 10px",
          borderRadius: 6,
          fontSize: 12,
          fontWeight: 600,
          whiteSpace: "nowrap",
          border: `1px solid ${THEME.primary}55`,
          opacity: labelOpacity,
        }}
      >
        {step.label}
      </div>

      {step.detail && (
        <div
          style={{
            position: "absolute",
            top: 24,
            left: midX - 10,
            transform: "translateX(-50%)",
            color: THEME.detailText,
            fontSize: 10,
            whiteSpace: "nowrap",
            opacity: Math.max(0, labelOpacity - 0.3),
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

  const lifelineHeight = Math.max(
    820,
    sequence.steps.length * STEP_SPACING + 60
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
          top: 20,
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
            margin: "4px 0 0",
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
