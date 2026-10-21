import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from app.routers import groups


class GroupRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_unknown_or_suspended_owner_without_writing(self):
        db = SimpleNamespace(users=SimpleNamespace(find_one=AsyncMock(return_value=None)),
                             app_groups=SimpleNamespace(update_one=AsyncMock()))
        with patch.object(groups, "get_db", return_value=db):
            with self.assertRaises(HTTPException) as caught:
                await groups.update_group("demo", groups.GroupUpdate(name="Demo", owner="inactive"), SimpleNamespace(username="owner"))
        self.assertEqual(caught.exception.status_code, 422)
        db.app_groups.update_one.assert_not_awaited()

    async def test_stores_only_group_metadata_and_audits_the_actor(self):
        db = SimpleNamespace(users=SimpleNamespace(find_one=AsyncMock(return_value={"_id": "user"})),
                             app_groups=SimpleNamespace(update_one=AsyncMock()))
        log = AsyncMock()
        with patch.object(groups, "get_db", return_value=db), patch.object(groups.activity_log, "log", log):
            result = await groups.update_group("demo", groups.GroupUpdate(name=" Demo ", owner="developer", stage="reference"), SimpleNamespace(username="owner"))
        self.assertEqual(result["name"], "Demo")
        self.assertEqual(result["owner"], "developer")
        self.assertEqual(db.app_groups.update_one.call_args.args[0], {"_id": "demo"})
        self.assertEqual(log.call_args.kwargs["actor"], "owner")

    async def test_group_identifier_cannot_be_a_mongo_expression(self):
        with self.assertRaises(HTTPException):
            await groups.update_group("$where", groups.GroupUpdate(name="Demo"), SimpleNamespace(username="owner"))
