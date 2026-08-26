# LitBlog tutorial media

This is the editable, self-contained, development-only Remotion 4 project for the LitBlog student tutorial and FAQ guides. It owns its own exact dependencies and does not add Remotion to the Vite application or its production runtime.

## Prerequisites

- Windows with Node.js 24 and npm.
- Microsoft Zira Desktop (`en-US`) available through `System.Speech`.
- PostgreSQL 17 server binaries at `C:\Program Files\PostgreSQL\17\bin`.
- The prepared LitBlog Python environment at `C:\Users\antho\Documents\Projects\LitBlog\.venv\Scripts\python.exe`, or another compatible path supplied as `E2E_PYTHON`.
- Enough free space for Remotion's local Chrome Headless Shell and temporary render frames.

Remotion's bundled `ffmpeg.exe` and `ffprobe.exe` are used for compression and validation. A system ffmpeg installation is not required.

## Windows workflow

From the repository root in PowerShell:

```powershell
Set-Location litblogs
npm ci
npm run test:e2e:install

Set-Location ..\media\tutorial-video
npm ci

$env:E2E_DISPOSABLE_DATABASE_CONFIRMED = 'litblogs-e2e-only'
$env:E2E_PYTHON = 'C:\Users\antho\Documents\Projects\LitBlog\.venv\Scripts\python.exe'

npm test
npm run capture
npm run voice
npm run music
npm run accessibility/export
npm run poster/stills
npm run render
npm run validate
```

The first install supplies the existing LitBlog Vite and disposable-E2E harness that `capture` reuses; the second installs this package's isolated Remotion toolchain. Remotion remains absent from the application package and runtime.

`npm run build:media` runs the same regeneration sequence end to end. Use `npm run studio` to edit or scrub the video interactively. The video composition is `LitBlogsTutorial`; the four FAQ compositions are `FAQSignUp`, `FAQSignIn`, `FAQJoinClass`, and `FAQPostEditor`.

## Synthetic-data guarantee

The capture script refuses to run unless `E2E_DISPOSABLE_DATABASE_CONFIRMED` is exactly `litblogs-e2e-only`. It reuses LitBlog's disposable PostgreSQL 17 bootstrap, randomized database roles, migration path, runtime ACL checks, and teardown. It never connects to the normal development or production database.

All visible tutorial content is fixed synthetic data:

- Jordan Reader
- `student.guide@example.com`
- English 10 Reading Circle
- My Reading Reflection

Teacher credentials are generated inside the temporary harness, remain masked, are never captured, and disappear during teardown. The capture browser intercepts public runtime configuration to blank Google and Microsoft client IDs and blocks non-loopback network requests. No API key, OAuth secret, real school record, or external service is used.

The capture viewport is 1440×900 at device scale 1 in light mode. The long Sign Up form is captured at 82% browser zoom so all real fields and the real submit button fit in one 1440×900 state; no form content is replaced or mocked. Every other capture uses the normal page scale. The script fails if current labels, routes, six-character code handling, editor toolbar actions, or rendered `<strong>` and amber `<mark>` output drift.

## Asset provenance

- UI imagery: captured from the current LitBlog frontend running against the disposable local backend and database.
- LitBlog logo: copied from `litblogs/public/logo.png`, the repository's existing project artwork.
- Narration: generated locally with Microsoft Zira Desktop from the checked-in scene manifest; temporary WAV files are removed and compressed MP3 inputs are committed.
- Music: an original deterministic pad/arpeggio bed synthesized by `scripts/generate-music.mjs`; it uses no sample, remote asset, or copyrighted recording.
- Typography: local system UI fonts only. No font is downloaded at render time.

Curated captures, compressed audio, source code, the manifest, and final app assets are committed. `node_modules`, render output, temporary WAV/PCM files, raw intermediates, and caches are ignored.

## Timing and accessibility

`src/manifest.js` is the only scene, narration, caption, camera, cursor, and callout source of truth. Scene starts are derived cumulatively. The composition is fixed at 1280×720, 30fps, 3510 frames, exactly 117.0 seconds.

`npm run accessibility/export` regenerates all three synchronized text artifacts from that manifest:

- `litblogs/src/assets/tutorial/litblogs-tutorial.en.vtt`
- `litblogs/src/assets/tutorial/litblogs-tutorial-transcript.txt`
- `litblogs/src/components/tutorialTranscript.js`

`npm run validate` verifies streams, dimensions, frame rate, H.264/yuv420p/BT.709 video, AAC 48kHz audio, duration, size, fast-start MP4 box order, audio peak headroom, poster/still dimensions, VTT bounds, and transcript parity.

## Remotion license note

Remotion 4's free license covers individuals, nonprofits, and for-profit organizations with up to three employees. Larger for-profit organizations need a Company License. Review the current terms before regenerating or using this media commercially: [Remotion licensing](https://www.remotion.dev/docs/licensing) and [Remotion Company License](https://www.remotion.pro/license).
