#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import time
from datetime import datetime
from pathlib import Path
from typing import List, Tuple


def read_timeline(csv_path: Path) -> Tuple[List[int], List[datetime], List[float]]:
    xs_case: List[int] = []
    xs_time: List[datetime] = []
    ys: List[float] = []
    if not csv_path.exists():
        return xs_case, xs_time, ys

    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                x_case = int(row.get("case_index", "0") or 0)
                ts = row.get("timestamp", "") or ""
                # timeline_total.csv uses ISO format, e.g. 2026-03-03T04:46:00
                x_time = datetime.fromisoformat(ts)
                y = float(row.get("cumulative_line_percent", "0") or 0.0)
            except Exception:
                continue
            xs_case.append(x_case)
            xs_time.append(x_time)
            ys.append(y)
    return xs_case, xs_time, ys


def main() -> int:
    parser = argparse.ArgumentParser(description="Realtime line chart for rustc coverage timeline CSV")
    parser.add_argument(
        "--csv",
        default="/home/laix/Study/Traitor/trait-fuzzer/utils/coverage/reports_multi/timeline_total.csv",
        help="Path to timeline_total.csv",
    )
    parser.add_argument("--interval", type=float, default=2.0, help="Refresh interval in seconds")
    parser.add_argument(
        "--headless-png",
        default=None,
        help="Headless mode: periodically overwrite this PNG instead of showing a GUI window",
    )
    parser.add_argument(
        "--x-axis",
        choices=["time", "case"],
        default="time",
        help="X-axis type: time or case",
    )
    args = parser.parse_args()

    csv_path = Path(args.csv).resolve()

    try:
        import matplotlib.pyplot as plt
    except Exception as e:
        print(f"[ERR] matplotlib not available: {e}")
        print("[HINT] pip install matplotlib")
        return 2

    interval = max(0.5, float(args.interval))

    if args.headless_png:
        out_png = Path(args.headless_png).resolve()
        out_png.parent.mkdir(parents=True, exist_ok=True)
        print(f"[INFO] headless mode; writing {out_png} every {interval:.1f}s (x-axis={args.x_axis})")
        while True:
            xs_case, xs_time, ys = read_timeline(csv_path)
            fig, ax = plt.subplots(figsize=(10, 5))
            ax.set_title("Rustc Coverage Timeline (Realtime)")
            if args.x_axis == "time":
                ax.set_xlabel("Time")
            else:
                ax.set_xlabel("Case Index")
            ax.set_ylabel("Cumulative Line Coverage (%)")
            ax.grid(True, alpha=0.3)

            if ys:
                xvals = xs_time if args.x_axis == "time" else xs_case
                ax.plot(xvals, ys, marker="o", linewidth=1.8)
                if args.x_axis == "case" and xs_case:
                    ax.set_xlim(min(xs_case), max(xs_case) if max(xs_case) > min(xs_case) else min(xs_case) + 1)
                ymin = min(ys)
                ymax = max(ys)
                pad = max(0.2, (ymax - ymin) * 0.2)
                ax.set_ylim(max(0.0, ymin - pad), min(100.0, ymax + pad))
                ax.text(
                    xvals[-1],
                    ys[-1],
                    f"  latest={ys[-1]:.4f}%",
                    va="center",
                    fontsize=9,
                )
            else:
                ax.text(0.5, 0.5, f"Waiting for data: {csv_path}", ha="center", va="center", transform=ax.transAxes)

            if args.x_axis == "time":
                fig.autofmt_xdate()

            fig.tight_layout()
            fig.savefig(out_png, dpi=120)
            plt.close(fig)
            time.sleep(interval)

    # GUI mode (interactive realtime)
    plt.ion()
    fig, ax = plt.subplots(figsize=(10, 5))
    line, = ax.plot([], [], marker="o", linewidth=1.8)
    ax.set_title("Rustc Coverage Timeline (Realtime)")
    if args.x_axis == "time":
        ax.set_xlabel("Time")
    else:
        ax.set_xlabel("Case Index")
    ax.set_ylabel("Cumulative Line Coverage (%)")
    ax.grid(True, alpha=0.3)

    print(f"[INFO] watching {csv_path} every {interval:.1f}s (x-axis={args.x_axis}, Ctrl+C to stop)")

    try:
        while True:
            xs_case, xs_time, ys = read_timeline(csv_path)
            if ys:
                xvals = xs_time if args.x_axis == "time" else xs_case
                line.set_data(xvals, ys)
                if args.x_axis == "case" and xs_case:
                    ax.set_xlim(min(xs_case), max(xs_case) if max(xs_case) > min(xs_case) else min(xs_case) + 1)
                ymin = min(ys)
                ymax = max(ys)
                pad = max(0.2, (ymax - ymin) * 0.2)
                ax.set_ylim(max(0.0, ymin - pad), min(100.0, ymax + pad))
                if args.x_axis == "time":
                    ax.relim()
                    ax.autoscale_view(scalex=True, scaley=False)
            else:
                line.set_data([], [])
                ax.set_xlim(0, 1)
                ax.set_ylim(0, 1)

            fig.canvas.draw_idle()
            if args.x_axis == "time":
                fig.autofmt_xdate()
            plt.pause(interval)
    except KeyboardInterrupt:
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
