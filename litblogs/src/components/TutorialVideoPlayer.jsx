import { useEffect, useRef, useState } from "react";
import {
  FaClosedCaptioning,
  FaCompress,
  FaExpand,
  FaPause,
  FaPlay,
  FaVolumeHigh,
  FaVolumeXmark,
} from "react-icons/fa6";
import "../styles/tutorial-video-player.css";

const isInteractiveTarget = (target) => target instanceof Element && Boolean(
  target.closest("a, button, input, select, summary, textarea, [contenteditable='true']"),
);

const clamp = (value, minimum, maximum) => Math.min(maximum, Math.max(minimum, value));
const safeDuration = (value) => Number.isFinite(value) && value > 0 ? value : 0;
const PLAYBACK_START_ERROR = "Playback could not start. Please try again. The transcript remains available below.";

const formatTime = (value) => {
  const totalSeconds = Number.isFinite(value) && value > 0 ? Math.floor(value) : 0;
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const minuteText = hours > 0 ? String(minutes).padStart(2, "0") : String(minutes);
  const baseTime = `${minuteText}:${String(seconds).padStart(2, "0")}`;
  return hours > 0 ? `${hours}:${baseTime}` : baseTime;
};

const TutorialVideoPlayer = ({
  videoSrc,
  posterSrc,
  captionsSrc,
  transcriptSrc,
  transcript,
  title = "LitBlog student tutorial",
}) => {
  const videoRef = useRef(null);
  const playerRef = useRef(null);
  const captionPreferenceRef = useRef(true);
  const lastAudibleVolumeRef = useRef(1);
  const [isPlaying, setIsPlaying] = useState(false);
  const [captionsEnabled, setCaptionsEnabled] = useState(true);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [fullscreenSupported, setFullscreenSupported] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(1);
  const [isMuted, setIsMuted] = useState(false);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [mediaError, setMediaError] = useState(false);
  const [playbackError, setPlaybackError] = useState("");

  useEffect(() => {
    setFullscreenSupported(
      typeof playerRef.current?.requestFullscreen === "function"
        && typeof document.exitFullscreen === "function",
    );

    const syncFullscreenState = () => {
      setIsFullscreen(document.fullscreenElement === playerRef.current);
    };

    document.addEventListener("fullscreenchange", syncFullscreenState);
    return () => document.removeEventListener("fullscreenchange", syncFullscreenState);
  }, []);

  const togglePlay = () => {
    const video = videoRef.current;
    if (!video) return;

    if (isPlaying) {
      video.pause();
      return;
    }

    setPlaybackError("");
    try {
      const playRequest = video.play();
      playRequest?.catch(() => setPlaybackError(PLAYBACK_START_ERROR));
    } catch {
      setPlaybackError(PLAYBACK_START_ERROR);
    }
  };

  const syncTime = () => {
    const video = videoRef.current;
    if (!video) return;
    const mediaDuration = safeDuration(video.duration);
    const mediaTime = Number.isFinite(video.currentTime) ? video.currentTime : 0;
    setCurrentTime(clamp(mediaTime, 0, mediaDuration));
  };

  const syncDuration = () => {
    setDuration(safeDuration(videoRef.current?.duration));
  };

  const syncVolume = () => {
    const video = videoRef.current;
    if (!video) return;
    const mediaVolume = clamp(Number.isFinite(video.volume) ? video.volume : 1, 0, 1);
    if (mediaVolume > 0) lastAudibleVolumeRef.current = mediaVolume;
    setVolume(mediaVolume);
    setIsMuted(video.muted || mediaVolume === 0);
  };

  const syncPlaybackRate = () => {
    const mediaRate = videoRef.current?.playbackRate;
    setPlaybackRate(Number.isFinite(mediaRate) && mediaRate > 0 ? mediaRate : 1);
  };

  const seekTo = (requestedTime) => {
    const video = videoRef.current;
    if (!video) return;
    const nextTime = clamp(Number.isFinite(requestedTime) ? requestedTime : 0, 0, safeDuration(video.duration));
    video.currentTime = nextTime;
    syncTime();
  };

  const changeVolume = (requestedVolume) => {
    const video = videoRef.current;
    if (!video) return;
    const nextVolume = clamp(Number.isFinite(requestedVolume) ? requestedVolume : 0, 0, 1);
    video.volume = nextVolume;
    video.muted = nextVolume === 0;
    syncVolume();
  };

  const toggleMute = () => {
    const video = videoRef.current;
    if (!video) return;
    if (video.muted || video.volume === 0) {
      video.muted = false;
      if (video.volume === 0) video.volume = lastAudibleVolumeRef.current;
    } else {
      lastAudibleVolumeRef.current = video.volume;
      video.muted = true;
    }
    syncVolume();
  };

  const syncCaptionTrack = () => {
    const captionTrack = videoRef.current?.textTracks?.[0];
    if (!captionTrack) return;

    captionTrack.mode = captionPreferenceRef.current ? "showing" : "disabled";
    setCaptionsEnabled(captionTrack.mode === "showing");
  };

  const toggleCaptions = () => {
    captionPreferenceRef.current = !captionPreferenceRef.current;
    const captionTrack = videoRef.current?.textTracks?.[0];
    if (captionTrack) {
      captionTrack.mode = captionPreferenceRef.current ? "showing" : "disabled";
      setCaptionsEnabled(captionTrack.mode === "showing");
    } else {
      setCaptionsEnabled(captionPreferenceRef.current);
    }
  };

  const toggleFullscreen = () => {
    if (!fullscreenSupported) return;

    try {
      const fullscreenRequest = document.fullscreenElement
        ? document.exitFullscreen?.()
        : playerRef.current?.requestFullscreen?.();
      fullscreenRequest?.catch(() => {});
    } catch {
      // Fullscreen can be blocked by browser policy; the player remains usable.
    }
  };

  const handleLoadedMetadata = () => {
    syncCaptionTrack();
    syncDuration();
    syncTime();
    syncVolume();
    syncPlaybackRate();
  };

  const handleKeyDown = (event) => {
    if (mediaError || isInteractiveTarget(event.target)) return;
    const key = event.key.toLowerCase();
    let handled = true;

    switch (key) {
      case " ":
      case "k":
        togglePlay();
        break;
      case "m":
        toggleMute();
        break;
      case "f":
        if (fullscreenSupported) {
          toggleFullscreen();
        } else {
          handled = false;
        }
        break;
      case "arrowleft":
        seekTo((videoRef.current?.currentTime || 0) - 5);
        break;
      case "arrowright":
        seekTo((videoRef.current?.currentTime || 0) + 5);
        break;
      case "arrowup":
        changeVolume((videoRef.current?.volume || 0) + 0.1);
        break;
      case "arrowdown":
        changeVolume((videoRef.current?.volume || 0) - 0.1);
        break;
      default:
        handled = false;
    }

    if (handled) event.preventDefault();
  };

  return (
    <section
      ref={playerRef}
      className="tutorial-video-player"
      aria-label={`${title} player. Keyboard shortcuts: Space or K play and pause, M mute, ${fullscreenSupported ? "F fullscreen, " : ""}arrow keys seek and change volume.`}
      tabIndex={0}
      onKeyDown={handleKeyDown}
    >
      <div className="tutorial-video-player__frame">
        <div className="tutorial-video-player__viewport">
          <video
            ref={videoRef}
            aria-label={title}
            className="tutorial-video-player__video"
            hidden={mediaError}
            poster={posterSrc}
            preload="metadata"
            playsInline
            onLoadedMetadata={handleLoadedMetadata}
            onDurationChange={syncDuration}
            onTimeUpdate={syncTime}
            onVolumeChange={syncVolume}
            onRateChange={syncPlaybackRate}
            onPlay={() => {
              setIsPlaying(true);
              setPlaybackError("");
            }}
            onPause={() => setIsPlaying(false)}
            onEnded={() => setIsPlaying(false)}
            onCanPlay={() => {
              setMediaError(false);
              setPlaybackError("");
            }}
            onError={() => {
              setIsPlaying(false);
              setMediaError(true);
              setPlaybackError("");
            }}
          >
            <source src={videoSrc} type="video/mp4" />
            <track
              src={captionsSrc}
              kind="captions"
              srcLang="en"
              label="English"
              default
            />
            Your browser does not support HTML video. You can use the transcript below instead.
          </video>

          {mediaError ? (
            <div
              className="tutorial-video-player__fallback"
              role="alert"
            >
              <p className="tutorial-video-player__fallback-title">The tutorial video is not available right now.</p>
              <p>The written walkthrough is open below, so you can still follow every step.</p>
              <a className="tutorial-video-player__fallback-link" href={transcriptSrc} download>
                Download transcript
              </a>
            </div>
          ) : !isPlaying && (
            <button
              type="button"
              className="tutorial-video-player__overlay-play"
              aria-label="Play tutorial"
              title="Play tutorial (Space or K)"
              onClick={togglePlay}
            >
              <FaPlay aria-hidden="true" focusable="false" />
            </button>
          )}
        </div>

        {!mediaError && <div className="tutorial-video-player__controls">
          <input
            className="tutorial-video-player__seek"
            type="range"
            min="0"
            max={duration}
            step="0.1"
            value={currentTime}
            aria-label="Seek video"
            aria-valuetext={`${formatTime(currentTime)} of ${formatTime(duration)}`}
            title="Seek video (Left or Right arrow)"
            onChange={(event) => seekTo(Number(event.target.value))}
          />

          <div className="tutorial-video-player__control-row">
            <button
              type="button"
              className="tutorial-video-player__button"
              aria-label={isPlaying ? "Pause" : "Play"}
              title={isPlaying ? "Pause (Space or K)" : "Play (Space or K)"}
              onClick={togglePlay}
            >
              {isPlaying
                ? <FaPause aria-hidden="true" focusable="false" />
                : <FaPlay aria-hidden="true" focusable="false" />}
            </button>
            <button
              type="button"
              className="tutorial-video-player__button"
              aria-label={isMuted ? "Unmute" : "Mute"}
              title={isMuted ? "Unmute (M)" : "Mute (M)"}
              onClick={toggleMute}
            >
              {isMuted
                ? <FaVolumeXmark aria-hidden="true" focusable="false" />
                : <FaVolumeHigh aria-hidden="true" focusable="false" />}
            </button>
            <input
              className="tutorial-video-player__volume"
              type="range"
              min="0"
              max="1"
              step="0.01"
              value={volume}
              aria-label="Volume"
              aria-valuetext={`${Math.round(volume * 100)}%`}
              title="Volume (Up or Down arrow)"
              onChange={(event) => changeVolume(Number(event.target.value))}
            />
            <span className="tutorial-video-player__time" aria-live="off">
              {formatTime(currentTime)} / {formatTime(duration)}
            </span>
            <button
              type="button"
              className="tutorial-video-player__button tutorial-video-player__cc"
              aria-label={captionsEnabled ? "Turn captions off" : "Turn captions on"}
              aria-pressed={captionsEnabled}
              title={captionsEnabled ? "Turn captions off" : "Turn captions on"}
              onClick={toggleCaptions}
            >
              <FaClosedCaptioning aria-hidden="true" focusable="false" />
            </button>
            <label className="tutorial-video-player__speed-label">
              <span className="sr-only">Playback speed</span>
              <select
                className="tutorial-video-player__speed"
                aria-label="Playback speed"
                title="Playback speed"
                value={String(playbackRate)}
                onChange={(event) => {
                  const video = videoRef.current;
                  if (!video) return;
                  video.playbackRate = Number(event.target.value);
                  syncPlaybackRate();
                }}
              >
                {[0.5, 0.75, 1, 1.25, 1.5, 1.75, 2].map((speed) => (
                  <option key={speed} value={speed}>{speed}x</option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="tutorial-video-player__button tutorial-video-player__fullscreen"
              aria-label={fullscreenSupported
                ? (isFullscreen ? "Exit fullscreen" : "Enter fullscreen")
                : "Fullscreen unavailable"}
              title={fullscreenSupported
                ? (isFullscreen ? "Exit fullscreen (F)" : "Enter fullscreen (F)")
                : "Fullscreen is not supported by this browser"}
              disabled={!fullscreenSupported}
              onClick={toggleFullscreen}
            >
              {isFullscreen
                ? <FaCompress aria-hidden="true" focusable="false" />
                : <FaExpand aria-hidden="true" focusable="false" />}
            </button>
          </div>
        </div>}
      </div>

      {playbackError && (
        <p className="tutorial-video-player__playback-status" role="status">
          {playbackError}
        </p>
      )}

      <details open={mediaError || undefined} className="tutorial-video-player__transcript">
        <summary className="tutorial-video-player__transcript-summary">Read tutorial transcript</summary>
        <ol className="tutorial-video-player__transcript-list">
          {transcript.map((entry) => (
            <li key={entry.id}>
              <p className="tutorial-video-player__transcript-heading">
                <span className="tutorial-video-player__timestamp">{entry.time}</span>
                {entry.heading}
              </p>
              <p className="tutorial-video-player__transcript-copy">{entry.text}</p>
            </li>
          ))}
        </ol>
        <a className="tutorial-video-player__download" href={transcriptSrc} download>
          Download transcript
        </a>
      </details>
    </section>
  );
};

export default TutorialVideoPlayer;
