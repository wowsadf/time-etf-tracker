from __future__ import annotations

import sys
import shutil
import json
import unittest
from copy import deepcopy
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch, MagicMock
from uuid import uuid4
from types import SimpleNamespace

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent.parent
APP_DIR = ROOT_DIR / "app"
sys.path.insert(0, str(APP_DIR))
TEST_TEMP_ROOT = ROOT_DIR / "temp"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)

import snapshot_manager  # noqa: E402
import state_manager  # noqa: E402
import run_tracker_once  # noqa: E402
import ai_analyzer  # noqa: E402
import fetcher  # noqa: E402
import manual  # noqa: E402
import email_sender  # noqa: E402
from compare import compare_holdings, add_rank, has_stock_quantity_changes  # noqa: E402
from exceptions import StateCorruptionError, DataNotReadyError  # noqa: E402
from holdings_parser import load_holdings_excel  # noqa: E402
from reporter import build_compare_report_html, build_compare_report_text, build_compare_ai_payload  # noqa: E402
from validator import validate_holdings  # noqa: E402


SNAPSHOT_COLUMNS = [
    "종목코드",
    "종목명",
    "수량",
    "평가금액(원)",
    "비중(%)",
    "asset_key",
    "asset_type",
]


def make_df(rows: list[list[object]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=SNAPSHOT_COLUMNS)


def valid_df() -> pd.DataFrame:
    return make_df([
        [f"S{i} US EQUITY", f"S{i}", 10, 100, 10.0, f"S{i} US EQUITY", "stock"]
        for i in range(10)
    ])


def valid_analysis() -> dict:
    return {
        "quantity_claims": [],
        "one_line_take": "확인이 필요한 변화입니다.", "core_view": "해석", "manager_intent": "가설",
        "evidence_based_observations": ["근거"],
        "portfolio_implications": ["영향"],
        "key_risks": [{"level": "low", "issue": "위험", "evidence": "근거"}],
        "what_to_watch_next": ["확인"],
        "data_limitations": ["한계"] * 2,
    }


@contextmanager
def workspace_temp_dir():
    path = TEST_TEMP_ROOT / f"test-{uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        resolved = path.resolve()
        if resolved.parent != TEST_TEMP_ROOT.resolve():
            raise RuntimeError(f"테스트 임시 경로가 예상 범위를 벗어났습니다: {resolved}")
        shutil.rmtree(resolved)


class CompareHoldingsTests(unittest.TestCase):
    def test_numeric_strings_rank_numerically(self) -> None:
        data = valid_df()
        data["비중(%)"] = ["9.0", "10.0"] + ["1.0"] * 8
        result = compare_holdings(data, data).set_index("asset_key")
        self.assertEqual(result.loc["S1 US EQUITY", "rank_today"], 1)

    def test_missing_numeric_value_is_not_filled_as_zero(self) -> None:
        data = valid_df()
        data.loc[0, "수량"] = float("nan")
        with self.assertRaises(ValueError):
            compare_holdings(data, data)

    def test_asset_type_change_requires_review(self) -> None:
        old, current = valid_df(), valid_df()
        current.loc[0, "asset_type"] = "cash"
        with self.assertRaisesRegex(ValueError, "자산 분류"):
            compare_holdings(current, old)

    def test_equal_weights_have_stable_ranks(self) -> None:
        first = add_rank(valid_df()).set_index("asset_key")["rank"]
        second = add_rank(valid_df().iloc[::-1]).set_index("asset_key")["rank"]
        pd.testing.assert_series_equal(first.sort_index(), second.sort_index())

    def test_quantity_percent_is_null_for_zero_previous(self) -> None:
        old = valid_df()
        old.loc[0, "수량"] = 0
        result = compare_holdings(valid_df(), old).set_index("asset_key")
        self.assertTrue(pd.isna(result.loc["S0 US EQUITY", "quantity_change_pct"]))

    def test_duplicate_merge_keys_are_rejected(self) -> None:
        data = valid_df()
        with self.assertRaises(pd.errors.MergeError):
            compare_holdings(pd.concat([data, data.iloc[:1]]), data)

    def test_weight_drift_is_not_classified_as_trade(self) -> None:
        previous = make_df([
            ["A US EQUITY", "A", 10, 600, 60.0, "A US EQUITY", "stock"],
            ["B US EQUITY", "B", 10, 400, 40.0, "B US EQUITY", "stock"],
        ])
        current = make_df([
            ["A US EQUITY", "A", 10, 550, 55.0, "A US EQUITY", "stock"],
            ["B US EQUITY", "B", 10, 450, 45.0, "B US EQUITY", "stock"],
        ])

        compared = compare_holdings(current, previous).set_index("asset_key")

        self.assertEqual(compared.loc["A US EQUITY", "status"], "decreased")
        self.assertEqual(compared.loc["A US EQUITY", "quantity_status"], "unchanged")
        self.assertEqual(compared.loc["B US EQUITY", "status"], "increased")
        self.assertEqual(compared.loc["B US EQUITY", "quantity_status"], "unchanged")

    def test_stock_rank_excludes_cash_and_futures(self) -> None:
        data = make_df([
            ["CASH", "현금", 1, 900, 90.0, "CASH", "cash"],
            ["A US EQUITY", "A", 10, 60, 6.0, "A US EQUITY", "stock"],
            ["B US EQUITY", "B", 10, 40, 4.0, "B US EQUITY", "stock"],
        ])

        compared = compare_holdings(data, data).set_index("asset_key")

        self.assertEqual(compared.loc["A US EQUITY", "rank_today"], 1)
        self.assertEqual(compared.loc["B US EQUITY", "rank_today"], 2)
        self.assertTrue(pd.isna(compared.loc["CASH", "rank_today"]))

    def test_existing_zero_weight_row_is_not_removed(self) -> None:
        previous = make_df([
            ["A US EQUITY", "A", 0, 0, 0.0, "A US EQUITY", "stock"],
        ])
        current = previous.copy()

        compared = compare_holdings(current, previous).iloc[0]

        self.assertEqual(compared["status"], "unchanged")
        self.assertEqual(compared["quantity_status"], "unchanged")


class ValidationTests(unittest.TestCase):
    def test_duplicate_excel_headers_are_rejected(self) -> None:
        with workspace_temp_dir() as temp_dir:
            data = valid_df().drop(columns=["asset_key", "asset_type"])
            data = pd.concat([data, data[["수량"]]], axis=1)
            path = temp_dir / "duplicate.xlsx"
            data.to_excel(path, index=False)
            with self.assertRaisesRegex(ValueError, "중복"):
                load_holdings_excel(path)

    def test_missing_key_or_asset_type_is_rejected(self) -> None:
        for column in ["asset_key", "asset_type"]:
            with self.subTest(column=column):
                data = valid_df()
                data.loc[0, column] = None
                with self.assertRaises(ValueError):
                    validate_holdings(data)

    def test_numeric_strings_are_accepted(self) -> None:
        data = valid_df()
        data["비중(%)"] = data["비중(%)"].astype(str)
        validate_holdings(data)

    def test_nonfinite_value_is_rejected(self) -> None:
        data = valid_df()
        data["수량"] = data["수량"].astype(float)
        data.loc[0, "수량"] = float("inf")
        with self.assertRaises(ValueError):
            validate_holdings(data)

    def test_empty_template_is_skipped(self) -> None:
        with workspace_temp_dir() as temp_dir:
            path = temp_dir / "empty.xlsx"
            valid_df().iloc[:0].drop(columns=["asset_key", "asset_type"]).to_excel(path, index=False)
            with self.assertRaises(DataNotReadyError):
                validate_holdings(load_holdings_excel(path))

    def test_partially_empty_excel_row_is_not_silently_dropped(self) -> None:
        with workspace_temp_dir() as temp_dir:
            data = valid_df().drop(columns=["asset_key", "asset_type"])
            data.loc[10] = [None, None, 1, 100, 0]
            path = temp_dir / "broken.xlsx"
            data.to_excel(path, index=False)
            parsed = load_holdings_excel(path)
            self.assertEqual(len(parsed), 11)
            with self.assertRaises(ValueError):
                validate_holdings(parsed)

    def test_duplicate_asset_key_is_rejected(self) -> None:
        rows = [
            [f"S{i} US EQUITY", f"S{i}", 10, 100, 10.0, f"S{i} US EQUITY", "stock"]
            for i in range(9)
        ]
        rows.append(rows[0].copy())
        duplicated = make_df(rows)

        with self.assertRaisesRegex(ValueError, "asset_key 중복"):
            validate_holdings(duplicated)


class SnapshotManagerTests(unittest.TestCase):
    def test_text_key_na_is_not_interpreted_as_missing(self) -> None:
        with workspace_temp_dir() as temp_dir:
            data = valid_df()
            data.loc[0, "asset_key"] = "NA"
            path = temp_dir / "data.csv"
            data.to_csv(path, index=False, encoding="utf-8-sig")
            self.assertEqual(snapshot_manager.load_snapshot_df(path).loc[0, "asset_key"], "NA")

    def test_hash_ignores_row_order_and_numeric_dtype(self) -> None:
        first = valid_df()
        second = first.iloc[::-1].copy()
        second["수량"] = second["수량"].astype(float)
        second["평가금액(원)"] = second["평가금액(원)"].astype(float)
        self.assertEqual(snapshot_manager.compute_snapshot_hash(first), snapshot_manager.compute_snapshot_hash(second))

    def test_hash_rejects_missing_values(self) -> None:
        data = valid_df()
        data.loc[0, "수량"] = float("nan")
        with self.assertRaises(ValueError):
            snapshot_manager.compute_snapshot_hash(data)

    def test_snapshot_date_cannot_escape_directory(self) -> None:
        with self.assertRaises(ValueError):
            snapshot_manager.make_snapshot_filename("../outside")

    def test_different_snapshots_on_same_date_do_not_overwrite(self) -> None:
        first = make_df([
            ["A US EQUITY", "A", 10, 1000, 100.0, "A US EQUITY", "stock"],
        ])
        second = make_df([
            ["A US EQUITY", "A", 11, 1000, 100.0, "A US EQUITY", "stock"],
        ])

        with workspace_temp_dir() as temp_dir:
            original_dir = snapshot_manager.SNAPSHOTS_DIR
            snapshot_manager.SNAPSHOTS_DIR = temp_dir
            try:
                first_path = snapshot_manager.save_snapshot(first, "2026-01-01")
                second_path = snapshot_manager.save_snapshot(second, "2026-01-01")

                self.assertNotEqual(first_path, second_path)
                self.assertEqual(
                    snapshot_manager.compute_snapshot_hash(snapshot_manager.load_snapshot_df(first_path)),
                    snapshot_manager.compute_snapshot_hash(first),
                )
            finally:
                snapshot_manager.SNAPSHOTS_DIR = original_dir


class StateManagerTests(unittest.TestCase):
    def test_incomplete_pending_state_is_rejected(self) -> None:
        with workspace_temp_dir() as temp_dir:
            path = temp_dir / "state.json"
            path.write_text(json.dumps({"pending_report_hash": "abc"}), encoding="utf-8")
            with patch.object(state_manager, "TRACKER_STATE_PATH", path):
                with self.assertRaises(StateCorruptionError):
                    state_manager.load_state()

    def test_state_save_and_load_is_backward_compatible(self) -> None:
        with workspace_temp_dir() as temp_dir:
            original_path = state_manager.TRACKER_STATE_PATH
            state_manager.TRACKER_STATE_PATH = temp_dir / "tracker_state.json"
            try:
                state = state_manager.default_state()
                state["last_attempt_status"] = "test"
                state_manager.save_state(state)
                loaded = state_manager.load_state()

                self.assertEqual(loaded["last_attempt_status"], "test")
                self.assertEqual(loaded["schema_version"], state_manager.STATE_SCHEMA_VERSION)
            finally:
                state_manager.TRACKER_STATE_PATH = original_path

    def test_corrupt_state_is_not_silently_reset(self) -> None:
        with workspace_temp_dir() as temp_dir:
            original_path = state_manager.TRACKER_STATE_PATH
            state_manager.TRACKER_STATE_PATH = temp_dir / "tracker_state.json"
            try:
                state_manager.TRACKER_STATE_PATH.write_text("{broken", encoding="utf-8")
                with self.assertRaises(StateCorruptionError):
                    state_manager.load_state()
            finally:
                state_manager.TRACKER_STATE_PATH = original_path


class TrackerRetryTests(unittest.TestCase):
    def test_ai_failure_still_sends_base_email(self) -> None:
        with workspace_temp_dir() as temp_dir:
            data = valid_df()
            previous, current = temp_dir / "previous.csv", temp_dir / "current.csv"
            data.to_csv(previous, index=False, encoding="utf-8-sig")
            data.loc[0, "수량"] += 1
            data.to_csv(current, index=False, encoding="utf-8-sig")
            with (
                patch.object(run_tracker_once, "analyze_compare_payload", side_effect=ValueError("invalid AI")),
                patch.object(run_tracker_once, "send_html_email") as send,
            ):
                run_tracker_once.send_report(previous, current)
            send.assert_called_once()
            self.assertIn("AI 분석을 사용할 수 없습니다", send.call_args.kwargs["html_body"])

    def test_pending_report_is_retried_from_saved_snapshot_paths(self) -> None:
        with workspace_temp_dir() as temp_dir:
            previous_path = temp_dir / "previous.csv"
            current_path = temp_dir / "current.csv"
            data = valid_df()
            data.to_csv(previous_path, index=False, encoding="utf-8-sig")
            data.loc[0, "수량"] += 1
            data.to_csv(current_path, index=False, encoding="utf-8-sig")
            pending_hash = snapshot_manager.compute_snapshot_hash(data)

            state = state_manager.default_state()
            state.update({
                "pending_report_hash": pending_hash,
                "pending_snapshot_path": str(current_path),
                "pending_previous_snapshot_path": str(previous_path),
            })

            with (
                patch.object(run_tracker_once, "send_report", return_value=True) as mocked_send,
                patch.object(run_tracker_once, "save_state") as mocked_save,
            ):
                retried = run_tracker_once.retry_pending_report_if_needed(state)

            self.assertTrue(retried)
            mocked_send.assert_called_once_with(previous_path, current_path)
            mocked_save.assert_called_once_with(state)
            self.assertEqual(state["last_reported_hash"], pending_hash)
            self.assertIsNone(state["pending_report_hash"])

    def test_smtp_failure_keeps_pending_report(self) -> None:
        with workspace_temp_dir() as temp_dir:
            data = valid_df()
            path = temp_dir / "current.csv"
            data.to_csv(path, index=False, encoding="utf-8-sig")
            state = state_manager.default_state()
            state.update({"pending_report_hash": snapshot_manager.compute_snapshot_hash(data),
                          "pending_snapshot_path": str(path), "pending_previous_snapshot_path": str(path)})
            original = state.copy()
            with patch.object(run_tracker_once, "send_report", side_effect=RuntimeError("SMTP failed")):
                with self.assertRaises(RuntimeError):
                    run_tracker_once.retry_pending_report_if_needed(state)
            self.assertEqual(state, original)

    def test_corrupted_pending_snapshot_is_not_sent(self) -> None:
        with workspace_temp_dir() as temp_dir:
            data = valid_df()
            path = temp_dir / "current.csv"
            data.to_csv(path, index=False, encoding="utf-8-sig")
            state = state_manager.default_state()
            state.update({"pending_report_hash": "wrong-hash",
                          "pending_snapshot_path": str(path), "pending_previous_snapshot_path": str(path)})
            with patch.object(run_tracker_once, "send_report") as send:
                with self.assertRaises(ValueError):
                    run_tracker_once.retry_pending_report_if_needed(state)
                send.assert_not_called()

    def test_hash_upgrade_does_not_send_duplicate_email(self) -> None:
        with workspace_temp_dir() as temp_dir:
            data = valid_df()
            path = temp_dir / "previous.csv"
            data.to_csv(path, index=False, encoding="utf-8-sig")
            state = state_manager.default_state()
            state.update({"last_snapshot_hash": snapshot_manager.compute_snapshot_hash(data, legacy=True),
                          "last_snapshot_path": str(path)})
            with (
                patch.object(run_tracker_once, "load_state", return_value=state),
                patch.object(run_tracker_once, "save_state"),
                patch.object(run_tracker_once, "download_excel_with_retry"),
                patch.object(run_tracker_once, "load_holdings_excel", return_value=data),
                patch.object(run_tracker_once, "send_report") as send,
                patch.object(run_tracker_once, "save_snapshot") as save,
            ):
                run_tracker_once.main()
                send.assert_not_called()
                save.assert_not_called()
            self.assertEqual(state["last_attempt_status"], "duplicate_valid_snapshot")


class TrackerNotificationPolicyTests(unittest.TestCase):
    def run_tracker(self, previous, currents):
        """Real snapshot/report flow, with download, AI, SMTP and operating state isolated."""
        with workspace_temp_dir() as temp_dir:
            previous_path = temp_dir / "previous.csv"
            previous.to_csv(previous_path, index=False, encoding="utf-8-sig")
            state = state_manager.default_state()
            previous_hash = snapshot_manager.compute_snapshot_hash(previous)
            state.update({
                "last_snapshot_path": str(previous_path), "last_snapshot_hash": previous_hash,
                "last_reported_snapshot_path": str(previous_path), "last_reported_hash": previous_hash,
                "last_reported_at": "previous-report-time",
            })
            initial = deepcopy(state)
            persisted, after_runs = [], []
            with (
                patch.object(snapshot_manager, "SNAPSHOTS_DIR", temp_dir),
                patch.object(run_tracker_once, "load_state", return_value=state),
                patch.object(run_tracker_once, "save_state", side_effect=lambda value: persisted.append(deepcopy(value))),
                patch.object(run_tracker_once, "download_excel_with_retry"),
                patch.object(run_tracker_once, "load_holdings_excel", side_effect=[df.copy() for df in currents]),
                patch.object(run_tracker_once, "try_build_ai_analysis", return_value=None) as ai,
                patch.object(run_tracker_once, "send_html_email") as email,
                patch.object(run_tracker_once, "send_report", wraps=run_tracker_once.send_report) as report,
                patch.object(run_tracker_once, "now_kst_iso", return_value="2026-11-27T12:00:00+09:00"),
            ):
                for _ in currents:
                    run_tracker_once.main()
                    after_runs.append(deepcopy(state))
                stored = snapshot_manager.load_snapshot_df(state_manager.resolve_state_path(state["last_snapshot_path"]))
                pairs = [tuple(state_manager.path_to_state_value(path) for path in call.args) for call in report.call_args_list]
            return {"state": state, "initial": initial, "persisted": persisted, "after_runs": after_runs,
                    "ai_calls": ai.call_count, "email_calls": email.call_count, "stored": stored, "report_pairs": pairs}

    def assert_quiet_day(self, result):
        self.assertEqual(result["ai_calls"], 0)
        self.assertEqual(result["email_calls"], 0)
        self.assertEqual(result["state"]["last_attempt_status"], "saved_without_stock_quantity_change")
        for key in ["last_reported_hash", "last_reported_snapshot_path", "last_reported_at"]:
            self.assertEqual(result["state"][key], result["initial"][key])
        self.assertNotEqual(result["state"]["last_snapshot_hash"], result["initial"]["last_snapshot_hash"])
        self.assertTrue(all(state["pending_report_hash"] is None for state in result["persisted"]))

    def test_weight_valuation_and_rank_changes_only_save_snapshot(self):
        previous, current = valid_df(), valid_df()
        current.loc[0, "비중(%)"] += 0.5
        current.loc[1, "비중(%)"] -= 0.5
        current.loc[0, "평가금액(원)"] += 5
        result = self.run_tracker(previous, [current])
        self.assert_quiet_day(result)
        self.assertEqual(result["state"]["last_snapshot_hash"], snapshot_manager.compute_snapshot_hash(current))
        self.assertEqual(result["stored"].loc[0, "비중(%)"], 10.5)

    def test_cash_or_futures_quantity_only_does_not_notify(self):
        for asset_type in ["cash", "futures"]:
            with self.subTest(asset_type=asset_type):
                previous = valid_df()
                previous["비중(%)"] = 9.5
                previous.loc[10] = ["OTHER", "현금" if asset_type == "cash" else "선물", 100, 100, 5.0, "OTHER", asset_type]
                current = previous.copy()
                current.loc[10, "수량"] -= 1
                self.assert_quiet_day(self.run_tracker(previous, [current]))

    def test_stock_quantity_increase_or_decrease_notifies(self):
        for delta in [-1, 1]:
            with self.subTest(delta=delta):
                previous, current = valid_df(), valid_df()
                current.loc[0, "수량"] += delta
                result = self.run_tracker(previous, [current])
                self.assertEqual(result["email_calls"], 1)
                self.assertEqual(result["ai_calls"], 1)
                self.assertEqual(result["state"]["last_attempt_status"], "reported")
                self.assertEqual(result["state"]["last_reported_hash"], result["state"]["last_snapshot_hash"])
                self.assertIsNone(result["state"]["pending_report_hash"])

    def test_new_and_removed_stocks_notify_even_if_total_quantity_unchanged(self):
        previous, current = valid_df(), valid_df()
        current.loc[0, ["종목코드", "asset_key", "종목명"]] = ["NEW US EQUITY", "NEW US EQUITY", "New stock"]
        self.assertTrue(has_stock_quantity_changes(compare_holdings(current, previous)))
        result = self.run_tracker(previous, [current])
        self.assertEqual(result["email_calls"], 1)
        self.assertEqual(result["ai_calls"], 1)

    def test_repeated_quiet_snapshot_stays_quiet(self):
        previous, current = valid_df(), valid_df()
        current.loc[0, "평가금액(원)"] += 1
        result = self.run_tracker(previous, [current, current])
        self.assertEqual(result["email_calls"], 0)
        self.assertEqual(result["ai_calls"], 0)
        self.assertEqual(result["state"]["last_attempt_status"], "duplicate_valid_snapshot")
        self.assertEqual(result["state"]["last_reported_at"], "previous-report-time")

    def test_quantity_change_after_quiet_day_compares_against_latest_snapshot(self):
        previous, quiet = valid_df(), valid_df()
        quiet.loc[0, "평가금액(원)"] += 1
        changed = quiet.copy()
        changed.loc[0, "수량"] += 1
        result = self.run_tracker(previous, [quiet, changed])
        self.assertEqual(result["email_calls"], 1)
        self.assertEqual(result["report_pairs"][0][0], result["after_runs"][0]["last_snapshot_path"])

    def test_legacy_pending_report_without_stock_quantity_change_is_dropped(self):
        with workspace_temp_dir() as temp_dir:
            previous, current = valid_df(), valid_df()
            current.loc[0, "평가금액(원)"] += 1
            prev_path, current_path = temp_dir / "previous.csv", temp_dir / "current.csv"
            previous.to_csv(prev_path, index=False, encoding="utf-8-sig")
            current.to_csv(current_path, index=False, encoding="utf-8-sig")
            state = state_manager.default_state()
            state.update({"last_snapshot_path": str(current_path),
                          "last_snapshot_hash": snapshot_manager.compute_snapshot_hash(current),
                          "last_reported_hash": "previous-report-hash", "last_reported_at": "previous-report-time",
                          "pending_report_hash": snapshot_manager.compute_snapshot_hash(current),
                          "pending_snapshot_path": str(current_path), "pending_previous_snapshot_path": str(prev_path)})
            with (patch.object(run_tracker_once, "save_state"),
                  patch.object(run_tracker_once, "try_build_ai_analysis") as ai,
                  patch.object(run_tracker_once, "send_html_email") as email):
                self.assertFalse(run_tracker_once.retry_pending_report_if_needed(state))
            ai.assert_not_called()
            email.assert_not_called()
            self.assertIsNone(state["pending_report_hash"])
            self.assertEqual(state["last_reported_at"], "previous-report-time")
            self.assertEqual(state["last_reported_hash"], "previous-report-hash")


class ReporterTests(unittest.TestCase):
    def test_email_html_does_not_embed_raw_ai_payload(self) -> None:
        previous = pd.read_csv(ROOT_DIR / "snapshots" / "2026-03-27.csv", encoding="utf-8-sig")
        current = pd.read_csv(ROOT_DIR / "snapshots" / "2026-03-30.csv", encoding="utf-8-sig")
        compared = compare_holdings(current, previous)

        report = build_compare_report_html(compared)

        self.assertNotIn("ai-summary-json", report)
        self.assertLess(len(report.encode("utf-8")), 100_000)
        self.assertIn("수량 증가", report)
        self.assertIn("현재 TOP10", report)
        self.assertIn("주요 비중 변화", report)
        self.assertNotIn("비중 증가 상위 10", report)
        self.assertNotIn("비중 감소 상위 10", report)
        self.assertNotIn("변동폭 상위 10", report)

    def test_detailed_ai_sections_are_rendered(self) -> None:
        previous = pd.read_csv(ROOT_DIR / "snapshots" / "2026-03-27.csv", encoding="utf-8-sig")
        current = pd.read_csv(ROOT_DIR / "snapshots" / "2026-03-30.csv", encoding="utf-8-sig")
        compared = compare_holdings(current, previous)
        scenario = {
            "thesis": "시나리오 설명",
            "confidence": "medium",
            "implications": ["확인 1", "확인 2", "확인 3"],
        }
        ai_analysis = {
            "one_line_take": "한 줄 결론",
            "core_view": "핵심 해석",
            "manager_intent": "운용 의도",
            "what_changed_in_plain_english": ["변화 1", "변화 2", "변화 3", "변화 4"],
            "evidence_based_observations": [f"근거 {i}" for i in range(1, 6)],
            "portfolio_implications": [f"영향 {i}" for i in range(1, 5)],
            "base_case": scenario,
            "bull_case": scenario,
            "bear_case": scenario,
            "key_risks": [],
            "what_to_watch_next": [f"확인 {i}" for i in range(1, 6)],
            "watchlist": [],
            "data_limitations": ["한계 1", "한계 2"],
        }

        report = build_compare_report_html(compared, ai_analysis=ai_analysis)

        self.assertIn("해석 노트", report)
        self.assertIn("판단의 근거", report)
        self.assertIn("운용 관점", report)
        self.assertIn("분석 한계", report)
        self.assertNotIn("낙관 시나리오", report)

    def test_html_escapes_names_and_ai_text(self) -> None:
        data = valid_df()
        data.loc[0, "종목명"] = '<script>alert("x")</script>'
        result = compare_holdings(data, data)
        analysis = valid_analysis()
        analysis["core_view"] = "<img src=x onerror=alert(1)>"
        report = build_compare_report_html(result, ai_analysis=analysis)
        self.assertNotIn("<script>", report)
        self.assertNotIn("<img src=x", report)
        self.assertIn("&lt;script&gt;", report)
        self.assertNotIn("display:flex", report)
        self.assertNotIn("display:grid", report)

    def test_all_quantity_changes_are_shown_not_just_top10(self) -> None:
        data = pd.concat([valid_df(), valid_df().assign(
            asset_key=lambda d: d.asset_key + "-extra", 종목명=lambda d: d.종목명 + "-extra",
        )], ignore_index=True)
        current = data.copy()
        current["수량"] += 1
        report = build_compare_report_html(compare_holdings(current, data))
        for name in data["종목명"]:
            self.assertIn(name, report)
        self.assertIn("주식 20종목의 보유 내역", report)

    def test_editorial_layout_has_no_decorative_dashboard_cards(self) -> None:
        data = valid_df()
        result = compare_holdings(data, data)
        report = build_compare_report_html(result, sample=True, previous_label="2026-01-01", current_label="2026-01-02")
        self.assertIn("디자인 확인용 예시", report)
        self.assertIn("2026-01-01 → 2026-01-02", report)
        self.assertNotIn("border-radius", report)
        self.assertNotIn("box-shadow", report)
        self.assertNotIn("PORTFOLIO MONITOR", report)
        self.assertIn("예시 메일", build_compare_report_text(result, sample=True))

    def test_html_and_plain_text_show_same_ai_and_date(self) -> None:
        data = valid_df()
        compared = compare_holdings(data, data)
        analysis = {**valid_analysis(), "provider": "Gemini", "model": "gemini-4-hydrogen"}
        labels = {"previous_label": "2026-01-01", "current_label": "2026-01-02"}
        for output in [build_compare_report_html(compared, ai_analysis=analysis, **labels), build_compare_report_text(compared, ai_analysis=analysis, **labels)]:
            self.assertIn("gemini-4-hydrogen", output)
            self.assertIn("2026-01-01 → 2026-01-02", output)
            self.assertIn(analysis["core_view"], output)

    def test_payload_includes_dates_and_proportional_quantity_signal(self) -> None:
        data = valid_df()
        current = data.copy()
        current["수량"] *= 2
        payload = build_compare_ai_payload(compare_holdings(current, data), previous_label="before", current_label="after")
        self.assertEqual(payload["meta"]["previous_snapshot"], "before")
        self.assertEqual(payload["portfolio_stats"]["quantity_signals"]["median_existing_quantity_change_pct"], 100)


class AIProviderTests(unittest.TestCase):
    def test_hydrogen_request_uses_declared_schema_without_temperature(self) -> None:
        client = MagicMock()
        client.models.generate_content.return_value = SimpleNamespace(
            parsed=valid_analysis(), candidates=[SimpleNamespace(finish_reason=ai_analyzer.types.FinishReason.STOP)],
        )
        with patch.object(ai_analyzer, "GEMINI_THINKING_LEVEL", "medium"):
            ai_analyzer._call_gemini_once(client, "gemini-4-hydrogen", {})
        config = client.models.generate_content.call_args.kwargs["config"]
        self.assertIsNone(config.temperature)
        self.assertEqual(config.thinking_config.thinking_level.value.lower(), "medium")
        self.assertEqual(config.max_output_tokens, 16384)

    def test_gemini_truncated_output_is_not_accepted_even_if_parsed(self) -> None:
        client = MagicMock()
        client.models.generate_content.return_value = SimpleNamespace(
            parsed=valid_analysis(), candidates=[SimpleNamespace(finish_reason=ai_analyzer.types.FinishReason.MAX_TOKENS)],
        )
        with self.assertRaisesRegex(ValueError, "끝까지"):
            ai_analyzer._call_gemini_once(client, "gemini-4-hydrogen", {})

    def test_quiet_day_does_not_require_filler_lists(self) -> None:
        analysis = valid_analysis()
        analysis.update(evidence_based_observations=[], portfolio_implications=[], manager_intent="", key_risks=[], what_to_watch_next=[])
        self.assertIsNotNone(ai_analyzer.AnalysisResult.model_validate(analysis))

    def test_correct_quantity_fact_claims_pass(self) -> None:
        analysis = valid_analysis()
        analysis["quantity_claims"] = [{"asset_key": "A", "quantity_status": "bought", "previous_quantity": 10, "current_quantity": 11}]
        result = ai_analyzer.AnalysisResult.model_validate(analysis)
        payload = {"quantity_facts": [{"asset_key": "A", "quantity_status": "bought", "수량_prev": 10, "수량_today": 11}]}
        self.assertIs(ai_analyzer._validate_quantity_claims(result, payload), result)

    def test_ai_quantity_facts_reject_false_or_missing_claims(self) -> None:
        payload = {"quantity_facts": [{"asset_key": "A", "quantity_status": "bought", "수량_prev": 10, "수량_today": 11}]}
        for claims in [[], [{"asset_key": "A", "quantity_status": "sold", "previous_quantity": 10, "current_quantity": 11}],
                       [{"asset_key": "A", "quantity_status": "bought", "previous_quantity": 10, "current_quantity": 12}]]:
            with self.subTest(claims=claims):
                analysis = valid_analysis()
                analysis["quantity_claims"] = claims
                result = ai_analyzer.AnalysisResult.model_validate(analysis)
                with self.assertRaises(ValueError):
                    ai_analyzer._validate_quantity_claims(result, payload)

    def test_gemini_failure_uses_validated_glm_fallback(self) -> None:
        validated = ai_analyzer.AnalysisResult.model_validate(valid_analysis())
        with (
            patch.object(ai_analyzer, "GEMINI_API_KEY", "test-key"),
            patch.object(ai_analyzer.genai, "Client"),
            patch.object(ai_analyzer, "_call_with_retry", side_effect=ValueError("bad response")),
            patch.object(ai_analyzer, "_call_glm", return_value=validated) as glm,
        ):
            result = ai_analyzer.analyze_compare_payload({})
        glm.assert_called_once_with({})
        self.assertEqual(result["provider"], "GLM")

    def test_primary_success_does_not_call_fallback(self) -> None:
        validated = ai_analyzer.AnalysisResult.model_validate(valid_analysis())
        with (
            patch.object(ai_analyzer, "GEMINI_API_KEY", "test-key"),
            patch.object(ai_analyzer.genai, "Client"),
            patch.object(ai_analyzer, "_call_with_retry", return_value=validated),
            patch.object(ai_analyzer, "_call_glm") as glm,
        ):
            result = ai_analyzer.analyze_compare_payload({})
        glm.assert_not_called()
        self.assertEqual(result["provider"], "Gemini")

    def test_glm_invalid_or_truncated_json_is_rejected(self) -> None:
        for reason, content in [("length", "{}"), ("stop", "{}"), ("stop", "not json")]:
            with self.subTest(reason=reason, content=content):
                response = MagicMock(status_code=200)
                response.__enter__.return_value = response
                response.json.return_value = {"choices": [{"finish_reason": reason, "message": {"content": content}}]}
                with patch.object(ai_analyzer, "GLM_API_KEY", "test-key"), patch.object(ai_analyzer.requests, "post", return_value=response):
                    with self.assertRaises(ValueError):
                        ai_analyzer._call_glm({})

    def test_glm_failure_does_not_log_server_body(self) -> None:
        response = MagicMock(status_code=401)
        response.__enter__.return_value = response
        response.text = "private credential details"
        with patch.object(ai_analyzer, "GLM_API_KEY", "test-key"), patch.object(ai_analyzer.requests, "post", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "^GLM HTTP 401$"):
                ai_analyzer._call_glm({})


class FetcherTests(unittest.TestCase):
    def test_stream_size_limit_preserves_existing_file(self) -> None:
        with workspace_temp_dir() as temp_dir:
            path = temp_dir / "latest.xlsx"
            path.write_bytes(b"original")
            response = MagicMock()
            response.__enter__.return_value = response
            response.headers = {}
            response.iter_content.return_value = iter([b"012345", b"678901"])
            with patch.object(fetcher.requests, "get", return_value=response), patch.object(fetcher, "MAX_DOWNLOAD_SIZE_BYTES", 10):
                with self.assertRaises(RuntimeError):
                    fetcher.download_excel_with_retry(path, max_retries=1)
            self.assertEqual(path.read_bytes(), b"original")
            self.assertEqual(list(temp_dir.glob("*.tmp")), [])


class ManualPreviewTests(unittest.TestCase):
    def test_saved_analysis_requires_exact_fingerprints(self) -> None:
        with workspace_temp_dir() as temp_dir:
            path = temp_dir / "analysis.json"
            labels = {"previous_label": "before", "current_label": "after"}
            fingerprints = {"previous": "a", "current": "b"}
            saved = {"comparison": labels, "fingerprints": fingerprints,
                     "analysis": {**valid_analysis(), "provider": "Gemini", "model": "gemini-4-hydrogen"}}
            path.write_text(json.dumps(saved), encoding="utf-8")
            self.assertEqual(manual.load_saved_analysis(path, labels, fingerprints, {})["provider"], "Gemini")
            with self.assertRaisesRegex(ValueError, "내용"):
                manual.load_saved_analysis(path, labels, {"previous": "a", "current": "changed"}, {})


class EmailSenderTests(unittest.TestCase):
    def test_multipart_message_contains_html_and_plain_text(self) -> None:
        with (
            patch.object(email_sender, "SMTP_USER", "sender@example.com"),
            patch.object(email_sender, "SMTP_PASS", "test-password"),
            patch.object(email_sender, "TO_EMAIL", "recipient@example.com"),
            patch.object(email_sender.smtplib, "SMTP") as smtp,
        ):
            message_id = email_sender.send_html_email("Report", "<p>HTML</p>", "Plain text")
        arguments = smtp.return_value.__enter__.return_value.sendmail.call_args.args
        self.assertIn("multipart/alternative", arguments[2])
        self.assertIn("TIME ETF", arguments[2])
        self.assertIn(message_id, arguments[2])
        self.assertNotIn("test-password", arguments[2])


if __name__ == "__main__":
    unittest.main()
