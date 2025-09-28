// src/screens/EditBookingScreen.jsx
import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { getBooking, updateBooking, deleteBooking, cancelBooking } from '../lib/api.js';
import { patchTraveler } from '../lib/api.js';
import SpecialTravelerFields from '../components/SpecialTravelerFields.jsx';

const fmtMoney = (v, cur='EUR') =>
  new Intl.NumberFormat(undefined, { style:'currency', currency:cur, maximumFractionDigits: 2 })
    .format(Number(v||0));

const STATUS_LABEL = {
  DRAFT: 'Черновик',
  PENDING: 'Отправлено',
  HOLD: 'Ожидает оплаты',
  PAID: 'Оплачено',
  CONFIRMED:'Подтверждено',
  CANCELLED:'Отменено',
  EXPIRED: 'Просрочено',
};

const STATUS_COLOR = {
  DRAFT:    '#2563eb',
  PENDING:  '#7c3aed',
  HOLD:     '#f59e0b',
  PAID:     '#16a34a',
  CONFIRMED:'#0891b2',
  CANCELLED:'#ef4444',
  EXPIRED:  '#6b7280',
};

function StatusBadge({status}) {
  const color = STATUS_COLOR[status] || '#334155';
  const label = STATUS_LABEL[status] || status;
  return (
    <span
      className="badge"
      style={{
        background: `${color}20`,
        color,
        border: `1px solid ${color}66`,
        padding: '2px 8px',
        borderRadius: 999,
        fontSize: 12,
        lineHeight: '18px'
      }}
    >
      {label}
    </span>
  );
}

// эвристика: какие допполя нужны по заголовку экскурсии (как в FamilyScreen)
function detectSpecialKey(title='') {
  const s = String(title).toLowerCase();
  if (s.includes('танжер') || s.includes('tang')) return 'tangier';
  if (s.includes('гранад')) return 'granada';
  if (s.includes('гибрал') || s.includes('gibr')) return 'gibraltar';
  if (s.includes('севиль') || s.includes('sevil')) return 'seville';
  return 'regular';
}

