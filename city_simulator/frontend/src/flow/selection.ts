export type Selection =
  | { kind: 'city' }
  | { kind: 'agent'; characterId: string }
  | { kind: 'place'; placeId: string };
