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

const initialRate = Object.freeze({ title: 4, verify: 4, "open-post": 0 });

for (const scene of SCENES) {
  const wav = path.join(voiceTempDirectory, `${scene.id}.wav`);
  const mp3 = path.join(audioDirectory, `${scene.id}.mp3`);
  let rate = initialRate[scene.id] ?? 1;
  let duration = Number.POSITIVE_INFINITY;

  while (rate <= 8) {
    fs.rmSync(wav, { force: true });
    run("powershell.exe", [
      "-NoProfile",
      "-ExecutionPolicy", "Bypass",
      "-File", powershellScript,
      "-Text", scene.narration,
      "-OutputPath", wav,
      "-Rate", String(rate),
    ], `Zira narration for ${scene.id}`);
    duration = Number(probeMedia(wav).format.duration);
    if (duration <= (scene.durationInFrames / VIDEO.fps) - 0.12) break;
    rate += 1;
  }
  if (rate > 8) throw new Error(`Zira narration cannot fit scene ${scene.id}`);

  run(ffmpegPath, [
    "-y", "-v", "error", "-i", wav,
    "-ar", "48000", "-ac", "1",
    "-codec:a", "libmp3lame", "-b:a", "96k",
    mp3,
  ], `MP3 compression for ${scene.id}`);
  const compressedDuration = Number(probeMedia(mp3).format.duration);
  const sceneSeconds = scene.durationInFrames / VIDEO.fps;
  if (compressedDuration > sceneSeconds - 0.08) {
    throw new Error(`${scene.id} narration is ${compressedDuration}s for a ${sceneSeconds}s scene`);
  }
  fs.rmSync(wav, { force: true });
  console.log(`${scene.id}: Zira rate ${rate}, ${compressedDuration.toFixed(2)}s / ${sceneSeconds.toFixed(2)}s`);
}

fs.rmSync(voiceTempDirectory, { recursive: true, force: true });
