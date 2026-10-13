import type { FactoryFlavor } from "../contracts";
import { factoryActivityTypesFor, FACTORY_FLAVOR_LABELS, type FactoryActivityCategory } from "../../platform/factoryActivityTypes";
import { GRAPH_DROP_TYPE } from "../SharedGraphCanvas";

/** Category headings of the palette (the products group their activities the same way). */
export const PALETTE_CATEGORIES: Record<FactoryActivityCategory, string> = {
  move: "Move and transform",
  transform: "Transform",
  general: "General",
  control: "Iteration and conditionals",
  notify: "Notifications",
  external: "External"
};
const ORDER: FactoryActivityCategory[] = ["move", "transform", "general", "control", "notify", "external"];

/**
 * Activities the simulator accepts for the product, from runtime/factorylab/activities.py. Click (or Enter) adds one
 * to the level shown; dragging one onto the canvas adds it where it is dropped.
 */
export function Palette({
  flavor,
  disabled,
  onAdd,
  categories = PALETTE_CATEGORIES
}: {
  flavor: FactoryFlavor;
  disabled?: boolean;
  onAdd: (type: string) => void;
  categories?: Record<FactoryActivityCategory, string>;
}) {
  const types = factoryActivityTypesFor(flavor);
  return (
    <nav className="factory-palette" aria-label="Activities">
      <div className="factory-palette-head">
        <strong>Activities</strong>
        <small>{FACTORY_FLAVOR_LABELS[flavor]}: the types the simulator runs. Anything else is refused at run time, never guessed.</small>
      </div>
      {ORDER.map(category => {
        const items = types.filter(type => type.category === category);
        if (!items.length) return null;
        return (
          <div key={category} className="factory-palette-group" role="group" aria-label={categories[category]}>
            <span className="factory-palette-category">{categories[category]}</span>
            {items.map(type => (
              <button
                key={type.name}
                type="button"
                className="factory-palette-item"
                disabled={disabled}
                draggable={!disabled}
                title={`${type.name}${type.required.length ? ` · needs ${type.required.join(", ")}` : ""}`}
                aria-label={`Add ${type.label} (${type.name})`}
                onClick={() => onAdd(type.name)}
                onDragStart={event => {
                  event.dataTransfer.setData(GRAPH_DROP_TYPE, type.name);
                  event.dataTransfer.effectAllowed = "copy";
                }}
              >
                {type.label}
                <small>{type.name}</small>
              </button>
            ))}
          </div>
        );
      })}
    </nav>
  );
}
