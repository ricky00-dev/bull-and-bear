"""Compact numeric chart data backed by a frozen snapshot."""
import csv
from io import StringIO

from .snapshot import Snapshot, moving_average_value

CHART_MA_WINDOWS = (7, 11, 25, 200)


def chart_averages(snapshot: Snapshot) -> dict:
    bars = sorted((b for b in snapshot.series.stock_ohlcv if b.date <= snapshot.as_of),
                  key=lambda b: b.date)
    closes = [b.close for b in bars]
    averages = {}
    for window in CHART_MA_WINDOWS:
        key = f"PX.MA{window}"
        points = snapshot.series.moving_averages.get(key)
        averages[key] = ({p.date: p.value for p in points} if points is not None else
                         {b.date: moving_average_value(closes[max(0, i - window):i], window)
                          for i, b in enumerate(bars, 1)})
    return averages


def csv_rows(columns, rows, *, line_ending="\n") -> str:
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator=line_ending)
    writer.writerow(columns)
    for row in rows:
        writer.writerow(int(value) if isinstance(value, float) and value.is_integer() else value for value in row)
    return output.getvalue().removesuffix(line_ending)
