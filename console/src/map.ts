import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

export interface GridCell {
  cell: [number, number, number];
  state: 'seen' | 'inferred' | 'unknown';
  occupied: boolean;
  hits?: number;
}

export interface MapCellsPayload {
  t: number;
  res: number;
  cells: GridCell[];
}

export interface HazardRecord {
  cell: [number, number, number];
  status: 'stable' | 'at_risk' | 'collapsed';
  why?: string;
  estimate?: boolean;
}

export interface CasualtyRecord {
  id: string;
  pos: [number, number, number];
  confidence: number;
  clues?: string[];
  vitals?: {
    breathing_rate?: number;
    simulated?: boolean;
  };
}

export interface ScoutSensorsPayload {
  t: number;
  pose: {
    pos: [number, number, number];
    yaw: number;
  };
  lidar?: number[];
}

export interface ResponderActionPayload {
  action: 'move' | 'place_supply' | 'grip' | 'release';
  route?: string;
  item?: 'water' | 'first_aid_kit' | 'radio';
}

export interface RouteProposedPayload {
  id: string;
  robot: string;
  cells: [number, number, number][];
  goal?: string;
  model?: string;
}

const MAX_CELL_CAPACITY = 120000;
const DEFAULT_RES = 0.05;

// Color palette
const COLOR_SEEN_OCCUPIED = new THREE.Color(0x8a9ba8); // Solid grey
const COLOR_HAZARD_AT_RISK = new THREE.Color(0xf59e0b); // Amber
const COLOR_HAZARD_COLLAPSED = new THREE.Color(0xef4444); // Red
const COLOR_HAZARD_STABLE = new THREE.Color(0x8a9ba8); // Stable = regular grey

export class MapViewer {
  public scene: THREE.Scene;
  public camera: THREE.PerspectiveCamera;
  public renderer: THREE.WebGLRenderer;
  public controls: OrbitControls;

  // Instanced meshes for grid cells
  private seenMesh!: THREE.InstancedMesh;
  private inferredMesh!: THREE.InstancedMesh;
  private unknownMesh!: THREE.InstancedMesh;
  private dummy = new THREE.Object3D();

  // Data stores
  private currentCells: GridCell[] = [];
  private cellResolution = DEFAULT_RES;
  private hazardsMap = new Map<string, HazardRecord>();
  private casualtiesMap = new Map<string, CasualtyRecord>();
  private routesMap = new Map<string, RouteProposedPayload>();

  // Object groups
  private casualtyGroup = new THREE.Group();
  private scoutGroup = new THREE.Group();
  private responderGroup = new THREE.Group();
  private routesGroup = new THREE.Group();

  // Batching & state
  private cellsDirty = false;
  private hazardsDirty = false;
  private animationFrameId: number | null = null;

  // FPS and Benchmark tracking
  private lastFpsUpdate = performance.now();
  private framesSinceLastUpdate = 0;
  private currentFps = 60;
  private fpsDisplayElement: HTMLElement | null = null;
  private cellCountElement: HTMLElement | null = null;

  constructor(private canvas: HTMLCanvasElement) {
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0e1726);

    // Camera setup - Z is UP in MuJoCo / robotics coordinates
    this.camera = new THREE.PerspectiveCamera(50, 1, 0.05, 100);
    this.camera.up.set(0, 0, 1);
    this.camera.position.set(2.8, -3.2, 3.2);
    this.camera.lookAt(0.8, 0.4, 0.1);

    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas,
      antialias: true,
      powerPreference: 'high-performance'
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.target.set(0.8, 0.4, 0.1);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.update();

    this.setupLighting();
    this.setupEnvironment();
    this.setupInstancedMeshes();
    this.setupRobotModels();

    this.scene.add(this.casualtyGroup);
    this.scene.add(this.scoutGroup);
    this.scene.add(this.responderGroup);
    this.scene.add(this.routesGroup);

