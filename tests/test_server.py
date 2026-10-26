"""Meaningful regression tests for local state, fact readiness and recovery.

All writes use TemporaryDirectory. These tests never touch production data.
"""
from __future__ import annotations

import copy
import csv
import io
import json
import sys
import tempfile
import threading
import unittest
from datetime import date
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402


TODAY = date(2026, 10, 24)


def make_catalog():
    return {
        "profile": {"name": "测试用户"},
        "projects": [{"id": "01", "name": "测试项目一"},
                     {"id": "02", "name": "测试项目二"}],
        "sources": [], "roadmap": [], "capabilities": [], "opportunities": [],
    }


def make_seed():
    return {
        "schemaVersion": 1, "revision": 0,
        "projectStates": {
            key: {"status": "idea", "favorite": False, "notes": "",
                  "updatedAt": "2026-10-24T00:00:00"}
            for key in ("01", "02")
        },
        "evidence": [], "facts": [], "decisions": [], "reviews": [], "history": [],
    }


def fact_record(**overrides):
    value = {
        "subject": "培训课程", "field": "课程数量", "scope": "2026年秋季校区A",
        "value": "96", "unit": "节", "source": "本地核对表",
        "sourceDate": "2026-10-20", "validUntil": "2099-12-31",
        "status": "confirmed", "reviewer": "本人",
        "confirmedAt": "2026-10-24", "notes": "测试事实",
    }
    value.update(overrides)
    return value


def evidence_record(**overrides):
    value = {
        "title": "一次真实试用", "category": "实习", "contribution": "整理流程",
        "source": "本地试用记录", "boundary": "单次试用，不等于长期收益",
        "status": "documented", "date": "2026-10-24",
    }
    value.update(overrides)
    return value


def stored(record, identifier):
    return {**record, "id": identifier,
            "createdAt": "2026-10-24T00:00:00", "updatedAt": "2026-10-24T00:00:00"}


