import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { getBooking, updateBooking, deleteBooking, cancelBooking } from '../lib/api.js';

const fmtMoney = (v, cur='EUR') => new Intl.NumberFormat(undefined, { style:'currency', currency:cur, maximumFractionDigits: 2 }).format(Number(v||0));

const STATUS_LABEL = {
  DRAFT: 'Черновик',
  PENDING: 'Отправлено',
  HOLD: 'Ожидает оплаты',
  PAID: 'Оплачено',
  CONFIRMED: 'Подтверждено',
  CANCELLED: 'Отменено',
  EXPIRED: 'Просрочено',
};

export default function EditBookingScreen() {
  const { id } = useParams();               // /bookings/:id/edit
  const [sp] = useSearchParams();           // fallback для ?family=...
  const nav = useNavigate();

  const [data, setData] = useState(null);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');

  const isDraft = (data?.status === 'DRAFT');
  const isCancelled = (data?.status === 'CANCELLED');

  const familyId = useMemo(() => {
    // приоритет: пришло из JSON → query ?family=...
    return data?.family_id ?? (sp.get('family') ? Number(sp.get('family')) : null);
  }, [data, sp]);

  useEffect(() => {
    let abort = false
    ;(async () => {
      try {
        const r = await fetch(`/api/sales/bookings/${id}/`, { credentials: 'include' })
        const j = await r.json()
        if (!r.ok) throw new Error(j?.detail || `HTTP ${r.status}`)
        if (!abort) setData(j)
      } catch (e) {
        if (!abort) setErr(e.message || String(e))
      } finally {
        if (!abort) setLoading(false)
      }
    })()
    return () => { abort = true }
  }, [id])

  if (loading) return <div style={{padding:16}}>Загрузка брони #{id}…</div>
  if (err) return (
    <div style={{padding:16, color:'#b91c1c'}}>
      Ошибка загрузки: {err}
      <div><button className="btn" onClick={() => nav(-1)}>← Назад</button></div>
    </div>
  )

  function onChange(field, cast = v => v) {
    return e => setData(d => ({ ...d, [field]: cast(e.target.value) }));
  }

  async function onSave() {
    if (!data) return;
    setSaving(true); setErr('');
    try {
      const payload = {
        // PATCH — отправляем только редактируемые поля
        date: data.date,
        room_number: data.room_number || '',
        excursion_language: data.excursion_language || '',
        pickup_point_id: data.pickup_point_id ?? null,
        pickup_point_name: data.pickup_point_name || '',
        pickup_time_str: data.pickup_time_str || '',
        pickup_lat: data.pickup_lat ?? null,
        pickup_lng: data.pickup_lng ?? null,
        pickup_address: data.pickup_address || '',
        adults: Number(data.adults||0),
        children: Number(data.children||0),
        infants: Number(data.infants||0),
        price_per_adult: data.price_per_adult != null ? Number(data.price_per_adult) : null,
        price_per_child: data.price_per_child != null ? Number(data.price_per_child) : null,
        gross_total: data.gross_total != null ? Number(data.gross_total) : null,
      };
      const j = await updateBooking(id, payload, { method: 'PATCH' });
      setData(j);
      alert('Сохранено');
      // после сохранения — вернёмся на семью, если знаем её
      if (familyId) nav(`/family/${familyId}`);
    } catch (e) {
      setErr(e.message || 'Не удалось сохранить');
    } finally {
      setSaving(false);
    }
  }

  async function onDelete() {
    if (!isDraft) { alert('Удалять можно только черновик'); return; }
    if (!confirm('Удалить эту бронь?')) return;
    try {
      await deleteBooking(id);
      alert('Удалено');
      if (familyId) nav(`/family/${familyId}`); else nav(-1);
    } catch (e) {
      setErr(e.message || 'Не удалось удалить');
    }
  }

  async function onCancel() {
    if (isDraft) { alert('Черновик не аннулируют — его удаляют'); return; }
    if (isCancelled) { alert('Бронь уже аннулирована'); return; }
    const reason = prompt('Причина аннуляции (необязательно):', '') || '';
    try {
      const j = await cancelBooking(id, reason);
      setData(j);
      alert('Аннулировано');
      if (familyId) nav(`/family/${familyId}`);
    } catch (e) {
      setErr(e.message || 'Не удалось аннулировать');
    }
  }

  if (loading)  return <div className="container app-padding">Загрузка…</div>;
  if (err)      return <div className="container app-padding" style={{color:'#b91c1c'}}>{err}</div>;
  if (!data)    return <div className="container app-padding">Нет данных</div>;

  return (
    <div className="container app-padding" style={{maxWidth: 780}}>
      <div className="section">
        <div className="section__head" style={{display:'flex', alignItems:'center', gap:8}}>
          <h1>Редактирование брони</h1>
          <span className="badge">{STATUS_LABEL[data.status] || data.status}</span>
          <span style={{marginLeft:'auto'}} />
          <button className="btn btn-outline" onClick={() => (familyId ? nav(`/family/${familyId}`) : nav(-1))}>
            ← Назад
          </button>
        </div>

        <div className="section__body" style={{display:'grid', gap:12}}>
          <div className="note">
            <b>{data.excursion_title}</b>
            {!!data.date && <> · {new Date(data.date).toLocaleDateString()}</>}
            {!!data.booking_code && <> · Код: {data.booking_code}</>}
          </div>

          {!isDraft && (
            <div className="muted">
              Бронь не в статусе «Черновик» — редактирование ограничено, можно только аннулировать.
            </div>
          )}

          {/* Дата */}
          <label>
            <div className="muted">Дата (YYYY-MM-DD)</div>
            <input
              className="input"
              type="date"
              value={data.date || ''}
              onChange={onChange('date', v => v)}
              disabled={!isDraft}
            />
          </label>

          {/* Язык / Комната */}
          <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:12}}>
            <label>
              <div className="muted">Язык</div>
              <input
                className="input"
                value={data.excursion_language || ''}
                onChange={onChange('excursion_language')}
                disabled={!isDraft}
                placeholder="ru / en / es ..."
              />
            </label>
            <label>
              <div className="muted">Комната</div>
              <input
                className="input"
                value={data.room_number || ''}
                onChange={onChange('room_number')}
                disabled={!isDraft}
                placeholder="Номер комнаты"
              />
            </label>
          </div>

          {/* Пикап */}
          <div className="card" style={{padding:12}}>
            <div className="muted" style={{marginBottom:6}}>Пикап</div>
            <div style={{display:'grid', gridTemplateColumns:'2fr 1fr 1fr', gap:8}}>
              <input className="input" placeholder="Точка (название)"
                     value={data.pickup_point_name || ''} onChange={onChange('pickup_point_name')} disabled={!isDraft}/>
              <input className="input" placeholder="Время HH:MM"
                     value={data.pickup_time_str || ''} onChange={onChange('pickup_time_str')} disabled={!isDraft}/>
              <input className="input" placeholder="ID точки"
                     value={data.pickup_point_id ?? ''} onChange={onChange('pickup_point_id', v => v ? Number(v) : null)} disabled={!isDraft}/>
            </div>
            <input className="input" style={{marginTop:8}} placeholder="Адрес"
                   value={data.pickup_address || ''} onChange={onChange('pickup_address')} disabled={!isDraft}/>
          </div>

          {/* Состав и цены */}
          <div style={{display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:12}}>
            <label>
              <div className="muted">Взрослые</div>
              <input className="input" type="number" min="0"
                     value={data.adults ?? 0} onChange={onChange('adults', Number)} disabled={!isDraft}/>
            </label>
            <label>
              <div className="muted">Дети</div>
              <input className="input" type="number" min="0"
                     value={data.children ?? 0} onChange={onChange('children', Number)} disabled={!isDraft}/>
            </label>
            <label>
              <div className="muted">Младенцы</div>
              <input className="input" type="number" min="0"
                     value={data.infants ?? 0} onChange={onChange('infants', Number)} disabled={!isDraft}/>
            </label>
          </div>

          <div style={{display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:12}}>
            <label>
              <div className="muted">Цена взрослого</div>
              <input className="input" type="number" step="0.01"
                     value={data.price_per_adult ?? ''} onChange={onChange('price_per_adult', Number)} disabled={!isDraft}/>
            </label>
            <label>
              <div className="muted">Цена ребёнка</div>
              <input className="input" type="number" step="0.01"
                     value={data.price_per_child ?? ''} onChange={onChange('price_per_child', Number)} disabled={!isDraft}/>
            </label>
            <label>
              <div className="muted">Итог (gross)</div>
              <input className="input" type="number" step="0.01"
                     value={data.gross_total ?? ''} onChange={onChange('gross_total', Number)} disabled={!isDraft}/>
            </label>
          </div>

          <div className="note" style={{fontWeight:700}}>
            Текущая сумма: {fmtMoney(data.gross_total || 0, 'EUR')}
          </div>

          {!!err && <div className="err">{err}</div>}

          <div className="form-footer" style={{display:'flex', gap:12, marginTop:8}}>
            {/* Сохранить — доступно только для черновиков */}
            <button className="btn btn-primary" onClick={onSave} disabled={saving || !isDraft}>
              {saving ? 'Сохраняем…' : 'Сохранить'}
            </button>

            {/* Аннулировать — доступно только для НЕ DRAFT и не отменённых */}
            {data?.status !== 'DRAFT' && (
              <button className="btn btn-warning" onClick={onCancel} disabled={isCancelled}>
                Аннулировать
              </button>
            )}

            {/* Удалить — доступно только для черновиков */}
            <button className="btn btn-outline" onClick={onDelete} disabled={!isDraft}>
              Удалить
            </button>
          </div>

        </div>
      </div>
    </div>
  );
}
