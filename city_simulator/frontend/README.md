# frontend/

The React + TypeScript + Vite single-page app that is the city simulator's
interface (a node-based canvas built on `@xyflow/react`). The project-level
[README](../README.md) describes what it does and how the screens, nodes and
API fit together; this file is just the build/dev mechanics.

```bash
npm install
npm run build     # tsc -b && vite build  -> ../static/dist/ (what app.py serves)
npm run lint      # oxlint
npm run dev       # Vite dev server on :5173, proxies /api/* to Flask on :8420
```

`npm run build` writes into `../static/dist/` (gitignored), and `python3
app.py` serves that directory as-is, so after a build the running Flask
process picks up the new bundle on the next page refresh -- no server
restart needed for frontend-only changes. In dev mode, run `python3 app.py`
in another terminal for the API; `vite.config.ts` proxies `/api` to it.

Layout (`src/`):

| Path | What lives there |
|---|---|
| `main.tsx`, `App.tsx`, `App.css` | Entry point; breadcrumb bar, the per-scope screen switch, the shared job-status strip and Lightbox |
| `routes/router.ts` | The hand-rolled scope router (real URLs per canvas -- city, agent, place, gallery, scratch, storyboard) |
| `routes/*Screen.tsx` | One component per scope: `CitiesScreen`, `AgentScreen`, `PlaceScreen`, `GalleryScreen`, `ScratchScreen`, `StoryboardScreen`; `NewCityModal` |
| `flow/CityCanvas.tsx`, `flow/EntityCanvas.tsx` | The React Flow canvases (a city's; an agent's/place's own) |
| `flow/nodes/` | Every node type (`AgentNode`, `LocationNode`, `SimulationNode`, `TreatmentNode`, `StoryboardNode`, `FrameNode`, `VideoNode`, `ImageNode`, `StyleNode`, `ScratchImageNode`, `ScratchMusicNode`, `TextViewerNode`, `MissingNode`), the shared `NodeShell`/`Port`, and port colors (`portTypes.ts`) |
| `flow/edgeRules.ts` | The one table of which output port may plug into which input port |
| `flow/pipeline.ts` | Cross-node data derivation, recomputed from raw nodes/edges every render |
| `flow/usePersistedGraph.ts`, `graphIds.ts`, `reconcile.ts` | Autosaved graph documents (`/api/graph/<scope>`) and reconciling saved nodes against the city's current entities |
| `flow/useGraphLibrary.ts`, `useSavedGraphs.tsx`, `SavedGraphDialog.tsx` | The drawer's *Saved graphs* section: save a canvas (with its Storyboards' inner canvases) to the library, load one back with fresh ids |
| `flow/use*.ts`, `*NodeKit.ts`, `layout.ts` | Shared canvas hooks (add-node actions, pipeline callbacks, styles library, hidden-entity curation) and node <-> persisted-shape mapping |
| `inspector/` | The right-hand Inspector panel (city overview + generation log, agent/place detail, media grid) |
| `api/` | Typed fetch wrappers (`client.ts`), response types (`types.ts`), visuals job polling |
| `state/` | zustand stores: the app-wide job poller (`jobStore`) and the Lightbox |
| `theme/tokens.css` | Design tokens (colors, fonts, radii) |
