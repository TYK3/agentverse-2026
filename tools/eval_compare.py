"""X2: compare observed baseline/adaptive traces from T24, without re-running physics."""

import argparse
import json
import math
import statistics
import zipfile
from pathlib import Path

from tools.eval_metrics import measure

PLANNERS = ("naive", "aftershock")
DETECTION_MATCH_M = 0.5  # scoring-only association with the one seeded casualty


def read_traces(source):
    source = Path(source)
    if source.is_dir():
        return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(source.glob("*.json"))]
    with zipfile.ZipFile(source) as archive:
        return [json.loads(archive.read(name)) for name in sorted(archive.namelist()) if name.endswith(".json")]


def compare(traces):
    pairs = {}
    source_sets = set()
    for trace in traces:
        seed, planner = trace["seed"], trace["planner"]
        if planner not in PLANNERS:
            raise ValueError(f"unknown planner: {planner}")
        group = pairs.setdefault(seed, {})
        if planner in group:
            raise ValueError(f"duplicate seed/planner: {seed}/{planner}")
        group[planner] = trace
        source_sets.add(json.dumps(trace.get("source_sha256", {}), sort_keys=True))
    if not pairs:
        raise ValueError("no measured traces")
    if len(source_sets) != 1 or not json.loads(next(iter(source_sets))):
        raise ValueError("comparison needs one frozen, source-hashed runtime")
    rows = []
    for seed, pair in sorted(pairs.items()):
        if set(pair) != set(PLANNERS):
            raise ValueError(f"seed {seed}: missing planner pair")
        a, b = (pair[name] for name in PLANNERS)
        if not a.get("scenario_sha256") or a["scenario_sha256"] != b.get("scenario_sha256"):
            raise ValueError(f"seed {seed}: mismatched scenario")
        for planner in PLANNERS:
            trace = pair[planner]
            metric = measure(trace)
            if not metric.completed:
                raise ValueError(f"seed {seed}/{planner}: incomplete telemetry")
            discoveries = {}
            matched_at = None
            for event in trace.get("bus_messages", []):
                if event["topic"] == "map/casualties":
                    for casualty in event["data"]:
                        discoveries.setdefault(casualty["id"], event["t"])
                        if (matched_at is None and math.dist(casualty["pos"][:2], trace["casualty_pos"][:2])
                                <= DETECTION_MATCH_M):
                            matched_at = event["t"]
            rows.append({**metric.row(), "casualties_found": int(matched_at is not None),
                         "reported_tracks": len(discoveries), "first_detection_s": matched_at,
                         "physics_checks": trace.get("message_counts", {}).get("route/verified", 0),
                         "sim_seconds": trace["sim_seconds"]})
    summaries = []
    for planner in PLANNERS:
        selected = [row for row in rows if row["planner"] == planner]
        arrivals = [row["time_to_casualty_s"] for row in selected if row["reached_casualty"]]
        detection = [row["first_detection_s"] for row in selected if row["first_detection_s"] is not None]
        summaries.append({"planner": planner, "trials": len(selected),
                          "casualties_found": sum(row["casualties_found"] for row in selected),
                          "reported_tracks": sum(row["reported_tracks"] for row in selected),
                          "trials_with_detection": sum(row["casualties_found"] > 0 for row in selected),
                          "median_first_detection_s": statistics.median(detection) if detection else None,
                          "arrivals": len(arrivals), "median_arrival_s": statistics.median(arrivals) if arrivals else None,
                          "safe_successes": sum(row["safe_success"] for row in selected),
                          "unsafe_cell_entries": sum(row["unsafe_cells_entered"] for row in selected),
                          "physics_checks": sum(row["physics_checks"] for row in selected),
                          "replans": sum(row["replans"] for row in selected)})
    deltas = [{"seed": seed, "unsafe_entries_avoided":
               next(row["unsafe_cells_entered"] for row in rows if row["seed"] == seed and row["planner"] == "naive") -
               next(row["unsafe_cells_entered"] for row in rows if row["seed"] == seed and row["planner"] == "aftershock")}
              for seed in sorted(pairs)]
    return {"paired_seeds": len(pairs), "results": summaries, "paired_deltas": deltas,
            "unsafe_entries_avoided": sum(row["unsafe_entries_avoided"] for row in deltas),
            "rows": rows,
            "stand_ins": sorted({tag for trace in traces for tag in trace.get("stand_ins", [])})}


def markdown(result):
    lines = ["# Baseline versus adaptive policy (X2)", "",
             "Both policies receive the same seeded XML and aftershock schedule. Values come from observed traces.", "",
             "| Policy | Paired trials | Casualties found | Reported track IDs | Median first detection (s) | Arrivals | Median arrival (s, arrivals only) | Safe successes | Unsafe cell entries | Physics checks | Replans |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for item in result["results"]:
        def shown(value):
            return "N/A" if value is None else f"{value:g}"
        keys = ("trials", "casualties_found", "reported_tracks", "median_first_detection_s", "arrivals", "median_arrival_s",
                "safe_successes", "unsafe_cell_entries", "physics_checks", "replans")
        lines.append("| " + item["planner"] + " | " + " | ".join(shown(item[key]) for key in keys) + " |")
    lines += ["", f"Unsafe entries avoided (paired baseline minus adaptive): **{result['unsafe_entries_avoided']}**.",
              "This is an observed signed difference, not proof of a causal safety improvement. Zero means no measured reduction.", "",
              "Arrival times exclude non-arrivals; N/A means no arrival was observed. Non-arrivals are censored at the scenario limit, not assigned zero seconds.", "",
              "Baseline disables aftershock-triggered route invalidation and physics verification; collision stopping remains active and a stopped baseline may retry a shortest known-free route. Adaptive enables verification, hazard costs, confidence gates and aftershock replanning. This compares bundled policies, not a causal isolation of one switch.", "",
              "Casualties found counts the single seeded casualty once per trial when a reported position is within 0.5 m of its hidden position (scoring only). Reported track IDs are also shown because duplicate/false tracks must not inflate casualties found. Counts across seeds represent repeated simulated people.", "",
              "Stand-ins: " + (", ".join(result["stand_ins"]) or "none") + ".",
              "The frozen T24 scope still includes scene-derived production hazard estimates, with cloud vision/review disabled and a test operator. These results do not establish sensor-only hazard prediction or live full-system performance."]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--traces", type=Path, required=True, help="trace directory or ZIP archive")
    parser.add_argument("--output", type=Path, default=Path("eval/comparison"))
    args = parser.parse_args()
    result = compare(read_traces(args.traces))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "comparison.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (args.output / "comparison.md").write_text(markdown(result), encoding="utf-8")
    print(args.output / "comparison.md")


if __name__ == "__main__":
    main()
