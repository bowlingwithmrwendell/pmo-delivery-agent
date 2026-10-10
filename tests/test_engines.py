"""Engine tests. Every expected value below is calculated by hand in the comments."""
from datetime import date
from decimal import Decimal

import pytest

from app.engines.dependencies import analyse_dependencies, find_cycles
from app.engines.evm import EVMInputError, compute_evm
from app.engines.milestones import milestone_health
from app.engines.rag import AMBER, GREEN, RED, determine_rag, variance_status
from app.engines.raid import RaidInputError, raid_summary, score_item
from app.engines.report import narrative_is_grounded
from app.engines.risk import RiskInputError, score_risk
from app.engines.types import CrossDependency, Milestone, RaidItem


# --- risk exposure -----------------------------------------------------------

@pytest.mark.parametrize("p,i,score,band,label", [
    (4, 4, 16, "HIGH", "16 (HIGH)"),   # R-101 in the spec
    (3, 5, 15, "HIGH", "15 (HIGH)"),   # R-102: lowest HIGH score
    (2, 4, 8, "MEDIUM", "8 (MED)"),    # R-103: lowest MEDIUM score
    (3, 4, 12, "MEDIUM", "12 (MED)"),  # highest MEDIUM score
    (2, 3, 6, "LOW", "6 (LOW)"),       # highest LOW score
    (1, 1, 1, "LOW", "1 (LOW)"),
    (5, 5, 25, "HIGH", "25 (HIGH)"),
])
def test_risk_exposure_and_band(p, i, score, band, label):
    r = score_risk(p, i)
    assert (r.score, r.band, r.label) == (score, band, label)


def test_risk_band_policy():
    assert score_risk(4, 4).escalate_to_sponsor is True
    assert score_risk(4, 4).review_interval_days == 7
    assert score_risk(2, 4).review_interval_days == 14
    assert score_risk(2, 3).review_interval_days == 30
    assert score_risk(2, 3).escalate_to_sponsor is False


@pytest.mark.parametrize("p,i", [(0, 3), (6, 3), (3, 0), (True, 3), (2.5, 3), ("3", 3)])
def test_risk_rejects_out_of_scale_inputs(p, i):
    with pytest.raises(RiskInputError):
        score_risk(p, i)


def test_issue_probability_is_certain():
    # An issue has already happened: probability fixed at 5. 5 x 4 = 20 (HIGH).
    item = RaidItem("I-1", "P", "ISSUE", "Vendor", "x", impact=4)
    assert score_item(item)["score_label"] == "20 (HIGH)"


def test_raid_validation():
    with pytest.raises(RaidInputError):
        score_item(RaidItem("R-1", "P", "RISK", "Tech", "no impact", probability=3))
    with pytest.raises(RaidInputError):
        score_item(RaidItem("R-1", "P", "RISK", "Tech", "flag on risk", 2, 2, blocker=True))
    with pytest.raises(RaidInputError):
        score_item(RaidItem("I-1", "P", "ISSUE", "Tech", "cp w/o blocker", impact=3, critical_path=True))


# --- earned value -------------------------------------------------------------

def test_evm_data_migration_stream():
    # BAC 2,000,000  PV 1,000,000  EV 940,000  AC 921,000  elapsed 66 days
    e = compute_evm("2000000", "1000000", "940000", "921000", 66).as_dict()
    assert e["sv"] == "-60000.00"          # 940,000 - 1,000,000
    assert e["cv"] == "19000.00"           # 940,000 - 921,000
    assert e["spi"] == "0.94"              # 940,000 / 1,000,000
    assert e["cpi"] == "1.02"              # 940,000 / 921,000 = 1.0206
    assert e["sv_pct"] == "-6.0"           # -60,000 / 1,000,000 x 100
    assert e["cv_pct"] == "2.0"            # 19,000 / 940,000 x 100 = 2.02
    assert e["eac"] == "1959574.47"        # 2,000,000 x 921,000 / 940,000
    assert e["etc"] == "1038574.47"        # EAC - 921,000
    assert e["vac"] == "40425.53"          # 2,000,000 - EAC
    assert e["tcpi"] == "0.98"             # 1,060,000 / 1,079,000 = 0.9824
    assert e["sv_days"] == "-4.0"          # -60,000 / (1,000,000 / 66) = -3.96
    assert e["percent_complete"] == "47.0"  # 940,000 / 2,000,000


def test_evm_red_stream():
    # BAC 800,000  PV 400,000  EV 320,000  AC 400,000
    e = compute_evm("800000", "400000", "320000", "400000").as_dict()
    assert (e["spi"], e["cpi"]) == ("0.80", "0.80")
    assert e["eac"] == "1000000.00"        # 800,000 / 0.8
    assert e["vac"] == "-200000.00"
    assert e["tcpi"] == "1.20"             # 480,000 / 400,000
    assert e["cv_pct"] == "-25.0"          # -80,000 / 320,000


def test_evm_zero_denominators_return_none_not_a_guess():
    e = compute_evm("100", "0", "0", "0").as_dict()
    assert e["spi"] is None and e["cpi"] is None and e["eac"] is None and e["sv_pct"] is None


def test_evm_rejects_bad_inputs():
    with pytest.raises(EVMInputError):
        compute_evm("0", "1", "1", "1")
    with pytest.raises(EVMInputError):
        compute_evm("100", "-1", "1", "1")
    with pytest.raises(EVMInputError):
        compute_evm("100", "abc", "1", "1")


# --- RAG ----------------------------------------------------------------------

