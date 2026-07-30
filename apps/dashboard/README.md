# Radius Dashboard

Next.js application for repository management, analysis history, blast radius visualization, test execution reports, and explainable confidence reports.

The dashboard presents Radius intelligence. It must not contain domain business logic.

## Backend connection

Set these public runtime variables before running the dashboard:

- `NEXT_PUBLIC_RADIUS_API_BASE_URL` defaults to `http://localhost:8000`.
- `NEXT_PUBLIC_RADIUS_ORGANIZATION_ID` is required and is sent as `X-Radius-Organization-Id`.
- `NEXT_PUBLIC_RADIUS_API_KEY` is optional and is sent as `X-Radius-API-Key`.
