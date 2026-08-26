const EXPECTED_DURATION_SECONDS = 117;
const EXPECTED_SIZE_LIMIT_BYTES = 20 * 1024 * 1024;

const parseRate = (rate) => {
  const [numerator, denominator = "1"] = String(rate).split("/").map(Number);
  return denominator === 0 ? Number.NaN : numerator / denominator;
};

export const validateManifest = (scenes) => {
  const issues = [];
  const ids = new Set();
  let nextStart = 0;

  for (const scene of scenes) {
    if (!scene.id || ids.has(scene.id)) issues.push(`scene id ${scene.id || "<missing>"} is not unique`);
    ids.add(scene.id);
    if (scene.startFrame !== nextStart) issues.push(`scene ${scene.id} does not start contiguously`);
    if (!scene.narration?.trim()) issues.push(`scene ${scene.id} has empty narration`);
    if (!scene.caption?.text?.trim()) issues.push(`scene ${scene.id} has empty caption text`);
    if (scene.caption?.startOffsetFrames < 0
      || scene.caption?.endOffsetFrames > scene.durationInFrames
      || scene.caption?.startOffsetFrames >= scene.caption?.endOffsetFrames) {
      issues.push(`scene ${scene.id} has an out-of-bounds caption cue`);
    }
    for (const [name, keyframes] of [
      ["camera", scene.camera],
      ["cursor", scene.cursor],
      ["callout", scene.callouts],
    ]) {
      if (!Array.isArray(keyframes) || keyframes.length === 0) {
        issues.push(`scene ${scene.id} has no ${name} keyframes`);
        continue;
      }
      let previous = -1;
      for (const keyframe of keyframes) {
        if (keyframe.frame < 0 || keyframe.frame >= scene.durationInFrames) {
          issues.push(`scene ${scene.id} has an out-of-bounds ${name} keyframe`);
        }
        if (keyframe.frame < previous) issues.push(`scene ${scene.id} has unordered ${name} keyframes`);
        const offCanvasCursor = name === "cursor"
          && (keyframe.x < 13 || keyframe.x > 1248 || keyframe.y < 13 || keyframe.y > 680);
        const offCanvasCallout = name === "callout"
          && (keyframe.x < 0 || keyframe.x > 1000 || keyframe.y < 0 || keyframe.y > 660);
        if (offCanvasCursor || offCanvasCallout) {
          issues.push(`scene ${scene.id} has an off-canvas ${name} visual`);
        }
        if (name === "cursor" && keyframe.click) {
          const target = keyframe.target;
          const bounds = target?.bounds;
          const hasCompositionTarget = target?.space === "composition"
            && target?.label?.trim()
            && bounds
            && [bounds.left, bounds.top, bounds.right, bounds.bottom].every(Number.isFinite)
            && bounds.left >= 0
            && bounds.top >= 0
            && bounds.left < bounds.right
            && bounds.right <= 1280
            && bounds.top < bounds.bottom
            && bounds.bottom <= 720;
          if (!hasCompositionTarget) {
            issues.push(
              `scene ${scene.id} click at frame ${keyframe.frame} has no composition-space target`,
            );
          } else {
            const tipX = keyframe.x + 3;
            const tipY = keyframe.y + 2;
            if (tipX < bounds.left || tipX > bounds.right
              || tipY < bounds.top || tipY > bounds.bottom) {
              issues.push(
                `scene ${scene.id} click at frame ${keyframe.frame} misses target ${target.label}`,
              );
            }
          }
        }
        previous = keyframe.frame;
      }
    }
    nextStart += scene.durationInFrames;
  }

  if (nextStart !== 3510) issues.push(`manifest totals ${nextStart} frames instead of 3510`);
  const serialized = JSON.stringify(scenes);
  const emails = serialized.match(/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/g) ?? [];
  if (emails.some((email) => !email.endsWith("@example.com"))) issues.push("manifest contains a non-synthetic email address");
  if (/password\s*[:=]|bearer\s+|api[_-]?key|secret\s*[:=]/i.test(serialized)) issues.push("manifest contains secret-like text");
  return issues;
};

