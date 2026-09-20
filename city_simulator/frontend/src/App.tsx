import { useEffect } from 'react';
import { CityCanvas } from './flow/CityCanvas';
import { AgentScreen } from './routes/AgentScreen';
import { PlaceScreen } from './routes/PlaceScreen';
import { ScratchScreen } from './routes/ScratchScreen';
import { navigate, useRoute, type Scope } from './routes/router';
import { useJobStore } from './state/jobStore';
import './App.css';

// A single fixed board replaces the old Studio tab exactly (Studio was
// one page too, not a list of named boards) -- real multi-board
// management is a top-level-canvas concern that arrives with real
// multi-city support, not before.
const DEFAULT_SCRATCH_BOARD = 'default';

function breadcrumbFor(scope: Scope): { label: string; scope: Scope }[] {
  const root = { label: 'CITY', scope: { kind: 'city' } as Scope };
  switch (scope.kind) {
    case 'city':
      return [root];
    case 'agent':
      return [root, { label: scope.agentId, scope }];
    case 'place':
      return [root, { label: scope.placeId, scope }];
    case 'scratch':
      return [root, { label: `SCRATCH · ${scope.boardId}`, scope }];
  }
}

function JobStrip() {
  const { historyStatus, agentsState, visualsStatus } = useJobStore();
  const running = [
    historyStatus?.phase === 'running' && 'history · generating',
    agentsState?.status.phase === 'running' && 'agents · running',
    visualsStatus?.phase === 'running' && 'visuals · generating',
  ].filter(Boolean) as string[];

  if (running.length === 0) return null;
  return (
    <div className="job-strip">
      {running.map((label) => (
        <span key={label} className="job-strip-item">
          <span className="job-dot" />
          {label}
        </span>
      ))}
    </div>
  );
}

function App() {
  const scope = useRoute();
  const start = useJobStore((s) => s.start);
  const stop = useJobStore((s) => s.stop);

  useEffect(() => {
    start();
    return () => stop();
  }, [start, stop]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && scope.kind !== 'city') {
        navigate({ kind: 'city' });
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [scope.kind]);

  const crumbs = breadcrumbFor(scope);

  return (
    <div className="app-shell">
      <header className="breadcrumb-bar">
        {crumbs.map((crumb, i) => (
          <span key={i} className="breadcrumb-segment">
            {i > 0 && <span className="breadcrumb-sep">/</span>}
            <button
              className="breadcrumb-btn"
              disabled={i === crumbs.length - 1}
              onClick={() => navigate(crumb.scope)}
            >
              {crumb.label}
            </button>
          </span>
        ))}
        <span className="breadcrumb-spacer" />
        <button
          className="breadcrumb-btn"
          disabled={scope.kind === 'scratch'}
          onClick={() => navigate({ kind: 'scratch', boardId: DEFAULT_SCRATCH_BOARD })}
        >
          Scratch
        </button>
      </header>

      <main className="app-main">
        {scope.kind === 'city' && <CityCanvas />}
        {scope.kind === 'agent' && <AgentScreen characterId={scope.agentId} />}
        {scope.kind === 'place' && <PlaceScreen placeId={scope.placeId} />}
        {scope.kind === 'scratch' && <ScratchScreen boardId={scope.boardId} />}
      </main>

      <JobStrip />
    </div>
  );
}

export default App;
