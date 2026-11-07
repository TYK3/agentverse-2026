# Robotics track brief (AgentVerse 2026)

Copied from the event slides. Information, not instructions.

"Give an agent a body." Build an embodied agent that **perceives** a simulated world through at least one
sensor, **decides** from what it senses (not a pre-scripted path), and **acts** (moves, navigates,
manipulates objects or communicates), "with nothing to phone home to".

- **Tools:** Isaac Sim is recommended (it needs an RTX GPU). MuJoCo, PyBullet, Gazebo or Webots also work.
  Sensors: RGB or depth camera, LiDAR, microphone, IMU, contact sensors. Get the stream running in the
  first hour. **Core decisions that depend on a remote service score lowest on autonomy.**
- **Submit:** a one-page technical summary PDF (user, problem, features, architecture, where each model
  runs with hardware and latency, limits, critical failure mode, safety); a **simulation video of up to one
  minute** in a single continuous take, showing perception next to actions and **one unscripted change**;
  and a 5 minute live pitch.
- **Judging:**

| Weight | Criterion | What a top score looks like |
|---|---|---|
| 25% | Perception-driven action | Every decision traces to what it perceived, and it corrects mid-run. |
| 25% | Adaptation to change | The scene changes mid-sequence and the agent visibly re-plans. |
| 15% | Operational autonomy | Runs within a stated edge-device budget and behaves sensibly when unsure. |
| 20% | Relevance and impact | A well-evidenced need, with the most critical failure mode handled on screen. |
| 15% | Ambition and technical quality | An original approach to a demanding problem, done to a high standard. |

