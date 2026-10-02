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
BODY_STYLE = "font-size:14px;line-height:1.85;color:#334155;"


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


def _paragraph(text: object) -> str:
    return "".join(
        f'<p style="margin:0 0 12px;{BODY_STYLE}">{_escape(p).replace(chr(10), "<br>")}</p>'
        for p in str(text).strip().split("\n\n") if p
    )


def _list(items: list) -> str:
    if not items:
        return ""
    return '<ul style="margin:0;padding-left:20px;' + BODY_STYLE + '">' + "".join(
        f'<li style="margin:0 0 9px;">{_escape(item)}</li>' for item in items
    ) + "</ul>"


def _card(title: str, body: str, subtitle: str = "", accent: str = "#e2e8f0") -> str:
    if not body:
        return ""
    note = f'<p style="margin:0 0 14px;font-size:12px;line-height:1.7;color:#64748b;">{_escape(subtitle)}</p>' if subtitle else ""
    return f'''<tr><td style="padding:0 0 14px;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"
           style="background:#ffffff;border:1px solid {accent};border-radius:14px;">
      <tr><td class="card-pad" style="padding:22px;">
        <h2 style="margin:0 0 12px;font-size:18px;line-height:1.4;color:#0f172a;">{_escape(title)}</h2>
        {note}{body}
      </td></tr>
    </table></td></tr>'''


def _stock_name(row: pd.Series, rank: bool = False) -> str:
    name = _escape(row["종목명"])
    ticker = re.fullmatch(r"([A-Z0-9.\-]+) US EQUITY", str(row["asset_key"]))
    if ticker:
        url = "https://www.tradingview.com/search/?query=" + quote(ticker[1])
        name = f'<a href="{url}" style="color:#0f172a;text-decoration:none;">{name}</a>'
    prefix = f'<span style="color:#64748b;">{int(row["rank_today"]):02d}&nbsp;</span>' if rank else ""
    return prefix + name


def _rank_move(row: pd.Series) -> str:
    before, after = row["rank_prev"], row["rank_today"]
    if pd.isna(before) or before > 10:
        return "TOP10 진입"
    if pd.isna(after) or after > 10:
        return "TOP10 이탈"
    diff = int(before - after)
    return f"↑ {diff}" if diff > 0 else f"↓ {abs(diff)}" if diff < 0 else "유지"


def _data_table(data: pd.DataFrame, kind: str) -> str:
    if data.empty:
        return ""
    headings = {
        "new": ["종목", "보유 수량", "현재 비중"], "removed": ["종목", "이전 수량", "이전 비중"],
        "bought": ["종목", "수량 변화", "증감률"], "sold": ["종목", "수량 변화", "증감률"],
        "top10": ["종목", "현재 비중", "순위 변화"], "weights": ["종목", "이전 → 현재", "변화"],
        "other": ["자산", "수량 이전 → 현재", "비중 변화"],
    }[kind]
    header = "".join(
        f'<th scope="col" style="padding:9px 4px;border-bottom:2px solid #e2e8f0;'
        f'color:#64748b;font-size:11px;text-align:{"left" if i == 0 else "right"};">{_escape(h)}</th>'
        for i, h in enumerate(headings)
    )
    rows = []
    for _, row in data.iterrows():
        name = _stock_name(row, rank=kind == "top10")
        if kind in {"new", "removed"}:
            side = "today" if kind == "new" else "prev"
            cells = [name, _number(row[f"수량_{side}"]), _weight(row[f"비중(%)_{side}"])]
        elif kind in {"bought", "sold"}:
            before, after = _number(row["수량_prev"]), _number(row["수량_today"])
            quantity = (f'<strong>{_number(row["quantity_diff"], True)}</strong><br>'
                        f'<span style="font-size:11px;color:#64748b;">{before} → {after}</span>')
            pct = row["quantity_change_pct"]
            cells = [name, quantity, "—" if pd.isna(pct) else f"{pct:+.2f}%"]
        elif kind == "top10":
            cells = [name, _weight(row["비중(%)_today"]), _rank_move(row)]
        elif kind == "other":
            status = STATUS_LABELS.get(row["quantity_status"], "수량 유지")
            cells = [name + f'<br><span style="font-size:11px;color:#64748b;">{status}</span>',
                     f'{_number(row["수량_prev"])} → {_number(row["수량_today"])}',
                     f'{_weight(row["비중(%)_today"])}<br><span style="font-size:11px;color:#64748b;">{_delta(row["diff_pctp"])}</span>']
        else:
            color = "#1d4ed8" if row["diff_pctp"] >= 0 else "#be123c"
            cells = [name, f'{_weight(row["비중(%)_prev"])} → {_weight(row["비중(%)_today"])}',
                     f'<span style="color:{color};font-weight:700;">{_delta(row["diff_pctp"])}</span>']
        rendered = "".join(
            f'<td style="padding:12px 4px;border-bottom:1px solid #edf2f7;vertical-align:top;'
            f'font-size:12px;line-height:1.65;color:#334155;text-align:{"left" if i == 0 else "right"};'
            f'{"width:48%;word-break:break-word;" if i == 0 else "width:26%;"}">{cell}</td>'
            for i, cell in enumerate(cells)
        )
        rows.append(f"<tr>{rendered}</tr>")
    return f'<table width="100%" cellspacing="0" cellpadding="0" border="0" style="border-collapse:collapse;table-layout:fixed;"><thead><tr>{header}</tr></thead><tbody>{"".join(rows)}</tbody></table>'