class FactDerivationTests(unittest.TestCase):
    def derive(self, *records):
        state = make_seed()
        state["facts"] = [stored(value, f"f-{index}") for index, value in enumerate(records)]
        return server.derive(state, today=TODAY)

    def test_confirmed_current_sourced_fact_is_ready(self):
        result = self.derive(fact_record())
        self.assertTrue(result["facts"][0]["ready"])
        self.assertEqual(result["stats"]["readyFacts"], 1)
        self.assertEqual(result["conflicts"], [])

    def test_96_and_112_conflict_and_neither_can_be_published(self):
        result = self.derive(fact_record(value="96"), fact_record(value="112"))
        self.assertEqual(len(result["conflicts"]), 1)
        self.assertEqual(set(result["conflicts"][0]["ids"]), {"f-0", "f-1"})
        self.assertTrue(all(not row["ready"] for row in result["facts"]))

    def test_numeric_equivalence_does_not_create_false_conflict(self):
        result = self.derive(fact_record(value="96"), fact_record(value="96.0"))
        self.assertEqual(result["conflicts"], [])
        self.assertTrue(all(row["ready"] for row in result["facts"]))

    def test_numeric_normalization_does_not_round_distinct_large_values(self):
        result = self.derive(
            fact_record(value="123456789012345678901234567890"),
            fact_record(value="123456789012345678901234567891"))
        self.assertEqual(len(result["conflicts"]), 1)
        self.assertTrue(all(not row["ready"] for row in result["facts"]))

    def test_unit_difference_is_a_conflict(self):
        result = self.derive(fact_record(unit="节"), fact_record(unit="小时"))
        self.assertEqual(len(result["conflicts"]), 1)

    def test_different_scope_is_not_a_conflict(self):
        result = self.derive(fact_record(value="96"),
                             fact_record(value="112", scope="2026年秋季校区B"))
        self.assertEqual(result["conflicts"], [])
        self.assertTrue(all(row["ready"] for row in result["facts"]))

    def test_pending_disagreement_blocks_otherwise_confirmed_fact(self):
        result = self.derive(fact_record(), fact_record(value="112", status="pending"))
        self.assertEqual(len(result["conflicts"]), 1)
        self.assertTrue(all(not row["ready"] for row in result["facts"]))

    def test_expired_fact_is_excluded_from_current_conflicts_and_publication(self):
        result = self.derive(fact_record(),
                             fact_record(value="112", validUntil="2026-10-23"))
        self.assertEqual(result["conflicts"], [])
        self.assertTrue(result["facts"][0]["ready"])
        self.assertFalse(result["facts"][1]["ready"])
        self.assertEqual(result["stats"]["expiredFacts"], 1)

    def test_expiry_is_inclusive(self):
        result = self.derive(fact_record(validUntil="2026-10-24"))
        self.assertTrue(result["facts"][0]["ready"])

    def test_retired_fact_is_not_ready_and_does_not_block_current_fact(self):
        result = self.derive(fact_record(), fact_record(value="112", status="retired"))
        self.assertEqual(result["conflicts"], [])
        self.assertTrue(result["facts"][0]["ready"])
        self.assertFalse(result["facts"][1]["ready"])

    def test_missing_validity_is_not_publishable(self):
        result = self.derive(fact_record(status="pending", validUntil=""))
        self.assertFalse(result["facts"][0]["ready"])

    def test_derivation_does_not_mutate_input_state(self):
        state = make_seed()
        state["facts"] = [stored(fact_record(), "f-1")]
        original = copy.deepcopy(state)
        server.derive(state, today=TODAY)
        self.assertEqual(state, original)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="career-workbench-test-")
        self.addCleanup(self.temp.cleanup)
        self.data_dir = Path(self.temp.name) / "data"
        self.catalog = make_catalog()
        self.seed = make_seed()
        self.store = server.Store(self.catalog, self.seed, self.data_dir)

    def assert_api_error(self, status, operation):
        with self.assertRaises(server.APIError) as caught:
            operation()
        self.assertEqual(caught.exception.status, status)

    def test_read_returns_independent_copy(self):
        result = self.store.get_state()
        result["projectStates"]["01"]["notes"] = "不应保存"
        result["facts"].append({"id": "bad"})
        actual = self.store.get_state()
        self.assertEqual(actual["projectStates"]["01"]["notes"], "")
        self.assertEqual(actual["facts"], [])

    def test_save_and_restart_preserve_user_data(self):
        result = self.store.save("evidence", evidence_record(), 0)
        self.assertEqual(result["revision"], 1)
        self.assertEqual(result["evidence"][0]["title"], "一次真实试用")
        self.assertTrue(result["evidence"][0]["id"])
        restarted = server.Store(self.catalog, self.seed, self.data_dir)
        self.assertEqual(restarted.get_state(), result)

    def test_corrupted_disk_state_is_not_silently_replaced_with_seed(self):
        corrupt = '{"incomplete":'
        state_file = self.data_dir / "state.json"
        state_file.write_text(corrupt, encoding="utf-8")
        with self.assertRaises(RuntimeError):
            server.Store(self.catalog, self.seed, self.data_dir)
        self.assertEqual(state_file.read_text(encoding="utf-8"), corrupt)

    def test_failed_atomic_replace_leaves_memory_and_disk_unchanged(self):
        before = self.store.save("evidence", evidence_record(title="不可丢失"), 0)
        state_file = self.data_dir / "state.json"
        disk_before = state_file.read_bytes()
        with patch.object(server.os, "replace", side_effect=PermissionError("simulated disk failure")):
            with self.assertRaises(PermissionError):
                self.store.save("evidence", evidence_record(title="本次未保存"), 1)
        self.assertEqual(self.store.get_state(), before)
        self.assertEqual(state_file.read_bytes(), disk_before)
        self.assertEqual(list(self.data_dir.glob(".state-*.tmp")), [])

    def test_stale_save_is_409_and_preserves_first_writer(self):
        first = self.store.save("evidence", evidence_record(title="先保存"), 0)
        self.assert_api_error(409, lambda: self.store.save(
            "evidence", evidence_record(title="过期覆盖"), 0))
        self.assertEqual(self.store.get_state(), first)

    def test_invalid_collection_does_not_change_state(self):
        original = self.store.get_state()
        self.assert_api_error(400, lambda: self.store.save("unknown", {}, 0))
        self.assertEqual(self.store.get_state(), original)

    def test_simultaneous_writers_cannot_overwrite_each_other(self):
        barrier = threading.Barrier(2)

        def write(title):
            barrier.wait(timeout=5)
            try:
                self.store.save("evidence", evidence_record(title=title), 0)
                return 200
            except server.APIError as error:
                return error.status

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(write, ["窗口一", "窗口二"]))
        self.assertEqual(sorted(outcomes), [200, 409])
        self.assertEqual(self.store.get_state()["revision"], 1)
        self.assertEqual(len(self.store.get_state()["evidence"]), 1)

    def test_record_with_unknown_field_is_rejected(self):
        self.assert_api_error(400, lambda: self.store.save(
            "evidence", evidence_record(unexpected="应拒绝"), 0))
        self.assertEqual(self.store.get_state()["revision"], 0)

    def test_wrong_text_type_and_unknown_enum_are_rejected(self):
        for record in (evidence_record(title=["不是文本"]), evidence_record(status="approved")):
            with self.subTest(record=record):
                self.assert_api_error(400, lambda record=record:
                                      self.store.save("evidence", record, 0))
        self.assertEqual(self.store.get_state()["revision"], 0)

    def test_nonboolean_favorite_is_rejected(self):
        self.assert_api_error(400, lambda: self.store.update_project(
            "01", {"favorite": "false"}, 0))
        self.assertFalse(self.store.get_state()["projectStates"]["01"]["favorite"])

    def test_boolean_revision_is_not_an_integer_revision(self):
        self.assert_api_error(400, lambda: self.store.save(
            "evidence", evidence_record(), False))
        self.assertEqual(self.store.get_state()["revision"], 0)

    def test_confirmed_fact_requires_each_audit_field(self):
        for field in ("source", "reviewer", "confirmedAt", "validUntil"):
            with self.subTest(field=field):
                self.assert_api_error(400, lambda field=field: self.store.save(
                    "facts", fact_record(**{field: ""}), 0))
                self.assertEqual(self.store.get_state()["facts"], [])
                self.assertEqual(self.store.get_state()["revision"], 0)

    def test_illegal_calendar_date_is_rejected_without_write(self):
        for bad_date in ("2026-02-30", "2026/10/24", "tomorrow"):
            with self.subTest(bad_date=bad_date):
                self.assert_api_error(400, lambda bad_date=bad_date: self.store.save(
                    "facts", fact_record(validUntil=bad_date), 0))
        self.assertEqual(self.store.get_state()["revision"], 0)

    def test_edit_preserves_id_and_creation_time(self):
        first = self.store.save("evidence", evidence_record(), 0)
        record = copy.deepcopy(first["evidence"][0])
        record["title"] = "补充后的试用记录"
        result = self.store.save("evidence", record, 1)
        self.assertEqual(len(result["evidence"]), 1)
        self.assertEqual(result["evidence"][0]["id"], record["id"])
        self.assertEqual(result["evidence"][0]["createdAt"], record["createdAt"])
        self.assertEqual(result["evidence"][0]["title"], "补充后的试用记录")

    def test_unknown_project_cannot_be_updated(self):
        self.assert_api_error(400, lambda: self.store.update_project(
            "99", {"status": "active"}, 0))
        self.assertEqual(self.store.get_state()["revision"], 0)

    def test_project_state_saves_and_rejects_stale_updates(self):
        result = self.store.update_project("01", {
            "status": "active", "favorite": True, "notes": "真实用户试用中"}, 0)
        self.assertTrue(result["projectStates"]["01"]["favorite"])
        self.assertEqual(result["projectStates"]["01"]["status"], "active")
        self.assert_api_error(409, lambda: self.store.update_project(
            "01", {"status": "archived"}, 0))
        self.assertEqual(self.store.get_state(), result)

    def test_review_cannot_reference_unknown_project(self):
        record = {"projectId": "99", "baseline": "之前", "result": "之后",
                  "feedback": "意见", "nextStep": "下一步", "date": "2026-10-24"}
        self.assert_api_error(400, lambda: self.store.save("reviews", record, 0))
        self.assertEqual(self.store.get_state()["reviews"], [])

    def test_backup_is_serializable_and_contains_format_identity(self):
        self.store.save("facts", fact_record(), 0)
        backup = self.store.export_backup()
        self.assertEqual(backup["app"], "career-workbench")
        self.assertEqual(backup["schemaVersion"], 1)
        self.assertEqual(json.loads(json.dumps(backup, ensure_ascii=False)), backup)

    def test_import_preview_is_read_only(self):
        self.store.save("facts", fact_record(), 0)
        before = self.store.get_state()
        preview = self.store.preview_import(self.store.export_backup())
        self.assertEqual(preview["counts"]["facts"], 1)
        self.assertEqual(self.store.get_state(), before)

    def test_restore_recovers_backup_and_uses_current_revision(self):
        self.store.save("evidence", evidence_record(title="备份中的记录"), 0)
        backup = self.store.export_backup()
        self.store.save("evidence", evidence_record(title="备份之后新增"), 1)
        result = self.store.restore(backup, 2)
        self.assertEqual(result["revision"], 3)
        self.assertEqual([row["title"] for row in result["evidence"]], ["备份中的记录"])
        restarted = server.Store(self.catalog, self.seed, self.data_dir)
        self.assertEqual(restarted.get_state(), result)

    def test_stale_restore_cannot_replace_newer_data(self):
        backup = self.store.export_backup()
        before = self.store.save("evidence", evidence_record(), 0)
        self.assert_api_error(409, lambda: self.store.restore(backup, 0))
        self.assertEqual(self.store.get_state(), before)

    def test_malformed_import_shapes_and_schema_do_not_modify_state(self):
        before = self.store.save("evidence", evidence_record(), 0)
        backup = self.store.export_backup()
        wrong_schema = copy.deepcopy(backup)
        wrong_schema["schemaVersion"] = 2
        wrong_app = copy.deepcopy(backup)
        wrong_app["app"] = "another-app"
        missing_state = {"app": "career-workbench", "schemaVersion": 1}
        for malformed in (None, [], "{invalid JSON", wrong_schema, wrong_app, missing_state):
            with self.subTest(malformed=malformed):
                self.assert_api_error(400, lambda malformed=malformed:
                                      self.store.restore(malformed, 1))
                self.assertEqual(self.store.get_state(), before)

    def test_duplicate_ids_in_import_are_rejected(self):
        before = self.store.save("evidence", evidence_record(), 0)
        backup = self.store.export_backup()
        backup["state"]["evidence"].append(copy.deepcopy(backup["state"]["evidence"][0]))
        self.assert_api_error(400, lambda: self.store.preview_import(backup))
        self.assert_api_error(400, lambda: self.store.restore(backup, 1))
        self.assertEqual(self.store.get_state(), before)

    def test_invalid_import_record_is_rejected_without_partial_restore(self):
        before = self.store.save("evidence", evidence_record(), 0)
        backup = self.store.export_backup()
        backup["state"]["facts"] = [stored(fact_record(validUntil="2026-02-30"), "bad-fact")]
        self.assert_api_error(400, lambda: self.store.restore(backup, 1))
        self.assertEqual(self.store.get_state(), before)

    def test_unknown_project_state_in_import_is_rejected(self):
        backup = self.store.export_backup()
        backup["state"]["projectStates"]["99"] = copy.deepcopy(
            backup["state"]["projectStates"]["01"])
        self.assert_api_error(400, lambda: self.store.preview_import(backup))
        self.assertEqual(self.store.get_state()["revision"], 0)

    def test_delete_preserves_other_records_and_rejects_stale_request(self):
        first = self.store.save("evidence", evidence_record(title="删除此项"), 0)
        target = first["evidence"][0]["id"]
        self.store.save("evidence", evidence_record(title="保留此项"), 1)
        result = self.store.delete("evidence", target, 2)
        self.assertEqual([row["title"] for row in result["evidence"]], ["保留此项"])
        self.assert_api_error(409, lambda: self.store.delete(
            "evidence", result["evidence"][0]["id"], 2))
        self.assertEqual(self.store.get_state(), result)

    def test_delete_creates_recoverable_prechange_backup(self):
        before = self.store.save("evidence", evidence_record(title="自动备份恢复测试"), 0)
        self.store.delete("evidence", before["evidence"][0]["id"], 1)
        backups = list((self.data_dir.parent / "backups").glob("*.json"))
        self.assertTrue(backups, "Deleting a record must create a historical backup")
        recoverable = [json.loads(path.read_text(encoding="utf-8")) for path in backups]
        matching = [value for value in recoverable
                    if value.get("state", {}).get("evidence")
                    and value["state"]["evidence"][0]["title"] == "自动备份恢复测试"]
        self.assertTrue(matching, "Backup must preserve the state before deletion")
        restored = self.store.restore(matching[-1], 2)
        self.assertEqual(restored["evidence"][0]["title"], "自动备份恢复测试")

    def test_restore_preserves_preimport_state_in_automatic_backup(self):
        empty_backup = self.store.export_backup()
        self.store.save("evidence", evidence_record(title="导入前的独有记录"), 0)
        self.store.restore(empty_backup, 1)
        backups = list((self.data_dir.parent / "backups").glob("*.json"))
        recovered_titles = [row["title"]
                            for path in backups
                            for row in json.loads(path.read_text(encoding="utf-8"))
                            .get("state", {}).get("evidence", [])]
        self.assertIn("导入前的独有记录", recovered_titles)


