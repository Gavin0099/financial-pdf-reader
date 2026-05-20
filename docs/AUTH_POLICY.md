# API Auth Policy

Last updated: 2026-05-20

## Default rule
- `/api/v1/*` endpoints are JWT protected unless explicitly listed as public.
- Protected routers use `APIRouter(dependencies=[Depends(JWTBearer())])`.
- Clients must send header: `Authorization: Bearer <token>`.

## Protected endpoint groups
- `/api/v1/documents/*` from routers: `documents`, `summary`, `classification`, `tables`, `disclosures`, `patterns`
- `/api/v1/reports/diff*` from router: `diff`
- `/api/v1/stocks/*` from router: `data_source`

## Public endpoint groups
- Root/service metadata routes (for health/info):
  - `GET /`
  - `GET /healthz`
- UI/static assets:
  - `GET /ui`
  - `GET /static/*`

## Known exception
- `apis/v1/routers/audit.py` currently does **not** attach `JWTBearer()`.
- Mounted path: `/api/v1/documents/{document_id}/audit`.
- Treat as temporary exception; if this endpoint should be protected, add router-level dependency.

## UI integration note
- `static/index.html` now supports optional token input and sends auth header when provided.
- If backend auth is enabled and token is empty, API calls will return 401/403 as expected.