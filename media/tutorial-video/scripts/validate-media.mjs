import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

import { SCENES, VIDEO } from "../src/manifest.js";
import {
  hasFastStartMp4,
  parseMaxVolumeDb,
  readWebpDimensions,
  validateAudioPeak,
  validateProbeData,
  validateTranscriptParity,
  validateVtt,
} from "../src/validation.js";
import {
  ffmpegPath,
  faqAssetsDirectory,
  tutorialAssetsDirectory,
} from "./lib/paths.mjs";
import { probeMedia } from "./lib/probe.mjs";

const video = path.join(tutorialAssetsDirectory, "litblogs-tutorial.mp4");
const poster = path.join(tutorialAssetsDirectory, "litblogs-tutorial-poster.jpg");
const vttPath = path.join(tutorialAssetsDirectory, "litblogs-tutorial.en.vtt");
const transcriptPath = path.join(tutorialAssetsDirectory, "litblogs-tutorial-transcript.txt");
const faqStills = [
  "litblogs-faq-sign-up.webp",
  "litblogs-faq-sign-in.webp",
  "litblogs-faq-join-class.webp",
  "litblogs-faq-post-editor.webp",
].map((filename) => path.join(faqAssetsDirectory, filename));

const missing = [video, poster, vttPath, transcriptPath, ...faqStills]
  .filter((target) => !fs.existsSync(target));
if (missing.length) throw new Error(`Missing generated assets:\n${missing.join("\n")}`);

const issues = validateProbeData(probeMedia(video));
if (!hasFastStartMp4(fs.readFileSync(video))) issues.push("MP4 moov box does not precede mdat");
const volumeDetect = spawnSync(ffmpegPath, [
  "-v", "info", "-i", video,
  "-map", "0:a:0",
  "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
  "-f", "null", process.platform === "win32" ? "NUL" : "/dev/null",
], { encoding: "utf8", windowsHide: true });
if (volumeDetect.status !== 0) {
  issues.push(`ffmpeg loudnorm peak analysis failed with exit ${volumeDetect.status}`);
}
const maxVolumeDb = parseMaxVolumeDb(volumeDetect.stderr);
issues.push(...validateAudioPeak(maxVolumeDb));

const posterStream = probeMedia(poster).streams.find(({ codec_type }) => codec_type === "video");
if (posterStream?.width !== 1280 || posterStream?.height !== 720) {
  issues.push(`poster is ${posterStream?.width}x${posterStream?.height}, expected 1280x720`);
}
for (const still of faqStills) {
  const stream = probeMedia(still).streams.find(({ codec_type }) => codec_type === "video");
  const dimensions = stream?.width > 0 && stream?.height > 0
    ? { width: stream.width, height: stream.height }
    : readWebpDimensions(fs.readFileSync(still));
  if (dimensions?.width !== 1440 || dimensions?.height !== 900) {
    issues.push(`${path.basename(still)} is ${dimensions?.width}x${dimensions?.height}, expected 1440x900`);
  }
  if (fs.statSync(still).size < 10_000) issues.push(`${path.basename(still)} is unexpectedly small`);
}

const vtt = fs.readFileSync(vttPath, "utf8");
const transcript = fs.readFileSync(transcriptPath, "utf8");
issues.push(...validateVtt(vtt, VIDEO.durationInSeconds));
issues.push(...validateTranscriptParity(transcript, SCENES));
if (!transcript.trim()) issues.push("plain transcript is empty");

if (issues.length) throw new Error(`Media validation failed:\n- ${issues.join("\n- ")}`);
const probe = probeMedia(video);
const videoStream = probe.streams.find(({ codec_type }) => codec_type === "video");
const audioStream = probe.streams.find(({ codec_type }) => codec_type === "audio");
console.log(JSON.stringify({
  file: video,
  bytes: fs.statSync(video).size,
  duration: Number(probe.format.duration),
  video: {
    codec: videoStream.codec_name,
    dimensions: `${videoStream.width}x${videoStream.height}`,
    pixelFormat: videoStream.pix_fmt,
    frameRate: videoStream.avg_frame_rate,
    colorSpace: videoStream.color_space,
  },
  audio: {
    codec: audioStream.codec_name,
    sampleRate: audioStream.sample_rate,
  },
  fastStart: true,
  maxVolumeDb,
  faqStills: faqStills.map((still) => ({
    file: still,
    bytes: fs.statSync(still).size,
  })),
}, null, 2));
