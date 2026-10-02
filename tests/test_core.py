from __future__ import annotations

import sys
import shutil
import json
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch, MagicMock
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
import ai_analyzer  # noqa: E402
import fetcher  # noqa: E402
from compare import compare_holdings, add_rank  # noqa: E402
from exceptions import StateCorruptionError, DataNotReadyError  # noqa: E402
from holdings_parser import load_holdings_excel  # noqa: E402
from reporter import build_compare_report_html, build_compare_ai_payload  # noqa: E402
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
    scenario = {"thesis": "가설", "confidence": "low", "implications": ["확인"] * 3}
    return {
        "quantity_claims": [],
        "one_line_take": "확인이 필요한 변화입니다.", "core_view": "해석", "manager_intent": "가설",
        "what_changed_in_plain_english": ["변화"] * 4,
        "evidence_based_observations": ["근거"] * 5,
        "portfolio_implications": ["영향"] * 4,
        "base_case": scenario, "bull_case": scenario, "bear_case": scenario,
        "key_risks": [{"level": "low", "issue": "위험", "evidence": "근거"}] * 4,
        "what_to_watch_next": ["확인"] * 5,
        "watchlist": [{"name": "관찰", "direction": "neutral", "reason": "근거", "next_check": "확인"}] * 5,
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
            data.to_csv(current_path, index=False, encoding="utf-8-sig")
            pending_hash = snapshot_manager.compute_snapshot_hash(data)

            state = state_manager.default_state()
            state.update({
                "pending_report_hash": pending_hash,
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

        self.assertIn("AI 상세 분석", report)
        self.assertIn("데이터로 확인된 근거", report)
        self.assertIn("포트폴리오 영향", report)
        self.assertIn("분석 한계", report)

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
            self.assertIn(f">{name}</", report)
        self.assertIn("수량 증가 · 20종목", report)

    def test_payload_includes_dates_and_proportional_quantity_signal(self) -> None:
        data = valid_df()
        current = data.copy()
        current["수량"] *= 2
        payload = build_compare_ai_payload(compare_holdings(current, data), previous_label="before", current_label="after")
        self.assertEqual(payload["meta"]["previous_snapshot"], "before")
        self.assertEqual(payload["portfolio_stats"]["quantity_signals"]["median_existing_quantity_change_pct"], 100)


class AIProviderTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
