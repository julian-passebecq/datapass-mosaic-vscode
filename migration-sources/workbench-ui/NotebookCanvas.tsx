import ReactGridLayout,{useContainerWidth,verticalCompactor,type Layout} from 'react-grid-layout';
import 'react-grid-layout/css/styles.css';
import 'react-resizable/css/styles.css';
import type {ReactNode} from 'react';
import type {NotebookView} from '../../../packages/notebook-core/src/v2/model.ts';
import type {RootBlock} from './notebook';

/** Extracted from Mosaic V2Workspace: geometry only, no domain or runtime imports. */
export function NotebookCanvas({view,blocks,onLayout,renderBlock}:{view:NotebookView;blocks:RootBlock[];onLayout:(layout:Layout)=>void;renderBlock:(block:RootBlock)=>ReactNode}){
 const {width,containerRef,mounted}=useContainerWidth();
 const byId=new Map(blocks.map(b=>[b.id,b]));
 const visible=view.blockIds.flatMap(id=>byId.has(id)?[byId.get(id)!]:[]);
 const commitLayout=(layout:Layout)=>{if(JSON.stringify(layout)!==JSON.stringify(view.layout))onLayout(layout)};
 return <div className="notebook-canvas" ref={containerRef}>
  {!visible.length&&<div className="empty-state"><h2>This view is empty</h2><p>Add a cell or select a different layout. The notebook has not been deleted.</p></div>}
  {mounted&&(width<600?<div className="narrow-notebook">{visible.map(block=><div key={block.id}>{renderBlock(block)}</div>)}</div>:<ReactGridLayout width={width} layout={view.layout} onDragStop={layout=>commitLayout(layout)} onResizeStop={layout=>commitLayout(layout)} gridConfig={{cols:12,rowHeight:24,margin:[12,12],containerPadding:[16,16]}} dragConfig={{enabled:true,handle:'.block-drag-handle'}} resizeConfig={{enabled:true,handles:['se','s','e']}} compactor={verticalCompactor}>
   {visible.map(block=><div key={block.id}>{renderBlock(block)}</div>)}
  </ReactGridLayout>)}
 </div>;
}
