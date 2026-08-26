import { spawnSync } from "node:child_process";

import { assertMediaTools, ffprobePath } from "./paths.mjs";

export const probeMedia = (target) => {
  assertMediaTools();
  const result = spawnSync(ffprobePath, [
    "-v", "error",
    "-show_streams",
    "-show_format",
    "-of", "json",
    target,
  ], { encoding: "utf8", windowsHide: true });
  if (result.status !== 0) {
    throw new Error(`ffprobe failed for ${target}: ${result.stderr.trim()}`);
  }
  return JSON.parse(result.stdout);
};
