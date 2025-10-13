// frontend/src/lib/api.js
import { getCookie } from './csrf.js';

export const BACKEND    = import.meta.env.VITE_BACKEND    || "http://127.0.0.1:8000";
export const SALES_BASE = import.meta.env.VITE_SALES_BASE || "/api/sales/";

// Хелперы URL (если где-то нужны прямые BASE URL)
export const url = (p = "") =>
  `${BACKEND}${p.startsWith("/") ? p : "/" + p}`;

export const salesUrl = (p = "") =>
  `${BACKEND}${SALES_BASE.replace(/\/$/, "")}/${p.replace(/^\//, "")}`;

const NEEDS_CSRF = /^(POST|PUT|PATCH|DELETE)$/i;

function makeHeaders(extra = {}) {
  const h = {
    Accept: "application/json",
    "X-Requested-With": "XMLHttpRequest",
    ...extra,
  };
  // если уже лежит csrftoken — добавим проактивно
  if (!("X-CSRFToken" in h)) {
    const token = getCookie("csrftoken");
    if (token) h["X-CSRFToken"] = token;
  }
  return h;
}

/**
 * Универсальный fetch:
 *  - credentials: 'include'
 *  - автоподстановка X-CSRFToken для «опасных» методов
 *  - авто-получение токена через /api/sales/csrf/ при его отсутствии
 *  - один ретрай при 403 (вероятный CSRF)
 */
export async function jsonFetch(input, init = {}) {
  let opts = { credentials: "include", ...init };
  const method = (opts.method || "GET").toUpperCase();
  opts.headers = makeHeaders(opts.headers || {});

  // Если тело передали строкой (у нас это JSON.stringify), а Content-Type не указан — проставим
  if (
    opts.body != null &&
    typeof opts.body === "string" &&
    !("Content-Type" in opts.headers)
  ) {
    opts.headers["Content-Type"] = "application/json";
  }

  // Для мутирующих методов — гарантируем наличие CSRF
  if (NEEDS_CSRF.test(method)) {
    let token = getCookie("csrftoken");
    if (!opts.headers["X-CSRFToken"]) {
      opts.headers["X-CSRFToken"] = token || "";
    }
    // Токена нет — дернём эндпоинт и попробуем снова
    if (!opts.headers["X-CSRFToken"]) {
      await fetch("/api/sales/csrf/", { credentials: "include" });
      token = getCookie("csrftoken");
      opts.headers["X-CSRFToken"] = token || "";
    }
  }

  let res;
  try {
    res = await fetch(input, opts);
  } catch (e) {
    throw new Error(String(e?.message || e) || "Network error");
  }

  // Если 403 и метод «опасный» — обновим токен и повторим один раз
  if (res.status === 403 && NEEDS_CSRF.test(method)) {
    try {
      await fetch("/api/sales/csrf/", { credentials: "include" });
      const token = getCookie("csrftoken");
      opts.headers["X-CSRFToken"] = token || "";
      res = await fetch(input, opts);
    } catch (e) {
      throw new Error("CSRF refresh failed: " + String(e?.message || e));
    }
  }

  const ct = res.headers.get("content-type") || "";
  const body = ct.includes("application/json")
    ? await res.json().catch(() => null)
    : await res.text().catch(() => "");

  if (!res.ok) {
    const detail =
      (body && body.detail) ? body.detail :
      (typeof body === "string" && body) || `${res.status} ${res.statusText}`;
    throw new Error(String(detail));
  }
  return body;
}

// Вызывать один раз при старте приложения (чтобы сервер выдал csrftoken cookie)
export async function initCsrf() {
  try {
    await fetch("/api/sales/csrf/", { credentials: "include" });
  } catch {
    // молча: не роняем приложение
  }
}

// -------- API ФУНКЦИИ --------

export async function previewBatch(familyId) {
  return jsonFetch("/api/sales/bookings/batch/preview/", {
    method: "POST",
    body: JSON.stringify({ family_id: Number(familyId) }),
  });
}

export async function sendBatch(familyId) {
  return jsonFetch("/api/sales/bookings/batch/send/", {
    method: "POST",
    body: JSON.stringify({ family_id: Number(familyId) }),
  });
}

export async function getBooking(id) {
  return jsonFetch(`/api/sales/bookings/${id}/`, { method: "GET" });
}

export async function updateBooking(id, payload, { method = "PATCH" } = {}) {
  return jsonFetch(`/api/sales/bookings/${id}/`, {
    method,
    body: JSON.stringify(payload),
  });
}

export async function deleteBooking(id) {
  await jsonFetch(`/api/sales/bookings/${id}/`, { method: "DELETE" });
  return true;
}

export async function cancelBooking(id, reason = "") {
  return jsonFetch(`/api/sales/bookings/${id}/cancel/`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export async function patchTraveler(id, payload) {
  return jsonFetch(`/api/sales/travelers/${id}/`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}
