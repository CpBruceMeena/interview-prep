import { Composition } from "remotion";
import { SequenceDiagram } from "./SequenceDiagram";
import { LLD_SEQUENCES } from "./sequences";
import { ADVANCED_SEQUENCES } from "./sequences-advanced";
import { ECS_AGENT_SEQUENCES } from "./sequences-agent-ecs";

const ALL_SEQUENCES = [...LLD_SEQUENCES, ...ADVANCED_SEQUENCES, ...ECS_AGENT_SEQUENCES];

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
    </>
  );
};
