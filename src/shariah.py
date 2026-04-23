"""
Stage 6 — Shariah Compliance Screening
Programmatic AAOIFI-standard screening.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from src.models import Opportunity, ShariahStatus

# Business activity deny-list (sector/industry keywords → non-compliant)
_DENIED_SECTORS = {
    "Financial Services",
    "Insurance",
}

_DENIED_INDUSTRIES = {
    "Banks—Diversified",
    "Banks—Regional",
    "Credit Services",
    "Insurance—Diversified",
    "Insurance—Life",
    "Insurance—Property & Casualty",
    "Gambling",
    "Beverages—Wineries & Distilleries",
    "Tobacco",
    "Adult Entertainment",
    "Aerospace & Defense",  # flagged as ambiguous (weapons)
}

# Industries that are ambiguous (flag as Partial, not outright No)
_AMBIGUOUS_INDUSTRIES = {
    "Aerospace & Defense",
    "Biotechnology",        # may involve pork derivatives
}


def _activity_screen(sector: str, industry: str) -> tuple[str, list[str]]:
    """
    Check business activity compliance.
    Returns (screen_result, reasons) where screen_result is Pass/Fail/Ambiguous.
    """
    reasons = []

    # Normalize for comparison (strip whitespace)
    sector = (sector or "").strip()
    industry = (industry or "").strip()

    for denied in _DENIED_SECTORS:
        if denied.lower() in sector.lower():
            reasons.append(f"Sector '{sector}' involves non-compliant activity ({denied})")
            return "Fail", reasons

    for denied in _DENIED_INDUSTRIES:
        if denied.lower() in industry.lower():
            if denied in _AMBIGUOUS_INDUSTRIES:
                reasons.append(f"Industry '{industry}' may involve non-compliant activity — review required")
                return "Ambiguous", reasons
            else:
                reasons.append(f"Industry '{industry}' involves non-compliant activity ({denied})")
                return "Fail", reasons

    return "Pass", reasons


def _financial_screens(opp: Opportunity) -> tuple[bool, list[str]]:
    """
    Run AAOIFI financial ratio screens.
    Returns (all_pass, reasons_for_any_failure).
    """
    mcap = opp.mcap
    reasons = []

    if not mcap or mcap <= 0:
        reasons.append("Market cap unavailable — financial screens skipped")
        return True, reasons   # can't screen, don't fail

    debt_ratio  = opp.total_debt / mcap
    cash_ratio  = opp.total_cash / mcap
    recv_ratio  = opp.accounts_receivable / mcap

    all_pass = True

    if debt_ratio > config.SHARIAH_DEBT_THRESHOLD:
        reasons.append(
            f"Debt ratio {debt_ratio:.1%} exceeds {config.SHARIAH_DEBT_THRESHOLD:.0%} threshold"
        )
        all_pass = False

    if cash_ratio > config.SHARIAH_CASH_THRESHOLD:
        reasons.append(
            f"Cash/securities ratio {cash_ratio:.1%} exceeds {config.SHARIAH_CASH_THRESHOLD:.0%} threshold"
        )
        all_pass = False

    if recv_ratio > config.SHARIAH_RECV_THRESHOLD:
        reasons.append(
            f"Receivables ratio {recv_ratio:.1%} exceeds {config.SHARIAH_RECV_THRESHOLD:.0%} threshold"
        )
        all_pass = False

    # Interest income screen
    if opp.total_revenue > 0:
        interest_ratio = opp.interest_income / opp.total_revenue
        if interest_ratio > config.SHARIAH_INTEREST_THRESHOLD:
            reasons.append(
                f"Interest income {interest_ratio:.1%} of revenue exceeds {config.SHARIAH_INTEREST_THRESHOLD:.0%} threshold"
            )
            all_pass = False

    return all_pass, reasons


def check_shariah(opportunities: list[Opportunity]) -> list[Opportunity]:
    """
    Screen each opportunity for Shariah compliance.
    Attaches ShariahStatus to each Opportunity.
    """
    for opp in opportunities:
        activity_result, activity_reasons = _activity_screen(opp.sector, opp.industry)
        fin_pass, fin_reasons = _financial_screens(opp)

        mcap = opp.mcap or 1  # avoid division by zero in ratio storage
        debt_ratio = opp.total_debt / mcap
        cash_ratio = opp.total_cash / mcap
        recv_ratio = opp.accounts_receivable / mcap

        all_reasons = activity_reasons + fin_reasons

        if activity_result == "Fail":
            compliant = "No"
        elif activity_result == "Ambiguous" or not fin_pass:
            compliant = "Partial"
        else:
            compliant = "Yes"

        opp.shariah = ShariahStatus(
            compliant=compliant,
            debt_ratio=round(debt_ratio, 4),
            cash_ratio=round(cash_ratio, 4),
            receivables_ratio=round(recv_ratio, 4),
            activity_screen=activity_result,
            reasons=all_reasons,
        )

    return opportunities
