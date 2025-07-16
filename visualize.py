import sys
import csv
import datetime as dt
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib as mpl
from i18n import t
import argparse


def parse_args() -> tuple[str, int, list[tuple[dt.datetime, str]]]:
    """Return (folder_name, user_id, landmarks) parsed from CLI arguments.

    Landmarks are supplied with ``-m/--mark`` in the form
    ``YYYY-MM-DD HH:MM[:SS][+TZ]|Label`` and can be repeated.
    """

    parser = argparse.ArgumentParser(
        description=t("Visualize Telegram Story views with optional landmarks.")
    )
    parser.add_argument("folder", help=t("Results sub-folder name"))
    parser.add_argument("user_id", type=int, help=t("Target user id"))
    parser.add_argument(
        "-m",
        "--mark",
        metavar="DATETIME|LABEL",
        action="append",
        help=t(
            "Landmark in the form '2024-07-16 12:00|Something happened' — can be repeated"
        ),
    )

    args = parser.parse_args()

    landmarks: list[tuple[dt.datetime, str]] = []
    if args.mark:
        for spec in args.mark:
            try:
                date_str, label = spec.split("|", 1)
            except ValueError:
                raise SystemExit(
                    t(
                        "Invalid landmark '{spec}'. Expected '<datetime>|<label>'.",
                        spec=spec,
                    )
                )
            try:
                when = dt.datetime.fromisoformat(date_str.strip())
                # If datetime is offset-naive, assume UTC for consistency with dataset timestamps
                if when.tzinfo is None:
                    when = when.replace(tzinfo=dt.timezone.utc)
            except ValueError as exc:
                raise SystemExit(
                    t("Invalid datetime '{dt}' in landmark.", dt=date_str.strip())
                ) from exc
            landmarks.append((when, label.strip()))

    return args.folder, args.user_id, landmarks


