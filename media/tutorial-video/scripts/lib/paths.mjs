import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const packageDirectory = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
export const repositoryDirectory = path.resolve(packageDirectory, "..", "..");
export const appDirectory = path.join(repositoryDirectory, "litblogs");
export const publicDirectory = path.join(packageDirectory, "public");
export const outputDirectory = path.join(packageDirectory, "out");
export const tempDirectory = path.join(packageDirectory, "temp");
export const tutorialAssetsDirectory = path.join(appDirectory, "src", "assets", "tutorial");
export const faqAssetsDirectory = path.join(appDirectory, "src", "assets", "faq");
export const entryPoint = path.join(packageDirectory, "src", "index.jsx");

const compositorPackage = path.join(
  packageDirectory,
  "node_modules",
  "@remotion",
  "compositor-win32-x64-msvc",
);

export const ffmpegPath = process.platform === "win32"
  ? path.join(compositorPackage, "ffmpeg.exe")
  : "ffmpeg";
export const ffprobePath = process.platform === "win32"
  ? path.join(compositorPackage, "ffprobe.exe")
  : "ffprobe";

export const ensureDirectories = (...directories) => {
  for (const directory of directories) fs.mkdirSync(directory, { recursive: true });
};

export const assertMediaTools = () => {
  for (const executable of [ffmpegPath, ffprobePath]) {
    if (process.platform === "win32" && !fs.existsSync(executable)) {
      throw new Error(`Remotion-bundled media executable is missing: ${executable}`);
    }
  }
};
