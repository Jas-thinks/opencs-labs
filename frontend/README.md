# OpenCS Labs — frontend

React 18 + TypeScript single-page application built with Vite.

## Run

```bash
npm install --include=dev
npm run dev          # http://localhost:5173, proxies /api to :8000
npm run test         # vitest
npm run typecheck
npm run build        # dist/
```

In development, `vite.config.ts` proxies `/api` to `VITE_DEV_API_TARGET`
(default `http://localhost:8000`). In production, nginx proxies `/api` to the
backend service (see `nginx.conf` and `Dockerfile`), so the browser sees one
origin and the session cookie is first-party.

## Structure

```
src/
├── api/
│   ├── types.ts      types mirroring the backend OpenAPI schemas
│   └── client.ts     typed fetch wrapper, structured ApiError
├── app/
│   ├── AuthContext   session state, sign in/out
│   ├── routes        protected routes
│   ├── Layout        sidebar + topbar shell
│   └── useAsync      small data-fetching hook
├── components/
│   ├── ui            badges, progress, formatters, states
│   ├── Blocks        renders authored lesson blocks
│   └── Chart         dependency-free SVG chart renderer
├── features/
│   ├── auth          Login
│   ├── learning      LearnHome, LessonPage
│   ├── practice      PracticeHome, ExercisePage
│   ├── datasets      DatasetsHome, DatasetPage
│   └── notebooks     NotebooksHome
├── styles            design tokens + layout
└── test              vitest + testing-library
```

## Behaviour worth knowing

- **Session** is an HttpOnly cookie; the client always sends
  `credentials: "include"` and never reads the token.
- **401** clears the user and routes to `/login` via `onUnauthorized`.
- **Dataset snippets** are displayed and copied; the UI states clearly that
  they are never auto-executed. "Open in Notebook" opens JupyterLab; the
  student pastes and runs.
- **Errors** from the API are structured (`code`, `message`, `details`) and
  mapped to helpful messages — e.g. `UPSTREAM_UNAVAILABLE` explains that the
  notebook service is down and that nothing was lost.
- **Charts** render from data declared in the lesson YAML; no plotting library
  runs in the browser and no code is executed to draw a chart.

## Tests

`src/test/` covers the API client (credentials, query building, error mapping,
204 handling), formatting helpers and the app shell (login redirect, catalogue
render for a signed-in student) with `fetch` stubbed.