class ExportTests(unittest.TestCase):
    def test_publication_uses_only_current_confirmed_nonconflicting_facts(self):
        state = make_seed()
        state["facts"] = [
            stored(fact_record(subject="可发布课程总量"), "ready"),
            stored(fact_record(subject="待核实内容", status="pending"), "pending"),
            stored(fact_record(subject="已过期内容", validUntil="2026-10-23"), "expired"),
            stored(fact_record(subject="已退役内容", status="retired"), "retired"),
            stored(fact_record(subject="争议内容", value="96"), "conflict-a"),
            stored(fact_record(subject="争议内容", value="112"), "conflict-b"),
        ]
        result = server.publication_markdown(state, today=TODAY)
        self.assertIn("可发布课程总量", result)
        for forbidden in ("待核实内容", "已过期内容", "已退役内容", "争议内容"):
            self.assertNotIn(forbidden, result)

    def test_empty_publication_is_an_explicit_error(self):
        with self.assertRaises(server.APIError) as caught:
            server.publication_markdown(make_seed(), today=TODAY)
        self.assertEqual(caught.exception.status, 400)

    def test_markdown_escapes_active_html_in_user_text(self):
        state = make_seed()
        state["evidence"] = [stored(evidence_record(
            title='<script>alert("injected")</script>',
            contribution='<img src=x onerror="alert(1)">'), "e-1")]
        result = server.render_markdown(state, kind="evidence")
        self.assertNotIn("<script>", result)
        self.assertNotIn("<img ", result)
        self.assertIn("injected", result)

    def test_csv_formula_values_are_escaped_for_spreadsheets(self):
        for formula in ("=1+1", "+1+1", "-1+1", "@SUM(1,1)"):
            with self.subTest(formula=formula):
                state = make_seed()
                state["evidence"] = [stored(evidence_record(title=formula), "e-1")]
                result = server.render_csv(state, kind="evidence")
                rows = list(csv.reader(io.StringIO(result)))
                matching = [cell for row in rows[1:] for cell in row if formula in cell]
                self.assertTrue(matching)
                self.assertTrue(all(cell.startswith("'") for cell in matching))

    def test_csv_roundtrip_preserves_quotes_commas_and_newlines(self):
        title = '含逗号,和"引号"\n第二行'
        state = make_seed()
        state["evidence"] = [stored(evidence_record(title=title), "e-1")]
        result = server.render_csv(state, kind="evidence")
        rows = list(csv.reader(io.StringIO(result)))
        self.assertEqual(len(rows), 2)
        self.assertIn(title, rows[1])


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="career-workbench-http-test-")
        self.addCleanup(self.temp.cleanup)
        self.catalog = make_catalog()
        self.store = server.Store(self.catalog, make_seed(), Path(self.temp.name) / "data")
        self.httpd = server.create_server("127.0.0.1", 0, self.store, self.catalog)
        self.worker = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.worker.start()
        self.addCleanup(self.stop_server)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def stop_server(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=3)

    def request(self, path, *, payload=None, raw=None, token=None, origin=None):
        headers = {}
        data = raw
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if data is not None:
            headers = {"Content-Type": "application/json",
                       "X-App-Token": self.httpd.token if token is None else token,
                       "Origin": self.base if origin is None else origin}
        request = Request(self.base + path, data=data, headers=headers)
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, response.read()
        except HTTPError as error:
            return error.code, error.read()

    def test_bootstrap_exposes_local_catalog_state_and_token(self):
        status, raw = self.request("/api/bootstrap")
        self.assertEqual(status, 200)
        value = json.loads(raw)
        self.assertEqual(value["state"]["revision"], 0)
        self.assertEqual(value["token"], self.httpd.token)
        self.assertEqual(len(value["catalog"]["projects"]), 2)

    def test_malformed_json_is_400_and_server_remains_usable(self):
        status, raw = self.request("/api/save", raw=b'{"broken":')
        self.assertEqual(status, 400)
        self.assertIn("error", json.loads(raw))
        health_status, health_raw = self.request("/api/health")
        self.assertEqual(health_status, 200)
        self.assertEqual(json.loads(health_raw)["app"], "career-workbench")
        self.assertEqual(self.store.get_state()["revision"], 0)

    def test_duplicate_json_keys_and_nonstandard_numbers_are_rejected(self):
        for raw in (b'{"expectedRevision":0,"expectedRevision":1}', b'{"value":NaN}'):
            with self.subTest(raw=raw):
                status, body = self.request("/api/save", raw=raw)
                self.assertEqual(status, 400)
                self.assertIn("error", json.loads(body))
        self.assertEqual(self.store.get_state()["revision"], 0)

    def test_invalid_token_cannot_write(self):
        status, _ = self.request("/api/save", token="untrusted", payload={
            "expectedRevision": 0, "collection": "evidence", "record": evidence_record()})
        self.assertEqual(status, 403)
        self.assertEqual(self.store.get_state()["revision"], 0)

    def test_cross_origin_request_cannot_write(self):
        status, _ = self.request("/api/save", origin="https://untrusted.example", payload={
            "expectedRevision": 0, "collection": "evidence", "record": evidence_record()})
        self.assertEqual(status, 403)
        self.assertEqual(self.store.get_state()["revision"], 0)

    def test_stale_http_save_is_409_and_preserves_saved_record(self):
        payload = {"expectedRevision": 0, "collection": "evidence", "record": evidence_record()}
        status, raw = self.request("/api/save", payload=payload)
        self.assertEqual(status, 200)
        first = json.loads(raw)["state"]
        status, raw = self.request("/api/save", payload=payload)
        self.assertEqual(status, 409)
        self.assertIn("error", json.loads(raw))
        self.assertEqual(self.store.get_state(), first)


if __name__ == "__main__":
    unittest.main(verbosity=2)
