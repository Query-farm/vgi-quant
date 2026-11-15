"""Plot SQL-returned model repricing and convention comparisons."""

import matplotlib.pyplot as plt
import numpy as np
from vgi_notebooks import finish

SOURCE = "Authored inputs · actual VGI Quant v0.5.0 / QuantLib outputs · no observed market data"
COLORS = ["#327659", "#B16D44", "#397F91"]


def option_changes(curve, extent):
    """Compare model repricing against fixed spot derivatives."""
    fig, ax = plt.subplots(figsize=(11, 5.8))
    for column, label, style, color in [
        ("exact_change", "Full model repricing", "-", COLORS[0]),
        ("delta_change", "Delta only", "--", COLORS[1]),
        ("delta_gamma_change", "Delta + gamma", ":", COLORS[2]),
    ]:
        ax.plot(curve.move_pct, curve[column], style, color=color, lw=2.4, label=label)
    ax.axhline(0, color="#AAB6B0", lw=0.8)
    ax.set(xlabel="Spot-price shock (%)", ylabel="Call value change\n(currency units per underlying unit)")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.02), ncol=3, fontsize=9)
    finish(
        fig,
        "The tangent misses curvature as spot moves",
        f"European call · ±{extent}% spot range · time, volatility and rate held fixed",
        SOURCE + "\nNo dividend yield or contract multiplier; model comparison, not hedge performance.",
        name="option-repricing",
    )


def option_errors(curve, extent):
    """Keep approximation errors in price units."""
    fig, ax = plt.subplots(figsize=(11, 5.6))
    ax.plot(curve.move_pct, curve.delta_error, "--", color=COLORS[1], lw=2, label="Delta-only error")
    ax.plot(curve.move_pct, curve.delta_gamma_error, color=COLORS[2], lw=2.4, label="Delta + gamma error")
    ax.axhline(0, color="#243E32", lw=1)
    ax.set(
        xlabel="Spot-price shock (%)", ylabel="Approximation minus full change\n(currency units per underlying unit)"
    )
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.02), ncol=2, fontsize=9)
    finish(
        fig,
        "Curvature helps locally; residuals remain measurable",
        f"Fixed-time comparison · ±{extent}% range · positive residual overstates the model change",
        SOURCE + "\nLocal delta and gamma stay fixed at the initial spot in every scenario.",
        name="option-errors",
    )


def bond_changes(curve, extent):
    """Show full yield repricing for three fixed schedules."""
    fig, ax = plt.subplots(figsize=(11, 5.8))
    for years, color in zip(sorted(curve.years.unique()), COLORS, strict=True):
        g = curve[curve.years == years]
        ax.plot(g.shock_bp, g.full_change, color=color, lw=2.4, label=f"{years}-year maturity")
    ax.axhline(0, color="#AAB6B0", lw=0.8)
    ax.set(
        xlabel="Annual yield change (basis points; 1 bp = 0.0001)",
        ylabel="Full clean-price change\n(quote units per 100 nominal)",
    )
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.02), ncol=3, fontsize=9)
    finish(
        fig,
        "Longer fixed schedules respond more to the same yield shift",
        f"±{extent} bp range · 5% coupon / initial yield · semiannual compounding",
        SOURCE + "\nEvaluation/start: 2026-06-15; Actual/Actual ISDA, null calendar, no elapsed accrual.",
        name="bond-repricing",
    )


def bond_errors(curve, extent):
    """Compare fixed first- and second-order yield estimates."""
    fig, axes = plt.subplots(1, 3, figsize=(12, 5.5), sharex=True, sharey=True)
    for ax, years in zip(axes, sorted(curve.years.unique()), strict=True):
        g = curve[curve.years == years]
        ax.plot(g.shock_bp, g.duration_error, "--", color=COLORS[1], lw=2, label="Duration only")
        ax.plot(g.shock_bp, g.second_order_error, color=COLORS[2], lw=2.4, label="+ Convexity")
        ax.axhline(0, color="#AAB6B0", lw=0.8)
        ax.set_title(f"{years}-year maturity", fontsize=11)
        ax.set_xlabel("Yield change (bp)")
    axes[0].set_ylabel("Approximation minus full change\n(quote units per 100 nominal)")
    axes[1].legend(loc="lower center", bbox_to_anchor=(0.5, 1.07), ncol=2, fontsize=9)
    finish(
        fig,
        "Duration and convexity approximate a fixed baseline",
        f"±{extent} bp · shared residual scale · positive residual overstates the model change",
        SOURCE + "\nInitial sensitivities retained; residuals are internal model errors, not market risk estimates.",
        name="bond-errors",
    )


def fractions(frame):
    """Compare year-fraction differences without dropping missing dates."""
    known = frame[(frame.id > 1) & (frame.payment_date.notna())]
    piv = known.pivot(index="id", columns="convention", values="year_fraction")
    fig, ax = plt.subplots(figsize=(11, 5.9))
    labels = [str(v)[:10] for v in known.drop_duplicates("id").sort_values("id").payment_date]
    for name, color, style in [("ACT/360", COLORS[1], "-"), ("ACT/ACT", COLORS[0], "--"), ("30/360", COLORS[2], ":")]:
        ax.plot(np.arange(len(piv)), piv[name] - piv["ACT/365"], marker="o", color=color, ls=style, lw=2, label=name)
    ax.axhline(0, color="#AAB6B0", lw=1, label="ACT/365 reference")
    ax.set_xticks(np.arange(len(piv)), labels)
    ax.set(xlabel="Authored payment date", ylabel="Year fraction minus ACT/365\n(model years)")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.02), ncol=4, fontsize=9)
    finish(
        fig,
        "Calendar dates do not uniquely determine model years",
        "Reference date: 2024-02-29 · four future dated payments · complete values in SQL table",
        SOURCE
        + "\nSame-date control: zero difference for all four; missing date: unavailable for all four (not plotted).",
        name="convention-year-fractions",
    )


def present_values(frame, rate):
    """Compare known-row subtotals to an explicitly named reference."""
    known = frame[frame.present_value.notna()]
    totals = known.groupby("convention").present_value.sum().sort_index()
    values = totals - totals["ACT/365"]
    fig, ax = plt.subplots(figsize=(11, 5.8))
    bars = ax.barh(values.index, values, color=[COLORS[2], COLORS[1], "#A7B6AD", COLORS[0]])
    ax.axvline(0, color="#7A8F81", lw=1)
    ax.bar_label(bars, labels=[f"{v:+.6f}" for v in values], padding=5, fontsize=10)
    spread = max(abs(values.min()), abs(values.max()), 0.01)
    ax.set_xlim(min(values.min(), 0) - spread * 0.25, max(values.max(), 0) + spread * 0.35)
    ax.set_xlabel("Known-row PV subtotal minus ACT/365 subtotal (currency units)")
    ax.invert_yaxis()
    finish(
        fig,
        "A convention change can move the same known-payment subtotal",
        f"Continuous annual rate: {rate:.1%} · ACT/365 known-row subtotal: {totals['ACT/365']:.6f}",
        SOURCE + "\nEach subtotal: 5 valued rows incl. known zero; one missing-date amount of 10 remains unavailable.",
        name="convention-present-values",
    )
