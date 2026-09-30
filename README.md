# SupportAI

AI-powered incident analysis for production-support teams. SupportAI turns compact closed-incident evidence into grounded troubleshooting guidance, helping engineers search less, avoid guesswork, and reach validated next actions faster.

## What it does

- Routes incidents to production-support teams and records an immutable timeline for Create, OPEN/TIA, Update, Transfer, Close, and Reopen actions.
- Preserves full ticket history for the team while restricting AI knowledge to the initial incident description and final closing comments.
- Uses local Retrieval-Augmented Generation (RAG) with Ollama embeddings to find comparable closed incidents from their symptoms, causes, resolutions, and log evidence.
- Applies semantic retrieval guardrails for filesystem, inbound-file, transfer, MQ, database, deployment, and TLS incidents, preventing unrelated suggestions.
- Presents a clear support flow: immediate checks, closest historical evidence, and separately labelled alternative patterns.
- Supports four teams, an ADMIN workspace, application routing, priorities, active/closed queues, and incident search.

## Run locally

Install dependencies once:

```bash
npm install
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
```

Start the backend in one terminal:

```bash
cd backend
./.venv/bin/uvicorn app:app --reload --port 8000
```

Start the frontend in another terminal:

```bash
npm run dev
```

Open `http://127.0.0.1:5173`.

## Local AI and RAG

SupportAI keeps incident content on the local machine. Install and run [Ollama](https://ollama.com/) with the embedding model used by the app:

```bash
ollama pull nomic-embed-text
ollama serve
```

The application caches closed-incident embeddings locally. If no credible historical evidence is found, it labels the result as a general suggestion instead of presenting an unsupported match.

## Test

```bash
PYTHONPATH=backend backend/.venv/bin/python backend/test_api.py
```
