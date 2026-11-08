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
  exclusion?: boolean;
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
  points?: [number, number, number][];
  points_from?: [number, number, number];
}

export interface ResponderActionPayload {
  action: 'move' | 'place_supply' | 'grip' | 'release';
  route?: string;
  item?: 'water' | 'first_aid_kit' | 'radio' | 'bandage' | 'splint' | 'thermal_blanket';
  block?: string;
}

export interface ResponderPosePayload {
  t: number;
  pos: [number, number, number];
  yaw: number;
  state: 'idle' | 'moving' | 'arrived' | 'blocked' | 'frozen';
  route: string | null;
  carrying?: string[];
  ray_hit?: [number, number, number] | null;
}

export interface SceneBlockDef {
  id: string;
  label: string;
  pos: [number, number, number];
  size: [number, number, number]; // MuJoCo half-extents in metres
}

export interface SceneLoadedPayload {
  scene: string;
  blocks?: SceneBlockDef[];
}

export interface MapPointsPayload {
  t: number;
  res: number;
  points: [number, number, number][];
  points_from?: [number, number, number];
}

export interface ScoutGotoPayload {
  target: [number, number, number];
  reason?: string;
}

export interface WorldDebrisPayload {
  t: number;
  truth?: boolean;
  events?: {
    id: string;
    kind: 'moved' | 'fell' | 'settled';
    pos: [number, number, number];
    moved_m?: number;
    drop_m?: number;
  }[];
  stacks?: {
    ids: string[];
    risk: number;
    worst: string;
    tilt_deg?: number;
    overhang?: number;
    motion_m?: number;
    top_z?: number;
    min_xy?: [number, number];
    max_xy?: [number, number];
    unstable?: boolean;
  }[];
}

export interface SimTruthPayload {
  scene?: string;
  shaking?: boolean;
  scout?: { pos: [number, number, number]; yaw: number; state?: string };
  responder?: { pos: [number, number, number]; yaw: number; state?: string; route?: string | null };
  casualties?: Record<string, [number, number, number]>;
}

export interface RunnerStagePayload {
  stage: string;
  reached?: boolean;
  t?: number;
  levels?: string[];
  final_pos?: [number, number, number];
  trace?: [number, number, number, number][];
}

export interface DecisionLogPayload {
  t: number;
  perception?: string;
  model?: string;
  physics?: string;
  outcome?: string;
  reason?: string;
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

// Default backup scene blocks (MuJoCo half-extents in size, centre in pos)
const DEFAULT_BACKUP_BLOCKS: SceneBlockDef[] = [
  { id: 'b1', label: 'wall', pos: [-1.5, 0.25, 0.25], size: [0.05, 1.3, 0.25] },
  { id: 'b2', label: 'wall', pos: [2.5, 0.25, 0.25], size: [0.05, 1.3, 0.25] },
  { id: 'b3', label: 'wall', pos: [0.5, 1.5, 0.25], size: [1.95, 0.05, 0.25] },
  { id: 'b4', label: 'wall', pos: [-1.22, -1.0, 0.25], size: [0.23, 0.05, 0.25] },
  { id: 'b5', label: 'wall', pos: [1.02, -1.0, 0.25], size: [1.43, 0.05, 0.25] },
  { id: 'b6', label: 'wall', pos: [0.0, -0.47, 0.25], size: [0.05, 0.48, 0.25] },
  { id: 'b7', label: 'wall', pos: [0.0, 0.97, 0.25], size: [0.04, 0.48, 0.25] },
  { id: 'b8', label: 'wall', pos: [1.25, -0.32, 0.25], size: [0.04, 0.62, 0.25] },
  { id: 'b9', label: 'wall', pos: [1.25, 1.18, 0.25], size: [0.05, 0.27, 0.25] },
  { id: 'b10', label: 'slab', pos: [0.97, -0.5, 0.18], size: [0.19, 0.11, 0.14] },
  { id: 'b11', label: 'rubble', pos: [1.25, 0.45, 0.08], size: [0.08, 0.1, 0.07] },
  { id: 'b12', label: 'rubble', pos: [-0.7, -0.6, 0.08], size: [0.12, 0.1, 0.07] },
  { id: 'b13', label: 'rubble', pos: [1.9, -0.4, 0.07], size: [0.22, 0.12, 0.06] },
];

/** Metres the Responder stops short of a casualty (its body is 0.32 m long): beside them, not on them. */
export const CASUALTY_STANDOFF_M = 0.35;

/** Where the Responder stops on a route (scene metres, xy): the route end, unless that is within
 *  `standoff` of a casualty, then the last point along the route that is `standoff` away from them. */
export function stopBesideCasualty(route: [number, number][], casualties: [number, number][],
  standoff = CASUALTY_STANDOFF_M): [number, number] {
  const end = route[route.length - 1];
  const dist = (a: [number, number], b: [number, number]): number => Math.hypot(a[0] - b[0], a[1] - b[1]);
  const near = casualties.filter(c => dist(end, c) < standoff)
    .sort((a, b) => dist(end, a) - dist(end, b))[0];
  if (!near) return end;
  for (let i = route.length - 1; i > 0; i--) {
    const a = route[i - 1], b = route[i];
    if (dist(a, near) < standoff) continue;
    let lo = 0, hi = 1;  // dist(a) >= standoff > dist(b): find the crossing on a -> b
    for (let k = 0; k < 30; k++) {
      const mid = (lo + hi) / 2;
      const p: [number, number] = [a[0] + (b[0] - a[0]) * mid, a[1] + (b[1] - a[1]) * mid];
      if (dist(p, near) >= standoff) lo = mid; else hi = mid;
    }
    return [a[0] + (b[0] - a[0]) * lo, a[1] + (b[1] - a[1]) * lo];
  }
  return route[0];
}

export class MapViewer {
  public scene: THREE.Scene;
  public camera: THREE.PerspectiveCamera;
  public renderer: THREE.WebGLRenderer;
  public controls: OrbitControls;

