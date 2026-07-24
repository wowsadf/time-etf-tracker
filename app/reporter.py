from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any
from urllib.parse import quote
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

QUANTITY_STATUS_TEXT_MAP = {
    "new": "신규 편입",
    "removed": "편출",
    "bought": "수량 증가",
    "sold": "수량 감소",
    "unchanged": "수량 변동 없음",
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
    "수량_prev": "이전 수량",
    "수량_today": "현재 수량",
    "quantity_diff": "수량 변화",
    "quantity_status": "수량 변화 유형",
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


def _fmt_quantity(value: object, show_sign: bool = False) -> str:
    v = _safe_float(value)
    sign = "+" if show_sign and v > 0 else ""
    if float(v).is_integer():
        return f"{sign}{int(v):,}"
    return f"{sign}{v:,.4f}".rstrip("0").rstrip(".")


def _fmt_rank(value: object) -> str:
    rank = _safe_int_or_none(value)
    if rank is None or rank >= 999:
        return "-"
    return str(rank)


def _normalize_status_text(value: object) -> str:
    return STATUS_TEXT_MAP.get(str(value).strip(), str(value).strip())


def _normalize_quantity_status_text(value: object) -> str:
    return QUANTITY_STATUS_TEXT_MAP.get(str(value).strip(), str(value).strip())


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


def _prepare_significant_weight_moves(
    stock_df: pd.DataFrame,
    threshold_pctp: float = 0.10,
    n: int = 5,
) -> pd.DataFrame:
    data = stock_df[
        (~stock_df["status"].isin(["new", "removed"]))
        & (stock_df["diff_pctp"].abs() >= threshold_pctp)
    ].copy()
    data["abs_diff"] = data["diff_pctp"].abs()
    data = data.sort_values("abs_diff", ascending=False)
    return data.head(n).drop(columns=["abs_diff"])


def _summary_lines(compared: pd.DataFrame) -> list[str]:
    stock_df = _prepare_stock_only(compared)
    non_stock_df = _prepare_non_stock(compared)

    new_count = int((stock_df["status"] == "new").sum())
    removed_count = int((stock_df["status"] == "removed").sum())
    bought_count = int((stock_df["quantity_status"] == "bought").sum())
    sold_count = int((stock_df["quantity_status"] == "sold").sum())
    significant_moves = _prepare_significant_weight_moves(stock_df)

    non_stock_changed = non_stock_df[
        (non_stock_df["diff_pctp"].abs() >= 0.10)
        | (non_stock_df["quantity_status"] != "unchanged")
    ]

    summary = [
        f"주식 기준 신규 편입은 {new_count}종목, 편출은 {removed_count}종목입니다.",
        (
            f"실제 보유 수량 증가 종목은 {bought_count}개, 수량 감소 종목은 {sold_count}개입니다."
            if bought_count or sold_count
            else "기존 주식 종목의 보유 수량 변화는 없습니다. 비중 변화는 가격·환율·자산가치 변화의 영향일 수 있습니다."
        ),
    ]

    if not significant_moves.empty:
        names = ", ".join(significant_moves["종목명"].tolist())
        summary.append(
            f"0.10%p 이상 주요 비중 변화는 {len(significant_moves)}개이며, 대상은 {names}입니다."
        )

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
    bought_items = stock_df[stock_df["quantity_status"] == "bought"].sort_values(
        ["비중(%)_today", "quantity_diff"],
        ascending=[False, False],
    )
    sold_items = stock_df[stock_df["quantity_status"] == "sold"].sort_values(
        ["비중(%)_prev", "quantity_diff"],
        ascending=[False, True],
    )

    top10_changes = _prepare_top10_rank_changes(stock_df)
    significant_weight_moves = _prepare_significant_weight_moves(stock_df)
    current_top10 = stock_df[stock_df["rank_today"] <= 10].sort_values("rank_today")

    non_stock_changes = non_stock_df[
        (non_stock_df["diff_pctp"].abs() >= 0.10)
        | (non_stock_df["quantity_status"] != "unchanged")
    ].copy()
    non_stock_changes["abs_diff"] = non_stock_changes["diff_pctp"].abs()
    non_stock_changes = non_stock_changes.sort_values("abs_diff", ascending=False).drop(
        columns=["abs_diff"]
    )

    return {
        "summary": _summary_lines(compared),
        "increased": _top_n(increased, 10),
        "decreased": _top_n(decreased, 10),
        "new_items": _top_n(new_items, 10),
        "removed_items": _top_n(removed_items, 10),
        "bought_items": _top_n(bought_items, 10),
        "sold_items": _top_n(sold_items, 10),
        "significant_weight_moves": _top_n(significant_weight_moves, 5),
        "current_top10": _top_n(current_top10, 10),
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
        elif col in {"수량_prev", "수량_today"}:
            df[col] = df[col].map(_fmt_quantity)
        elif col == "quantity_diff":
            df[col] = df[col].map(lambda value: _fmt_quantity(value, show_sign=True))
        elif col in {"rank_prev", "rank_today"}:
            df[col] = df[col].map(_fmt_rank)
        elif col in {"status", "변화유형"}:
            df[col] = df[col].map(_normalize_status_text)
        elif col == "quantity_status":
            df[col] = df[col].map(_normalize_quantity_status_text)

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
    return f"https://www.tradingview.com/search/?query={quote(ticker)}"


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
            f'<a href="{html.escape(tv_url)}" target="_blank" rel="noopener noreferrer" '
            f'style="margin-left:8px;font-size:12px;color:#2563eb;text-decoration:none;">TradingView</a>'
        )

    if ENABLE_TOSS_LINKS:
        toss_url = _build_tossinvest_url(ticker)
        parts.append(
            f'<a href="{html.escape(toss_url)}" target="_blank" rel="noopener noreferrer" '
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
        "수량 증가": ("#1a7f37", "#edf7ed"),
        "수량 감소": ("#d1242f", "#fff1f3"),
        "수량 변동 없음": ("#57606a", "#f6f8fa"),
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
            elif col in {"변화 유형", "수량 변화 유형"}:
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
    <section style="margin-top:12px;padding:18px;background:#ffffff;
                    border:1px solid #e2e8f0;border-radius:14px;">
      <div style="margin-bottom:12px;">
        <h2 style="margin:0;font-size:17px;font-weight:800;color:#0f172a;">{html.escape(title)}</h2>
        <p style="margin:6px 0 0 0;font-size:12px;line-height:1.6;color:#64748b;">{html.escape(subtitle)}</p>
      </div>
      {table_html}
    </section>
    """


def _kpi_cards_html(compared: pd.DataFrame) -> str:
    stock_df = _prepare_stock_only(compared)

    cards = [
        ("신규 편입", int((stock_df["status"] == "new").sum()), "#047857", "#ecfdf5"),
        ("편출", int((stock_df["status"] == "removed").sum()), "#b45309", "#fffbeb"),
        ("수량 증가", int((stock_df["quantity_status"] == "bought").sum()), "#1d4ed8", "#eff6ff"),
        ("수량 감소", int((stock_df["quantity_status"] == "sold").sum()), "#be123c", "#fff1f2"),
    ]

    cells = []
    for label, value, color, bg in cards:
        cells.append(
            f"""
            <td width="50%" style="padding:6px;vertical-align:top;">
              <div style="padding:16px 18px;background:{bg};border:1px solid {color}22;
                          border-radius:14px;">
                <div style="font-size:12px;font-weight:700;color:#64748b;margin-bottom:8px;">
                  {html.escape(label)}
                </div>
                <div style="font-size:26px;font-weight:800;color:{color};line-height:1.1;">
                  {value}<span style="margin-left:5px;font-size:12px;font-weight:700;">종목</span>
                </div>
              </div>
            </td>
            """
        )

    return f"""
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
      <tr>{''.join(cells[:2])}</tr>
      <tr>{''.join(cells[2:])}</tr>
    </table>
    """


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
    <div style="margin-top:12px;padding:16px 18px;background:#f8fafc;border-left:4px solid #6366f1;
                border-radius:12px;">
      <div style="font-size:12px;font-weight:800;color:#475569;margin-bottom:8px;letter-spacing:0.03em;">TOP10 집중도</div>
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
    bought_count = int((stock_df["quantity_status"] == "bought").sum())
    sold_count = int((stock_df["quantity_status"] == "sold").sum())
    quantity_unchanged_count = int((stock_df["quantity_status"] == "unchanged").sum())

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
            "previous_stock_names": int(stock_df["rank_prev"].notna().sum()),
            "current_stock_names": int(stock_df["rank_today"].notna().sum()),
        },
        "quantity_signals": {
            "bought": bought_count,
            "sold": sold_count,
            "unchanged_existing": quantity_unchanged_count,
            "note": "수량 변화는 실제 매매의 단서이며, 비중 변화만으로 매매를 단정할 수 없다.",
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
        "수량_prev",
        "수량_today",
        "quantity_diff",
        "quantity_status",
        "valuation_diff_krw",
    ]

    stock_all_changes = stock_df.assign(abs_diff=stock_df["diff_pctp"].abs()).sort_values(
        by=["abs_diff", "비중(%)_today"],
        ascending=[False, False],
    ).drop(columns=["abs_diff"])

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
                "quantity_status는 실제 보유 수량 변화 신호이며 bought, sold, new, removed, unchanged 중 하나다.",
                "수량 변화 없이 비중만 바뀐 경우 가격·환율·다른 자산 변화의 영향일 수 있으며 매매로 단정하면 안 된다.",
                "rank_prev / rank_today가 null이면 해당 시점에 종목이 없었음을 의미한다.",
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
            "quantity_increases": _records_from_df(
                sections["bought_items"],
                ["종목명", "asset_key", "수량_prev", "수량_today", "quantity_diff", "diff_pctp"],
                limit=10,
            ),
            "quantity_decreases": _records_from_df(
                sections["sold_items"],
                ["종목명", "asset_key", "수량_prev", "수량_today", "quantity_diff", "diff_pctp"],
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
            "all_stock_changes_sorted_by_absolute_weight_change": _records_from_df(
                stock_all_changes,
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
                "실제 수량 증가·감소와 단순 비중 변화를 명확히 구분",
                "신규 편입 종목이 단순 추가인지, 상위권 진입까지 동반하는 공격적 편입인지",
                "감소 종목이 몇 개 종목에 집중되는지, 아니면 전반적 디레이킹인지",
                "현금 및 선물 비중 변화가 위험관리 신호인지",
                "반도체, AI 인프라, 우주항공 등 특정 테마 로테이션이 보이는지",
            ],
            "desired_output_style": [
                "단순 재진술보다 해석 중심",
                "가격 단정보다 시나리오 중심",
                "운용 의도 가설 제시",
                "수량 변화가 없으면 운용 의도를 단정하지 않기",
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
        ("신규 편입", sections["new_items"], ["종목명", "비중(%)_today"], {}),
        ("편출", sections["removed_items"], ["종목명", "비중(%)_prev"], {}),
        ("수량 증가 (매수 추정)", sections["bought_items"], ["종목명", "수량_prev", "수량_today", "quantity_diff"], {}),
        ("수량 감소 (매도 추정)", sections["sold_items"], ["종목명", "수량_prev", "수량_today", "quantity_diff"], {}),
        ("현재 TOP10", sections["current_top10"], ["종목명", "rank_today", "비중(%)_today", "diff_pctp"], {}),
        ("주요 비중 변화", sections["significant_weight_moves"], ["종목명", "비중(%)_prev", "비중(%)_today", "diff_pctp"], {}),
        ("주식 외 자산 변화", sections["non_stock_changes"], ["종목명", "asset_type", "비중(%)_today", "diff_pctp"], {"asset_type": "자산 유형"}),
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
    <div style="padding:19px;background:#ffffff;border:1px solid #e2e8f0;border-radius:14px;">
      <div style="margin-bottom:12px;">
        <h3 style="margin:0;font-size:18px;font-weight:700;color:#111827;">{html.escape(title)}</h3>
        {subtitle_html}
      </div>
      <p style="margin:0;font-size:14px;line-height:1.85;color:#1e293b;white-space:pre-line;">{html.escape(body)}</p>
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
    <div style="padding:19px;background:#ffffff;border:1px solid #e2e8f0;border-radius:14px;">
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
    <div style="padding:18px;background:#ffffff;border:1px solid #e2e8f0;border-radius:14px;">
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
            <div style="margin-bottom:12px;padding:16px;background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;">
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
            <div style="margin-bottom:12px;padding:16px;background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;">
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
    evidence_points = [str(x) for x in (ai_analysis.get("evidence_based_observations", []) or [])]
    portfolio_implications = [str(x) for x in (ai_analysis.get("portfolio_implications", []) or [])]
    next_checks = [str(x) for x in (ai_analysis.get("what_to_watch_next", []) or [])]
    data_limitations = [str(x) for x in (ai_analysis.get("data_limitations", []) or [])]

    base_case = ai_analysis.get("base_case", {}) or {}
    bull_case = ai_analysis.get("bull_case", {}) or {}
    bear_case = ai_analysis.get("bear_case", {}) or {}

    risks = ai_analysis.get("key_risks", []) or []
    watchlist = ai_analysis.get("watchlist", []) or []

    top_cards = f"""
    <div>
      {_simple_text_card_html("한 줄 결론", one_line_take)}
      <div style="height:12px;"></div>
      {_simple_text_card_html("운용 의도", manager_intent)}
    </div>
    """

    core_cards = f"""
    <div style="margin-top:12px;">
      {_simple_text_card_html("핵심 해석", core_view)}
      <div style="height:12px;"></div>
      {_simple_list_card_html("이번에 바뀐 점 4가지", changed_points)}
      <div style="height:12px;"></div>
      {_simple_list_card_html("데이터로 확인된 근거", evidence_points)}
      <div style="height:12px;"></div>
      {_simple_list_card_html("포트폴리오 영향", portfolio_implications)}
    </div>
    """

    scenario_grid = f"""
    <div>
      {_scenario_card_html("기본 시나리오", base_case)}
      <div style="height:12px;"></div>
      {_scenario_card_html("낙관 시나리오", bull_case)}
      <div style="height:12px;"></div>
      {_scenario_card_html("비관 시나리오", bear_case)}
    </div>
    """

    risk_section = _simple_text_card_html("핵심 리스크", "").replace(
        '<p style="margin:0;font-size:14px;line-height:1.85;color:#1e293b;white-space:pre-line;"></p>',
        f'<div>{_risk_cards_html(risks)}</div>'
    )

    next_section = _simple_list_card_html("다음 확인 포인트", next_checks)
    limitation_section = _simple_list_card_html(
        "분석 한계",
        data_limitations,
        "현재 구성종목 스냅샷만으로 확정할 수 없는 부분입니다.",
    )

    watchlist_section = _simple_text_card_html("관찰 항목", "").replace(
        '<p style="margin:0;font-size:14px;line-height:1.85;color:#1e293b;white-space:pre-line;"></p>',
        f'<div>{_watchlist_cards_html(watchlist)}</div>'
    )

    return f"""
    <section style="margin-top:26px;">
      <div style="padding:22px;background:#eef2ff;border:1px solid #c7d2fe;border-radius:18px;">
        <div style="display:inline-block;padding:6px 10px;border-radius:999px;background:#4338ca;
                    color:#ffffff;font-size:11px;font-weight:800;letter-spacing:0.07em;">
          GEMINI ANALYSIS
        </div>
        <h2 style="margin:14px 0 8px 0;font-size:23px;line-height:1.3;color:#1e1b4b;">AI 상세 분석</h2>
        <p style="margin:0;font-size:14px;line-height:1.8;color:#475569;">
          실제 수량 변화와 단순 비중 변화를 구분하고, 데이터 근거·포트폴리오 영향·시나리오·리스크를 함께 정리했습니다.
        </p>
      </div>

      <div style="margin-top:16px;">{top_cards}</div>
      <div>{core_cards}</div>

      <div style="margin-top:20px;">
        <div style="font-size:18px;font-weight:700;color:#111827;margin-bottom:12px;">시나리오 전망</div>
        {scenario_grid}
      </div>

      <div style="margin-top:20px;">
        {risk_section}
        <div style="height:12px;"></div>
        {next_section}
        <div style="height:12px;"></div>
        {limitation_section}
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
    generated_at = _get_report_generated_at(report_generated_at)

    section_specs = [
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
            "수량 증가 (매수 추정)",
            "동일 종목코드 기준으로 실제 보유 수량이 늘어난 종목입니다. 기업행동 등 다른 원인도 확인이 필요합니다.",
            sections["bought_items"],
            ["종목명", "수량_prev", "수량_today", "quantity_diff"],
            {},
        ),
        (
            "수량 감소 (매도 추정)",
            "동일 종목코드 기준으로 실제 보유 수량이 줄어든 종목입니다. 기업행동 등 다른 원인도 확인이 필요합니다.",
            sections["sold_items"],
            ["종목명", "수량_prev", "수량_today", "quantity_diff"],
            {},
        ),
        (
            "현재 TOP10",
            "현재 포트폴리오에서 비중이 가장 큰 10개 주식입니다.",
            sections["current_top10"],
            ["종목명", "rank_today", "비중(%)_today", "diff_pctp"],
            {},
        ),
        (
            "주요 비중 변화",
            "매매 신호가 아닌 보조 지표입니다. 기존 종목 중 절대 변화가 0.10%p 이상인 최대 5개만 표시합니다.",
            sections["significant_weight_moves"],
            ["종목명", "비중(%)_prev", "비중(%)_today", "diff_pctp"],
            {},
        ),
        (
            "주식 외 자산 변화",
            "현금, 선물 등 주식 외 자산의 비중 변화입니다.",
            sections["non_stock_changes"],
            ["종목명", "asset_type", "비중(%)_today", "diff_pctp"],
            {"asset_type": "자산 유형"},
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
        if raw_df.empty:
            continue
        display_df = _select_and_format(raw_df, cols, rename_map)
        table_html = _dataframe_to_html_table(display_df, raw_df)
        section_html_parts.append(_section_card_html(section_title, subtitle, table_html))

    ai_analysis_html = _build_ai_analysis_section_html(ai_analysis)

    return f"""
    <!DOCTYPE html>
    <html lang="ko">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{html.escape(title)}</title>
      </head>
      <body style="margin:0;padding:0;background:#eef2f7;
                   font-family:-apple-system, BlinkMacSystemFont, 'Apple SD Gothic Neo',
                   'Malgun Gothic', 'Segoe UI', Arial, sans-serif;
                   color:#111827;">
        <div style="max-width:760px;margin:0 auto;padding:20px 12px 36px 12px;">
          
          <div style="padding:26px 24px 24px 24px;background:#0f172a;
                      border-radius:20px;box-shadow:0 10px 28px rgba(15,23,42,0.16);">
            <div style="display:inline-block;padding:6px 10px;border-radius:999px;background:#1e293b;
                        color:#bfdbfe;font-size:11px;font-weight:800;letter-spacing:0.08em;">
              ETF DAILY CHANGE REPORT
            </div>
            <h1 style="margin:14px 0 10px 0;font-size:26px;line-height:1.35;color:#ffffff;">
              {html.escape(title)}
            </h1>
            <div style="margin-top:14px;color:#cbd5e1;font-size:12px;line-height:1.6;">
              <strong style="color:#ffffff;">생성 시각</strong>&nbsp;&nbsp;{html.escape(generated_at)}
            </div>
          </div>

          <section style="margin-top:16px;">
            {cards_html}

            <div style="margin-top:12px;padding:18px 20px;background:#ffffff;border:1px solid #e2e8f0;
                        border-radius:14px;">
              <div style="font-size:12px;font-weight:800;color:#475569;margin-bottom:10px;letter-spacing:0.04em;">오늘의 핵심</div>
              <ul style="margin:0;padding-left:18px;color:#1e293b;font-size:14px;line-height:1.75;">
                {summary_items}
              </ul>
            </div>

            {concentration_html}
          </section>

          {ai_analysis_html}

          <div style="margin:28px 0 10px 0;padding-left:12px;border-left:4px solid #6366f1;">
            <h2 style="margin:0;font-size:20px;color:#0f172a;">구성 상세</h2>
            <p style="margin:5px 0 0 0;font-size:13px;color:#64748b;">실제 수량 변화가 우선이며 비중은 보조 지표로 표시합니다.</p>
          </div>

          {''.join(section_html_parts)}

          <div style="margin-top:24px;padding:14px 16px;color:#64748b;font-size:11px;line-height:1.7;text-align:center;">
            본 리포트는 공개 구성종목 데이터의 자동 비교 결과이며 투자 권유가 아닙니다.
          </div>
        </div>
      </body>
    </html>
    """
