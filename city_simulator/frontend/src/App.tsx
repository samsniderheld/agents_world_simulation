import { useEffect } from 'react';
import { Lightbox } from './components/Lightbox';
import { CityCanvas } from './flow/CityCanvas';
import { AgentScreen } from './routes/AgentScreen';
import { CitiesScreen } from './routes/CitiesScreen';
import { GalleryScreen } from './routes/GalleryScreen';
import { PlaceScreen } from './routes/PlaceScreen';
import { ScratchScreen } from './routes/ScratchScreen';
import { StoryboardScreen } from './routes/StoryboardScreen';
import { navigate, useRoute, type Scope } from './routes/router';
import { useJobStore } from './state/jobStore';
import './App.css';

// A single fixed board replaces the old Studio tab exactly (Studio was
// one page too, not a list of named boards) -- real multi-board
// management belongs with the top-level canvas, which now exists (see
// CitiesScreen) but doesn't extend to scratch boards yet.
const DEFAULT_SCRATCH_BOARD = 'default';

function breadcrumbFor(scope: Scope): { label: string; scope: Scope }[] {
  const root = { label: 'CITIES', scope: { kind: 'root' } as Scope };
  switch (scope.kind) {
    case 'root':
      return [root];
    case 'city':
      return [root, { label: scope.cityId, scope }];
    case 'agent': {
      const originCrumbs = scope.from ? breadcrumbFor(scope.from) : [root, { label: scope.cityId, scope: { kind: 'city', cityId: scope.cityId } as Scope }];
      return [...originCrumbs, { label: scope.agentId, scope }];
    }
    case 'place': {
      const originCrumbs = scope.from ? breadcrumbFor(scope.from) : [root, { label: scope.cityId, scope: { kind: 'city', cityId: scope.cityId } as Scope }];
      return [...originCrumbs, { label: scope.placeId, scope }];
    }
    case 'gallery':
      return [root, { label: scope.cityId, scope: { kind: 'city', cityId: scope.cityId } }, { label: 'GALLERY', scope }];
    case 'scratch': {
      const originCrumbs = scope.from ? breadcrumbFor(scope.from) : [root];
      return [...originCrumbs, { label: `SCRATCH · ${scope.boardId}`, scope }];
    }
    case 'storyboard': {
      const originCrumbs = scope.from ? breadcrumbFor(scope.from) : [root];
      return [...originCrumbs, { label: `STORYBOARD · ${scope.storyboardId}`, scope }];
    }
  }
}

// Which city (if any) the current scope belongs to -- drives the
// header's "Gallery" button (enabled/target) below. `from` chains aren't
// consulted here: the Gallery button always means "this screen's own
// city," not wherever an agent/place happened to be opened from.
function cityIdFor(scope: Scope): string | undefined {
  switch (scope.kind) {
    case 'city':
    case 'agent':
    case 'place':
    case 'gallery':
      return scope.cityId;
    default:
      return undefined;
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
  const crumbs = breadcrumbFor(scope);

  useEffect(() => {
    start();
    return () => stop();
  }, [start, stop]);

  // Esc goes up one level -- literally the second-to-last breadcrumb,
  // since scopes nest the same way the breadcrumb displays them.
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && crumbs.length > 1) {
        navigate(crumbs[crumbs.length - 2].scope);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [crumbs]);

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
        {(() => {
          const cityId = cityIdFor(scope);
          return (
            <button
              className="breadcrumb-btn"
              disabled={!cityId || scope.kind === 'gallery'}
              onClick={() => cityId && navigate({ kind: 'gallery', cityId })}
            >
              Gallery
            </button>
          );
        })()}
        <button
          className="breadcrumb-btn"
          disabled={scope.kind === 'scratch'}
          onClick={() => navigate({ kind: 'scratch', boardId: DEFAULT_SCRATCH_BOARD, from: scope })}
        >
          Scratch
        </button>
      </header>

      <main className="app-main">
        {scope.kind === 'root' && <CitiesScreen />}
        {scope.kind === 'city' && <CityCanvas cityId={scope.cityId} />}
        {scope.kind === 'agent' && <AgentScreen cityId={scope.cityId} characterId={scope.agentId} />}
        {scope.kind === 'place' && <PlaceScreen cityId={scope.cityId} placeId={scope.placeId} />}
        {scope.kind === 'gallery' && <GalleryScreen cityId={scope.cityId} />}
        {scope.kind === 'scratch' && <ScratchScreen boardId={scope.boardId} from={scope.from} />}
        {scope.kind === 'storyboard' && <StoryboardScreen storyboardId={scope.storyboardId} from={scope.from} />}
      </main>

      <JobStrip />
      <Lightbox />
    </div>
  );
}

export default App;
