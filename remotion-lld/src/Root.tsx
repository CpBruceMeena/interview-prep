import { Composition } from "remotion";
import { SequenceDiagram } from "./SequenceDiagram";
import { FlowchartAnimation, FlowchartData } from "./FlowchartAnimation";
import { ClassDiagramAnimation } from "./ClassDiagramAnimation";
import { LLD_SEQUENCES } from "./sequences";
import { ADVANCED_SEQUENCES } from "./sequences-advanced";
import { ECS_AGENT_SEQUENCES } from "./sequences-agent-ecs";
import { AWS_ARCHITECTURE_SEQUENCES } from "./sequences-aws-architecture";
import { AWS_COMPUTE_SEQUENCES } from "./sequences-aws-compute";
import { AWS_NETWORKING_SEQUENCES } from "./sequences-aws-networking";
import { AWS_STORAGE_DB_SEQUENCES } from "./sequences-aws-storage-db";
import { AWS_SECURITY_ADDITIONAL_SEQUENCES } from "./sequences-aws-security-additional";
import { ALL_CLASS_DIAGRAMS } from "./sequences-class-diagrams";
import { SECURITY_SEQUENCES } from "./sequences-security";
import { SECURITY_FLOWCHARTS } from "./flowcharts-security";

const ALL_SEQUENCES = [
  ...LLD_SEQUENCES,
  ...ADVANCED_SEQUENCES,
  ...ECS_AGENT_SEQUENCES,
  ...AWS_ARCHITECTURE_SEQUENCES,
  ...AWS_COMPUTE_SEQUENCES,
  ...AWS_NETWORKING_SEQUENCES,
  ...AWS_STORAGE_DB_SEQUENCES,
  ...AWS_SECURITY_ADDITIONAL_SEQUENCES,
  ...SECURITY_SEQUENCES,
];

// ─── Sample Flowchart ──────────────────────────────────

const SAMPLE_FLOWCHART: FlowchartData = {
  id: "sample-flowchart",
  title: "Process Flow — Start to End",
  subtitle:
    "Start → Process A → Decision Point → End — with animated data packet",
  nodes: [
    {
      id: "start",
      label: "Start",
      x: 860,
      y: 160,
      width: 200,
      height: 60,
      type: "start",
    },
    {
      id: "process-a",
      label: "Process A",
      x: 810,
      y: 340,
      width: 300,
      height: 70,
      type: "process",
    },
    {
      id: "decision",
      label: "Decision\nPoint",
      x: 810,
      y: 540,
      width: 300,
      height: 100,
      type: "decision",
    },
    {
      id: "end",
      label: "End",
      x: 860,
      y: 760,
      width: 200,
      height: 60,
      type: "end",
    },
  ],
  edges: [
    {
      from: "start",
      to: "process-a",
      label: "Initialize",
      path: "M 960 220 L 960 340",
    },
    {
      from: "process-a",
      to: "decision",
      label: "Process Data",
      path: "M 960 410 L 960 540",
    },
    {
      from: "decision",
      to: "end",
      label: "Complete ✓",
      path: "M 960 640 L 960 760",
    },
  ],
  durationInFrames: 240,
};

export const RemotionRoot: React.FC = () => {
  return (
    <>
      {ALL_SEQUENCES.map((seq) => (
        <Composition
          key={seq.id}
          id={seq.id}
          component={SequenceDiagram}
          durationInFrames={seq.durationInFrames}
          fps={30}
          width={1920}
          height={1080}
          defaultProps={{ sequence: seq }}
        />
      ))}
      <Composition
        id={SAMPLE_FLOWCHART.id}
        component={FlowchartAnimation}
        durationInFrames={SAMPLE_FLOWCHART.durationInFrames}
        fps={30}
        width={1920}
        height={1080}
        defaultProps={{ flowchart: SAMPLE_FLOWCHART }}
      />
      {SECURITY_FLOWCHARTS.map((fc) => (
        <Composition
          key={fc.id}
          id={fc.id}
          component={FlowchartAnimation}
          durationInFrames={fc.durationInFrames}
          fps={30}
          width={1920}
          height={1080}
          defaultProps={{ flowchart: fc }}
        />
      ))}
      {ALL_CLASS_DIAGRAMS.map((diag) => (
        <Composition
          key={diag.id}
          id={diag.id}
          component={ClassDiagramAnimation}
          durationInFrames={diag.durationInFrames}
          fps={30}
          width={1920}
          height={1080}
          defaultProps={{ diagram: diag }}
        />
      ))}
    </>
  );
};
