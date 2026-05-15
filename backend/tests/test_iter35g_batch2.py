"""Iter35g — Batch 2 tests :
- Bulk transfer of tracked users (#3)
- Personal Notes & Tasks via /me/notes/{notes,tasks} (#6 — transcription
  is exercised end-to-end via Whisper in the existing /transcribe endpoint
  which is the same code path used by reports/suivis).
- /me/notes-summary now reports counts for notes + tasks → Dashboard tiles.
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://sawali-portal.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"


def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    if not data.get("needs_otp"):
        return data.get("access_token")
    r2 = requests.post(f"{API}/auth/verify-otp", json={"session_token": data["session_token"], "code": data.get("dev_otp")}, timeout=30)
    assert r2.status_code == 200, r2.text
    return r2.json().get("access_token")


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login(ADMIN_EMAIL, ADMIN_PASSWORD)}"}


# ============================================================
# #3 — Bulk transfer of tracked users
# ============================================================
class TestBulkTransferTrackedUsers:
    def test_full_transfer_roundtrip(self, admin_h):
        s = uuid.uuid4().hex[:8]
        c1 = requests.post(
            f"{API}/admin/clients", headers=admin_h, timeout=20,
            json={"full_name": f"C1 {s}", "email": f"c1_{s}@iter35g.example.com", "password": "Pass1234!aa", "company": f"Co1 {s}", "role": "client"},
        )
        c2 = requests.post(
            f"{API}/admin/clients", headers=admin_h, timeout=20,
            json={"full_name": f"C2 {s}", "email": f"c2_{s}@iter35g.example.com", "password": "Pass1234!aa", "company": f"Co2 {s}", "role": "client"},
        )
        assert c1.status_code in (200, 201) and c2.status_code in (200, 201), f"{c1.status_code}/{c2.status_code} {c1.text} {c2.text}"
        cid1, cid2 = c1.json()["id"], c2.json()["id"]
        try:
            # Create 3 tracked users on cid1
            tu_ids = []
            for i in range(3):
                tr = requests.post(
                    f"{API}/admin/tracked-users", headers=admin_h, timeout=20,
                    json={
                        "client_id": cid1,
                        "name": f"TU {s} #{i}",
                        "email": f"tu_{s}_{i}@iter35g.example.com",
                        "role": "Consultation",
                    },
                )
                assert tr.status_code in (200, 201), tr.text
                tu_ids.append(tr.json()["id"])

            # Bulk transfer to cid2
            br = requests.post(
                f"{API}/admin/tracked-users/bulk-transfer",
                headers=admin_h,
                json={"tracked_user_ids": tu_ids, "target_client_id": cid2},
                timeout=30,
            )
            assert br.status_code == 200, br.text
            body = br.json()
            assert body["ok"] is True
            assert body["moved_count"] == 3
            assert body["skipped_count"] == 0
            assert body["target"]["id"] == cid2

            # Verify all 3 now belong to cid2
            after = requests.get(f"{API}/admin/tracked-users", headers=admin_h, timeout=15).json()
            after_ids = [x for x in after if x["id"] in tu_ids]
            assert len(after_ids) == 3
            for x in after_ids:
                assert x["client_id"] == cid2, f"tu {x['id']} still on {x['client_id']}"

            # Re-transferring to the same client should report all as skipped
            br2 = requests.post(
                f"{API}/admin/tracked-users/bulk-transfer",
                headers=admin_h,
                json={"tracked_user_ids": tu_ids, "target_client_id": cid2},
                timeout=20,
            )
            assert br2.status_code == 200, br2.text
            b2 = br2.json()
            assert b2["moved_count"] == 0
            assert b2["skipped_count"] == 3
            for s_row in b2["skipped"]:
                assert "déjà" in s_row["reason"].lower()
        finally:
            requests.delete(f"{API}/admin/clients/{cid1}", headers=admin_h, timeout=10)
            requests.delete(f"{API}/admin/clients/{cid2}", headers=admin_h, timeout=10)

    def test_unknown_target_client_returns_404(self, admin_h):
        r = requests.post(
            f"{API}/admin/tracked-users/bulk-transfer",
            headers=admin_h,
            json={"tracked_user_ids": [f"bogus_{uuid.uuid4().hex}"], "target_client_id": "ghost-client"},
            timeout=15,
        )
        assert r.status_code == 404

    def test_empty_selection_returns_400(self, admin_h):
        r = requests.post(
            f"{API}/admin/tracked-users/bulk-transfer",
            headers=admin_h,
            json={"tracked_user_ids": [], "target_client_id": "anything"},
            timeout=15,
        )
        assert r.status_code == 400

    def test_endpoint_requires_admin(self):
        r = requests.post(
            f"{API}/admin/tracked-users/bulk-transfer",
            json={"tracked_user_ids": ["x"], "target_client_id": "y"},
            timeout=10,
        )
        assert r.status_code in (401, 403)


# ============================================================
# #6 — Personal Notes & Tasks via /me/notes/{notes,tasks}
# ============================================================
class TestPersonalNotesAndTasks:
    def test_notes_summary_includes_new_kinds(self, admin_h):
        r = requests.get(f"{API}/me/notes-summary", headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        for k in ("reports", "suivis", "notes", "tasks"):
            assert k in body, f"missing {k} in summary"
            assert "count" in body[k] and "last_updated" in body[k]

    def test_can_create_personal_note(self, admin_h):
        r = requests.post(
            f"{API}/me/notes/notes",
            headers=admin_h,
            json={"title": f"Note iter35g {uuid.uuid4().hex[:6]}", "content_html": "<p>test</p>"},
            timeout=15,
        )
        assert r.status_code in (200, 201), r.text
        body = r.json()
        assert body.get("numero", "").startswith("NTE"), f"expected NTE prefix, got {body.get('numero')!r}"

    def test_can_create_personal_task(self, admin_h):
        r = requests.post(
            f"{API}/me/notes/tasks",
            headers=admin_h,
            json={"title": f"Tâche iter35g {uuid.uuid4().hex[:6]}", "content_html": "<p>todo</p>"},
            timeout=15,
        )
        assert r.status_code in (200, 201), r.text
        body = r.json()
        assert body.get("numero", "").startswith("TSK"), f"expected TSK prefix, got {body.get('numero')!r}"

    def test_voice_note_url_persists(self, admin_h):
        """Verify the voice-note URL and transcript fields round-trip through
        /me/notes/notes — the same mechanism already validated on reports/suivis."""
        r = requests.post(
            f"{API}/me/notes/notes",
            headers=admin_h,
            json={
                "title": f"Note vocale {uuid.uuid4().hex[:6]}",
                "content_html": "<p>avec voix</p>",
                "voice_note_url": "https://example.com/audio.webm",
                "voice_note_transcript": "Ceci est ma transcription automatique.",
            },
            timeout=15,
        )
        assert r.status_code in (200, 201), r.text
        body = r.json()
        assert body.get("voice_note_url") == "https://example.com/audio.webm"
        assert "transcription" in (body.get("voice_note_transcript") or "")

    def test_unknown_kind_still_returns_404(self, admin_h):
        r = requests.get(f"{API}/me/notes/bogus_kind_iter35g", headers=admin_h, timeout=10)
        assert r.status_code == 404

    def test_listing_reports_unchanged(self, admin_h):
        """Regression — the existing 'reports' endpoint still works."""
        r = requests.get(f"{API}/me/notes/reports", headers=admin_h, timeout=10)
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)
