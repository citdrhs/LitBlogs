export const VIDEO = Object.freeze({
  id: "LitBlogsTutorial",
  width: 1280,
  height: 720,
  fps: 30,
  durationInFrames: 3510,
  durationInSeconds: 117,
});

const CAPTION_INSET_FRAMES = 6;

const rawScenes = [
  {
    id: "title",
    title: "Welcome to LitBlog",
    durationInFrames: 150,
    narration: "Welcome to LitBlog. In under two minutes, you'll create an account, join a class, and publish your first post.",
    captureAsset: "captures/student-hub.jpg",
    audioAsset: "audio/title.mp3",
    camera: [
      { frame: 0, scale: 1.02, x: 0, y: 0 },
      { frame: 149, scale: 1.08, x: -18, y: -8 },
    ],
    cursor: [
      { frame: 0, x: 1070, y: 610, visible: false },
      { frame: 149, x: 1070, y: 610, visible: false },
    ],
    callouts: [
      { id: "title-path", frame: 18, endFrame: 142, number: 1, label: "Account → class → post", x: 88, y: 560 },
    ],
  },
  {
    id: "signup",
    title: "Sign up",
    durationInFrames: 690,
    narration: "Choose Sign Up. Enter your name, school email, a strong password, and choose Student. Confirm your password, then select Sign Up.",
    captureAsset: "captures/signup-filled.jpg",
    audioAsset: "audio/signup.mp3",
    camera: [
      { frame: 0, scale: 1.04, x: 0, y: 4 },
      { frame: 330, scale: 1.18, x: 185, y: -22 },
      { frame: 689, scale: 1.12, x: 178, y: -102 },
    ],
    cursor: [
      { frame: 35, x: 904, y: 287, visible: true },
      { frame: 300, x: 900, y: 555, visible: true },
      {
        frame: 520,
        x: 815,
        y: 615,
        visible: true,
        click: true,
        target: {
          label: "Sign Up",
          space: "composition",
          bounds: { left: 584, top: 602, right: 1059, bottom: 650 },
        },
      },
    ],
    callouts: [
      { id: "signup-fields", frame: 40, endFrame: 350, number: 1, label: "Use your school details", x: 52, y: 108 },
      { id: "signup-role", frame: 250, endFrame: 520, number: 2, label: "Choose Student", x: 52, y: 220 },
      { id: "signup-submit", frame: 470, endFrame: 675, number: 3, label: "Confirm, then Sign Up", x: 52, y: 332 },
    ],
  },
  {
    id: "signin",
    title: "Register and sign in",
    durationInFrames: 420,
    narration: "After registration, choose Sign In. Enter the same email and password to open your Student Hub.",
    captureAsset: "captures/registration-success.jpg",
    alternateCaptureAsset: "captures/signin-filled.jpg",
    alternateAtFrame: 150,
    audioAsset: "audio/signin.mp3",
    camera: [
      { frame: 0, scale: 1.05, x: 0, y: 0 },
      { frame: 149, scale: 1.12, x: 20, y: 4 },
      { frame: 150, scale: 1.04, x: 0, y: 0 },
      { frame: 419, scale: 1.16, x: 170, y: -50 },
    ],
    cursor: [
      {
        frame: 48,
        x: 640,
        y: 440,
        visible: true,
        click: true,
        target: {
          label: "Registration Sign In",
          space: "composition",
          bounds: { left: 476, top: 427, right: 817, bottom: 476 },
        },
      },
      { frame: 215, x: 915, y: 412, visible: true },
      {
        frame: 350,
        x: 760,
        y: 345,
        visible: true,
        click: true,
        target: {
          label: "Sign In",
          space: "composition",
          bounds: { left: 588, top: 329, right: 946, bottom: 385 },
        },
      },
    ],
    callouts: [
      { id: "registration-complete", frame: 25, endFrame: 148, number: 1, label: "Registration complete", x: 60, y: 128 },
      { id: "same-credentials", frame: 175, endFrame: 405, number: 2, label: "Use the same credentials", x: 60, y: 252 },
    ],
  },
  {
    id: "join-class",
    title: "Join a class",
    durationInFrames: 480,
    narration: "Select Join Class. Type the six-character code from your teacher, then choose Join Class again.",
    captureAsset: "captures/student-hub-empty.jpg",
    alternateCaptureAsset: "captures/join-class-code.jpg",
    alternateAtFrame: 150,
    captureObjectPosition: "center top",
    alternateCaptureObjectPosition: "center",
    audioAsset: "audio/join-class.mp3",
    camera: [
      { frame: 0, scale: 1.02, x: 0, y: 0 },
      { frame: 149, scale: 1.02, x: 0, y: 0 },
      { frame: 150, scale: 1.02, x: 0, y: 0 },
      { frame: 200, scale: 1.22, x: 4, y: 18 },
      { frame: 479, scale: 1.16, x: 4, y: 10 },
    ],
    cursor: [
      {
        frame: 34,
        x: 1165,
        y: 197,
        visible: true,
        click: true,
        target: {
          label: "Open Join Class",
          space: "composition",
          bounds: { left: 1125, top: 189, right: 1222, bottom: 223 },
        },
      },
      { frame: 220, x: 722, y: 436, visible: true },
      {
        frame: 380,
        x: 775,
        y: 468,
        visible: true,
        click: true,
        target: {
          label: "Submit Join Class",
          space: "composition",
          bounds: { left: 742, top: 460, right: 841, bottom: 499 },
        },
      },
    ],
    callouts: [
      { id: "join-open", frame: 22, endFrame: 155, number: 1, label: "Select Join Class", x: 58, y: 110 },
      { id: "join-code", frame: 150, endFrame: 345, number: 2, label: "Enter the 6-character code", x: 58, y: 222 },
      { id: "join-submit", frame: 330, endFrame: 466, number: 3, label: "Join the class", x: 58, y: 334 },
    ],
  },
  {
    id: "enter-class",
    title: "Enter the class",
    durationInFrames: 300,
    narration: "Open the class card to see announcements, assignments, and posts.",
    captureAsset: "captures/student-hub.jpg",
    alternateCaptureAsset: "captures/class-feed.jpg",
    alternateAtFrame: 122,
    audioAsset: "audio/enter-class.mp3",
    camera: [
      { frame: 0, scale: 1.04, x: 0, y: 0 },
      { frame: 121, scale: 1.18, x: -80, y: -24 },
      { frame: 122, scale: 1.02, x: 0, y: 0 },
      { frame: 299, scale: 1.09, x: 2, y: -20 },
    ],
    cursor: [
      {
        frame: 66,
        x: 330,
        y: 170,
        visible: true,
        click: true,
        target: {
          label: "English 10 Reading Circle class card",
          space: "composition",
          bounds: { left: 197, top: 115, right: 527, bottom: 273 },
        },
      },
      { frame: 170, x: 890, y: 312, visible: true },
      { frame: 285, x: 890, y: 312, visible: true },
    ],
    callouts: [
      { id: "class-card", frame: 28, endFrame: 120, number: 1, label: "Open the class card", x: 58, y: 118 },
      { id: "class-space", frame: 145, endFrame: 286, number: 2, label: "Your class workspace", x: 58, y: 238 },
    ],
  },
  {
    id: "open-post",
    title: "Open a new post",
    durationInFrames: 270,
    narration: "Select Create New Post.",
    captureAsset: "captures/class-feed.jpg",
    alternateCaptureAsset: "captures/post-composer.jpg",
    alternateAtFrame: 125,
    audioAsset: "audio/open-post.mp3",
    camera: [
      { frame: 0, scale: 1.04, x: 0, y: 0 },
      { frame: 124, scale: 1.19, x: -160, y: 40 },
      { frame: 125, scale: 1.02, x: 0, y: 0 },
      { frame: 269, scale: 1.11, x: 0, y: -25 },
    ],
    cursor: [
      { frame: 48, x: 1145, y: 202, visible: true },
      {
        frame: 95,
        x: 1000,
        y: 135,
        visible: true,
        click: true,
        target: {
          label: "Create New Post",
          space: "composition",
          bounds: { left: 943, top: 116, right: 1100, bottom: 158 },
        },
      },
      { frame: 196, x: 740, y: 250, visible: true },
    ],
    callouts: [
      { id: "create-post", frame: 25, endFrame: 118, number: 1, label: "Create New Post", x: 58, y: 125 },
      { id: "composer-ready", frame: 145, endFrame: 255, number: 2, label: "Composer ready", x: 58, y: 245 },
    ],
  },
  {
    id: "compose",
    title: "Write and format",
    durationInFrames: 750,
    narration: "Add a clear title and write your response. Select text and choose Bold. Then choose a highlight color. The editor previews exactly what classmates and teachers will see.",
    captureAsset: "captures/post-written.jpg",
    captureTimeline: [
      { frame: 0, asset: "captures/post-written.jpg" },
      { frame: 450, asset: "captures/post-bold.jpg" },
      { frame: 610, asset: "captures/post-formatted.jpg" },
    ],
    audioAsset: "audio/compose.mp3",
    camera: [
      { frame: 0, scale: 1.02, x: 0, y: 0 },
      { frame: 245, scale: 1.16, x: 0, y: -95 },
      { frame: 359, scale: 1.19, x: 6, y: -70 },
      { frame: 360, scale: 1.09, x: 0, y: -45 },
      { frame: 749, scale: 1.15, x: 0, y: -42 },
    ],
    cursor: [
      { frame: 70, x: 714, y: 286, visible: true },
      { frame: 250, x: 642, y: 485, visible: true },
      {
        frame: 430,
        x: 670,
        y: 265,
        visible: true,
        click: true,
        target: {
          label: "Bold",
          space: "composition",
          bounds: { left: 659, top: 258, right: 693, bottom: 293 },
        },
      },
      {
        frame: 590,
        x: 625,
        y: 265,
        visible: true,
        click: true,
        target: {
          label: "Amber Highlight",
          space: "composition",
          bounds: { left: 615, top: 258, right: 651, bottom: 293 },
        },
      },
    ],
    callouts: [
      { id: "clear-title", frame: 28, endFrame: 230, number: 1, label: "Add a clear title", x: 46, y: 104 },
      { id: "write-response", frame: 175, endFrame: 370, number: 2, label: "Write your response", x: 46, y: 216 },
      { id: "bold", frame: 355, endFrame: 545, number: 3, label: "Select text → Bold", x: 46, y: 328 },
      { id: "highlight", frame: 515, endFrame: 735, number: 4, label: "Choose amber Highlight", x: 46, y: 440 },
    ],
  },
  {
    id: "publish",
    title: "Publish",
    durationInFrames: 270,
    narration: "Review your work, then select Publish.",
    captureAsset: "captures/publish-action.jpg",
    captureObjectPosition: "center bottom",
    audioAsset: "audio/publish.mp3",
    camera: [
      { frame: 0, scale: 1.04, x: 0, y: -12 },
      { frame: 150, scale: 1.19, x: -90, y: -120 },
      { frame: 269, scale: 1.15, x: -82, y: -108 },
    ],
    cursor: [
      { frame: 60, x: 1080, y: 670, visible: true },
      { frame: 120, x: 930, y: 535, visible: true },
      {
        frame: 165,
        x: 915,
        y: 515,
        visible: true,
        click: true,
        target: {
          label: "Publish",
          space: "composition",
          bounds: { left: 875, top: 508, right: 973, bottom: 548 },
        },
      },
      { frame: 250, x: 1080, y: 670, visible: false },
    ],
    callouts: [
      { id: "review", frame: 24, endFrame: 138, number: 1, label: "Review your work", x: 58, y: 150 },
      { id: "publish-action", frame: 120, endFrame: 258, number: 2, label: "Select Publish", x: 58, y: 268 },
    ],
  },
  {
    id: "verify",
    title: "Verify and finish",
    durationInFrames: 180,
    narration: "Your post appears in the class feed with bold and highlighting preserved. You're ready to write on LitBlog.",
    captureAsset: "captures/published-post.jpg",
    audioAsset: "audio/verify.mp3",
    camera: [
      { frame: 0, scale: 1.03, x: 0, y: 0 },
      { frame: 179, scale: 1.13, x: 0, y: -34 },
    ],
    cursor: [
      { frame: 0, x: 880, y: 450, visible: false },
      { frame: 179, x: 880, y: 450, visible: false },
    ],
    callouts: [
      { id: "format-preserved", frame: 12, endFrame: 146, number: 1, label: "Bold + highlight preserved", x: 54, y: 132 },
      { id: "ready", frame: 64, endFrame: 175, number: 2, label: "Ready to write", x: 54, y: 246 },
    ],
  },
];

let nextStartFrame = 0;

export const SCENES = Object.freeze(rawScenes.map((scene) => {
  const startFrame = nextStartFrame;
  nextStartFrame += scene.durationInFrames;
  return Object.freeze({
    ...scene,
    startFrame,
    caption: Object.freeze({
      startOffsetFrames: CAPTION_INSET_FRAMES,
      endOffsetFrames: scene.durationInFrames - CAPTION_INSET_FRAMES,
      text: scene.narration,
    }),
  });
}));

export const SCENE_BY_ID = Object.freeze(Object.fromEntries(
  SCENES.map((scene) => [scene.id, scene]),
));