@pytest.mark.parametrize("pct,expected", [
    ("-5.0", GREEN),   # exactly 5% is "within tolerance"
    ("-5.1", AMBER),
    ("-15.0", AMBER),  # exactly 15% is still "between 5% and 15%"
    ("-15.1", RED),
    ("12.0", GREEN),   # favourable variance never degrades status
    (None, GREEN),
])
def test_variance_boundaries(pct, expected):
    assert variance_status(None if pct is None else Decimal(pct)) == expected


def _evm(ev, ac, pv="100"):
    return compute_evm("1000", pv, ev, ac)


def test_rag_cost_overrun_is_red():
    # CV% = (100 - 116) / 100 = -16% -> RED
    r = determine_rag(_evm("100", "116"), [])
    assert r["status"] == RED and r["cost_status"] == RED and r["executive_intervention_required"]


def test_rag_unmitigated_medium_risk_is_amber():
    risk = RaidItem("R-1", "P", "RISK", "Compliance", "x", 3, 3)  # 9 MED, no owner
    assert determine_rag(_evm("100", "100"), [risk])["status"] == AMBER


def test_rag_mitigated_high_risk_is_amber_unmitigated_is_red():
    mitigated = RaidItem("R-1", "P", "RISK", "Tech", "x", 4, 4, "plan", "Lead")
    bare = RaidItem("R-2", "P", "RISK", "Tech", "x", 4, 4)
    assert determine_rag(_evm("100", "100"), [mitigated])["status"] == AMBER
    assert determine_rag(_evm("100", "100"), [bare])["status"] == RED


def test_rag_blockers_and_closed_items():
    blocker = RaidItem("I-1", "P", "ISSUE", "Vendor", "x", impact=4, mitigation="m", owner="o", blocker=True)
    cp = RaidItem("I-2", "P", "ISSUE", "Gov", "x", impact=5, mitigation="m", owner="o",
                  blocker=True, critical_path=True)
    closed = RaidItem("R-3", "P", "RISK", "Tech", "x", 5, 5, status="CLOSED")
    assert determine_rag(_evm("100", "100"), [blocker])["status"] == AMBER
    assert determine_rag(_evm("100", "100"), [cp])["status"] == RED
    assert determine_rag(_evm("100", "100"), [closed])["status"] == GREEN


def test_raid_summary_counts():
    items = [RaidItem("R-1", "P", "RISK", "T", "x", 4, 4),                          # HIGH, unmitigated
             RaidItem("R-2", "P", "RISK", "T", "x", 2, 4, "m", "o"),                # MED, mitigated
             RaidItem("I-3", "P", "ISSUE", "T", "x", impact=2, blocker=True),       # 10 MED blocker
             RaidItem("R-4", "P", "RISK", "T", "x", 5, 5, status="CLOSED")]         # excluded
    s = raid_summary(items)
    assert s["open_items"] == 3
    assert s["by_band"] == {"HIGH": 1, "MEDIUM": 2, "LOW": 0}
    assert s["unmitigated_high"] == 1 and s["unmitigated_medium"] == 1
    assert s["open_critical_blockers"] == 1 and s["critical_path_blocked"] is False


# --- milestones ---------------------------------------------------------------

def test_milestone_completion_excludes_not_yet_due():
    d = date.fromisoformat
    ms = [Milestone("A", "P", "a", d("2026-09-01"), d("2026-09-01"), d("2026-09-01")),
          Milestone("B", "P", "b", d("2026-09-15"), d("2026-09-20")),           # due, not done
          Milestone("C", "P", "c", d("2026-12-01"), d("2026-12-01"), d("2026-10-01"))]  # early, not due
    h = milestone_health(ms, d("2026-10-01"), "85")
    assert h["due_to_date"] == 2 and h["completed_of_due"] == 1
    assert h["completion_rate_pct"] == "50.0"
    assert h["completion_status"] == RED          # (85-50)/85 = 41% short
    assert h["overdue"][0]["id"] == "B" and h["overdue"][0]["days_overdue"] == 11


# --- dependencies -------------------------------------------------------------

def test_dependency_conflict_and_float():
    d = date.fromisoformat
    ms = [Milestone("M1", "A", "m1", d("2026-11-06"), d("2026-11-13")),
          Milestone("M2", "B", "m2", d("2026-10-30"), d("2026-10-30"))]
    deps = [CrossDependency("D1", "A", "M1", "C", d("2026-11-06")),   # 7 days late
            CrossDependency("D2", "B", "M2", "C", d("2026-11-02"))]   # 3 days float < 5
    r = {x["id"]: x for x in analyse_dependencies(deps, ms)["dependencies"]}
    assert r["D1"]["status"] == "CONFLICT" and r["D1"]["slip_days"] == 7
    assert r["D2"]["status"] == "AT_RISK" and r["D2"]["float_days"] == 3


def test_circular_dependency_detected_once():
    x = date(2026, 1, 1)
    deps = [CrossDependency("1", "B", "m", "A", x), CrossDependency("2", "C", "m", "B", x),
            CrossDependency("3", "A", "m", "C", x)]
    assert find_cycles(deps) == [["A", "B", "C", "A"]]


# --- narrative grounding guard ------------------------------------------------

def test_grounding_guard_flags_invented_numbers():
    facts = {"spi": "0.94", "sv_days": "-4.0", "id": "R-101"}
    assert narrative_is_grounded("SPI is 0.94, about 4 days behind; see R-101.", facts) == (True, [])
    ok, unknown = narrative_is_grounded("SPI is 0.94 and we expect recovery by Sprint 15.", facts)
    assert not ok and unknown == ["15"]
