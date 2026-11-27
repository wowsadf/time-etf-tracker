"""ETF report data and email-safe HTML. Calculations stay outside the AI."""
from __future__ import annotations

import html
import json
import re
from datetime import datetime
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pandas as pd

from config import REPORT_TITLE

WEIGHT_THRESHOLD = 0.10
WEIGHT_LIMIT = 5
STATUS_LABELS = {"new": "신규 편입", "removed": "편출", "bought": "수량 증가", "sold": "수량 감소"}


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _number(value: object, signed: bool = False) -> str:
    if pd.isna(value):
        return "—"
    number = float(value)
    sign = "+" if signed and number > 0 else ""
    return sign + f"{number:,.6f}".rstrip("0").rstrip(".")


def _weight(value: object) -> str:
    return f"{float(value):.2f}%"


def _delta(value: object) -> str:
    return f"{float(value):+.2f}%p"


def _generated_at(value: str | None) -> str:
    return value or datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M KST")


def _sections(compared: pd.DataFrame) -> dict[str, pd.DataFrame]:
    stocks = compared[compared["asset_type"] == "stock"]
    sections = {}
    for status, weight_col in [
        ("new", "비중(%)_today"), ("removed", "비중(%)_prev"),
        ("bought", "비중(%)_today"), ("sold", "비중(%)_prev"),
    ]:
        sections[status] = stocks[stocks["quantity_status"] == status].sort_values(
            [weight_col, "asset_key"], ascending=[False, True]
        )
    sections["top10"] = stocks[stocks["rank_today"] <= 10].sort_values("rank_today")
    significant = stocks[
        ~stocks["quantity_status"].isin(["new", "removed"])
        & (stocks["diff_pctp"].abs() >= WEIGHT_THRESHOLD)
    ]
    sections["weights"] = significant.assign(magnitude=significant["diff_pctp"].abs()).sort_values(
        ["magnitude", "asset_key"], ascending=[False, True]
    ).head(WEIGHT_LIMIT).drop(columns="magnitude")
    sections["other"] = compared[
        (compared["asset_type"] != "stock")
        & ((compared["quantity_status"] != "unchanged") | (compared["diff_pctp"].abs() >= WEIGHT_THRESHOLD))
    ]
    return sections


def _summary(compared: pd.DataFrame) -> list[str]:
    sections = _sections(compared)
    lines = [f"신규 편입 {len(sections['new'])}종목 · 편출 {len(sections['removed'])}종목"]
    bought, sold = len(sections["bought"]), len(sections["sold"])
    if bought or sold:
        lines.append(f"기존 주식 수량 증가 {bought}종목 · 수량 감소 {sold}종목")
    else:
        lines.append("기존 주식의 수량 변화는 없습니다. 비중 변화만으로 매매를 판단할 수 없습니다.")
    return lines


def _concentration(compared: pd.DataFrame, n: int, side: str) -> float:
    stocks = compared[compared["asset_type"] == "stock"]
    return round(float(stocks.loc[stocks[f"rank_{side}"] <= n, f"비중(%)_{side}"].sum()), 6)


def _records(data: pd.DataFrame) -> list[dict]:
    columns = [
        "asset_key", "종목명", "asset_type", "수량_prev", "수량_today",
        "quantity_diff", "quantity_change_pct", "quantity_status",
        "비중(%)_prev", "비중(%)_today", "diff_pctp", "rank_prev", "rank_today",
        "평가금액(원)_prev", "평가금액(원)_today", "valuation_diff_krw",
    ]
    return json.loads(data[[c for c in columns if c in data]].to_json(orient="records", force_ascii=False))


