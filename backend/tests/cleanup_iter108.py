"""Cleanup helper for Iter108 test artifacts."""
import asyncio
import os

from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

env = dotenv_values("/app/backend/.env")
MONGO_URL = os.environ.get("MONGO_URL") or env.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME") or env.get("DB_NAME")


async def main():
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    emails = [
        "test_s158_billing@sawali-test.com",
        "test_s159_suspend@sawali-test.com",
        "test_s159_gate@sawali-test.com",
    ]
    users = [u async for u in db.users.find({"email": {"$in": emails}}, {"_id": 0, "id": 1})]
    ids = [u["id"] for u in users]
    print("users:", await db.users.delete_many({"email": {"$in": emails}}))
    if ids:
        print("billing_reminders:", await db.billing_reminders.delete_many({"tenant_id": {"$in": ids}}))
        print("overdue_alerts:", await db.contract_overdue_alerts.delete_many({"tenant_id": {"$in": ids}}))
        print("payments:", await db.tenant_payments.delete_many({"tenant_id": {"$in": ids}}))
    print("appointments:", await db.appointments.delete_many({"subject": {"$regex": "^TEST_ITER107"}}))
    client.close()


asyncio.run(main())
