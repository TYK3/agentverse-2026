You are given photos of a tabletop model of a collapsed building. Output ONLY a MuJoCo MJCF file. Use the same conventions as sim/scenes/backup.xml (paste it): metres, z up, a mocap body named ground, every wall or rubble block a separate body named b<number>, a body casualty_c1, cameras scout_cam and overview. Keep every block's size and mass plausible for a 1:20 model scaled to a 6 m by 6 m room.

Reference sim/scenes/backup.xml conventions:
- XML root: <mujoco model="aftershock_photo_scene">
- Option: <option timestep="0.002" gravity="0 0 -9.81" noslip_iterations="3"/>
- Ground: <body name="ground" mocap="true" pos="0 0 0"><geom name="floor" type="box" size="3 3 0.05" pos="0 0 -0.05" rgba="0.5 0.5 0.5 1"/></body>
- Bodies: Freejoint bodies named b1, b2, ... with geom named b1_wall, b2_rubble, etc.
- Casualty marker: <body name="casualty_c1" pos="2.0 1.0 0.12" euler="0 90 0"><geom name="c1_g" type="capsule" size="0.12 0.3" contype="0" conaffinity="0" rgba="1 0.3 0.3 1"/></body>
- Cameras:
  <camera name="scout_cam" pos="-0.7 -1.4 0.2" euler="90 0 0"/>
  <camera name="overview" pos="0.5 -4 3.5" xyaxes="1 0 0 0 0.6 0.8"/>
  <camera name="side_view" pos="4 0 3" xyaxes="0 1 0 -0.6 0 0.8"/>