def build_compare_ai_payload(
    compared: pd.DataFrame, report_generated_at: str | None = None,
    previous_label: str | None = None, current_label: str | None = None,
) -> dict[str, Any]:
    stocks = compared[compared["asset_type"] == "stock"]
    existing = stocks[~stocks["quantity_status"].isin(["new", "removed"])]
    ratios = existing.loc[existing["수량_prev"] > 0, "quantity_change_pct"].dropna()
    median = float(ratios.median()) if not ratios.empty else 0.0
    concentration = {}
    for n in [5, 10]:
        before, after = (_concentration(compared, n, s) for s in ["prev", "today"])
        concentration.update({f"top{n}_prev_pct": before, f"top{n}_today_pct": after,
                              f"top{n}_diff_pctp": round(after - before, 6)})
    mix = {}
    for asset_type in ["stock", "cash", "futures", "other"]:
        rows = compared[compared["asset_type"] == asset_type]
        before, after = (float(rows[f"비중(%)_{s}"].sum()) for s in ["prev", "today"])
        mix[asset_type] = {"previous_pct": round(before, 6), "current_pct": round(after, 6),
                          "diff_pctp": round(after - before, 6)}
    return {
        "meta": {
            "report_generated_at": _generated_at(report_generated_at),
            "previous_snapshot": previous_label, "current_snapshot": current_label,
            "notes": [
                "직전 정상 스냅샷과 비교하며 반드시 전 거래일은 아니다.",
                "수량 변화는 매매뿐 아니라 ETF 설정·환매와 기업행동 때문일 수 있다.",
                "두 시점의 수량이 같더라도 그 사이 매매가 전혀 없었다는 뜻은 아니다.",
                "수량 단위가 다르므로 종목 간 수량을 합산하거나 절대 크기로 비교하지 않는다.",
                "비중 변화만으로 운용 의도를 단정할 수 없다. 원인 구분에는 가격·환율·ETF 좌수가 필요하다.",
                "주식의 rank가 null이면 그 시점에 없던 종목이며, 주식 외 자산의 rank는 항상 null이다.",
                "선물 비중은 평가액 비중이다. 명목금액·델타가 없으므로 실제 시장 노출로 해석하지 않는다.",
            ],
        },
        "summary": _summary(compared),
        "quantity_facts": _records(stocks[stocks["quantity_status"] != "unchanged"].sort_values("asset_key")),
        "portfolio_stats": {
            "stock_counts": {
                "previous_stock_names": int(stocks["rank_prev"].notna().sum()),
                "current_stock_names": int(stocks["rank_today"].notna().sum()),
                **{s: int((stocks["quantity_status"] == s).sum()) for s in ["new", "removed"]},
            },
            "quantity_signals": {
                **{s: int((stocks["quantity_status"] == s).sum()) for s in ["bought", "sold", "unchanged"]},
                "median_existing_quantity_change_pct": round(median, 6),
                "existing_names_near_median_within_0_25pctp": int((ratios.sub(median).abs() <= 0.25).sum()),
                "note": "다수 종목의 비슷한 수량 증감률은 ETF 규모 변화 가능성을 점검하는 보조 정보다.",
            },
            "concentration": concentration, "asset_mix": mix,
        },
        "full_universe": _records(compared.sort_values(["asset_type", "asset_key"])),
    }


# Muted editorial palette; use only inline styles and tables for mail clients.
INK = "#202a25"
MUTED = "#68716a"
LINE = "#dce0d8"
ACCENT = "#315b47"
CELL = f"padding:14px 6px;border-bottom:1px solid {LINE};vertical-align:top;font-size:13px;line-height:1.65;color:{INK};"
SMALL = f"font-size:11px;line-height:1.6;color:{MUTED};"


def _paragraph(text: object, break_long: bool = False) -> str:
    text = str(text or "").strip()
    if break_long and len(text) > 260 and "\n" not in text:
        # 긴 한국어 분석은 읽기 편하게 나눈다. 숫자의 소수점·영문 약어에서는 끊지 않는다.
        sentences = re.split(r"(?<=[다요]\.)\s+", text)
        text = "\n\n".join(" ".join(sentences[i:i + 2]) for i in range(0, len(sentences), 2))
    return "".join(
        f'<p style="margin:0 0 14px;font-size:15px;line-height:1.95;color:{INK};">{_escape(p).replace(chr(10), "<br>")}</p>'
        for p in text.split("\n\n") if p.strip()
    )


def _list(items: list) -> str:
    if not items:
        return ""
    return f'<ul style="margin:0;padding-left:19px;font-size:14px;line-height:1.9;color:{INK};">' + "".join(
        f'<li style="margin:0 0 10px;padding-left:3px;">{_escape(item)}</li>' for item in items
    ) + "</ul>"


def _section(title: str, body: str, note: str = "") -> str:
    if not body:
        return ""
    subtitle = f'<p style="margin:0 0 17px;font-size:12px;line-height:1.8;color:{MUTED};">{_escape(note)}</p>' if note else ""
    return f'''<tr><td class="section-pad" style="padding:28px 38px 8px;">
      <h2 style="margin:0 0 15px;padding-top:24px;border-top:1px solid {LINE};font-size:19px;line-height:1.5;letter-spacing:-0.5px;color:{INK};">{_escape(title)}</h2>
      {subtitle}{body}</td></tr>'''


