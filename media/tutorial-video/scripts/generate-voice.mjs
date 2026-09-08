import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

import { SCENES, VIDEO } from "../src/manifest.js";
import { probeMedia } from "./lib/probe.mjs";
import {
  assertMediaTools,
  ensureDirectories,
  ffmpegPath,
  packageDirectory,
  publicDirectory,
  tempDirectory,
} from "./lib/paths.mjs";

assertMediaTools();
const audioDirectory = path.join(publicDirectory, "audio");
const voiceTempDirectory = path.join(tempDirectory, "voice");
const powershellScript = path.join(packageDirectory, "scripts", "generate-zira-voice.ps1");
ensureDirectories(audioDirectory, voiceTempDirectory);

const run = (command, args, label) => {
  const result = spawnSync(command, args, {
    encoding: "utf8",
    windowsHide: true,
  });
  if (result.status !== 0) {
    throw new Error(`${label} failed: ${(result.stderr || result.stdout).trim()}`);
  }
};

const initialRate = Object.freeze({ title: 5, verify: 4, "open-post": 0 });
const mp3FrameSeconds = 1152 / 48_000;

for (const scene of SCENES) {
  const wav = path.join(voiceTempDirectory, `${scene.id}.wav`);
  const mp3 = path.join(audioDirectory, `${scene.id}.mp3`);
  const rate = initialRate[scene.id] ?? 1;
  fs.rmSync(wav, { force: true });
  run("powershell.exe", [
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", powershellScript,
    "-Text", scene.narration,
    "-OutputPath", wav,
    "-Rate", String(rate),
  ], `Zira narration for ${scene.id}`);
  const sourceDuration = Number(probeMedia(wav).format.duration);
  const targetMp3Duration = Math.floor(
    (scene.narrationDurationInFrames / VIDEO.fps) / mp3FrameSeconds,
  ) * mp3FrameSeconds;
  let targetPcmDuration = targetMp3Duration - mp3FrameSeconds;
  let compressedDuration = Number.NaN;
  let compressedFrames = 0;
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const tempo = sourceDuration / targetPcmDuration;
    if (!Number.isFinite(tempo) || tempo < 0.5 || tempo > 2) {
      throw new Error(`Zira narration needs an unsafe tempo adjustment for ${scene.id}`);
    }
    run(ffmpegPath, [
      "-y", "-v", "error", "-i", wav,
      "-af", `atempo=${tempo.toFixed(8)},apad,atrim=end=${targetPcmDuration.toFixed(6)}`,
      "-ar", "48000", "-ac", "1",
      "-codec:a", "libmp3lame", "-b:a", "96k",
      mp3,
    ], `MP3 compression for ${scene.id}`);
    compressedDuration = Number(probeMedia(mp3).format.duration);
    compressedFrames = Math.ceil(compressedDuration * VIDEO.fps);
    if (compressedFrames === scene.narrationDurationInFrames) break;
    targetPcmDuration -= (
      compressedFrames - scene.narrationDurationInFrames
    ) * mp3FrameSeconds;
  }
  const sceneSeconds = scene.durationInFrames / VIDEO.fps;
  if (compressedFrames !== scene.narrationDurationInFrames) {
    throw new Error(
      `${scene.id} narration is ${compressedFrames} frames; `
      + `expected ${scene.narrationDurationInFrames}`,
    );
  }
  fs.rmSync(wav, { force: true });
  console.log(`${scene.id}: Zira rate ${rate}, ${compressedDuration.toFixed(2)}s / ${sceneSeconds.toFixed(2)}s`);
}

fs.rmSync(voiceTempDirectory, { recursive: true, force: true });
