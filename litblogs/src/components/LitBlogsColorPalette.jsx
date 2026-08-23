import { useEffect, useId, useRef, useState } from "react";

import "../styles/litblogs-editor.css";

const GRID_COLUMNS = 6;

const normalizeColor = (value) => (
  typeof value === "string" ? value.trim().toLowerCase() : null
);

const LitBlogsColorPalette = ({
  label,
  colors,
  value,
  onChange,
  disabled = false,
}) => {
  const [open, setOpen] = useState(false);
  const [focusedIndex, setFocusedIndex] = useState(0);
  const containerRef = useRef(null);
  const triggerRef = useRef(null);
  const swatchRefs = useRef([]);
  const paletteId = useId();
  const normalizedValue = normalizeColor(value);
  const selectedIndex = colors.findIndex(
    (entry) => normalizeColor(entry.value) === normalizedValue,
  );
  const selectedEntry = selectedIndex >= 0 ? colors[selectedIndex] : null;
  const selectedLabel = selectedEntry?.label
    ?? (normalizedValue ? `Custom ${normalizedValue}` : "Default");

  const closePalette = ({ restoreFocus = true } = {}) => {
    if (restoreFocus) {
      triggerRef.current?.focus();
    }
    setOpen(false);
  };

  const openPalette = () => {
    if (disabled) return;
    setFocusedIndex(selectedIndex >= 0 ? selectedIndex : 0);
    setOpen(true);
  };

  useEffect(() => {
    if (!open) return undefined;

    swatchRefs.current[focusedIndex]?.focus();

    const handlePointerDown = (event) => {
      if (!containerRef.current?.contains(event.target)) {
        closePalette({ restoreFocus: false });
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [focusedIndex, open]);

  const focusSwatch = (index) => {
    const wrappedIndex = (index + colors.length) % colors.length;
    setFocusedIndex(wrappedIndex);
    swatchRefs.current[wrappedIndex]?.focus();
  };

  const handleSwatchKeyDown = (event, index) => {
    let nextIndex = null;

    switch (event.key) {
      case "ArrowRight":
        nextIndex = index + 1;
        break;
      case "ArrowLeft":
        nextIndex = index - 1;
        break;
      case "ArrowDown":
        nextIndex = index + GRID_COLUMNS;
        break;
      case "ArrowUp":
        nextIndex = index - GRID_COLUMNS;
        break;
      case "Home":
        nextIndex = 0;
        break;
      case "End":
        nextIndex = colors.length - 1;
        break;
      case "Escape":
        event.preventDefault();
        closePalette();
        return;
      default:
        return;
    }

    event.preventDefault();
    focusSwatch(nextIndex);
  };

  const chooseColor = (nextValue) => {
    onChange(nextValue);
    closePalette();
  };

  return (
    <div className="litblogs-color-picker" ref={containerRef}>
      <button
        ref={triggerRef}
        type="button"
        className="litblogs-toolbar-button litblogs-color-trigger"
        aria-label={`${label}: ${selectedLabel}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? paletteId : undefined}
        disabled={disabled}
        style={{ "--selected-color": normalizedValue ?? "transparent" }}
        onClick={() => (open ? closePalette({ restoreFocus: false }) : openPalette())}
      >
        <span aria-hidden="true" className="litblogs-color-trigger__letter">A</span>
        <span
          aria-hidden="true"
          className={`litblogs-color-trigger__sample${normalizedValue ? "" : " litblogs-color-trigger__sample--none"}`}
        />
      </button>

      {open && (
        <div
          id={paletteId}
          role="dialog"
          aria-label={`${label} palette`}
          className="litblogs-color-palette"
        >
          <div className="litblogs-color-palette__heading">{label}</div>
          <div className="litblogs-color-palette__grid" role="group" aria-label={`${label} choices`}>
            {colors.map((entry, index) => {
              const entryValue = normalizeColor(entry.value);
              const selected = entryValue === normalizedValue;
              const isNone = entry.value === null;
              const isLight = entryValue === "#ffffff";
              const swatchLabel = isNone
                ? `Clear ${label.toLowerCase().replace(/ color$/, "")}`
                : `${entry.label} ${entryValue}`;

              return (
                <button
                  key={`${entry.label}-${entryValue ?? "none"}`}
                  ref={(element) => {
                    swatchRefs.current[index] = element;
                  }}
                  type="button"
                  className={[
                    "litblogs-color-swatch",
                    isNone ? "litblogs-color-swatch--none" : "",
                    isLight ? "litblogs-color-swatch--light" : "",
                  ].filter(Boolean).join(" ")}
                  aria-label={swatchLabel}
                  aria-pressed={selected}
                  title={swatchLabel}
                  tabIndex={index === focusedIndex ? 0 : -1}
                  style={{ "--swatch-color": entryValue ?? "transparent" }}
                  onClick={() => chooseColor(entry.value)}
                  onFocus={() => setFocusedIndex(index)}
                  onKeyDown={(event) => handleSwatchKeyDown(event, index)}
                >
                  <span aria-hidden="true" className="litblogs-color-swatch__sample" />
                  {selected && <span aria-hidden="true" className="litblogs-color-swatch__check">✓</span>}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};

export default LitBlogsColorPalette;
