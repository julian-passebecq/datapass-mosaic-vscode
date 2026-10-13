import { Badge } from "@fluentui/react-components";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  applyNodeChanges,
  useReactFlow,
  type Connection,
  type Edge,
  type Node,
  type NodeChange,
  type NodeProps,
  type Viewport
} from "@xyflow/react";
import { useEffect, useMemo, useState, type DragEvent } from "react";
import "@xyflow/react/dist/style.css";
import type { GraphView } from "./contracts";
import type { VsCodeApi } from "./WorkbenchApp";

interface StoredGraphView {
  positions: Record<string, { x: number; y: number }>;
  viewport?: Viewport;
}

interface PersistedWebviewState {
  graphViews?: Record<string, StoredGraphView>;
}

interface Props {
  graph: GraphView;
  vscode: VsCodeApi;
  storageKey: string;
  /** Called with the node id when a node is clicked (Factory Lab opens its details). */
  onNodeClick?: (id: string) => void;
  // Editing (Cloud Lab › Pipelines). All optional: without them the canvas is read-only, as on the other surfaces.
  /** Handles connect, Delete removes the selection, and keyboard selection reaches onNodeClick. */
  editable?: boolean;
  /** A connection dragged from a node's right handle to another node's left handle. */
  onConnect?: (source: string, target: string) => void;
  /** Delete pressed on selected nodes; the canvas removes nothing itself (the graph prop is the truth). */
  onDeleteNodes?: (ids: string[]) => void;
  /** Delete pressed on selected edges. */
  onDeleteEdges?: (ids: string[]) => void;
  onEdgeClick?: (id: string) => void;
  /** Something was dropped on the canvas (dataTransfer type DROP_TYPE); return the new node's id to place it there. */
  onDrop?: (data: string, position: { x: number; y: number }) => string | undefined;
  /** A node was dragged to a new position (the position is kept in the webview state only). */
  onMove?: (id: string, position: { x: number; y: number }) => void;
  /** Node and edge to show as selected (selection then follows these props). */
  selectedNodeId?: string;
  selectedEdgeId?: string;
}

/** dataTransfer type the canvas accepts in onDrop. */
export const GRAPH_DROP_TYPE = "application/x-datapass-graph-item";

const SIDES = [["top", Position.Top], ["right", Position.Right], ["bottom", Position.Bottom], ["left", Position.Left]] as const;

function DatapassGraphNode({ data, selected }: NodeProps) {
  return (
    <div className={`datapass-graph-node ${selected ? "is-selected" : ""}${data.status ? ` state-${String(data.status)}` : ""}`}>
      <Handle type="target" position={Position.Left} />
      <Badge size="small" appearance="outline">{String(data.truth ?? "Design")}</Badge>
      <strong>{String(data.label ?? "")}</strong>
      <small>{String(data.detail ?? "")}</small>
      <Handle type="source" position={Position.Right} />
      {data.allSides ? SIDES.map(([side, position]) => [
        <Handle key={`s-${side}`} id={`s-${side}`} type="source" position={position} className="datapass-side-handle" />,
        <Handle key={`t-${side}`} id={`t-${side}`} type="target" position={position} className="datapass-side-handle" />
      ]) : null}
    </div>
  );
}

const nodeTypes = { datapass: DatapassGraphNode };

