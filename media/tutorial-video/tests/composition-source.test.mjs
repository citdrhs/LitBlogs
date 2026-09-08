import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const testDirectory = path.dirname(fileURLToPath(import.meta.url));
const sourceDirectory = path.resolve(testDirectory, "..", "src");

test("keeps the tutorial poster free of a decorative play control", () => {
  const compositionSource = fs.readFileSync(
    path.join(sourceDirectory, "TutorialVideo.jsx"),
    "utf8",
  );
  const stylesheetSource = fs.readFileSync(
    path.join(sourceDirectory, "styles.css"),
    "utf8",
  );

  assert.doesNotMatch(compositionSource, /tutorial-poster__play/);
  assert.doesNotMatch(stylesheetSource, /\.tutorial-poster__play/);
});

test("keeps the rendered tutorial free of a decorative progress bar", () => {
  const compositionSource = fs.readFileSync(
    path.join(sourceDirectory, "TutorialVideo.jsx"),
    "utf8",
  );
  const stylesheetSource = fs.readFileSync(
    path.join(sourceDirectory, "styles.css"),
    "utf8",
  );

  assert.doesNotMatch(compositionSource, /tutorial-progress/);
  assert.doesNotMatch(stylesheetSource, /\.tutorial-progress/);
});

test("uses shared forward-only cursor helpers without symmetric click timing", () => {
  const compositionSource = fs.readFileSync(
    path.join(sourceDirectory, "TutorialVideo.jsx"),
    "utf8",
  );

  assert.match(compositionSource, /expandClickHolds/);
  assert.match(compositionSource, /clickPulseAtFrame/);
  assert.doesNotMatch(compositionSource, /Math\.abs\(frame\s*-\s*clickFrame\)/);
});

test("does not nest scene duration props inside the scene component", () => {
  const compositionSource = fs.readFileSync(
    path.join(sourceDirectory, "TutorialVideo.jsx"),
    "utf8",
  );
  const tutorialScene = compositionSource.match(
    /const TutorialScene[\s\S]*?export const TutorialVideo/,
  )?.[0] ?? "";

  assert.doesNotMatch(tutorialScene, /durationInFrames=/);
});

test("derives poster and title duration labels from the manifest", () => {
  const compositionSource = fs.readFileSync(
    path.join(sourceDirectory, "TutorialVideo.jsx"),
    "utf8",
  );

  assert.match(compositionSource, /formatDurationLabel\(VIDEO\)/);
  assert.match(compositionSource, /formatDurationWords\(VIDEO\)/);
  assert.doesNotMatch(compositionSource, /1:03|1 minute 3 seconds|1:57/);
});
