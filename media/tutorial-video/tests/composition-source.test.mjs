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