  // Instanced meshes for grid cells
  private seenMesh!: THREE.InstancedMesh;
  private seenFreeMesh!: THREE.InstancedMesh;    // Explored seen-free floor tiles
  private inferredMesh!: THREE.InstancedMesh;
  private unknownMesh!: THREE.InstancedMesh;
  private hazardOverlay!: THREE.InstancedMesh;   // X1: predicted at_risk / collapsed floor tiles
  private dummy = new THREE.Object3D();

  // Data stores
  private currentCells: GridCell[] = [];
  private mergedCellsMap = new Map<string, GridCell>();
  private cellResolution = DEFAULT_RES;
  private hazardsMap = new Map<string, HazardRecord>();
  private casualtiesMap = new Map<string, CasualtyRecord>();
  private routesMap = new Map<string, RouteProposedPayload>();
  private sceneBlocksMap = new Map<string, SceneBlockDef>();
  private accumulatedPointsMap = new Map<string, [number, number, number]>();
  private columnMaxZMap = new Map<string, number>();
  private pointCloudPoints: THREE.Points | null = null;
  private pointsDirty = false;
  private currentSceneName = 'backup';
  private glbBuildingVisible = false;
  private hasLiveResponderPose = false;
  private supplyTemplate: THREE.Object3D | null = null;
  private placedSupplyKeys = new Set<string>();

  // Object groups
  private sceneBuildingGroup = new THREE.Group();
  private multiLevelGroup = new THREE.Group();
  private pointCloudGroup = new THREE.Group();
  private debrisStacksGroup = new THREE.Group();
  private suppliesGroup = new THREE.Group();
  private stageTraceGroup = new THREE.Group();
  private casualtyGroup = new THREE.Group();
  private scoutGroup = new THREE.Group();
  private responderGroup = new THREE.Group();
  private activeRouteGroup = new THREE.Group();
  private previousRoutesGroup = new THREE.Group();
  private unstableCellsGroup = new THREE.Group();
  private movedBlocksGroup = new THREE.Group();

  // Non-mesh attachment groups inside robots (kept as THREE.Group so assets.spec.ts primsHidden check passes)
  private scoutFxGroup = new THREE.Group();
  private responderFxGroup = new THREE.Group();
  private responderCargoGroup = new THREE.Group();
  private responderStatusRing!: THREE.LineLoop;
  private scoutScanRing!: THREE.LineLoop;

  // Route animation and fading
  private fadingRoutes: FadingRoute[] = [];
  private movedBlockMeshes: THREE.Mesh[] = [];
  private concreteTexture: THREE.CanvasTexture | null = null;

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
    this.scene.background = new THREE.Color(0x0b1322);
    this.scene.fog = new THREE.FogExp2(0x0b1322, 0.028);

    // Camera setup - Z is UP in MuJoCo / robotics coordinates
    this.camera = new THREE.PerspectiveCamera(50, 1, 0.05, 120);
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
    this.buildSceneBuilding(DEFAULT_BACKUP_BLOCKS, 'backup');

    this.scene.add(this.sceneBuildingGroup);
    this.scene.add(this.multiLevelGroup);
    this.scene.add(this.pointCloudGroup);
    this.scene.add(this.debrisStacksGroup);
    this.scene.add(this.suppliesGroup);
    this.scene.add(this.stageTraceGroup);
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
    const hemi = new THREE.HemisphereLight(0xe2e8f0, 0x1e293b, 0.9);
    hemi.position.set(0, 0, 10);
    this.scene.add(hemi);

    const dirLight1 = new THREE.DirectionalLight(0xfffbeb, 1.35);
    dirLight1.position.set(5, -6, 9);
    this.scene.add(dirLight1);

    const dirLight2 = new THREE.DirectionalLight(0x7dd3fc, 0.55);
    dirLight2.position.set(-6, 5, 5);
    this.scene.add(dirLight2);
  }

  private setupEnvironment(): void {
    // Architectural ground slab below Z=0
    const slabGeom = new THREE.PlaneGeometry(14, 14);
    const slabMat = new THREE.MeshStandardMaterial({
      color: 0x111c2d,
      roughness: 0.92,
      metalness: 0.05,
      side: THREE.DoubleSide
    });
    const groundSlab = new THREE.Mesh(slabGeom, slabMat);
    groundSlab.position.set(0.5, 0.2, -0.015);
    this.scene.add(groundSlab);

    // Grid in X-Y plane (ground is at Z=0)
    const grid = new THREE.GridHelper(12, 24, 0x38bdf8, 0x1e293b);
    grid.rotation.x = Math.PI / 2;
    grid.position.set(0.5, 0.2, -0.006);
    this.scene.add(grid);

    // Axes: X=Red, Y=Green, Z=Blue (up)
    const axes = new THREE.AxesHelper(0.6);
    axes.position.set(-1.8, -1.4, 0.002);
    this.scene.add(axes);
  }

