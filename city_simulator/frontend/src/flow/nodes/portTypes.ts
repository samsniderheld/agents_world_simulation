// Matches the tokens defined in theme/tokens.css's --port-* custom
// properties -- entity refs (agent/place/run) share a warm neutral,
// narrative data (treatment/shot) a cool cyan, media (image/video) a
// green, and style is deliberately the odd one out (violet).
export type PortType = 'agent' | 'place' | 'run' | 'treatment' | 'shot' | 'image' | 'video' | 'style';

const GROUP: Record<PortType, string> = {
  agent: 'var(--port-entity)',
  place: 'var(--port-entity)',
  run: 'var(--port-entity)',
  treatment: 'var(--port-narrative)',
  shot: 'var(--port-narrative)',
  image: 'var(--port-media)',
  video: 'var(--port-media)',
  style: 'var(--port-style)',
};

export function portColor(type: PortType): string {
  return GROUP[type];
}
