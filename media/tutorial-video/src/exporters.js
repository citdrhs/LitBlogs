const pad = (value, width = 2) => String(value).padStart(width, "0");

const formatClock = (totalSeconds) => {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  return hours > 0
    ? `${hours}:${pad(minutes)}:${pad(remainder)}`
    : `${minutes}:${pad(remainder)}`;
};

export const formatVttTimestamp = (frame, fps) => {
  const totalMilliseconds = Math.round((frame / fps) * 1000);
  const hours = Math.floor(totalMilliseconds / 3_600_000);
  const minutes = Math.floor((totalMilliseconds % 3_600_000) / 60_000);
  const seconds = Math.floor((totalMilliseconds % 60_000) / 1000);
  const milliseconds = totalMilliseconds % 1000;
  return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}.${pad(milliseconds, 3)}`;
};

export const manifestToVtt = (scenes, video) => {
  const cues = scenes.map((scene, index) => {
    const cueStart = scene.startFrame + scene.caption.startOffsetFrames;
    const cueEnd = scene.startFrame + scene.caption.endOffsetFrames;
    return [
      String(index + 1),
      `${formatVttTimestamp(cueStart, video.fps)} --> ${formatVttTimestamp(cueEnd, video.fps)}`,
      scene.caption.text,
    ].join("\n");
  });
  return `WEBVTT\n\n${cues.join("\n\n")}\n`;
};

export const manifestToPlainTranscript = (scenes, video) => {
  const chapters = scenes.map((scene) => [
    `[${formatClock(scene.startFrame / video.fps)}] ${scene.title}`,
    scene.narration,
  ].join("\n"));
  return [
    "LitBlog Student Tutorial",
    `Duration: ${formatClock(video.durationInSeconds)}`,
    "",
    chapters.join("\n\n"),
    "",
  ].join("\n");
};

export const manifestToFrontendTranscript = (scenes, video) => scenes.map((scene) => ({
  id: scene.id,
  time: formatClock(scene.startFrame / video.fps),
  heading: scene.title,
  text: scene.narration,
}));

export const manifestToFrontendModule = (scenes, video) => (
  `// Generated from media/tutorial-video/src/manifest.js. Do not edit by hand.\n\n`
  + `export const studentTutorialTranscript = ${JSON.stringify(
    manifestToFrontendTranscript(scenes, video),
    null,
    2,
  )};\n`
);
