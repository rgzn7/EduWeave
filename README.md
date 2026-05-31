<!-- @Date: 2026-05-31 @Author: xisy @Discription: EduWeave root project README -->

# EduWeave

Language: English | [中文](README.zh-CN.md)

EduWeave is an end-to-end AI teaching resource reconstruction system that turns textbooks into classroom-ready materials. It converts raw inputs such as textbook PDFs and class learning-profile files into standardized teaching deliverables: curriculum outlines, lesson plans, PPT courseware, homework, unit/final exam papers, and knowledge-point coverage reports.

The project targets the "MinerU-based textbook-to-classroom AI teaching resource reconstruction" scenario. It follows a teacher-centered workflow and uses a decoupled architecture: the backend exposes RESTful APIs with FastAPI, and the frontend is a React single-page application built with Vite.

## Core Capabilities

EduWeave compresses a traditionally time-consuming and fragmented teaching-resource production process into a seven-step closed loop: upload, parse, structure, plan, generate, validate, and deliver. Each stage is versioned, and each downstream stage uses a confirmed upstream version as its input baseline, making the whole workflow traceable and repeatable.

- Multi-version textbook parsing and review: PDF upload, multiple textbook versions, high-fidelity MinerU parsing, page-level evidence browsing, anomaly lists, partial page re-parsing, manual correction, and parse confirmation.
- Class learning-profile aggregation: upload multiple student DOCX files, parse individual profiles locally, and use an LLM to aggregate a class-level profile with shared difficulties, learning-style distribution, tiered goals, and teaching suggestions.
- Knowledge graph editing: chapter trees, knowledge-point browsing, evidence tracing, patch-based manual revisions, version management, and Milvus-backed semantic retrieval for knowledge points and semantic chunks.
- One-click generation: cross-stage orchestration from parsing to deliverables, with options such as automatic parse confirmation, lesson count, and lesson duration.
- Deliverable management: curriculum outlines, lesson plans, PPT courseware via Raccoon PPT, homework, unit/final exam papers, and coverage reports, all with query, preview, and on-demand generation support.
- Task center: task lists, step-level progress, failure diagnosis, and lesson-level resumability.
- Export and download: Word export for curriculum outlines, lesson plans, papers, and other resources, with downloads served through Huawei Cloud OBS signed URLs.
- Lesson-preparation assistant: a project-level conversational assistant that can refine curriculum outlines and lesson plans into new versions, answer textbook-grounded questions with hybrid retrieval, and show tool calls on a transparent timeline. It is available both as a lesson-page drawer and as a standalone assistant page.

## Architecture

The backend follows a "version-first, async-first, structured-first" design. It is organized into five logical layers: access, application, domain persistence, infrastructure, and async execution. Runtime collaboration happens across three application processes and several infrastructure components:

- Application processes: API service for HTTP requests and the in-process assistant worker pool; Celery worker for parsing, extraction, generation, and analysis tasks; Celery beat for scheduled task recovery and courseware status polling.
- Data and middleware: MySQL 8.0 as the business data center, Redis as Celery broker/backend, Milvus/Zilliz as the vector retrieval center, and Huawei Cloud OBS as the file asset store.
- External AI services: MinerU for high-fidelity textbook parsing, OpenAI-compatible LLMs for structured generation, an independent embedding service for vectorization, and Raccoon PPT OpenAPI for courseware layout generation.

The system advances through three stages. Database entities are linked through strict version chains, and `generation_batch` freezes the input baseline during generation to keep all deliverables consistent:

```text
textbook_version
   └─ parse_version (parent chain supports partial re-parsing)
        └─ knowledge_version (chapter tree + knowledge points + semantic chunks + vectors)
             └─ generation_batch (frozen baseline + chapter range + lesson/assessment strategy)
                  ├─ curriculum_plan
                  │    └─ lesson_plan (multiple lessons)
                  │         ├─ courseware_result (Raccoon PPT)
                  │         └─ homework_result → homework_question
                  ├─ assessment_blueprint → paper_result → question_item
                  └─ coverage_report
learner_profile_version (aggregated class profile) → frozen by generation_batch
```

