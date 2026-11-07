# AFTERSHOCK hardware spec (Y7b)

What the two robots would be built from if they left the simulation. All parts are real products on
sale or documented by their makers, and each figure has a source link. Figures we derived ourselves
(total weight, power, runtime, sensor positions) are marked **estimate** and show the working.
The sim models (Y7a) and the console panel (Y7c) are built from the tables here.

Checked 7 Nov 2026. Where sources disagreed, the table gives the maker's figure and the note says so.

## Summary

| | Scout (per unit) | Responder |
|---|---|---|
| Base | AgileX LIMO Pro | Clearpath Jackal |
| Size (L x W x H) | 322 x 220 x 251 mm | 508 x 430 x 250 mm base; about 700 mm high with the LiDAR mast (estimate) |
| Weight | 4.8 kg base; about 5.2 kg with add-ons (estimate) | 17 kg base; about 26 kg with arm, sensors, compute and supplies (estimate) |
| Compute | NVIDIA Jetson Orin Nano (built in) | NVIDIA Jetson Orin NX 16GB |
| LiDAR | EAI YDLIDAR T-mini Pro, 2D, 360 degrees, 12 m | Livox Mid-360, 3D, 360 x 59 degrees, 40 m at 10% reflectivity |
| Camera | Orbbec DaBai depth camera (built in) | Luxonis OAK-D Lite (RGB + stereo depth) |
| Thermal | Teledyne FLIR Lepton 3.5, 160 x 120 | Teledyne FLIR Lepton 3.5, 160 x 120 |
| Microphones | Seeed ReSpeaker Mic Array v2.0 (4 mics, direction of arrival) | Seeed ReSpeaker Mic Array v2.0 (also the casualty speaker/mic for the guide voice) |
| IMU | CEVA BNO085 (added) | Jackal onboard IMU, plus CEVA BNO085 |
| Arm | none | Kinova Gen3 lite, 6 DoF, 0.5 kg payload, 760 mm reach |
| Battery | 12 V, 10 Ah (120 Wh) | 270 Wh lithium |
| Runtime | 2.5 h working (maker); about 2.3 h with add-ons (estimate) | 2 h heavy use to 8 h basic use (maker); about 2 h on a rescue run (estimate) |
| Units | 2 in a full deployment (the demo simulates 1) | 1 |

## Scout unit

A small, light rover that only looks. The LIMO Pro is a complete ROS platform with its own compute,
2D LiDAR and depth camera, so the Scout adds only the thermal camera, the microphone array, an IMU
and a radio.

| Item | Part | Key figures | Source |
|---|---|---|---|
| Base | AgileX LIMO Pro | 322 x 220 x 251 mm, 4.8 kg, 4 kg payload, 24 mm ground clearance, in-wheel motors | [Weston Robot LIMO Pro guide][limo-pro] |
| Compute | NVIDIA Jetson Orin Nano (in the LIMO Pro) | RAM not listed by AgileX; the Orin Nano module comes as 4 GB or 8 GB. Up to 67 INT8 TOPS and up to 25 W on the 8 GB Super kit | [LIMO Pro guide][limo-pro], [CNX Software on the Orin Nano Super][orin-nano] |
| LiDAR | EAI YDLIDAR T-mini Pro | 2D, 360 degrees, 0.02 to 12 m, 6 to 12 Hz scan, 4000 samples/s, 0.54 degree resolution, 38.6 x 38.6 x 33.4 mm, UART | [T-mini Pro datasheet V0.2.0][tmini], [Elektor listing][tmini-shop] |
| Depth camera | Orbbec DaBai (in the LIMO Pro) | Stereo depth camera; range and FOV not checked | [LIMO Pro guide][limo-pro], [Trossen LIMO specs][limo] |
| Thermal camera | Teledyne FLIR Lepton 3.5 on a PureThermal USB board | 160 x 120 radiometric LWIR, 57 degree HFOV (one table lists 56), scene range to +400 C, about 150 mW | [Lepton 3/3.5 datasheet (Mouser)][lepton] |
| Microphones | Seeed ReSpeaker Mic Array v2.0 (XMOS XVF-3000) | 4 PDM mics, on-chip direction of arrival, beamforming, noise suppression, voices to about 5 m, USB audio, 70 x 70 x 13.3 mm, 70 g | [Seeed wiki][respeaker] |
| IMU | CEVA BNO085 (Adafruit 4754 breakout) | 9-axis with on-chip fusion, rotation vector up to 400 Hz | [Adafruit 4754][bno085], [Luxonis BNO08x notes][bno085-lux] |
| Radio relay (future, as in the spec) | Semtech SX1262 LoRa transceiver | +22 dBm out, -148 dBm sensitivity, 170 dB link budget, 150 to 960 MHz | [Mouser SX1261/2 page][sx1262] |
| Battery | LIMO Pro pack | 12 V, 10 Ah (120 Wh), 2.5 h working, 4 h standby | [LIMO Pro guide][limo-pro] |

