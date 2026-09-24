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
}

function DatapassGraphNode({ data, selected }: NodeProps) {
  return (
    <div className={`datapass-graph-node ${selected ? "is-selected" : ""}`}>
      <Handle type="target" position={Position.Left} />
      <Badge size="small" appearance="outline">{String(data.truth ?? "Design")}</Badge>
      <strong>{String(data.label ?? "")}</strong>
      <small>{String(data.detail ?? "")}</small>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

const nodeTypes = { datapass: DatapassGraphNode };

function InnerGraph({ graph, vscode, storageKey }: Props) {
  // Read persisted view state once per graph surface. Recreating it on every render
  // produced new dependencies each time and an endless setNodes/render loop.
  const stored = useMemo(() => readGraphView(vscode, storageKey), [vscode, storageKey]);
  // Host state messages arrive as fresh objects; key on content so unrelated
  // refreshes (runtime status, catalog) neither loop nor reset dragged nodes.
  const graphKey = JSON.stringify(graph);
  const mapped = useMemo<Node[]>(() => {
    const positions = readGraphView(vscode, storageKey).positions;
    return graph.nodes.map((node, index) => ({
      id: node.id,
      type: "datapass",
      position: positions[node.id] ?? {
        x: (index % 3) * 270,
        y: Math.floor(index / 3) * 150
      },
      data: { ...node }
    }));
  }, [graphKey, storageKey]);
  const [nodes, setNodes] = useState<Node[]>(mapped);

  useEffect(() => setNodes(mapped), [mapped]);

  const edges = useMemo(
    () => graph.edges.map(edge => ({
      ...edge,
      type: "smoothstep",
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

function readState(vscode: VsCodeApi): PersistedWebviewState {
  const value = vscode.getState();
  return value && typeof value === "object"
    ? value as PersistedWebviewState
    : {};
}

function readGraphView(vscode: VsCodeApi, storageKey: string): StoredGraphView {
  return readState(vscode).graphViews?.[storageKey] ?? { positions: {} };
}