![EduWeave system architecture](docs/assets/eduweave-system-architecture.png)

For the full design and key technical implementation details, see [Technical Solution](docs/技术解决方案.md).

## Tech Stack

| Area | Technologies |
| --- | --- |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Celery + Redis, Pydantic v2, PyMilvus, Huawei Cloud OBS SDK, PyMuPDF / python-docx |
| Frontend | React 18, TypeScript 5, Vite 6, React Router v7, TanStack Query v5, Zustand, Tailwind CSS 3, lucide-react, gsap |
| Data and middleware | MySQL 8.0, Redis, Milvus/Zilliz, Huawei Cloud OBS |
| External AI services | MinerU, OpenAI-compatible LLMs, independent embedding service, Raccoon PPT OpenAPI |

## Repository Layout

```text
EduWeave/
├── backend/            FastAPI backend, organized by business domain:
│   │                   textbook/parsing/knowledge/curriculum/lesson_plan/
│   │                   courseware/assessment/homework/coverage/orchestrator/agent
│   ├── app/            Application code: core utilities, modules, shared integrations
│   ├── migrations/     Alembic database migrations
│   ├── scripts/        Local startup, bootstrap, and reconciliation scripts
│   ├── tests/          Backend tests
│   └── docs/           Backend documentation
├── frontend/           Vite + React single-page application
├── sql/                Database schema SQL scripts for historical reference and alignment
├── docs/               Project-level documentation and architecture assets
└── 教育赛题/            Original challenge materials, textbooks, and learning-profile samples
```

## Quick Start

For complete environment variables, initialization steps, and multi-process startup details, see the [Backend README](backend/README.md). The following is the minimal local startup path.

### Prerequisites

Prepare and start MySQL 8.0, Redis, and Milvus. Configure credentials for MinerU, LLM, embedding, Raccoon PPT, OBS, and other external services as needed.

### Backend

The backend is expected to run in the isolated `backend/.venv` virtual environment to avoid binary dependency conflicts across packages such as numpy and pymilvus.

```bash
cd backend

# 1. Prepare environment variables
cp .env.example .env

# 2. Create and install the virtual environment
python -m venv .venv
./.venv/bin/python -m pip install "setuptools>=69.0" wheel
./.venv/bin/python -m pip install --no-build-isolation -e ".[dev]"

# 3. Initialize the database with Alembic
./.venv/bin/python -m alembic upgrade head

# 4. Bootstrap the local demo account and required Milvus collections
./.venv/bin/python scripts/bootstrap_local.py

# 5. Start the API service on port 8010 by default
./.venv/bin/python scripts/start_dev.py

# 6. Start the Celery worker with embedded beat in another process
./.venv/bin/celery -A app.worker worker -B \
  -Q celery,profile_queue,parsing_queue,knowledge_queue,generation_queue --loglevel=info
```

Run backend tests:

```bash
cd backend && ./.venv/bin/python -m pytest
```

### Frontend

```bash
cd frontend

# Prepare environment variables. VITE_API_BASE_URL should point to the backend;
# the default backend URL is http://127.0.0.1:8010.
cp .env.example .env

npm install
npm run dev      # Development server defaults to port 7777
```

## Deployment

Both backend and frontend provide `Dockerfile` entries for containerized deployment. The backend image runs API/worker processes, while the frontend image serves built assets through Nginx, using `frontend/nginx.conf`. The backend exposes `/health` and `/ready` probes for container orchestration and readiness checks.

## Documentation

- [Technical Solution](docs/技术解决方案.md): overall design, key implementation paths, performance and engineering practices, innovation points, and applicable scenarios.
- [Backend README](backend/README.md): environment variables, database initialization, multi-process startup, and runtime constraints.
- [Contributing Guide](CONTRIBUTING.md): contribution workflow, local checks, and sensitive-file handling.

## Maintainers

Maintainer information is available in [MAINTAINERS.md](MAINTAINERS.md). `rgzn7` is the primary maintainer / project owner, and `sevzq` is a core maintainer responsible for frontend and backend feature maintenance, PR review, issue triage, release/readiness checks, and AI workflow and automation maintenance.

## License

This project is licensed under the [MIT License](LICENSE).
