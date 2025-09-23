export const BACKEND = import.meta.env.VITE_BACKEND || "http://127.0.0.1:8000";
export const SALES_BASE = import.meta.env.VITE_SALES_BASE || "/api/sales/";

export const url = (p="") =>
  `${BACKEND}${p.startsWith("/") ? p : "/"+p}`;

export const salesUrl = (p="") =>
  `${BACKEND}${SALES_BASE.replace(/\/$/, "")}/${p.replace(/^\//, "")}`;


export async function previewBatch(familyId) {
  const r = await fetch("/api/sales/bookings/batch/preview/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ family_id: Number(familyId) }),
  });
  const data = await r.json();
  if (!r.ok) throw new Error(data?.detail || "Не удалось собрать предпросмотр");
  return data; // { count, total, items: [...] }
}

export async function sendBatch(familyId) {
  const r = await fetch("/api/sales/bookings/batch/send/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ family_id: Number(familyId) }),
  });
  const data = await r.json();
  if (!r.ok) throw new Error(data?.detail || "Ошибка отправки пакета");
  return data; // { updated }
}

export async function getBooking(id) {
  const r = await fetch(`/api/sales/bookings/${id}/`, { credentials: 'include' });
  const j = await r.json();
  if (!r.ok) throw new Error(j?.detail || `HTTP ${r.status}`);
  return j;
}

export async function updateBooking(id, payload, { method = 'PATCH' } = {}) {
  const r = await fetch(`/api/sales/bookings/${id}/`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(payload),
  });
  const j = await r.json();
  if (!r.ok) throw new Error(j?.detail || `HTTP ${r.status}`);
  return j;
}

// удалить бронь (только DRAFT)
export async function deleteBooking(id) {
  const r = await fetch(`/api/sales/bookings/${id}/`, {
    method: 'DELETE',
    credentials: 'include',
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) {
    throw new Error(j?.detail || `HTTP ${r.status}`);
  }
  return true;
}

// аннулировать бронь (не DRAFT)
export async function cancelBooking(id, reason = '') {
  const r = await fetch(`/api/sales/bookings/${id}/cancel/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ reason }),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) {
    throw new Error(j?.detail || `HTTP ${r.status}`);
  }
  return j; // возвращаем объект брони
}

