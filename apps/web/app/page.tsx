export default function HomePage() {
  return (
    <main className="app-shell">
      <section className="map-shell" aria-label="Map">
        <div className="map-label">
          <strong>Taiwan</strong>
          <p>Risk layer: off</p>
        </div>
      </section>
      <aside className="side-panel" aria-label="Risk query">
        <section className="panel-section stack">
          <label className="field">
            <span>Address</span>
            <input placeholder="Search address or landmark" />
          </label>
          <label className="field">
            <span>Radius</span>
            <select defaultValue="500">
              <option value="300">300 m</option>
              <option value="500">500 m</option>
              <option value="1000">1000 m</option>
            </select>
          </label>
          <button className="primary-action">Assess risk</button>
        </section>
        <section className="panel-section">
          <strong>Risk</strong>
          <p>Unknown</p>
        </section>
        <section className="panel-section">
          <strong>Evidence</strong>
          <p>No evidence loaded.</p>
        </section>
      </aside>
    </main>
  );
}
