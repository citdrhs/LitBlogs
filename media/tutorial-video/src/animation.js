export const CLICK_HOLD_FRAMES = 12;

export const expandClickHolds = (keyframes, holdFrames = CLICK_HOLD_FRAMES) => {
  const expanded = [];

  keyframes.forEach((keyframe, index) => {
    expanded.push(keyframe);
    if (!keyframe.click) return;

    const holdFrame = keyframe.frame + holdFrames;
    const nextFrame = keyframes[index + 1]?.frame ?? Number.POSITIVE_INFINITY;
    if (holdFrame >= nextFrame) return;

    expanded.push({
      frame: holdFrame,
      x: keyframe.x,
      y: keyframe.y,
      visible: keyframe.visible,
      clickHold: true,
    });
  });

  return expanded;
};

export const clickPulseAtFrame = (
  frame,
  keyframes,
  holdFrames = CLICK_HOLD_FRAMES,
) => {
  const click = keyframes.find((keyframe) => (
    keyframe.click
    && frame >= keyframe.frame
    && frame <= keyframe.frame + holdFrames
  ));
  if (!click) return 0;
  return Math.max(0, 1 - ((frame - click.frame) / holdFrames));
};
