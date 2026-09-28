import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from tessera_studio.server import create_server
from tessera_studio.store import NotFound, Store

PID = "a" * 64
OTHER = "b" * 64


def write(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def build_store(root: Path):
    project = root / PID
    write(project / "catalog.json", {
        "schema": 1, "project": "Demo", "scope": ["src/a.ts"], "coverage": "all",
        "reviewed_revision": "r1", "reviewed_on": "2026-09-28",
        "entries": [
            {"id": "card", "name": "Card", "kind": "component", "summary": "s", "contract": "c",
             "constraints": [], "tags": ["ui"], "source": "src/card.vue", "usages": [{"path": "src/p.vue", "start": 1, "end": 2}]},
            {"id": "fmt", "name": "fmt", "kind": "utility", "summary": "s", "contract": "c",
             "constraints": [], "source": "src/fmt.ts", "usages": [], "usage_gap": "none"},
        ],
    })
    write(project / "inventory.json", {"revision": "r1", "finalized": {"revision": "r1"}, "files": {
        "src/card.vue": {"review": {"kind": "catalogued"}},
        ".env.example": {"review": {"kind": "protected", "reason": "private_path"}},
    }})
    run = project / "runs" / "run1"
    write(run / "manifest.json", {"created_at": "2026-09-28T10:00:00", "repo_path": "C:/dev/Demo", "strategy": "exhaustive-batches-v1"})
    write(run / "derived.json", {"secret_source": "should never be served"})
    write(run / "calls" / "0000" / "result.json", {"answer": {"choice": "create", "confidence": 0.7,
                                                              "probabilities": {"create": 0.7, "reuse:card": 0.2, "wrap:fmt": 0.1}}})
    write(run / "calls" / "0001" / "result.json", {"answer": {"choice": "reuse:card", "confidence": 0.5,
                                                              "probabilities": {"create": 0.2, "reuse:card": 0.5}}})
    write(run / "response.json", {"answers": {"decision": {"probabilities": {"create": 0.6, "reuse:card": 0.4}}}})
    write(project / "tasks" / "t-1.json", {"id": "t-1", "requirement": "Build it", "acceptance": ["works"]})
    write(project / "decisions" / "t-1.json", {"schema": 1, "task_id": "t-1", "run": str(run), "provider": "typesafe",
                                               "provider_action": "create", "agent_final_choice": "create",
                                               "relation_to_provider": "agree", "reviewed_on": "2026-09-28"})
    (root / OTHER).mkdir()  # initialized directory without catalog yet
    (root / "not-a-project").mkdir()


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        build_store(self.root)
        self.store = Store([self.root / "missing", self.root])

    def tearDown(self):
        self.tmp.cleanup()

    def test_lists_only_hash_named_projects(self):
        projects = {p["id"]: p for p in self.store.projects()}
        self.assertEqual(set(projects), {PID, OTHER})
        demo = projects[PID]
        self.assertEqual((demo["name"], demo["entries"], demo["decisions"], demo["finalized"]), ("Demo", 2, 1, True))
        self.assertEqual(demo["repo_path"], "C:/dev/Demo")
        self.assertFalse(projects[OTHER]["initialized"])

    def test_project_detail_exposes_catalog_and_inventory(self):
        project = self.store.project(PID)
        self.assertEqual([e["id"] for e in project["catalog"]], ["card", "fmt"])
        self.assertEqual({f["path"]: f["kind"] for f in project["inventory"]},
                         {"src/card.vue": "catalogued", ".env.example": "protected"})
        self.assertEqual(project["decision_list"][0]["task_id"], "t-1")
        self.assertNotIn("run", project["decision_list"][0])

    def test_decision_trace_aggregates_batches(self):
        decision = self.store.decision(PID, "t-1")
        trace = decision["trace"]
        self.assertEqual([b["choice"] for b in trace["batches"]], ["create", "reuse:card"])
        self.assertEqual(tuple(trace["alternatives"][0]), ("reuse:card", 0.5))
        self.assertEqual(trace["final"][0][0], "create")
        self.assertEqual(decision["task"]["requirement"], "Build it")
        self.assertNotIn("run", decision)
        self.assertNotIn("secret_source", json.dumps(decision))

    def test_rejects_invalid_or_traversing_ids(self):
        for bad in ("../" + PID, PID.upper(), "x", ""):
            with self.assertRaises(NotFound):
                self.store.project(bad)
        for bad in ("../../catalog", "T-1", "missing"):
            with self.assertRaises(NotFound):
                self.store.decision(PID, bad)


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        build_store(root)
        cls.server = create_server(Store([root]), 0)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def request(self, path, method="GET", host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.putrequest(method, path, skip_host=True)
        conn.putheader("Host", host or f"127.0.0.1:{self.port}")
        conn.endheaders()
        response = conn.getresponse()
        body = response.read()
        conn.close()
        return response, body

    def test_binds_loopback_only(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_serves_app_with_security_headers(self):
        response, body = self.request("/")
        self.assertEqual(response.status, 200)
        self.assertIn(b"Tessera Studio", body)
        self.assertIn("default-src 'self'", response.getheader("Content-Security-Policy"))
        self.assertEqual(response.getheader("X-Content-Type-Options"), "nosniff")

    def test_api_routes(self):
        response, body = self.request("/api/projects")
        self.assertEqual(response.status, 200)
        self.assertEqual(len(json.loads(body)["projects"]), 2)
        response, body = self.request(f"/api/projects/{PID}/decisions/t-1")
        self.assertEqual(json.loads(body)["task_id"], "t-1")

    def test_unknown_and_traversal_paths_are_404(self):
        for path in ("/api/projects/nope", f"/api/projects/{PID}/decisions/..%2F..%2Fcatalog", "/../server.py", "/static/app.js"):
            response, _ = self.request(path)
            self.assertEqual(response.status, 404, path)

    def test_rejects_foreign_host_header(self):
        response, _ = self.request("/api/projects", host="evil.example:80")
        self.assertEqual(response.status, 421)

    def test_is_read_only(self):
        response, _ = self.request("/api/projects", method="POST")
        self.assertEqual(response.status, 405)


if __name__ == "__main__":
    unittest.main()
