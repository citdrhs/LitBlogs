import assert from "node:assert/strict";
import test from "node:test";

const manifestModule = await import("../src/manifest.js").catch(() => ({}));
const exporters = await import("../src/exporters.js").catch(() => ({}));

test("formats frame timestamps as WebVTT wall-clock times", () => {
  assert.equal(exporters.formatVttTimestamp?.(0, 30), "00:00:00.000");
  assert.equal(exporters.formatVttTimestamp?.(3510, 30), "00:01:57.000");
});

test("exports one ordered, bounded caption cue per scene", () => {
  const vtt = exporters.manifestToVtt?.(manifestModule.SCENES, manifestModule.VIDEO);
  assert.match(vtt ?? "", /^WEBVTT\n\n/);
  assert.equal((vtt.match(/--> /g) ?? []).length, 9);
  assert.match(vtt, /00:00:00\.200 --> 00:00:04\.800/);
  assert.match(vtt, /00:01:51\.200 --> 00:01:56\.800/);
  assert.match(vtt, /Welcome to LitBlog/);
  assert.match(vtt, /bold and highlighting preserved/);
});

test("exports a readable plain transcript from the same narration", () => {
  const transcript = exporters.manifestToPlainTranscript?.(
    manifestModule.SCENES,
    manifestModule.VIDEO,
  );
  assert.match(transcript ?? "", /^LitBlog Student Tutorial\nDuration: 1:57\n\n/);
  assert.match(transcript, /\[0:05\] Sign up/);
  assert.match(transcript, /\[1:51\] Verify and finish/);
  for (const scene of manifestModule.SCENES ?? []) {
    assert.match(transcript, new RegExp(scene.narration.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
});

test("exports frontend transcript data without a second handwritten script", () => {
  const transcript = exporters.manifestToFrontendTranscript?.(
    manifestModule.SCENES,
    manifestModule.VIDEO,
  );
  assert.equal(transcript?.length, 9);
  assert.deepEqual(transcript?.map(({ id }) => id), [
    "title",
    "signup",
    "signin",
    "join-class",
    "enter-class",
    "open-post",
    "compose",
    "publish",
    "verify",
  ]);
  assert.equal(transcript?.[1].time, "0:05");
  assert.equal(transcript?.at(-1).time, "1:51");
  assert.equal(transcript?.[6].text, manifestModule.SCENES?.[6].narration);
});

test("renders the committed frontend transcript module deterministically", () => {
  const output = exporters.manifestToFrontendModule?.(
    manifestModule.SCENES,
    manifestModule.VIDEO,
  );
  assert.match(output ?? "", /^\/\/ Generated from media\/tutorial-video\/src\/manifest\.js\./);
  assert.match(output, /export const studentTutorialTranscript = \[/);
  assert.match(output, /"id": "compose"/);
  assert.ok(output.endsWith(";\n"));
});
