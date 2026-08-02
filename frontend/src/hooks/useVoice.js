import { useCallback, useEffect, useRef, useState } from "react";
import { ttsSynthesize } from "../api";

// Wake-word variants — "C-bot" is pronounced "see-bot".
const WAKE_PATTERNS = [
  "c-bot",
  "cbot",
  "see bot",
  "seabot",
  "sea bot",
  "c bot",
  "seebot",
  "see-bot",
];

// After a reply we keep listening for a follow-up (no wake word); this much
// silence returns to wake-word standby.
const CONVO_SILENCE_MS = 15000;
// Ignore recognition results for a moment after the bot stops talking, so the
// tail of its own audio isn't picked up as the user's next command.
const POST_SPEECH_COOLDOWN_MS = 800;
// Tiny silent clip used to unlock audio playback on the mic-tap gesture.
const SILENT_WAV =
  "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAgD4AAAB9AAACABAAZGF0YQAAAAA=";

const SpeechRecognition =
  typeof window !== "undefined" &&
  (window.SpeechRecognition || window.webkitSpeechRecognition);

const speechSupported =
  typeof window !== "undefined" && "speechSynthesis" in window;

// Warm the voice list (Chrome loads it async).
if (speechSupported) {
  try {
    window.speechSynthesis.getVoices();
    window.speechSynthesis.onvoiceschanged = () => window.speechSynthesis.getVoices();
  } catch {
    /* ignore */
  }
}

// Pick the best-sounding system voice for a locale (used when cloud TTS is
// unavailable). Prefers natural/premium/enhanced/network voices.
function pickBestVoice(lang) {
  if (!speechSupported) return null;
  const voices = window.speechSynthesis.getVoices();
  if (!voices.length) return null;
  const base = (lang || "en").slice(0, 2).toLowerCase();
  const inLang = voices.filter((v) => (v.lang || "").toLowerCase().startsWith(base));
  const pool = inLang.length ? inLang : voices;
  const prefer = ["natural", "premium", "enhanced", "neural", "google", "siri", "samantha"];
  let best = null;
  let bestScore = -1;
  for (const v of pool) {
    const n = `${v.name} ${v.lang}`.toLowerCase();
    let score = 0;
    prefer.forEach((k, i) => {
      if (n.includes(k)) score += prefer.length - i;
    });
    if (v.localService === false) score += 1; // network voices are often better
    if (score > bestScore) {
      bestScore = score;
      best = v;
    }
  }
  return best;
}

function containsWakeWord(text) {
  const lower = text.toLowerCase();
  return WAKE_PATTERNS.some((p) => lower.includes(p));
}

function stripWakeWord(text) {
  const lower = text.toLowerCase();
  let cut = -1;
  let matchLen = 0;
  for (const p of WAKE_PATTERNS) {
    const idx = lower.indexOf(p);
    if (idx !== -1 && (cut === -1 || idx < cut)) {
      cut = idx;
      matchLen = p.length;
    }
  }
  if (cut === -1) return text.trim();
  return text.slice(cut + matchLen).replace(/^[\s,.:-]+/, "").trim();
}

// Heuristic echo guard for talk-over mode: treat heard text as the bot's own
// audio unless it contains words the bot did NOT just say.
function isLikelyEcho(heard, spoken) {
  if (!spoken) return false;
  const hw = heard.toLowerCase().replace(/[^\w\s]/g, "").split(/\s+/).filter(Boolean);
  if (!hw.length) return true;
  if (WAKE_PATTERNS.some((p) => heard.toLowerCase().includes(p))) return false;
  const sw = new Set(spoken.toLowerCase().replace(/[^\w\s]/g, "").split(/\s+/));
  const novel = hw.filter((w) => !sw.has(w));
  return novel.length < Math.max(1, Math.ceil(hw.length * 0.4));
}

