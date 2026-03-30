from __future__ import annotations

import html
import json
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

ENABLE_TRADINGVIEW_LINKS = True
ENABLE_TOSS_LINKS = False

STATUS_TEXT_MAP = {
    "new": "신규 편입",
    "removed": "편출",
    "increased": "비중 증가",
    "decreased": "비중 감소",
    "unchanged": "변동 없음",
    "increase": "비중 증가",
    "decrease": "비중 감소",
}

DISPLAY_RENAME_MAP = {
    "종목명": "종목명",
    "비중(%)_prev": "이전 비중",
    "비중(%)_today": "현재 비중",
    "diff_pctp": "비중 변화",
    "rank_prev": "이전 순위",
    "rank_today": "현재 순위",
    "asset_type": "자산 유형",
    "status": "변화 유형",
}


def _safe_float(value: object) -> float:
    if pd.isna(value):
        return 0.0
    return float(value)


def _safe_int_or_none(value: object) -> int | None:
    if pd.isna(value):
        return None
    try:
        return int(float(value))
    except Exception:
        return None


def _fmt_weight(value: object) -> str:
    return f"{_safe_float(value):.2f}%"


def _fmt_diff(value: object) -> str:
    v = _safe_float(value)
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.2f}%p"


def _fmt_rank(value: object) -> str:
    rank = _safe_int_or_none(value)
    if rank is None or rank >= 999:
        return "-"
    return str(rank)


def _normalize_status_text(value: object) -> str:
    return STATUS_TEXT_MAP.get(str(value).strip(), str(value).strip())


def _fmt_rank_change_text(rank_prev: object, rank_today: object) -> str:
    prev_rank = _safe_int_or_none(rank_prev)
    today_rank = _safe_int_or_none(rank_today)

    prev_in_top10 = prev_rank is not None and prev_rank <= 10
    today_in_top10 = today_rank is not None and today_rank <= 10

    if not prev_in_top10 and today_in_top10:
        return "신규 진입"
    if prev_in_top10 and not today_in_top10:
        return "TOP10 이탈"
    if prev_in_top10 and today_in_top10:
        diff = prev_rank - today_rank
        if diff > 0:
            return f"▲{diff}"
        if diff < 0:
            return f"▼{abs(diff)}"
        return "-"
    return "-"


def _section_title(title: str) -> str:
    return f"\n{'=' * 12} {title} {'=' * 12}"


