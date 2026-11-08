import { on } from './bus';
import type { GridCell, MapCellsPayload } from './map';

/**
 * MAP-DELTA-FIX: perception publishes a full map/cells snapshot every few seconds and only the changed
 * cells (deltas) at 2 Hz in between. Merge them the way planner/route.py update_map does: keyed by cell,
 * unlisted cells keep their last observation, and an explicit "unknown" forgets the cell. A change of
 * grid resolution (or a new scene, via clear()) starts the map again.
 *
 * CELLS-MERGE-FIX: MapViewer.updateCells (map.ts) also merges what it is given into its own map, so a
 * cell simply left out of our output stays drawn there. For every cell it was sent before and that we
 * no longer hold (an explicit unknown, or a resolution change), apply() adds a tombstone
 * {state: 'unknown', occupied: false}, which updateCells deletes and never draws.
 */
export class CellsMerge {
  private cells = new Map<string, GridCell>();
  private res: number | null = null;
  private sent = new Set<string>();   // keys the viewer holds from our last output

  apply(payload: MapCellsPayload): MapCellsPayload {
    if (payload.res !== this.res) {
      this.cells.clear();
      this.res = payload.res;
    }
    for (const record of payload.cells) {
      if (!record || !Array.isArray(record.cell)) continue;
      const key = record.cell.join(',');
      if (record.state === 'unknown') this.cells.delete(key);
      else this.cells.set(key, record);
    }
    const cells = Array.from(this.cells.values());
    for (const key of this.sent) {
      if (this.cells.has(key)) continue;
      const cell = key.split(',').map(Number) as GridCell['cell'];
      cells.push({ cell, state: 'unknown', occupied: false });
    }
    this.sent = new Set(this.cells.keys());
    return { t: payload.t, res: payload.res, cells };
  }

  /** A new scene: the viewer clears its own map on scene/loaded too, so nothing is left to forget. */
  clear(): void {
    this.cells.clear();
    this.res = null;
    this.sent.clear();
  }

  get size(): number {
    return this.cells.size;
  }
}

/** Call `draw` with the merged map on every map/cells message; a scene/loaded starts the map again. */
export function onMergedCells(draw: (payload: MapCellsPayload) => void): CellsMerge {
  const merged = new CellsMerge();
  on('scene/loaded', () => merged.clear());
  on('map/cells', data => {
    const payload = data as MapCellsPayload;
    if (payload && Array.isArray(payload.cells)) draw(merged.apply(payload));
  });
  return merged;
}