**Scout estimates.** Add-ons: Lepton 3.5 and PureThermal board about 0.03 kg, ReSpeaker 0.07 kg, IMU
and LoRa boards under 0.02 kg, plus brackets about 0.25 kg, so about 5.2 kg in all. They draw about
1.5 W (Lepton 0.15 W, ReSpeaker and USB about 1 W, IMU and radio receiving well under 0.5 W) against
roughly 48 W average implied by 120 Wh over 2.5 h, so runtime drops by about 3%, to about 2.3 h.

## Responder

The heavier robot that carries supplies, moves light debris and guides casualties. The Jackal is
small enough for indoor doorways and carries 20 kg (10 kg over rough ground). Clearpath documents and
sells the Kinova Gen3 lite as a manipulator accessory for its robots, and the arm runs straight off the
Jackal's 25.6 V battery rail, so the arm mount (for Y2) needs no extra power supply.

| Item | Part | Key figures | Source |
|---|---|---|---|
| Base | Clearpath Jackal | 508 x 430 x 250 mm, 17 kg, 20 kg payload (10 kg all-terrain), 2.0 m/s, 65 mm ground clearance | [Clearpath Jackal page][jackal], [Jackal user manual][jackal-manual], [UMD lab page][jackal-umd] |
| User power | Jackal fused user power | 16 A at VBAT (25.6 V nominal), 7 A at 12 V, 5 A at 5 V | [Jackal user manual][jackal-manual] |
| Arm | Kinova Gen3 lite | 6 DoF, 5.4 kg, 0.5 kg payload, 760 mm reach, 21 to 30 V DC (24 V nominal), 20 W average | [Clearpath Gen3 lite accessory page][gen3lite], [Clearpath store][gen3lite-store] |
| Compute | NVIDIA Jetson Orin NX 16GB | 16 GB LPDDR5, 1024-core Ampere GPU, 8-core Cortex-A78AE, up to 100 TOPS (sparse) at 10 to 25 W; up to 157 TOPS at 40 W in Super mode | [Connect Tech module page][orin-nx], [Waveshare Orin NX page][orin-nx-ws] |
| 3D LiDAR | Livox Mid-360 | 360 x 59 degrees (-7 to +52), 0.1 m minimum, 40 m at 10% and 70 m at 80% reflectivity, 65 x 65 x 60 mm, 265 g, 6.5 W, 9 to 27 V, IP67 | [Livox Mid-360 specs][mid360] |
| Camera | Luxonis OAK-D Lite | 13 MP IMX214 colour camera (about 68 degree HFOV), OV7251 global-shutter stereo pair, Myriad X on board, 91 x 28 x 17.5 mm, 61 g, 4.5 W max, USB-C | [OAK-D Lite spec sheet][oakd] |
| Thermal camera | Teledyne FLIR Lepton 3.5 | as on the Scout | [Lepton datasheet][lepton] |
| Microphones and speaker | Seeed ReSpeaker Mic Array v2.0 | as on the Scout; it also drives a small speaker for the guide voice (Y5) | [Seeed wiki][respeaker] |
| IMU | Jackal onboard IMU (model not named by Clearpath), plus CEVA BNO085 on the arm base | as on the Scout | [Jackal user manual][jackal-manual], [Adafruit 4754][bno085] |
| Battery | Jackal pack | 270 Wh lithium, 4 h charge, 2 h heavy use to 8 h basic use | [Jackal user manual][jackal-manual] |

**Responder estimates.**
- Weight: Jackal 17 kg + arm 5.4 kg + Mid-360 0.27 kg + Orin NX on a carrier about 0.3 kg + OAK-D
  Lite, Lepton, ReSpeaker and IMU about 0.2 kg + mast and brackets about 1 kg + supply kit about 1.5 kg
  = about 25.7 kg. That is 8.7 kg of payload, inside the 10 kg all-terrain limit.
- Power on a rescue run: drive about 60 W average (an assumption: Clearpath gives no average figure, only
  500 W peak drive power) + arm 20 W + Orin NX 25 W + Mid-360 6.5 W + OAK-D Lite 4.5 W + the rest
  about 2 W = about 118 W, so about 2.3 h on 270 Wh. With a 15% reserve that is about 2 h, which
  matches the maker's heavy-use figure.
- The planner's offline model fits: `gemma4:e2b` measured 4.1 GB resident on our 8 GB laptop
  (`planner/budget.json`), well inside the Orin NX's 16 GB alongside mapping and perception.

## Sensor positions (for the sim models, Y7a)

Robot frame: x forward, y left, z up, origin on the ground under the centre of the base. These
positions are our design (**estimate**), chosen so each sensor sees what the sim already reads.

