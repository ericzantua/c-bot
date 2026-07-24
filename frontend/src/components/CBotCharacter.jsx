import { useEffect, useRef } from "react";
import Lottie from "lottie-react";
import animationData from "../assets/cbot.json";

// Two visual states: the character animates while TALKING and freezes (paused)
// while LISTENING. Swap src/assets/cbot.json for a different avatar — no code
// change needed. The status label lives in the bottom voice bar (ChatWindow).
export default function CBotCharacter({ state, onInterrupt }) {
  const lottieRef = useRef(null);

  useEffect(() => {
    const lottie = lottieRef.current;
    if (!lottie) return;
    if (state === "speaking") lottie.play(); // talking → animate
    else lottie.pause(); // listening / idle → freeze on the current frame
  }, [state]);

  return (
    <div className={`cbot cbot--${state}`}>
      <button
        type="button"
        className="cbot-avatar-btn"
        onClick={onInterrupt}
        title={state === "speaking" ? "Tap to interrupt" : "Tap to talk"}
        aria-label={state === "speaking" ? "Interrupt" : "Talk to C-Bot"}
      >
        <Lottie
          lottieRef={lottieRef}
          animationData={animationData}
          loop
          autoplay={false}
          className="cbot-lottie"
        />
        <span className="cbot-logo" aria-hidden="true">Major Sales</span>
      </button>
    </div>
  );
}
