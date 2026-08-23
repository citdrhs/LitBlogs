import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  HIGHLIGHT_COLOR_PALETTE,
  TEXT_COLOR_PALETTE,
} from "../utils/richTextContract";
import LitBlogsColorPalette from "./LitBlogsColorPalette";

describe("LitBlogsColorPalette", () => {
  it("renders a visible, selection-aware foreground palette", () => {
    const onChange = vi.fn();

    render(
      <LitBlogsColorPalette
        label="Text color"
        colors={TEXT_COLOR_PALETTE}
        value="#1d4ed8"
        onChange={onChange}
      />,
    );

    const trigger = screen.getByRole("button", { name: "Text color: Blue" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveStyle({ "--selected-color": "#1d4ed8" });

    fireEvent.click(trigger);

    const palette = screen.getByRole("dialog", { name: "Text color palette" });
    const blue = within(palette).getByRole("button", { name: "Blue #1d4ed8" });
    const white = within(palette).getByRole("button", { name: "White #ffffff" });

    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(blue).toHaveAttribute("aria-pressed", "true");
    expect(blue).toHaveStyle({ "--swatch-color": "#1d4ed8" });
    expect(white).toHaveClass("litblogs-color-swatch--light");

    fireEvent.click(within(palette).getByRole("button", { name: "Red #b91c1c" }));

    expect(onChange).toHaveBeenCalledWith("#b91c1c");
    expect(screen.queryByRole("dialog", { name: "Text color palette" })).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it("makes the clear-highlight choice visible and selectable", () => {
    const onChange = vi.fn();

    const ControlledPalette = () => {
      const [value, setValue] = useState("#fef3c7");
      return (
        <LitBlogsColorPalette
          label="Highlight color"
          colors={HIGHLIGHT_COLOR_PALETTE}
          value={value}
          onChange={(nextValue) => {
            onChange(nextValue);
            setValue(nextValue);
          }}
        />
      );
    };

    render(<ControlledPalette />);

    fireEvent.click(screen.getByRole("button", { name: "Highlight color: Amber" }));
    const clear = screen.getByRole("button", { name: "Clear highlight" });

    expect(clear).toHaveClass("litblogs-color-swatch--none");
    expect(clear).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(clear);

    expect(onChange).toHaveBeenCalledWith(null);
    expect(screen.getByRole("button", { name: "Highlight color: None" })).toHaveFocus();
  });

  it("supports arrow navigation, Home, End, and Escape", () => {
    render(
      <LitBlogsColorPalette
        label="Text color"
        colors={TEXT_COLOR_PALETTE}
        value="#111827"
        onChange={() => {}}
      />,
    );

    const trigger = screen.getByRole("button", { name: "Text color: Ink" });
    fireEvent.click(trigger);

    const ink = screen.getByRole("button", { name: "Ink #111827" });
    const slate = screen.getByRole("button", { name: "Slate #374151" });
    const white = screen.getByRole("button", { name: "White #ffffff" });

    expect(ink).toHaveFocus();
    fireEvent.keyDown(ink, { key: "ArrowRight" });
    expect(slate).toHaveFocus();
    fireEvent.keyDown(slate, { key: "End" });
    expect(white).toHaveFocus();
    fireEvent.keyDown(white, { key: "Home" });
    expect(ink).toHaveFocus();
    fireEvent.keyDown(ink, { key: "ArrowLeft" });
    expect(white).toHaveFocus();
    fireEvent.keyDown(white, { key: "Escape" });

    expect(screen.queryByRole("dialog", { name: "Text color palette" })).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it("contains palette Escape so an outer composer stays open", () => {
    const onOuterKeyDown = vi.fn();
    render(
      <div onKeyDown={onOuterKeyDown}>
        <LitBlogsColorPalette
          label="Text color"
          colors={TEXT_COLOR_PALETTE}
          value="#111827"
          onChange={() => {}}
        />
      </div>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Text color: Ink" }));
    fireEvent.keyDown(screen.getByRole("button", { name: "Ink #111827" }), {
      key: "Escape",
    });

    expect(screen.queryByRole("dialog", { name: "Text color palette" })).not.toBeInTheDocument();
    expect(onOuterKeyDown).not.toHaveBeenCalled();
  });

  it("closes without stealing focus when keyboard focus leaves the palette", () => {
    render(
      <>
        <LitBlogsColorPalette
          label="Text color"
          colors={TEXT_COLOR_PALETTE}
          value="#111827"
          onChange={() => {}}
        />
        <button type="button">Next control</button>
      </>,
    );

    const trigger = screen.getByRole("button", { name: "Text color: Ink" });
    fireEvent.click(trigger);
    const swatch = screen.getByRole("button", { name: "Ink #111827" });
    const nextControl = screen.getByRole("button", { name: "Next control" });

    fireEvent.blur(swatch, { relatedTarget: nextControl });
    nextControl.focus();

    expect(screen.queryByRole("dialog", { name: "Text color palette" })).not.toBeInTheDocument();
    expect(nextControl).toHaveFocus();
  });

  it("does not open or emit changes while disabled", () => {
    const onChange = vi.fn();

    render(
      <LitBlogsColorPalette
        label="Text color"
        colors={TEXT_COLOR_PALETTE}
        value={null}
        onChange={onChange}
        disabled
      />,
    );

    const trigger = screen.getByRole("button", { name: "Text color: Default" });
    expect(trigger).toBeDisabled();
    fireEvent.click(trigger);

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("shows a legacy safe custom color without pretending it is the default", () => {
    render(
      <LitBlogsColorPalette
        label="Text color"
        colors={TEXT_COLOR_PALETTE}
        value="rgb(18, 52, 86)"
        onChange={() => {}}
      />,
    );

    const trigger = screen.getByRole("button", {
      name: "Text color: Custom rgb(18, 52, 86)",
    });
    expect(trigger).toHaveStyle({ "--selected-color": "rgb(18, 52, 86)" });
  });
});
