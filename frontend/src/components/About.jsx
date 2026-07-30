// About page — app info & credits. Shown as a top-nav tab for regular users and
// opened from the Settings page for admins.
export default function About() {
  return (
    <div className="settings-page">
      <div className="settings-card about-card">
        <div className="about-brand">🛒 C-Bot</div>
        <p className="about-sub">Costco Warehouse 552 · Major Sales</p>

        <p className="about-body">
          <strong>C-Bot</strong> is a product-knowledge assistant created by{" "}
          <strong>Eric Zantua</strong> at <strong>Costco Wholesale — Vancouver,
          Warehouse&nbsp;552</strong>.
        </p>
        <p className="about-body">
          It maintains a searchable repository of the products carried in the{" "}
          <strong>552 Major Sales</strong> department, serving as a quick reference
          and AI-powered assistant for Major Sales employees at Warehouse&nbsp;552 —
          helping them look up product details, compare items, and answer member
          questions with confidence.
        </p>

        <p className="about-foot">Made with ❤️ for the Costco&nbsp;552 Major Sales team.</p>
      </div>
    </div>
  );
}
