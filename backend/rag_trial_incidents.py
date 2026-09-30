"""Creates open incidents that pressure-test SupportAI against reworded closed evidence."""
from datetime import datetime, timezone

from app import db, initialize


TRIALS = [
    ("Apex", "Users99 filesystem capacity alert", "Monitoring shows /users99 at 95% utilization and scheduled output is beginning to retry."),
    ("Apex", "Temporary storage mount almost full", "Export processing cannot create /users56/recon_export.tmp because the mount has no available space."),
    ("Apex", "Inbound partner file not received", "The intake batch is waiting for partner_invoice_882.xml and the file is absent from the landing directory."),
    ("Volt", "Payload transfer completed but not processed", "CFT shows shipment_442.dat complete, but the application has not consumed it after the polling window."),
    ("Kinetic", "Consumer acknowledgement backlog", "Queue depth is rising and the Kinetic consumer group is no longer acknowledging messages."),
    ("Kinetic", "Retrying messages are increasing", "The retry queue is growing as the transformation worker rejects a new event payload format."),
    ("Vector", "Reconciliation waits on database transaction", "RECON_BATCH is waiting while database sessions show a blocking validation transaction."),
    ("Vector", "Settlement batch unable to start", "SETTLEMENT_LOAD remains queued behind a locked settlement database resource."),
    ("Matrix", "Release installed but configuration unchanged", "The new build is running but the approved payment routing setting is still disabled."),
    ("Matrix", "New endpoint not active after deployment", "The current service package is live, but outbound calls continue to use the legacy endpoint."),
    ("Glow", "TLS certificate validation failed", "The connector reports an untrusted issuer after the vendor certificate rotation."),
    ("Glow", "Partner HTTPS handshake error", "Outbound partner requests fail with a hostname verification failure during the TLS handshake."),
]


def main():
    initialize()
    created_at = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        created = []
        for app_name, title, description in TRIALS:
            exists = conn.execute(
                "SELECT id FROM incidents WHERE title = ? AND initial_description = ?", (title, description)
            ).fetchone()
            if exists:
                created.append(exists["id"])
                continue
            app = conn.execute("SELECT * FROM applications WHERE name = ?", (app_name,)).fetchone()
            cursor = conn.execute(
                """INSERT INTO incidents(title, title_normalized, application_id, current_team_id, priority,
                   initial_description, status, created_at)
                   VALUES(?,?,?,?,?,?, 'Open', ?)""",
                (title, title.casefold(), app["id"], app["primary_team_id"], "High", description, created_at),
            )
            incident_id = cursor.lastrowid
            conn.execute(
                "INSERT INTO incident_comments(incident_id, team_id, action, body, created_at) VALUES(?,NULL,'Created',?,?)",
                (incident_id, description, created_at),
            )
            created.append(incident_id)
        conn.commit()
    print("Created/located trial incidents:", ", ".join(map(str, created)))


if __name__ == "__main__":
    main()
