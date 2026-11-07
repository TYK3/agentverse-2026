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
  reason?: string;
  model?: string;
}

export interface RouteVerifiedPayload {
  id: string;
  ok: boolean;
  unstable_cells?: [number, number, number][];
  detail?: string;
}

export interface WorldChangePayload {
  kind: 'aftershock' | 'block_added';
  t: number;
  moved_blocks: string[];
}

interface FadingRoute {
  group: THREE.Group;
  materials: THREE.MeshStandardMaterial[];
  startTime: number;
  fadeDuration: number; // 1000 ms (1s)
  totalLifetime: number; // 8000 ms (8s)
  startOpacity: number;
  targetOpacity: number; // 0.2
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
  private activeRouteGroup = new THREE.Group();
  private previousRoutesGroup = new THREE.Group();
  private unstableCellsGroup = new THREE.Group();
  private movedBlocksGroup = new THREE.Group();

  // Route animation and fading
  private fadingRoutes: FadingRoute[] = [];
  private movedBlockMeshes: THREE.Mesh[] = [];

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

  // Banner elements
  private bannerElement: HTMLElement | null = null;
  private bannerTextElement: HTMLElement | null = null;
  private bannerIconElement: HTMLElement | null = null;
  private bannerTimeoutId: number | null = null;

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
    this.scene.add(this.previousRoutesGroup);
    this.scene.add(this.activeRouteGroup);
    this.scene.add(this.unstableCellsGroup);
    this.scene.add(this.movedBlocksGroup);

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

