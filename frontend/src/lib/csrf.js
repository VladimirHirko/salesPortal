// frontend/src/lib/csrf.js
export function getCookie(name = 'csrftoken') {
  if (typeof document === 'undefined') return '';
  const m = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)');
  return m ? decodeURIComponent(m.pop()) : '';
}
