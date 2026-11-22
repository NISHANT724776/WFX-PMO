export type SettingDef = { key: string; label: string; kind: "select" | "multiselect" | "product" | "location" | "number" | "text" | "longtext"; options: { value: string; label: string }[]; default: unknown; min: number | null; max: number | null };
export type WidgetType = { type: string; title: string; description: string; shape: string; default_size: { w: number; h: number }; min_size: { w: number; h: number }; sources: string[]; settings: SettingDef[] };
export type PlacedWidget = { id: string; type: string; x: number; y: number; w: number; h: number; config: Record<string, unknown> };
export type LayoutConfig = { version: number; filters: { product_id?: string; location_id?: string }; widgets: PlacedWidget[] };
export type LayoutSummary = { id: string; scope: "template" | "personal" | "project" | "management"; name: string; description?: string; project_id: string | null; version: number; widgets: number; updated_at: string | null; updated_by: string | null; can_edit: boolean };
export type Layout = LayoutSummary & { config: LayoutConfig };

export const COLS = 12;
export const ROW_H = 44;
export const GAP = 8;
export const SCOPE_LABEL: Record<string, string> = { template: "Default template", personal: "Personal", project: "Project (shared with the project)", management: "Management (organisation-wide)" };

const hit = (a: PlacedWidget, b: PlacedWidget) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

/** Lays widgets out without overlaps. The pinned widget (the one being dragged) keeps its spot; the others settle around it, moving up as far as they can. */
export function settle(widgets: PlacedWidget[], pinnedId?: string): PlacedWidget[] {
  const placed: PlacedWidget[] = [];
  const pinned = widgets.find((w) => w.id === pinnedId);
  if (pinned) placed.push({ ...pinned });
  [...widgets].filter((w) => w.id !== pinnedId).sort((a, b) => a.y - b.y || a.x - b.x).forEach((w) => {
    const c = { ...w, y: 0 };
    while (placed.some((p) => hit(c, p))) c.y += 1;
    placed.push(c);
  });
  return widgets.map((w) => placed.find((p) => p.id === w.id)!);
}

/** Where a new widget goes: the first free spot, scanning rows from the top. */
export function firstFree(widgets: PlacedWidget[], w: number, h: number): { x: number; y: number } {
  for (let y = 0; y < 400; y++) for (let x = 0; x + w <= COLS; x++) if (!widgets.some((p) => hit({ id: "", type: "", x, y, w, h, config: {} }, p))) return { x, y };
  return { x: 0, y: 0 };
}

export const newId = (widgets: PlacedWidget[]): string => {
  let n = widgets.length + 1;
  while (widgets.some((w) => w.id === `w${n}`)) n++;
  return `w${n}`;
};

/** Drops settings left empty, so a saved layout only carries real choices. */
export const cleanConfig = (c: Record<string, unknown>): Record<string, unknown> => Object.fromEntries(Object.entries(c).filter(([, v]) => v !== "" && v !== null && v !== undefined && !(Array.isArray(v) && v.length === 0)));