def _top_n(df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    return df.head(n).copy()


def _prepare_stock_only(compared: pd.DataFrame) -> pd.DataFrame:
    return compared[compared["asset_type"] == "stock"].copy()


def _prepare_non_stock(compared: pd.DataFrame) -> pd.DataFrame:
    return compared[compared["asset_type"] != "stock"].copy()


def _prepare_top10_rank_changes(stock_df: pd.DataFrame) -> pd.DataFrame:
    top10_related = stock_df[
        (stock_df["rank_today"] <= 10) | (stock_df["rank_prev"] <= 10)
    ].copy()

    if top10_related.empty:
        return top10_related

    top10_related["sort_today"] = top10_related["rank_today"].apply(
        lambda x: 999 if pd.isna(x) else int(float(x))
    )
    top10_related["sort_prev"] = top10_related["rank_prev"].apply(
        lambda x: 999 if pd.isna(x) else int(float(x))
    )

    top10_related = top10_related.sort_values(
        by=["sort_today", "sort_prev", "종목명"],
        ascending=[True, True, True],
    ).copy()

    return top10_related.drop(columns=["sort_today", "sort_prev"])


def _prepare_biggest_absolute_moves(stock_df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    data = stock_df.copy()
    data["abs_diff"] = data["diff_pctp"].abs()
    data = data.sort_values("abs_diff", ascending=False)
    return data.head(n).drop(columns=["abs_diff"])


def _summary_lines(compared: pd.DataFrame) -> list[str]:
    stock_df = _prepare_stock_only(compared)
    non_stock_df = _prepare_non_stock(compared)

    new_count = int((stock_df["status"] == "new").sum())
    removed_count = int((stock_df["status"] == "removed").sum())
    increased_count = int((stock_df["status"] == "increased").sum())
    decreased_count = int((stock_df["status"] == "decreased").sum())

    gainers = stock_df[stock_df["status"] == "increased"].sort_values("diff_pctp", ascending=False)
    losers = stock_df[stock_df["status"] == "decreased"].sort_values("diff_pctp", ascending=True)

    top_gainers = ", ".join(gainers["종목명"].head(3).tolist()) if not gainers.empty else "없음"
    top_losers = ", ".join(losers["종목명"].head(3).tolist()) if not losers.empty else "없음"

    non_stock_changed = non_stock_df[non_stock_df["status"] != "unchanged"]

    summary = [
        f"주식 기준 신규 편입은 {new_count}종목, 편출은 {removed_count}종목입니다.",
        f"주식 기준 비중 증가 종목은 {increased_count}개, 비중 감소 종목은 {decreased_count}개입니다.",
        f"주요 비중 확대 종목은 {top_gainers}입니다.",
        f"주요 비중 축소 종목은 {top_losers}입니다.",
    ]

    if not non_stock_changed.empty:
        changed_names = ", ".join(non_stock_changed["종목명"].head(5).tolist())
        summary.append(f"주식 외 자산에서는 {changed_names}의 변화가 확인되었습니다.")

    return summary


def _build_sections(compared: pd.DataFrame) -> dict[str, pd.DataFrame | list[str]]:
    stock_df = _prepare_stock_only(compared)
    non_stock_df = _prepare_non_stock(compared)

    increased = stock_df[stock_df["status"] == "increased"].sort_values("diff_pctp", ascending=False)
    decreased = stock_df[stock_df["status"] == "decreased"].sort_values("diff_pctp", ascending=True)
    new_items = stock_df[stock_df["status"] == "new"].sort_values("비중(%)_today", ascending=False)
    removed_items = stock_df[stock_df["status"] == "removed"].sort_values("비중(%)_prev", ascending=False)

    top10_changes = _prepare_top10_rank_changes(stock_df)
    biggest_moves = _prepare_biggest_absolute_moves(stock_df, n=10)

    non_stock_changes = non_stock_df[non_stock_df["status"] != "unchanged"].copy()
    non_stock_changes = non_stock_changes.sort_values("diff_pctp", ascending=False)

    return {
        "summary": _summary_lines(compared),
        "increased": _top_n(increased, 10),
        "decreased": _top_n(decreased, 10),
        "new_items": _top_n(new_items, 10),
        "removed_items": _top_n(removed_items, 10),
        "biggest_moves": _top_n(biggest_moves, 10),
        "top10_changes": _top_n(top10_changes, 10),
        "non_stock_changes": _top_n(non_stock_changes, 10),
    }


def _select_and_format(
    raw_df: pd.DataFrame,
    visible_cols: list[str],
    rename_map: dict[str, str] | None = None,
) -> pd.DataFrame:
    rename_map = rename_map or {}
    df = raw_df.copy()

    display_cols = [c for c in visible_cols if c in df.columns]
    df = df[display_cols].copy()

    for col in df.columns:
        if col in {"비중(%)_prev", "비중(%)_today", "비중(%)"}:
            df[col] = df[col].map(_fmt_weight)
        elif col == "diff_pctp":
            df[col] = df[col].map(_fmt_diff)
        elif col in {"rank_prev", "rank_today"}:
            df[col] = df[col].map(_fmt_rank)
        elif col in {"status", "변화유형"}:
            df[col] = df[col].map(_normalize_status_text)

    if {"rank_prev", "rank_today"}.issubset(raw_df.columns):
        df["순위 변화"] = [
            _fmt_rank_change_text(rp, rt)
            for rp, rt in zip(raw_df["rank_prev"], raw_df["rank_today"])
        ]

    final_rename_map = DISPLAY_RENAME_MAP.copy()
    final_rename_map.update(rename_map)
    return df.rename(columns=final_rename_map)


def _table_to_text(df: pd.DataFrame, empty_message: str = "없음") -> str:
    if df.empty:
        return empty_message
    return df.to_string(index=False)


def _extract_ticker_from_key(asset_key: str) -> str | None:
    if not asset_key:
        return None
    asset_key = str(asset_key).strip().upper()
    match = re.match(r"^([A-Z0-9.\-]+)\s+US\s+EQUITY$", asset_key)
    return match.group(1) if match else None


def _build_tradingview_url(ticker: str) -> str:
    return f"https://www.tradingview.com/symbols/NASDAQ-{ticker}/"


def _build_tossinvest_url(ticker: str) -> str:
    return f"https://tossinvest.com/stocks/us/{ticker}"


def _build_name_links_html(raw_row: pd.Series) -> str:
    name = html.escape(str(raw_row.get("종목명", "")))
    asset_type = str(raw_row.get("asset_type", "")).strip().lower()
    asset_key = str(raw_row.get("asset_key", "")).strip()

    if asset_type != "stock":
        return name

    ticker = _extract_ticker_from_key(asset_key)
    if not ticker:
        return name

    parts = [f'<span style="font-weight:600;color:#0f172a;">{name}</span>']

    if ENABLE_TRADINGVIEW_LINKS:
        tv_url = _build_tradingview_url(ticker)
        parts.append(
            f'<a href="{html.escape(tv_url)}" target="_blank" '
            f'style="margin-left:8px;font-size:12px;color:#2563eb;text-decoration:none;">TradingView</a>'
        )

    if ENABLE_TOSS_LINKS:
        toss_url = _build_tossinvest_url(ticker)
        parts.append(
            f'<a href="{html.escape(toss_url)}" target="_blank" '
            f'style="margin-left:6px;font-size:12px;color:#0f766e;text-decoration:none;">Toss</a>'
        )

    return "".join(parts)


def _rank_change_badge_html(text: str) -> str:
    escaped = html.escape(text)
    if text.startswith("▲"):
        color, bg = "#d1242f", "#fff1f3"
    elif text.startswith("▼"):
        color, bg = "#0969da", "#eff6ff"
    elif text == "신규 진입":
        color, bg = "#1a7f37", "#edf7ed"
    elif text == "TOP10 이탈":
        color, bg = "#9a6700", "#fff8c5"
    else:
        color, bg = "#57606a", "#f6f8fa"

    return (
        f'<span style="display:inline-block;padding:4px 8px;border-radius:999px;'
        f'font-weight:600;font-size:12px;color:{color};background:{bg};">{escaped}</span>'
    )


def _value_color_html(value: str) -> str:
    if value.startswith("+"):
        return f'<span style="color:#d1242f;font-weight:700;">{html.escape(value)}</span>'
    if value.startswith("-"):
        return f'<span style="color:#0969da;font-weight:700;">{html.escape(value)}</span>'
    return html.escape(value)


def _status_badge_html(text: str) -> str:
    color_map = {
        "신규 편입": ("#1a7f37", "#edf7ed"),
        "편출": ("#9a6700", "#fff8c5"),
        "비중 증가": ("#d1242f", "#fff1f3"),
        "비중 감소": ("#0969da", "#eff6ff"),
        "변동 없음": ("#57606a", "#f6f8fa"),
    }
    color, bg = color_map.get(text, ("#57606a", "#f6f8fa"))
    return (
        f'<span style="display:inline-block;padding:4px 8px;border-radius:999px;'
        f'font-weight:600;font-size:12px;color:{color};background:{bg};">{html.escape(text)}</span>'
    )


def _dataframe_to_html_table(
    display_df: pd.DataFrame,
    raw_df: pd.DataFrame,
    empty_message: str = "없음",
) -> str:
    if display_df.empty:
        return (
            '<div style="padding:14px 16px;border:1px solid #e5e7eb;border-radius:12px;'
            'background:#fafbfc;color:#6b7280;margin-top:10px;">'
            f'{html.escape(empty_message)}'
            "</div>"
        )

    header_html = "".join(
        f'<th style="padding:12px 14px;background:#f8fafc;border-bottom:1px solid #e5e7eb;'
        f'font-size:13px;font-weight:700;color:#334155;text-align:left;white-space:nowrap;">{html.escape(str(col))}</th>'
        for col in display_df.columns
    )

    rows_html = []
    for idx, row in display_df.iterrows():
        raw_row = raw_df.loc[idx]
        cells_html = []

        for col, val in zip(display_df.columns, row.tolist()):
            text = "" if pd.isna(val) else str(val)

            if col == "종목명":
                rendered = _build_name_links_html(raw_row)
            elif col == "순위 변화":
                rendered = _rank_change_badge_html(text)
            elif col == "변화 유형":
                rendered = _status_badge_html(text)
            elif col == "비중 변화":
                rendered = _value_color_html(text)
            else:
                rendered = html.escape(text)

            cells_html.append(
                f'<td style="padding:12px 14px;border-bottom:1px solid #eef2f7;'
                f'font-size:13px;color:#111827;vertical-align:top;">{rendered}</td>'
            )

        rows_html.append(f"<tr>{''.join(cells_html)}</tr>")

    return f"""
    <div style="overflow-x:auto;margin-top:10px;">
      <table style="width:100%;border-collapse:separate;border-spacing:0;background:#ffffff;
                    border:1px solid #e5e7eb;border-radius:14px;overflow:hidden;">
        <thead>
          <tr>{header_html}</tr>
        </thead>
        <tbody>
          {''.join(rows_html)}
        </tbody>
      </table>
    </div>
    """


def _section_card_html(title: str, subtitle: str, table_html: str) -> str:
    return f"""
    <section style="margin-top:22px;padding:20px 20px 18px 20px;background:#ffffff;
                    border:1px solid #e5e7eb;border-radius:18px;box-shadow:0 1px 2px rgba(16,24,40,0.04);">
      <div style="margin-bottom:12px;">
        <h2 style="margin:0;font-size:18px;font-weight:700;color:#111827;">{html.escape(title)}</h2>
        <p style="margin:6px 0 0 0;font-size:13px;color:#6b7280;">{html.escape(subtitle)}</p>
      </div>
      {table_html}
    </section>
    """


def _kpi_cards_html(compared: pd.DataFrame) -> str:
    stock_df = _prepare_stock_only(compared)

    cards = [
        ("신규 편입", int((stock_df["status"] == "new").sum()), "#1a7f37", "#edf7ed"),
        ("편출", int((stock_df["status"] == "removed").sum()), "#9a6700", "#fff8c5"),
        ("비중 증가", int((stock_df["status"] == "increased").sum()), "#d1242f", "#fff1f3"),
        ("비중 감소", int((stock_df["status"] == "decreased").sum()), "#0969da", "#eff6ff"),
    ]

    html_parts = []
    for label, value, color, bg in cards:
        html_parts.append(
            f"""
            <div style="padding:16px 18px;background:#ffffff;border:1px solid #e5e7eb;border-radius:16px;
                        box-shadow:0 1px 2px rgba(16,24,40,0.04);">
              <div style="font-size:12px;font-weight:700;color:#6b7280;margin-bottom:8px;">{html.escape(label)}</div>
              <div style="display:flex;align-items:end;gap:8px;">
                <div style="font-size:28px;font-weight:800;color:{color};line-height:1;">{value}</div>
                <div style="padding:4px 8px;border-radius:999px;background:{bg};color:{color};
                            font-size:12px;font-weight:700;">종목</div>
              </div>
            </div>
            """
        )
    return "".join(html_parts)


def _top10_concentration_html(compared: pd.DataFrame) -> str:
    stock_df = _prepare_stock_only(compared).copy()
    if stock_df.empty:
        return ""

    top10_today = stock_df.loc[stock_df["rank_today"] <= 10, "비중(%)_today"].fillna(0).sum()
    top10_prev = stock_df.loc[stock_df["rank_prev"] <= 10, "비중(%)_prev"].fillna(0).sum()
    diff = top10_today - top10_prev

    diff_text = _fmt_diff(diff)
    diff_color = "#d1242f" if diff > 0 else "#0969da" if diff < 0 else "#57606a"

    return f"""
    <div style="margin-top:14px;padding:16px 18px;background:#ffffff;border:1px solid #e5e7eb;
                border-radius:16px;box-shadow:0 1px 2px rgba(16,24,40,0.04);">
      <div style="font-size:12px;font-weight:700;color:#6b7280;margin-bottom:8px;">TOP10 집중도</div>
      <div style="font-size:14px;color:#111827;line-height:1.7;">
        이전 TOP10 비중 합계는 <strong>{_fmt_weight(top10_prev)}</strong>,
        현재 TOP10 비중 합계는 <strong>{_fmt_weight(top10_today)}</strong>입니다.
        변화는 <strong style="color:{diff_color};">{html.escape(diff_text)}</strong>입니다.
      </div>
    </div>
    """


def _get_report_generated_at(report_generated_at: str | None = None) -> str:
    if report_generated_at:
        return report_generated_at
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    return now_kst.strftime("%Y-%m-%d %H:%M:%S KST")


def _to_basic_python(value: object) -> object:
    if pd.isna(value):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        if isinstance(value, pd.Timestamp):
            return value.isoformat()
    except Exception:
        pass
    try:
        return value.item()
    except Exception:
        return str(value)


def _records_from_df(df: pd.DataFrame, cols: list[str], limit: int | None = None) -> list[dict[str, object]]:
    available = [c for c in cols if c in df.columns]
    sub = df[available].copy()
    if limit is not None:
        sub = sub.head(limit)

    records: list[dict[str, object]] = []
    for _, row in sub.iterrows():
        records.append({col: _to_basic_python(row[col]) for col in available})
    return records


def _portfolio_level_stats(compared: pd.DataFrame) -> dict[str, object]:
    stock_df = _prepare_stock_only(compared).copy()
    non_stock_df = _prepare_non_stock(compared).copy()

    increased_count = int((stock_df["status"] == "increased").sum())
    decreased_count = int((stock_df["status"] == "decreased").sum())
    new_count = int((stock_df["status"] == "new").sum())
    removed_count = int((stock_df["status"] == "removed").sum())
    unchanged_count = int((stock_df["status"] == "unchanged").sum())

    total_abs_weight_change = float(stock_df["diff_pctp"].abs().sum()) if not stock_df.empty else 0.0
    avg_abs_weight_change = float(stock_df["diff_pctp"].abs().mean()) if not stock_df.empty else 0.0

    top5_prev = float(stock_df.loc[stock_df["rank_prev"] <= 5, "비중(%)_prev"].fillna(0).sum())
    top5_today = float(stock_df.loc[stock_df["rank_today"] <= 5, "비중(%)_today"].fillna(0).sum())
    top10_prev = float(stock_df.loc[stock_df["rank_prev"] <= 10, "비중(%)_prev"].fillna(0).sum())
    top10_today = float(stock_df.loc[stock_df["rank_today"] <= 10, "비중(%)_today"].fillna(0).sum())

    outside_top10_prev = float(stock_df.loc[stock_df["rank_prev"] > 10, "비중(%)_prev"].fillna(0).sum())
    outside_top10_today = float(stock_df.loc[stock_df["rank_today"] > 10, "비중(%)_today"].fillna(0).sum())

    new_weight_sum = float(stock_df.loc[stock_df["status"] == "new", "비중(%)_today"].fillna(0).sum())
    removed_weight_sum = float(stock_df.loc[stock_df["status"] == "removed", "비중(%)_prev"].fillna(0).sum())

    stock_prev_sum = float(stock_df["비중(%)_prev"].fillna(0).sum())
    stock_today_sum = float(stock_df["비중(%)_today"].fillna(0).sum())

    non_stock_prev_sum = float(non_stock_df["비중(%)_prev"].fillna(0).sum())
    non_stock_today_sum = float(non_stock_df["비중(%)_today"].fillna(0).sum())

    cash_prev_sum = float(non_stock_df.loc[non_stock_df["asset_type"] == "cash", "비중(%)_prev"].fillna(0).sum())
    cash_today_sum = float(non_stock_df.loc[non_stock_df["asset_type"] == "cash", "비중(%)_today"].fillna(0).sum())

    futures_prev_sum = float(non_stock_df.loc[non_stock_df["asset_type"] == "futures", "비중(%)_prev"].fillna(0).sum())
    futures_today_sum = float(non_stock_df.loc[non_stock_df["asset_type"] == "futures", "비중(%)_today"].fillna(0).sum())

    return {
        "stock_counts": {
            "increased": increased_count,
            "decreased": decreased_count,
            "new": new_count,
            "removed": removed_count,
            "unchanged": unchanged_count,
            "total_stock_names": int(len(stock_df)),
        },
        "breadth_and_turnover": {
            "total_absolute_weight_change_pctp": round(total_abs_weight_change, 6),
            "average_absolute_weight_change_pctp": round(avg_abs_weight_change, 6),
            "new_entries_total_weight_pct": round(new_weight_sum, 6),
            "removed_entries_total_weight_pct": round(removed_weight_sum, 6),
        },
        "concentration": {
            "top5_prev_pct": round(top5_prev, 6),
            "top5_today_pct": round(top5_today, 6),
            "top5_diff_pctp": round(top5_today - top5_prev, 6),
            "top10_prev_pct": round(top10_prev, 6),
            "top10_today_pct": round(top10_today, 6),
            "top10_diff_pctp": round(top10_today - top10_prev, 6),
            "outside_top10_prev_pct": round(outside_top10_prev, 6),
            "outside_top10_today_pct": round(outside_top10_today, 6),
            "outside_top10_diff_pctp": round(outside_top10_today - outside_top10_prev, 6),
        },
        "asset_mix": {
            "stock_prev_pct": round(stock_prev_sum, 6),
            "stock_today_pct": round(stock_today_sum, 6),
            "stock_diff_pctp": round(stock_today_sum - stock_prev_sum, 6),
            "non_stock_prev_pct": round(non_stock_prev_sum, 6),
            "non_stock_today_pct": round(non_stock_today_sum, 6),
            "non_stock_diff_pctp": round(non_stock_today_sum - non_stock_prev_sum, 6),
            "cash_prev_pct": round(cash_prev_sum, 6),
            "cash_today_pct": round(cash_today_sum, 6),
            "cash_diff_pctp": round(cash_today_sum - cash_prev_sum, 6),
            "futures_prev_pct": round(futures_prev_sum, 6),
            "futures_today_pct": round(futures_today_sum, 6),
            "futures_diff_pctp": round(futures_today_sum - futures_prev_sum, 6),
        },
    }


def build_compare_ai_payload(
    compared: pd.DataFrame,
    report_generated_at: str | None = None,
) -> dict[str, Any]:
    sections = _build_sections(compared)
    stock_df = _prepare_stock_only(compared).copy()
    non_stock_df = _prepare_non_stock(compared).copy()
    generated_at = _get_report_generated_at(report_generated_at)

    all_changes_cols = [
        "asset_key",
        "종목명",
        "asset_type",
        "비중(%)_prev",
        "비중(%)_today",
        "diff_pctp",
        "rank_prev",
        "rank_today",
        "status",
    ]

    stock_all_changes_positive = stock_df.sort_values(
        by=["diff_pctp", "비중(%)_today"],
        ascending=[False, False],
    ).copy()

    stock_all_changes_negative = stock_df.sort_values(
        by=["diff_pctp", "비중(%)_today"],
        ascending=[True, False],
    ).copy()

    rank_changes_all = stock_df[
        (stock_df["rank_prev"] != stock_df["rank_today"]) |
        (stock_df["status"].isin(["new", "removed"]))
    ].copy()

    rank_changes_all = rank_changes_all.sort_values(
        by=["rank_today", "rank_prev", "종목명"],
        ascending=[True, True, True],
    )

    return {
        "meta": {
            "report_generated_at": generated_at,
            "analysis_scope": "전일 대비 ETF 구성 종목 변화",
            "notes": [
                "비중 변화는 percentage point 기준이다.",
                "status는 new, removed, increased, decreased, unchanged 중 하나다.",
                "rank_prev / rank_today의 큰 값은 순위권 밖을 의미할 수 있다.",
                "이 payload는 HTML 요약보다 더 풍부한 전체 포트폴리오 변화를 AI가 해석하도록 설계되었다.",
            ],
        },
        "summary": sections["summary"],
        "portfolio_stats": _portfolio_level_stats(compared),
        "headline_tables": {
            "top_gainers": _records_from_df(
                sections["increased"],
                ["종목명", "asset_key", "비중(%)_prev", "비중(%)_today", "diff_pctp", "rank_prev", "rank_today"],
                limit=10,
            ),
            "top_losers": _records_from_df(
                sections["decreased"],
                ["종목명", "asset_key", "비중(%)_prev", "비중(%)_today", "diff_pctp", "rank_prev", "rank_today"],
                limit=10,
            ),
            "new_items": _records_from_df(
                sections["new_items"],
                ["종목명", "asset_key", "비중(%)_today", "rank_today"],
                limit=10,
            ),
            "removed_items": _records_from_df(
                sections["removed_items"],
                ["종목명", "asset_key", "비중(%)_prev", "rank_prev"],
                limit=10,
            ),
            "top10_changes": _records_from_df(
                sections["top10_changes"],
                ["종목명", "asset_key", "비중(%)_prev", "비중(%)_today", "rank_prev", "rank_today", "status"],
                limit=10,
            ),
            "non_stock_changes": _records_from_df(
                sections["non_stock_changes"],
                ["종목명", "asset_key", "asset_type", "비중(%)_prev", "비중(%)_today", "diff_pctp", "status"],
                limit=10,
            ),
        },
        "full_universe": {
            "all_stock_changes_sorted_positive": _records_from_df(
                stock_all_changes_positive,
                all_changes_cols,
                limit=None,
            ),
            "all_stock_changes_sorted_negative": _records_from_df(
                stock_all_changes_negative,
                all_changes_cols,
                limit=None,
            ),
            "all_non_stock_changes": _records_from_df(
                non_stock_df.sort_values(by=["diff_pctp", "종목명"], ascending=[False, True]),
                all_changes_cols,
                limit=None,
            ),
            "all_rank_changes": _records_from_df(
                rank_changes_all,
                all_changes_cols,
                limit=None,
            ),
        },
        "analysis_hints": {
            "what_to_focus_on": [
                "상위 비중 종목의 집중도 변화",
                "신규 편입 종목이 단순 추가인지, 상위권 진입까지 동반하는 공격적 편입인지",
                "감소 종목이 몇 개 종목에 집중되는지, 아니면 전반적 디레이킹인지",
                "현금 및 선물 비중 변화가 위험관리 신호인지",
                "반도체, AI 인프라, 우주항공 등 특정 테마 로테이션이 보이는지",
            ],
            "desired_output_style": [
                "단순 재진술보다 해석 중심",
                "가격 단정보다 시나리오 중심",
                "운용 의도 가설 제시",
                "무효화 조건과 후속 확인 포인트 포함",
            ],
        },
    }


def build_compare_report_text(
    compared: pd.DataFrame,
    report_generated_at: str | None = None,
) -> str:
    sections = _build_sections(compared)
    generated_at = _get_report_generated_at(report_generated_at)
    lines: list[str] = []

    section_specs = [
        ("비중 증가 상위 10", sections["increased"], ["종목명", "비중(%)_prev", "비중(%)_today", "diff_pctp"], {}),
        ("비중 감소 상위 10", sections["decreased"], ["종목명", "비중(%)_prev", "비중(%)_today", "diff_pctp"], {}),
        ("신규 편입", sections["new_items"], ["종목명", "비중(%)_today"], {}),
        ("편출", sections["removed_items"], ["종목명", "비중(%)_prev"], {}),
        ("변동폭 상위 10", sections["biggest_moves"], ["종목명", "비중(%)_prev", "비중(%)_today", "diff_pctp", "status"], {"status": "변화 유형"}),
        ("TOP10 순위 변화", sections["top10_changes"], ["종목명", "rank_prev", "rank_today", "비중(%)_prev", "비중(%)_today"], {}),
        ("주식 외 자산 변화", sections["non_stock_changes"], ["종목명", "asset_type", "비중(%)_prev", "비중(%)_today", "diff_pctp", "status"], {"asset_type": "자산 유형", "status": "변화 유형"}),
    ]

    lines.append(_section_title("리포트 정보"))
    lines.append(f"- 리포트 생성 시각: {generated_at}")

    lines.append(_section_title("요약"))
    for line in sections["summary"]:
        lines.append(f"- {line}")

    for title, raw_df, cols, rename_map in section_specs:
        lines.append(_section_title(title))
        display_df = _select_and_format(raw_df, cols, rename_map)
        lines.append(_table_to_text(display_df))

    return "\n".join(lines)


def _ai_confidence_badge(confidence: str) -> str:
    mapping = {
        "high": ("높음", "#1a7f37", "#edf7ed"),
        "medium": ("보통", "#9a6700", "#fff8c5"),
        "low": ("낮음", "#0969da", "#eff6ff"),
    }
    label, color, bg = mapping.get(str(confidence).lower(), ("미정", "#57606a", "#f6f8fa"))
    return (
        f'<span style="display:inline-block;padding:4px 8px;border-radius:999px;'
        f'font-size:12px;font-weight:700;color:{color};background:{bg};">{label}</span>'
    )


def _ai_direction_badge(direction: str) -> str:
    mapping = {
        "positive": ("긍정", "#1a7f37", "#edf7ed"),
        "negative": ("부정", "#d1242f", "#fff1f3"),
        "neutral": ("중립", "#57606a", "#f6f8fa"),
    }
    label, color, bg = mapping.get(str(direction).lower(), ("중립", "#57606a", "#f6f8fa"))
    return (
        f'<span style="display:inline-block;padding:4px 8px;border-radius:999px;'
        f'font-size:12px;font-weight:700;color:{color};background:{bg};">{label}</span>'
    )


def _ai_risk_badge(level: str) -> str:
    mapping = {
        "high": ("높음", "#d1242f", "#fff1f3"),
        "medium": ("보통", "#9a6700", "#fff8c5"),
        "low": ("낮음", "#0969da", "#eff6ff"),
    }
    label, color, bg = mapping.get(str(level).lower(), ("미정", "#57606a", "#f6f8fa"))
    return (
        f'<span style="display:inline-block;padding:4px 8px;border-radius:999px;'
        f'font-size:12px;font-weight:700;color:{color};background:{bg};">{label}</span>'
    )


def _simple_text_card_html(title: str, body: str, subtitle: str = "") -> str:
    subtitle_html = (
        f'<p style="margin:6px 0 0 0;font-size:13px;color:#6b7280;">{html.escape(subtitle)}</p>'
        if subtitle else ""
    )
    return f"""
    <div style="padding:20px;background:#ffffff;border:1px solid #e5e7eb;border-radius:18px;
                box-shadow:0 1px 2px rgba(16,24,40,0.04);">
      <div style="margin-bottom:12px;">
        <h3 style="margin:0;font-size:18px;font-weight:700;color:#111827;">{html.escape(title)}</h3>
        {subtitle_html}
      </div>
      <p style="margin:0;font-size:14px;line-height:1.8;color:#111827;">{html.escape(body)}</p>
    </div>
    """


def _simple_list_card_html(title: str, items: list[str], subtitle: str = "") -> str:
    subtitle_html = (
        f'<p style="margin:6px 0 0 0;font-size:13px;color:#6b7280;">{html.escape(subtitle)}</p>'
        if subtitle else ""
    )
    if not items:
        body_html = '<div style="color:#6b7280;font-size:14px;">없음</div>'
    else:
        lis = "".join(f'<li style="margin:8px 0;">{html.escape(str(item))}</li>' for item in items)
        body_html = f'<ul style="margin:0;padding-left:18px;color:#111827;font-size:14px;line-height:1.8;">{lis}</ul>'

    return f"""
    <div style="padding:20px;background:#ffffff;border:1px solid #e5e7eb;border-radius:18px;
                box-shadow:0 1px 2px rgba(16,24,40,0.04);">
      <div style="margin-bottom:12px;">
        <h3 style="margin:0;font-size:18px;font-weight:700;color:#111827;">{html.escape(title)}</h3>
        {subtitle_html}
      </div>
      {body_html}
    </div>
    """


def _scenario_card_html(title: str, scenario: dict[str, Any]) -> str:
    thesis = str(scenario.get("thesis", ""))
    confidence = str(scenario.get("confidence", ""))
    implications = [str(x) for x in (scenario.get("implications", []) or [])]

    lis = "".join(f'<li style="margin:8px 0;">{html.escape(item)}</li>' for item in implications)

    return f"""
    <div style="padding:18px;background:#ffffff;border:1px solid #e5e7eb;border-radius:18px;
                box-shadow:0 1px 2px rgba(16,24,40,0.04);">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:10px;">
        <h4 style="margin:0;font-size:16px;font-weight:700;color:#111827;">{html.escape(title)}</h4>
        {_ai_confidence_badge(confidence)}
      </div>
      <p style="margin:0 0 12px 0;font-size:14px;line-height:1.8;color:#111827;">{html.escape(thesis)}</p>
      <div style="font-size:12px;font-weight:700;color:#6b7280;margin-bottom:8px;">시사점</div>
      <ul style="margin:0;padding-left:18px;color:#111827;font-size:14px;line-height:1.8;">
        {lis}
      </ul>
    </div>
    """


def _risk_cards_html(risks: list[dict[str, Any]]) -> str:
    if not risks:
        return '<div style="color:#6b7280;font-size:14px;">없음</div>'

    blocks = []
    for item in risks:
        level = str(item.get("level", ""))
        issue = str(item.get("issue", ""))
        evidence = str(item.get("evidence", ""))

        blocks.append(
            f"""
            <div style="padding:16px;background:#ffffff;border:1px solid #e5e7eb;border-radius:16px;">
              <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:10px;">
                <div style="font-size:15px;font-weight:700;color:#111827;">{html.escape(issue)}</div>
                {_ai_risk_badge(level)}
              </div>
              <div style="font-size:13px;color:#374151;line-height:1.7;">
                <strong>근거:</strong> {html.escape(evidence)}
              </div>
            </div>
            """
        )
    return "".join(blocks)


def _watchlist_cards_html(items: list[dict[str, Any]]) -> str:
    if not items:
        return '<div style="color:#6b7280;font-size:14px;">없음</div>'

    blocks = []
    for item in items:
        name = str(item.get("name", ""))
        direction = str(item.get("direction", "neutral"))
        reason = str(item.get("reason", ""))
        next_check = str(item.get("next_check", ""))

        blocks.append(
            f"""
            <div style="padding:16px;background:#ffffff;border:1px solid #e5e7eb;border-radius:16px;">
              <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:10px;">
                <div style="font-size:15px;font-weight:700;color:#111827;">{html.escape(name)}</div>
                {_ai_direction_badge(direction)}
              </div>
              <div style="font-size:13px;color:#374151;line-height:1.7;">
                <div><strong>이유:</strong> {html.escape(reason)}</div>
                <div style="margin-top:6px;"><strong>다음 확인:</strong> {html.escape(next_check)}</div>
              </div>
            </div>
            """
        )
    return "".join(blocks)


def _build_ai_analysis_section_html(ai_analysis: dict[str, Any] | None) -> str:
    if not ai_analysis:
        return ""

    one_line_take = str(ai_analysis.get("one_line_take", ""))
    core_view = str(ai_analysis.get("core_view", ""))
    manager_intent = str(ai_analysis.get("manager_intent", ""))

    changed_points = [str(x) for x in (ai_analysis.get("what_changed_in_plain_english", []) or [])]
    next_checks = [str(x) for x in (ai_analysis.get("what_to_watch_next", []) or [])]

    base_case = ai_analysis.get("base_case", {}) or {}
    bull_case = ai_analysis.get("bull_case", {}) or {}
    bear_case = ai_analysis.get("bear_case", {}) or {}

    risks = ai_analysis.get("key_risks", []) or []
    watchlist = ai_analysis.get("watchlist", []) or []

    top_cards = f"""
    <div style="display:grid;grid-template-columns:repeat(2, minmax(0, 1fr));gap:14px;">
      {_simple_text_card_html("한 줄 결론", one_line_take)}
      {_simple_text_card_html("운용 의도", manager_intent)}
    </div>
    """

    core_cards = f"""
    <div style="display:grid;grid-template-columns:repeat(2, minmax(0, 1fr));gap:14px;margin-top:14px;">
      {_simple_text_card_html("핵심 해석", core_view)}
      {_simple_list_card_html("이번에 바뀐 점 3가지", changed_points)}
    </div>
    """

    scenario_grid = f"""
    <div style="display:grid;grid-template-columns:repeat(3, minmax(0, 1fr));gap:14px;">
      {_scenario_card_html("기본 시나리오", base_case)}
      {_scenario_card_html("낙관 시나리오", bull_case)}
      {_scenario_card_html("비관 시나리오", bear_case)}
    </div>
    """

    risk_section = _simple_text_card_html("핵심 리스크", "").replace(
        '<p style="margin:0;font-size:14px;line-height:1.8;color:#111827;"></p>',
        f'<div style="display:grid;grid-template-columns:repeat(1, minmax(0, 1fr));gap:12px;">{_risk_cards_html(risks)}</div>'
    )

    next_section = _simple_list_card_html("다음 확인 포인트", next_checks)

    watchlist_section = _simple_text_card_html("관찰 항목", "").replace(
        '<p style="margin:0;font-size:14px;line-height:1.8;color:#111827;"></p>',
        f'<div style="display:grid;grid-template-columns:repeat(2, minmax(0, 1fr));gap:12px;">{_watchlist_cards_html(watchlist)}</div>'
    )

    return f"""
    <section style="margin-top:26px;">
      <div style="padding:22px 22px 20px 22px;background:linear-gradient(135deg, #ffffff 0%, #f8fbff 100%);
                  border:1px solid #dbe7ff;border-radius:22px;box-shadow:0 8px 24px rgba(15,23,42,0.05);">
        <div style="display:inline-block;padding:6px 10px;border-radius:999px;background:#eef4ff;
                    color:#1d4ed8;font-size:12px;font-weight:700;letter-spacing:0.02em;">
          AI PROFESSIONAL ANALYSIS
        </div>
        <h2 style="margin:14px 0 8px 0;font-size:24px;line-height:1.3;color:#0f172a;">AI 전문 분석</h2>
        <p style="margin:0;font-size:14px;line-height:1.8;color:#475569;">
          전 종목 변화와 포트폴리오 수준 지표를 함께 반영해, 이번 리밸런싱의 의미와 다음 확인 포인트를 정리했습니다.
        </p>
      </div>

      <div style="margin-top:16px;">{top_cards}</div>
      <div style="margin-top:14px;">{core_cards}</div>

      <div style="margin-top:20px;">
        <div style="font-size:18px;font-weight:700;color:#111827;margin-bottom:12px;">시나리오 전망</div>
        {scenario_grid}
      </div>

      <div style="display:grid;grid-template-columns:repeat(2, minmax(0, 1fr));gap:14px;margin-top:20px;">
        {risk_section}
        {next_section}
      </div>

      <div style="margin-top:14px;">
        {watchlist_section}
      </div>
    </section>
    """


def build_compare_report_html(
    compared: pd.DataFrame,
    title: str = "TIME 미국나스닥100 액티브 구성종목 변화",
    report_generated_at: str | None = None,
    ai_analysis: dict[str, Any] | None = None,
) -> str:
    sections = _build_sections(compared)
    ai_payload = build_compare_ai_payload(compared, report_generated_at=report_generated_at)
    generated_at = _get_report_generated_at(report_generated_at)

    section_specs = [
        (
            "비중 증가 상위 10",
            "주식 기준으로 전일 대비 비중이 가장 많이 늘어난 종목입니다.",
            sections["increased"],
            ["종목명", "비중(%)_prev", "비중(%)_today", "diff_pctp"],
            {},
        ),
        (
            "비중 감소 상위 10",
            "주식 기준으로 전일 대비 비중이 가장 많이 줄어든 종목입니다.",
            sections["decreased"],
            ["종목명", "비중(%)_prev", "비중(%)_today", "diff_pctp"],
            {},
        ),
        (
            "신규 편입",
            "이전 스냅샷에는 없었고 이번 스냅샷에서 새롭게 확인된 종목입니다.",
            sections["new_items"],
            ["종목명", "비중(%)_today"],
            {},
        ),
        (
            "편출",
            "이전 스냅샷에는 있었지만 이번 스냅샷에서는 빠진 종목입니다.",
            sections["removed_items"],
            ["종목명", "비중(%)_prev"],
            {},
        ),
        (
            "변동폭 상위 10",
            "비중 증가와 감소를 합쳐 절대 변화폭이 큰 종목 순으로 정리했습니다.",
            sections["biggest_moves"],
            ["종목명", "비중(%)_prev", "비중(%)_today", "diff_pctp", "status"],
            {"status": "변화 유형"},
        ),
        (
            "TOP10 순위 변화",
            "상위 10개 비중 종목 안에서 순위가 어떻게 이동했는지 보여줍니다.",
            sections["top10_changes"],
            ["종목명", "rank_prev", "rank_today", "비중(%)_prev", "비중(%)_today"],
            {},
        ),
        (
            "주식 외 자산 변화",
            "현금, 선물 등 주식 외 자산의 비중 변화입니다.",
            sections["non_stock_changes"],
            ["종목명", "asset_type", "비중(%)_prev", "비중(%)_today", "diff_pctp", "status"],
            {"asset_type": "자산 유형", "status": "변화 유형"},
        ),
    ]

    summary_items = "".join(
        f'<li style="margin:8px 0;">{html.escape(line)}</li>'
        for line in sections["summary"]
    )

    cards_html = _kpi_cards_html(compared)
    concentration_html = _top10_concentration_html(compared)

    section_html_parts = []
    for section_title, subtitle, raw_df, cols, rename_map in section_specs:
        display_df = _select_and_format(raw_df, cols, rename_map)
        table_html = _dataframe_to_html_table(display_df, raw_df)
        section_html_parts.append(_section_card_html(section_title, subtitle, table_html))

    ai_analysis_html = _build_ai_analysis_section_html(ai_analysis)

    ai_json = json.dumps(ai_payload, ensure_ascii=False, indent=2)
    ai_hidden_text = html.escape(ai_json)

    return f"""
    <!DOCTYPE html>
    <html lang="ko">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{html.escape(title)}</title>
      </head>
      <body style="margin:0;padding:0;background:#f4f7fb;
                   font-family:-apple-system, BlinkMacSystemFont, 'Apple SD Gothic Neo',
                   'Malgun Gothic', 'Segoe UI', Arial, sans-serif;
                   color:#111827;">
        <div style="max-width:1120px;margin:0 auto;padding:28px 20px 40px 20px;">
          
          <div style="padding:28px 28px 24px 28px;
                      background:linear-gradient(135deg, #ffffff 0%, #f8fbff 100%);
                      border:1px solid #e5e7eb;border-radius:24px;
                      box-shadow:0 8px 24px rgba(15,23,42,0.06);">
            <div style="display:inline-block;padding:6px 10px;border-radius:999px;background:#e8f0ff;
                        color:#1d4ed8;font-size:12px;font-weight:700;letter-spacing:0.02em;">
              ETF DAILY CHANGE REPORT
            </div>
            <h1 style="margin:14px 0 10px 0;font-size:28px;line-height:1.3;color:#0f172a;">
              {html.escape(title)}
            </h1>
            <div style="display:flex;flex-wrap:wrap;gap:10px;margin-top:10px;">
              <div style="display:inline-flex;align-items:center;padding:8px 12px;border-radius:999px;
                          background:#f8fafc;border:1px solid #e5e7eb;color:#475569;font-size:13px;">
                <span style="font-weight:700;color:#334155;margin-right:6px;">리포트 생성 시각</span>
                <span>{html.escape(generated_at)}</span>
              </div>
            </div>
          </div>

          <section style="margin-top:22px;">
            <div style="display:grid;grid-template-columns:repeat(4, minmax(0, 1fr));gap:14px;">
              {cards_html}
            </div>

            <div style="margin-top:14px;padding:18px 20px;background:#ffffff;border:1px solid #e5e7eb;
                        border-radius:18px;box-shadow:0 1px 2px rgba(16,24,40,0.04);">
              <div style="font-size:12px;font-weight:700;color:#6b7280;margin-bottom:10px;">요약</div>
              <ul style="margin:0;padding-left:18px;color:#111827;font-size:14px;line-height:1.8;">
                {summary_items}
              </ul>
            </div>

            {concentration_html}
          </section>

          {''.join(section_html_parts)}

          {ai_analysis_html}

          <script type="application/json" id="ai-summary-json">
{ai_json}
          </script>

          <pre style="display:none;" aria-hidden="true">{ai_hidden_text}</pre>
        </div>
      </body>
    </html>
    """