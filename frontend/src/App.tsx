import { useEffect, useState } from "react";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export default function App() {
  const [health, setHealth] = useState<string>("checking...");

  useEffect(() => {
    fetch(`${API_BASE_URL}/health`)
      .then((res) => (res.ok ? res.json() : Promise.reject(res.statusText)))
      .then((data) => setHealth(JSON.stringify(data)))
      .catch((err) => setHealth(`unreachable: ${err}`));
  }, []);

  return (
    <main style={{ fontFamily: "sans-serif", padding: "2rem" }}>
      <h1>Finsight</h1>
      <p>Phase 1 foundation. Dashboards land in Phase 7.</p>
      <p>Backend health: {health}</p>
    </main>
  );
}
