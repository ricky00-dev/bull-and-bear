"""Render an opening-round chart from local snapshot data."""
from base64 import b64encode
from io import BytesIO
from math import nan
from threading import Lock

from .chart_data import chart_averages
from .snapshot import DAILY_CHART_SESSIONS, Snapshot

_RENDER_LOCK = Lock()


def daily_chart_image(snapshot: Snapshot) -> dict | None:
    bars = sorted((b for b in snapshot.series.stock_ohlcv if b.date <= snapshot.as_of),
                  key=lambda b: b.date)[-DAILY_CHART_SESSIONS:]
    if not bars:
        return None

    with _RENDER_LOCK:
        png = _render_png(snapshot, bars)
    return {"type": "image", "source": {
        "type": "base64", "media_type": "image/png", "data": b64encode(png).decode("ascii"),
    }}


def _render_png(snapshot, bars):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    figure = Figure(figsize=(8.4, 5.6), dpi=100, layout="constrained")
    prices, volume = figure.subplots(2, 1, sharex=True, gridspec_kw={"height_ratios": [4, 1]})
    x = range(len(bars))
    colors = ["#b93d3d" if b.close >= b.open else "#2563a6" for b in bars]
    prices.vlines(x, [b.low for b in bars], [b.high for b in bars], colors=colors, linewidth=1)
    prices.bar(x, [abs(b.close - b.open) for b in bars], width=0.58,
               bottom=[min(b.close, b.open) for b in bars], color=colors, zorder=3)
    flat = [(i, b.close) for i, b in enumerate(bars) if b.close == b.open]
    if flat:
        indices, closes = zip(*flat)
        prices.hlines(closes, [i - 0.29 for i in indices], [i + 0.29 for i in indices],
                      colors=[colors[i] for i in indices], linewidth=2, zorder=4)
    palette = ("#a46a08", "#7c3aad", "#087f70", "#454b61")
    missing = []
    for (key, points), color in zip(chart_averages(snapshot).items(), palette, strict=True):
        values = [points.get(b.date) for b in bars]
        label = key.removeprefix("PX.")
        if all(v is None for v in values):
            missing.append(label)
            continue
        prices.plot(x, [v if v is not None else nan for v in values], label=label,
                    color=color, linewidth=1.5, marker=".", markersize=2, zorder=5)
    if prices.lines:
        prices.legend(loc="upper left", ncols=4, frameon=False)
    if missing:
        prices.text(0.99, 0.02, "Unavailable: " + ", ".join(missing),
                    transform=prices.transAxes, ha="right", va="bottom", fontsize=9)

    prices.set_title(f"{snapshot.ticker}  |  {len(bars)} daily candles through {bars[-1].date.isoformat()}", loc="left")
    prices.set_ylabel("Price (KRW)")
    prices.ticklabel_format(style="plain", useOffset=False, axis="y")
    volume.bar(x, [b.volume for b in bars], width=0.58, color=colors)
    volume.set_ylabel("Volume")
    ticks = sorted(set(range(0, len(bars), max(1, len(bars) // 6))) | {len(bars) - 1})
    volume.set_xticks(ticks, [bars[i].date.strftime("%m-%d") for i in ticks])
    for axis in (prices, volume):
        axis.grid(axis="y", alpha=0.2)
        axis.spines[["top", "right"]].set_visible(False)

    png = BytesIO()
    FigureCanvasAgg(figure).print_png(png)
    return png.getvalue()
