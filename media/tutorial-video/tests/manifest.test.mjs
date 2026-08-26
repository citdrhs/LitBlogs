import assert from "node:assert/strict";
import test from "node:test";

const manifestModule = await import("../src/manifest.js").catch(() => ({}));
const validationModule = await import("../src/validation.js").catch(() => ({}));

const EXPECTED_SCENES = [
  ["title", 0, 150],
  ["signup", 150, 690],
  ["signin", 840, 420],
  ["join-class", 1260, 480],
  ["enter-class", 1740, 300],
  ["open-post", 2040, 270],
  ["compose", 2310, 750],
  ["publish", 3060, 270],
  ["verify", 3330, 180],
];

const EXPECTED_NARRATION = [
  "Welcome to LitBlog. In under two minutes, you'll create an account, join a class, and publish your first post.",
  "Choose Sign Up. Enter your name, school email, a strong password, and choose Student. Confirm your password, then select Sign Up.",
  "After registration, choose Sign In. Enter the same email and password to open your Student Hub.",
  "Select Join Class. Type the six-character code from your teacher, then choose Join Class again.",
  "Open the class card to see announcements, assignments, and posts.",
  "Select Create New Post.",
  "Add a clear title and write your response. Select text and choose Bold. Then choose a highlight color. The editor previews exactly what classmates and teachers will see.",
  "Review your work, then select Publish.",
  "Your post appears in the class feed with bold and highlighting preserved. You're ready to write on LitBlog.",
];

const EXPECTED_CLICK_TARGETS = [
  ["signup", 520, "Sign Up"],
  ["signin", 48, "Registration Sign In"],
  ["signin", 350, "Sign In"],
  ["join-class", 34, "Open Join Class"],
  ["join-class", 380, "Submit Join Class"],
  ["enter-class", 66, "English 10 Reading Circle class card"],
  ["open-post", 95, "Create New Post"],
  ["compose", 430, "Bold"],
  ["compose", 590, "Open Highlight palette"],
  ["compose", 650, "Amber #fef3c7"],
  ["publish", 165, "Publish"],
];

test("publishes the exact 117-second tutorial timeline", () => {
  assert.deepEqual(
    manifestModule.SCENES?.map(({ id, startFrame, durationInFrames }) => [
      id,
      startFrame,
      durationInFrames,
    ]),
    EXPECTED_SCENES,
  );
  assert.equal(manifestModule.VIDEO?.width, 1280);
  assert.equal(manifestModule.VIDEO?.height, 720);
  assert.equal(manifestModule.VIDEO?.fps, 30);
  assert.equal(manifestModule.VIDEO?.durationInFrames, 3510);
});

test("keeps scene metadata browser-safe, descriptive, and bounded", () => {
  const scenes = manifestModule.SCENES ?? [];
  assert.equal(new Set(scenes.map(({ id }) => id)).size, EXPECTED_SCENES.length);

  for (const scene of scenes) {
    assert.ok(scene.title?.trim(), `${scene.id} needs a title`);
    assert.ok(scene.narration?.trim(), `${scene.id} needs narration`);
    assert.ok(scene.caption?.text?.trim(), `${scene.id} needs a caption`);
    assert.ok(scene.captureAsset?.trim(), `${scene.id} needs a capture`);
    assert.ok(scene.camera?.length, `${scene.id} needs camera keyframes`);
    assert.ok(scene.cursor?.length, `${scene.id} needs cursor keyframes`);
    assert.ok(scene.callouts?.length, `${scene.id} needs callouts`);
  }

  assert.doesNotThrow(() => JSON.stringify(scenes));
  assert.deepEqual(validationModule.validateManifest?.(scenes), []);
});

test("uses the approved narration verbatim", () => {
  assert.deepEqual(
    manifestModule.SCENES?.map(({ narration }) => narration),
    EXPECTED_NARRATION,
  );
});

test("keeps cursor and callout visuals fully inside 1280x720", () => {
  for (const scene of manifestModule.SCENES ?? []) {
    for (const keyframe of scene.cursor) {
      assert.ok(keyframe.x >= 13 && keyframe.x <= 1248, `${scene.id} cursor x=${keyframe.x}`);
      assert.ok(keyframe.y >= 13 && keyframe.y <= 680, `${scene.id} cursor y=${keyframe.y}`);
    }
    for (const keyframe of scene.callouts) {
      assert.ok(keyframe.x >= 0 && keyframe.x <= 1000, `${scene.id} callout x=${keyframe.x}`);
      assert.ok(keyframe.y >= 0 && keyframe.y <= 660, `${scene.id} callout y=${keyframe.y}`);
    }
  }
});

test("declares every click target in composition space and places the cursor tip inside it", () => {
  const clicks = (manifestModule.SCENES ?? []).flatMap((scene) => scene.cursor
    .filter(({ click }) => click)
    .map((keyframe) => [scene.id, keyframe]));
  assert.deepEqual(
    clicks.map(([sceneId, keyframe]) => [sceneId, keyframe.frame, keyframe.target?.label]),
    EXPECTED_CLICK_TARGETS,
  );

  for (const [sceneId, keyframe] of clicks) {
    const { left, top, right, bottom } = keyframe.target.bounds;
    assert.equal(keyframe.target.space, "composition", `${sceneId} target space`);
    assert.ok(left >= 0 && left < right && right <= 1280, `${sceneId} target x bounds`);
    assert.ok(top >= 0 && top < bottom && bottom <= 720, `${sceneId} target y bounds`);
    assert.ok(keyframe.x + 3 >= left && keyframe.x + 3 <= right, `${sceneId} click tip x`);
    assert.ok(keyframe.y + 2 >= top && keyframe.y + 2 <= bottom, `${sceneId} click tip y`);
  }
});

