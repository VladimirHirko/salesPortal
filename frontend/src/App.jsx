import { useEffect, useState } from "react";
import HomeHotelsScreen from "./screens/HomeHotelsScreen.jsx";

export default function App() {
  const [health, setHealth] = useState("…");

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch("/api/health/");
        const ct = res.headers.get("content-type") || "";
        const data = ct.includes("application/json")
          ? await res.json()
          : await res.text(); // покажем текст, если вдруг HTML
        setHealth(typeof data === "string" ? data : JSON.stringify(data));
      } catch (e) {
        setHealth("error: " + e.message);
      }
    })();
  }, []);

  return (
    <div style={{ padding: 16, fontFamily: "system-ui" }}>
      <h1>SalesPortal Frontend</h1>
      <div>Backend health: {health}</div>
    </div>
  );
}