function InnerGraph({
  graph, vscode, storageKey, onNodeClick, editable, onConnect, onDeleteNodes, onDeleteEdges, onEdgeClick, onDrop, onMove,
  selectedNodeId, selectedEdgeId
}: Props) {
  const flow = useReactFlow();
  // Read persisted view state once per graph surface. Recreating it on every render
  // produced new dependencies each time and an endless setNodes/render loop.
  const stored = useMemo(() => readGraphView(vscode, storageKey), [vscode, storageKey]);
  // Host state messages arrive as fresh objects; key on content so unrelated
  // refreshes (runtime status, catalog) neither loop nor reset dragged nodes.
  const graphKey = JSON.stringify(graph);
  const mapped = useMemo<Node[]>(() => {
    const positions = readGraphView(vscode, storageKey).positions;
    const layered = layeredPositions(graph);
    return graph.nodes.map(node => ({
      id: node.id,
      type: "datapass",
      position: positions[node.id] ?? node.position ?? layered[node.id],
      data: { ...node }
    }));
  }, [graphKey, storageKey]);
  const [nodes, setNodes] = useState<Node[]>(mapped);

  useEffect(() => setNodes(mapped), [mapped]);

  const edges = useMemo(
    () => graph.edges.map(({ sourceSide, targetSide, ...edge }) => ({
      ...edge,
      sourceHandle: sourceSide ? `s-${sourceSide}` : undefined,
      targetHandle: targetSide ? `t-${targetSide}` : undefined,
      type: sourceSide || targetSide ? "straight" : "smoothstep",
      markerEnd: { type: MarkerType.ArrowClosed }
    })),
    [graphKey]
  );

  // Selection follows selectedNodeId / selectedEdgeId when the surface passes them; otherwise React Flow keeps its own.
  const controlled = selectedNodeId !== undefined;
  const onNodesChange = (changes: NodeChange[]) => {
    if (controlled) {
      // Enter or Space on a focused node selects it: keyboard users reach the same details as a click.
      const picked = changes.filter(change => change.type === "select" && change.selected);
      if (editable && onNodeClick && picked.length === 1 && "id" in picked[0] && picked[0].id !== selectedNodeId) onNodeClick(picked[0].id);
      changes = changes.filter(change => change.type !== "select");
      if (!changes.length) return;
    }
    setNodes(current => applyNodeChanges(changes, current));
  };

  const shownNodes = useMemo(
    () => controlled
      ? nodes.map(node => !!node.selected === (node.id === selectedNodeId) ? node : { ...node, selected: node.id === selectedNodeId })
      : nodes,
    [nodes, controlled, selectedNodeId]
  );
  const shownEdges: Edge[] = useMemo(
    () => selectedEdgeId === undefined ? edges : edges.map(edge => ({ ...edge, selected: edge.id === selectedEdgeId })),
    [edges, selectedEdgeId]
  );

  const dropProps = onDrop
    ? {
      onDragOver: (event: DragEvent) => {
        if (event.dataTransfer.types.includes(GRAPH_DROP_TYPE)) {
          event.preventDefault();
          event.dataTransfer.dropEffect = "copy";
        }
      },
      onDrop: (event: DragEvent) => {
        const data = event.dataTransfer.getData(GRAPH_DROP_TYPE);
        if (!data) return;
        event.preventDefault();
        const position = flow.screenToFlowPosition({ x: event.clientX, y: event.clientY });
        const rounded = { x: Math.round(position.x / 10) * 10, y: Math.round(position.y / 10) * 10 };
        const id = onDrop(data, rounded);
        if (id) save({ positions: { ...readGraphView(vscode, storageKey).positions, [id]: rounded } });
      }
    }
    : {};

  const save = (patch: Partial<StoredGraphView>) => {
    const currentState = readState(vscode);
    const current = currentState.graphViews?.[storageKey] ?? { positions: {} };
    vscode.setState({
      ...currentState,
      graphViews: {
        ...(currentState.graphViews ?? {}),
        [storageKey]: { ...current, ...patch }
      }
    });
  };

  return (
    <div className="datapass-graph-host">
      <ReactFlow
        nodes={shownNodes}
        edges={shownEdges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onNodeClick={onNodeClick ? (_, node) => onNodeClick(node.id) : undefined}
        onEdgeClick={onEdgeClick ? (_, edge) => onEdgeClick(edge.id) : undefined}
        onConnect={onConnect ? (connection: Connection) => {
          if (connection.source && connection.target) onConnect(connection.source, connection.target);
        } : undefined}
        onBeforeDelete={editable ? async ({ nodes: removed, edges: cut }) => {
          if (removed.length && onDeleteNodes) onDeleteNodes(removed.map(node => node.id));
          else if (cut.length && onDeleteEdges) onDeleteEdges(cut.map(edge => edge.id));
          return false;
        } : undefined}
        onNodeDragStop={(_, node) => {
          const view = readGraphView(vscode, storageKey);
          const position = { x: Math.round(node.position.x), y: Math.round(node.position.y) };
          save({ positions: { ...view.positions, [node.id]: position } });
          onMove?.(node.id, position);
        }}
        onMoveEnd={(event, viewport) => {
          if (event) save({ viewport });
        }}
        defaultViewport={stored.viewport}
        fitView={!stored.viewport}
        fitViewOptions={{ padding: 0.2, maxZoom: 1.1 }}
        nodesConnectable={!!editable && !!onConnect}
        deleteKeyCode={editable ? ["Delete", "Backspace"] : null}
        {...dropProps}
        minZoom={0.2}
        maxZoom={3}
        snapToGrid
        snapGrid={[10, 10]}
      >
        <Background gap={20} />
        <Controls showInteractive={false} />
        <MiniMap zoomable pannable />
      </ReactFlow>
      {graph.nodes.length === 0 && (
        <div className="datapass-graph-empty">No validated graph is available yet.</div>
      )}
    </div>
  );
}

export function SharedGraphCanvas(props: Props) {
  return (
    <ReactFlowProvider>
      <InnerGraph {...props} />
    </ReactFlowProvider>
  );
}

/** Default layout: one column per dependency depth (longest path from a source), left to right. */
function layeredPositions(graph: GraphView): Record<string, { x: number; y: number }> {
  const ids = new Set(graph.nodes.map(node => node.id));
  const parents = new Map<string, string[]>(graph.nodes.map(node => [node.id, []]));
  for (const edge of graph.edges) {
    if (ids.has(edge.source) && ids.has(edge.target)) parents.get(edge.target)!.push(edge.source);
  }
  const depth = new Map<string, number>();
  const visiting = new Set<string>();
  const depthOf = (id: string): number => {
    const known = depth.get(id);
    if (known !== undefined) return known;
    if (visiting.has(id)) return 0; // a cycle never reaches here for valid graphs; stay finite anyway
    visiting.add(id);
    const value = Math.max(-1, ...parents.get(id)!.map(depthOf)) + 1;
    visiting.delete(id);
    depth.set(id, value);
    return value;
  };
  const rows = new Map<number, number>();
  const positions: Record<string, { x: number; y: number }> = {};
  for (const node of graph.nodes) {
    const column = depthOf(node.id);
    const row = rows.get(column) ?? 0;
    rows.set(column, row + 1);
    positions[node.id] = { x: column * 260, y: row * 120 };
  }
  return positions;
}

function readState(vscode: VsCodeApi): PersistedWebviewState {
  const value = vscode.getState();
  return value && typeof value === "object"
    ? value as PersistedWebviewState
    : {};
}

function readGraphView(vscode: VsCodeApi, storageKey: string): StoredGraphView {
  return readState(vscode).graphViews?.[storageKey] ?? { positions: {} };
}
