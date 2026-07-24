from __future__ import annotations

import sys
import shutil
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent.parent
APP_DIR = ROOT_DIR / "app"
sys.path.insert(0, str(APP_DIR))
TEST_TEMP_ROOT = ROOT_DIR / "temp"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)

import snapshot_manager  # noqa: E402
import state_manager  # noqa: E402
import run_tracker_once  # noqa: E402
from compare import compare_holdings  # noqa: E402
from exceptions import StateCorruptionError  # noqa: E402
from reporter import build_compare_report_html  # noqa: E402
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
    def test_pending_report_is_retried_from_saved_snapshot_paths(self) -> None:
        with workspace_temp_dir() as temp_dir:
            previous_path = temp_dir / "previous.csv"
            current_path = temp_dir / "current.csv"
            previous_path.write_text("previous", encoding="utf-8")
            current_path.write_text("current", encoding="utf-8")

            state = state_manager.default_state()
            state.update({
                "pending_report_hash": "pending-hash",
                "pending_snapshot_path": str(current_path),
                "pending_previous_snapshot_path": str(previous_path),
            })

            with (
                patch.object(run_tracker_once, "send_report") as mocked_send,
                patch.object(run_tracker_once, "save_state") as mocked_save,
            ):
                retried = run_tracker_once.retry_pending_report_if_needed(state)

            self.assertTrue(retried)
            mocked_send.assert_called_once_with(previous_path, current_path)
            mocked_save.assert_called_once_with(state)
            self.assertEqual(state["last_reported_hash"], "pending-hash")
            self.assertIsNone(state["pending_report_hash"])


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

        self.assertIn("GEMINI ANALYSIS", report)
        self.assertIn("데이터로 확인된 근거", report)
        self.assertIn("포트폴리오 영향", report)
        self.assertIn("분석 한계", report)


if __name__ == "__main__":
    unittest.main()
