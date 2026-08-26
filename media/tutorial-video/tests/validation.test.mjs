import assert from "node:assert/strict";
import test from "node:test";

const validation = await import("../src/validation.js").catch(() => ({}));

const GOOD_PROBE = {
  streams: [
    {
      codec_type: "video",
      codec_name: "h264",
      width: 1280,
      height: 720,
      pix_fmt: "yuv420p",
      avg_frame_rate: "30/1",
      color_space: "bt709",
    },
    {
      codec_type: "audio",
      codec_name: "aac",
      sample_rate: "48000",
    },
  ],
  format: {
    duration: "117.000000",
    size: "12345678",
  },
};

test("accepts the required tutorial media probe contract", () => {
  assert.deepEqual(validation.validateProbeData?.(GOOD_PROBE), []);
});

test("reports every material stream and container mismatch", () => {
  const invalid = structuredClone(GOOD_PROBE);
  invalid.streams[0] = {
    ...invalid.streams[0],
    codec_name: "hevc",
    width: 1920,
    pix_fmt: "yuv444p",
    avg_frame_rate: "30000/1001",
    color_space: "unknown",
  };
  invalid.streams[1].sample_rate = "44100";
  invalid.format.duration = "116.5";
  invalid.format.size = String(21 * 1024 * 1024);

  assert.deepEqual(validation.validateProbeData?.(invalid), [
    "expected H.264 video, received hevc",
    "expected 1280x720 video, received 1920x720",
    "expected yuv420p pixel format, received yuv444p",
    "expected 30fps video, received 30000/1001",
    "expected BT.709 color metadata, received unknown",
    "expected 48kHz AAC audio, received aac at 44100Hz",
    "expected duration within 0.1s of 117, received 116.5",
    "expected file size at most 20MiB, received 22020096 bytes",
  ]);
});

test("requires exactly one video and one audio stream", () => {
  const invalid = structuredClone(GOOD_PROBE);
  invalid.streams.push(structuredClone(invalid.streams[0]));
  assert.deepEqual(validation.validateProbeData?.(invalid), [
    "expected exactly one video stream, received 2",
  ]);
});

test("rejects missing or non-finite video frame-rate metadata", () => {
  const invalid = structuredClone(GOOD_PROBE);
  invalid.streams[0].avg_frame_rate = "0/0";
  assert.deepEqual(validation.validateProbeData?.(invalid), [
    "expected 30fps video, received 0/0",
  ]);
});

test("recognizes fast-start MP4 box order", () => {
  const fastStart = Buffer.from("....ftyp....moov....free....mdat");
  const slowStart = Buffer.from("....ftyp....mdat....moov");
  assert.equal(validation.hasFastStartMp4?.(fastStart), true);
  assert.equal(validation.hasFastStartMp4?.(slowStart), false);
});

test("bounds exported WebVTT cues to the tutorial duration", () => {
  const valid = "WEBVTT\n\n1\n00:00:00.200 --> 00:01:56.800\nText\n";
  const invalid = "WEBVTT\n\n1\n00:01:56.800 --> 00:01:57.200\nText\n";
  assert.deepEqual(validation.validateVtt?.(valid, 117), []);
  assert.deepEqual(validation.validateVtt?.(invalid, 117), [
    "caption cue 1 ends after 117 seconds",
  ]);
});

test("checks transcript narration parity independent of headings", () => {
  const scenes = [
    { id: "one", narration: "First narration." },
    { id: "two", narration: "Second narration." },
  ];
  const matching = "Title\n\n[0:00] One\nFirst narration.\n\n[0:05] Two\nSecond narration.";
  const missing = "Title\n\n[0:00] One\nFirst narration.";
  assert.deepEqual(validation.validateTranscriptParity?.(matching, scenes), []);
  assert.deepEqual(validation.validateTranscriptParity?.(missing, scenes), [
    "transcript is missing narration for scene two",
  ]);
});

test("parses ffmpeg volumedetect output and requires peak headroom", () => {
  const output = "[Parsed_volumedetect_0] mean_volume: -24.1 dB\n"
    + "[Parsed_volumedetect_0] max_volume: -1.7 dB\n";
  assert.equal(validation.parseMaxVolumeDb?.(output), -1.7);
  assert.deepEqual(validation.validateAudioPeak?.(-1.7), []);
  assert.deepEqual(validation.validateAudioPeak?.(0), [
    "audio peak 0.0 dB leaves no clipping headroom (expected at most -0.3 dB)",
  ]);
  assert.deepEqual(validation.validateAudioPeak?.(Number.NaN), [
    "ffmpeg volumedetect did not report a finite max_volume",
  ]);
});

test("parses true peak from Remotion-bundled ffmpeg loudnorm JSON", () => {
  const output = "[Parsed_loudnorm_0] {\n"
    + '  "input_i" : "-18.42",\n'
    + '  "input_tp" : "-1.24",\n'
    + '  "input_lra" : "4.10"\n'
    + "}\n";
  assert.equal(validation.parseMaxVolumeDb?.(output), -1.24);
});

test("reads dimensions from an extended WebP header when ffprobe reports 0x0", () => {
  const webp = Buffer.alloc(30);
  webp.write("RIFF", 0, "ascii");
  webp.writeUInt32LE(22, 4);
  webp.write("WEBPVP8X", 8, "ascii");
  webp.writeUInt32LE(10, 16);
  webp.writeUIntLE(1440 - 1, 24, 3);
  webp.writeUIntLE(900 - 1, 27, 3);

  assert.deepEqual(validation.readWebpDimensions?.(webp), {
    width: 1440,
    height: 900,
  });
  assert.equal(validation.readWebpDimensions?.(Buffer.from("not a webp")), null);
});
