import React from "react";
import { Audio } from "@remotion/media";
import {
  AbsoluteFill,
  Img,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

import { SCENES, VIDEO } from "./manifest.js";

const interpolateTrack = (frame, keyframes, property, fallback = 0) => {
  const usable = keyframes.filter((keyframe) => Number.isFinite(keyframe[property]));
  if (usable.length === 0) return fallback;
  if (usable.length === 1) return usable[0][property];
  return interpolate(
    frame,
    usable.map(({ frame: at }) => at),
    usable.map((keyframe) => keyframe[property]),
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
};

const BrowserCapture = ({ scene, frame }) => {
  const camera = {
    scale: interpolateTrack(frame, scene.camera, "scale", 1),
    x: interpolateTrack(frame, scene.camera, "x", 0),
    y: interpolateTrack(frame, scene.camera, "y", 0),
  };
  const captureTimeline = scene.captureTimeline ?? [
    {
      frame: 0,
      asset: scene.captureAsset,
      objectPosition: scene.captureObjectPosition,
    },
    ...(scene.alternateCaptureAsset ? [{
      frame: scene.alternateAtFrame,
      asset: scene.alternateCaptureAsset,
      objectPosition: scene.alternateCaptureObjectPosition,
    }] : []),
  ];

  return (
    <div className="tutorial-browser">
      <div className="browser-chrome tutorial-browser__chrome">
        <span className="browser-dot browser-dot--red" />
        <span className="browser-dot browser-dot--amber" />
        <span className="browser-dot browser-dot--green" />
        <div className="browser-address">litblog.school</div>
      </div>
      <div className="tutorial-browser__viewport">
        <div
          className="tutorial-browser__camera"
          style={{ transform: `translate(${camera.x}px, ${camera.y}px) scale(${camera.scale})` }}
        >
          {captureTimeline.map((capture, index) => {
            const opacity = index === 0
              ? 1
              : interpolate(
                frame,
                [capture.frame - 10, capture.frame + 10],
                [0, 1],
                { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
              );
            return (
            <Img
              key={`${capture.asset}-${capture.frame}`}
              src={staticFile(capture.asset)}
              style={{
                opacity,
                objectPosition: capture.objectPosition ?? scene.captureObjectPosition ?? "center",
              }}
            />
            );
          })}
        </div>
      </div>
    </div>
  );
};

const AnimatedCursor = ({ scene, frame }) => {
  const x = interpolateTrack(frame, scene.cursor, "x");
  const y = interpolateTrack(frame, scene.cursor, "y");
  const nearest = [...scene.cursor].reverse().find((keyframe) => keyframe.frame <= frame)
    ?? scene.cursor[0];
  if (!nearest.visible) return null;
  const clickFrame = scene.cursor.find((keyframe) => keyframe.click
    && Math.abs(frame - keyframe.frame) <= 12)?.frame;
  const pulse = clickFrame === undefined
    ? 0
    : interpolate(Math.abs(frame - clickFrame), [0, 12], [1, 0], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
  return (
    <div className="tutorial-cursor" style={{ transform: `translate(${x}px, ${y}px)` }}>
      <span className="tutorial-cursor__pulse" style={{ opacity: pulse, transform: `scale(${1 + pulse})` }} />
      <svg viewBox="0 0 32 40" aria-hidden="true">
        <path d="M3 2 28 24l-12 2-6 11z" />
      </svg>
    </div>
  );
};

const SceneCallouts = ({ scene, frame }) => {
  const { fps } = useVideoConfig();
  return scene.callouts.map((callout) => {
    const endFrame = callout.endFrame ?? scene.durationInFrames - 1;
    if (frame < callout.frame || frame > endFrame) return null;
    const enter = spring({
      frame: frame - callout.frame,
      fps,
      config: { damping: 18, mass: 0.65, stiffness: 165 },
    });
    const exit = interpolate(frame, [endFrame - 10, endFrame], [1, 0], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
    return (
      <div
        className="tutorial-callout"
        key={callout.id}
        style={{
          left: callout.x,
          top: callout.y,
          opacity: enter * exit,
          transform: `translateY(${(1 - enter) * 16}px) scale(${0.96 + (enter * 0.04)})`,
        }}
      >
        <span>{callout.number}</span>
        <strong>{callout.label}</strong>
      </div>
    );
  });
};

const BrandedOverlay = ({ scene, frame }) => {
  if (scene.id === "title") {
    const enter = spring({ frame, fps: VIDEO.fps, config: { damping: 18, stiffness: 110 } });
    return (
      <div className="tutorial-intro" style={{ opacity: enter, transform: `translateY(${(1 - enter) * 28}px)` }}>
        <Img src={staticFile("brand/logo.png")} />
        <p>Student walkthrough · 1 minute 57 seconds</p>
        <h1>Create. Join. Publish.</h1>
      </div>
    );
  }
  if (scene.id === "verify" && frame >= 70) {
    const enter = spring({ frame: frame - 70, fps: VIDEO.fps, config: { damping: 19, stiffness: 120 } });
    return (
      <div className="tutorial-outro" style={{ opacity: enter }}>
        <Img src={staticFile("brand/logo.png")} />
        <div>
          <p>Post published</p>
          <h1>You're ready to write.</h1>
        </div>
        <span>Help is always available at LitBlog.</span>
      </div>
    );
  }
  return null;
};

const TutorialScene = ({ scene, index }) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(
    frame,
    [0, 10, scene.durationInFrames - 10, scene.durationInFrames - 1],
    [index === 0 ? 1 : 0, 1, 1, index === SCENES.length - 1 ? 1 : 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  return (
    <AbsoluteFill className={`tutorial-scene tutorial-scene--${scene.id}`} style={{ opacity }}>
      <div className="tutorial-grid" />
      <BrowserCapture scene={scene} frame={frame} />
      <header className="tutorial-scene__header">
        <div className="tutorial-scene__brand">
          <Img src={staticFile("brand/logo.png")} />
          <span>Student tutorial</span>
        </div>
        <div className="tutorial-scene__step">
          <span>{String(index + 1).padStart(2, "0")}</span>
          <strong>{scene.title}</strong>
        </div>
      </header>
      <SceneCallouts scene={scene} frame={frame} />
      <AnimatedCursor scene={scene} frame={frame} />
      <BrandedOverlay scene={scene} frame={frame} />
      <div className="tutorial-progress">
        <div style={{ width: `${((scene.startFrame + frame) / VIDEO.durationInFrames) * 100}%` }} />
      </div>
    </AbsoluteFill>
  );
};

export const TutorialVideo = () => {
  return (
    <AbsoluteFill className="tutorial-video">
      <Audio
        src={staticFile("audio/music-bed.mp3")}
        volume={(audioFrame) => interpolate(
          audioFrame,
          [0, 60, VIDEO.durationInFrames - 90, VIDEO.durationInFrames - 1],
          [0, 0.065, 0.065, 0],
          { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
        )}
      />
      {SCENES.map((scene, index) => (
        <Sequence
          key={scene.id}
          from={scene.startFrame}
          durationInFrames={scene.durationInFrames}
          name={scene.title}
        >
          <TutorialScene scene={scene} index={index} />
          <Audio src={staticFile(scene.audioAsset)} volume={1} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};

export const TutorialPoster = () => (
  <AbsoluteFill className="tutorial-poster">
    <Img className="tutorial-poster__capture" src={staticFile("captures/published-post.jpg")} />
    <div className="tutorial-poster__wash" />
    <div className="tutorial-poster__card">
      <Img src={staticFile("brand/logo.png")} />
      <p>LitBlog student tutorial</p>
      <h1>Create. Join. Publish.</h1>
      <span>Learn the complete workflow in 1:57</span>
    </div>
  </AbsoluteFill>
);
