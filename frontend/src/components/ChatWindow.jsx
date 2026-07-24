import { useCallback, useEffect, useRef, useState } from "react";
import { sendChat } from "../api";
import { LANGUAGES, bcp47For } from "../languages";
import { useVoice } from "../hooks/useVoice";
import CBotCharacter from "./CBotCharacter";
import Message from "./Message";

// Strip markdown so text-to-speech reads cleanly (no "star star", "hash", etc.).
function toSpeech(md) {
  return md
    .replace(/`([^`]+)`/g, "$1")
    .replace(/[*_`#>]/g, " ")
    .replace(/^\s*[-•]\s*/gm, "")
    .replace(/\s*\n+\s*/g, ". ")
    .replace(/\.\s*\.\s*/g, ". ")
    .replace(/\s{2,}/g, " ")
    .trim();
}

const LABELS = {
  idle: "Tap the mic or say “C-Bot” to start",
  listening: "Listening for “C-Bot”…",
  capturing: "I'm listening — go ahead",
  speaking: "Speaking… (tap the character or Listen to interrupt)",
};

const GREETING_TEXT =
  "Hi! I'm C-Bot. Ask me about any Costco product you've indexed, or ask me " +
  "to compare a few. You can type, or turn on the mic and say “C-Bot”.";

// Each message stores both language versions (foreign = selected language).
const GREETING = {
  id: 0,
  role: "assistant",
  foreign: GREETING_TEXT,
  en: GREETING_TEXT,
  citations: [],
  productNotFound: false,
};

export default function ChatWindow({ language = "en" }) {
  const [messages, setMessages] = useState([GREETING]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [convoTab, setConvoTab] = useState("foreign"); // "foreign" | "en"
  const [inputEnglish, setInputEnglish] = useState(false);
  const scrollRef = useRef(null);
  const idRef = useRef(0);
  const messagesRef = useRef(messages);
  messagesRef.current = messages;

  const bilingual = language !== "en";
  const langLabel = (LANGUAGES.find((l) => l.code === language) || {}).label || "Foreign";
  const showEn = bilingual && convoTab === "en";

  // Reset tab/toggle when returning to English.
  useEffect(() => {
    if (!bilingual) {
      setConvoTab("foreign");
      setInputEnglish(false);
    }
  }, [bilingual]);

  const send = useCallback(
    async (text) => {
      const question = text.trim();
      if (!question || busy) return;

      // History uses the foreign (selected-language) content for continuity.
      const history = messagesRef.current
        .filter((m) => m.role === "user" || m.role === "assistant")
        .slice(-10)
        .map((m) => ({ role: m.role, content: m.foreign }));

      const uid = ++idRef.current;
      setMessages((prev) => [
        ...prev,
        { id: uid, role: "user", foreign: question, en: question, citations: [] },
      ]);
      setInput("");
      setBusy(true);
      try {
        const res = await sendChat(question, history, language);
        const aid = ++idRef.current;
        setMessages((prev) =>
          prev
            .map((m) =>
              m.id === uid
                ? {
                    ...m,
                    foreign: res.question_foreign || question,
                    en: res.question_en || question,
                  }
                : m
            )
            .concat({
              id: aid,
              role: "assistant",
              foreign: res.answer,
              en: res.answer_en || res.answer,
              citations: res.citations,
              productNotFound: res.product_not_found,
            })
        );
        speakRef.current?.(toSpeech(res.answer));
      } catch (e) {
        const aid = ++idRef.current;
        const err = `⚠️ ${e.message}`;
        setMessages((prev) => [
          ...prev,
          { id: aid, role: "assistant", foreign: err, en: err, citations: [] },
        ]);
      } finally {
        setBusy(false);
      }
    },
    [busy, language]
  );

  // Voice recognizes English when "input in English" is on, else the selected language.
  const inputLang = bilingual && inputEnglish ? "en" : language;
  const voice = useVoice(send, bcp47For(inputLang));
  const speakRef = useRef(voice.speak);
  speakRef.current = voice.speak;

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy, convoTab]);

  function handleSubmit(e) {
    e.preventDefault();
    send(input);
  }

  const micLabel = voice.enabled ? "Mic on — click to turn off" : "Turn on mic";

  return (
    <main className="chat">
      <div className="chat-main">
        <section className="chat-stage">
          <CBotCharacter state={voice.state} onInterrupt={voice.triggerCapture} />
        </section>

        <section className="chat-convo">
          {bilingual && (
            <div className="convo-tabs">
              <button
                className={`convo-tab ${convoTab === "foreign" ? "convo-tab--active" : ""}`}
                onClick={() => setConvoTab("foreign")}
              >
                {langLabel}
              </button>
              <button
                className={`convo-tab ${convoTab === "en" ? "convo-tab--active" : ""}`}
                onClick={() => setConvoTab("en")}
              >
                English
              </button>
            </div>
          )}

          <div className="messages" ref={scrollRef}>
            {messages.map((m) => (
              <Message
                key={m.id}
                message={{
                  role: m.role,
                  content: showEn ? m.en : m.foreign,
                  citations: m.citations,
                  productNotFound: m.productNotFound,
                }}
              />
            ))}
            {busy && (
              <div className="msg msg--assistant">
                <div className="msg-bubble typing">
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
              </div>
            )}
          </div>

          <form className="composer" onSubmit={handleSubmit}>
            <input
              type="text"
              placeholder={
                bilingual && inputEnglish
                  ? "Type in English…"
                  : bilingual
                    ? `Type in ${langLabel}…`
                    : "Ask about a product, or compare two…"
              }
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={busy}
            />
            <button type="submit" disabled={busy || !input.trim()}>
              Send
            </button>
          </form>
        </section>
      </div>

      <footer className="voice-bar">
        <span className="voice-status">{LABELS[voice.state] || ""}</span>
        <div className="voice-controls">
          {bilingual && (
            <button
              className={`mic-btn ${inputEnglish ? "mic-btn--on" : ""}`}
              onClick={() => setInputEnglish((v) => !v)}
              title="Speak/type in English; C-Bot still answers in the selected language."
            >
              {inputEnglish ? "⌨️ Input: English" : `⌨️ Input: ${langLabel}`}
            </button>
          )}
          {voice.recognitionSupported ? (
            <>
              <button
                className={`mic-btn ${voice.enabled ? "mic-btn--on" : ""}`}
                onClick={voice.toggle}
                title={micLabel}
              >
                {voice.enabled ? "🎙️ On" : "🎤 Off"}
              </button>
              {voice.enabled && (
                <button className="talk-btn" onClick={voice.triggerCapture} title="Skip wake word">
                  Talk
                </button>
              )}
              {voice.enabled && (
                <button
                  className={`mic-btn ${voice.bargeIn ? "mic-btn--on" : ""}`}
                  onClick={voice.toggleBargeIn}
                  title="Keep the mic live while C-Bot talks so you can speak over it. Use headphones — on speakers it hears itself."
                >
                  {voice.bargeIn ? "🎧 Talk-over: on" : "🎧 Talk-over: off"}
                </button>
              )}
              {voice.state === "speaking" && (
                <button className="talk-btn" onClick={voice.cancelSpeak} title="Stop and listen">
                  Listen
                </button>
              )}
            </>
          ) : (
            <span className="hint">Voice unsupported in this browser — text chat works.</span>
          )}
        </div>
        {voice.error && <span className="voice-error">{voice.error}</span>}
      </footer>
    </main>
  );
}