  public createLabelSprite(text: string, colorHex: string, subtext?: string): THREE.Sprite {
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
    ctx.font = 'bold 28px Inter, system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(text, 192, subtext ? 50 : 70);

    // Optional subtext
    if (subtext) {
      ctx.fillStyle = '#e2e8f0';
      ctx.font = '20px Inter, system-ui, sans-serif';
      ctx.fillText(subtext, 192, 88);
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

      // 2. Animate fading routes (fade to 20% opacity over 1s, keep for 8s)
      this.updateFadingRoutes(time);

      // 3. Animate flashing moved blocks
      this.updateMovedBlocksAnimation(time);

      // 4. Update camera controls
      this.controls.update();

      // 5. Render scene
      this.renderer.render(this.scene, this.camera);

      // 6. Update FPS counter
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

  public setBannerElements(banner: HTMLElement | null, text: HTMLElement | null, icon: HTMLElement | null): void {
    this.bannerElement = banner;
    this.bannerTextElement = text;
    this.bannerIconElement = icon;
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
        if (inferredCount < MAX_CELL_CAPACITY) {
          this.inferredMesh.setMatrixAt(inferredCount, this.dummy.matrix);
          inferredColorAttr.setXYZ(inferredCount, tintColor.r, tintColor.g, tintColor.b);
          inferredCount++;
        }
      } else if (c.state === 'unknown') {
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

      const sphere = new THREE.Mesh(sphereGeom, sphereMat);
      sphere.position.set(x, y, z + 0.12);
      this.casualtyGroup.add(sphere);

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
    if (payload.route && this.routesMap.has(payload.route)) {
      const route = this.routesMap.get(payload.route)!;
      if (route.cells && route.cells.length > 0) {
        const lastCell = route.cells[route.cells.length - 1];
        const res = this.cellResolution;
        this.responderGroup.position.set((lastCell[0] + 0.5) * res, (lastCell[1] + 0.5) * res, 0);
      }
    }
  }

  // --- Task T19: Route Drawing, Visible Re-Plan and Fading ---

  /**
   * Draws route/proposed cells as a TubeGeometry in solid blue.
   * When a new route/proposed arrives, fades the old line to 20% opacity over 1s
   * and keeps it for 8s labelled "previous route".
   */
  public updateRouteProposed(route: RouteProposedPayload): void {
    if (!route || !Array.isArray(route.cells) || route.cells.length === 0) return;
    this.routesMap.set(route.id, route);

    const now = performance.now();
    const res = this.cellResolution;

    // 1. If an active route already exists, move it to fadingRoutes
    if (this.activeRouteGroup.children.length > 0) {
      const oldGroup = new THREE.Group();
      while (this.activeRouteGroup.children.length > 0) {
        const child = this.activeRouteGroup.children[0];
        this.activeRouteGroup.remove(child);
        oldGroup.add(child);
      }

      const oldMaterials: THREE.MeshStandardMaterial[] = [];
      let midpoint = new THREE.Vector3(0, 0, 0);
      let pointCount = 0;

      oldGroup.traverse(obj => {
        if (obj instanceof THREE.Mesh && obj.material instanceof THREE.MeshStandardMaterial) {
          obj.material = obj.material.clone();
          obj.material.transparent = true;
          obj.material.opacity = 1.0;
          obj.material.color.setHex(0x60a5fa); // Faded blue tint
          oldMaterials.push(obj.material);
        }
      });

      // Find midpoint of old route for "previous route" label
      const oldRoute = Array.from(this.routesMap.values())[this.routesMap.size - 2];
      if (oldRoute?.cells && oldRoute.cells.length > 0) {
        const midCell = oldRoute.cells[Math.floor(oldRoute.cells.length / 2)];
        midpoint.set((midCell[0] + 0.5) * res, (midCell[1] + 0.5) * res, (midCell[2] + 0.5) * res + 0.18);
        pointCount = 1;
      }

      if (pointCount > 0) {
        const prevLabel = this.createLabelSprite('previous route', '#94a3b8');
        prevLabel.scale.set(0.5, 0.16, 1);
        prevLabel.position.copy(midpoint);
        oldGroup.add(prevLabel);
      }

      this.previousRoutesGroup.add(oldGroup);
      this.fadingRoutes.push({
        group: oldGroup,
        materials: oldMaterials,
        startTime: now,
        fadeDuration: 1000, // 1 s to fade to 20%
        totalLifetime: 8000, // Keep for 8 s
        startOpacity: 1.0,
        targetOpacity: 0.2 // 20% opacity
      });
    }

    // 2. Build new route TubeGeometry in solid blue
    const points: THREE.Vector3[] = [];
    for (const [ci, cj, ck] of route.cells) {
      points.push(new THREE.Vector3(
        (ci + 0.5) * res,
        (cj + 0.5) * res,
        (ck + 0.5) * res + 0.038
      ));
    }

    if (points.length >= 2) {
      const curve = new THREE.CatmullRomCurve3(points, false, 'centripetal');
      const tubeGeom = new THREE.TubeGeometry(curve, Math.max(points.length * 8, 24), 0.035, 10, false);
      const tubeMat = new THREE.MeshStandardMaterial({
        color: 0x2563eb, // Solid blue
        emissive: 0x1d4ed8,
        emissiveIntensity: 0.65,
        roughness: 0.2,
        metalness: 0.1
      });
      const tube = new THREE.Mesh(tubeGeom, tubeMat);
      this.activeRouteGroup.add(tube);

      // Start & destination waypoint markers
      const startMarkerGeom = new THREE.SphereGeometry(0.06, 16, 16);
      const startMarkerMat = new THREE.MeshStandardMaterial({ color: 0x10b981, emissive: 0x059669 });
      const startMarker = new THREE.Mesh(startMarkerGeom, startMarkerMat);
      startMarker.position.copy(points[0]);
      this.activeRouteGroup.add(startMarker);

      const destMarkerGeom = new THREE.SphereGeometry(0.07, 16, 16);
      const destMarkerMat = new THREE.MeshStandardMaterial({ color: 0x38bdf8, emissive: 0x0284c7 });
      const destMarker = new THREE.Mesh(destMarkerGeom, destMarkerMat);
      destMarker.position.copy(points[points.length - 1]);
      this.activeRouteGroup.add(destMarker);
    } else if (points.length === 1) {
      const dotGeom = new THREE.SphereGeometry(0.06, 16, 16);
      const dotMat = new THREE.MeshStandardMaterial({ color: 0x2563eb, emissive: 0x1d4ed8 });
      const dot = new THREE.Mesh(dotGeom, dotMat);
      dot.position.copy(points[0]);
      this.activeRouteGroup.add(dot);
    }

    // 3. Update Banner with route reason if world-change was active
    const reasonText = route.reason || route.goal || 'Re-planned path to target';
    this.showReplanReasonBanner(route.id, reasonText);
  }

  /**
   * On world/change:
   * Show banner "Aftershock detected: b7 moved. Re-scanning" and flash moved blocks red.
   */
  public onWorldChange(payload: WorldChangePayload): void {
    if (!payload) return;
    const moved = Array.isArray(payload.moved_blocks) && payload.moved_blocks.length > 0
      ? payload.moved_blocks.join(', ')
      : 'b7';

    // 1. Show Aftershock Banner
    this.showAftershockBanner(`Aftershock detected: ${moved} moved. Re-scanning`);

    // 2. Flash the moved blocks red in 3D
    this.flashMovedBlocksRed(payload.moved_blocks || ['b7']);
  }

  /**
   * route/verified ok:false draws the unstable cells in red with the detail.
   */
  public onRouteVerified(payload: RouteVerifiedPayload): void {
    if (!payload) return;
    this.unstableCellsGroup.clear();

    if (!payload.ok) {
      const res = this.cellResolution;
      const unstableCells = payload.unstable_cells || [];
      const detailText = payload.detail || 'Physics check failed';

      const boxGeom = new THREE.BoxGeometry(res * 1.15, res * 1.15, res * 1.15);
      const boxMat = new THREE.MeshStandardMaterial({
        color: 0xef4444,
        emissive: 0xdc2626,
        emissiveIntensity: 0.85,
        transparent: true,
        opacity: 0.9
      });

      for (const [ci, cj, ck] of unstableCells) {
        const x = (ci + 0.5) * res;
        const y = (cj + 0.5) * res;
        const z = (ck + 0.5) * res;

        const cellMesh = new THREE.Mesh(boxGeom, boxMat);
        cellMesh.position.set(x, y, z);
        this.unstableCellsGroup.add(cellMesh);

        // Warning label above unstable cell
        const warningSprite = this.createLabelSprite(`Unstable (${detailText})`, '#ef4444');
        warningSprite.position.set(x, y, z + 0.28);
        this.unstableCellsGroup.add(warningSprite);
      }
    }
  }

  private showAftershockBanner(text: string): void {
    if (this.bannerTimeoutId !== null) {
      window.clearTimeout(this.bannerTimeoutId);
      this.bannerTimeoutId = null;
    }

    if (this.bannerElement && this.bannerTextElement && this.bannerIconElement) {
      this.bannerElement.className = 'world-change-banner aftershock-banner visible';
      this.bannerIconElement.textContent = '⚠️';
      this.bannerTextElement.textContent = text;
    }
  }

  private showReplanReasonBanner(routeId: string, reason: string): void {
    if (this.bannerElement && this.bannerTextElement && this.bannerIconElement) {
      this.bannerElement.className = 'world-change-banner replan-banner visible';
      this.bannerIconElement.textContent = '🔄';
      this.bannerTextElement.textContent = `Re-plan (${routeId}): ${reason}`;

      // Automatically hide banner after 8 seconds
      this.bannerTimeoutId = window.setTimeout(() => {
        this.hideBanner();
      }, 8000);
    }
  }

  public hideBanner(): void {
    if (this.bannerElement) {
      this.bannerElement.className = 'world-change-banner hidden';
    }
  }

  private flashMovedBlocksRed(blockIds: string[]): void {
    this.movedBlocksGroup.clear();
    this.movedBlockMeshes = [];

    // Map block names to backup scene coordinates
    const blockPositions: Record<string, { pos: [number, number, number]; size: [number, number, number] }> = {
      b7: { pos: [0, 0.97, 0.25], size: [0.08, 0.48, 0.4] },
      b8: { pos: [1.25, -0.32, 0.25], size: [0.08, 0.62, 0.4] },
      b10: { pos: [0.97, -0.5, 0.18], size: [0.38, 0.22, 0.08] },
      b11: { pos: [1.25, 0.45, 0.08], size: [0.12, 0.16, 0.1] }
    };

    for (const id of blockIds) {
      const def = blockPositions[id] || { pos: [0, 1.0, 0.2], size: [0.2, 0.4, 0.3] };
      const geom = new THREE.BoxGeometry(def.size[0], def.size[1], def.size[2]);
      const mat = new THREE.MeshStandardMaterial({
        color: 0xef4444,
        emissive: 0xdc2626,
        emissiveIntensity: 0.9,
        transparent: true,
        opacity: 0.85
      });
      const mesh = new THREE.Mesh(geom, mat);
      mesh.position.set(def.pos[0], def.pos[1], def.pos[2]);
      this.movedBlocksGroup.add(mesh);
      this.movedBlockMeshes.push(mesh);

      const label = this.createLabelSprite(`Moved block: ${id}`, '#ef4444');
      label.position.set(def.pos[0], def.pos[1], def.pos[2] + def.size[2] / 2 + 0.16);
      this.movedBlocksGroup.add(label);
    }
  }

  private updateFadingRoutes(now: number): void {
    for (let i = this.fadingRoutes.length - 1; i >= 0; i--) {
      const item = this.fadingRoutes[i];
      const elapsed = now - item.startTime;

      if (elapsed < item.fadeDuration) {
        // Linear fade from startOpacity (1.0) to targetOpacity (0.2) over 1s
        const t = elapsed / item.fadeDuration;
        const opacity = item.startOpacity - (item.startOpacity - item.targetOpacity) * t;
        for (const mat of item.materials) {
          mat.opacity = opacity;
        }
      } else if (elapsed < item.totalLifetime) {
        // Maintain at 20% opacity for up to 8s
        for (const mat of item.materials) {
          mat.opacity = item.targetOpacity;
        }
      } else {
        // Remove after 8s
        this.previousRoutesGroup.remove(item.group);
        item.group.traverse(obj => {
          if (obj instanceof THREE.Mesh) {
            obj.geometry.dispose();
            if (Array.isArray(obj.material)) obj.material.forEach(m => m.dispose());
            else obj.material.dispose();
          }
        });
        this.fadingRoutes.splice(i, 1);
      }
    }
  }

  private updateMovedBlocksAnimation(time: number): void {
    if (this.movedBlockMeshes.length === 0) return;
    const pulse = 0.5 + 0.5 * Math.sin(time * 0.008);
    for (const mesh of this.movedBlockMeshes) {
      if (mesh.material instanceof THREE.MeshStandardMaterial) {
        mesh.material.emissiveIntensity = 0.4 + 0.6 * pulse;
      }
    }
  }

  /**
   * Helper to simulate aftershock and visible re-plan on demand
   */
  public simulateAftershockAndReplan(): void {
    const res = this.cellResolution;

    // 1. Fire aftershock
    this.onWorldChange({
      kind: 'aftershock',
      t: performance.now() / 1000,
      moved_blocks: ['b7']
    });

    // 2. Mark route verification failure for old route
    this.onRouteVerified({
      id: 'r3',
      ok: false,
      unstable_cells: [[Math.round(0 / res), Math.round(1.0 / res), 0]],
      detail: 'block b7 falls across doorway'
    });

    // 3. Propose new route after 1.5 seconds avoiding b7
    window.setTimeout(() => {
      this.updateRouteProposed({
        id: 'r4',
        robot: 'responder',
        cells: [
          [Math.round(-0.8 / res), Math.round(-1.2 / res), 0],
          [Math.round(-0.65 / res), Math.round(-0.85 / res), 0],
          [Math.round(-0.2 / res), Math.round(-0.4 / res), 0],
          [Math.round(0.4 / res), Math.round(-0.2 / res), 0],
          [Math.round(1.0 / res), Math.round(0.1 / res), 0],
          [Math.round(1.95 / res), Math.round(0.98 / res), 0]
        ],
        goal: 'deliver water to c1',
        reason: 'avoiding collapsed block b7 toward casualty c1',
        model: 'local-astar'
      });

      // Move Responder to route
      this.responderGroup.position.set(-0.2, -0.4, 0);
    }, 1500);
  }

  /**
   * Populates the map with the standard AFTERSHOCK collapsed building backup scene
   * (walls b1-b9, doorway, leaning slab b10 at risk, rubble b11-b15).
   * Ensures ?fake=1 immediately displays a coloured map with casualty, hazards and route.
   */
  public loadBackupSceneDemo(): void {
    const res = DEFAULT_RES;
    const cells: GridCell[] = [];

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

    // Perimeter walls
    addBox(-1.5, 2.5, 1.45, 1.55, 0, 0.4);
    addBox(-1.55, -1.45, -1.0, 1.5, 0, 0.4);
    addBox(-1.45, -1.0, -1.05, -0.95, 0, 0.4);
    addBox(-0.4, 2.45, -1.05, -0.95, 0, 0.4);
    addBox(2.45, 2.55, -1.0, 1.5, 0, 0.4);

    // Interior dividing wall 1 (door y: 0.0 to 0.5)
    addBox(-0.05, 0.05, -0.95, 0.0, 0, 0.4);
    addBox(-0.05, 0.05, 0.5, 1.45, 0, 0.4); // b7 wall north of doorway

    // Interior dividing wall 2
    addBox(1.2, 1.3, -0.95, 0.3, 0, 0.4);
    addBox(1.2, 1.3, 0.9, 1.45, 0, 0.4);

    // Rubble & leaning slab b10 (at risk)
    addBox(0.8, 1.15, -0.6, -0.4, 0, 0.25, 'seen');
    addBox(-0.8, -0.6, -0.7, -0.5, 0, 0.15, 'seen');
    addBox(1.15, 1.35, 0.4, 0.55, 0, 0.1, 'inferred');
    addBox(1.6, 2.2, -0.5, -0.3, 0, 0.08, 'inferred');

    this.updateCells({ t: 0, res, cells });

    const hazards: HazardRecord[] = [];
    const b10_i0 = Math.round(0.8 / res);
    const b10_i1 = Math.round(1.15 / res);
    const b10_j0 = Math.round(-0.6 / res);
    const b10_j1 = Math.round(-0.4 / res);
    for (let i = b10_i0; i <= b10_i1; i++) {
      for (let j = b10_j0; j <= b10_j1; j++) {
        hazards.push({ cell: [i, j, 0], status: 'at_risk', why: 'unsupported leaning slab b10', estimate: true });
        hazards.push({ cell: [i, j, 1], status: 'at_risk', why: 'unsupported leaning slab b10', estimate: true });
      }
    }
    hazards.push({
      cell: [Math.round(-0.7 / res), Math.round(-0.6 / res), 0],
      status: 'collapsed',
      why: 'breach collapse pile b12',
      estimate: true
    });
    this.updateHazards(hazards);

    this.updateCasualties([
      {
        id: 'c1',
        pos: [1.95, 0.98, 0.0],
        confidence: 0.82,
        clues: ['thermal', 'sound'],
        vitals: { breathing_rate: 14, simulated: true }
      }
    ]);

    this.updateScoutPose({
      t: 0,
      pose: { pos: [-0.65, -0.85, 0.0], yaw: Math.PI / 4 }
    });

    this.responderGroup.position.set(-0.8, -1.2, 0);

    // Initial proposed route r3 in solid blue
    this.updateRouteProposed({
      id: 'r3',
      robot: 'responder',
      cells: [
        [Math.round(-0.8 / res), Math.round(-1.2 / res), 0],
        [Math.round(-0.65 / res), Math.round(-0.85 / res), 0],
        [Math.round(-0.05 / res), Math.round(0.25 / res), 0],
        [Math.round(0.0 / res), Math.round(0.8 / res), 0]
      ],
      goal: 'deliver water to c1',
      model: 'local-astar'
    });
  }

  public generate100kBenchmark(): void {
    const res = DEFAULT_RES;
    const cells: GridCell[] = [];
    const hazards: HazardRecord[] = [];

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

    this.camera.position.set(6, -8, 8);
    this.controls.target.set(0, 0, 0.5);
    this.controls.update();
  }

  public destroy(): void {
    if (this.animationFrameId !== null) {
      cancelAnimationFrame(this.animationFrameId);
    }
    if (this.bannerTimeoutId !== null) {
      window.clearTimeout(this.bannerTimeoutId);
    }
    this.controls.dispose();
    this.renderer.dispose();
  }
}
