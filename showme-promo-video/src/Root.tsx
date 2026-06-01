import "./index.css";
import { Composition, Folder } from "remotion";
import { ShowMePromo } from "./Composition";

export const RemotionRoot = () => {
  return (
    <Folder name="Marketing">
      <Composition
        id="ShowMePromo"
        component={ShowMePromo}
        durationInFrames={720}
        fps={30}
        width={1920}
        height={1080}
      />
    </Folder>
  );
};
