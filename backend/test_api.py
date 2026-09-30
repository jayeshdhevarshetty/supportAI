import os
from pathlib import Path

os.environ["INCIDENT_DATABASE"] = "/private/tmp/incident_desk_test.db"
Path(os.environ["INCIDENT_DATABASE"]).unlink(missing_ok=True)

from fastapi.testclient import TestClient
from app import app


with TestClient(app) as client:
    teams = client.get("/api/teams").json()
    applications = client.get("/api/applications").json()
    assert len(teams) == 5
    assert len(applications) == 24

    payload = {
        "title": "File delivery failed",
        "application_id": applications[0]["id"],
        "priority": "High",
        "initial_description": "Inbound file is missing.",
    }
    created = client.post("/api/incidents", json=payload)
    assert created.status_code == 201, created.text
    incident = created.json()
    team_id = incident["current_team_id"]
    admin_team_id = next(team["id"] for team in teams if team["name"] == "ADMIN")

    assert client.post(
        f"/api/incidents/{incident['id']}/actions",
        json={"action": "update", "team_id": team_id, "body": "This must not be accepted yet."},
    ).status_code == 400

    assert client.post(
        f"/api/incidents/{incident['id']}/actions",
        json={"action": "open", "team_id": team_id, "body": ""},
    ).status_code == 400

    assert client.post(
        f"/api/incidents/{incident['id']}/actions",
        json={"action": "open", "team_id": team_id, "body": "Taking into account."},
    ).status_code == 200
    assert client.post(
        f"/api/incidents/{incident['id']}/actions",
        json={"action": "update", "team_id": admin_team_id, "body": "ADMIN validated the incident scope."},
    ).status_code == 200

    handoff = client.post("/api/incidents", json={**payload, "title": "Database lock after batch start"}).json()
    assert client.post(
        f"/api/incidents/{handoff['id']}/actions",
        json={"action": "open", "team_id": handoff["current_team_id"], "body": "Taking into account."},
    ).status_code == 200
    destination_id = next(team["id"] for team in teams if team["id"] != handoff["current_team_id"] and team["name"] != "ADMIN")
    assert client.post(
        f"/api/incidents/{handoff['id']}/actions",
        json={"action": "transfer", "team_id": handoff["current_team_id"], "destination_team_id": destination_id, "body": "Transfer for database investigation."},
    ).status_code == 200
    transferred = client.get(f"/api/incidents/{handoff['id']}").json()
    assert transferred["status"] == "Transferred"
    assert client.post(
        f"/api/incidents/{handoff['id']}/actions",
        json={"action": "update", "team_id": destination_id, "body": "This must wait for TIA."},
    ).status_code == 400
    assert client.post(
        f"/api/incidents/{handoff['id']}/actions",
        json={"action": "open", "team_id": destination_id, "body": "Receiving team takes the incident into account."},
    ).status_code == 200
    assert client.post(
        f"/api/incidents/{incident['id']}/actions",
        json={
            "action": "close",
            "team_id": team_id,
            "body": "Cause: missing upstream file\nImpact: delayed processing\nActions: requested resend",
        },
    ).status_code == 200

    follow_up = client.post("/api/incidents", json=payload)
    assert follow_up.status_code == 201
    recommendation = client.get(f"/api/incidents/{follow_up.json()['id']}/recommendation").json()
    assert recommendation["mode"] == "historical"
    assert recommendation["level"] == "Same application"

    assert client.post(
        f"/api/incidents/{incident['id']}/actions",
        json={"action": "reopen", "team_id": team_id, "body": "Reopened because the upstream file remains unavailable."},
    ).status_code == 200
    detail = client.get(f"/api/incidents/{incident['id']}").json()
    assert detail["status"] == "Open"
    assert [entry["action"] for entry in detail["comments"]] == ["Created", "OPEN", "Update", "Closed", "Reopened"]

print("API workflow test passed")
