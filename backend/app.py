from __future__ import annotations

import json
import math
import threading
import os
import re
import hashlib
import sqlite3
import urllib.error
import urllib.request
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
DATABASE = Path(os.getenv("INCIDENT_DATABASE", str(BASE_DIR / "incident_desk.db")))
TEAMS = ["VEXCAPUNIX", "LEXIXUNIX", "MARCAPUNIX", "KINEPUNIX"]
ADMIN_TEAM = "ADMIN"
APPLICATIONS = [
    "Spark", "Insta", "Snap", "Volt", "Dash", "Appetite", "Zing", "Bolt",
    "Glow", "Pulse", "Vibe", "Apex", "Vector", "Matrix", "Optic", "Stratum",
    "Kinetic", "Flare", "Breaker", "Rumble", "Havoc", "Razor", "Grip", "Claw",
]

app = FastAPI(title="Incident Desk", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def db() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def rows(items):
    return [dict(item) for item in items]


def initialize() -> None:
    with closing(db()) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS teams (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS applications (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL UNIQUE,
              primary_team_id INTEGER NOT NULL REFERENCES teams(id)
            );
            CREATE TABLE IF NOT EXISTS incidents (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              title TEXT NOT NULL,
              title_normalized TEXT NOT NULL,
              application_id INTEGER NOT NULL REFERENCES applications(id),
              current_team_id INTEGER NOT NULL REFERENCES teams(id),
              priority TEXT NOT NULL CHECK(priority IN ('Low','Medium','High','Critical')),
              initial_description TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'Open',
              created_at TEXT NOT NULL,
              acknowledged_at TEXT,
              closed_at TEXT,
              closing_comments TEXT
            );
            CREATE TABLE IF NOT EXISTS incident_comments (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              incident_id INTEGER NOT NULL REFERENCES incidents(id),
              team_id INTEGER REFERENCES teams(id),
              action TEXT NOT NULL,
              body TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS incident_embeddings (
              incident_id INTEGER PRIMARY KEY REFERENCES incidents(id),
              content_hash TEXT NOT NULL,
              embedding_json TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            """
        )
        for column, definition in (
            ("ai_recommendation_json", "TEXT"),
            ("ai_recommendation_created_at", "TEXT"),
            ("ai_generation_started_at", "TEXT"),
        ):
            try:
                conn.execute(f"ALTER TABLE incidents ADD COLUMN {column} {definition}")
            except sqlite3.OperationalError:
                pass
        for team in TEAMS:
            conn.execute("INSERT OR IGNORE INTO teams(name) VALUES(?)", (team,))
        conn.execute("INSERT OR IGNORE INTO teams(name) VALUES(?)", (ADMIN_TEAM,))
        # A backend restart interrupts in-memory workers. Let unfinished tickets restart cleanly.
        conn.execute("UPDATE incidents SET ai_generation_started_at = NULL WHERE ai_recommendation_json IS NULL")
        team_ids = {row["name"]: row["id"] for row in conn.execute("SELECT id, name FROM teams")}
        for index, application in enumerate(APPLICATIONS):
            team = TEAMS[index % len(TEAMS)]
            conn.execute(
                "INSERT OR IGNORE INTO applications(name, primary_team_id) VALUES(?, ?)",
                (application, team_ids[team]),
            )
        conn.commit()


@app.on_event("startup")
def startup() -> None:
    initialize()


class IncidentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    application_id: int
    priority: Literal["Low", "Medium", "High", "Critical"]
    initial_description: str = Field(min_length=1, max_length=8000)


class IncidentAction(BaseModel):
    action: Literal["open", "update", "transfer", "close", "reopen"]
    team_id: int
    body: str = Field(default="", max_length=8000)
    destination_team_id: int | None = None


def get_incident(conn: sqlite3.Connection, incident_id: int) -> dict:
    record = conn.execute(
        """
        SELECT i.*, a.name AS application_name, pt.name AS primary_team_name, ct.name AS current_team_name
        FROM incidents i
        JOIN applications a ON a.id = i.application_id
        JOIN teams pt ON pt.id = a.primary_team_id
        JOIN teams ct ON ct.id = i.current_team_id
        WHERE i.id = ?
        """,
        (incident_id,),
    ).fetchone()
    if not record:
        raise HTTPException(404, "Incident not found")
    return dict(record)


@app.get("/api/teams")
def list_teams():
    with closing(db()) as conn:
        return rows(conn.execute("SELECT * FROM teams ORDER BY name"))


@app.get("/api/applications")
def list_applications():
    with closing(db()) as conn:
        return rows(
            conn.execute(
                """SELECT a.id, a.name, a.primary_team_id, t.name AS primary_team_name
                FROM applications a JOIN teams t ON t.id = a.primary_team_id ORDER BY a.name"""
            )
        )


@app.get("/api/incidents")
def list_incidents(team_id: int | None = None, status: str | None = None):
    query = """
      SELECT i.*, a.name AS application_name, pt.name AS primary_team_name, ct.name AS current_team_name
      FROM incidents i
      JOIN applications a ON a.id = i.application_id
      JOIN teams pt ON pt.id = a.primary_team_id
      JOIN teams ct ON ct.id = i.current_team_id WHERE 1=1
    """
    values = []
    if team_id:
        query += " AND i.current_team_id = ?"
        values.append(team_id)
    if status:
        query += " AND i.status = ?"
        values.append(status)
    query += " ORDER BY CASE i.status WHEN 'Closed' THEN 1 ELSE 0 END, i.created_at DESC"
    with closing(db()) as conn:
        return rows(conn.execute(query, values))


@app.post("/api/incidents", status_code=201)
def create_incident(payload: IncidentCreate):
    with closing(db()) as conn:
        application = conn.execute("SELECT * FROM applications WHERE id = ?", (payload.application_id,)).fetchone()
        if not application:
            raise HTTPException(400, "Select an existing application")
        created_at = now()
        title = payload.title.strip()
        cursor = conn.execute(
            """INSERT INTO incidents(title, title_normalized, application_id, current_team_id, priority,
                 initial_description, status, created_at)
               VALUES(?,?,?,?,?,?, 'Open', ?)""",
            (title, title.casefold(), application["id"], application["primary_team_id"], payload.priority,
             payload.initial_description.strip(), created_at),
        )
        incident_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO incident_comments(incident_id, team_id, action, body, created_at) VALUES(?, NULL, 'Created', ?, ?)",
            (incident_id, payload.initial_description.strip(), created_at),
        )
        conn.commit()
        conn.execute("UPDATE incidents SET ai_generation_started_at = ? WHERE id = ?", (now(), incident_id))
        conn.commit()
        threading.Thread(target=recommendation, args=(incident_id,), daemon=True).start()
        return get_incident(conn, incident_id)


@app.get("/api/incidents/{incident_id}")
def incident_detail(incident_id: int):
    with closing(db()) as conn:
        incident = get_incident(conn, incident_id)
        incident["comments"] = rows(
            conn.execute(
                """SELECT c.*, COALESCE(t.name, 'AUTO') AS team_name
                   FROM incident_comments c LEFT JOIN teams t ON t.id = c.team_id
                   WHERE c.incident_id = ? ORDER BY c.created_at ASC, c.id ASC""",
                (incident_id,),
            )
        )
        return incident


@app.post("/api/incidents/{incident_id}/actions")
def act_on_incident(incident_id: int, payload: IncidentAction):
    with closing(db()) as conn:
        incident = get_incident(conn, incident_id)
        team = conn.execute("SELECT * FROM teams WHERE id = ?", (payload.team_id,)).fetchone()
        if not team:
            raise HTTPException(400, "Choose a valid team")
        body = payload.body.strip()
        is_admin = team["name"] == ADMIN_TEAM
        if not is_admin and team["id"] != incident["current_team_id"]:
            raise HTTPException(403, "Switch to the incident's assigned team before posting an action")
        if not body:
            raise HTTPException(400, "A comment is required before this action can be saved")
        timestamp = now()

        if payload.action == "open":
            if is_admin:
                raise HTTPException(403, "ADMIN cannot take an incident into account")
            if incident["status"] == "Closed":
                raise HTTPException(400, "Reopen the incident before opening it")
            if incident["status"] == "Acknowledged":
                raise HTTPException(400, "This incident has already been taken into account")
            conn.execute("UPDATE incidents SET status = 'Acknowledged', acknowledged_at = COALESCE(acknowledged_at, ?) WHERE id = ?", (timestamp, incident_id))
            action_label = "OPEN"
        elif payload.action == "update":
            if incident["status"] != "Acknowledged":
                raise HTTPException(400, "Take the incident into account before adding updates")
            action_label = "Update"
        elif payload.action == "transfer":
            if incident["status"] != "Acknowledged":
                raise HTTPException(400, "Take the incident into account before transferring it")
            if not payload.destination_team_id:
                raise HTTPException(400, "Choose the receiving team")
            destination = conn.execute("SELECT * FROM teams WHERE id = ?", (payload.destination_team_id,)).fetchone()
            if not destination:
                raise HTTPException(400, "Choose a valid receiving team")
            if destination["id"] == incident["current_team_id"]:
                raise HTTPException(400, "Choose a different team")
            action_label = "Transferred"
            conn.execute("UPDATE incidents SET current_team_id = ?, status = 'Transferred' WHERE id = ?", (destination["id"], incident_id))
        elif payload.action == "close":
            if incident["status"] != "Acknowledged":
                raise HTTPException(400, "Take the incident into account before closing it")
            action_label = "Closed"
            conn.execute("UPDATE incidents SET status = 'Closed', closed_at = ?, closing_comments = ? WHERE id = ?", (timestamp, body, incident_id))
        else:  # reopen
            if incident["status"] != "Closed":
                raise HTTPException(400, "Only closed incidents can be reopened")
            action_label = "Reopened"
            conn.execute("UPDATE incidents SET status = 'Open', closed_at = NULL WHERE id = ?", (incident_id,))

        conn.execute(
            "INSERT INTO incident_comments(incident_id, team_id, action, body, created_at) VALUES(?,?,?,?,?)",
            (incident_id, team["id"], action_label, body, timestamp),
        )
        conn.commit()
        return {"ok": True}


def ask_ollama(prompt: str) -> str | None:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", "llama3.2")
    request = urllib.request.Request(
        f"{base_url}/api/generate",
        data=json.dumps({"model": model, "prompt": prompt, "stream": False, "options": {"temperature": 0.2}}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.loads(response.read().decode()).get("response")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


def embed_with_ollama(texts: list[str]) -> list[list[float]] | None:
    """Returns local embeddings only; no incident content leaves this machine."""
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    request = urllib.request.Request(
        f"{base_url}/api/embed",
        data=json.dumps({"model": model, "input": texts}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode()).get("embeddings")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


def document_text(item: dict) -> str:
    return f"search_document: {item['title']}\n{item['initial_description']}\n{item['closing_comments']}"


def cached_document_embeddings(conn: sqlite3.Connection, candidates: list[dict]) -> list[list[float]] | None:
    """Embed each closed incident once locally, then reuse it for future new tickets."""
    if not candidates:
        return []
    ids = [item["id"] for item in candidates]
    placeholders = ",".join("?" for _ in ids)
    saved = {
        row["incident_id"]: (row["content_hash"], json.loads(row["embedding_json"]))
        for row in conn.execute(f"SELECT incident_id, content_hash, embedding_json FROM incident_embeddings WHERE incident_id IN ({placeholders})", ids)
    }
    hashes = {item["id"]: hashlib.sha256(document_text(item).encode()).hexdigest() for item in candidates}
    missing = [item for item in candidates if item["id"] not in saved or saved[item["id"]][0] != hashes[item["id"]]]
    if missing:
        new_vectors = embed_with_ollama([document_text(item) for item in missing])
        if not new_vectors or len(new_vectors) != len(missing):
            return None
        for item, vector in zip(missing, new_vectors):
            conn.execute(
                "INSERT OR REPLACE INTO incident_embeddings(incident_id, content_hash, embedding_json, updated_at) VALUES(?,?,?,?)",
                (item["id"], hashes[item["id"]], json.dumps(vector), now()),
            )
            saved[item["id"]] = (hashes[item["id"]], vector)
        conn.commit()
    return [saved[item["id"]][1] for item in candidates]


def cosine(left: list[float], right: list[float]) -> float:
    denominator = math.sqrt(sum(x * x for x in left)) * math.sqrt(sum(x * x for x in right))
    return sum(x * y for x, y in zip(left, right)) / denominator if denominator else 0.0


def support_signals(text: str) -> set[str]:
    """Conservative operational domains used as a guardrail for semantic retrieval."""
    value = text.casefold()
    groups = {
        "filesystem": ("/users", "filesystem", "file system", "mount", "disk", "capacity", "usage", "no space", "space left"),
        "inbound-file": ("inbound", "partner", ".xml", "file received", "file delivery", "payload", "file missing"),
        "transfer": ("secure transfer", "transfer channel", "cft", "sftp", "consumer polling"),
        "mq": ("mq", "queue", "consumer", "acknowledg", "message backlog"),
        "database": ("database", "database lock", "transaction", "blocking session", "recon_batch", "table lock"),
        "deployment": ("deployment", "release", "configuration", "endpoint", "package version"),
        "tls-trust": ("untrusted issuer", "trust store", "truststore", "pkix", "certification path", "intermediate certificate"),
        "tls-hostname": ("hostname verification", "common name", "endpoint hostname"),
        "tls-expiry": ("certificate expired", "expiry threshold", "expired date"),
    }
    found = {name for name, phrases in groups.items() if any(phrase in value for phrase in phrases)}
    if any(name.startswith("tls-") for name in found):
        return found
    if any(phrase in value for phrase in ("tls", "https", "certificate", "handshake")):
        found.add("tls-general")
    return found


def closing_sections(closing_comments: str) -> dict[str, str]:
    """Expose evidence clearly without asking the model to invent a summary."""
    def section(name: str) -> str:
        pattern = rf"(?:^|\n){name}\s*:\s*(.*?)(?=\n(?:Cause|Impact|Actions|Relevant log evidence)\s*:|\Z)"
        found = re.search(pattern, closing_comments, flags=re.IGNORECASE | re.DOTALL)
        return found.group(1).strip() if found else ""

    return {
        "cause": section("Cause"),
        "impact": section("Impact"),
        "actions": section("Actions"),
        "log_evidence": section("Relevant log evidence"),
    }


def enrich_evidence(matches: list[dict]) -> list[dict]:
    for match in matches:
        match.update(closing_sections(match.get("closing_comments") or ""))
    return matches


def diverse_matches(candidates: list[dict], query_embedding: list[float], document_embeddings: list[list[float]], query_text: str, limit: int = 3) -> list[dict]:
    """Use semantic similarity, but never let diversity introduce a different incident domain."""
    query_domains = support_signals(query_text)
    scored = [{**candidate, "_embedding": embedding, "similarity": cosine(query_embedding, embedding)} for candidate, embedding in zip(candidates, document_embeddings)]
    if query_domains:
        scored = [item for item in scored if query_domains & support_signals(f"{item['title']}\n{item['initial_description']}\n{item['closing_comments']}")]
    if not scored:
        return []
    # Keep only near the best result. A vague third 'match' is worse than no match.
    best_similarity = max(item["similarity"] for item in scored)
    cutoff = max(0.65, best_similarity - 0.12)
    scored = [item for item in scored if item["similarity"] >= cutoff]
    selected = []
    while scored and len(selected) < limit:
        def value(item):
            repetition = max((cosine(item["_embedding"], chosen["_embedding"]) for chosen in selected), default=0)
            return 0.78 * item["similarity"] - 0.22 * repetition
        chosen = max(scored, key=value)
        scored.remove(chosen)
        selected.append(chosen)
    for item in selected:
        item.pop("_embedding", None)
    return selected


def grounded_retrieval_summary(matches: list[dict]) -> str:
    closest = matches[0]
    prior_cause = closest.get("cause") or "the saved closing evidence"
    return (
        f"Closest comparable incident: INC-{closest['id']:04d} ({closest['application_name']}). "
        f"Its confirmed cause was: {prior_cause}"
    )


def suggested_checks(current: dict, matches: list[dict]) -> list[str]:
    """Clear, conservative next checks derived from the current symptom and saved evidence."""
    text = f"{current['title']}\n{current['initial_description']}"
    domains = support_signals(text)
    mount = re.search(r"/[A-Za-z0-9_./-]+", text)
    filename = re.search(r"\b[A-Za-z0-9_-]+\.(?:xml|csv|dat|txt)\b", text, flags=re.IGNORECASE)
    if "filesystem" in domains:
        location = mount.group(0) if mount else "the affected application mount"
        return [
            f"Confirm available space and recent growth on {location}.",
            "Check whether the cleanup, archive, or export process failed before removing any files.",
            "Use the approved cleanup process only; then retry the affected job and verify free space.",
        ]
    if "inbound-file" in domains:
        item = filename.group(0) if filename else "the expected inbound file"
        return [
            f"Confirm whether {item} was generated upstream and reached the landing directory.",
            "Check the receiving batch or transfer status before restarting the flow.",
            "Validate the delivered file before rerunning the dependent intake job.",
        ]
    if "transfer" in domains:
        return [
            "Confirm the transfer status and whether the delivered payload remains in the landing area.",
            "Check the consumer or validation service state and its most recent error.",
            "After the approved fix, verify that the payload is consumed during the next poll cycle.",
        ]
    if "mq" in domains:
        return [
            "Check queue depth, consumer connection state, and acknowledgement age.",
            "Identify whether one retrying or malformed message is blocking the consumer.",
            "Apply the approved consumer or mapping fix, then verify acknowledgement flow before replaying messages.",
        ]
    if "database" in domains:
        return [
            "Identify the blocking session, lock owner, and affected batch dependency.",
            "Coordinate any session or lock action through the approved database procedure.",
            "Rerun the batch only after the lock is confirmed released and monitor completion.",
        ]
    if "deployment" in domains:
        return [
            "Verify the live runtime value, not just the deployed package version.",
            "Check the environment override, configuration artifact, and refresh task for the release.",
            "Apply the approved configuration correction and complete a targeted smoke test.",
        ]
    if "tls-trust" in domains:
        return [
            "Check the connector trust store for the expected root or intermediate certificate chain.",
            "Compare the validation error with the current partner certificate chain before importing anything.",
            "Use the approved certificate update, restart the connector, and validate one handshake.",
        ]
    if "tls-hostname" in domains:
        return [
            "Compare the configured endpoint hostname with the certificate common name or SAN entries.",
            "Confirm the approved partner endpoint before changing the connector configuration.",
            "After correction, validate one TLS handshake and a controlled request.",
        ]
    if "tls-expiry" in domains:
        return [
            "Confirm the client or server certificate expiry and the certificate currently in use.",
            "Install only the approved renewed certificate and confirm the connector references it.",
            "Restart the affected connector or poller and validate an authenticated request.",
        ]
    return [
        "Review the initial symptom and compare it with the closest closed incident below.",
        "Validate the matching log evidence before applying any prior resolution.",
    ]


@app.get("/api/incidents/{incident_id}/recommendation")
def recommendation(incident_id: int, wait: bool = True):
    with closing(db()) as conn:
        current = get_incident(conn, incident_id)
        if current.get("ai_recommendation_json"):
            try:
                return json.loads(current["ai_recommendation_json"])
            except json.JSONDecodeError:
                pass
        if not wait:
            if not current.get("ai_generation_started_at"):
                conn.execute("UPDATE incidents SET ai_generation_started_at = ? WHERE id = ?", (now(), incident_id))
                conn.commit()
                threading.Thread(target=recommendation, args=(incident_id,), daemon=True).start()
            return {"mode": "pending", "level": None, "matches": [], "summary": "SupportAI is preparing the saved guidance for this new incident."}
        matches = rows(conn.execute(
            """SELECT i.id, i.title, a.name AS application_name, i.initial_description, i.closing_comments
               FROM incidents i JOIN applications a ON a.id = i.application_id
               WHERE i.status = 'Closed' AND i.id != ? AND i.title_normalized = ? AND i.application_id = ?
               ORDER BY i.closed_at DESC LIMIT 5""",
            (incident_id, current["title_normalized"], current["application_id"]),
        ))
        level = "Same application"
        if not matches:
            matches = rows(conn.execute(
                """SELECT i.id, i.title, a.name AS application_name, i.initial_description, i.closing_comments
                   FROM incidents i JOIN applications a ON a.id = i.application_id
                   WHERE i.status = 'Closed' AND i.id != ? AND i.title_normalized = ?
                   ORDER BY i.closed_at DESC LIMIT 5""",
                (incident_id, current["title_normalized"]),
            ))
            level = "All applications"
        retrieval_type = "Exact title"
        if not matches:
            candidates = rows(conn.execute(
                """SELECT i.id, i.title, a.name AS application_name, i.application_id, i.initial_description, i.closing_comments
                   FROM incidents i JOIN applications a ON a.id = i.application_id
                   WHERE i.status = 'Closed' AND i.id != ? ORDER BY i.closed_at DESC LIMIT 120""", (incident_id,)
            ))
            query_text = f"search_query: {current['title']}\n{current['initial_description']}"
            query_vectors = embed_with_ollama([query_text]) if candidates else None
            document_vectors = cached_document_embeddings(conn, candidates) if candidates else None
            if query_vectors and document_vectors and len(document_vectors) == len(candidates):
                query_vector = query_vectors[0]
                same_app = [item for item in candidates if item['application_id'] == current['application_id']]
                if same_app:
                    indices = [index for index, item in enumerate(candidates) if item['application_id'] == current['application_id']]
                    matches = diverse_matches(same_app, query_vector, [document_vectors[index] for index in indices], query_text)
                    level = "Semantic match · Same application"
                else:
                    matches = diverse_matches(candidates, query_vector, document_vectors, query_text)
                    level = "Semantic match · All applications"
                retrieval_type = "Semantic similarity"
        if matches:
            matches = enrich_evidence(matches)
            context = "\n\n".join(
                f"Incident #{m['id']} ({m['application_name']})\nInitial description: {m['initial_description']}\nClosing comments: {m['closing_comments']}"
                for m in matches
            )
            prompt = f"""You are an incident-support assistant. Use only the historical records below. Do not invent facts. Provide a concise suggested investigation plan and state that the engineer must validate it.\n\nNew incident title: {current['title']}\nNew incident initial description: {current['initial_description']}\n\nHistorical records:\n{context}"""
            generated = ask_ollama(prompt) if os.getenv("SUPPORTAI_ENABLE_LLM", "false").lower() == "true" else None
            summary = generated or grounded_retrieval_summary(matches)
            result = {"mode": "historical", "level": level, "retrieval_type": retrieval_type, "matches": matches, "summary": summary, "suggested_checks": suggested_checks(current, matches)}
        else:
            result = {
            "mode": "general",
            "level": None,
            "matches": [],
            "summary": "No closed incident with this exact title was found. Start with the initial description, confirm the application impact, check the relevant logs and dependencies, and document each validated finding in the incident comments.",
            }
        conn.execute("UPDATE incidents SET ai_recommendation_json = ?, ai_recommendation_created_at = ? WHERE id = ?", (json.dumps(result), now(), incident_id))
        conn.commit()
        return result
