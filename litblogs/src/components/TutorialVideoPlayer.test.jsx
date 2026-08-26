import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cwd } from "node:process";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import TutorialVideoPlayer from "./TutorialVideoPlayer.jsx";
import { studentTutorialTranscript } from "./tutorialTranscript.js";

const tutorialPlayerStyles = readFileSync(
  resolve(cwd(), "src/styles/tutorial-video-player.css"),
  "utf8",
);

const PLAYER_PROPS = {
  videoSrc: "/tutorial.mp4",
  posterSrc: "/tutorial.jpg",
  captionsSrc: "/tutorial.en.vtt",
  transcriptSrc: "/tutorial.txt",
  transcript: studentTutorialTranscript,
};

const renderPlayer = () => render(<TutorialVideoPlayer {...PLAYER_PROPS} />);

describe("TutorialVideoPlayer controls", () => {
  let playMock;
  let pauseMock;
  let styleElement;

  beforeAll(() => {
    styleElement = document.createElement("style");
    styleElement.textContent = tutorialPlayerStyles;
    document.head.append(styleElement);
  });

  beforeEach(() => {
    playMock = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    pauseMock = vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  });

  afterEach(() => {
    document.documentElement.classList.remove("dark");
    vi.restoreAllMocks();
  });

  afterAll(() => {
    styleElement.remove();
  });

  it("keeps Space and K scoped to the focused player and ignores editable or control targets", () => {
    renderPlayer();

    const player = screen.getByRole("region", { name: /Keyboard shortcuts/ });
    const playButton = screen.getByRole("button", { name: "Play" });
    const seekControl = screen.getByRole("slider", { name: "Seek video" });
    const speedControl = screen.getByRole("combobox", { name: "Playback speed" });
    const textarea = document.createElement("textarea");
    const contentEditable = document.createElement("div");
    contentEditable.setAttribute("contenteditable", "true");
    player.append(textarea, contentEditable);

    fireEvent.keyDown(document.body, { key: "k" });
    expect(playMock).not.toHaveBeenCalled();

    player.focus();
    expect(player).toHaveFocus();
    fireEvent.keyDown(player, { key: "k" });
    expect(playMock).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(player, { key: " " });
    expect(playMock).toHaveBeenCalledTimes(2);

    fireEvent.keyDown(playButton, { key: "k" });
    fireEvent.keyDown(seekControl, { key: " " });
    fireEvent.keyDown(speedControl, { key: " " });
    fireEvent.keyDown(textarea, { key: " " });
    fireEvent.keyDown(contentEditable, { key: " " });
    expect(playMock).toHaveBeenCalledTimes(2);

    const summary = screen.getByText("Read tutorial transcript");
    expect(fireEvent.keyDown(summary, { key: " " })).toBe(true);
    expect(playMock).toHaveBeenCalledTimes(2);
  });

  it("does not claim playback started after play rejects and follows media events", async () => {
    playMock.mockRejectedValueOnce(new Error("Playback was blocked"));
    renderPlayer();

    const video = screen.getByLabelText("LitBlog student tutorial");
    fireEvent.click(screen.getByRole("button", { name: "Play" }));

    await waitFor(() => expect(playMock).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Playback could not start. Please try again. The transcript remains available below.",
    );
    expect(screen.getByRole("button", { name: "Play" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    expect(playMock).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    fireEvent.play(video);
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Play tutorial" })).not.toBeInTheDocument();

    fireEvent.pause(video);
    expect(screen.getByRole("button", { name: "Play" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Play tutorial" })).toBeInTheDocument();
    expect(pauseMock).not.toHaveBeenCalled();
  });

  it("uses accessible vector icons instead of emoji-style control glyphs", () => {
    const { container } = renderPlayer();

    const iconButtons = [
      screen.getByRole("button", { name: "Play tutorial" }),
      screen.getByRole("button", { name: "Play" }),
      screen.getByRole("button", { name: "Mute" }),
      screen.getByRole("button", { name: "Turn captions off" }),
      screen.getByRole("button", { name: "Fullscreen unavailable" }),
    ];

    for (const button of iconButtons) {
      const icon = button.querySelector("svg");
      expect(icon).toBeInTheDocument();
      expect(icon).toHaveAttribute("aria-hidden", "true");
      expect(icon).toHaveAttribute("focusable", "false");
    }

    expect(container).not.toHaveTextContent(/[▶❚🔇🔊↙↗]/u);

    const video = screen.getByLabelText("LitBlog student tutorial");
    fireEvent.play(video);
    expect(screen.getByRole("button", { name: "Pause" }).querySelector("svg"))
      .toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Mute" }));
    expect(screen.getByRole("button", { name: "Unmute" }).querySelector("svg"))
      .toBeInTheDocument();
    expect(container).not.toHaveTextContent(/[▶❚🔇🔊↙↗]/u);
  });

  it("enables the English caption track by default and keeps the CC toggle synchronized", () => {
    renderPlayer();

    const video = screen.getByLabelText("LitBlog student tutorial");
    const captionTrack = { mode: "disabled" };
    Object.defineProperty(video, "textTracks", {
      configurable: true,
      value: [captionTrack],
    });

    fireEvent.loadedMetadata(video);
    expect(captionTrack.mode).toBe("showing");

    fireEvent.click(screen.getByRole("button", { name: "Turn captions off" }));
    expect(captionTrack.mode).toBe("disabled");
    expect(screen.getByRole("button", { name: "Turn captions on" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Turn captions on" }));
    expect(captionTrack.mode).toBe("showing");
  });

  it("keeps custom controls outside the 16:9 caption rendering viewport", () => {
    renderPlayer();

    const video = screen.getByLabelText("LitBlog student tutorial");
    const captionViewport = video.parentElement;

    expect(captionViewport).toHaveClass("tutorial-video-player__viewport");
    expect(within(captionViewport).queryByRole("slider", { name: "Seek video" }))
      .not.toBeInTheDocument();
  });

  it("keeps a computed 16:9 viewport and responds to the page theme", () => {
    renderPlayer();
    const player = screen.getByRole("region", { name: /Keyboard shortcuts/ });
    const viewport = screen.getByLabelText("LitBlog student tutorial").parentElement;

    expect(getComputedStyle(viewport).aspectRatio).toBe("16 / 9");
    viewport.style.width = "320px";
    expect(getComputedStyle(viewport).aspectRatio).toBe("16 / 9");

    const lightColor = getComputedStyle(player).color;
    document.documentElement.classList.add("dark");
    const darkColor = getComputedStyle(player).color;

    expect(lightColor).toBe("rgb(15, 23, 42)");
    expect(darkColor).toBe("rgb(226, 232, 240)");
  });

  it("exposes a strong focus-visible affordance through the parsed style contract", () => {
    renderPlayer();
    const player = screen.getByRole("region", { name: /Keyboard shortcuts/ });

    player.focus();
    const focusRule = Array.from(styleElement.sheet.cssRules).find(
      (rule) => rule.selectorText?.includes(".tutorial-video-player:focus-visible"),
    );

    expect(player).toHaveFocus();
    expect(focusRule).toBeDefined();
    expect(focusRule.style.outline).toBe("3px solid #fbbf24");
    expect(focusRule.style.getPropertyValue("outline-offset")).toBe("3px");
  });

  it("disables fullscreen with accurate guidance and ignores F when the API is unavailable", () => {
    renderPlayer();
    const player = screen.getByRole("region", { name: /Keyboard shortcuts/ });
    const fullscreenButton = screen.getByRole("button", { name: "Fullscreen unavailable" });

    expect(fullscreenButton).toBeDisabled();
    expect(fullscreenButton).toHaveAttribute(
      "title",
      "Fullscreen is not supported by this browser",
    );

    player.focus();
    expect(fireEvent.keyDown(player, { key: "f" })).toBe(true);
    expect(screen.getByRole("button", { name: "Fullscreen unavailable" })).toBeDisabled();
  });

  it("requests and exits fullscreen but changes control state only on fullscreenchange", () => {
    let fullscreenElement = null;
    const originalFullscreenDescriptor = Object.getOwnPropertyDescriptor(document, "fullscreenElement");
    const originalExitDescriptor = Object.getOwnPropertyDescriptor(document, "exitFullscreen");
    const originalRequestDescriptor = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      "requestFullscreen",
    );
    const requestFullscreen = vi.fn().mockResolvedValue();
    const exitFullscreen = vi.fn().mockResolvedValue();
    Object.defineProperty(document, "fullscreenElement", {
      configurable: true,
      get: () => fullscreenElement,
    });
    Object.defineProperty(document, "exitFullscreen", {
      configurable: true,
      value: exitFullscreen,
    });
    Object.defineProperty(HTMLElement.prototype, "requestFullscreen", {
      configurable: true,
      value: requestFullscreen,
    });

    try {
      renderPlayer();
      const player = screen.getByRole("region", { name: /Keyboard shortcuts/ });

      fireEvent.click(screen.getByRole("button", { name: "Enter fullscreen" }));
      expect(requestFullscreen).toHaveBeenCalledTimes(1);
      expect(screen.getByRole("button", { name: "Enter fullscreen" })).toBeInTheDocument();

      fullscreenElement = player;
      fireEvent(document, new Event("fullscreenchange"));
      expect(screen.getByRole("button", { name: "Exit fullscreen" })).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: "Exit fullscreen" }));
      expect(exitFullscreen).toHaveBeenCalledTimes(1);
      expect(screen.getByRole("button", { name: "Exit fullscreen" })).toBeInTheDocument();

      fullscreenElement = null;
      fireEvent(document, new Event("fullscreenchange"));
      expect(screen.getByRole("button", { name: "Enter fullscreen" })).toBeInTheDocument();
    } finally {
      if (originalFullscreenDescriptor) {
        Object.defineProperty(document, "fullscreenElement", originalFullscreenDescriptor);
      } else {
        delete document.fullscreenElement;
      }
      if (originalExitDescriptor) {
        Object.defineProperty(document, "exitFullscreen", originalExitDescriptor);
      } else {
        delete document.exitFullscreen;
      }
      if (originalRequestDescriptor) {
        Object.defineProperty(
          HTMLElement.prototype,
          "requestFullscreen",
          originalRequestDescriptor,
        );
      } else {
        delete HTMLElement.prototype.requestFullscreen;
      }
    }
  });

  it("absorbs rejected and throwing fullscreen API calls without reporting false state", async () => {
    let fullscreenElement = null;
    const originalFullscreenDescriptor = Object.getOwnPropertyDescriptor(document, "fullscreenElement");
    const originalExitDescriptor = Object.getOwnPropertyDescriptor(document, "exitFullscreen");
    const originalRequestDescriptor = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      "requestFullscreen",
    );
    const requestFullscreen = vi.fn()
      .mockRejectedValueOnce(new Error("Fullscreen denied"))
      .mockImplementationOnce(() => { throw new Error("Fullscreen unavailable"); });
    const exitFullscreen = vi.fn()
      .mockRejectedValueOnce(new Error("Exit denied"))
      .mockImplementationOnce(() => { throw new Error("Exit unavailable"); });
    Object.defineProperty(document, "fullscreenElement", {
      configurable: true,
      get: () => fullscreenElement,
    });
    Object.defineProperty(document, "exitFullscreen", {
      configurable: true,
      value: exitFullscreen,
    });
    Object.defineProperty(HTMLElement.prototype, "requestFullscreen", {
      configurable: true,
      value: requestFullscreen,
    });

    try {
      renderPlayer();
      const player = screen.getByRole("region", { name: /Keyboard shortcuts/ });

      fireEvent.click(screen.getByRole("button", { name: "Enter fullscreen" }));
      await waitFor(() => expect(requestFullscreen).toHaveBeenCalledTimes(1));
      expect(screen.getByRole("button", { name: "Enter fullscreen" })).toBeInTheDocument();

      expect(() => fireEvent.click(screen.getByRole("button", { name: "Enter fullscreen" })))
        .not.toThrow();
      expect(requestFullscreen).toHaveBeenCalledTimes(2);
      expect(screen.getByRole("button", { name: "Enter fullscreen" })).toBeInTheDocument();

      fullscreenElement = player;
      fireEvent(document, new Event("fullscreenchange"));
      fireEvent.click(screen.getByRole("button", { name: "Exit fullscreen" }));
      await waitFor(() => expect(exitFullscreen).toHaveBeenCalledTimes(1));
      expect(screen.getByRole("button", { name: "Exit fullscreen" })).toBeInTheDocument();

      expect(() => fireEvent.click(screen.getByRole("button", { name: "Exit fullscreen" })))
        .not.toThrow();
      expect(exitFullscreen).toHaveBeenCalledTimes(2);
      expect(screen.getByRole("button", { name: "Exit fullscreen" })).toBeInTheDocument();

      fullscreenElement = null;
      fireEvent(document, new Event("fullscreenchange"));
      expect(screen.getByRole("button", { name: "Enter fullscreen" })).toBeInTheDocument();
    } finally {
      if (originalFullscreenDescriptor) {
        Object.defineProperty(document, "fullscreenElement", originalFullscreenDescriptor);
      } else {
        delete document.fullscreenElement;
      }
      if (originalExitDescriptor) {
        Object.defineProperty(document, "exitFullscreen", originalExitDescriptor);
      } else {
        delete document.exitFullscreen;
      }
      if (originalRequestDescriptor) {
        Object.defineProperty(
          HTMLElement.prototype,
          "requestFullscreen",
          originalRequestDescriptor,
        );
      } else {
        delete HTMLElement.prototype.requestFullscreen;
      }
    }
  });

  it("updates speed, volume, seek, and time labels from safe media values", () => {
    renderPlayer();
    const video = screen.getByLabelText("LitBlog student tutorial");
    let mediaDuration = Number.NaN;

    Object.defineProperties(video, {
      duration: { configurable: true, get: () => mediaDuration },
      currentTime: { configurable: true, writable: true, value: 0 },
      volume: { configurable: true, writable: true, value: 1 },
      muted: { configurable: true, writable: true, value: false },
      playbackRate: { configurable: true, writable: true, value: 1 },
    });

    fireEvent.loadedMetadata(video);
    expect(screen.getByText("0:00 / 0:00")).toBeInTheDocument();

    mediaDuration = 120;
    fireEvent.durationChange(video);
    video.currentTime = 35;
    fireEvent.timeUpdate(video);
    expect(screen.getByText("0:35 / 2:00")).toBeInTheDocument();
    expect(screen.getByRole("slider", { name: "Seek video" }))
      .toHaveAttribute("aria-valuetext", "0:35 of 2:00");

    fireEvent.change(screen.getByRole("slider", { name: "Seek video" }), {
      target: { value: "90" },
    });
    expect(video.currentTime).toBe(90);

    fireEvent.change(screen.getByRole("slider", { name: "Volume" }), {
      target: { value: "0.25" },
    });
    expect(video.volume).toBe(0.25);

    video.volume = 0.4;
    fireEvent.volumeChange(video);
    expect(screen.getByRole("slider", { name: "Volume" })).toHaveValue("0.4");

    fireEvent.change(screen.getByRole("combobox", { name: "Playback speed" }), {
      target: { value: "1.5" },
    });
    expect(video.playbackRate).toBe(1.5);
    expect(screen.getByRole("combobox", { name: "Playback speed" })).toHaveValue("1.5");
  });

  it("clamps keyboard seeking and volume while supporting mute and fullscreen", () => {
    const originalExitDescriptor = Object.getOwnPropertyDescriptor(document, "exitFullscreen");
    const originalRequestDescriptor = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      "requestFullscreen",
    );
    const requestFullscreen = vi.fn().mockResolvedValue();
    Object.defineProperty(document, "exitFullscreen", {
      configurable: true,
      value: vi.fn().mockResolvedValue(),
    });
    Object.defineProperty(HTMLElement.prototype, "requestFullscreen", {
      configurable: true,
      value: requestFullscreen,
    });

    try {
      renderPlayer();
      const player = screen.getByRole("region", { name: /Keyboard shortcuts/ });
      const video = screen.getByLabelText("LitBlog student tutorial");
      Object.defineProperties(video, {
        duration: { configurable: true, value: 60 },
        currentTime: { configurable: true, writable: true, value: 2 },
        volume: { configurable: true, writable: true, value: 0.95 },
        muted: { configurable: true, writable: true, value: false },
      });

      player.focus();
      fireEvent.keyDown(player, { key: "ArrowLeft" });
      expect(video.currentTime).toBe(0);

      video.currentTime = 58;
      fireEvent.keyDown(player, { key: "ArrowRight" });
      expect(video.currentTime).toBe(60);

      fireEvent.keyDown(player, { key: "ArrowUp" });
      expect(video.volume).toBe(1);
      fireEvent.keyDown(player, { key: "ArrowDown" });
      expect(video.volume).toBeCloseTo(0.9);

      fireEvent.keyDown(player, { key: "m" });
      expect(video.muted).toBe(true);
      fireEvent.keyDown(player, { key: "f" });
      expect(requestFullscreen).toHaveBeenCalledTimes(1);
    } finally {
      if (originalExitDescriptor) {
        Object.defineProperty(document, "exitFullscreen", originalExitDescriptor);
      } else {
        delete document.exitFullscreen;
      }
      if (originalRequestDescriptor) {
        Object.defineProperty(
          HTMLElement.prototype,
          "requestFullscreen",
          originalRequestDescriptor,
        );
      } else {
        delete HTMLElement.prototype.requestFullscreen;
      }
    }
  });

  it("replaces unusable controls with a calm transcript fallback on media error", () => {
    renderPlayer();
    fireEvent.error(screen.getByLabelText("LitBlog student tutorial"));

    const fallback = screen.getByRole("alert");
    expect(fallback).toHaveTextContent("The tutorial video is not available right now");
    expect(fallback).toHaveTextContent("The written walkthrough is open below");
    expect(within(fallback).getByRole("link", { name: "Download transcript" }))
      .toHaveAttribute("href", "/tutorial.txt");
    expect(screen.getByText("Read tutorial transcript").closest("details")).toHaveAttribute("open");
    expect(screen.queryByRole("button", { name: "Play" })).not.toBeInTheDocument();
    expect(screen.queryByRole("slider", { name: "Seek video" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Mute" })).not.toBeInTheDocument();
  });
});
