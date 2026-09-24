/** Graph mechanics extracted/adapted from migration-sources/fabric/src/graph-engine/LearningGraph.tsx.
 * Owns no semantics or data. Workflow, Lineage and DataModel supply display projections.
 */
import {useEffect,useMemo,useState} from 'react';
import {Background,Controls,Handle,MarkerType,MiniMap,Position,ReactFlow,ReactFlowProvider,applyNodeChanges,type Node,type NodeProps,type NodeChange} from '@xyflow/react';
import {Badge} from '@fluentui/react-components';
import '@xyflow/react/dist/style.css';
import type {GraphProjection,ViewInstance} from '../../../../packages/contracts/src/foundation.ts';

function GraphNode({data,selected}:NodeProps){return <div className={`foundation-graph-node ${selected?'is-selected':''}`}><Handle type="target" position={Position.Left}/><Badge size="small" appearance="outline">{String(data.truth??'Design')}</Badge><strong>{String(data.label)}</strong><small>{String(data.detail)}</small><Handle type="source" position={Position.Right}/></div>}
const nodeTypes={foundation:GraphNode};
interface Props {graph:GraphProjection;view:ViewInstance;disabled:boolean;connectable?:boolean;onView:(patch:Partial<ViewInstance>)=>void;onConnect:(source:string,target:string)=>void}
function Inner({graph,view,disabled,connectable=true,onView,onConnect}:Props){
 const mapped=useMemo<Node[]>(()=>graph.nodes.map((n,i)=>({id:n.id,type:'foundation',position:view.positions[n.id]??{x:(i%3)*280,y:Math.floor(i/3)*160},selected:view.selected_node===n.id,data:{...n}})),[graph,view.positions,view.selected_node]);
 const [nodes,setNodes]=useState<Node[]>(mapped);
 useEffect(()=>setNodes(mapped),[mapped]);
 const edges=useMemo(()=>graph.edges.map(e=>({...e,type:'smoothstep',selected:view.selected_edge===e.id,markerEnd:{type:MarkerType.ArrowClosed}})),[graph,view.selected_edge]);
 const changes=(value:NodeChange[])=>setNodes(current=>applyNodeChanges(value,current));
 return <div className="foundation-graph-host" data-testid="foundation-graph">
  <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={changes}
   onNodeClick={(_,n)=>{if(!disabled)onView({selected_node:n.id,selected_edge:null})}} onEdgeClick={(_,e)=>{if(!disabled)onView({selected_edge:e.id,selected_node:null})}}
   onPaneClick={()=>{if(!disabled)onView({selected_node:null,selected_edge:null})}}
   onNodeDragStop={(_,node)=>{if(!disabled)onView({positions:{...view.positions,[node.id]:{x:Math.round(node.position.x),y:Math.round(node.position.y)}}})}}
   onConnect={c=>{if(!disabled&&connectable&&c.source&&c.target)onConnect(c.source,c.target)}}
   onMoveEnd={(event,viewport)=>{if(!disabled&&event)onView({viewport})}}
   defaultViewport={view.viewport??undefined} fitView={!view.viewport} fitViewOptions={{padding:0.2,maxZoom:1.1}}
   nodesDraggable={!disabled} nodesConnectable={!disabled&&connectable} elementsSelectable={!disabled} deleteKeyCode={null}
   minZoom={0.2} maxZoom={3} snapToGrid snapGrid={[10,10]}>
   <Background gap={20}/><Controls showInteractive={false}/><MiniMap zoomable pannable/>
  </ReactFlow>
  {!graph.nodes.length&&<p className="foundation-graph-empty">Add a node from the toolbar to start a design.</p>}
 </div>;
}
export function GraphCanvas(props:Props){return <ReactFlowProvider><Inner {...props}/></ReactFlowProvider>}
