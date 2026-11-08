import { on } from './bus';
import type { GridCell, MapCellsPayload } from './map';

/**
 * MAP-DELTA-FIX: perception publishes a full map/cells snapshot every few seconds and only the changed
 * cells (deltas) at 2 Hz in between. Merge them the way planner/route.py update_map does: keyed by cell,
 * unlisted cells keep their last observation, and an explicit "unknown" forgets the cell. A change of
 * grid resolution (or a new scene, via clear()) starts the map again.
 */
export class CellsMerge {
  private cells = new Map<string, GridCell>();
  private res: number | null = null;

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
    return { t: payload.t, res: payload.res, cells: Array.from(this.cells.values()) };
  }

  clear(): void {
    this.cells.clear();
    this.res = null;
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