def _subhead(title: str) -> str:
    return f'<h3 style="margin:23px 0 10px;font-size:14px;line-height:1.6;color:{ACCENT};">{_escape(title)}</h3>'


def _ticker(row: pd.Series) -> str | None:
    match = re.fullmatch(r"([A-Z0-9.\-]+) US EQUITY", str(row["asset_key"]))
    return match[1] if match else None


def _stock_name(row: pd.Series, rank: bool = False) -> str:
    name = _escape(row["종목명"])
    ticker = _ticker(row)
    if ticker:
        url = "https://www.tradingview.com/search/?query=" + quote(ticker)
        name = f'<a href="{url}" style="color:{INK};text-decoration:none;">{name}</a>'
    if rank:
        name = f'<span style="font-size:11px;color:{MUTED};">{int(row["rank_today"]):02d}&nbsp;&nbsp;</span>' + name
    return name


def _rank_move(row: pd.Series) -> str:
    before, after = row["rank_prev"], row["rank_today"]
    if pd.isna(before) or before > 10:
        return "진입"
    diff = int(before - after)
    return f"↑ {diff}" if diff > 0 else f"↓ {abs(diff)}" if diff < 0 else "—"


def _table(headings: list[str], rows: list[list[str]], widths=(50, 31, 19)) -> str:
    header = "".join(
        f'<th scope="col" width="{widths[i]}%" style="width:{widths[i]}%;padding:0 6px 10px;border-bottom:1px solid {INK};font-size:11px;font-weight:400;color:{MUTED};text-align:{"left" if i == 0 else "right"};">{_escape(label)}</th>'
        for i, label in enumerate(headings)
    )
    body = "".join("<tr>" + "".join(
        f'<td width="{widths[i]}%" style="{CELL}width:{widths[i]}%;text-align:{"left" if i == 0 else "right"};overflow-wrap:anywhere;word-break:break-word;">{value}</td>'
        for i, value in enumerate(row)
    ) + "</tr>" for row in rows)
    return f'<table width="100%" cellspacing="0" cellpadding="0" border="0" style="width:100%;border-collapse:collapse;table-layout:fixed;"><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>'


def _changes_table(data: pd.DataFrame) -> str:
    rows = []
    for _, row in data.iterrows():
        status = STATUS_LABELS.get(row["quantity_status"], "수량 유지")
        ticker = _ticker(row)
        details = status + (f" · {ticker}" if ticker else "")
        name = _stock_name(row) + f'<br><span style="{SMALL}">{_escape(details)}</span>'
        change = _number(row["quantity_diff"], signed=True)
        color = ACCENT if row["quantity_diff"] > 0 else INK
        quantity = (f'<span style="font-weight:600;color:{color};">{change}</span><br>'
                    f'<span style="{SMALL}">{_number(row["수량_prev"])} → {_number(row["수량_today"])}</span>')
        weight = "—" if row["quantity_status"] == "removed" else _weight(row["비중(%)_today"])
        rows.append([name, quantity, weight])
    return _table(["종목 / 구분", "수량 변화", "현재 비중"], rows) if rows else ""


def _reference_table(data: pd.DataFrame, kind: str) -> str:
    rows = []
    for _, row in data.iterrows():
        if kind == "top10":
            rows.append([_stock_name(row, rank=True), _weight(row["비중(%)_today"]), _rank_move(row)])
        else:
            rows.append([_stock_name(row), f'{_weight(row["비중(%)_prev"])} → {_weight(row["비중(%)_today"])}',
                         _delta(row["diff_pctp"])])
    if not rows:
        return ""
    labels = ["종목", "현재 비중", "순위"] if kind == "top10" else ["종목", "이전 → 현재", "변화"]
    return _table(labels, rows, (50, 30, 20))


def _headline(sections: dict[str, pd.DataFrame]) -> str:
    count = sum(len(sections[key]) for key in STATUS_LABELS)
    return f"주식 {count}종목의 보유 내역이 바뀌었습니다." if count else "주식의 편입·편출과 수량 변화는 없습니다."


