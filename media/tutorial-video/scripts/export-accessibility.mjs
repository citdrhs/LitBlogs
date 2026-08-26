import fs from "node:fs";
import path from "node:path";

import {
  manifestToFrontendModule,
  manifestToPlainTranscript,
  manifestToVtt,
} from "../src/exporters.js";
import { SCENES, VIDEO } from "../src/manifest.js";
import {
  validateManifest,
  validateTranscriptParity,
  validateVtt,
} from "../src/validation.js";
import {
  appDirectory,
  ensureDirectories,
  tutorialAssetsDirectory,
} from "./lib/paths.mjs";

const manifestIssues = validateManifest(SCENES);
if (manifestIssues.length) throw new Error(manifestIssues.join("\n"));

const vtt = manifestToVtt(SCENES, VIDEO);
const transcript = manifestToPlainTranscript(SCENES, VIDEO);
const frontendModule = manifestToFrontendModule(SCENES, VIDEO);
const accessibilityIssues = [
  ...validateVtt(vtt, VIDEO.durationInSeconds),
  ...validateTranscriptParity(transcript, SCENES),
];
if (accessibilityIssues.length) throw new Error(accessibilityIssues.join("\n"));

ensureDirectories(tutorialAssetsDirectory);
fs.writeFileSync(
  path.join(tutorialAssetsDirectory, "litblogs-tutorial.en.vtt"),
  vtt,
  "utf8",
);
fs.writeFileSync(
  path.join(tutorialAssetsDirectory, "litblogs-tutorial-transcript.txt"),
  transcript,
  "utf8",
);
fs.writeFileSync(
  path.join(appDirectory, "src", "components", "tutorialTranscript.js"),
  frontendModule,
  "utf8",
);
console.log("Exported WebVTT, plain transcript, and frontend transcript from the manifest");
