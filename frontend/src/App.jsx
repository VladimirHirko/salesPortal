// frontend/src/App.jsx
import { useEffect, useState } from "react";
import HomeHotelsScreen from "./screens/HomeHotelsScreen.jsx";
import { initCsrf } from "./lib/api.js";

export default function App() {
  const [health, setHealth] = useState("…");

  useEffect(() => {
    jsonFetch('/api/sales/csrf/', { method: 'GET' }).catch(() => {});
  }, []);
  
  useEffect(() => {
    // 1. Инициализируем CSRF cookie при старте приложения
    initCsrf().catch((err) => {
      console.warn("CSRF init failed:", err);
    });

    // 2. Проверяем доступность backend
    (async () => {
      try {
        const res = await fetch("/api/health/", { credentials: "include" });
        const ct = res.headers.get("content-type") || "";
        const data = ct.includes("application/json")
          ? await res.json()
          : await res.text();
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

      {/* пример подключения первого экрана */}
      <div style={{ marginTop: 24 }}>
        <HomeHotelsScreen />
      </div>
    </div>
  );
}
