import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

import { VIDEO } from "../src/manifest.js";
import {
  assertMediaTools,
  ensureDirectories,
  ffmpegPath,
  publicDirectory,
  tempDirectory,
} from "./lib/paths.mjs";

assertMediaTools();
ensureDirectories(path.join(publicDirectory, "audio"), tempDirectory);

const sampleRate = 48_000;
const channels = 2;
const frames = VIDEO.durationInSeconds * sampleRate;
const dataBytes = frames * channels * 2;
const buffer = Buffer.allocUnsafe(44 + dataBytes);
const wav = path.join(tempDirectory, "music-bed.wav");
const mp3 = path.join(publicDirectory, "audio", "music-bed.mp3");

buffer.write("RIFF", 0);
buffer.writeUInt32LE(36 + dataBytes, 4);
buffer.write("WAVE", 8);
buffer.write("fmt ", 12);
buffer.writeUInt32LE(16, 16);
buffer.writeUInt16LE(1, 20);
buffer.writeUInt16LE(channels, 22);
buffer.writeUInt32LE(sampleRate, 24);
buffer.writeUInt32LE(sampleRate * channels * 2, 28);
buffer.writeUInt16LE(channels * 2, 32);
buffer.writeUInt16LE(16, 34);
buffer.write("data", 36);
buffer.writeUInt32LE(dataBytes, 40);

const midiToHz = (note) => 440 * (2 ** ((note - 69) / 12));
const progression = [
  [48, 55, 59, 64],
  [45, 52, 57, 60],
  [41, 48, 52, 57],
  [43, 50, 55, 60],
];

for (let index = 0; index < frames; index += 1) {
  const time = index / sampleRate;
  const chord = progression[Math.floor(time / 8) % progression.length];
  const chordFade = Math.min(1, (time % 8) / 1.6, (8 - (time % 8)) / 1.6);
  const globalFade = Math.min(1, time / 2.5, (VIDEO.durationInSeconds - time) / 3.5);
  let pad = 0;
  for (const [voice, note] of chord.entries()) {
    const frequency = midiToHz(note);
    pad += Math.sin((Math.PI * 2 * frequency * time) + (voice * 0.19)) * 0.17;
    pad += Math.sin((Math.PI * 2 * frequency * 0.5 * time) + (voice * 0.11)) * 0.07;
  }
  const arpeggioNote = chord[Math.floor((time % 8) / 2)];
  const arpeggioEnvelope = Math.exp(-((time % 2) * 1.5));
  const arpeggio = Math.sin(Math.PI * 2 * midiToHz(arpeggioNote + 12) * time)
    * 0.08 * arpeggioEnvelope;
  const sample = Math.max(-1, Math.min(1, (pad * chordFade + arpeggio) * globalFade * 0.58));
  const left = sample * (0.96 + (0.04 * Math.sin(time * 0.21)));
  const right = sample * (0.96 + (0.04 * Math.cos(time * 0.19)));
  const offset = 44 + (index * 4);
  buffer.writeInt16LE(Math.round(left * 32767), offset);
  buffer.writeInt16LE(Math.round(right * 32767), offset + 2);
}

fs.writeFileSync(wav, buffer);
const result = spawnSync(ffmpegPath, [
  "-y", "-v", "error", "-i", wav,
  "-ar", "48000", "-ac", "2",
  "-codec:a", "libmp3lame", "-b:a", "128k",
  mp3,
], { encoding: "utf8", windowsHide: true });
if (result.status !== 0) throw new Error(`Music compression failed: ${result.stderr.trim()}`);
fs.rmSync(wav, { force: true });
console.log(`Generated deterministic original music bed: ${mp3}`);