function playChime() {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.type = "sine";
    osc.frequency.setValueAtTime(660, ctx.currentTime);
    osc.frequency.setValueAtTime(880, ctx.currentTime + 0.1);
    gain.gain.setValueAtTime(0.15, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.3);
    osc.start();
    osc.stop(ctx.currentTime + 0.3);
    osc.onended = () => ctx.close();
  } catch {
    /* audio unavailable */
  }
}

/**
 * Conversational voice hook.
 *
 * The recognizer stays running the whole time the mic is on (it is never
 * stopped mid-session — that previously left it deaf). While the bot speaks we
 * simply ignore results (half-duplex, no self-interrupt); in talk-over mode we
 * allow voice barge-in. Audio playback is unlocked on the mic tap so
 * voice-triggered ElevenLabs replies aren't blocked by autoplay policy.
 */
export function useVoice(onPrompt, lang = "en-CA") {
  const [enabled, setEnabled] = useState(false);
  const [state, setState] = useState("idle");
  const [error, setError] = useState("");
  const [debug, setDebug] = useState("");
  const [bargeIn, setBargeInState] = useState(false);

  const recogRef = useRef(null);
  const enabledRef = useRef(false);
  const modeRef = useRef("wake"); // "wake" | "convo"
  const speakingRef = useRef(false);
  const spokenTextRef = useRef("");
  const cooldownUntilRef = useRef(0);
  const audioElRef = useRef(null); // single, gesture-unlocked <audio>
  const curUrlRef = useRef(null);
  const silenceTimerRef = useRef(null);
  const bargeInRef = useRef(false);
  const langRef = useRef(lang);
  langRef.current = lang;
  // Actual speech-recognition locale. Starts as the selected language but falls
  // back to English if the device's dictation doesn't include that language
  // (common on phones — only the languages you've added are available).
  const sttLangRef = useRef(lang);
  const onPromptRef = useRef(onPrompt);
  onPromptRef.current = onPrompt;

  const recognitionSupported = Boolean(SpeechRecognition);
  const now = () => (typeof performance !== "undefined" ? performance.now() : Date.now());

  const clearSilenceTimer = useCallback(() => {
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
  }, []);

  const armSilenceTimer = useCallback(() => {
    clearSilenceTimer();
    silenceTimerRef.current = setTimeout(() => {
      if (enabledRef.current && !speakingRef.current) {
        modeRef.current = "wake";
        setState("listening");
      }
    }, CONVO_SILENCE_MS);
  }, [clearSilenceTimer]);

  const stopAudio = useCallback(() => {
    const el = audioElRef.current;
    if (el) {
      try {
        el.pause();
        el.removeAttribute("src");
        el.load();
      } catch {
        /* ignore */
      }
    }
    if (curUrlRef.current) {
      URL.revokeObjectURL(curUrlRef.current);
      curUrlRef.current = null;
    }
    if (speechSupported) window.speechSynthesis.cancel();
    speakingRef.current = false;
    spokenTextRef.current = "";
  }, []);

  const submitCommand = useCallback(
    (text) => {
      modeRef.current = "convo";
      clearSilenceTimer();
      setState("capturing");
      if (text) onPromptRef.current?.(text);
    },
    [clearSilenceTimer]
  );

  const startRecognition = useCallback(() => {
    if (!recognitionSupported) return;
    if (recogRef.current) {
      try {
        recogRef.current.abort();
      } catch {
        /* ignore */
      }
    }
    const recog = new SpeechRecognition();
    recog.lang = sttLangRef.current || "en-CA";
    recog.continuous = true;
    recog.interimResults = true;
    recogRef.current = recog;

    recog.onstart = () => setDebug("recognition started…");
    recog.onaudiostart = () => setDebug("mic OK — capturing audio");
    recog.onspeechstart = () => setDebug("speech detected…");

    recog.onresult = (event) => {
      let finalText = "";
      let interimText = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const res = event.results[i];
        if (res.isFinal) finalText += res[0].transcript;
        else interimText += res[0].transcript;
      }
      finalText = finalText.trim();
      const heard = `${interimText} ${finalText}`.trim();
      if (!heard) return;
      setDebug(`heard: "${heard}" (mode=${modeRef.current})`);

      // While the bot is talking:
      if (speakingRef.current) {
        if (!bargeInRef.current) return; // half-duplex: ignore (no self-interrupt)
        if (isLikelyEcho(heard, spokenTextRef.current)) return;
        stopAudio(); // talk-over barge-in
        modeRef.current = "convo";
        setState("capturing");
        if (finalText) submitCommand(stripWakeWord(finalText));
        return;
      }

      // Just after the bot stops, ignore the tail of its own audio.
      if (now() < cooldownUntilRef.current) return;

      if (!finalText) return;

      if (modeRef.current === "convo") {
        submitCommand(stripWakeWord(finalText));
        return;
      }
      // wake-word standby
      if (containsWakeWord(finalText)) {
        modeRef.current = "convo";
        playChime();
        setState("capturing");
        const remainder = stripWakeWord(finalText);
        if (remainder) submitCommand(remainder);
        else armSilenceTimer();
      }
    };

    recog.onerror = (event) => {
      setDebug(`error: ${event.error}`);
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        setError("Microphone permission denied. Voice is off; text chat still works.");
        stop();
      } else if (event.error === "language-not-supported") {
        // The device's dictation doesn't include the selected language (e.g. a
        // phone only supports the languages you've added). Fall back to English
        // input so Talk still works — the reply still comes back in the selected
        // language via the bilingual path.
        if ((sttLangRef.current || "").slice(0, 2).toLowerCase() !== "en") {
          sttLangRef.current = "en-US";
          setError(
            "Your device can't listen in that language — switched voice input to English. " +
              "Add the language in your device's keyboard/dictation settings, or use the " +
              "“⌨️ Input” toggle. (You'll still get answers in the selected language.)"
          );
          startRecognition();
        } else {
          setError("Speech recognition isn't available on this device/browser.");
        }
      } else if (event.error !== "no-speech" && event.error !== "aborted") {
        setError(`Speech recognition: ${event.error}`);
      }
    };

    recog.onend = () => {
      // Always restart while enabled — the recognizer must never go deaf. The
      // identity check stops a replaced recognizer from spawning a zombie.
      if (enabledRef.current && recogRef.current === recog) {
        try {
          recog.start();
        } catch {
          /* already starting */
        }
      }
    };

    try {
      recog.start();
    } catch {
      /* already started */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recognitionSupported, stopAudio, submitCommand, armSilenceTimer]);

  const stop = useCallback(() => {
    enabledRef.current = false;
    modeRef.current = "wake";
    clearSilenceTimer();
    setEnabled(false);
    stopAudio();
    setState("idle");
    if (recogRef.current) {
      try {
        recogRef.current.abort();
      } catch {
        /* ignore */
      }
      recogRef.current = null;
    }
  }, [stopAudio, clearSilenceTimer]);

  // Unlock <audio> playback within the user gesture that turns the mic on.
  const unlockAudio = useCallback(() => {
    if (!audioElRef.current) audioElRef.current = new Audio();
    const el = audioElRef.current;
    try {
      el.src = SILENT_WAV;
      el.play().then(() => el.pause()).catch(() => {});
    } catch {
      /* ignore */
    }
  }, []);

  const start = useCallback(() => {
    if (!recognitionSupported) {
      setError("This browser doesn't support speech recognition. Text chat still works.");
      return;
    }
    setError("");
    unlockAudio();
    enabledRef.current = true;
    modeRef.current = "wake";
    setEnabled(true);
    setState("listening");
    startRecognition();
  }, [recognitionSupported, startRecognition, unlockAudio]);

  const toggle = useCallback(() => {
    if (enabledRef.current) stop();
    else start();
  }, [start, stop]);

  // Tap the avatar / "Talk now": interrupt and listen immediately.
  const triggerCapture = useCallback(() => {
    unlockAudio();
    if (!enabledRef.current) {
      start();
    }
    stopAudio();
    modeRef.current = "convo";
    playChime();
    setState("capturing");
  }, [start, stopAudio, unlockAudio]);

  const toggleBargeIn = useCallback(() => {
    const next = !bargeInRef.current;
    bargeInRef.current = next;
    setBargeInState(next);
  }, []);

  const afterSpeaking = useCallback(() => {
    speakingRef.current = false;
    spokenTextRef.current = "";
    cooldownUntilRef.current = now() + POST_SPEECH_COOLDOWN_MS;
    setState(enabledRef.current ? "capturing" : "idle");
    if (enabledRef.current) {
      armSilenceTimer();
      startRecognition(); // fresh recognizer → discard the bot's own audio buffer
    }
  }, [armSilenceTimer, startRecognition]);

  const speakFallback = useCallback(
    (text) => {
      if (!speechSupported) return afterSpeaking();
      window.speechSynthesis.cancel();
      const utter = new SpeechSynthesisUtterance(text);
      utter.lang = langRef.current || "en-CA";
      const voice = pickBestVoice(utter.lang);
      if (voice) utter.voice = voice;
      utter.onstart = () => {
        if (speakingRef.current) setState("speaking");
      };
      utter.onend = afterSpeaking;
      utter.onerror = afterSpeaking;
      window.speechSynthesis.speak(utter);
    },
    [afterSpeaking]
  );

  const speak = useCallback(
    async (text) => {
      if (!text) return;
      stopAudio();
      clearSilenceTimer();
      speakingRef.current = true; // half-duplex: ignore mic while preparing/speaking
      spokenTextRef.current = text;
      // Don't switch to the "speaking" animation yet — wait for audio to actually
      // start (onplaying), so the mouth doesn't move silently during the fetch.
      try {
        const blob = await ttsSynthesize(text);
        if (!speakingRef.current) return; // interrupted while fetching
        if (!audioElRef.current) audioElRef.current = new Audio();
        const el = audioElRef.current;
        const url = URL.createObjectURL(blob);
        curUrlRef.current = url;
        el.src = url;
        el.onplaying = () => {
          if (speakingRef.current) setState("speaking");
        };
        el.onended = afterSpeaking;
        el.onerror = afterSpeaking;
        await el.play(); // throws if autoplay-blocked → caught below
      } catch (err) {
        // "__browser__" = intentional browser-voice mode; no error banner.
        if (err.message !== "__browser__") {
          setError((e) => e || `Voice: ${err.message} — using browser speech.`);
        }
        speakFallback(text);
      }
    },
    [stopAudio, clearSilenceTimer, speakFallback, afterSpeaking]
  );

  const cancelSpeak = useCallback(() => {
    stopAudio();
    cooldownUntilRef.current = now() + POST_SPEECH_COOLDOWN_MS;
    setState(enabledRef.current ? "capturing" : "idle");
    if (enabledRef.current) {
      armSilenceTimer();
      startRecognition(); // flush the recognizer so Stop doesn't submit the bot's words
    }
  }, [stopAudio, armSilenceTimer, startRecognition]);

  // Re-apply the recognition locale when the language changes (retry the native
  // locale — the previous language may have fallen back to English).
  useEffect(() => {
    sttLangRef.current = lang;
    if (enabledRef.current && !speakingRef.current) startRecognition();
  }, [lang, startRecognition]);

  useEffect(() => {
    return () => {
      enabledRef.current = false;
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
      if (recogRef.current) {
        try {
          recogRef.current.abort();
        } catch {
          /* ignore */
        }
      }
      if (speechSupported) window.speechSynthesis.cancel();
      if (audioElRef.current) {
        try {
          audioElRef.current.pause();
        } catch {
          /* ignore */
        }
      }
    };
  }, []);

  return {
    recognitionSupported,
    speechSupported,
    enabled,
    state,
    error,
    debug,
    bargeIn,
    toggleBargeIn,
    toggle,
    triggerCapture,
    speak,
    cancelSpeak,
  };
}
