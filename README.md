# SupportAI

SupportAI is a local AI-powered incident analysis project for application and production support teams. I built it to reduce manual incident search, avoid repeated guesswork, lower unnecessary storage and AI-context cost, and help engineers reach the right next action faster.

Instead of sending the full history of every old ticket to AI, SupportAI saves only the useful parts of a closed incident: the first issue description and the final closing comment. This makes the knowledge base smaller, cheaper to store and retrieve, and more focused than searching through every update, transfer comment, log dump, and team conversation.

## Why I built this

In production support, engineers can lose time searching old tickets, reading long comment histories, asking other teams for prior fixes, and trying actions that may not match the real issue. The same problem can also return with different wording. For example, one ticket may say **Application Down** while another says **URL not responding**.

SupportAI uses RAG to retrieve only useful closed-incident evidence and show what was found before, what resolved it, and which logs were important. This gives the engineer a faster starting point without claiming that an old cause is automatically the new cause.

## How SupportAI reduces time and cost

| Problem in normal incident support | What SupportAI does |
| --- | --- |
| Engineers manually search many old tickets | Retrieves the most relevant closed incidents automatically |
| Old tickets contain long updates, transfers, and discussion | Uses only the initial description and final closure as AI knowledge |
| Sending full ticket histories to an AI model increases context size and cost | Keeps retrieval compact by storing only decision-useful evidence |
| Different ticket wording hides similar past issues | Uses semantic RAG matching, not only exact titles |
| Previous fixes are hard to verify | Shows the historical cause, resolution, and log evidence with the incident number |

The goal is not to replace the support engineer. The goal is to reduce low-value searching and give the engineer better evidence before they decide what to do.

## How it works

```text
New incident
     ↓
Title + application + initial description
     ↓
Exact title search first
     ↓
Semantic RAG search if the title is different
     ↓
Relevant closed-incident evidence
     ↓
Start-here checks + previous cause + resolution + log evidence
```

SupportAI gives more importance to the incident title and initial alert when matching. The final closing comment is used as supporting evidence after a relevant incident is found.

## What AI can and cannot use

| Ticket information | Visible in the ticket | Used by RAG |
| --- | --- | --- |
| Initial incident description | Yes | Yes |
| OPEN/TIA, update, and transfer comments | Yes | No |
| Final closing comment | Yes | Yes |
| Cause, impact, actions, and logs written in the closing comment | Yes | Yes |

This means normal discussion can stay in the ticket, while RAG only learns from the original issue and final resolution. It reduces unnecessary data stored for AI retrieval and keeps the answer focused on evidence that helped close the incident.

## Main features

- Incident queues for VEXCAPUNIX, LEXIXUNIX, MARCAPUNIX, KINEPUNIX, and ADMIN.
- Create, OPEN/TIA, update, transfer, close, and reopen workflows with an immutable timeline.
- Active incidents, closed incidents, and a separate search view.
- RAG guidance that shows:
  - **Start here** checks for the current incident
  - The closest matching closed incident
  - Its confirmed cause, previous resolution, and relevant logs
  - Other possible patterns kept separate, so different causes are not mixed together
- Clickable incident references and in-app incident tabs, so engineers can inspect historical tickets without losing the incident they are working on.
- Local Ollama embeddings and local caching, so incident data stays on the machine.

## Demo examples

The project includes synthetic closed incidents and active test tickets for common production-support situations:

- Filesystem capacity and `/users` mount issues
- Inbound files, CFT/SFTP transfers, and delayed payloads
- MQ consumers, acknowledgements, retry queues, and channels
- Database locks and batch jobs
- Deployments and configuration problems
- TLS certificate, trust-store, hostname, and expiry failures
- Application availability alerts after restarts

Try opening **INC-0111** or **INC-0112**. Their titles are different from the closed ticket **INC-0109**, but SupportAI can still retrieve the previous application-availability investigation through semantic matching.

## Run locally

Install the frontend and backend dependencies once:

```bash
npm install
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
```

Start the backend in one terminal:

```bash
cd backend
./.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000
```

Start Ollama in a second terminal:

```bash
ollama pull nomic-embed-text
ollama serve
```

Start the frontend in a third terminal:

```bash
npm run dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173).

## Tech used

- React and Vite for the interface
- FastAPI and SQLite for the backend and local ticket storage
- Ollama with `nomic-embed-text` for local semantic embeddings
- Retrieval-Augmented Generation (RAG) for incident matching and grounded evidence

## Test

```bash
PYTHONPATH=backend backend/.venv/bin/python backend/test_api.py
```

All example incidents in this project are synthetic and created only for testing and demonstration.
