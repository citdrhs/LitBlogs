import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { probeMedia } from "../scripts/lib/probe.mjs";
import { SCENES, VIDEO } from "../src/manifest.js";

const packageDirectory = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);

test("committed narration audio matches the manifest and leaves only the closing beat", () => {
  for (const scene of SCENES) {
    const audioPath = path.join(packageDirectory, "public", scene.audioAsset);
    const durationInFrames = Math.ceil(
      Number(probeMedia(audioPath).format.duration) * VIDEO.fps,
    );

    assert.equal(durationInFrames, scene.narrationDurationInFrames, scene.id);
    assert.ok(scene.durationInFrames - durationInFrames >= 18, `${scene.id} closing beat too short`);
    assert.ok(scene.durationInFrames - durationInFrames <= 24, `${scene.id} narration tail too long`);
  }
});
