import contextlib
import http.client
import io
import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path

from tessera_studio.server import create_server
from tessera_studio.store import NotFound, Store

PID = "a" * 64
OTHER = "b" * 64
BROKEN = "c" * 64
WEIRD = "d" * 64
SECRET = "SECRET-MARKER-7f3a9c"


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
    # Raw evidence that contains source text: must never reach any response.
    write(run / "context.json", {"source": SECRET})
    write(run / "request.json", {"prompt": SECRET})
    write(run / "calls" / "0000" / "request.json", {"prompt": SECRET})
    write(project / "tasks" / "t-1.json", {"id": "t-1", "requirement": "Build it", "acceptance": ["works"]})
    write(project / "decisions" / "t-1.json", {"schema": 1, "task_id": "t-1", "run": str(run), "provider": "typesafe",
                                               "provider_action": "create", "agent_final_choice": "create",
                                               "relation_to_provider": "agree", "reviewed_on": "2026-09-28"})
    # tessera.py accepts any non-empty task id, including uppercase ones.
    write(project / "tasks" / "PROJ-42.json", {"id": "PROJ-42", "requirement": "Upper", "acceptance": []})
    write(project / "decisions" / "PROJ-42.json", {"task_id": "PROJ-42", "run": "C:\\store\\runs\\run1",
                                                   "relation_to_provider": None, "agent_final_choice": None,
                                                   "reviewed_on": "2026-09-27"})
    (root / OTHER).mkdir()  # initialized directory without catalog yet
    (root / "not-a-project").mkdir()


def build_malformed(root: Path):
    """A project whose files have the wrong JSON shapes."""
    project = root / BROKEN
    write(project / "catalog.json", ["not", "an", "object"])
    write(project / "inventory.json", {"files": ["a", "b"], "finalized": "yes"})
    write(project / "runs" / "r" / "manifest.json", ["list"])
    write(project / "decisions" / "a.json", {"task_id": "a", "reviewed_on": "2026-09-01"})
    write(project / "decisions" / "b.json", {"task_id": "b", "reviewed_on": 5, "run": ".."})
    write(project / "decisions" / "c.json", {"reviewed_on": "2026-09-02"})  # missing task_id
    write(project / "decisions" / "d.json", ["not", "a", "decision"])
    write(project / "decisions" / "e.json", {"task_id": "e", "reviewed_on": {"odd": True}})
    (project / "decisions" / "f.json").write_text("{broken", encoding="utf-8")
    weird = root / WEIRD
    write(weird / "catalog.json", {"project": ["x"], "reviewed_on": 3, "scope": "not-a-list", "entries": [
        "string entry", {"id": 7, "kind": None, "source": None, "usages": "x", "tags": None}]})
    write(weird / "inventory.json", {"files": {"a.ts": "not-a-dict", "b.ts": {"review": ["x"]}}})
    write(weird / "decisions" / "x.json", {"task_id": "x", "run": "run1"})
    write(weird / "runs" / "run1" / "calls" / "0000" / "result.json",
          {"answer": {"choice": ["odd"], "confidence": "high", "probabilities": {"reuse:a": "0.5", "wrap:b": 0.3}}})
    write(weird / "runs" / "run1" / "response.json", {"answers": {"decision": ["bad"]}})


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
        self.assertEqual((demo["name"], demo["entries"], demo["decisions"], demo["finalized"]), ("Demo", 2, 2, True))
        self.assertEqual(demo["repo_path"], "C:/dev/Demo")
        self.assertEqual((demo["files"], demo["reviewed"]), (2, 2))
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
        for bad in ("../../catalog", "T-1", "missing", "..", ".", "t-1/../t-1", None):
            with self.assertRaises(NotFound):
                self.store.decision(PID, bad)

    def test_uppercase_task_id_and_null_fields(self):
        decision = self.store.decision(PID, "PROJ-42")
        self.assertEqual(decision["task"]["requirement"], "Upper")
        self.assertIsNone(decision["relation_to_provider"])
        # A Windows-style run path still resolves to the run inside this store.
        self.assertEqual(len(decision["trace"]["batches"]), 2)

    def test_task_file_must_stay_inside_tasks_directory(self):
        write(self.root / PID / "decisions" / "evil.json", {"task_id": "../catalog", "run": "../.."})
        decision = self.store.decision(PID, "../catalog")
        self.assertIsNone(decision["task"])
        self.assertIsNone(decision["trace"])


class MalformedStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        build_store(self.root)
        build_malformed(self.root)
        self.store = Store([self.root])

    def tearDown(self):
        self.tmp.cleanup()

    def test_malformed_projects_do_not_break_listing(self):
        projects = {p["id"]: p for p in self.store.projects()}
        self.assertEqual(set(projects), {PID, OTHER, BROKEN, WEIRD})
        self.assertEqual((projects[BROKEN]["entries"], projects[BROKEN]["files"]), (0, 0))
        self.assertFalse(projects[BROKEN]["finalized"])
        self.assertIsNone(projects[BROKEN]["repo_path"])
        self.assertEqual(projects[WEIRD]["reviewed_on"], "3")
        self.assertEqual(projects[WEIRD]["kinds"], [("unknown", 1)])
        json.dumps(list(projects.values()))  # always serializable

    def test_malformed_project_detail(self):
        broken = self.store.project(BROKEN)
        self.assertEqual(broken["catalog"], [])
        self.assertEqual(broken["inventory"], [])
        # Mixed-type reviewed_on values sort; decisions without task_id or not objects are skipped.
        self.assertEqual(sorted(d["task_id"] for d in broken["decision_list"]), ["a", "b", "e"])
        weird = self.store.project(WEIRD)
        self.assertEqual(weird["scope"], [])
        entry = weird["catalog"][0]
        self.assertEqual((entry["id"], entry["kind"], entry["source"], entry["usages"], entry["tags"]),
                         ("7", "unknown", "", [], []))
        self.assertEqual({f["path"]: f["kind"] for f in weird["inventory"]}, {"a.ts": "pending", "b.ts": "pending"})

    def test_malformed_decisions(self):
        self.assertIsNone(self.store.decision(BROKEN, "a")["task"])
        self.assertIsNone(self.store.decision(BROKEN, "b")["trace"])  # run ".." never resolves
        trace = self.store.decision(WEIRD, "x")["trace"]
        self.assertEqual(trace["batches"], [{"call": "0000", "choice": None, "confidence": None,
                                             "best": ("wrap:b", 0.3)}])
        self.assertEqual(trace["final"], [])


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
        """``host=False`` sends no Host header at all."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        if host is not False:
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
        for method in ("POST", "PUT", "DELETE", "OPTIONS", "TRACE", "FOO"):
            response, body = self.request("/api/projects", method=method)
            self.assertEqual(response.status, 405, method)
            self.assertEqual(response.getheader("X-Content-Type-Options"), "nosniff", method)
            self.assertIn("error", json.loads(body), method)

    def test_rejects_missing_host_header(self):
        response, _ = self.request("/api/projects", host=False)
        self.assertEqual(response.status, 421)

    def test_accepts_localhost_host_header(self):
        response, _ = self.request("/api/projects", host=f"localhost:{self.port}")
        self.assertEqual(response.status, 200)

    def test_head_returns_headers_without_body(self):
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
            sock.sendall(f"HEAD / HTTP/1.0\r\nHost: 127.0.0.1:{self.port}\r\n\r\n".encode())
            raw = b""
            while chunk := sock.recv(65536):
                raw += chunk
        head, _, body = raw.partition(b"\r\n\r\n")
        self.assertIn(b" 200 ", head.split(b"\r\n")[0])
        self.assertIn(b"Content-Length:", head)
        self.assertEqual(body, b"")

    def test_static_content_types(self):
        expected = {"/": "text/html; charset=utf-8", "/app.js": "text/javascript; charset=utf-8",
                    "/app.css": "text/css; charset=utf-8", "/favicon.svg": "image/svg+xml; charset=utf-8"}
        for path, content_type in expected.items():
            response, _ = self.request(path)
            self.assertEqual(response.getheader("Content-Type"), content_type, path)

    def test_null_relation_decision_is_served(self):
        response, body = self.request(f"/api/projects/{PID}/decisions/PROJ-42")
        self.assertEqual(response.status, 200)
        self.assertIsNone(json.loads(body)["relation_to_provider"])

    def test_raw_run_evidence_is_never_served(self):
        paths = ["/api/projects", f"/api/projects/{PID}", f"/api/projects/{PID}/decisions/t-1",
                 f"/api/projects/{PID}/decisions/PROJ-42"]
        for path in paths:
            response, body = self.request(path)
            self.assertEqual(response.status, 200, path)
            self.assertNotIn(SECRET.encode(), body, path)
            self.assertNotIn(b"should never be served", body, path)


class FailingStore(Store):
    def projects(self):
        raise RuntimeError("boom with a private detail")


class ServerErrorTest(unittest.TestCase):
    def test_unexpected_exception_returns_json_500(self):
        server = create_server(FailingStore([]), 0)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        stderr = io.StringIO()
        try:
            with contextlib.redirect_stderr(stderr):
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("GET", "/api/projects", headers={"Host": f"127.0.0.1:{port}"})
                response = conn.getresponse()
                body = response.read()
                conn.close()
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(response.status, 500)
        self.assertEqual(response.getheader("Content-Type"), "application/json; charset=utf-8")
        self.assertEqual(response.getheader("X-Content-Type-Options"), "nosniff")
        self.assertEqual(json.loads(body), {"error": "internal error"})
        self.assertNotIn(b"private detail", body)
        self.assertNotIn(b"Traceback", body)
        self.assertIn("RuntimeError", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
