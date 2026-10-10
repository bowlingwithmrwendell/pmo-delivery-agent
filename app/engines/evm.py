"""Earned Value Management (EVM) metrics.

Inputs (currency amounts, as of the status date):
    BAC  Budget at Completion
    PV   Planned Value  (budgeted cost of work scheduled to date)
    EV   Earned Value   (budgeted cost of work actually performed)
    AC   Actual Cost    (actual cost of work performed)

Standard PMI formulas:
    SV   = EV - PV            SPI  = EV / PV
    CV   = EV - AC            CPI  = EV / AC
    SV%  = SV / PV x 100      CV%  = CV / EV x 100
    EAC  = BAC / CPI          ETC  = EAC - AC
    VAC  = BAC - EAC          TCPI = (BAC - EV) / (BAC - AC)

Optional schedule variance in days, when elapsed working days are known:
    SV(days) = SV / (PV / elapsed_days)      (PV burn rate per day)

Ratios that would divide by zero are returned as None rather than guessed.
All arithmetic uses Decimal; results are rounded half-up only for display.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .explain import explain

MONEY = Decimal("0.01")
INDEX = Decimal("0.01")
PCT = Decimal("0.1")


class EVMInputError(ValueError):
    pass


def D(value) -> Decimal:
    """Convert to Decimal via str() so floats don't carry binary noise."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise EVMInputError(f"Not a number: {value!r}")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise EVMInputError(f"Not a number: {value!r}") from exc


def q(value: Decimal | None, step: Decimal) -> Decimal | None:
    return None if value is None else value.quantize(step, rounding=ROUND_HALF_UP)


def _div(a: Decimal, b: Decimal) -> Decimal | None:
    return None if b == 0 else a / b


