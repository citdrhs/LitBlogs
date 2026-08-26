import React from "react";
import { Composition, Still } from "remotion";

import { FAQ_STILLS, FaqStill } from "./FaqStill.jsx";
import { TutorialPoster, TutorialVideo } from "./TutorialVideo.jsx";
import { VIDEO } from "./manifest.js";

export const RemotionRoot = () => (
  <>
    <Composition
      id={VIDEO.id}
      component={TutorialVideo}
      width={VIDEO.width}
      height={VIDEO.height}
      fps={VIDEO.fps}
      durationInFrames={VIDEO.durationInFrames}
    />
    <Still
      id="TutorialPoster"
      component={TutorialPoster}
      width={VIDEO.width}
      height={VIDEO.height}
    />
    {Object.entries(FAQ_STILLS).map(([id, props]) => (
      <Still
        key={id}
        id={id}
        component={FaqStill}
        width={1440}
        height={900}
        defaultProps={props}
      />
    ))}
  </>
);
