import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import TutorialVideoPlayer from "./TutorialVideoPlayer.jsx";
import { studentTutorialTranscript } from "./tutorialTranscript.js";

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

  beforeEach(() => {
    playMock = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    pauseMock = vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("keeps shortcuts scoped to the focused player and ignores control targets", () => {
    renderPlayer();

    const player = screen.getByRole("region", { name: /Keyboard shortcuts/ });
    const playButton = screen.getByRole("button", { name: "Play" });

    fireEvent.keyDown(document.body, { key: "k" });
    expect(playMock).not.toHaveBeenCalled();

    player.focus();
    expect(player).toHaveFocus();
    fireEvent.keyDown(player, { key: "k" });
    expect(playMock).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(playButton, { key: "k" });
    expect(playMock).toHaveBeenCalledTimes(1);

    const summary = screen.getByText("Read tutorial transcript");
    expect(fireEvent.keyDown(summary, { key: " " })).toBe(true);
    expect(playMock).toHaveBeenCalledTimes(1);
  });

  it("does not claim playback started after play rejects and follows media events", async () => {
    playMock.mockRejectedValueOnce(new Error("Playback was blocked"));
    renderPlayer();

    const video = screen.getByLabelText("LitBlog student tutorial");
    fireEvent.click(screen.getByRole("button", { name: "Play" }));

    await waitFor(() => expect(playMock).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("button", { name: "Play" })).toBeInTheDocument();

    fireEvent.play(video);
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Play tutorial" })).not.toBeInTheDocument();

    fireEvent.pause(video);
    expect(screen.getByRole("button", { name: "Play" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Play tutorial" })).toBeInTheDocument();
    expect(pauseMock).not.toHaveBeenCalled();
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

  it("derives fullscreen control state from fullscreenchange events", async () => {
    let fullscreenElement = null;
    const originalFullscreenDescriptor = Object.getOwnPropertyDescriptor(document, "fullscreenElement");
    Object.defineProperty(document, "fullscreenElement", {
      configurable: true,
      get: () => fullscreenElement,
    });

    try {
      renderPlayer();
      const player = screen.getByRole("region", { name: /Keyboard shortcuts/ });
      const requestFullscreen = vi.fn().mockResolvedValue();
      Object.defineProperty(player, "requestFullscreen", {
        configurable: true,
        value: requestFullscreen,
      });

      fireEvent.click(screen.getByRole("button", { name: "Enter fullscreen" }));
      expect(requestFullscreen).toHaveBeenCalledTimes(1);
      expect(screen.getByRole("button", { name: "Enter fullscreen" })).toBeInTheDocument();

      fullscreenElement = player;
      fireEvent(document, new Event("fullscreenchange"));
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
    renderPlayer();
    const player = screen.getByRole("region", { name: /Keyboard shortcuts/ });
    const video = screen.getByLabelText("LitBlog student tutorial");
    Object.defineProperties(video, {
      duration: { configurable: true, value: 60 },
      currentTime: { configurable: true, writable: true, value: 2 },
      volume: { configurable: true, writable: true, value: 0.95 },
      muted: { configurable: true, writable: true, value: false },
    });
    const requestFullscreen = vi.fn().mockResolvedValue();
    Object.defineProperty(player, "requestFullscreen", {
      configurable: true,
      value: requestFullscreen,
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