def _kpis(sections: dict[str, pd.DataFrame]) -> str:
    cells = []
    for key, color, bg in [("new", "#047857", "#ecfdf5"), ("removed", "#b45309", "#fffbeb"),
                           ("bought", "#1d4ed8", "#eff6ff"), ("sold", "#be123c", "#fff1f2")]:
        cells.append(f'''<td width="50%" style="padding:5px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:{bg};border-radius:12px;">
          <tr><td style="padding:15px 18px;color:{color};">
            <div style="font-size:12px;font-weight:700;">{STATUS_LABELS[key]}</div>
            <div style="margin-top:5px;font-size:27px;font-weight:800;">{len(sections[key])}<span style="font-size:12px;font-weight:400;"> 종목</span></div>
          </td></tr></table></td>''')
    return f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"><tr>{"".join(cells[:2])}</tr><tr>{"".join(cells[2:])}</tr></table>'


def _ai_cards(analysis: dict | None) -> str:
    if not analysis:
        return _card("AI 분석 상태", _paragraph("AI 분석을 사용할 수 없습니다. 아래 숫자와 구성 변화는 Python 계산 결과입니다."))
    source = " · ".join(str(analysis[k]) for k in ["provider", "model"] if analysis.get(k))
    cards = [_card("AI 상세 분석 · 참고 가설", _paragraph(analysis.get("one_line_take", ""))
                   + _paragraph(analysis.get("core_view", ""))
                   + '<h3 style="font-size:14px;color:#0f172a;">운용 의도 가설</h3>'
                   + _paragraph(analysis.get("manager_intent", "")),
                   source + " · 수량 사실 확인표를 검산했지만 자유 서술 전체의 정확성을 보장하지 않습니다. 숫자 표를 우선하세요.", "#c7d2fe")]
    for key, title in [
        ("what_changed_in_plain_english", "구조적 변화"),
        ("evidence_based_observations", "데이터로 확인된 근거"),
        ("portfolio_implications", "포트폴리오 영향"),
    ]:
        cards.append(_card(title, _list(analysis.get(key, []))))
    scenarios = []
    for key, title in [("base_case", "기본"), ("bull_case", "낙관"), ("bear_case", "비관")]:
        item = analysis.get(key, {})
        confidence = {"low": "낮음", "medium": "보통", "high": "높음"}.get(item.get("confidence"), "미정")
        scenarios.append(f'<h3 style="margin:18px 0 8px;font-size:14px;color:#1e293b;">{title} 시나리오 · 가설 신뢰도 {confidence}</h3>'
                         + _paragraph(item.get("thesis", "")) + _list(item.get("implications", [])))
    cards.append(_card("시나리오와 확인 조건", "".join(scenarios)))
    risk_body = "".join(
        '<h3 style="margin:16px 0 6px;font-size:14px;color:#1e293b;">' + _escape(item.get("issue", ""))
        + ' <span style="font-size:11px;color:#64748b;">위험 ' + {"low": "낮음", "medium": "보통", "high": "높음"}.get(item.get("level"), "미정") + '</span>'
        + '</h3>' + _paragraph(item.get("evidence", "")) for item in analysis.get("key_risks", [])
    )
    cards.append(_card("핵심 리스크", risk_body))
    watch_body = "".join(
        '<h3 style="margin:16px 0 6px;font-size:14px;color:#1e293b;">' + _escape(item.get("name", "")) + '</h3>'
        + _paragraph("해석 방향: " + {"positive": "긍정", "negative": "부정", "neutral": "중립"}.get(item.get("direction"), "미정"))
        + _paragraph(item.get("reason", "")) + _paragraph("다음 확인: " + str(item.get("next_check", "")))
        for item in analysis.get("watchlist", [])
    )
    cards.append(_card("관찰 항목", watch_body))
    cards.append(_card("다음 확인 포인트", _list(analysis.get("what_to_watch_next", []))))
    cards.append(_card("분석 한계", _list(analysis.get("data_limitations", []))))
    return "".join(cards)


