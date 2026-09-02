# Repository Guidelines

## Project Structure & Module Organization

The repository is a four-layer portfolio system. `bp_ingest/` contains market-data adapters, cleaning, and CLI jobs; `bp_api/` contains the FastAPI application, repositories, task workers, and quantitative engines under `bp_api/quant/`; and `web/` is the Next.js App Router frontend. Backend tests live in `bp_api/tests/`. Database definitions are in `ddl/schema.sql`; operational scripts and deployment configuration are in `scripts/` and `deploy/`; user-facing technical material and images are in `docs/`. Treat `vendor/`, `autocallables-pricing-master/`, and design-reference directories as local reference material, not production modules.

## Build, Test, and Development Commands

Install Python dependencies with `pip install -r requirements.txt`. Run the backend with `uvicorn bp_api.main:app --reload --port 8000`; use `BP_TASK_MODE=inline` for local work without Redis/Celery. Run the ingestion CLI with `python -m bp_ingest --help` (for example, `python -m bp_ingest run`).

From `web/`, install with `npm ci --legacy-peer-deps`, start development with `npm run dev`, type-check with `npm run typecheck`, and build with `npm run build`. The CI-equivalent checks are `python -m pytest bp_api/tests -q` and `cd web && npm run build`.

## Coding Style & Naming Conventions

Use four-space indentation for Python and follow clear, type-annotated FastAPI/Pydantic patterns. Use `snake_case` for Python modules, functions, and variables; use PascalCase for React components and camelCase for TypeScript variables. Keep frontend API types and option registries in `web/lib/api.ts` synchronized with backend registrations. Preserve existing formatting and Tailwind/shadcn conventions; no separate repository formatter or linter is configured.

## Testing Guidelines

Tests use pytest and are named `test_*.py` with `test_*` functions. Add focused regression coverage for changes to quant logic, data cleaning, authentication, or API routes; especially preserve the no-future-data guarantees in backtests. Run a targeted test during iteration, then the full `python -m pytest bp_api/tests -q` suite before submitting.

## Commit & Pull Request Guidelines

Recent commits use short, imperative Chinese descriptions (for example, `修复加密货币看板更新bug`); keep commits focused and use the repository’s concise style. Pull requests should explain the behavior change, identify affected backend/frontend/database areas, link an issue when applicable, and include screenshots for visible UI changes. Report tests and build commands run, and call out required environment variables, migrations, or deployment changes.

## Security & Configuration

Never commit `.env`, credentials, cookies, or production secrets; use `.env.example` as the template. Keep `BP_JWT_SECRET` strong and at least 32 characters. Review database changes against `ddl/schema.sql` and deployment notes, and do not rerun migrations already applied in production.