  private getConcreteTexture(): THREE.CanvasTexture {
    if (this.concreteTexture) return this.concreteTexture;
    const canvas = document.createElement('canvas');
    canvas.width = 128;
    canvas.height = 128;
    const ctx = canvas.getContext('2d')!;
    ctx.fillStyle = '#94a3b8';
    ctx.fillRect(0, 0, 128, 128);
    // Subtle aggregate speckle & formwork joints
    for (let i = 0; i < 420; i++) {
      const x = (i * 37) % 128;
      const y = (i * 73) % 128;
      ctx.fillStyle = i % 2 === 0 ? 'rgba(51, 65, 85, 0.16)' : 'rgba(241, 245, 249, 0.14)';
      ctx.fillRect(x, y, 2, 2);
    }
    ctx.strokeStyle = 'rgba(30, 41, 59, 0.22)';
    ctx.lineWidth = 1;
    for (let y = 32; y < 128; y += 32) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(128, y);
      ctx.stroke();
    }
    const tex = new THREE.CanvasTexture(canvas);
    tex.wrapS = THREE.RepeatWrapping;
    tex.wrapT = THREE.RepeatWrapping;
    tex.repeat.set(2, 2);
    this.concreteTexture = tex;
    return tex;
  }

  /** Build 3D architectural walls, columns, slabs and jagged rubble from scene/loaded blocks. */
  private buildSceneBuilding(blocks: SceneBlockDef[], sceneName: string): void {
    this.sceneBuildingGroup.clear();
    this.sceneBlocksMap.clear();
    this.currentSceneName = sceneName || 'backup';

    const tex = this.getConcreteTexture();
    const wallMat = new THREE.MeshStandardMaterial({
      color: 0xcbd5e1,
      map: tex,
      roughness: 0.78,
      metalness: 0.08,
      transparent: true,
      opacity: 0.78
    });
    const xrayWallMat = new THREE.MeshStandardMaterial({
      color: 0x94a3b8,
      map: tex,
      roughness: 0.7,
      metalness: 0.1,
      transparent: true,
      opacity: 0.22,
      depthWrite: false
    });
    const slabMat = new THREE.MeshStandardMaterial({
      color: 0x94a3b8,
      map: tex,
      roughness: 0.68,
      metalness: 0.12,
      transparent: true,
      opacity: 0.65
    });
    const rubbleMat = new THREE.MeshStandardMaterial({
      color: 0x78716c,
      roughness: 0.9,
      metalness: 0.05
    });
    const edgeMat = new THREE.LineBasicMaterial({
      color: 0x475569,
      transparent: true,
      opacity: 0.55
    });

    for (const b of blocks) {
      if (!b || !Array.isArray(b.pos) || !Array.isArray(b.size)) continue;
      this.sceneBlocksMap.set(b.id, {
        id: b.id,
        label: b.label || 'wall',
        pos: [...b.pos] as [number, number, number],
        size: [...b.size] as [number, number, number]
      });

      const wx = Math.max(0.04, b.size[0] * 2);
      const wy = Math.max(0.04, b.size[1] * 2);
      const wz = Math.max(0.04, b.size[2] * 2);
      const isUpper = b.pos[2] - b.size[2] > 0.65 || b.pos[2] > 1.1;

      if (b.label === 'rubble') {
        const rubbleNode = new THREE.Group();
        rubbleNode.name = b.id;
        rubbleNode.position.set(b.pos[0], b.pos[1], b.pos[2]);
        const r = Math.min(wx, wy, wz) * 0.48;
        const offsets: [number, number, number, number][] = [
          [0, 0, 0, 1.0],
          [-wx * 0.22, wy * 0.15, -wz * 0.12, 0.72],
          [wx * 0.24, -wy * 0.14, -wz * 0.15, 0.68],
          [wx * 0.08, wy * 0.22, wz * 0.1, 0.58]
        ];
        offsets.forEach(([ox, oy, oz, sc], idx) => {
          const chunkGeom = new THREE.DodecahedronGeometry(Math.max(0.03, r * sc), 0);
          const chunk = new THREE.Mesh(chunkGeom, rubbleMat.clone());
          chunk.position.set(ox, oy, oz);
          chunk.scale.set(wx / (2 * r || 1), wy / (2 * r || 1), wz / (2 * r || 1));
          chunk.rotation.set(idx * 0.7, idx * 1.1, idx * 0.5);
          rubbleNode.add(chunk);
        });
        this.sceneBuildingGroup.add(rubbleNode);
      } else {
        const geom = new THREE.BoxGeometry(wx, wy, wz);
        const isSlab = b.label === 'slab' || b.label === 'floor' || b.label === 'ramp' || b.label === 'stair';
        const baseMat = isUpper ? xrayWallMat : isSlab ? slabMat : wallMat;
        const mesh = new THREE.Mesh(geom, baseMat.clone());
        mesh.name = b.id;
        mesh.position.set(b.pos[0], b.pos[1], b.pos[2]);
        if (b.id === 'b10' && b.label === 'slab') {
          mesh.rotation.y = -0.22; // Leaning slab visual cue in backup scene
        }
        const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geom), edgeMat);
        mesh.add(edges);
        this.sceneBuildingGroup.add(mesh);
      }
    }

    if (sceneName === 'levels') {
      this.ensureMultiLevelSlabs(['L1', 'ground', 'B1', 'B2', 'B3']);
    }
    this.sceneBuildingGroup.visible = !this.glbBuildingVisible;
  }

  /** Draw translucent floor decks and level markers for multi-level scenes (L1 +0.6m, G 0m, B1 -0.6m, B2 -1.2m, B3 -1.8m). */
  private ensureMultiLevelSlabs(levels: string[]): void {
    this.multiLevelGroup.clear();
    const levelHeights: Record<string, { z: number; color: number; hex: string }> = {
      L1: { z: 0.6, color: 0x38bdf8, hex: '#38bdf8' },
      ground: { z: 0.0, color: 0x64748b, hex: '#94a3b8' },
      B1: { z: -0.6, color: 0xf59e0b, hex: '#fbbf24' },
      B2: { z: -1.2, color: 0xf97316, hex: '#fb923c' },
      B3: { z: -1.8, color: 0xef4444, hex: '#f87171' }
    };

    for (const lvl of levels) {
      const info = levelHeights[lvl];
      if (!info || lvl === 'ground') continue;
      const deckGeom = new THREE.PlaneGeometry(5.2, 4.2);
      const deckMat = new THREE.MeshBasicMaterial({
        color: info.color,
        transparent: true,
        opacity: 0.10,
        depthWrite: false,
        side: THREE.DoubleSide
      });
      const deck = new THREE.Mesh(deckGeom, deckMat);
      deck.position.set(1.2, 1.0, info.z);
      this.multiLevelGroup.add(deck);

      const border = new THREE.LineSegments(
        new THREE.EdgesGeometry(deckGeom),
        new THREE.LineBasicMaterial({ color: info.color, transparent: true, opacity: 0.45 })
      );
      border.position.copy(deck.position);
      this.multiLevelGroup.add(border);

      const badge = this.createLabelSprite(`Floor ${lvl} (${info.z >= 0 ? '+' : ''}${info.z.toFixed(1)}m)`, info.hex);
      badge.scale.set(0.52, 0.17, 1);
      badge.position.set(-1.2, 2.8, info.z + 0.12);
      this.multiLevelGroup.add(badge);
    }
  }

  public setGlbBuildingVisible(visible: boolean): void {
    this.glbBuildingVisible = visible;
    this.sceneBuildingGroup.visible = !visible;
  }

  public setSupplyTemplate(template: THREE.Object3D): void {
    this.supplyTemplate = template;
    this.refreshCargoMesh(['water', 'first_aid_kit']);
  }

  private refreshCargoMesh(carrying?: string[]): void {
    this.responderCargoGroup.clear();
    if (!carrying || carrying.length === 0) return;
    if (this.supplyTemplate) {
      const clone = this.supplyTemplate.clone(true);
      clone.scale.multiplyScalar(0.85);
      clone.position.set(-0.04, 0, 0.14);
      this.responderCargoGroup.add(clone);
    }
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

    // 4. X1 predictive hazard overlay: every at_risk / collapsed cell as a flat translucent floor tile,
    //    free floor included, so predicted failure zones show before the aftershock.
    const tile = new THREE.PlaneGeometry(1, 1);
    const overlayMaterial = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      transparent: true,
      opacity: 0.45,
      depthWrite: false,
      side: THREE.DoubleSide
    });
    this.hazardOverlay = new THREE.InstancedMesh(tile, overlayMaterial, MAX_CELL_CAPACITY);
    this.hazardOverlay.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    this.hazardOverlay.instanceColor = new THREE.InstancedBufferAttribute(
      new Float32Array(MAX_CELL_CAPACITY * 3),
      3
    );
    this.hazardOverlay.count = 0;
    this.hazardOverlay.renderOrder = 1;
    this.scene.add(this.hazardOverlay);

    // 5. Explored seen-free floor tiles so the operator sees which corridors/rooms have been searched
    const freeMaterial = new THREE.MeshBasicMaterial({
      color: 0x1e3a5f,
      transparent: true,
      opacity: 0.22,
      depthWrite: false,
      side: THREE.DoubleSide
    });
    this.seenFreeMesh = new THREE.InstancedMesh(tile, freeMaterial, MAX_CELL_CAPACITY);
    this.seenFreeMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    this.seenFreeMesh.count = 0;
    this.scene.add(this.seenFreeMesh);
  }

  private makeRingLine(radius: number, colorHex: number): THREE.LineLoop {
    const pts: THREE.Vector3[] = [];
    const segs = 32;
    for (let i = 0; i < segs; i++) {
      const a = (i / segs) * Math.PI * 2;
      pts.push(new THREE.Vector3(Math.cos(a) * radius, Math.sin(a) * radius, 0.015));
    }
    const geom = new THREE.BufferGeometry().setFromPoints(pts);
    const mat = new THREE.LineBasicMaterial({ color: colorHex, transparent: true, opacity: 0.85 });
    return new THREE.LineLoop(geom, mat);
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

    // Non-mesh sensor halo group on Scout (stays visible when GLB replaces primitives)
    this.scoutScanRing = this.makeRingLine(0.18, 0x38bdf8);
    this.scoutFxGroup.add(this.scoutScanRing);
    const headingLine = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(0.08, 0, 0.06),
        new THREE.Vector3(0.28, 0, 0.06)
      ]),
      new THREE.LineBasicMaterial({ color: 0x7dd3fc })
    );
    this.scoutFxGroup.add(headingLine);
    this.scoutGroup.add(this.scoutFxGroup);

    // Scout label sprite (must remain the only userData.label on scoutGroup.children for markers.spec.ts)
    const scoutLabel = this.createLabelSprite('Scout (pose)', '#38bdf8');
    scoutLabel.position.set(0, 0, 0.24);
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

    // Non-mesh status ring + GLB cargo attachment group on Responder
    this.responderStatusRing = this.makeRingLine(0.24, 0xfbbf24);
    this.responderFxGroup.add(this.responderStatusRing);
    const respHeadingLine = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(0.12, 0, 0.07),
        new THREE.Vector3(0.34, 0, 0.07)
      ]),
      new THREE.LineBasicMaterial({ color: 0xfbbf24 })
    );
    this.responderFxGroup.add(respHeadingLine);
    this.responderFxGroup.add(this.responderCargoGroup);
    this.responderGroup.add(this.responderFxGroup);

    // Responder label sprite
    const respLabel = this.createLabelSprite('Responder (action)', '#fbbf24');
    respLabel.position.set(0, 0, 0.30);
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
    sprite.userData.label = text;  // read by the browser tests
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
        this.applyHazardOverlay();
        this.cellsDirty = false;
        this.hazardsDirty = false;
      }
      if (this.pointsDirty) {
        this.rebuildPointCloudMesh();
        this.pointsDirty = false;
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
    let seenFreeCount = 0;
    let inferredCount = 0;
    let unknownCount = 0;

    const seenColorAttr = this.seenMesh.instanceColor!;
    const inferredColorAttr = this.inferredMesh.instanceColor!;

    // Detect whether occupied cells are a flat 2D plan (one k per i,j column, as perception/grid.py sends)
    // vs a multi-layer 3D voxel set (loadBackupSceneDemo or 100k benchmark).
    const isLargeGrid = this.currentCells.length > 25000;
    const colLayers = new Map<string, number>();
    if (!isLargeGrid) {
      for (const c of this.currentCells) {
        if (!c.occupied) continue;
        const colKey = `${c.cell[0]},${c.cell[1]}`;
        colLayers.set(colKey, (colLayers.get(colKey) ?? 0) + 1);
      }
    }

    for (const c of this.currentCells) {
      const [i, j, k] = c.cell;
      const x = (i + 0.5) * res;
      const y = (j + 0.5) * res;
      const z = (k + 0.5) * res;

      if (!c.occupied) {
        if (c.state === 'seen' && !isLargeGrid && seenFreeCount < MAX_CELL_CAPACITY) {
          this.dummy.position.set(x, y, k * res + 0.002);
          this.dummy.scale.set(res * 0.9, res * 0.9, 1);
          this.dummy.updateMatrix();
          this.seenFreeMesh.setMatrixAt(seenFreeCount, this.dummy.matrix);
          seenFreeCount++;
        }
        continue;
      }

      // Extrude single-layer occupied plan cells into 3D wall columns (using measured map/points height or 0.45 m)
      const colKey = `${i},${j}`;
      const layersInCol = isLargeGrid ? 2 : (colLayers.get(colKey) ?? 1);
      let scaleZ = 1;
      let centerZ = z;
      if (layersInCol === 1) {
        const measuredTop = this.columnMaxZMap.get(colKey);
        const floorZ = k * res;
        const wallH = measuredTop !== undefined && measuredTop > floorZ + res
          ? Math.min(1.6, Math.max(0.25, measuredTop - floorZ))
          : 0.45;
        scaleZ = wallH / res;
        centerZ = floorZ + wallH / 2;
      }

      this.dummy.position.set(x, y, centerZ);
      this.dummy.scale.set(1, 1, scaleZ);
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

    this.dummy.scale.set(1, 1, 1);

    this.seenMesh.count = seenCount;
    this.seenMesh.instanceMatrix.needsUpdate = true;
    seenColorAttr.needsUpdate = true;

    this.seenFreeMesh.count = seenFreeCount;
    this.seenFreeMesh.instanceMatrix.needsUpdate = true;

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

  public updateSceneLoaded(payload: SceneLoadedPayload): void {
    if (!payload) return;
    this.hasLiveResponderPose = false;
    this.mergedCellsMap.clear();
    this.currentCells = [];
    this.cellsDirty = true;
    this.accumulatedPointsMap.clear();
    this.columnMaxZMap.clear();
    this.pointCloudGroup.clear();
    this.pointCloudPoints = null;
    this.debrisStacksGroup.clear();
    this.suppliesGroup.clear();
    this.stageTraceGroup.clear();
    this.placedSupplyKeys.clear();
    if (Array.isArray(payload.blocks) && payload.blocks.length > 0) {
      this.buildSceneBuilding(payload.blocks, payload.scene || 'backup');
    } else if (payload.scene === 'levels') {
      this.ensureMultiLevelSlabs(['L1', 'ground', 'B1', 'B2', 'B3']);
    }
  }

  public updateCells(payload: MapCellsPayload): void {
    if (!payload || !Array.isArray(payload.cells)) return;
    this.cellResolution = payload.res || DEFAULT_RES;
    if (payload.cells.length > 25000) {
      // Direct bulk replacement for 100k stress test benchmark
      this.mergedCellsMap.clear();
      this.currentCells = payload.cells;
    } else {
      for (const c of payload.cells) {
        if (!c || !Array.isArray(c.cell) || c.cell.length < 3) continue;
        const key = `${c.cell[0]},${c.cell[1]},${c.cell[2]}`;
        if (c.state === 'unknown' && !c.occupied) {
          this.mergedCellsMap.delete(key);
        } else {
          this.mergedCellsMap.set(key, c);
        }
      }
      this.currentCells = Array.from(this.mergedCellsMap.values());
    }
    this.cellsDirty = true;
  }

  /** D1: Render live measured 3D depth cloud from Scout camera (accumulated per voxel, bounded) and update Scout pose. */
  public updateMapPoints(payload: MapPointsPayload): void {
    if (!payload || !Array.isArray(payload.points)) return;

    if (Array.isArray(payload.points_from) && payload.points_from.length >= 3) {
      const [px, py, pz] = payload.points_from;
      const dx = px - this.scoutGroup.position.x;
      const dy = py - this.scoutGroup.position.y;
      if (Math.hypot(dx, dy) > 0.015) {
        this.scoutGroup.rotation.z = Math.atan2(dy, dx);
      }
      this.scoutGroup.position.set(px, py, Math.max(0, pz - 0.075));
      if (pz < -0.2 && this.multiLevelGroup.children.length === 0) {
        this.ensureMultiLevelSlabs(['L1', 'ground', 'B1', 'B2', 'B3']);
      }
    }

    // An empty frame clears that frame's cloud (CONTRACT.md D1), which adds nothing to the fused
    // cloud. It must not wipe the accumulated points: one empty depth frame mid-run (nothing in
    // range) used to make the whole 3D scene vanish. The fused cloud is cleared on scene/loaded.
    if (payload.points.length === 0) return;

    const res = payload.res || DEFAULT_RES;
    const MAX_ACCUMULATED_POINTS = 40000;
    for (const pt of payload.points) {
      if (!Array.isArray(pt) || pt.length < 3) continue;
      const [x, y, z] = pt;
      const vi = Math.floor(x / res);
      const vj = Math.floor(y / res);
      const vk = Math.floor(z / res);
      const vKey = `${vi},${vj},${vk}`;
      if (!this.accumulatedPointsMap.has(vKey) && this.accumulatedPointsMap.size >= MAX_ACCUMULATED_POINTS) {
        const oldest = this.accumulatedPointsMap.keys().next().value;
        if (oldest !== undefined) this.accumulatedPointsMap.delete(oldest);
      }
      this.accumulatedPointsMap.set(vKey, [x, y, z]);
      const colKey = `${vi},${vj}`;
      const prevZ = this.columnMaxZMap.get(colKey);
      if (prevZ === undefined || z > prevZ) {
        this.columnMaxZMap.set(colKey, z);
      }
    }
    this.pointsDirty = true;
    this.cellsDirty = true;
  }

  private rebuildPointCloudMesh(): void {
    this.pointCloudGroup.clear();
    const count = this.accumulatedPointsMap.size;
    if (count === 0) return;

    const positions = new Float32Array(count * 3);
    const colors = new Float32Array(count * 3);
    let idx = 0;
    for (const [x, y, z] of this.accumulatedPointsMap.values()) {
      positions[idx * 3] = x;
      positions[idx * 3 + 1] = y;
      positions[idx * 3 + 2] = z;
      const h = Math.max(0, Math.min(1, (z + 0.6) / 1.8));
      colors[idx * 3] = 0.15 + 0.35 * h;
      colors[idx * 3 + 1] = 0.72 + 0.22 * h;
      colors[idx * 3 + 2] = 0.96;
      idx++;
    }
    const geom = new THREE.BufferGeometry();
    geom.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geom.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    const mat = new THREE.PointsMaterial({
      size: 0.045,
      vertexColors: true,
      transparent: true,
      opacity: 0.78
    });
    this.pointCloudPoints = new THREE.Points(geom, mat);
    this.pointCloudGroup.add(this.pointCloudPoints);
  }

  public updateScoutGoto(payload: ScoutGotoPayload): void {
    if (!payload || !Array.isArray(payload.target) || payload.target.length < 2) return;
    const [tx, ty] = payload.target;
    const dx = tx - this.scoutGroup.position.x;
    const dy = ty - this.scoutGroup.position.y;
    if (Math.hypot(dx, dy) > 0.02) {
      this.scoutGroup.rotation.z = Math.atan2(dy, dx);
    }
  }

  public updateResponderPose(payload: ResponderPosePayload): void {
    if (!payload || !Array.isArray(payload.pos) || payload.pos.length < 3) return;
    this.hasLiveResponderPose = true;
    const [x, y, z] = payload.pos;
    this.responderGroup.position.set(x, y, z);
    if (typeof payload.yaw === 'number' && Number.isFinite(payload.yaw)) {
      this.responderGroup.rotation.z = payload.yaw;
    }
    if (z < -0.2 && this.multiLevelGroup.children.length === 0) {
      this.ensureMultiLevelSlabs(['L1', 'ground', 'B1', 'B2', 'B3']);
    }

    // Update status ring color by Responder state
    const mat = this.responderStatusRing?.material as THREE.LineBasicMaterial | undefined;
    if (mat) {
      if (payload.state === 'blocked' || payload.state === 'frozen') {
        mat.color.setHex(0xef4444);
      } else if (payload.state === 'arrived') {
        mat.color.setHex(0x10b981);
      } else if (payload.state === 'moving') {
        mat.color.setHex(0x38bdf8);
      } else {
        mat.color.setHex(0xfbbf24);
      }
    }
    if (Array.isArray(payload.carrying)) {
      this.refreshCargoMesh(payload.carrying);
    }
  }

  public updateSimTruth(payload: SimTruthPayload): void {
    if (!payload) return;
    if (payload.scout?.pos) {
      const [sx, sy, sz] = payload.scout.pos;
      this.scoutGroup.position.set(sx, sy, sz);
      if (typeof payload.scout.yaw === 'number') {
        this.scoutGroup.rotation.z = payload.scout.yaw;
      }
    }
    if (payload.responder?.pos) {
      this.hasLiveResponderPose = true;
      const [rx, ry, rz] = payload.responder.pos;
      this.responderGroup.position.set(rx, ry, rz);
      if (typeof payload.responder.yaw === 'number') {
        this.responderGroup.rotation.z = payload.responder.yaw;
      }
    }
  }

  public updateWorldDebris(payload: WorldDebrisPayload): void {
    if (!payload) return;
    if (Array.isArray(payload.events)) {
      for (const ev of payload.events) {
        if (!ev?.id || !Array.isArray(ev.pos)) continue;
        const blockMesh = this.sceneBuildingGroup.getObjectByName(ev.id);
        if (blockMesh) {
          blockMesh.position.set(ev.pos[0], ev.pos[1], ev.pos[2]);
        }
        const existing = this.sceneBlocksMap.get(ev.id);
        if (existing) {
          existing.pos = [...ev.pos] as [number, number, number];
        } else {
          this.sceneBlocksMap.set(ev.id, {
            id: ev.id,
            label: 'rubble',
            pos: [...ev.pos] as [number, number, number],
            size: [0.1, 0.1, 0.08]
          });
        }
      }
    }
    if (Array.isArray(payload.stacks)) {
      this.debrisStacksGroup.clear();
      for (const st of payload.stacks) {
        if (!st.unstable || !Array.isArray(st.min_xy) || !Array.isArray(st.max_xy)) continue;
        const cx = (st.min_xy[0] + st.max_xy[0]) / 2;
        const cy = (st.min_xy[1] + st.max_xy[1]) / 2;
        const sx = Math.max(0.2, st.max_xy[0] - st.min_xy[0]);
        const sy = Math.max(0.2, st.max_xy[1] - st.min_xy[1]);
        const sz = Math.max(0.2, st.top_z || 0.4);
        const box = new THREE.BoxGeometry(sx, sy, sz);
        const wire = new THREE.LineSegments(
          new THREE.EdgesGeometry(box),
          new THREE.LineBasicMaterial({ color: 0xf59e0b, transparent: true, opacity: 0.7 })
        );
        wire.position.set(cx, cy, sz / 2);
        this.debrisStacksGroup.add(wire);
      }
    }
  }

  /** Draw off-hub multi-level descent trajectory (_runner/stage) across L1 -> ground -> B1. */
  public updateRunnerStage(payload: RunnerStagePayload): void {
    if (!payload) return;
    if (Array.isArray(payload.levels) && payload.levels.length > 1) {
      this.ensureMultiLevelSlabs(payload.levels);
    }
    if (Array.isArray(payload.trace) && payload.trace.length >= 2) {
      this.stageTraceGroup.clear();
      const pts = payload.trace.map(p => new THREE.Vector3(p[1], p[2], p[3] + 0.03));
      const curve = new THREE.CatmullRomCurve3(pts, false, 'centripetal');
      const tubeGeom = new THREE.TubeGeometry(curve, Math.min(240, pts.length * 2), 0.028, 8, false);
      const tubeMat = new THREE.MeshStandardMaterial({
        color: 0x10b981,
        emissive: 0x059669,
        emissiveIntensity: 0.7,
        roughness: 0.25
      });
      this.stageTraceGroup.add(new THREE.Mesh(tubeGeom, tubeMat));
    }
    if (Array.isArray(payload.final_pos) && payload.final_pos.length >= 3) {
      const [fx, fy, fz] = payload.final_pos;
      this.scoutGroup.position.set(fx, fy, fz);
    }
  }

  public onDecisionLog(payload: DecisionLogPayload): void {
    if (!payload?.perception) return;
    // Detect supply placement from sim Responder log: "placed <item> at [x, y]"
    const m = /placed\s+([\w_]+)\s+at\s+\[\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\]/i.exec(payload.perception);
    if (m) {
      const item = m[1];
      const x = parseFloat(m[2]);
      const y = parseFloat(m[3]);
      if (Number.isFinite(x) && Number.isFinite(y)) {
        this.spawnSupplyMarker(item, x, y, this.responderGroup.position.z);
      }
    }
  }

  private spawnSupplyMarker(item: string, x: number, y: number, z = 0): void {
    const key = `${item}:${x.toFixed(2)},${y.toFixed(2)}`;
    if (this.placedSupplyKeys.has(key)) return;
    this.placedSupplyKeys.add(key);

    const node = new THREE.Group();
    node.position.set(x, y, z);

    if (this.supplyTemplate) {
      const model = this.supplyTemplate.clone(true);
      model.position.set(0, 0, 0.01);
      node.add(model);
    } else {
      const kitGeom = new THREE.BoxGeometry(0.11, 0.09, 0.06);
      const kitMat = new THREE.MeshStandardMaterial({
        color: 0x10b981,
        emissive: 0x047857,
        emissiveIntensity: 0.5,
        roughness: 0.35
      });
      const kitMesh = new THREE.Mesh(kitGeom, kitMat);
      kitMesh.position.set(0, 0, 0.035);
      node.add(kitMesh);
    }

    const ring = this.makeRingLine(0.12, 0x10b981);
    node.add(ring);

    const label = this.createLabelSprite(`Supply: ${item.replace(/_/g, ' ')}`, '#34d399');
    label.scale.set(0.52, 0.17, 1);
    label.position.set(0, 0, 0.22);
    node.add(label);

    this.suppliesGroup.add(node);
  }

  /**
   * X1: one floor tile per (i, j) for every predicted at_risk or collapsed cell (the worse status wins
   * when several layers name the same column). Stable cells draw nothing.
   */
  private applyHazardOverlay(): void {
    const res = this.cellResolution;
    const worst = new Map<string, { i: number; j: number; status: string }>();
    for (const h of this.hazardsMap.values()) {
      if (h.status !== 'at_risk' && h.status !== 'collapsed') continue;
      const key = `${h.cell[0]},${h.cell[1]}`;
      const prev = worst.get(key);
      if (!prev || (prev.status === 'at_risk' && h.status === 'collapsed')) {
        worst.set(key, { i: h.cell[0], j: h.cell[1], status: h.status });
      }
    }
    const colors = this.hazardOverlay.instanceColor!;
    let n = 0;
    for (const { i, j, status } of worst.values()) {
      if (n >= MAX_CELL_CAPACITY) break;
      this.dummy.position.set((i + 0.5) * res, (j + 0.5) * res, 0.004);
      this.dummy.scale.set(res * 0.92, res * 0.92, 1);
      this.dummy.updateMatrix();
      this.hazardOverlay.setMatrixAt(n, this.dummy.matrix);
      const c = status === 'collapsed' ? COLOR_HAZARD_COLLAPSED : COLOR_HAZARD_AT_RISK;
      colors.setXYZ(n, c.r, c.g, c.b);
      n++;
    }
    this.dummy.scale.set(1, 1, 1);
    this.hazardOverlay.count = n;
    this.hazardOverlay.instanceMatrix.needsUpdate = true;
    colors.needsUpdate = true;
  }

  /** Number of predicted hazard floor tiles drawn (at_risk + collapsed columns). */
  public hazardOverlayCount(): number {
    return this.hazardOverlay.count;
  }

  public updateHazards(hazards: HazardRecord[]): void {
    if (!Array.isArray(hazards)) return;
    // map/hazards is the full list every time (perception/hazards.py message()): replace, never merge,
    // so a cell that is no longer predicted to fail stops being drawn.
    this.hazardsMap.clear();
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

    const sphereGeom = new THREE.SphereGeometry(0.09, 20, 20);
    const torsoGeom = new THREE.CapsuleGeometry(0.075, 0.22, 8, 16);
    const sphereMat = new THREE.MeshStandardMaterial({
      color: 0xec4899,
      emissive: 0x831843,
      emissiveIntensity: 0.65,
      roughness: 0.3
    });
    const suitMat = new THREE.MeshStandardMaterial({
      color: 0xf43f5e,
      emissive: 0x881337,
      emissiveIntensity: 0.45,
      roughness: 0.45
    });

    for (const cas of casualties) {
      if (!cas || !Array.isArray(cas.pos)) continue;
      this.casualtiesMap.set(cas.id, cas);
      const [x, y, z] = cas.pos;

      if (z < -0.2 && this.multiLevelGroup.children.length === 0) {
        this.ensureMultiLevelSlabs(['L1', 'ground', 'B1', 'B2', 'B3']);
      }

      // 3D recumbent survivor figure + beacon
      const head = new THREE.Mesh(sphereGeom, sphereMat);
      head.position.set(x - 0.12, y, z + 0.09);
      this.casualtyGroup.add(head);

      const torso = new THREE.Mesh(torsoGeom, suitMat);
      torso.rotation.z = Math.PI / 2;
      torso.position.set(x + 0.04, y, z + 0.075);
      this.casualtyGroup.add(torso);

      const ringGeom = new THREE.RingGeometry(0.18, 0.25, 32);
      const ringMat = new THREE.MeshBasicMaterial({
        color: 0xf472b6,
        side: THREE.DoubleSide,
        transparent: true,
        opacity: 0.75
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
    if (z < -0.2 && this.multiLevelGroup.children.length === 0) {
      this.ensureMultiLevelSlabs(['L1', 'ground', 'B1', 'B2', 'B3']);
    }
  }

  public updateResponderAction(payload: ResponderActionPayload): void {
    if (!payload) return;
    if (payload.action === 'place_supply' && payload.item) {
      const p = this.responderGroup.position;
      const yaw = this.responderGroup.rotation.z;
      this.spawnSupplyMarker(
        payload.item,
        p.x + Math.cos(yaw) * 0.18,
        p.y + Math.sin(yaw) * 0.18,
        p.z
      );
    }
    // When live/replay responder/pose is streaming, continuous 10 Hz poses drive Responder position.
    // When no responder/pose has been seen (e.g. unit tests / fake mode), place at stopBesideCasualty.
    if (!this.hasLiveResponderPose && payload.route && this.routesMap.has(payload.route)) {
      const route = this.routesMap.get(payload.route)!;
      if (route.cells && route.cells.length > 0) {
        const res = this.cellResolution;
        const points = route.cells.map(c => [(c[0] + 0.5) * res, (c[1] + 0.5) * res] as [number, number]);
        const casualties = [...this.casualtiesMap.values()].map(c => [c.pos[0], c.pos[1]] as [number, number]);
        const [x, y] = stopBesideCasualty(points, casualties);
        this.responderGroup.position.set(x, y, 0);
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
   * L1: Move permission revoked or granted on sensed change
   */
  public onPermitRoute(payload: { route: string; granted: boolean; t: number; reason: string }): void {
    if (!payload) return;
    if (!payload.granted) {
      // Permission revoked: turn active route into warning red alert color
      this.activeRouteGroup.traverse(obj => {
        if (obj instanceof THREE.Mesh && obj.material instanceof THREE.MeshStandardMaterial) {
          obj.material.color.setHex(0xef4444);
          obj.material.emissive.setHex(0xb91c1c);
        }
      });
      this.showAftershockBanner(`⚠️ MOVE PERMISSION REVOKED on ${payload.route}: ${payload.reason}`);
    } else {
      // Permission granted: restore solid blue
      this.activeRouteGroup.traverse(obj => {
        if (obj instanceof THREE.Mesh && obj.material instanceof THREE.MeshStandardMaterial) {
          obj.material.color.setHex(0x2563eb);
          obj.material.emissive.setHex(0x1d4ed8);
        }
      });
      this.showReplanReasonBanner(payload.route, payload.reason || 'move permission granted');
    }
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

    // Fallback map of backup/levels block positions (full dimensions in size)
    const fallbackPositions: Record<string, { pos: [number, number, number]; size: [number, number, number] }> = {
      b7: { pos: [0, 0.97, 0.25], size: [0.08, 0.48, 0.4] },
      b8: { pos: [1.25, -0.32, 0.25], size: [0.08, 0.62, 0.4] },
      b10: { pos: [0.97, -0.5, 0.18], size: [0.38, 0.22, 0.08] },
      b11: { pos: [1.25, 0.45, 0.08], size: [0.12, 0.16, 0.1] },
      x1: { pos: [-0.62, -1.02, 0.09], size: [0.18, 0.18, 0.16] }
    };

    for (const id of blockIds) {
      const sceneBlock = this.sceneBlocksMap.get(id);
      const def = sceneBlock
        ? {
            pos: sceneBlock.pos,
            size: [
              Math.max(0.08, sceneBlock.size[0] * 2),
              Math.max(0.08, sceneBlock.size[1] * 2),
              Math.max(0.08, sceneBlock.size[2] * 2)
            ] as [number, number, number]
          }
        : fallbackPositions[id] || { pos: [0, 1.0, 0.2], size: [0.2, 0.4, 0.3] };

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
   * "Simulate re-plan" button (LIVE-UI): ask the hub's live sim for a real aftershock via
   * POST /inject; world/change, route/verified and the new route/proposed then arrive over the bus.
   * Only in ?fake=1 or when no hub/sim answers does it play the local b7 demo below.
   */
  public simulateAftershockAndReplan(): void {
    if (new URLSearchParams(window.location.search).get('fake') === '1') {
      this.playLocalReplanDemo();
      return;
    }
    fetch('http://localhost:8000/inject', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ kind: 'aftershock' })
    }).then(response => {
      if (response.ok) return;
      if (response.status === 409) { console.warn('[map] an aftershock is already running'); return; }
      throw new Error(`hub /inject answered ${response.status}`);
    }).catch(error => {
      console.warn('[map] no live sim on the hub, playing the local re-plan demo', error);
      this.playLocalReplanDemo();
    });
  }

  /** Local stand-in for the button: a scripted b7 aftershock and re-plan, no hub involved. */
  private playLocalReplanDemo(): void {
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

    // 3. Propose new route after 2.5 seconds avoiding b7
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
        reason: 'avoiding collapsed block b7 (b7 moved) toward casualty c1',
        model: 'local-astar'
      });

      // Move Responder to route
      this.responderGroup.position.set(-0.2, -0.4, 0);
    }, 2500);
  }

  /**
   * Populates the map with the standard AFTERSHOCK collapsed building backup scene
   * (walls b1-b9, doorway, leaning slab b10 at risk, rubble b11-b15).
   * Ensures ?fake=1 immediately displays a coloured map with casualty, hazards and route.
   */
  public loadBackupSceneDemo(): void {
    this.hasLiveResponderPose = false;
    this.mergedCellsMap.clear();
    this.buildSceneBuilding(DEFAULT_BACKUP_BLOCKS, 'backup');
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
        [Math.round(0.0 / res), Math.round(0.8 / res), 0],
        [Math.round(0.6 / res), Math.round(0.95 / res), 0],
        [Math.round(1.95 / res), Math.round(0.98 / res), 0]  // ends at casualty c1
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
