"""Subida por partes del Hub: reanudable, validada y equivalente a una subida normal."""

import io
import json
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.routers import hub as routes
from app.services import agent_hub as hub
try:  # discover -s tests (como en CI) o python -m unittest tests.test_hub_uploads
    from test_hub_routes import Bucket, Collection, Db
except ImportError:
    from tests.test_hub_routes import Bucket, Collection, Db


class Parts(Collection):
    async def delete_many(self, query):
        self.docs = [d for d in self.docs if not all(d.get(k) == v for k, v in query.items())]

    async def delete_one(self, query):
        await self.delete_many(query)


class PartsDb(Db):
    def __missing__(self, name):
        self[name] = Parts()
        return self[name]


def request(username, body=b""):
    return SimpleNamespace(body=AsyncMock(return_value=body), state=SimpleNamespace(
        principal=SimpleNamespace(username=username, superadmin=False, token_name=None)))


def phases_zip():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("fase 1/portada.png", b"\x89PNG" + bytes(3000))
        archive.writestr("fase 5/kaanbal.hub.json", json.dumps({"version": 1, "tasks": []}))
    return buffer.getvalue()


class ChunkMathTests(unittest.TestCase):
    def test_parts_cover_the_file_exactly(self):
        size = hub.CHUNK_BYTES * 2 + 5
        self.assertEqual(hub.chunk_count(size), 3)
        self.assertEqual([hub.chunk_length(size, i) for i in range(3)], [hub.CHUNK_BYTES, hub.CHUNK_BYTES, 5])
        self.assertEqual(hub.chunk_count(1), 1)


class ChunkedUploadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = PartsDb()
        self.patches = [patch.object(routes, "get_db", return_value=self.db),
                        patch.object(routes, "_bucket", return_value=Bucket(self.db["hub_files.files"])),
                        patch.object(routes.activity_log, "log", AsyncMock()),
                        patch.object(hub, "CHUNK_BYTES", 1000)]
        for item in self.patches:
            item.start()

    async def asyncTearDown(self):
        for item in self.patches:
            item.stop()

    async def test_a_zip_sent_in_parts_out_of_order_is_unpacked_like_a_normal_upload(self):
        data = phases_zip()
        started = await routes.start_upload("app-x", routes.UploadStart(name="fases.zip", size=len(data)), request("ana"))
        upload, chunks = started["upload_id"], started["chunks"]
        self.assertGreater(chunks, 2)
        order = list(range(chunks))[::-1]
        for index in order[:-1]:
            await routes.upload_chunk(upload, index, request("ana", data[index * 1000:(index + 1) * 1000]))

        # Falta una parte: se dice cuál, y el estado sirve para reanudar.
        with self.assertRaises(HTTPException) as caught:
            await routes.complete_upload(upload, request("ana"))
        self.assertEqual(caught.exception.detail["missing"], [0])
        self.assertEqual((await routes.upload_status(upload, request("ana")))["received"], list(range(1, chunks)))

        await routes.upload_chunk(upload, 0, request("ana", data[:1000]))
        result = await routes.complete_upload(upload, request("ana"))
        self.assertEqual(result["stored"], 2)
        self.assertEqual(result["plan_found"], "fuente/fase 5/kaanbal.hub.json")
        self.assertEqual(self.db["hub_upload_parts"].docs, [])
        self.assertEqual(self.db["hub_uploads"].docs, [])

    async def test_a_part_of_the_wrong_size_or_index_is_rejected(self):
        started = await routes.start_upload("app-x", routes.UploadStart(name="a.bin", size=2500), request("ana"))
        with self.assertRaises(HTTPException):
            await routes.upload_chunk(started["upload_id"], 2, request("ana", b"x" * 1000))
        with self.assertRaises(HTTPException):
            await routes.upload_chunk(started["upload_id"], 3, request("ana", b"x" * 500))
        await routes.upload_chunk(started["upload_id"], 2, request("ana", b"x" * 500))

    async def test_an_upload_belongs_to_whoever_started_it(self):
        started = await routes.start_upload("app-x", routes.UploadStart(name="a.bin", size=10), request("ana"))
        with self.assertRaises(HTTPException) as caught:
            await routes.upload_chunk(started["upload_id"], 0, request("beto", b"x" * 10))
        self.assertEqual(caught.exception.status_code, 403)

    async def test_destination_cannot_escape_the_project(self):
        with self.assertRaises(HTTPException):
            await routes.start_upload("app-x", routes.UploadStart(name="a.zip", size=10, dest="../fuera"), request("ana"))


if __name__ == "__main__":
    unittest.main()