    this.setupResizeObserver();
    this.startLoop();
  }

  private setupLighting(): void {
    const ambient = new THREE.AmbientLight(0xffffff, 0.85);
    this.scene.add(ambient);

    const dirLight1 = new THREE.DirectionalLight(0xffffff, 1.2);
    dirLight1.position.set(5, 5, 8);
    this.scene.add(dirLight1);

    const dirLight2 = new THREE.DirectionalLight(0x7dd3fc, 0.4);
    dirLight2.position.set(-5, -5, 4);
    this.scene.add(dirLight2);
  }

  private setupEnvironment(): void {
    // Grid in X-Y plane (ground is at Z=0)
    const grid = new THREE.GridHelper(8, 16, 0x38bdf8, 0x1e293b);
    grid.rotation.x = Math.PI / 2;
    this.scene.add(grid);

    // Axes: X=Red, Y=Green, Z=Blue (up)
    const axes = new THREE.AxesHelper(0.8);
    this.scene.add(axes);
  }

  private setupInstancedMeshes(): void {
    // 0.05 m cube geometry
    const boxGeometry = new THREE.BoxGeometry(DEFAULT_RES, DEFAULT_RES, DEFAULT_RES);

    // 1. Seen solid (Lambert/Standard with instance colors)
    const seenMaterial = new THREE.MeshStandardMaterial({
      color: 0xffffff,
      roughness: 0.5,
      metalness: 0.1
    });
    this.seenMesh = new THREE.InstancedMesh(boxGeometry, seenMaterial, MAX_CELL_CAPACITY);
    this.seenMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    this.seenMesh.instanceColor = new THREE.InstancedBufferAttribute(
      new Float32Array(MAX_CELL_CAPACITY * 3),
      3
    );
    this.seenMesh.count = 0;
    this.scene.add(this.seenMesh);

    // 2. Inferred translucent (opacity 0.35)
    const inferredMaterial = new THREE.MeshStandardMaterial({
      color: 0xffffff,
      roughness: 0.5,
      metalness: 0.1,
      transparent: true,
      opacity: 0.35,
      depthWrite: false
    });
    this.inferredMesh = new THREE.InstancedMesh(boxGeometry, inferredMaterial, MAX_CELL_CAPACITY);
    this.inferredMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    this.inferredMesh.instanceColor = new THREE.InstancedBufferAttribute(
      new Float32Array(MAX_CELL_CAPACITY * 3),
      3
    );
    this.inferredMesh.count = 0;
    this.scene.add(this.inferredMesh);

    // 3. Unknown not drawn (or very faint wireframe)
    const unknownMaterial = new THREE.MeshBasicMaterial({
      color: 0x334155,
      wireframe: true,
      transparent: true,
      opacity: 0.05
    });
    this.unknownMesh = new THREE.InstancedMesh(boxGeometry, unknownMaterial, MAX_CELL_CAPACITY);
    this.unknownMesh.count = 0;
    this.scene.add(this.unknownMesh);
  }

  private setupRobotModels(): void {
    // Scout rover mesh (compact blue rover with LiDAR turret)
    const scoutBodyGeom = new THREE.BoxGeometry(0.22, 0.16, 0.07);
    const scoutBodyMat = new THREE.MeshStandardMaterial({ color: 0x0284c7, roughness: 0.4 });
    const scoutBody = new THREE.Mesh(scoutBodyGeom, scoutBodyMat);
    scoutBody.position.z = 0.04;
    this.scoutGroup.add(scoutBody);

    // Scout wheels (4 black cylinders)
    const wheelGeom = new THREE.CylinderGeometry(0.035, 0.035, 0.025, 16);
    const wheelMat = new THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.8 });
    const wheelPositions = [
      [-0.08, -0.09, 0.035],
      [0.08, -0.09, 0.035],
      [-0.08, 0.09, 0.035],
      [0.08, 0.09, 0.035]
    ];
    for (const [wx, wy, wz] of wheelPositions) {
      const wheel = new THREE.Mesh(wheelGeom, wheelMat);
      wheel.rotation.x = Math.PI / 2;
      wheel.position.set(wx, wy, wz);
      this.scoutGroup.add(wheel);
    }

    // LiDAR cylinder turret on top
    const lidarGeom = new THREE.CylinderGeometry(0.025, 0.025, 0.035, 16);
    const lidarMat = new THREE.MeshStandardMaterial({ color: 0x38bdf8, emissive: 0x0369a1 });
    const lidar = new THREE.Mesh(lidarGeom, lidarMat);
    lidar.rotation.x = Math.PI / 2;
    lidar.position.set(0, 0, 0.09);
    this.scoutGroup.add(lidar);

    // Front heading indicator (pointing +x)
    const headingGeom = new THREE.ConeGeometry(0.025, 0.06, 12);
    const headingMat = new THREE.MeshBasicMaterial({ color: 0x38bdf8 });
    const heading = new THREE.Mesh(headingGeom, headingMat);
    heading.rotation.z = -Math.PI / 2;
    heading.position.set(0.13, 0, 0.04);
    this.scoutGroup.add(heading);

    // Scout label sprite
    const scoutLabel = this.createLabelSprite('Scout Rover (pose)', '#38bdf8');
    scoutLabel.position.set(0, 0, 0.22);
    this.scoutGroup.add(scoutLabel);

    // Default scout initial position
    this.scoutGroup.position.set(0.1, 0.1, 0.0);

    // Responder robot mesh (larger tracked rover in hazard amber/gold)
    const respBodyGeom = new THREE.BoxGeometry(0.32, 0.24, 0.1);
    const respBodyMat = new THREE.MeshStandardMaterial({ color: 0xd97706, roughness: 0.5 });
    const respBody = new THREE.Mesh(respBodyGeom, respBodyMat);
    respBody.position.z = 0.06;
    this.responderGroup.add(respBody);

    // Tracks / treads on sides
    const treadGeom = new THREE.BoxGeometry(0.34, 0.04, 0.07);
    const treadMat = new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.9 });
    const leftTread = new THREE.Mesh(treadGeom, treadMat);
    leftTread.position.set(0, 0.13, 0.045);
    const rightTread = new THREE.Mesh(treadGeom, treadMat);
    rightTread.position.set(0, -0.13, 0.045);
    this.responderGroup.add(leftTread, rightTread);

    // Responder cargo / arm box on top
    const cargoGeom = new THREE.BoxGeometry(0.14, 0.14, 0.06);
    const cargoMat = new THREE.MeshStandardMaterial({ color: 0x10b981, roughness: 0.4 });
    const cargo = new THREE.Mesh(cargoGeom, cargoMat);
    cargo.position.set(-0.04, 0, 0.14);
    this.responderGroup.add(cargo);

    // Responder label sprite
    const respLabel = this.createLabelSprite('Responder (action)', '#fbbf24');
    respLabel.position.set(0, 0, 0.28);
    this.responderGroup.add(respLabel);

    // Default responder initial position
    this.responderGroup.position.set(-0.6, -0.8, 0.0);
  }

  private createLabelSprite(text: string, colorHex: string, subtext?: string): THREE.Sprite {
    const canvas = document.createElement('canvas');
    canvas.width = 384;
    canvas.height = 128;
    const ctx = canvas.getContext('2d')!;

    // Rounded rectangle background
    ctx.fillStyle = 'rgba(15, 23, 42, 0.88)';
    ctx.beginPath();
    ctx.roundRect(8, 8, 368, 112, 16);
    ctx.fill();

    // Border
    ctx.strokeStyle = colorHex;
    ctx.lineWidth = 4;
    ctx.stroke();

    // Main text
    ctx.fillStyle = colorHex;
    ctx.font = 'bold 30px Inter, system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(text, 192, subtext ? 52 : 72);

    // Optional subtext (e.g. simulated vitals)
    if (subtext) {
      ctx.fillStyle = '#e2e8f0';
      ctx.font = '22px Inter, system-ui, sans-serif';
      ctx.fillText(subtext, 192, 92);
    }

    const texture = new THREE.CanvasTexture(canvas);
    texture.minFilter = THREE.LinearFilter;
    const material = new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false });
    const sprite = new THREE.Sprite(material);
    sprite.scale.set(0.7, 0.23, 1);
    return sprite;
  }

  private setupResizeObserver(): void {
    const resize = (): void => {
      const width = this.canvas.clientWidth || 1;
      const height = this.canvas.clientHeight || 1;
      this.renderer.setSize(width, height, false);
      this.camera.aspect = width / height;
      this.camera.updateProjectionMatrix();
    };
    new ResizeObserver(resize).observe(this.canvas);
    resize();
  }

  private startLoop(): void {
    const animate = (time: number): void => {
      // 1. Batch updates once per animation frame
      if (this.cellsDirty || this.hazardsDirty) {
        this.applyBatchMeshUpdates();
        this.cellsDirty = false;
        this.hazardsDirty = false;
      }

      // 2. Update camera controls
      this.controls.update();

      // 3. Render scene
      this.renderer.render(this.scene, this.camera);

      // 4. Update FPS counter
      this.framesSinceLastUpdate++;
      if (time - this.lastFpsUpdate >= 500) {
        this.currentFps = Math.round((this.framesSinceLastUpdate * 1000) / (time - this.lastFpsUpdate));
        this.lastFpsUpdate = time;
        this.framesSinceLastUpdate = 0;
        if (this.fpsDisplayElement) {
          this.fpsDisplayElement.textContent = `${this.currentFps} FPS`;
          if (this.currentFps >= 30) {
            this.fpsDisplayElement.className = 'fps-badge fps-good';
          } else {
            this.fpsDisplayElement.className = 'fps-badge fps-low';
          }
        }
      }

      this.animationFrameId = requestAnimationFrame(animate);
    };

    this.animationFrameId = requestAnimationFrame(animate);
  }

  public setHudElements(fpsEl: HTMLElement | null, cellCountEl: HTMLElement | null): void {
    this.fpsDisplayElement = fpsEl;
    this.cellCountElement = cellCountEl;
  }

  /**
   * Batch updates for the InstancedMeshes. Called strictly once per animation frame.
   */
  private applyBatchMeshUpdates(): void {
    const res = this.cellResolution;
    let seenCount = 0;
    let inferredCount = 0;
    let unknownCount = 0;

    const seenColorAttr = this.seenMesh.instanceColor!;
    const inferredColorAttr = this.inferredMesh.instanceColor!;

    for (const c of this.currentCells) {
      // Rule: Occupied cells grey, free cells hidden
      if (!c.occupied) continue;

      const [i, j, k] = c.cell;
      const x = (i + 0.5) * res;
      const y = (j + 0.5) * res;
      const z = (k + 0.5) * res;

      this.dummy.position.set(x, y, z);
      this.dummy.scale.set(1, 1, 1);
      this.dummy.updateMatrix();

      // Lookup hazard tint for this cell
      const cellKey = `${i},${j},${k}`;
      const hazard = this.hazardsMap.get(cellKey);
      let tintColor = COLOR_SEEN_OCCUPIED;

      if (hazard) {
        if (hazard.status === 'at_risk') {
          tintColor = COLOR_HAZARD_AT_RISK; // Amber
        } else if (hazard.status === 'collapsed') {
          tintColor = COLOR_HAZARD_COLLAPSED; // Red
        } else if (hazard.status === 'stable') {
          tintColor = COLOR_HAZARD_STABLE;
        }
      }

      if (c.state === 'seen') {
        if (seenCount < MAX_CELL_CAPACITY) {
          this.seenMesh.setMatrixAt(seenCount, this.dummy.matrix);
          seenColorAttr.setXYZ(seenCount, tintColor.r, tintColor.g, tintColor.b);
          seenCount++;
        }
      } else if (c.state === 'inferred') {
        // Inferred translucent (opacity 0.35)
        if (inferredCount < MAX_CELL_CAPACITY) {
          this.inferredMesh.setMatrixAt(inferredCount, this.dummy.matrix);
          inferredColorAttr.setXYZ(inferredCount, tintColor.r, tintColor.g, tintColor.b);
          inferredCount++;
        }
      } else if (c.state === 'unknown') {
        // Unknown: very faint wireframe or hidden
        if (unknownCount < MAX_CELL_CAPACITY) {
          this.unknownMesh.setMatrixAt(unknownCount, this.dummy.matrix);
          unknownCount++;
        }
      }
    }

    this.seenMesh.count = seenCount;
    this.seenMesh.instanceMatrix.needsUpdate = true;
    seenColorAttr.needsUpdate = true;

    this.inferredMesh.count = inferredCount;
    this.inferredMesh.instanceMatrix.needsUpdate = true;
    inferredColorAttr.needsUpdate = true;

    this.unknownMesh.count = unknownCount;
    this.unknownMesh.instanceMatrix.needsUpdate = true;

    const totalOccupied = seenCount + inferredCount;
    if (this.cellCountElement) {
      this.cellCountElement.textContent = `${totalOccupied.toLocaleString()} occupied cells`;
    }
  }

  // --- External Event Handlers ---

  public updateCells(payload: MapCellsPayload): void {
    if (!payload || !Array.isArray(payload.cells)) return;
    this.cellResolution = payload.res || DEFAULT_RES;
    this.currentCells = payload.cells;
    this.cellsDirty = true;
  }

  public updateHazards(hazards: HazardRecord[]): void {
    if (!Array.isArray(hazards)) return;
    for (const h of hazards) {
      if (!Array.isArray(h.cell) || h.cell.length < 3) continue;
      const key = `${h.cell[0]},${h.cell[1]},${h.cell[2]}`;
      this.hazardsMap.set(key, h);
    }
    this.hazardsDirty = true;
  }

  public updateCasualties(casualties: CasualtyRecord[]): void {
    if (!Array.isArray(casualties)) return;

    // Clear existing casualty meshes
    while (this.casualtyGroup.children.length > 0) {
      const obj = this.casualtyGroup.children[0];
      this.casualtyGroup.remove(obj);
    }
    this.casualtiesMap.clear();

    const sphereGeom = new THREE.SphereGeometry(0.12, 24, 24);
    const sphereMat = new THREE.MeshStandardMaterial({
      color: 0xec4899,
      emissive: 0x831843,
      emissiveIntensity: 0.6,
      roughness: 0.3
    });

    for (const cas of casualties) {
      if (!cas || !Array.isArray(cas.pos)) continue;
      this.casualtiesMap.set(cas.id, cas);
      const [x, y, z] = cas.pos;

      // Casualty sphere marker
      const sphere = new THREE.Mesh(sphereGeom, sphereMat);
      sphere.position.set(x, y, z + 0.12);
      this.casualtyGroup.add(sphere);

      // Pulse beacon ring around casualty
      const ringGeom = new THREE.RingGeometry(0.15, 0.22, 32);
      const ringMat = new THREE.MeshBasicMaterial({
        color: 0xf472b6,
        side: THREE.DoubleSide,
        transparent: true,
        opacity: 0.7
      });
      const ring = new THREE.Mesh(ringGeom, ringMat);
      ring.position.set(x, y, z + 0.02);
      this.casualtyGroup.add(ring);

      // Label: c1 (0.82, estimate); vitals text with (simulated)
      const confText = typeof cas.confidence === 'number' ? cas.confidence.toFixed(2) : '0.80';
      const title = `${cas.id} (${confText}, estimate)`;
      const vitalsText = cas.vitals?.breathing_rate
        ? `Breathing: ${cas.vitals.breathing_rate} bpm (simulated)`
        : 'Vitals: 14 bpm (simulated)';

      const labelSprite = this.createLabelSprite(title, '#f472b6', vitalsText);
      labelSprite.position.set(x, y, z + 0.42);
      this.casualtyGroup.add(labelSprite);
    }
  }

  public updateScoutPose(payload: ScoutSensorsPayload): void {
    if (!payload?.pose?.pos) return;
    const [x, y, z] = payload.pose.pos;
    this.scoutGroup.position.set(x, y, z);
    if (typeof payload.pose.yaw === 'number') {
      this.scoutGroup.rotation.z = payload.pose.yaw;
    }
  }

  public updateResponderAction(payload: ResponderActionPayload): void {
    if (!payload) return;
    // If action refers to a route, move responder to destination or along route
    if (payload.route && this.routesMap.has(payload.route)) {
      const route = this.routesMap.get(payload.route)!;
      if (route.cells && route.cells.length > 0) {
        const lastCell = route.cells[route.cells.length - 1];
        const res = this.cellResolution;
        this.responderGroup.position.set((lastCell[0] + 0.5) * res, (lastCell[1] + 0.5) * res, 0);
      }
    }
  }

  public updateRouteProposed(route: RouteProposedPayload): void {
    if (!route?.cells) return;
    this.routesMap.set(route.id, route);

    // Draw route line in routesGroup
    const points: THREE.Vector3[] = [];
    const res = this.cellResolution;
    for (const [ci, cj, ck] of route.cells) {
      points.push(new THREE.Vector3((ci + 0.5) * res, (cj + 0.5) * res, (ck + 0.5) * res + 0.03));
    }

    const lineGeom = new THREE.BufferGeometry().setFromPoints(points);
    const lineMat = new THREE.LineBasicMaterial({ color: 0x10b981, linewidth: 3 });
    const line = new THREE.Line(lineGeom, lineMat);
    this.routesGroup.clear();
    this.routesGroup.add(line);
  }

  /**
   * Populates the map with the standard AFTERSHOCK collapsed building backup scene
   * (walls b1-b9, doorway, leaning slab b10 at risk, rubble b11-b15).
   * Ensures ?fake=1 immediately displays a coloured map with casualty and hazards.
   */
  public loadBackupSceneDemo(): void {
    const res = DEFAULT_RES;
    const cells: GridCell[] = [];

    // Helper to generate a solid wall block of cells
    const addBox = (minX: number, maxX: number, minY: number, maxY: number, minZ: number, maxZ: number, state: 'seen' | 'inferred' = 'seen') => {
      const i0 = Math.round(minX / res);
      const i1 = Math.round(maxX / res);
      const j0 = Math.round(minY / res);
      const j1 = Math.round(maxY / res);
      const k0 = Math.round(minZ / res);
      const k1 = Math.round(maxZ / res);

      for (let i = i0; i <= i1; i++) {
        for (let j = j0; j <= j1; j++) {
          for (let k = k0; k <= k1; k++) {
            cells.push({
              cell: [i, j, k],
              state,
              occupied: true
            });
          }
        }
      }
    };

    // Perimeter walls (b1 north, b2 west, b3/b4 south breach, b5 north)
    addBox(-1.5, 2.5, 1.45, 1.55, 0, 0.4); // North wall b1/b5
    addBox(-1.55, -1.45, -1.0, 1.5, 0, 0.4); // West wall b2
    addBox(-1.45, -1.0, -1.05, -0.95, 0, 0.4); // South wall west of breach b3
    addBox(-0.4, 2.45, -1.05, -0.95, 0, 0.4); // South wall east of breach b4 (breach is -1.0 to -0.4)
    addBox(2.45, 2.55, -1.0, 1.5, 0, 0.4); // East wall

    // Interior dividing wall 1 (between room 1 and 2, door y: 0.0 to 0.5)
    addBox(-0.05, 0.05, -0.95, 0.0, 0, 0.4); // b6 wall south of doorway
    addBox(-0.05, 0.05, 0.5, 1.45, 0, 0.4); // b7 wall north of doorway

    // Interior dividing wall 2 (between room 2 and 3, gap y: 0.3 to 0.9)
    addBox(1.2, 1.3, -0.95, 0.3, 0, 0.4); // b8 wall
    addBox(1.2, 1.3, 0.9, 1.45, 0, 0.4); // b9 wall

    // Rubble & leaning slab b10 (at risk) in room 2 (x: 0.8 to 1.2, y: -0.6 to -0.4)
    addBox(0.8, 1.15, -0.6, -0.4, 0, 0.25, 'seen'); // b10 slab (at risk)

    // Rubble in breach room 1 (b12, b13)
    addBox(-0.8, -0.6, -0.7, -0.5, 0, 0.15, 'seen');

    // Rubble in doorway room 2/3 (b11)
    addBox(1.15, 1.35, 0.4, 0.55, 0, 0.1, 'inferred');

    // Fallen section in room 3 (b14)
    addBox(1.6, 2.2, -0.5, -0.3, 0, 0.08, 'inferred');

    this.updateCells({ t: 0, res, cells });

    // Mark hazards
    const hazards: HazardRecord[] = [];
    const b10_i0 = Math.round(0.8 / res);
    const b10_i1 = Math.round(1.15 / res);
    const b10_j0 = Math.round(-0.6 / res);
    const b10_j1 = Math.round(-0.4 / res);
    for (let i = b10_i0; i <= b10_i1; i++) {
      for (let j = b10_j0; j <= b10_j1; j++) {
        hazards.push({
          cell: [i, j, 0],
          status: 'at_risk',
          why: 'unsupported leaning slab b10',
          estimate: true
        });
        hazards.push({
          cell: [i, j, 1],
          status: 'at_risk',
          why: 'unsupported leaning slab b10',
          estimate: true
        });
      }
    }

    // Add a collapsed rubble hazard in breach
    hazards.push({
      cell: [Math.round(-0.7 / res), Math.round(-0.6 / res), 0],
      status: 'collapsed',
      why: 'breach collapse pile b12',
      estimate: true
    });

    this.updateHazards(hazards);

    // Add casualty c1 in room 3
    this.updateCasualties([
      {
        id: 'c1',
        pos: [1.95, 0.98, 0.0],
        confidence: 0.82,
        clues: ['thermal', 'sound'],
        vitals: { breathing_rate: 14, simulated: true }
      }
    ]);

    // Position scout at south breach entry
    this.updateScoutPose({
      t: 0,
      pose: { pos: [-0.65, -0.85, 0.0], yaw: Math.PI / 4 }
    });

    // Position responder outside
    this.responderGroup.position.set(-0.8, -1.2, 0);

    // Initial proposed route from scout to room 2
    this.updateRouteProposed({
      id: 'r1',
      robot: 'responder',
      cells: [
        [Math.round(-0.8 / res), Math.round(-1.2 / res), 0],
        [Math.round(-0.65 / res), Math.round(-0.85 / res), 0],
        [Math.round(-0.3 / res), Math.round(-0.4 / res), 0],
        [Math.round(0.4 / res), Math.round(0.2 / res), 0]
      ],
      goal: 'explore room 2'
    });
  }

  /**
   * Benchmark mode: Generates 100,000 cells to verify 30+ FPS rendering performance.
   */
  public generate100kBenchmark(): void {
    const res = DEFAULT_RES;
    const cells: GridCell[] = [];
    const hazards: HazardRecord[] = [];

    // 100 x 100 grid with 10 vertical layers or structured clusters
    // 100 * 100 * 10 = 100,000 cells exactly
    const sizeX = 100;
    const sizeY = 100;
    const layers = 10;

    for (let k = 0; k < layers; k++) {
      for (let j = 0; j < sizeY; j++) {
        for (let i = 0; i < sizeX; i++) {
          const state: 'seen' | 'inferred' = (i + j + k) % 7 === 0 ? 'inferred' : 'seen';
          cells.push({
            cell: [i - 50, j - 50, k],
            state,
            occupied: true
          });
        }
      }
    }

    // Add hazard tags to some cells
    for (let i = -10; i < 10; i++) {
      for (let j = -10; j < 10; j++) {
        hazards.push({
          cell: [i, j, 0],
          status: (i + j) % 2 === 0 ? 'at_risk' : 'collapsed',
          why: '100k stress test cluster',
          estimate: true
        });
      }
    }

    this.updateHazards(hazards);
    this.updateCells({ t: performance.now(), res, cells });

    // Focus camera out to frame 100k cells
    this.camera.position.set(6, -8, 8);
    this.controls.target.set(0, 0, 0.5);
    this.controls.update();
  }

  public destroy(): void {
    if (this.animationFrameId !== null) {
      cancelAnimationFrame(this.animationFrameId);
    }
    this.controls.dispose();
    this.renderer.dispose();
  }
}
