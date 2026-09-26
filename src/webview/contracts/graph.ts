export interface GraphNodeView {
  id: string;
  label: string;
  detail: string;
  truth?: string;
  /** Optional state used to color the node (Airflow task states). */
  status?: string;
  /** Initial position when the graph has its own layout (the BI Lab star); dragged positions still win. */
  position?: { x: number; y: number };
  /** Connection points on all four sides, for layouts that are not left to right (edges then name their sides). */
  allSides?: boolean;
}

export type GraphSide = "top" | "right" | "bottom" | "left";

export interface GraphEdgeView {
  id: string;
  source: string;
  target: string;
  label: string;
  /** Optional CSS class (Factory Lab colors dependency conditions). */
  className?: string;
  /** Sides the edge leaves and enters by, between nodes with allSides (default: right to left). */
  sourceSide?: GraphSide;
  targetSide?: GraphSide;
}

export interface GraphView {
  nodes: readonly GraphNodeView[];
  edges: readonly GraphEdgeView[];
}