| Robot | Sensor | Position x, y, z (m) | Facing | Why there |
|---|---|---|---|---|
| Scout | T-mini Pro LiDAR | 0.00, 0.00, 0.26 | spins, 360 degrees | on top, clear of the body |
| Scout | Orbbec DaBai camera | 0.15, 0.00, 0.18 | forward | where the LIMO Pro has it, front face |
| Scout | Lepton 3.5 | 0.15, 0.00, 0.21 | forward | next to the camera so the two images line up |
| Scout | ReSpeaker array | -0.05, 0.00, 0.27 | up | flat on top, so bearing covers all round |
| Scout | BNO085 | 0.00, 0.00, 0.10 | - | inside, near the centre |
| Responder | Mid-360 LiDAR | -0.15, 0.00, 0.70 | up | on a mast above the arm's reach envelope when stowed |
| Responder | OAK-D Lite | 0.24, 0.00, 0.30 | forward, tilted 15 degrees down | front of the top plate, sees the floor ahead and the gripper |
| Responder | Lepton 3.5 | 0.24, 0.05, 0.30 | forward | beside the OAK-D |
| Responder | ReSpeaker + speaker | -0.20, 0.00, 0.27 | up | rear deck, away from the arm |
| Responder | Gen3 lite arm base | 0.10, 0.00, 0.25 | - | front half of the top plate, so it reaches the floor ahead |
| Responder | Supply deck | -0.10, 0.00, 0.26 | - | between the arm and the mast |

## What this means for the simulation

- **Doorways.** The real Jackal is 430 mm wide. The backup scene's 0.5 m doorway leaves 35 mm each
  side, and the planner keeps 0.15 m clearance from walls (`planner/route.py` `CLEARANCE_M`), which
  only fits a robot up to 0.3 m wide. A true-scale Responder needs either about 0.8 m doorways in the
  scene (a normal interior door is 0.76 to 0.9 m) or a clearance that matches its half-width.
  The 220 mm Scout fits as it is.
- **Lifting.** The Gen3 lite lifts 0.5 kg. The sim lets the gripper clear light blocks under 2 kg
  (`sim/scenes/backup.xml`). True to scale, the arm can lift only blocks up to 0.5 kg (a bandage, a
  splint board, a water bottle); heavier light debris is pushed with the base, not lifted.
- **LiDAR range.** The sim's 6 m LiDAR limit (`sim/sensors.py`) is inside both real sensors' ranges, so
  it is a fair, cautious stand-in. The Scout's real LiDAR is 2D like the sim's; the Responder's is 3D.
- **Thermal.** The sim's 16 x 12 thermal grid over 60 x 45 degrees is a downsampled Lepton 3.5
  (160 x 120 over 57 degrees horizontal).

## Not checked

- Exact RAM of the LIMO Pro's Orin Nano, and the Orbbec DaBai's depth range and FOV.
- Prices and stock. Luxonis lists the OAK-D Lite as possibly retired at some retailers; the OAK-D
  family has drop-in successors.
- Drive power on rubble. The 60 W average is an assumption until measured.

[limo-pro]: https://westonrobot.github.io/docs-legacy/_sources/robot_user_guide/agilex/limo_pro.rst.txt
[limo]: https://docs.trossenrobotics.com/agilex_limo_docs/specifications/limo.html
[orin-nano]: https://cnx-software.com/2024/12/18/249-nvidia-jetson-orin-nano-super-developer-kit-targets-generative-ai-applications-at-the-edge/
[tmini]: https://stgaws.robu.in/wp-content/uploads/2022/11/YDLIDAR-T-mini-Pro-Data-Sheet_V0.2.0-220831.pdf
[tmini-shop]: https://www.elektor.com/ydlidar-tmini-pro-360-degree-laser-range-scanner-12-m
[lepton]: https://www.mouser.com/datasheet/2/227/Lepton3_3_5_Data_Sheet-2580086.pdf
[respeaker]: https://wiki.seeedstudio.com/ReSpeaker_Mic_Array_v2.0
[bno085]: https://adafruit.com/product/4754
[bno085-lux]: https://docs.luxonis.com/hardware/platform/sensors/imu/bno08x.md
[sx1262]: https://www.mouser.in/semtech-sx1261-2-lora-transceivers/
[jackal]: https://clearpathrobotics.com/jackal-small-unmanned-ground-vehicle
[jackal-manual]: https://docs.clearpathrobotics.com/docs_robots/outdoor_robots/jackal/user_manual_jackal
[jackal-umd]: https://facilities.robotics.umd.edu/ral/equipment/robotics/clearpath-jackal.html
[gen3lite]: https://docs.clearpathrobotics.com/docs/robots/accessories/manipulators/kinova_gen3_lite
[gen3lite-store]: https://store.clearpathrobotics.com/products/gen3-lite
[orin-nx]: https://connecttech.com/?p=17607
[orin-nx-ws]: https://www.waveshare.com/product/ai/jetson-orin-nx.htm
[mid360]: https://www.livoxtech.com/mid-360/specs
[oakd]: https://cdn.shopify.com/s/files/1/0630/8950/8583/files/OAK-D-Lite_Spec_Sheet.pdf