export const validateProbeData = (probe) => {
  const issues = [];
  const videos = probe?.streams?.filter(({ codec_type }) => codec_type === "video") ?? [];
  const audios = probe?.streams?.filter(({ codec_type }) => codec_type === "audio") ?? [];

  if (videos.length !== 1) {
    issues.push(`expected exactly one video stream, received ${videos.length}`);
  } else {
    const video = videos[0];
    if (video.codec_name !== "h264") issues.push(`expected H.264 video, received ${video.codec_name}`);
    if (video.width !== 1280 || video.height !== 720) issues.push(`expected 1280x720 video, received ${video.width}x${video.height}`);
    if (video.pix_fmt !== "yuv420p") issues.push(`expected yuv420p pixel format, received ${video.pix_fmt}`);
    const frameRate = parseRate(video.avg_frame_rate);
    if (!Number.isFinite(frameRate) || Math.abs(frameRate - 30) > 0.001) {
      issues.push(`expected 30fps video, received ${video.avg_frame_rate}`);
    }
    if (video.color_space !== "bt709") issues.push(`expected BT.709 color metadata, received ${video.color_space}`);
  }

  if (audios.length !== 1) {
    issues.push(`expected exactly one audio stream, received ${audios.length}`);
  } else {
    const audio = audios[0];
    if (audio.codec_name !== "aac" || audio.sample_rate !== "48000") {
      issues.push(`expected 48kHz AAC audio, received ${audio.codec_name} at ${audio.sample_rate}Hz`);
    }
  }

  const duration = Number(probe?.format?.duration);
  if (!Number.isFinite(duration) || Math.abs(duration - EXPECTED_DURATION_SECONDS) > 0.1) {
    issues.push(`expected duration within 0.1s of 117, received ${probe?.format?.duration}`);
  }
  const size = Number(probe?.format?.size);
  if (!Number.isFinite(size) || size > EXPECTED_SIZE_LIMIT_BYTES) {
    issues.push(`expected file size at most 20MiB, received ${probe?.format?.size} bytes`);
  }
  return issues;
};

export const hasFastStartMp4 = (buffer) => {
  const moov = buffer.indexOf(Buffer.from("moov"));
  const mdat = buffer.indexOf(Buffer.from("mdat"));
  return moov >= 0 && mdat >= 0 && moov < mdat;
};

export const readWebpDimensions = (buffer) => {
  if (!Buffer.isBuffer(buffer)
    || buffer.length < 30
    || buffer.toString("ascii", 0, 4) !== "RIFF"
    || buffer.toString("ascii", 8, 12) !== "WEBP"
    || buffer.toString("ascii", 12, 16) !== "VP8X") {
    return null;
  }

  return {
    width: buffer.readUIntLE(24, 3) + 1,
    height: buffer.readUIntLE(27, 3) + 1,
  };
};

const parseVttTimestamp = (timestamp) => {
  const match = timestamp.match(/^(\d{2}):(\d{2}):(\d{2})\.(\d{3})$/);
  if (!match) return Number.NaN;
  const [, hours, minutes, seconds, milliseconds] = match.map(Number);
  return (hours * 3600) + (minutes * 60) + seconds + (milliseconds / 1000);
};

export const validateVtt = (vtt, durationSeconds) => {
  const issues = [];
  const cuePattern = /(\d{2}:\d{2}:\d{2}\.\d{3}) --> (\d{2}:\d{2}:\d{2}\.\d{3})/g;
  let previousEnd = 0;
  let cueNumber = 0;
  for (const match of vtt.matchAll(cuePattern)) {
    cueNumber += 1;
    const start = parseVttTimestamp(match[1]);
    const end = parseVttTimestamp(match[2]);
    if (start < previousEnd) issues.push(`caption cue ${cueNumber} overlaps the previous cue`);
    if (end > durationSeconds) issues.push(`caption cue ${cueNumber} ends after ${durationSeconds} seconds`);
    if (start >= end) issues.push(`caption cue ${cueNumber} has an invalid time range`);
    previousEnd = end;
  }
  if (cueNumber === 0) issues.push("caption file contains no cues");
  return issues;
};

export const validateTranscriptParity = (transcript, scenes) => {
  const normalized = transcript.replace(/\s+/g, " ");
  return scenes
    .filter((scene) => !normalized.includes(scene.narration.replace(/\s+/g, " ")))
    .map((scene) => `transcript is missing narration for scene ${scene.id}`);
};

export const parseMaxVolumeDb = (ffmpegOutput) => {
  const output = String(ffmpegOutput);
  const match = output.match(/max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB/i)
    ?? output.match(/"input_tp"\s*:\s*"(-?\d+(?:\.\d+)?)"/i);
  return match ? Number(match[1]) : Number.NaN;
};

export const validateAudioPeak = (maxVolumeDb, maximumAllowedDb = -0.3) => {
  if (!Number.isFinite(maxVolumeDb)) {
    return ["ffmpeg volumedetect did not report a finite max_volume"];
  }
  if (maxVolumeDb > maximumAllowedDb) {
    return [
      `audio peak ${maxVolumeDb.toFixed(1)} dB leaves no clipping headroom `
      + `(expected at most ${maximumAllowedDb.toFixed(1)} dB)`,
    ];
  }
  return [];
};
