import { NodeViewWrapper } from "@tiptap/react";

const WIDTH_OPTIONS = ["", "25%", "50%", "75%", "100%"];
const ALIGNMENT_CLASSES = {
  center: "img-fluid mx-auto d-block",
  left: "img-fluid float-left",
  none: "img-fluid",
  right: "img-fluid float-right",
};

const currentAlignment = (className = "") => {
  const classes = new Set(String(className).split(/\s+/));
  if (classes.has("float-left") || classes.has("alignleft")) return "left";
  if (classes.has("float-right") || classes.has("alignright")) return "right";
  if (classes.has("mx-auto") || classes.has("aligncenter")) return "center";
  return "none";
};

const preventImplicitSubmit = (event) => {
  if (
    event.key === "Enter"
    && !event.isComposing
    && !event.nativeEvent?.isComposing
  ) {
    event.preventDefault();
  }
};

const pixelDimension = (value) => {
  const match = String(value ?? "").match(/^(\d+(?:\.\d+)?)(?:px)?$/i);
  return match ? Number(match[1]) : "";
};

const updatePixelDimension = (updateAttributes, name, rawValue) => {
  if (rawValue === "") {
    updateAttributes({ [name]: null });
    return;
  }
  if (!/^\d{1,4}$/.test(rawValue)) return;
  const amount = Number(rawValue);
  if (amount >= 1 && amount <= 4096) updateAttributes({ [name]: String(amount) });
};

const EditorImageNodeView = ({
  deleteNode,
  editor,
  node,
  selected,
  updateAttributes,
}) => {
  const editable = Boolean(editor?.isEditable);
  const alignment = currentAlignment(node.attrs.class);
  const widthPreset = WIDTH_OPTIONS.includes(node.attrs.width || "")
    ? node.attrs.width || ""
    : "custom";

  return (
    <NodeViewWrapper
      as="figure"
      className={`litblogs-media-node litblogs-media-node--image${selected ? " is-selected" : ""}`}
      data-node-kind="image"
    >
      <img
        src={node.attrs.src}
        alt={node.attrs.alt || ""}
        title={node.attrs.title || undefined}
        width={node.attrs.width || undefined}
        height={node.attrs.height || undefined}
        className={node.attrs.class || undefined}
        draggable="false"
      />
      {editable && selected && (
        <div className="litblogs-media-node__controls" contentEditable={false}>
          <label>
            <span>Image description</span>
            <input
              type="text"
              maxLength={512}
              value={node.attrs.alt || ""}
              onChange={(event) => updateAttributes({ alt: event.target.value })}
              onKeyDown={preventImplicitSubmit}
            />
          </label>
          <label>
            <span>Image width</span>
            <select
              aria-label="Image width"
              value={widthPreset}
              onChange={(event) => updateAttributes({
                height: null,
                width: event.target.value === "custom" ? node.attrs.width : event.target.value || null,
              })}
            >
              {WIDTH_OPTIONS.map((width) => (
                <option key={width || "original"} value={width}>
                  {width || "Original width"}
                </option>
              ))}
              <option value="custom" disabled>Custom dimensions</option>
            </select>
          </label>
          <label>
            <span>Custom width (px)</span>
            <input
              aria-label="Custom image width (pixels)"
              type="number"
              min="1"
              max="4096"
              value={pixelDimension(node.attrs.width)}
              onChange={(event) => updatePixelDimension(
                updateAttributes,
                "width",
                event.target.value,
              )}
              onKeyDown={preventImplicitSubmit}
            />
          </label>
          <label>
            <span>Custom height (px)</span>
            <input
              aria-label="Custom image height (pixels)"
              type="number"
              min="1"
              max="4096"
              value={pixelDimension(node.attrs.height)}
              onChange={(event) => updatePixelDimension(
                updateAttributes,
                "height",
                event.target.value,
              )}
              onKeyDown={preventImplicitSubmit}
            />
          </label>
          <div className="litblogs-media-node__alignment" role="group" aria-label="Image alignment">
            {[
              ["none", "No image alignment"],
              ["left", "Align image left"],
              ["center", "Center image"],
              ["right", "Align image right"],
            ].map(([value, label]) => (
              <button
                key={value}
                type="button"
                aria-label={label}
                aria-pressed={alignment === value}
                onClick={() => updateAttributes({ class: ALIGNMENT_CLASSES[value] })}
              >
                {value === "none" ? "None" : value}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => updateAttributes({ height: null, width: null })}
            aria-label="Reset image dimensions"
          >
            Reset size
          </button>
          <button type="button" onClick={deleteNode} aria-label="Remove image from post">
            Remove image
          </button>
        </div>
      )}
    </NodeViewWrapper>
  );
};

export default EditorImageNodeView;
