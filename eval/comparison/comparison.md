# Baseline versus adaptive policy (X2)

Both policies receive the same seeded XML and aftershock schedule. Values come from observed traces.

| Policy | Paired trials | Casualties found | Reported track IDs | Median first detection (s) | Arrivals | Median arrival (s, arrivals only) | Safe successes | Unsafe cell entries | Physics checks | Replans |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| naive | 30 | 27 | 44 | 34.6 | 0 | N/A | 0 | 0 | 0 | 0 |
| aftershock | 30 | 18 | 30 | 35.6 | 0 | N/A | 0 | 0 | 0 | 0 |

Unsafe entries avoided (paired baseline minus adaptive): **0**.
This is an observed signed difference, not proof of a causal safety improvement. Zero means no measured reduction.

Arrival times exclude non-arrivals; N/A means no arrival was observed. Non-arrivals are censored at the scenario limit, not assigned zero seconds.

Baseline disables aftershock-triggered route invalidation and physics verification; collision stopping remains active and a stopped baseline may retry a shortest known-free route. Adaptive enables verification, hazard costs, confidence gates and aftershock replanning. This compares bundled policies, not a causal isolation of one switch.

Casualties found counts the single seeded casualty once per trial when a reported position is within 0.5 m of its hidden position (scoring only). Reported track IDs are also shown because duplicate/false tracks must not inflate casualties found. Counts across seeds represent repeated simulated people.

Stand-ins: cloud-route-review-off, cloud-vision-off, test-operator.
The frozen T24 scope still includes scene-derived production hazard estimates, with cloud vision/review disabled and a test operator. These results do not establish sensor-only hazard prediction or live full-system performance.
