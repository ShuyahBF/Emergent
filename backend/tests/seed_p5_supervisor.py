"""Seed script (fork P5) — creates a stable Superviseur + 2 Médecins across two
clients so the frontend walk-in dropdown can be tested manually / via Playwright.

Run: python /app/backend/tests/seed_p5_supervisor.py
"""
import os
import sys

import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
API = f"{BASE_URL.rstrip('/')}/api"
ADMIN_EMAIL = "admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"
TAG = "p5fe"


def login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    b = r.json()
    v = requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": b["session_token"], "code": b["dev_otp"]},
        timeout=15,
    )
    v.raise_for_status()
    return v.json()["access_token"]


def main():
    hdr = {"Authorization": f"Bearer {login(ADMIN_EMAIL, ADMIN_PASSWORD)}"}

    def create_client(suffix):
        email = f"client-{suffix}-{TAG}@sawali-test.com"
        r = requests.post(
            f"{API}/admin/clients",
            headers=hdr,
            json={
                "email": email,
                "password": "Client@2026",
                "full_name": f"Client {suffix} {TAG}",
                "role": "admin",
                "company": f"{suffix}-{TAG}",
            },
            timeout=15,
        )
        if r.status_code >= 400:
            print(f"client {suffix} create -> {r.status_code} {r.text[:200]}")
            # try lookup existing
            lst = requests.get(f"{API}/admin/clients", headers=hdr, timeout=15).json()
            items = lst if isinstance(lst, list) else lst.get("items", lst.get("clients", []))
            for c in items:
                if c.get("email") == email:
                    return c["id"]
            sys.exit(1)
        return r.json()["id"]

    def create_tracked(email, role, client_id, password):
        r = requests.post(
            f"{API}/admin/tracked-users",
            headers=hdr,
            json={"email": email, "name": email.split("@")[0], "role": role, "client_id": client_id},
            timeout=15,
        )
        if r.status_code >= 400:
            print(f"tracked {email} create -> {r.status_code} {r.text[:200]}")
            return None
        tu_id = r.json()["id"]
        sp = requests.post(
            f"{API}/admin/tracked-users/{tu_id}/set-password",
            headers=hdr,
            json={"password": password},
            timeout=15,
        )
        sp.raise_for_status()
        return sp.json()["user_id"]

    cli_a = create_client("SUPA")
    cli_b = create_client("SUPB")
    med_a = create_tracked(f"med-a-{TAG}@sawali-test.com", "Médecin", cli_a, "Med@2026")
    med_b = create_tracked(f"med-b-{TAG}@sawali-test.com", "Médecin", cli_b, "Med@2026")
    sup = create_tracked(f"sup-{TAG}@sawali-test.com", "Superviseur", cli_a, "Sup@2026")
    print("cli_a", cli_a, "cli_b", cli_b)
    print("med_a", med_a, "med_b", med_b, "sup", sup)
    print(f"SUPERVISEUR LOGIN: sup-{TAG}@sawali-test.com / Sup@2026")

    tok = login(f"sup-{TAG}@sawali-test.com", "Sup@2026")
    r = requests.get(f"{API}/me/planning/doctors", headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    print("doctors status", r.status_code)
    docs = r.json().get("doctors", [])
    print("doctors", [(d["id"], d.get("full_name")) for d in docs])
    print("med_a visible:", med_a in [d["id"] for d in docs])
    print("med_b leaked:", med_b in [d["id"] for d in docs])


if __name__ == "__main__":
    main()
