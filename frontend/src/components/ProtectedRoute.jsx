// src/components/ProtectedRoute.jsx
import { useEffect, useState } from 'react';
import { isAuthenticated } from '../auth.js';
import { useLocation, Navigate, Outlet } from 'react-router-dom';

export default function ProtectedRoute() {
  const loc = useLocation();
  const [ready, setReady] = useState(false);
  const [ok, setOk] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      const yes = await isAuthenticated();
      if (!alive) return;
      setOk(!!yes);
      setReady(true);
    })();
    return () => { alive = false; };
  }, [loc.pathname, loc.search]);

  if (!ready) {
    return (
      <div className="section" style={{ maxWidth: 480, margin: '40px auto' }}>
        <div className="muted">Проверяю сессию…</div>
      </div>
    );
  }

  if (!ok) {
    const next = encodeURIComponent(loc.pathname + (loc.search || ''));
    return <Navigate to={`/login?next=${next}`} replace />;
  }

  return <Outlet />;
}
