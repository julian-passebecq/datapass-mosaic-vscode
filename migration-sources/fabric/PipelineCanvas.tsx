import type { ActivityType, PipelineEdge, PipelineNode } from '../types/app';
import { activityLabels } from '../lib/pipeline';
import { LearningGraph } from '../graph-engine/LearningGraph';
import { PIPELINE_ACTIVITY_MIME } from './ActivityPalette';

export function PipelineCanvas({ nodes, edges, selectedId, selectedEdgeId, onSelect, onEdgeSelect, onMove, onConnect, onDeleteNodes, onDeleteEdges, onDropAdd, onNodeContextMenu }: {
  nodes: PipelineNode[];
  edges: PipelineEdge[];
  selectedId: string | null;
  selectedEdgeId: string | null;
  onSelect: (id: string | null) => void;
  onEdgeSelect: (id: string | null) => void;
  onMove: (id: string, x: number, y: number) => void;
  onConnect: (from: string, to: string) => void;
  onDeleteNodes: (ids: string[]) => void;
  onDeleteEdges: (ids: string[]) => void;
  onDropAdd: (type: ActivityType, x: number, y: number) => void;
  onNodeContextMenu: (id: string, x: number, y: number) => void;
}) {
  return (
    <div className="pipeline-canvas xyflow-pipeline-canvas">
      <LearningGraph
        nodes={nodes.map((node) => ({
          id: node.id,
          x: node.x,
          y: node.y,
          title: node.name,
          subtitle: activityLabels[node.type],
          kind: node.type,
          iconName: node.type,
          status: node.status,
          detail: node.type === 'copy' && node.config.destination ? String(node.config.destination) : undefined,
        }))}
        edges={edges.map((edge) => ({ id: edge.id, source: edge.from, target: edge.to, condition: edge.condition, label: edge.condition }))}
        selectedId={selectedId}
        selectedEdgeId={selectedEdgeId}
        onSelect={onSelect}
        onEdgeSelect={onEdgeSelect}
        onMove={onMove}
        onConnect={onConnect}
        onDeleteNodes={onDeleteNodes}
        onDeleteEdges={onDeleteEdges}
        onNodeContextMenu={onNodeContextMenu}
        dropMime={PIPELINE_ACTIVITY_MIME}
        onDropPayload={(payload, x, y) => onDropAdd(payload as ActivityType, x, y)}
        emptyTitle="Add an activity to start"
        emptySubtitle="Drag an activity from the left pane. Connect activities from the output handle on the right to the input handle on the left."
      />
    </div>
  );
}
