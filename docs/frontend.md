# Frontend

React 19 + Vite 8 + react-router 7. UI kits: MUI 9 (Uploads, UploadNew, RunCreating, GraphView) and shadcn/Tailwind 4 (Runs, RunDetail, Relationships, Document). Graph: `react-force-graph-2d`. Markdown: `react-markdown` with `rehype-raw` / `rehype-sanitize`.

The API base URL is hard-coded to `http://localhost:8000` in each page.

## Run it

```sh
cd frontend
npm install
npm run dev      # http://localhost:5173  (use localhost, not 127.0.0.1)
npm run build
npm run lint
```

## Routes (`src/App.jsx`)

| Route | Page | API calls | What it shows |
|---|---|---|---|
| `/uploads` | `Uploads.jsx` | `GET /api/uploads` | Uploaded files; "create run" per file |
| `/uploads/new` | `UploadNew.jsx` | `POST /api/uploads` | Drag-and-drop zone (`.txt` only) |
| `/runs/creating` | `RunCreating.jsx` | `POST /api/uploads/{id}/run`, then `GET /api/runs/{id}` every 2 s | Spinner until `status === "completed"`, then redirects |
| `/runs` | `Runs.jsx` | `GET /api/runs` | Searchable run list |
| `/runs/:runId` | `RunDetail.jsx` | `GET /api/runs/{id}` | Summary cards and entity table with type badges |
| `/runs/:runId/relationships` | `Relationships.jsx` | `GET /api/runs/{id}` | Source, type, target table (ids resolved to names) with filter |
| `/runs/:runId/document` | `Document.jsx` | `GET /api/runs/{id}`, `GET /api/runs/{id}/document` | Source text (plain, markdown or HTML) with entity names highlighted |
| `/runs/:runId/graph` | `GraphView.jsx` | `GET /api/runs/{id}/graph` | Force-directed graph, colour by type, click a node to open the document at that entity |

Clicking an entity row opens `/runs/:id/document?entity=<name>`, which scrolls to and flashes the first matching highlight.

## Data flow

Upload page → `POST /api/uploads` (gets `upload_id`) → router state → `RunCreating` starts the run and polls → `/runs/:id` once `output.json` exists. All result pages read the same `entities` / `relationships` payload, except the graph page which reads the server-built `{nodes, edges}`.

## Known rough edges

- The graph page has no navigation link; open `/runs/<id>/graph` directly.
- Polling stops only on `completed`; there is no error state.
- `UploadNew.jsx` makes a dead `POST /api/runs` call (405) before navigating; it is harmless.
- Type-based UI (summary counts) compares lowercase types, while docling runs emit `Company`, `Person`, etc.
- Lint reports pre-existing style errors; the build passes. Details in [`tests/known-issues.md`](tests/known-issues.md).