def build_compare_report_html(
    compared: pd.DataFrame, title: str = REPORT_TITLE, report_generated_at: str | None = None,
    ai_analysis: dict[str, Any] | None = None,
    previous_label: str | None = None, current_label: str | None = None,
) -> str:
    sections = _sections(compared)
    generated = _generated_at(report_generated_at)
    period = f"{previous_label} → {current_label}" if previous_label and current_label else "직전 정상 스냅샷 대비"
    summary = _summary(compared)
    before, after = (_concentration(compared, 10, s) for s in ["prev", "today"])
    summary_body = _list(summary)
    summary_body += f'<p style="margin:14px 0 0;font-size:12px;color:#64748b;">TOP10 비중 합계 {_weight(after)} · 이전 대비 {_delta(after - before)}</p>'
    content = _card("이번 스냅샷의 핵심", summary_body)
    for key in ["new", "removed", "bought", "sold"]:
        content += _card(f"{STATUS_LABELS[key]} · {len(sections[key])}종목", _data_table(sections[key], key))
    if not any(len(sections[k]) for k in STATUS_LABELS):
        content += _card("구성 변화", _paragraph("편입·편출 및 기존 주식의 수량 변화가 없습니다."))
    content += _ai_cards(ai_analysis)
    content += _card("현재 TOP10", _data_table(sections["top10"], "top10"), "현재 비중과 순위 변화만 간결하게 표시합니다.")
    stocks = compared[compared["asset_type"] == "stock"]
    exits = stocks[(stocks["rank_prev"] <= 10) & (stocks["rank_today"].isna() | (stocks["rank_today"] > 10))]
    if not exits.empty:
        content += _card("TOP10 이탈", _list(exits["종목명"].tolist()))
    content += _card("주요 비중 변화", _data_table(sections["weights"], "weights"),
                     "보조 지표 · 기존 종목 중 0.10%p 이상 변화한 최대 5개. 비중 변화는 매매를 뜻하지 않습니다.")
    content += _card("주식 외 자산 변화", _data_table(sections["other"], "other"),
                     "수량 변화 또는 0.10%p 이상 비중 변화만 표시합니다. 선물 평가액 비중은 실제 시장 노출과 다릅니다.")
    preheader = _escape(" / ".join(summary))
    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{_escape(title)}</title>
    <style>@media only screen and (max-width:600px){{.card-pad{{padding:16px!important;}}.report-title{{font-size:23px!important;}}}}</style>
    </head><body style="margin:0;padding:0;background:#f1f5f9;font-family:'Apple SD Gothic Neo','Malgun Gothic',Arial,sans-serif;">
    <div style="display:none;max-height:0;overflow:hidden;mso-hide:all;">{preheader}</div>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#f1f5f9;">
    <tr><td align="center" style="padding:20px 10px;">
    <!--[if mso]><table role="presentation" width="680"><tr><td><![endif]-->
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:680px;">
    <tr><td class="card-pad" style="padding:28px 24px;background:#0f172a;border-top:4px solid #818cf8;border-radius:14px 14px 0 0;">
      <div style="font-size:11px;font-weight:700;letter-spacing:2px;color:#a5b4fc;">TIME / PORTFOLIO MONITOR</div>
      <h1 class="report-title" style="margin:14px 0 12px;font-size:26px;line-height:1.4;color:#ffffff;">{_escape(title)}</h1>
      <div style="font-size:13px;line-height:1.7;color:#cbd5e1;">{_escape(period)}</div>
      <div style="margin-top:5px;font-size:11px;color:#94a3b8;">생성 {_escape(generated)}</div>
    </td></tr>
    <tr><td style="padding:12px 0 14px;">{_kpis(sections)}</td></tr>
    {content}
    <tr><td style="padding:10px 14px;text-align:center;font-size:11px;line-height:1.8;color:#64748b;">
      공개 구성종목 데이터의 자동 비교 결과입니다.<br>
      수량 변화에는 설정·환매 및 기업행동이 포함될 수 있으며 AI 해석은 데이터 기반 가설입니다.
    </td></tr></table>
    <!--[if mso]></td></tr></table><![endif]-->
    </td></tr></table></body></html>'''


def build_compare_report_text(
    compared: pd.DataFrame, report_generated_at: str | None = None,
    ai_analysis: dict[str, Any] | None = None,
    previous_label: str | None = None, current_label: str | None = None,
) -> str:
    lines = [REPORT_TITLE, _generated_at(report_generated_at)]
    if previous_label and current_label:
        lines.append(f"비교: {previous_label} → {current_label}")
    lines.extend(_summary(compared))
    for kind, data in _sections(compared).items():
        if data.empty:
            continue
        title = STATUS_LABELS.get(kind, {"top10": "현재 TOP10", "weights": "주요 비중 변화", "other": "주식 외 자산 변화"}.get(kind, kind))
        lines.extend(["", title])
        for _, row in data.iterrows():
            if kind in {"bought", "sold"}:
                value = f'{_number(row["수량_prev"])} → {_number(row["수량_today"])} ({_number(row["quantity_diff"], True)})'
            else:
                value = f'{_weight(row["비중(%)_prev"])} → {_weight(row["비중(%)_today"])}'
            lines.append(f"- {row['종목명']}: {value}")
    if ai_analysis:
        lines.extend(["", "AI 상세 분석", " · ".join(str(ai_analysis[k]) for k in ["provider", "model"] if ai_analysis.get(k))])
        for key, title in [("one_line_take", "한 줄 결론"), ("core_view", "핵심 해석"), ("manager_intent", "운용 의도 가설")]:
            lines.extend(["", title, str(ai_analysis.get(key, ""))])
        for key, title in [
            ("what_changed_in_plain_english", "구조적 변화"), ("evidence_based_observations", "데이터로 확인된 근거"),
            ("portfolio_implications", "포트폴리오 영향"), ("what_to_watch_next", "다음 확인 포인트"), ("data_limitations", "분석 한계"),
        ]:
            lines.extend(["", title, *[f"- {item}" for item in ai_analysis.get(key, [])]])
        for key, title in [("base_case", "기본 시나리오"), ("bull_case", "낙관 시나리오"), ("bear_case", "비관 시나리오")]:
            scenario = ai_analysis.get(key, {})
            lines.extend(["", title, str(scenario.get("thesis", "")), *[f"- {item}" for item in scenario.get("implications", [])]])
        lines.extend(["", "핵심 리스크", *[f"- {item['issue']}: {item['evidence']}" for item in ai_analysis.get("key_risks", [])]])
        lines.extend(["", "관찰 항목", *[f"- {item['name']}: {item['reason']} / 다음 확인: {item['next_check']}" for item in ai_analysis.get("watchlist", [])]])
    else:
        lines.extend(["", "AI 분석을 사용할 수 없습니다."])
    return "\n".join(lines)
