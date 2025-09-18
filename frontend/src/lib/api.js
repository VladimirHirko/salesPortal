export const BACKEND = import.meta.env.VITE_BACKEND || "http://127.0.0.1:8000";
export const SALES_BASE = import.meta.env.VITE_SALES_BASE || "/api/sales/";

export const url = (p="") =>
  `${BACKEND}${p.startsWith("/") ? p : "/"+p}`;

export const salesUrl = (p="") =>
  `${BACKEND}${SALES_BASE.replace(/\/$/, "")}/${p.replace(/^\//, "")}`;
