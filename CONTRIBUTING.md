# Contributing to EduWeave

Thank you for helping improve EduWeave. This project combines a FastAPI backend,
a React frontend, database migrations, and AI workflow integrations, so small,
well-scoped contributions are easiest to review and maintain.

## Contribution Workflow

1. Open or reference an issue when the change affects product behavior,
   deployment, data models, or public documentation.
2. Create a focused branch for one change at a time.
3. Keep pull requests small enough to review. Separate feature work,
   refactoring, generated assets, and documentation cleanup when possible.
4. Explain the user-facing impact, touched modules, and verification steps in
   the pull request description.

## Local Checks

Run the checks that match the area you changed:

```bash
# Backend
cd backend
./.venv/bin/python -m pytest

# Frontend
cd frontend
npm run lint
npm run build
```

If a check cannot be run locally because of missing services or credentials,
note that clearly in the pull request.

## Sensitive Files

Do not commit secrets, credentials, database backups, `.env` files, local Claude
or editor settings, exported production data, or large generated artifacts unless
they are explicitly required and reviewed.

Use the existing `.env.example` files for documenting environment variables.

## Maintainers

Maintainer roles are listed in [MAINTAINERS.md](MAINTAINERS.md). For ownership
and review routing, see `.github/CODEOWNERS`.
