// src/screens/LoginScreen.jsx
import { useEffect, useState } from 'react';
import { login, isAuthenticated, getCsrf } from '../auth.js';
import { useNavigate, useLocation, Link } from 'react-router-dom';

export default function LoginScreen() {
  const [username, setU] = useState('');
  const [password, setP] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const nav = useNavigate();
  const loc = useLocation();

  useEffect(() => {
    (async () => {
      try {
        await getCsrf();
        setMsg('CSRF-токен готов.');
      } catch (e) {
        setMsg('Ошибка получения CSRF: ' + (e?.message || ''));
      }
      try {
        if (await isAuthenticated()) {
          const next = new URLSearchParams(loc.search).get('next') || '/';
          nav(next, { replace: true });
        }
      } catch {}
    })();
  }, [loc.search, nav]);

  async function handleLogin(e) {
    e?.preventDefault();
    setMsg('');
    setBusy(true);
    try {
      await login(username.trim(), password);
      setMsg('Вход выполнен успешно.');
      const next = new URLSearchParams(loc.search).get('next') || '/';
      nav(next, { replace: true });
    } catch (e2) {
      const raw = e2?.data?.detail || e2?.message || '';
      const txt = /<html/i.test(raw)
        ? 'Сервер вернул HTML/404. Проверь порт или маршрут.'
        : (raw || 'Ошибка входа');
      setMsg(`Ошибка: ${txt}`);
      console.error('LOGIN ERROR:', e2);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="section stack-3" style={{ maxWidth: 420, margin: '40px auto', textAlign: 'center' }}>
      <h2>Вход в систему</h2>
      <form className="stack-3" onSubmit={handleLogin}>
        <div className="stack-1">
          <label htmlFor="username">Имя пользователя</label>
          <input
            id="username"
            className="input"
            placeholder="Введите логин"
            value={username}
            onChange={e => setU(e.target.value)}
            autoFocus
            required
          />
        </div>
        <div className="stack-1">
          <label htmlFor="password">Пароль</label>
          <input
            id="password"
            className="input"
            type="password"
            placeholder="Введите пароль"
            value={password}
            onChange={e => setP(e.target.value)}
            required
          />
        </div>

        {msg && (
          <div className={/Ошибка/.test(msg) ? 'alert alert-danger' : 'alert alert-info'}>
            {msg}
          </div>
        )}

        <div className="row" style={{ display: 'flex', gap: '10px', justifyContent: 'center' }}>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={busy}
            style={{ minWidth: '120px' }}
          >
            {busy ? 'Входим…' : 'Войти'}
          </button>

          <Link
            to="/"
            className="btn btn-light"
            style={{
              display: 'inline-block',
              padding: '8px 16px',
              borderRadius: '6px',
              border: '1px solid #ccc',
              textDecoration: 'none',
              lineHeight: '28px',
            }}
          >
            На главную
          </Link>
        </div>
      </form>
    </div>
  );
}
