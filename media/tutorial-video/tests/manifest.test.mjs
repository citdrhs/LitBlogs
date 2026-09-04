import assert from "node:assert/strict";
import test from "node:test";

const manifestModule = await import("../src/manifest.js").catch(() => ({}));
const validationModule = await import("../src/validation.js").catch(() => ({}));
const animationModule = await import("../src/animation.js").catch(() => ({}));

const EXPECTED_SCENES = [
  ["title", 0, 159],
  ["signup", 159, 449],
  ["signin", 608, 194],
  ["join-class", 802, 222],
  ["enter-class", 1024, 147],
  ["open-post", 1171, 99],
  ["compose", 1270, 350],
  ["publish", 1620, 113],
  ["verify", 1733, 158],
];

const EXPECTED_NARRATION = [
  "Welcome to LitBlog. In under two minutes, you'll create an account, join a class, and publish your first post.",
  "Choose Sign Up. Enter your name, school email, a strong password, and choose Student. Confirm your password, then select Sign Up. Open the verification email and select Verify Email before you sign in.",
  "After verification, choose Sign In. Enter the same email and password to open your Student Hub.",
  "Select Join Class. Type the six-character code from your teacher, then choose Join Class again.",
  "Open the class card to see announcements, assignments, and posts.",
  "Select Create New Post.",
  "Add a clear title and write your response. Select text and choose Bold. Then choose a highlight color. The editor previews exactly what classmates and teachers will see.",
  "Review your work, then select Publish.",
  "Your post appears in the class feed with bold and highlighting preserved. You're ready to write on LitBlog.",
];

const EXPECTED_CLICK_TARGETS = [
  ["signup", 264, "Sign Up"],
  ["signin", 22, "Verification Sign In"],
  ["signin", 146, "Sign In"],
  ["join-class", 16, "Open Join Class"],
  ["join-class", 175, "Submit Join Class"],
  ["enter-class", 32, "English 10 Reading Circle class card"],
  ["open-post", 35, "Create New Post"],
  ["compose", 118, "Bold"],
  ["compose", 156, "Open Highlight palette"],
  ["compose", 190, "Amber #fef3c7"],
  ["publish", 67, "Publish"],
];

const EXPECTED_NARRATION_FRAMES = [135, 425, 170, 198, 123, 75, 326, 89, 134];

test("publishes the exact 1:03 tutorial timeline", () => {
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
  assert.equal(manifestModule.VIDEO?.durationInFrames, 1891);
  assert.equal(manifestModule.VIDEO?.durationInSeconds, 1891 / 30);
});

test("ends every scene at the narration or action bound with only a short closing beat", () => {
  for (const scene of manifestModule.SCENES ?? []) {
    const lastRequiredAction = Math.max(
      0,
      ...scene.cursor.filter(({ click }) => click).map(({ frame }) => frame),
    );
    const expectedDuration = Math.max(
      scene.narrationDurationInFrames + 24,
      lastRequiredAction + 18,
    );
    assert.equal(scene.durationInFrames, expectedDuration, scene.id);
    assert.ok(
      scene.durationInFrames - scene.narrationDurationInFrames <= 24,
      `${scene.id} trails narration too long`,
    );
  }
});

test("holds every click target through its forward-only pulse", () => {
  assert.equal(typeof animationModule.expandClickHolds, "function");
  assert.equal(typeof animationModule.clickPulseAtFrame, "function");

  for (const scene of manifestModule.SCENES ?? []) {
    const expanded = animationModule.expandClickHolds(scene.cursor);
    for (const click of scene.cursor.filter(({ click }) => click)) {
      const hold = expanded.find(({ frame }) => frame === click.frame + 12);
      assert.ok(hold, `${scene.id} click needs a +12 hold`);
      assert.equal(hold.x, click.x, `${scene.id} click x moved during pulse`);
      assert.equal(hold.y, click.y, `${scene.id} click y moved during pulse`);
      assert.equal(animationModule.clickPulseAtFrame(click.frame - 1, scene.cursor), 0);
      assert.equal(animationModule.clickPulseAtFrame(click.frame, scene.cursor), 1);
      assert.ok(animationModule.clickPulseAtFrame(click.frame + 6, scene.cursor) > 0);
      assert.equal(animationModule.clickPulseAtFrame(click.frame + 12, scene.cursor), 0);
      assert.equal(animationModule.clickPulseAtFrame(click.frame + 13, scene.cursor), 0);
    }
  }
});

