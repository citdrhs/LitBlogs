import { NodeViewWrapper } from "@tiptap/react";

const EditorVideoNodeView = ({ deleteNode, editor, node, selected }) => {
  const editable = Boolean(editor?.isEditable);
  const videoAttributes = {
    controls: true,
    height: node.attrs.height || undefined,
    preload: "metadata",
    width: node.attrs.width || undefined,
  };

  return (
    <NodeViewWrapper
      as="figure"
      className={`litblogs-media-node video-container${selected ? " is-selected" : ""}`}
      data-node-kind="video"
    >
      {node.attrs.type ? (
        <video {...videoAttributes}>
          <source src={node.attrs.src} type={node.attrs.type} />
        </video>
      ) : (
        <video {...videoAttributes} src={node.attrs.src} />
      )}
      {editable && selected && (
        <div className="litblogs-media-node__controls" contentEditable={false}>
          <button type="button" onClick={deleteNode} aria-label="Remove video from post">
            Remove video
          </button>
        </div>
      )}
    </NodeViewWrapper>
  );
};

export default EditorVideoNodeView;