def read_story_csv(csv_path: Path) -> list[tuple[int, str, str, dt.datetime]]:
    """Read the CSV produced by main.py and return list of tuples.

    Each tuple is (user_id, full_name, username, date).
    """
    rows: list[tuple[int, str, str, dt.datetime]] = []
    with csv_path.open(newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            try:
                user_id = int(row["user_id"])
                full_name = row["full_name"]
                username = row["username"]
                # Parse ISO timestamp that looks like "2024-07-16 10:07:48+00:00"
                date = dt.datetime.fromisoformat(row["date"])
                rows.append((user_id, full_name, username, date))
            except (KeyError, ValueError):
                # Skip malformed rows
                continue
    return rows


def build_dataset(results_dir: Path, target_user_id: int):
    """Build plot data for *target_user_id* based on all viewer data.

    Steps:
    1. Load each story CSV → dict{user_id: view_datetime}
    2. Collect Δt between consecutive story views for *all* users → percentile    thresholds (20 %, 80 %).
    3. For the chosen user, assign y-value:
       • 0   = not viewed
       • 0.5 = swiped past   (Δt ≤ p20)
       • 0.75 = partially watched (p20 < Δt < p80)
       • 1   = watched fully (Δt ≥ p80 or no next-story view)
    4. Return x-labels, y-values, latencies (publish→view seconds), full-name, username.
    """

    def numeric_key(path: Path):
        try:
            return int(path.stem)
        except ValueError:
            return path.stem

    csv_files = sorted(results_dir.glob("*.csv"), key=numeric_key)
    if not csv_files:
        raise SystemExit(t("No CSV files found in {dir}", dir=results_dir))

    # Per-story mapping of user → view_time
    story_views: list[dict[int, dt.datetime]] = []
    creation_times: list[dt.datetime] = []

    for csv_path in csv_files:
        rows = read_story_csv(csv_path)
        user_to_time: dict[int, dt.datetime] = {}
        for uid, _fn, _un, view_dt in rows:
            user_to_time[uid] = view_dt
        if not user_to_time:
            # Skip empty CSV (should not happen)
            story_views.append({})
            creation_times.append(dt.datetime.min.replace(tzinfo=dt.timezone.utc))
            continue

        # Earliest view approximates creation time
        creation_times.append(min(user_to_time.values()))
        story_views.append(user_to_time)

    # ---- Compute Δt distribution across all users ----
    gap_seconds: list[int] = []
    for idx in range(len(story_views) - 1):
        cur_story = story_views[idx]
        nxt_story = story_views[idx + 1]
        # Iterate users who viewed both stories
        for uid, cur_time in cur_story.items():
            nxt_time = nxt_story.get(uid)
            if nxt_time is None:
                continue
            diff = int((nxt_time - cur_time).total_seconds())
            if diff > 0:
                gap_seconds.append(diff)

    # Determine percentile thresholds (integer seconds)
    if gap_seconds:
        gap_seconds.sort()
        n = len(gap_seconds)
        p20_idx = (n * 20) // 100
        p80_idx = (n * 80) // 100
        threshold_skip = gap_seconds[p20_idx]
        threshold_full = gap_seconds[p80_idx]
    else:
        # Fallback defaults if no gaps available
        threshold_skip = 30
        threshold_full = 60

    # ---- Build data for target user ----
    y_values: list[float] = []
    latencies: list[int | None] = []
    user_full_name = ""
    user_username = ""

    # Pre-collect all target user's view times per story
    user_views: list[dt.datetime | None] = []
    for sv in story_views:
        dt_time = sv.get(target_user_id)
        user_views.append(dt_time)
    # Capture name/username from any CSV row (optional)
    if CSV_ROW := next((row for sv in story_views for uid, row in []), None):
        pass  # placeholder – kept for clarity but unused

    # Determine latencies and y values
    for idx, (creation, view_time) in enumerate(zip(creation_times, user_views)):
        # x label date string
        # Compute latency
        if view_time is None:
            latencies.append(None)
            y_values.append(0)
            continue

        lat_sec = int((view_time - creation).total_seconds())
        latencies.append(lat_sec)

        # Next view gap
        gap = None
        if idx + 1 < len(user_views):
            next_view = user_views[idx + 1]
            if next_view is not None:
                gap = int((next_view - view_time).total_seconds())

        # Classify engagement
        if gap is None:
            y_val = 1  # assume watched when no next view
        elif gap <= threshold_skip:
            y_val = 0.5  # swiped past
        elif gap >= threshold_full:
            y_val = 1  # watched fully
        else:
            y_val = 0.75  # partial / uncertain

        y_values.append(y_val)

        # Extract name once (need to read from csv)
        if not user_full_name or not user_username:
            # We can attempt to find details from one of the CSVs where the user appeared
            pass  # filled below

    # Retrieve user info (full_name, username) from any CSV line
    if not user_full_name:
        for csv_path in csv_files:
            rows = read_story_csv(csv_path)
            for uid, full_name, uname, _dt_ in rows:
                if uid == target_user_id:
                    user_full_name = full_name
                    user_username = uname
                    break
            if user_full_name:
                break

    x_labels = [c.strftime("%Y-%m-%d %H:%M") for c in creation_times]

    return x_labels, y_values, latencies, user_full_name, user_username, creation_times


def plot_results(
    x_labels: list[str],
    y_values: list[float],
    latencies: list[int | None],
    creation_times: list[dt.datetime],
    landmarks: list[tuple[dt.datetime, str]],
    output_path: Path,
    user_id: int,
    full_name: str,
    username: str,
):
    """Generate and save the PNG plot using vertical lines and latency-based colors."""
    # Prepare figure
    width = min(25, 2 + len(x_labels) * 0.4)
    fig_height = 10  # taller for readability
    fig, ax = plt.subplots(figsize=(width, fig_height))

    # Determine color mapping based on latency
    valid_latencies = [lat for lat in latencies if lat is not None]
    if valid_latencies:
        min_lat, max_lat = min(valid_latencies), max(valid_latencies)
        lat_range = max_lat - min_lat if max_lat != min_lat else 1
    else:
        min_lat, max_lat, lat_range = 0, 1, 1

    cmap = mpl.colormaps.get_cmap("RdYlGn_r")  # green (fast) to red (slow)

    # Plot vertical lines
    for idx, (y_val, lat) in enumerate(zip(y_values, latencies)):
        if lat is None:
            color = "#cccccc"
        else:
            norm = (lat - min_lat) / lat_range
            color = cmap(norm)

        ax.vlines(idx, 0, y_val, colors=color, linewidth=4)

        # Annotation if viewed
        if lat is not None and y_val > 0:
            if lat < 60:
                annotation = t("view {seconds}s after publ.", seconds=lat)
            elif lat < 3600:
                mins, secs = divmod(lat, 60)
                annotation = t("view {mins}m {secs}s after publ.", mins=mins, secs=secs)
            else:
                hours, rem = divmod(lat, 3600)
                mins = rem // 60
                annotation = t(
                    "view {hours}h {mins}m after publ.", hours=hours, mins=mins
                )
            y_pos = min(y_val + 0.05, 1.15)  # keep label inside axis
            ax.text(
                idx,
                y_pos,
                annotation,
                rotation=30,  # gentler diagonal
                va="bottom",
                ha="left",  # start at the line and extend rightwards
                fontsize=8,
                clip_on=True,
            )

    # ---- Plot landmark markers (thin red lines) ----
    landmark_x_positions = []
    if landmarks:
        for when, label in landmarks:
            # Determine x-coordinate between stories
            if when <= creation_times[0]:
                x_pos: float = -0.5
            elif when >= creation_times[-1]:
                x_pos = len(creation_times) - 0.5
            else:
                x_pos = len(creation_times) - 0.5  # fallback
                for idx, (start, end) in enumerate(
                    zip(creation_times[:-1], creation_times[1:])
                ):
                    if start <= when <= end:
                        if end == start:
                            frac = 0.5
                        else:
                            frac = (when - start).total_seconds() / (
                                end - start
                            ).total_seconds()
                        x_pos = idx + frac
                        break

            landmark_x_positions.append(x_pos)
            ax.axvline(x_pos, ymin=0, ymax=1, color="red", linewidth=1, alpha=0.8)
            ax.text(
                x_pos,
                1.15,
                label,
                rotation=0,
                ha="left",  # align left for consistency with latency annotation
                va="bottom",
                fontsize=8,
                color="red",
                clip_on=True,
            )

    # Set x-axis labels
    ax.set_xticks(range(len(x_labels)))
    ax.set_xticklabels(x_labels, rotation=45, ha="right")

    ax.set_xlabel(t("Telegram Story (creation time)"))

    ax.set_yticks([0, 0.5, 0.75, 1])
    ax.set_yticklabels(
        [
            t("not viewed"),
            t("swiped past"),
            t("partially watched"),
            t("likely watched fully"),
        ]
    )
    ax.set_ylim(-0.1, 1.2)

    # Adjust x-axis limits to include all landmark lines and bars
    min_x = 0
    max_x = len(x_labels) - 1
    if landmark_x_positions:
        min_x = min(min_x, int(min(landmark_x_positions) - 1))
        max_x = max(max_x, int(max(landmark_x_positions) + 1))
    ax.set_xlim(min_x - 0.5, max_x + 0.5)

    # Title
    title_parts = [full_name.strip()]
    if username:
        title_parts.append(f"@{username}")
    title_parts.append(str(user_id))
    ax.set_title(" | ".join(title_parts))

    # Color legend text at bottom
    fig.text(
        0.5,
        0.01,
        t(
            "Color indicates latency between story publication and user's view: green = viewed quickly, yellow = moderate, red = viewed after long delay. Empty = not viewed."
        ),
        ha="center",
        fontsize=8,
    )

    fig.tight_layout(rect=[0, 0.05, 1, 1])
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def main():
    folder_name, user_id, landmarks = parse_args()
    results_dir = Path("results") / folder_name
    if not results_dir.exists():
        raise SystemExit(t("Directory not found: {dir}", dir=results_dir))

    x_labels, y_values, latencies, full_name, username, creation_times = build_dataset(
        results_dir, user_id
    )  # last part of the title and default PNG name

    output_path = results_dir / f"{user_id}.png"
    plot_results(
        x_labels,
        y_values,
        latencies,
        creation_times,
        landmarks,
        output_path,
        user_id,
        full_name,
        username,
    )
    print(t("Saved plot to {path}", path=output_path))


if __name__ == "__main__":
    main()