export default function EditBookingScreen() {
  const { id } = useParams();
  const [sp] = useSearchParams();
  const nav = useNavigate();

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  // полные объекты туристов из брони
  const [travs, setTravs] = useState([]); // [{id, first_name, last_name, gender, doc_type, doc_expiry, passport, nationality, dob, ...}]

  const original = useRef(null);
  const toastTimer = useRef(null);

  const isDraft = (data?.status === 'DRAFT');
  const isCancelled = (data?.status === 'CANCELLED');

  const familyId = useMemo(() => {
    return data?.family_id ?? (sp.get('family') ? Number(sp.get('family')) : null);
  }, [data, sp]);

  const showToast = useCallback((msg) => {
    if (window?.__toast) { window.__toast(msg); return; }
    const el = document.createElement('div');
    el.textContent = msg;
    Object.assign(el.style, {
      position:'fixed', bottom:'20px', left:'50%', transform:'translateX(-50%)',
      background:'#111827', color:'#fff', padding:'8px 12px', borderRadius:'8px',
      boxShadow:'0 8px 24px rgba(0,0,0,.2)', zIndex:9999, fontSize:'14px'
    });
    document.body.appendChild(el);
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => el.remove(), 1500);
  }, []);

  // извлечь id туристов из разных форматов ответа
  function extractTravelerIds(b) {
    if (!b) return [];
    if (Array.isArray(b.travelers)) return b.travelers.map(Number);
    if (Array.isArray(b.travelers_ids)) return b.travelers_ids.map(Number);
    if (typeof b.travelers_csv === 'string') {
      return b.travelers_csv.split(',').map(s=>Number(s.trim())).filter(n=>Number.isFinite(n));
    }
    return [];
  }

  const fetchData = useCallback(async () => {
    setLoading(true); setErr('');
    try {
      const j = await getBooking(id);
      setData(j);
      original.current = pickEditable(j);

      // турики: если бэк уже дал travelers_full — берём его, иначе докачиваем по id
      if (Array.isArray(j.travelers_full)) {
        setTravs(j.travelers_full);
      } else {
        const ids = extractTravelerIds(j);
        if (ids.length) {
          const list = await Promise.all(
            ids.map(trId =>
              fetch(`/api/sales/travelers/${trId}/`, { credentials:'include' })
                .then(r => r.ok ? r.json() : null)
                .catch(() => null)
            )
          );
          setTravs(list.filter(Boolean));
        } else {
          setTravs([]);
        }
      }
    } catch (e) {
      setErr(e.message || 'Ошибка загрузки');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // горячая клавиша Cmd/Ctrl+S
  useEffect(() => {
    const onKey = e => {
      const isSave = (e.key === 's' || e.key === 'ы') && (e.metaKey || e.ctrlKey);
      if (isSave) {
        e.preventDefault();
        if (isDraft && isDirty) onSave();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isDraft]); // eslint-disable-line

  function onChange(field, cast = v => v) {
    return e => setData(d => ({ ...d, [field]: cast(e.target ? e.target.value : e) }));
  }

  // редактируемые поля брони
  function pickEditable(src) {
    if (!src) return {};
    const n = (x)=> (x ?? null);
    return {
      date: n(src.date),
      room_number: n(src.room_number || ''),
      excursion_language: n(src.excursion_language || ''),
      pickup_point_id: src.pickup_point_id ?? null,
      pickup_point_name: n(src.pickup_point_name || ''),
      pickup_time_str: n(src.pickup_time_str || ''),
      pickup_lat: src.pickup_lat ?? null,
      pickup_lng: src.pickup_lng ?? null,
      pickup_address: n(src.pickup_address || ''),
      adults: Number(src.adults||0),
      children: Number(src.children||0),
      infants: Number(src.infants||0),
      price_per_adult: src.price_per_adult != null ? Number(src.price_per_adult) : null,
      price_per_child: src.price_per_child != null ? Number(src.price_per_child) : null,
      gross_total: src.gross_total != null ? Number(src.gross_total) : null,
    };
  }

  // diff для PATCH
  const patch = useMemo(() => {
    const cur = pickEditable(data);
    const base = original.current || {};
    const diff = {};
    for (const k of Object.keys(cur)) {
      const a = cur[k];
      const b = base[k];
      if ((a ?? null) !== (b ?? null)) diff[k] = a;
    }
    return diff;
  }, [data]);

  const isDirty = useMemo(() => Object.keys(patch).length > 0, [patch]);

  async function onSave() {
    if (!data || !isDraft || !isDirty) return;
    setSaving(true); setErr('');
    try {
      const j = await updateBooking(id, patch, { method: 'PATCH' });
      setData(j);
      original.current = pickEditable(j);
      showToast('Изменения сохранены');
      window.dispatchEvent(new CustomEvent('booking:changed', {
        detail: { id: Number(id), action: 'updated', data: j }
      }));
      if (familyId) nav(`/family/${familyId}`);
    } catch (e) {
      setErr(e.message || 'Не удалось сохранить');
    } finally {
      setSaving(false);
    }
  }

  async function onDelete() {
    if (!isDraft) { showToast('Удалять можно только черновик'); return; }
    if (!confirm('Удалить эту бронь?')) return;
    try {
      await deleteBooking(id);
      showToast('Бронь удалена');
      window.dispatchEvent(new CustomEvent('booking:changed', {
        detail: { id: Number(id), action: 'deleted' }
      }));
      if (familyId) nav(`/family/${familyId}`); else nav(-1);
    } catch (e) {
      setErr(e.message || 'Не удалось удалить');
    }
  }

  async function onCancel() {
    if (isDraft) { showToast('Черновик не аннулируют — его удаляют'); return; }
    if (isCancelled) { showToast('Бронь уже аннулирована'); return; }
    const reason = prompt('Причина аннуляции (необязательно):', '') || '';
    try {
      const j = await cancelBooking(id, reason);
      setData(j);
      original.current = pickEditable(j);
      showToast('Бронь аннулирована');
      window.dispatchEvent(new CustomEvent('booking:changed', {
        detail: { id: Number(id), action: 'cancelled', data: j }
      }));
      if (familyId) nav(`/family/${familyId}`);
    } catch (e) {
      setErr(e.message || 'Не удалось аннулировать');
    }
  }

  // ====== редактирование данных туристов прямо здесь =========================
  const excursionTitle = data?.excursion_title || '';
  const specialKey = detectSpecialKey(excursionTitle);

  // оптимистично меняем локально + PATCH на бэк
  function onTravelerExtraChange(id, field, value) {
    if (!isDraft) { showToast('Редактирование доступно только для черновиков'); return; }
    setTravs(list => list.map(t => t.id === id ? { ...t, [field]: value } : t));
    patchTraveler(id, { [field]: value }).catch(() => {
      showToast('Не удалось сохранить поле туриста');
    });
  }

  if (loading) return <div className="container app-padding">Загрузка брони #{id}…</div>;
  if (err) return (
    <div className="container app-padding" style={{color:'#b91c1c'}}>
      <div style={{fontWeight:600, marginBottom:6}}>Ошибка:</div>{err}
      <div style={{marginTop:12}}><button className="btn" onClick={() => nav(-1)}>← Назад</button></div>
    </div>
  );
  if (!data) return <div className="container app-padding">Нет данных</div>;

  const fieldsDisabled = !isDraft;
  const disabledTip = fieldsDisabled ? 'Редактирование доступно только в статусе «Черновик»' : '';

  return (
    <div className="container app-padding" style={{maxWidth: 820, paddingBottom: 96}}>
      <div className="section">
        <div className="section__head" style={{display:'flex', alignItems:'center', gap:8}}>
          <h1 style={{margin:0}}>Редактирование брони</h1>
          <StatusBadge status={data.status} />
          <span style={{marginLeft:'auto'}} />
          <button className="btn btn-outline" onClick={() => (familyId ? nav(`/family/${familyId}`) : nav(-1))}>← Назад</button>
        </div>

        <div className="section__body" style={{display:'grid', gap:12}}>
          <div className="note" style={{display:'flex', gap:8, flexWrap:'wrap'}}>
            <b>{data.excursion_title}</b>
            {!!data.date && <span>· {new Date(data.date).toLocaleDateString()}</span>}
            {!!data.booking_code && <span>· Код: {data.booking_code}</span>}
          </div>

          {!isDraft && (
            <div className="muted" title={disabledTip}>
              Бронь не в статусе «Черновик» — поля заблокированы. Доступны аннуляция и просмотр.
            </div>
          )}

          {/* Дата */}
          <label title={disabledTip}>
            <div className="muted">Дата (YYYY-MM-DD)</div>
            <input
              className="input"
              type="date"
              value={data.date || ''}
              onChange={onChange('date')}
              disabled={fieldsDisabled}
            />
          </label>

          {/* Язык / Комната */}
          <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:12}}>
            <label title={disabledTip}>
              <div className="muted">Язык</div>
              <input
                className="input"
                value={data.excursion_language || ''}
                onChange={onChange('excursion_language')}
                disabled={fieldsDisabled}
                placeholder="ru / en / es ..."
              />
            </label>
            <label title={disabledTip}>
              <div className="muted">Комната</div>
              <input
                className="input"
                value={data.room_number || ''}
                onChange={onChange('room_number')}
                disabled={fieldsDisabled}
                placeholder="Номер комнаты"
              />
            </label>
          </div>

          {/* Пикап */}
          <div className="card" style={{padding:12}} title={disabledTip}>
            <div className="muted" style={{marginBottom:6}}>Пикап</div>
            <div style={{display:'grid', gridTemplateColumns:'2fr 1fr 1fr', gap:8}}>
              <input className="input" placeholder="Точка (название)"
                     value={data.pickup_point_name || ''} onChange={onChange('pickup_point_name')} disabled={fieldsDisabled}/>
              <input className="input" placeholder="Время HH:MM"
                     value={data.pickup_time_str || ''} onChange={onChange('pickup_time_str')} disabled={fieldsDisabled}/>
              <input className="input" placeholder="ID точки"
                     value={data.pickup_point_id ?? ''} onChange={onChange('pickup_point_id', v => v ? Number(v) : null)} disabled={fieldsDisabled}/>
            </div>
            <input className="input" style={{marginTop:8}} placeholder="Адрес"
                   value={data.pickup_address || ''} onChange={onChange('pickup_address')} disabled={fieldsDisabled}/>
          </div>

          {/* Состав */}
          <div style={{display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:12}}>
            <label title={disabledTip}>
              <div className="muted">Взрослые</div>
              <input className="input" type="number" min="0"
                     value={data.adults ?? 0} onChange={onChange('adults', Number)} disabled={fieldsDisabled}/>
            </label>
            <label title={disabledTip}>
              <div className="muted">Дети</div>
              <input className="input" type="number" min="0"
                     value={data.children ?? 0} onChange={onChange('children', Number)} disabled={fieldsDisabled}/>
            </label>
            <label title={disabledTip}>
              <div className="muted">Младенцы</div>
              <input className="input" type="number" min="0"
                     value={data.infants ?? 0} onChange={onChange('infants', Number)} disabled={fieldsDisabled}/>
            </label>
          </div>

          {/* Цены */}
          <div style={{display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:12}}>
            <label title={disabledTip}>
              <div className="muted">Цена взрослого</div>
              <input className="input" type="number" step="0.01"
                     value={data.price_per_adult ?? ''} onChange={onChange('price_per_adult', Number)} disabled={fieldsDisabled}/>
            </label>
            <label title={disabledTip}>
              <div className="muted">Цена ребёнка</div>
              <input className="input" type="number" step="0.01"
                     value={data.price_per_child ?? ''} onChange={onChange('price_per_child', Number)} disabled={fieldsDisabled}/>
            </label>
            <label title={disabledTip}>
              <div className="muted">Итог (gross)</div>
              <input className="input" type="number" step="0.01"
                     value={data.gross_total ?? ''} onChange={onChange('gross_total', Number)} disabled={fieldsDisabled}/>
            </label>
          </div>

          <div className="note" style={{fontWeight:700}}>
            Текущая сумма: {fmtMoney(data.gross_total || 0, 'EUR')}
          </div>

          {!!err && <div className="err">{err}</div>}
        </div>
      </div>

      {/* ====== НОВЫЙ БЛОК: данные туристов для этой брони ====== */}
      {specialKey !== 'regular' && travs.length > 0 && (
        <div className="section">
          <div className="section__head">Данные туристов для спец-экскурсии</div>
          <div className="section__body" style={{ display:'grid', gap:12 }}>
            {travs.map(t => (
              <SpecialTravelerFields
                key={t.id}
                traveler={t}
                excursionTitle={excursionTitle}
                onChange={(id, field, value) => onTravelerExtraChange(id, field, value)}
              />
            ))}
          </div>
          <div className="muted" style={{marginTop:6}}>
            Изменения по туристам сохраняются автоматически.
          </div>
        </div>
      )}

      {/* Приклеенный футер действий */}
      <div style={{
        position:'fixed', left:0, right:0, bottom:0, padding:'8px 16px',
        background:'rgba(255,255,255,.92)', backdropFilter:'saturate(180%) blur(8px)',
        borderTop:'1px solid #e5e7eb', display:'flex', gap:12, justifyContent:'center'
      }}>
        <button className="btn btn-primary" onClick={onSave} disabled={saving || !isDraft || !isDirty}>
          {saving ? 'Сохраняем…' : (isDirty ? 'Сохранить изменения' : 'Нет изменений')}
        </button>

        {data?.status !== 'DRAFT' && (
          <button className="btn btn-warning" onClick={onCancel} disabled={isCancelled}>
            Аннулировать
          </button>
        )}

        <button className="btn btn-outline" onClick={onDelete} disabled={!isDraft}>
          Удалить черновик
        </button>
      </div>
    </div>
  );
}
