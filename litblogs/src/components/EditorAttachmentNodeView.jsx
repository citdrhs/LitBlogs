import { NodeViewWrapper } from "@tiptap/react";

const EditorAttachmentNodeView = ({ deleteNode, editor, node, selected }) => {
  const editable = Boolean(editor?.isEditable);

  return (
    <NodeViewWrapper
      className={`litblogs-media-node file-attachment${selected ? " is-selected" : ""}`}
      data-node-kind="attachment"
      data-file-url={node.attrs.url}
      data-file-name={node.attrs.name}
      data-file-size={node.attrs.size || undefined}
      data-file-type="application/pdf"
    >
      <span className="file-icon" aria-hidden="true">PDF</span>
      <span className="file-info">
        <span className="file-name">{node.attrs.name}</span>
        {node.attrs.size && <span className="file-size">{node.attrs.size}</span>}
      </span>
      {editable && selected && (
        <span className="litblogs-media-node__controls" contentEditable={false}>
          <button type="button" onClick={deleteNode} aria-label="Remove PDF from post">
            Remove PDF
          </button>
        </span>
      )}
    </NodeViewWrapper>
  );
};

export default EditorAttachmentNodeView;
