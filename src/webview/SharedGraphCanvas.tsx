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
  type Node,
  type NodeChange,
  type NodeProps,
  type Viewport
} from "@xyflow/react";
import { useEffect, useMemo, useState } from "react";
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
}

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

function InnerGraph({ graph, vscode, storageKey, onNodeClick }: Props) {
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

  const onNodesChange = (changes: NodeChange[]) => {
    setNodes(current => applyNodeChanges(changes, current));
  };

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
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onNodeClick={onNodeClick ? (_, node) => onNodeClick(node.id) : undefined}
        onNodeDragStop={(_, node) => {
          const view = readGraphView(vscode, storageKey);
          save({
            positions: {
              ...view.positions,
              [node.id]: {
                x: Math.round(node.position.x),
                y: Math.round(node.position.y)
              }
            }
          });
        }}
        onMoveEnd={(event, viewport) => {
          if (event) save({ viewport });
        }}
        defaultViewport={stored.viewport}
        fitView={!stored.viewport}
        fitViewOptions={{ padding: 0.2, maxZoom: 1.1 }}
        nodesConnectable={false}
        deleteKeyCode={null}
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