def _analysis_body(analysis: dict | None) -> str:
    if not analysis:
        return _paragraph("AI 분석을 사용할 수 없습니다. 종목별 변화와 아래 지표는 검증된 스냅샷의 계산 결과입니다.")
    body = _paragraph(analysis.get("core_view", ""), break_long=True)
    for key, title in [("evidence_based_observations", "판단의 근거"), ("portfolio_implications", "운용 관점")]:
        if analysis.get(key):
            body += _subhead(title) + _list(analysis[key])
    if analysis.get("manager_intent"):
        body += _subhead("운용 가설과 다른 가능성") + _paragraph(analysis["manager_intent"])
    if analysis.get("key_risks"):
        risks = [f'{item["issue"]} — {item["evidence"]}' for item in analysis["key_risks"]]
        body += _subhead("유의할 점") + _list(risks)
    if analysis.get("what_to_watch_next"):
        body += _subhead("다음 스냅샷에서 확인할 것") + _list(analysis["what_to_watch_next"])
    if analysis.get("data_limitations"):
        body += _subhead("분석 한계") + _list(analysis["data_limitations"])
    return body


def build_compare_report_html(
    compared: pd.DataFrame, title: str = REPORT_TITLE, report_generated_at: str | None = None,
    ai_analysis: dict[str, Any] | None = None,
    previous_label: str | None = None, current_label: str | None = None,
    sample: bool = False,
) -> str:
    sections = _sections(compared)
    generated = _generated_at(report_generated_at)
    period = f"{previous_label} → {current_label}" if previous_label and current_label else "직전 정상 스냅샷 대비"
    summary = _summary(compared)
    counts = " &nbsp;·&nbsp; ".join(f'{STATUS_LABELS[key]} <strong style="color:{INK};">{len(sections[key])}</strong>' for key in STATUS_LABELS)
    stock_changes = pd.concat([sections[key] for key in STATUS_LABELS])
    content = _section("종목별 변화", _changes_table(stock_changes),
                       "수량 증감은 보유 내역의 차이입니다. 실제 매매 내역을 의미하지 않습니다.")
    if stock_changes.empty:
        content = ""
    content += _section("해석 노트", _analysis_body(ai_analysis), "계산된 사실과 구분해서 읽는 AI의 참고 해석입니다.")
    content += _section("현재 TOP10", _reference_table(sections["top10"], "top10"),
                        f'주식 기준 · 비중 합계 {_weight(_concentration(compared, 10, "today"))}')
    stocks = compared[compared["asset_type"] == "stock"]
    exits = stocks[(stocks["rank_prev"] <= 10) & (stocks["rank_today"].isna() | (stocks["rank_today"] > 10))]
    if not exits.empty:
        content += _section("TOP10에서 빠진 종목", _paragraph(" · ".join(exits["종목명"].tolist())))
    content += _section("주요 비중 변화", _reference_table(sections["weights"], "weights"),
                        "보조 지표 · 기존 주식 중 0.10%p 이상 변화한 최대 5개. 매매 신호가 아닙니다.")
    content += _section("현금·선물 등 기타 자산", _changes_table(sections["other"]))
    note = (f'<tr><td class="section-pad" style="padding:18px 38px;background:#f2f3ed;font-size:12px;line-height:1.8;color:{ACCENT};">'
            '디자인 확인용 예시 메일입니다. 아래 날짜의 저장된 스냅샷을 비교했으며 최신 공시자료가 아닐 수 있습니다.</td></tr>') if sample else ""
    source = " · ".join(str(ai_analysis[key]) for key in ["provider", "model"] if ai_analysis and ai_analysis.get(key))
    source = f'<p style="margin:0 0 8px;">해석 생성: {_escape(source)}</p>' if source else ""
    preheader = _escape(" / ".join(summary))
    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light">
    <title>{_escape(title)}</title>
    <style>body{{margin:0;padding:0;}}table{{border-spacing:0;}}a{{color:{ACCENT};}}
    @media only screen and (max-width:600px){{.section-pad{{padding-left:20px!important;padding-right:20px!important;}}.report-title{{font-size:25px!important;}}.outer-pad{{padding:12px 0!important;}}}}</style>
    </head><body style="margin:0;padding:0;background:#edf0e9;font-family:'Apple SD Gothic Neo','Malgun Gothic',Arial,sans-serif;">
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;mso-hide:all;">{preheader}</div>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#edf0e9;">
    <tr><td align="center" class="outer-pad" style="padding:32px 12px;">
    <!--[if mso]><table role="presentation" width="720"><tr><td><![endif]-->
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="width:100%;max-width:720px;background:#fffffc;border-top:3px solid {ACCENT};">
    <tr><td class="section-pad" style="padding:27px 38px 24px;border-bottom:1px solid {LINE};">
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"><tr>
        <td style="font-family:Georgia,serif;font-size:26px;font-weight:700;letter-spacing:-1px;color:{ACCENT};">TIME<span style="font-family:Arial,sans-serif;font-size:12px;font-weight:400;letter-spacing:1px;">&nbsp; ETF</span></td>
        <td style="text-align:right;font-size:11px;line-height:1.8;color:{MUTED};">보유종목 노트<br>직전 정상 스냅샷 비교</td>
      </tr></table>
    </td></tr>{note}
    <tr><td class="section-pad" style="padding:29px 38px 5px;">
      <p style="margin:0 0 12px;font-size:12px;line-height:1.7;color:{MUTED};">{_escape(period)}</p>
      <h1 class="report-title" style="margin:0 0 23px;font-size:29px;line-height:1.5;letter-spacing:-1px;font-weight:600;color:{INK};">{_escape(title)}</h1>
      <p style="margin:0 0 12px;font-size:17px;font-weight:600;line-height:1.8;color:{INK};">{_escape(_headline(sections))}</p>
      <p style="margin:0;font-size:12px;line-height:2.1;color:{MUTED};">{counts}</p>
    </td></tr>{content}
    <tr><td class="section-pad" style="padding:35px 38px 30px;">
      <div style="padding-top:20px;border-top:1px solid {LINE};font-size:11px;line-height:1.9;color:{MUTED};">
        {source}<p style="margin:0 0 8px;">수량 사실 확인표는 검산하지만 AI 서술 전체의 정확성을 보장하지 않습니다. 숫자 표를 우선해 주세요.
        ETF 설정·환매와 기업행동도 수량에 영향을 줄 수 있습니다. 투자 판단을 위한 권유가 아닙니다.</p>
        <p style="margin:0;">생성 {_escape(generated)}<br>비교 날짜는 저장된 스냅샷 파일 기준이며, 반드시 연속 거래일은 아닙니다.</p>
      </div>
    </td></tr></table><!--[if mso]></td></tr></table><![endif]-->
    </td></tr></table></body></html>'''


def build_compare_report_text(
    compared: pd.DataFrame, report_generated_at: str | None = None,
    ai_analysis: dict[str, Any] | None = None,
    previous_label: str | None = None, current_label: str | None = None,
    sample: bool = False,
) -> str:
    lines = [REPORT_TITLE, "생성 " + _generated_at(report_generated_at)]
    if sample:
        lines.append("예시 메일 · 저장된 스냅샷 비교이며 최신 공시자료가 아닐 수 있습니다.")
    if previous_label and current_label:
        lines.append(f"비교: {previous_label} → {current_label}")
    lines.extend(_summary(compared))
    for kind, data in _sections(compared).items():
        if data.empty:
            continue
        label = STATUS_LABELS.get(kind, {"top10": "현재 TOP10", "weights": "주요 비중 변화", "other": "현금·선물 등 기타 자산"}.get(kind, kind))
        lines.extend(["", label])
        for _, row in data.iterrows():
            if kind in STATUS_LABELS or kind == "other":
                value = f'{_number(row["수량_prev"])} → {_number(row["수량_today"])} ({_number(row["quantity_diff"], True)})'
            else:
                value = f'{_weight(row["비중(%)_prev"])} → {_weight(row["비중(%)_today"])}'
            lines.append(f"- {row['종목명']}: {value}")
    lines.extend(["", "해석 노트"])
    if ai_analysis:
        for key in ["core_view", "manager_intent"]:
            if ai_analysis.get(key):
                lines.extend(["", str(ai_analysis[key])])
        for key, title in [
            ("evidence_based_observations", "판단의 근거"), ("portfolio_implications", "운용 관점"),
            ("what_to_watch_next", "다음 스냅샷에서 확인할 것"), ("data_limitations", "분석 한계"),
        ]:
            if ai_analysis.get(key):
                lines.extend(["", title, *[f"- {item}" for item in ai_analysis[key]]])
        if ai_analysis.get("key_risks"):
            lines.extend(["", "유의할 점", *[f"- {item['issue']}: {item['evidence']}" for item in ai_analysis["key_risks"]]])
        lines.extend(["", "해석 생성: " + " · ".join(str(ai_analysis[k]) for k in ["provider", "model"] if ai_analysis.get(k))])
    else:
        lines.append("AI 분석을 사용할 수 없습니다.")
    lines.append("\n수량 변화는 매매뿐 아니라 ETF 설정·환매 및 기업행동 때문일 수 있습니다. AI 해석보다 숫자 표를 우선하세요.")
    return "\n".join(lines)
