// src/auth.js
import { apiGet, apiPost, getCookie } from './api/sales.js';

let CSRF_CACHE = null;

export async function getCsrf() {
  const data = await apiGet('/api/sales/csrf/');   // { csrftoken, detail }
  CSRF_CACHE = (data && data.csrftoken) || getCookie('csrftoken') || '';
  return CSRF_CACHE;
}

export async function login(username, password) {
  const csrftoken = (await getCsrf()) || getCookie('csrftoken') || '';
  return apiPost('/api/sales/login/', { username, password }, csrftoken);
}

/**
 * Проверяем сессию запросом к ЗАЩИЩЁННОМУ эндпоинту.
 * Если 200 — авторизованы; 401/403 — нет.
 */
export async function isAuthenticated() {
  try {
    // выбери любой надёжно защищённый GET (без анонимного доступа)
    await apiGet('/api/sales/bookings/?limit=1');
    return true;
  } catch (e) {
    return false;
  }
}

export function getCachedCsrf() {
  return CSRF_CACHE || getCookie('csrftoken') || '';
}