test("keeps scene metadata browser-safe, descriptive, and bounded", () => {
  const scenes = manifestModule.SCENES ?? [];
  assert.equal(new Set(scenes.map(({ id }) => id)).size, EXPECTED_SCENES.length);

  for (const scene of scenes) {
    assert.ok(scene.title?.trim(), `${scene.id} needs a title`);
    assert.ok(scene.narration?.trim(), `${scene.id} needs narration`);
    assert.ok(scene.captionCues?.length, `${scene.id} needs phrase caption cues`);
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
  assert.deepEqual(
    manifestModule.SCENES?.map(({ narrationDurationInFrames }) => narrationDurationInFrames),
    EXPECTED_NARRATION_FRAMES,
  );
});

test("derives narration from readable phrase cues with no more than two short lines", () => {
  for (const scene of manifestModule.SCENES ?? []) {
    const cueNarration = scene.captionCues
      .map(({ text }) => text.replace(/\s+/g, " ").trim())
      .join(" ");
    assert.equal(scene.narration, cueNarration, scene.id);

    let previousEnd = -1;
    for (const cue of scene.captionCues) {
      const lines = cue.text.split("\n");
      assert.ok(lines.length <= 2, `${scene.id} cue exceeds two displayed lines`);
      assert.ok(
        lines.every((line) => line.length <= 52),
        `${scene.id} cue has a line wider than 52 characters`,
      );
      assert.ok(cue.startOffsetFrames >= 0, `${scene.id} cue starts before its scene`);
      assert.ok(cue.endOffsetFrames <= scene.durationInFrames, `${scene.id} cue ends after its scene`);
      assert.ok(cue.startOffsetFrames < cue.endOffsetFrames, `${scene.id} cue has no duration`);
      assert.ok(cue.startOffsetFrames >= previousEnd, `${scene.id} cues overlap`);
      previousEnd = cue.endOffsetFrames;
    }
  }
});

test("synchronizes signup and formatting clicks to the phrases that describe them", () => {
  const signup = manifestModule.SCENE_BY_ID?.signup;
  const compose = manifestModule.SCENE_BY_ID?.compose;
  const signupCue = signup.captionCues.find(({ text }) => text.includes("then select Sign Up"));
  const boldCue = compose.captionCues.find(({ text }) => text.includes("choose Bold"));
  const highlightCue = compose.captionCues.find(({ text }) => text.includes("highlight color"));
  const signupClick = signup.cursor.find(({ target }) => target?.label === "Sign Up");
  const boldClick = compose.cursor.find(({ target }) => target?.label === "Bold");
  const paletteClick = compose.cursor.find(
    ({ target }) => target?.label === "Open Highlight palette",
  );
  const amberClick = compose.cursor.find(({ target }) => target?.label === "Amber #fef3c7");

  for (const [click, cue, label] of [
    [signupClick, signupCue, "signup"],
    [boldClick, boldCue, "bold"],
    [paletteClick, highlightCue, "highlight palette"],
    [amberClick, highlightCue, "highlight color"],
  ]) {
    assert.ok(click.frame >= cue.startOffsetFrames, `${label} happens before its narration`);
    assert.ok(click.frame < cue.endOffsetFrames, `${label} happens after its narration`);
  }

  assert.ok(signup.alternateAtFrame - 10 > signupClick.frame + 12);
  const verificationCue = signup.captionCues.find(({ text }) => text.includes("verification email"));
  assert.ok(signup.alternateAtFrame + 10 <= verificationCue.startOffsetFrames + 1);
});

test("links every click to a unique caption phrase and keeps the action inside it", () => {
  for (const scene of manifestModule.SCENES ?? []) {
    assert.equal(
      new Set(scene.captionCues.map(({ id }) => id)).size,
      scene.captionCues.length,
      `${scene.id} cue IDs`,
    );
    for (const click of scene.cursor.filter(({ click: isClick }) => isClick)) {
      const cue = scene.captionCues.find(({ id }) => id === click.actionCueId);
      assert.ok(cue, `${scene.id} ${click.target.label} needs a caption phrase link`);
      assert.ok(click.frame >= cue.startOffsetFrames, `${scene.id} action starts before its phrase`);
      assert.ok(click.frame < cue.endOffsetFrames, `${scene.id} action ends after its phrase`);
    }
  }
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

test("locks refreshed auth clicks to their encoded-frame-audited controls", () => {
  const signupClick = manifestModule.SCENE_BY_ID?.signup.cursor.find(({ click }) => click);
  const signinClick = manifestModule.SCENE_BY_ID?.signin.cursor.find(
    ({ target }) => target?.label === "Sign In",
  );

  assert.deepEqual(
    { x: signupClick.x, y: signupClick.y, bounds: signupClick.target.bounds },
    {
      x: 815,
      y: 660,
      bounds: { left: 582, top: 650, right: 1068, bottom: 680 },
    },
  );
  assert.deepEqual(
    { x: signinClick.x, y: signinClick.y, bounds: signinClick.target.bounds },
    {
      x: 760,
      y: 400,
      bounds: { left: 584, top: 379, right: 941, bottom: 435 },
    },
  );
});

test("keeps target controls visible through capture changes and camera framing", () => {
  const join = manifestModule.SCENE_BY_ID?.["join-class"];
  const openPost = manifestModule.SCENE_BY_ID?.["open-post"];
  const publish = manifestModule.SCENE_BY_ID?.publish;
  assert.equal(join.captureAsset, "captures/student-hub-empty.jpg");
  assert.equal(join.alternateCaptureAsset, "captures/join-class-code.jpg");
  assert.equal(join.captureObjectPosition, "center top");
  assert.equal(join.alternateCaptureObjectPosition, "center");
  assert.ok(join.alternateAtFrame > 16, "join modal must appear after the opener click");
  assert.ok(openPost.camera.find(({ frame }) => frame === 45)?.y >= 35);
  assert.equal(publish.captureObjectPosition, "center bottom");
});

test("reveals the highlight palette and amber formatting only after their separate clicks", () => {
  const compose = manifestModule.SCENE_BY_ID?.compose;
  assert.deepEqual(
    compose.captureTimeline?.map(({ frame, asset }) => [frame, asset]),
    [
      [0, "captures/post-written.jpg"],
      [142, "captures/post-bold.jpg"],
      [180, "captures/post-highlight-palette.jpg"],
      [213, "captures/post-formatted.jpg"],
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
  const approach = publish.cursor.find(({ frame }) => frame === 48);
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
    "scene signup click at frame 264 has no composition-space target",
  ));

  const misaligned = structuredClone(manifestModule.SCENES);
  const click = misaligned[1].cursor.find(({ click }) => click);
  click.target = {
    label: "Sign Up",
    space: "composition",
    bounds: { left: 0, top: 0, right: 10, bottom: 10 },
  };
  assert.ok(validationModule.validateManifest(misaligned).includes(
    "scene signup click at frame 264 misses target Sign Up",
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
    assert.ok(scene.captionCues.length > 0);
    assert.ok(scene.captionCues.every((cue) => cue.startOffsetFrames >= 0));
    assert.ok(scene.captionCues.every((cue) => cue.endOffsetFrames <= scene.durationInFrames));
    assert.ok(scene.captionCues.every((cue) => cue.startOffsetFrames < cue.endOffsetFrames));

    for (const collection of [scene.camera, scene.cursor, scene.callouts]) {
      for (const keyframe of collection) {
        assert.ok(keyframe.frame >= 0);
        assert.ok(keyframe.frame < scene.durationInFrames);
      }
    }
    expectedStart += scene.durationInFrames;
  }

  assert.equal(expectedStart, 1891);
});
