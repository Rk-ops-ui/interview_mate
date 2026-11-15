# CareerCoach AI — AI-Powered Mock Interview Agent

CareerCoach AI is a web-based mock interview application. A candidate uploads a PDF resume, provides a job description, and answers interview questions aloud. The React frontend records audio and sends it to a FastAPI backend for transcription and saving.

> **Documentation note:** This README is based on the supplied React frontend, backend import list, environment-variable names, and MySQL schema. Backend behaviour beyond the visible API contract should be verified against the implementation before production deployment.

## Contents
- [Features](#features)
- [Technology stack](#technology-stack)
- [Architecture](#architecture)
- [Project structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Local setup](#local-setup)
- [Environment variables](#environment-variables)
- [Database setup](#database-setup)
- [LiteLLM configuration](#litellm-configuration)
- [Run locally](#run-locally)
- [API contract](#api-contract)
- [Google Cloud deployment plan](#google-cloud-deployment-plan)
- [Security notes](#security-notes)

## Features

- PDF resume upload and job-description input.
- Interview question retrieval, one question at a time.
- Browser-based question playback using the Web Speech API (`speechSynthesis`).
- Candidate audio recording using `MediaRecorder` and the browser microphone.
- Audio upload to the backend for speech-to-text processing.
- Display of the returned transcription and save status.
- MySQL storage for interview questions and candidate responses.
- LLM orchestration using LangChain and LiteLLM.
- Web search/crawling integrations using Firecrawl and Crawl4AI.
- Embeddings and similarity components using Sentence Transformers and scikit-learn.

The supplied frontend's completion screen currently contains a placeholder for interview feedback. Confirm that answer evaluation and consolidated feedback are implemented in the backend before advertising them as completed features.

## Technology stack

**Frontend**
- React, React DOM, Vite
- Lucide React
- Browser APIs: `MediaRecorder`, `getUserMedia`, `speechSynthesis`

**Backend**
- Python, FastAPI, Uvicorn, Pydantic
- PyMuPDF
- LangChain, LangChain OpenAI integration, LiteLLM
- Firecrawl, Crawl4AI
- MySQL Connector/Python
- Faster-Whisper
- Sentence Transformers, scikit-learn

**Suggested Google Cloud infrastructure**
- Firebase Hosting for the React production build.
- Cloud Run for the FastAPI backend and, optionally, a separate LiteLLM proxy.
- Cloud SQL for MySQL.
- Secret Manager for credentials.
- Cloud Storage for persistent resume/audio files if the application needs to retain them.

This is a proposed deployment architecture, not a claim that the application is already deployed on these services.

## Architecture

```text
Candidate browser
      |
      v
React + Vite frontend
      | HTTP / multipart form-data
      v
FastAPI backend
      |
      +---- LiteLLM proxy ---- Gemini provider
      |
      +---- Firecrawl / Crawl4AI
      |
      +---- Faster-Whisper (speech-to-text)
      |
      +---- Sentence Transformers / scikit-learn
      |
      +---- MySQL database
```

The browser currently reads questions aloud using built-in speech synthesis. Faster-Whisper is used on the backend for speech-to-text; it is not the frontend text-to-speech engine.

## Project structure

Suggested layout (adjust names to match your repository):

```text
careercoach-ai/
├── backend/
│   ├── main.py
│   ├── project_main.py
│   ├── requirements.txt
│   ├── schema.sql
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   └── main.jsx
│   ├── public/
│   ├── index.html
│   ├── package.json
│   ├── package-lock.json
│   └── vite.config.js
├── .gitignore
└── README.md
```

## Prerequisites

- Python 3.11 is a reasonable starting runtime; verify compatibility with your pinned dependencies.
- Node.js and npm.
- MySQL server.
- Gemini API key.
- Firecrawl API key.
- LiteLLM proxy configuration and credentials.
- A modern browser with microphone support (Chrome or Edge recommended).

Crawl4AI may require browser binaries and operating-system libraries. Faster-Whisper and Sentence Transformers may download model files on first use.

## Local setup

### 1. Clone the repository

```bash
git clone https://github.com/<YOUR_GITHUB_USERNAME>/<YOUR_REPOSITORY>.git
cd <YOUR_REPOSITORY>
```

Replace the placeholders with your actual repository URL.

### 2. Set up the backend

From the backend directory:

```bash
cd backend
python -m venv venv
```

Windows PowerShell:

```powershell
.\venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

If the project uses Crawl4AI's browser crawler, install its browser dependencies:

```bash
crawl4ai-setup
```

### 3. Set up the frontend

From the frontend directory, install packages:

```bash
cd frontend
npm install
```

The supplied frontend defaults to `http://127.0.0.1:8000` for the backend. To override it, create `frontend/.env`:

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8000
```

## Environment variables

Create `backend/.env` from `backend/.env.example` and fill in the values locally:

```dotenv
FIRECRAWL_API_KEY=
GEMINI_API_KEY=

MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=
MYSQL_PASSWORD=
MYSQL_DATABASE=

# Actual LiteLLM proxy database connection URL, if database-backed
# LiteLLM features are enabled. Do not use the literal "(litellm)".
DATABASE_URL=

# LiteLLM proxy authentication key
LITELLM_MASTER_KEY=
```

| Variable | Purpose |
|---|---|
| `FIRECRAWL_API_KEY` | Firecrawl authentication. |
| `GEMINI_API_KEY` | Gemini credential, if read by the application or proxy configuration. |
| `MYSQL_HOST` | MySQL server hostname/address. |
| `MYSQL_PORT` | MySQL port, commonly `3306`. |
| `MYSQL_USER` | MySQL username. |
| `MYSQL_PASSWORD` | MySQL password. |
| `MYSQL_DATABASE` | Application database name. |
| `DATABASE_URL` | LiteLLM proxy database URL, if database-backed proxy features are enabled. |
| `LITELLM_MASTER_KEY` | LiteLLM proxy client-authentication key. |

Check all backend modules and the LiteLLM config for any additional variables. Do not commit the real `.env` file. Never put API keys, database passwords, or the LiteLLM master key in frontend `VITE_*` variables.

## Database setup

Create the database named by `MYSQL_DATABASE`, then import the supplied `schema.sql`. For example:

```sql
CREATE DATABASE your_database_name
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;
```

Then, from a terminal:

```bash
mysql -u YOUR_MYSQL_USER -p YOUR_MYSQL_DATABASE < schema.sql
```

### `interview_questions` table

The supplied schema stores:

| Column | Purpose |
|---|---|
| `id` | Auto-increment primary key. |
| `interview_id` | Interview identifier; indexed. |
| `candidate_name` | Candidate name, nullable. |
| `question_id` | Question identifier. |
| `question_text` | Question text. |
| `category` | Question category. |
| `difficulty` | Question difficulty. |
| `source_url` | Source URL, if available. |
| `source_type` | Source type, if available. |
| `resume_relevance` | Resume relevance information. |
| `expected_answer_points` | JSON expected-answer points. |
| `question_order` | Question ordering. |
| `status` | Question status; defaults to `pending`. |
| `created_at` | Creation timestamp. |
| `candidate_response` | Candidate's transcribed response. |
| `answered_at` | Answer timestamp. |

The schema defines `id` as the primary key and an index on `interview_id`. It does not define a unique constraint on `question_id` or a foreign key for interview records.

## LiteLLM configuration

Configure LiteLLM according to the model/provider and deployment method you use. The proxy configuration should define the Gemini model/provider, obtain the Gemini credential securely, and configure a proxy master key.

A local proxy can be started with a configuration file using:

```bash
litellm --config config.yaml --port 4000
```

Configure the backend's LiteLLM-compatible client (the supplied imports include `ChatOpenAI`) with the actual proxy base URL and matching authentication key. Do not expose the master key in frontend code.

If database-backed LiteLLM features are enabled, `DATABASE_URL` must contain the actual database connection URL expected by LiteLLM. The application's `MYSQL_*` settings and LiteLLM's `DATABASE_URL` may refer to different databases; do not assume they are interchangeable.

## Run locally

Run MySQL, LiteLLM, FastAPI, and Vite in separate terminals.

**1. MySQL:** Start the local MySQL server and ensure the database/schema exists.

**2. LiteLLM proxy:**

```bash
litellm --config config.yaml --port 4000
```

**3. FastAPI backend:** From the backend directory, assuming the FastAPI instance is named `app` in `main.py`:

```bash
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

If your entry-point filename or FastAPI variable differs, adjust `main:app`.

**4. React frontend:** From the frontend directory:

```bash
npm run dev
```

Open the local URL printed by Vite (commonly `http://localhost:5173`).

## API contract

The supplied React frontend calls these routes:

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/upload-resume/` | Upload a resume PDF and job description; create an interview. |
| `GET` | `/interview/{interview_id}/next-question` | Retrieve the next interview question. |
| `POST` | `/interview/{interview_id}/submit-audio` | Submit recorded audio for transcription and saving. |

### Resume upload

The frontend sends multipart form data:
- `file`: PDF resume.
- `job_description`: job description text.

It expects the response to contain `interview_id` and optionally `total_questions`.

### Next question

The frontend expects `question_id` and `question`, with optional `category` and `difficulty`. When the interview is complete, it expects `completed: true`.

### Audio submission

The frontend sends multipart form data:
- `question_id`: current question identifier.
- `audio`: recorded audio (format depends on browser support; the supplied frontend may use WebM, OGG, or MP4).

It expects `saved` and `transcribed_answer` in the response.

These are the paths and response fields expected by the supplied frontend. Confirm that your backend implements the same contract.

## Google Cloud deployment plan

Suggested service mapping:

| Component | Suggested service | Role |
|---|---|---|
| React frontend | Firebase Hosting | Host the Vite production build. |
| FastAPI backend | Cloud Run | Run the API container. |
| LiteLLM proxy | Separate Cloud Run service, if independently operated | Provide the LLM gateway. |
| MySQL | Cloud SQL for MySQL | Managed relational database. |
| Secrets | Secret Manager | Store credentials and API keys. |
| Uploaded files | Cloud Storage | Persist resumes/audio if required. |

### Build the frontend

Set the backend URL at build time:

```dotenv
VITE_API_BASE_URL=https://YOUR_BACKEND_SERVICE_URL
```

Then build:

```bash
npm run build
```

Deploy the generated `dist/` directory to Firebase Hosting or your chosen static host. Vite environment values are embedded in the browser bundle, so only public configuration such as the API base URL belongs in `VITE_*` variables.

### Run the backend on Cloud Run

The container must listen on `0.0.0.0` and the port provided by Cloud Run's `PORT` environment variable. For example:

```bash
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
```

Configure secrets as Cloud Run environment variables or Secret Manager references. Configure Cloud SQL connectivity and networking so the backend can reach the database.

### Production considerations

- Restrict CORS to the deployed frontend origin.
- Store provider keys, database passwords, and the LiteLLM master key in Secret Manager.
- Do not rely on a Cloud Run container's local filesystem for durable uploaded files.
- Faster-Whisper and Sentence Transformers can require significant memory, startup time, and model downloads. Measure resource use and configure CPU/memory accordingly.
- Crawl4AI browser automation may require browser binaries and OS libraries in the container image.
- Configure request timeouts and concurrency for audio transcription and resume processing.
- Test the complete resume upload → question retrieval → audio submission → interview completion flow after deployment.

## Security notes

Do not commit or publish:
- `.env` files with real credentials.
- `node_modules/`, `venv/`, `.venv/`, or `__pycache__/`.
- Private resumes, audio recordings, or database exports.
- Downloaded model weights unless intentionally distributing them.

Commit dependency manifests (`requirements.txt`, `package.json`, and `package-lock.json`) so environments can be recreated.

If a secret was committed to Git, deleting it in a later commit is not enough. Rotate the credential and clean the repository history if necessary.

## License

Add the license that applies to this repository before publishing the project publicly.