@dataclass(frozen=True)
class EVMResult:
    bac: Decimal
    pv: Decimal
    ev: Decimal
    ac: Decimal
    sv: Decimal
    cv: Decimal
    spi: Decimal | None
    cpi: Decimal | None
    sv_pct: Decimal | None
    cv_pct: Decimal | None
    eac: Decimal | None
    etc: Decimal | None
    vac: Decimal | None
    tcpi: Decimal | None
    percent_complete: Decimal | None
    percent_spent: Decimal | None
    sv_days: Decimal | None
    elapsed_days: int | None = None

    # Unrounded variances used for RAG decisions (never display-rounded first).
    @property
    def schedule_variance_pct_exact(self) -> Decimal | None:
        return self.sv_pct

    @property
    def cost_variance_pct_exact(self) -> Decimal | None:
        return self.cv_pct

    def as_dict(self) -> dict:
        def s(v, step):
            r = q(v, step)
            return None if r is None else str(r)

        return {
            "bac": s(self.bac, MONEY),
            "pv": s(self.pv, MONEY),
            "ev": s(self.ev, MONEY),
            "ac": s(self.ac, MONEY),
            "sv": s(self.sv, MONEY),
            "cv": s(self.cv, MONEY),
            "spi": s(self.spi, INDEX),
            "cpi": s(self.cpi, INDEX),
            "sv_pct": s(self.sv_pct, PCT),
            "cv_pct": s(self.cv_pct, PCT),
            "eac": s(self.eac, MONEY),
            "etc": s(self.etc, MONEY),
            "vac": s(self.vac, MONEY),
            "tcpi": s(self.tcpi, INDEX),
            "percent_complete": s(self.percent_complete, PCT),
            "percent_spent": s(self.percent_spent, PCT),
            "sv_days": s(self.sv_days, PCT),
            "explanation": self.explanations(),
        }

    def explanations(self) -> dict:
        """Formula, inputs and reasoning for every metric in as_dict()."""
        m = lambda v: None if v is None else str(q(v, MONEY))  # noqa: E731
        i = lambda v: None if v is None else str(q(v, INDEX))  # noqa: E731
        p = lambda v: None if v is None else str(q(v, PCT))    # noqa: E731
        bac, pv, ev, ac = m(self.bac), m(self.pv), m(self.ev), m(self.ac)
        undefined = "is 0, so this ratio is undefined and returned as null rather than guessed"

        def ratio(name, formula, num_label, num, den_label, den, result, fmt):
            if result is None:
                return explain(formula, {num_label: num, den_label: den}, f"{den_label.upper()} {undefined}.")
            return explain(formula, {num_label: num, den_label: den},
                           f"{num} / {den} = {fmt(result)}" + (
                               "" if name not in ("spi", "cpi") else
                               f" ({'behind schedule' if name == 'spi' else 'over budget'} when below 1.00)"
                               if result < 1 else ""))

        out = {
            "sv": explain("SV = EV - PV", {"ev": ev, "pv": pv},
                          f"{ev} - {pv} = {m(self.sv)}; negative means behind schedule."),
            "cv": explain("CV = EV - AC", {"ev": ev, "ac": ac},
                          f"{ev} - {ac} = {m(self.cv)}; negative means over budget."),
            "spi": ratio("spi", "SPI = EV / PV", "ev", ev, "pv", pv, self.spi, i),
            "cpi": ratio("cpi", "CPI = EV / AC", "ev", ev, "ac", ac, self.cpi, i),
            "sv_pct": explain("SV% = SV / PV x 100", {"sv": m(self.sv), "pv": pv},
                              f"PV {undefined}." if self.sv_pct is None else
                              f"{m(self.sv)} / {pv} x 100 = {p(self.sv_pct)}%. Adverse beyond 5% is "
                              "AMBER, beyond 15% is RED."),
            "cv_pct": explain("CV% = CV / EV x 100", {"cv": m(self.cv), "ev": ev},
                              f"EV {undefined}." if self.cv_pct is None else
                              f"{m(self.cv)} / {ev} x 100 = {p(self.cv_pct)}%. Adverse beyond 5% is "
                              "AMBER, beyond 15% is RED."),
            "eac": explain("EAC = BAC / CPI", {"bac": bac, "cpi": i(self.cpi)},
                           "CPI is null or 0, so EAC is undefined." if self.eac is None else
                           f"{bac} / {i(self.cpi)} (unrounded CPI used) = {m(self.eac)}: the forecast "
                           "total cost if the current cost efficiency continues."),
            "etc": explain("ETC = EAC - AC", {"eac": m(self.eac), "ac": ac},
                           "EAC is undefined, so ETC is too." if self.etc is None else
                           f"{m(self.eac)} - {ac} = {m(self.etc)} still to spend."),
            "vac": explain("VAC = BAC - EAC", {"bac": bac, "eac": m(self.eac)},
                           "EAC is undefined, so VAC is too." if self.vac is None else
                           f"{bac} - {m(self.eac)} = {m(self.vac)}; negative is a forecast overrun."),
            "tcpi": explain("TCPI = (BAC - EV) / (BAC - AC)", {"bac": bac, "ev": ev, "ac": ac},
                            "BAC - AC is 0 (budget fully spent), so TCPI is undefined."
                            if self.tcpi is None else
                            f"({bac} - {ev}) / ({bac} - {ac}) = {i(self.tcpi)}: the cost efficiency "
                            "needed on remaining work to finish on budget."),
            "percent_complete": explain("% complete = EV / BAC x 100", {"ev": ev, "bac": bac},
                                        f"{ev} / {bac} x 100 = {p(self.percent_complete)}%."),
            "percent_spent": explain("% spent = AC / BAC x 100", {"ac": ac, "bac": bac},
                                     f"{ac} / {bac} x 100 = {p(self.percent_spent)}%."),
            "sv_days": explain("SV(days) = SV / (PV / elapsed working days)",
                               {"sv": m(self.sv), "pv": pv, "elapsed_days": self.elapsed_days},
                               "Elapsed days not recorded (or PV is 0), so SV in days is not computed."
                               if self.sv_days is None else
                               f"PV burns at {pv} / {self.elapsed_days} per day; {m(self.sv)} / that "
                               f"rate = {p(self.sv_days)} days."),
        }
        return out


def compute_evm(bac, pv, ev, ac, elapsed_days: int | None = None) -> EVMResult:
    bac, pv, ev, ac = D(bac), D(pv), D(ev), D(ac)
    for name, v in (("BAC", bac), ("PV", pv), ("EV", ev), ("AC", ac)):
        if v < 0:
            raise EVMInputError(f"{name} cannot be negative")
    if bac == 0:
        raise EVMInputError("BAC must be greater than zero")
    if elapsed_days is not None and (isinstance(elapsed_days, bool) or elapsed_days < 0):
        raise EVMInputError("elapsed_days must be a non-negative integer")

    sv = ev - pv
    cv = ev - ac
    spi = _div(ev, pv)
    cpi = _div(ev, ac)
    sv_pct = None if pv == 0 else sv / pv * 100
    cv_pct = None if ev == 0 else cv / ev * 100
    eac = None if not cpi else bac / cpi
    etc = None if eac is None else eac - ac
    vac = None if eac is None else bac - eac
    tcpi = _div(bac - ev, bac - ac)
    sv_days = None
    if elapsed_days and pv > 0:
        sv_days = sv / (pv / D(elapsed_days))

    return EVMResult(
        bac=bac, pv=pv, ev=ev, ac=ac,
        sv=sv, cv=cv, spi=spi, cpi=cpi,
        sv_pct=sv_pct, cv_pct=cv_pct,
        eac=eac, etc=etc, vac=vac, tcpi=tcpi,
        percent_complete=ev / bac * 100,
        percent_spent=ac / bac * 100,
        sv_days=sv_days,
        elapsed_days=elapsed_days,
    )
