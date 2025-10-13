// src/api/sales.js
import { getCachedCsrf } from '../auth.js';

// frontend/src/api/sales.js
import {
  jsonFetch,
  previewBatch,
  sendBatch,
  getBooking,
  updateBooking,
  deleteBooking,
  cancelBooking,
  patchTraveler,
} from "../lib/api.js";

export {
  jsonFetch,
  previewBatch,
  sendBatch,
  getBooking,
  updateBooking,
  deleteBooking,
  cancelBooking,
  patchTraveler,
};


export function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return decodeURIComponent(parts.pop().split(';').shift());
  return '';
}

async function handle(resp) {
  if (!resp.ok) {
    const text = await resp.text().catch(() => '');
    let data;
    try { data = JSON.parse(text); } catch { data = { detail: text || resp.statusText }; }
    const err = new Error(data.detail || `HTTP ${resp.status}`);
    err.status = resp.status;
    err.data = data;
    throw err;
  }
  const ct = resp.headers.get('content-type') || '';
  if (ct.includes('application/json')) return resp.json();
  return resp.text();
}

export async function apiGet(url) {
  const resp = await fetch(url, {
    method: 'GET',
    credentials: 'include',
    headers: { 'Accept': 'application/json' },
  });
  return handle(resp);
}

export async function apiPost(url, body, csrftoken) {
  const headers = {
    'Accept': 'application/json',
    'Content-Type': 'application/json',
  };
  const token = csrftoken || getCachedCsrf() || getCookie('csrftoken');
  if (token) headers['X-CSRFToken'] = token;

  const resp = await fetch(url, {
    method: 'POST',
    credentials: 'include',
    headers,
    body: JSON.stringify(body || {}),
  });
  return handle(resp);
}
