// A single chat bubble. Assistant messages may carry citation chips and an
// optional "not found" ingestion prompt.
export default function Message({ message }) {
  const { role, content, citations, productNotFound } = message;
  return (
    <div className={`msg msg--${role}`}>
      <div className="msg-bubble">
        {content}
        {productNotFound && (
          <div className="msg-notfound">
            💡 That product isn't indexed yet — add its item code in the sidebar
            (or reply with the number) and I'll fetch it.
          </div>
        )}
      </div>
      {citations && citations.length > 0 && (
        <div className="citations">
          <span className="citations-label">Sources:</span>
          {citations.map((c) => (
            <span key={c.item_code} className="chip" title={`Item #${c.item_code}`}>
              {c.title || `#${c.item_code}`}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
