import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

import { bundle } from "@remotion/bundler";
import { renderMedia, selectComposition } from "@remotion/renderer";

import { VIDEO } from "../src/manifest.js";
import {
  assertMediaTools,
  ensureDirectories,
  entryPoint,
  ffmpegPath,
  tempDirectory,
  tutorialAssetsDirectory,
} from "./lib/paths.mjs";

assertMediaTools();
ensureDirectories(tempDirectory, tutorialAssetsDirectory);
const output = path.join(tutorialAssetsDirectory, "litblogs-tutorial.mp4");
const rendered = path.join(tempDirectory, "litblogs-tutorial-rendered.mp4");
const serveUrl = await bundle({
  entryPoint,
  onProgress: (progress) => {
    if (progress % 25 === 0) console.log(`Bundling: ${progress}%`);
  },
});
const composition = await selectComposition({ serveUrl, id: VIDEO.id });
if (composition.durationInFrames !== VIDEO.durationInFrames) {
  throw new Error(`Composition drifted to ${composition.durationInFrames} frames`);
}

const renderAtCrf = async (crf) => {
  await renderMedia({
    serveUrl,
    composition,
    codec: "h264",
    audioCodec: "aac",
    audioBitrate: "128k",
    sampleRate: 48_000,
    pixelFormat: "yuv420p",
    colorSpace: "bt709",
    crf,
    x264Preset: "medium",
    imageFormat: "jpeg",
    jpegQuality: 90,
    outputLocation: rendered,
    overwrite: true,
    concurrency: 4,
    logLevel: "warn",
    onProgress: ({ progress, renderedFrames, encodedFrames }) => {
      const percent = Math.floor(progress * 100);
      if (percent % 10 === 0) {
        console.log(`Render ${percent}% (${renderedFrames} rendered, ${encodedFrames} encoded)`);
      }
    },
  });
};

await renderAtCrf(22);
if (fs.statSync(rendered).size > 20 * 1024 * 1024) {
  console.log("CRF 22 exceeded 20MiB; rerendering at CRF 23");
  await renderAtCrf(23);
}

const remux = spawnSync(ffmpegPath, [
  "-y", "-v", "error", "-i", rendered,
  "-map", "0:v:0", "-map", "0:a:0",
  "-c", "copy", "-movflags", "+faststart",
  output,
], { encoding: "utf8", windowsHide: true });
if (remux.status !== 0) throw new Error(`Fast-start remux failed: ${remux.stderr.trim()}`);
fs.rmSync(rendered, { force: true });
console.log(`Rendered ${VIDEO.durationInFrames} frames to ${output}`);
