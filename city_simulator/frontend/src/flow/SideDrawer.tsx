import { useState } from 'react';
import './sideDrawer.css';

export interface DrawerItem {
  id: string;
  label: string;
  sublabel?: string;
  // Read on drop via DragEvent.dataTransfer.getData(DRAG_MIME) -- a plain
  // string rather than JSON since that's all dataTransfer needs to carry;
  // each canvas defines its own small "kind:id" encoding for what it means.
  dragPayload: string;
  onAdd: () => void; // click-to-add fallback -- drag isn't the only way in
  // Only the Styles section uses this today (a saved style is a library
  // entry, not just a canvas node, so it needs a way to delete it that
  // doesn't require placing a node first) -- every other section's items
  // (agents/locations/node types) have no library entry of their own to
  // delete independent of a canvas node.
  onDelete?: () => void;
}

export interface DrawerSection {
  id: string;
  label: string;
  items: DrawerItem[];
  emptyLabel?: string;
}

export const DRAG_MIME = 'application/x-city-sim-node';

// The one place nodes get added from, everywhere in the app -- a
// left-docked, collapsible, accordion-sectioned palette. Drag an item
// onto the canvas to drop it where you want; click it to add at a
// default position instead. What sections/items exist is entirely up to
// the caller (CityCanvas's Nodes/Locations/Agents vs. ScratchScreen's
// flatter Nodes-only list), so this component owns no domain knowledge.
export function SideDrawer({ sections }: { sections: DrawerSection[] }) {
  const [collapsed, setCollapsed] = useState(true);
  const [openIds, setOpenIds] = useState<Set<string>>(() => new Set(sections.map((s) => s.id)));

  const toggle = (id: string) =>
    setOpenIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  if (collapsed) {
    return (
      <button className="drawer-expand-tab" onClick={() => setCollapsed(false)} title="Show add-node panel">
        ▶
      </button>
    );
  }

  return (
    <div className="side-drawer">
      <div className="side-drawer-header">
        <span className="side-drawer-title">Add node</span>
        <button className="drawer-close-btn" onClick={() => setCollapsed(true)} title="Hide panel">
          ✕
        </button>
      </div>
      <div className="side-drawer-body">
        {sections.map((section) => {
          const open = openIds.has(section.id);
          return (
            <div className="drawer-section" key={section.id}>
              <button className="drawer-section-header" onClick={() => toggle(section.id)}>
                <span>
                  {open ? '▾' : '▸'} {section.label}
                </span>
                <span className="drawer-section-count">{section.items.length}</span>
              </button>
              {open && (
                <div className="drawer-section-items">
                  {section.items.length === 0 ? (
                    <div className="drawer-empty">{section.emptyLabel ?? 'nothing here'}</div>
                  ) : (
                    section.items.map((item) => (
                      <div
                        key={item.id}
                        className="drawer-item"
                        draggable
                        onDragStart={(e) => {
                          e.dataTransfer.setData(DRAG_MIME, item.dragPayload);
                          e.dataTransfer.effectAllowed = 'move';
                        }}
                        onClick={item.onAdd}
                        title="Drag onto the canvas, or click to add"
                      >
                        <div className="drawer-item-label">{item.label}</div>
                        {item.sublabel && <div className="drawer-item-sublabel">{item.sublabel}</div>}
                        {item.onDelete && (
                          <button
                            className="drawer-item-delete"
                            title="Delete"
                            onClick={(e) => {
                              e.stopPropagation();
                              item.onDelete!();
                            }}
                          >
                            ✕
                          </button>
                        )}
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