test("keeps target controls visible through capture changes and camera framing", () => {
  const join = manifestModule.SCENE_BY_ID?.["join-class"];
  const openPost = manifestModule.SCENE_BY_ID?.["open-post"];
  const publish = manifestModule.SCENE_BY_ID?.publish;
  assert.equal(join.captureAsset, "captures/student-hub-empty.jpg");
  assert.equal(join.alternateCaptureAsset, "captures/join-class-code.jpg");
  assert.equal(join.captureObjectPosition, "center top");
  assert.equal(join.alternateCaptureObjectPosition, "center");
  assert.ok(join.alternateAtFrame > 34, "join modal must appear after the opener click");
  assert.ok(openPost.camera.find(({ frame }) => frame === 124)?.y >= 35);
  assert.equal(publish.captureObjectPosition, "center bottom");
});

test("reveals the highlight palette and amber formatting only after their separate clicks", () => {
  const compose = manifestModule.SCENE_BY_ID?.compose;
  assert.deepEqual(
    compose.captureTimeline?.map(({ frame, asset }) => [frame, asset]),
    [
      [0, "captures/post-written.jpg"],
      [450, "captures/post-bold.jpg"],
      [610, "captures/post-highlight-palette.jpg"],
      [680, "captures/post-formatted.jpg"],
    ],
  );
  const boldClick = compose.cursor.find(({ target }) => target?.label === "Bold");
  const paletteClick = compose.cursor.find(
    ({ target }) => target?.label === "Open Highlight palette",
  );
  const amberClick = compose.cursor.find(
    ({ target }) => target?.label === "Amber #fef3c7",
  );
  assert.ok(compose.captureTimeline[1].frame > boldClick.frame);
  assert.ok(compose.captureTimeline[2].frame > paletteClick.frame);
  assert.ok(amberClick.frame > compose.captureTimeline[2].frame);
  assert.ok(compose.captureTimeline[3].frame > amberClick.frame);
});

test("approaches the visible Publish button before the click pulse", () => {
  const publish = manifestModule.SCENE_BY_ID?.publish;
  const approach = publish.cursor.find(({ frame }) => frame === 120);
  const click = publish.cursor.find(({ click }) => click);
  const { left, top, right, bottom } = click.target.bounds;
  assert.ok(approach.x + 3 >= left && approach.x + 3 <= right);
  assert.ok(approach.y + 2 >= top && approach.y + 2 <= bottom);
});

test("reports cursor or callout visuals extending outside the visible frame", () => {
  const scenes = structuredClone(manifestModule.SCENES);
  scenes[0].cursor[0].y = 681;
  assert.ok(validationModule.validateManifest(scenes).includes(
    "scene title has an off-canvas cursor visual",
  ));
});

test("reports missing or misaligned composition-space click targets", () => {
  const missing = structuredClone(manifestModule.SCENES);
  delete missing[1].cursor.find(({ click }) => click).target;
  assert.ok(validationModule.validateManifest(missing).includes(
    "scene signup click at frame 520 has no composition-space target",
  ));

  const misaligned = structuredClone(manifestModule.SCENES);
  const click = misaligned[1].cursor.find(({ click }) => click);
  click.target = {
    label: "Sign Up",
    space: "composition",
    bounds: { left: 0, top: 0, right: 10, bottom: 10 },
  };
  assert.ok(validationModule.validateManifest(misaligned).includes(
    "scene signup click at frame 520 misses target Sign Up",
  ));
});

test("contains no real email addresses, passwords, tokens, or secrets", () => {
  const serialized = JSON.stringify(manifestModule.SCENES ?? []);
  const emails = serialized.match(/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/g) ?? [];

  assert.ok(emails.every((email) => email.endsWith("@example.com")));
  assert.doesNotMatch(serialized, /password\s*[:=]|bearer\s+|api[_-]?key|secret\s*[:=]/i);
});

test("derives starts cumulatively and keeps cues and keyframes inside each scene", () => {
  const scenes = manifestModule.SCENES ?? [];
  let expectedStart = 0;

  for (const scene of scenes) {
    assert.equal(scene.startFrame, expectedStart);
    assert.ok(scene.caption.startOffsetFrames >= 0);
    assert.ok(scene.caption.endOffsetFrames <= scene.durationInFrames);
    assert.ok(scene.caption.startOffsetFrames < scene.caption.endOffsetFrames);

    for (const collection of [scene.camera, scene.cursor, scene.callouts]) {
      for (const keyframe of collection) {
        assert.ok(keyframe.frame >= 0);
        assert.ok(keyframe.frame < scene.durationInFrames);
      }
    }
    expectedStart += scene.durationInFrames;
  }

  assert.equal(expectedStart, 3510);
});
