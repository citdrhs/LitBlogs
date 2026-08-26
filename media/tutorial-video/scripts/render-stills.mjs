import path from "node:path";

import { bundle } from "@remotion/bundler";
import { renderStill, selectComposition } from "@remotion/renderer";

import {
  ensureDirectories,
  entryPoint,
  faqAssetsDirectory,
  tutorialAssetsDirectory,
} from "./lib/paths.mjs";

ensureDirectories(faqAssetsDirectory, tutorialAssetsDirectory);
const serveUrl = await bundle({
  entryPoint,
  onProgress: (progress) => {
    if (progress % 25 === 0) console.log(`Bundling: ${progress}%`);
  },
});

const stills = [
  ["FAQSignUp", path.join(faqAssetsDirectory, "litblogs-faq-sign-up.webp"), "webp"],
  ["FAQSignIn", path.join(faqAssetsDirectory, "litblogs-faq-sign-in.webp"), "webp"],
  ["FAQJoinClass", path.join(faqAssetsDirectory, "litblogs-faq-join-class.webp"), "webp"],
  ["FAQPostEditor", path.join(faqAssetsDirectory, "litblogs-faq-post-editor.webp"), "webp"],
  ["TutorialPoster", path.join(tutorialAssetsDirectory, "litblogs-tutorial-poster.jpg"), "jpeg"],
];

for (const [id, output, imageFormat] of stills) {
  const composition = await selectComposition({ serveUrl, id });
  await renderStill({
    serveUrl,
    composition,
    output,
    imageFormat,
    ...(imageFormat === "jpeg" ? { jpegQuality: 88 } : {}),
    overwrite: true,
    logLevel: "warn",
  });
  console.log(`Rendered ${id}: ${output}`);
}
