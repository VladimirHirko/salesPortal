import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { DayPicker } from 'react-day-picker'

// 0=Sun в JS, значит Mon=1 ... Sun=0
const WEEKDAY_CODE_TO_NUM = { mon:1, tue:2, wed:3, thu:4, fri:5, sat:6, sun:0 }

function toWeekdayNums(ex) {
  if (!ex) return []
  // если пришли числа 0..6 с семантикой Mon..Sun — сдвигаем к JS (Sun=0)
  if (Array.isArray(ex.available_days) && ex.available_days.length) {
    return ex.available_days.map(n => (Number(n) + 1) % 7)
  }
  if (Array.isArray(ex.days) && ex.days.length) {
    return ex.days.map(c => WEEKDAY_CODE_TO_NUM[c]).filter(n => n !== undefined)
  }
  return []
}

function buildNextDates(weekdayNums, daysAhead = 60) {
  const set = new Set(weekdayNums)
  const out = []
  const today = new Date()
  for (let i=0; i<=daysAhead; i++) {
    const d = new Date(today)
    d.setDate(today.getDate() + i)
    if (set.size === 0 || set.has(d.getDay())) {
      const yyyy = d.getFullYear()
      const mm = String(d.getMonth()+1).padStart(2,'0')
      const dd = String(d.getDate()).padStart(2,'0')
      out.push({ iso: `${yyyy}-${mm}-${dd}`, label: d.toLocaleDateString() })
    }
  }
  return out
}

function normalizeQuote(raw, { adults=0, children=0, infants=0 } = {}) {
  if (!raw || typeof raw !== 'object') return { ok:false };
  if (raw.detail) return { ok:false, error: String(raw.detail) };

  const cur = raw.currency || 'EUR';

  let gross = raw.gross ?? raw.gross_total ?? raw.total;
  if (typeof gross === 'string') gross = Number(gross.replace(',', '.'));

  let perAdult = raw.meta?.adult_price ?? raw.price_adult ?? raw.adult_price ?? raw.details?.price_adult ?? null;
  let perChild = raw.meta?.child_price ?? raw.price_child ?? raw.child_price ?? raw.details?.price_child ?? null;

  perAdult = perAdult != null ? Number(perAdult) : null;
  perChild = perChild != null ? Number(perChild) : null;

  if ((gross == null || Number.isNaN(Number(gross))) && (perAdult != null || perChild != null)) {
    const a = perAdult ?? 0;
    const c = perChild ?? perAdult ?? 0;
    gross = a * adults + c * children;
  }

  const grossNum = Number(gross ?? 0);

  return {
    ok: (grossNum > 0) || (perAdult != null || perChild != null),
    currency: cur,
    gross: grossNum,
    perAdult,
    perChild,
    source: raw.meta?.source || raw.source || null,
  };
}

function calcDraftsTotal(list) {
  let sum = 0;
  for (const b of list || []) sum += Number(b?.gross_total || 0);
  return sum;
}

const fmtMoney = (v, cur='EUR') =>
  new Intl.NumberFormat(undefined, { style:'currency', currency: cur, maximumFractionDigits: 2 }).format(Number(v||0))

export default function FamilyScreen(){
  const { famId } = useParams()
  const nav = useNavigate()
  const [fam, setFam] = useState(null)
  const [sel, setSel] = useState([])           // выбранные traveler.id
  const [date, setDate] = useState('')
  const [excursions, setExcursions] = useState([])
  const [excursionId, setExcursionId] = useState('')
  const [availableDates, setAvailableDates] = useState([])
  const [pickup, setPickup] = useState(null)
  const [loading, setLoading] = useState(false)
  const [quoteLoading, setQuoteLoading] = useState(false)
  const [quote, setQuote] = useState(null)

  // ── новые состояния ─────────────────────────────────────────────────────────
  const [companies, setCompanies] = useState([])        // [{id,name}]
  const [companyId, setCompanyId] = useState(null)
  const [roomNumber, setRoomNumber] = useState('')      // ручной ввод
  const [excursionLanguage, setExcursionLanguage] = useState('') // 'ru'|'en'|...
  const [drafts, setDrafts] = useState([])

  // сумма по черновикам — теперь drafts уже объявлен
  const draftsTotal = useMemo(() => calcDraftsTotal(drafts), [drafts])

  useEffect(()=>{
    (async ()=>{
      // семья
      const fRes = await fetch(`/api/sales/families/${famId}/`)
      const f = fRes.ok ? await fRes.json() : null
      if (!f) { setFam(null); return }
      setFam(f); setSel(Array.isArray(f.party) ? f.party.map(p=>p.id) : [])

      // экскурсии
      const exRes = await fetch(`/api/sales/excursions/?compact=1&limit=20`)
      const exJson = exRes.ok ? await exRes.json() : null
      setExcursions(Array.isArray(exJson?.items) ? exJson.items : [])

      // компании (не падаем, если 403/500)
      try {
        const cRes = await fetch(`/api/sales/companies/`)
        const cJson = cRes.ok ? await cRes.json() : []
        setCompanies(Array.isArray(cJson) ? cJson : [])
      } catch {
        setCompanies([])
      }
    })()
  }, [famId])

  // ⬇️ ДОБАВЬ ЭТОТ ЭФФЕКТ СРАЗУ ПОСЛЕ useEffect(...) что грузит семью/экскурсии/компании
  useEffect(() => {
    let aborted = false;
    (async () => {
      const r = await fetch(`/api/sales/bookings/family/${famId}/drafts/`);
      if (!aborted && r.ok) {
        const json = await r.json();
        setDrafts(Array.isArray(json) ? json : (json.items || []));
      }
    })();
    return () => { aborted = true; };
  }, [famId]);


  // доступные языки для выбранной экскурсии
  const availableLangs = useMemo(() => {
    const ex = excursions.find(x => String(x.id) === String(excursionId))
    const codesRaw = Array.isArray(ex?.languages) ? ex.languages : []
    const codes = codesRaw.map(c => String(c).trim().toLowerCase()).filter(Boolean)

    let dn
    try {
      dn = new Intl.DisplayNames([navigator.language || 'ru'], { type: 'language' })
    } catch (_) {
      dn = null
    }

    return codes.map(c => ({
      code: c,
      label: dn ? dn.of(c) || c.toUpperCase() : c.toUpperCase()
    }))
  }, [excursions, excursionId])


  // если язык единственный — автоподставим
  useEffect(() => {
    if (availableLangs.length === 1) setExcursionLanguage(availableLangs[0].code)
  }, [availableLangs])

  // когда выбрана экскурсия и дата — подтягиваем пикапы и цену
  useEffect(() => {
    if (!excursionId || !date || !fam) return;

    const adults = (fam.party || []).filter(p => !p.is_child && sel.includes(p.id)).length || 1;
    const children = (fam.party || []).filter(p =>  p.is_child && sel.includes(p.id)).length || 0;

    const ctrl = new AbortController();
    (async () => {
      setQuoteLoading(true);
      try {
        // 1) pickups v2 — передаём и id, и name (бэк сам зарезолвит, если id отсутствует)
        const p = new URLSearchParams({
          excursion_id: String(excursionId),
          hotel_id: String(fam.hotel_id || ''),   // может быть пусто
          hotel_name: fam.hotel_name || '',
          date,
        });
        const pickRes = await fetch('/api/sales/pickups/v2/?' + p.toString(), { signal: ctrl.signal });
        const pick = pickRes.ok ? await pickRes.json() : null;
        if (ctrl.signal.aborted) return;
        setPickup(pick);

        // 2) pricing quote — тот же принцип
        const qp = new URLSearchParams({
          excursion_id: String(excursionId),
          adults: String(adults),
          children: String(children),
          infants: '0',
          lang: 'ru',
          hotel_id: String(fam.hotel_id || ''),   // может быть пусто
          hotel_name: fam.hotel_name || '',
          date,
        });
        const quoteRes = await fetch('/api/sales/pricing/quote/?' + qp.toString(), { signal: ctrl.signal });
        const qraw = await quoteRes.json().catch(() => null);
        if (ctrl.signal.aborted) return;
        setQuote(qraw);
      } finally {
        if (!ctrl.signal.aborted) setQuoteLoading(false);
      }
    })();

    return () => ctrl.abort();
  }, [excursionId, date, fam, sel]);

  useEffect(()=>{
    if (excursions.length && !excursionId) {
      const first = excursions[0]
      const id = String(first.id)
      setExcursionId(id)
      setAvailableDates(buildNextDates(toWeekdayNums(first), 60))
    }
  }, [excursions, excursionId])

  // Сравниваем "та же" бронь?
  function sameSet(a=[], b=[]){
    const A = new Set(a.map(Number)), B = new Set(b.map(Number));
    if (A.size !== B.size) return false;
    for (const v of A) if (!B.has(v)) return false;
    return true;
  }

  function isSameBooking(b, body) {
    const bTrav = (b.travelers || (b.travelers_csv ? b.travelers_csv.split(',').map(Number) : []));
    return String(b.excursion_id) === String(body.excursion_id)
      && String(b.date) === String(body.date)
      && String(b.excursion_language||'') === String(body.excursion_language||'')
      && Number(b.pickup_point_id||0) === Number(body.pickup_point_id||0)
      && sameSet(bTrav, body.travelers || []);
  }


  const submitBooking = async ()=>{
    if (!fam || !excursionId || !date || sel.length===0 || !companyId || !excursionLanguage) return;

    // подготавливаем данные
    const adults  = (fam.party || []).filter(p=>!p.is_child && sel.includes(p.id)).length || 0;
    const children= (fam.party || []).filter(p=> p.is_child && sel.includes(p.id)).length || 0;
    const qn = normalizeQuote(quote, { adults, children, infants:0 });
    const p0 = pickup?.results?.[0] || null;

    const body = {
      date, adults, children, infants: 0,
      excursion_id: Number(excursionId),
      excursion_title: (excursions.find(x=>String(x.id)===String(excursionId))?.title) || '',
      hotel_id: fam.hotel_id ?? null,
      hotel_name: fam.hotel_name || '',
      region_name: fam.region_name || '',
      pickup_point_id: p0?.id ?? null,
      pickup_point_name: p0?.point || p0?.name || '',
      pickup_time_str: p0?.time || '',
      pickup_lat: p0?.lat ?? null,
      pickup_lng: p0?.lng ?? null,
      pickup_address: p0?.address || '',
      family_id: fam.id,
      travelers: sel,
      company_id: companyId,
      excursion_language: excursionLanguage,
      room_number: roomNumber || '',
      price_source: qn.source || 'PICKUP',
      price_per_adult: qn.perAdult ?? 0,
      price_per_child: qn.perChild ?? 0,
      gross_total: qn.gross ?? 0,
      net_total: 0,
      commission: 0,
    };

    // локальная дедупликация
    if ((drafts || []).some(d => isSameBooking(d, body))) {
      alert('Похоже, такая бронь уже есть в списке черновиков. Дубликаты не допускаются.');
      return;
    }

    setLoading(true);
    try {
      const res = await fetch(`/api/sales/bookings/create/`, {
        method: 'POST',
        headers: { 'Content-Type':'application/json' },
        body: JSON.stringify(body)
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || JSON.stringify(data));

      // обновляем черновики
      const r2 = await fetch(`/api/sales/bookings/family/${famId}/drafts/`);
      if (r2.ok) {
        const j2 = await r2.json();
        setDrafts(Array.isArray(j2) ? j2 : (j2.items || []));
      }

      // сброс формы (оставляем компанию/комнату/состав — как обсуждали)
      setExcursionId('');
      setAvailableDates([]);
      setDate('');
      setPickup(null);
      setQuote(null);
      setQuoteLoading(false);
      setExcursionLanguage('');
    } catch (e) {
      alert('Ошибка бронирования: ' + (e?.message || String(e)));
    } finally {
      setLoading(false);
    }
  };


  if(!fam) return <div style={{padding:16}}>Загрузка…</div>

  const toggle = (id)=> setSel(s => s.includes(id) ? s.filter(x=>x!==id) : [...s, id])

  const adultsCount = (fam.party || []).filter(p=>!p.is_child && sel.includes(p.id)).length
  const childrenCount = (fam.party || []).filter(p=> p.is_child && sel.includes(p.id)).length

  return (
    <div className="app-padding container">

      {/* Навигация */}
      <div className="section" style={{marginBottom:12}}>
        <div className="section__body" style={{display:'flex', gap:8}}>
          <button onClick={()=>nav(-1)} className="btn btn-outline" style={{width:'auto'}}>← Назад</button>
          <div className="muted" style={{alignSelf:'center'}}>Заезд {fam.checkin || '—'} — {fam.checkout || '—'}</div>
        </div>
      </div>

      {/* Шапка: отель + номер комнаты */}
      <div className="section">
        <div className="section__head">
          <h1>{fam.hotel_name}</h1>
        </div>
        <div className="section__body" style={{display:'grid', gap:10}}>
          <input
            value={roomNumber}
            onChange={e => setRoomNumber(e.target.value)}
            placeholder="Номер комнаты"
            className="input"
          />
        </div>
      </div>

      {/* Компания */}
      <div className="section">
        <div className="section__head">Компания</div>
        <div className="section__body">
          <select
            className="input"
            value={companyId ?? ''}
            onChange={e=> setCompanyId(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">— выберите компанию —</option>
            {(Array.isArray(companies) ? companies : []).map((c)=>(
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Язык экскурсии */}
      {availableLangs.length > 0 && (
        <div className="section">
          <div className="section__head">Язык экскурсии</div>
          <div className="section__body">
            <select
              className="input"
              value={excursionLanguage}
              onChange={e=> setExcursionLanguage(e.target.value)}
            >
              <option value="">— выберите язык —</option>
              {availableLangs.map(l => <option key={l.code} value={l.code}>{l.label}</option>)}
            </select>
          </div>
        </div>
      )}

      {/* Состав группы */}
      <div className="section">
        <div className="section__head">Кто едет</div>
        <div className="section__body" style={{display:'grid', gap:8}}>
          {(fam.party || []).map(p=>(
            <label key={p.id} className="draft" style={{display:'flex', gap:8, alignItems:'center'}}>
              <input type="checkbox" checked={sel.includes(p.id)} onChange={()=>toggle(p.id)} />
              <span>{p.full_name}{p.is_child ? ' (ребёнок)' : ''}</span>
            </label>
          ))}
          <div className="muted">Выбрано: взрослых {adultsCount}, детей {childrenCount}</div>
        </div>
      </div>

      {/* Экскурсия */}
      <div className="section">
        <div className="section__head">Экскурсия</div>
        <div className="section__body">
          <select
            className="input"
            value={excursionId}
            onChange={e=>{
              const id = e.target.value
              setExcursionId(id)
              const ex = excursions.find(x => String(x.id) === String(id))
              const weekdays = toWeekdayNums(ex)
              setAvailableDates(buildNextDates(weekdays, 60))
              setDate('')
            }}
          >
            <option value="">— выбрать —</option>
            {excursions.map(ex => (
              <option key={ex.id} value={ex.id}>
                {ex.title || ex.localized_title || `Экскурсия #${ex.id}`}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Дата */}
      <div className="section">
        <div className="section__head">Дата</div>
        <div className="section__body">
          {(() => {
            const allowed = new Set(availableDates.map(d => d.iso))
            const fromDate = new Date()
            const toDate = new Date(); toDate.setDate(toDate.getDate() + 60)
            const disabled = (d) => {
              const yyyy = d.getFullYear()
              const mm = String(d.getMonth()+1).padStart(2,'0')
              const dd = String(d.getDate()).padStart(2,'0')
              const iso = `${yyyy}-${mm}-${dd}`
              if (d < fromDate || d > toDate) return true
              return !allowed.has(iso)
            }
            return (
              <>
                <DayPicker
                  mode="single"
                  fromDate={fromDate}
                  toDate={toDate}
                  selected={date ? new Date(date) : undefined}
                  onSelect={(d) => {
                    if (!d) { setDate(''); return }
                    const yyyy = d.getFullYear()
                    const mm = String(d.getMonth()+1).padStart(2,'0')
                    const dd = String(d.getDate()).padStart(2,'0')
                    const iso = `${yyyy}-${mm}-${dd}`
                    if (allowed.has(iso)) setDate(iso)
                  }}
                  disabled={disabled}
                  weekStartsOn={1}
                  captionLayout="dropdown"
                />
                <div className="muted" style={{marginTop:8}}>
                  {date ? `Выбрано: ${new Date(date).toLocaleDateString()}` : 'Выберите доступный день'}
                </div>
              </>
            )
          })()}
        </div>
      </div>

      {/* Точка сбора (плашка) */}
      {pickup?.results?.length > 0 && (() => {
        const p0 = pickup.results[0] || {}
        const mapHref = (p0.lat && p0.lng)
          ? `https://maps.google.com/?q=${p0.lat},${p0.lng}`
          : (p0.point ? `https://maps.google.com/?q=${encodeURIComponent(p0.point)}` : null)
        return (
          <div className="section">
            <div className="section__body">
              <div className="note">
                Точка сбора: {p0.point || p0.name || '—'}
                {p0.time ? ` · ${p0.time}` : ''}
                {mapHref && <> · <a href={mapHref} target="_blank" rel="noreferrer">Открыть на карте</a></>}
              </div>
            </div>
          </div>
        )
      })()}

      {/* Стоимость */}
      {(excursionId && date && sel.length>0) && (
        <div className="section">
          <div className="section__head">
            <div>Стоимость выбранной экскурсии</div>
            {quoteLoading && <div className="muted" style={{fontSize:12}}>считаем…</div>}
          </div>
          <div className="section__body">
            {(() => {
              if (quoteLoading) {
                return <div className="muted">Пожалуйста, подождите…</div>
              }
              const adults = (fam.party || []).filter(p=>!p.is_child && sel.includes(p.id)).length || 0
              const children = (fam.party || []).filter(p=> p.is_child && sel.includes(p.id)).length || 0
              const qn = normalizeQuote(quote, { adults, children, infants:0 });
              if (!qn.ok) {
                return (
                  <div className="muted">
                    Цена пока недоступна для выбранных параметров.
                    {quote?.detail && <div style={{marginTop:6}}>{String(quote.detail)}</div>}
                  </div>
                );
              }
              return (
                <div>
                  <div style={{fontSize:22, fontWeight:800, marginBottom:6}}>
                    {fmtMoney(qn.gross, qn.currency)}
                  </div>
                  {(qn.perAdult != null || qn.perChild != null) && (
                    <div className="muted" style={{fontSize:14}}>
                      {qn.perAdult != null && <>Взрослый: {fmtMoney(qn.perAdult, qn.currency)}</>}
                      {qn.perChild != null && <> · Ребёнок: {fmtMoney(qn.perChild, qn.currency)}</>}
                    </div>
                  )}
                </div>
              )
            })()}
          </div>
        </div>
      )}
      
      {/* Основная кнопка */}
      <button
        className="btn btn-primary sticky-cta"
        disabled={
          loading || quoteLoading ||
          !excursionId || !date || sel.length===0 ||
          !companyId || !excursionLanguage
        }
        onClick={submitBooking}
        style={{marginTop:16}}
      >
        {loading ? 'Бронирую…' : 'Забронировать'}
      </button>

      {/* Черновики + отправка */}
      {Array.isArray(drafts) && drafts.length > 0 && (
        <div className="section" style={{marginTop:16}}>
          <div className="section__head">Черновики для этой семьи</div>
          <div className="section__body drafts">
            {drafts.map((b) => (
              <div key={b.id} className="draft">
                <div className="draft__row">
                  <div className="draft__title">
                    {b.excursion_title || `Экскурсия #${b.excursion_id}`}
                  </div>
                  <div className="draft__meta">{b.date || '—'}</div>
                </div>

                <div className="draft__meta" style={{marginTop:4}}>
                  {b.pickup_point_name ? `Пикап: ${b.pickup_point_name}${b.pickup_time_str ? `, ${b.pickup_time_str}` : ''}` : 'Пикап: —'}
                  {b.excursion_language ? ` · Язык: ${String(b.excursion_language).toUpperCase()}` : ''}
                  {b.room_number ? ` · Комната: ${b.room_number}` : ''}
                  {b.maps_url && <> · <a href={b.maps_url} target="_blank" rel="noreferrer">Карта</a></>}
                </div>

                <div className="draft__sum">
                  {fmtMoney(b.gross_total || 0, 'EUR')}
                </div>
              </div>
            ))}
          </div>
          <div className="section__foot">
            <div className="muted" style={{marginRight:'auto'}}>
              Итого по черновикам: <b>{fmtMoney(draftsTotal, 'EUR')}</b>
            </div>
            <button
              className="btn btn-secondary"
              onClick={async ()=>{
                if (!drafts.length) return;
                const ids = drafts.map(d=>d.id);
                const r = await fetch('/api/sales/bookings/batch/preview/', {
                  method:'POST', headers:{'Content-Type':'application/json'},
                  body: JSON.stringify({ booking_ids: ids })
                });
                const p = await r.json();
                if (!r.ok) { alert('Ошибка предпросмотра: ' + (p?.detail || r.status)); return; }
                alert(`К отправке ${ids.length} строк. После подтверждения будет отправлено письмо.`);
              }}
            >
              Предпросмотр
            </button>

            <button
              className="btn btn-primary"
              onClick={async ()=>{
                if (!drafts.length) return;

                const email = (companies.find(c=>c.id===companyId)?.email_for_orders || '').trim();
                if (!email) { alert('У выбранной компании нет email для заявок.'); return; }

                const ids = drafts.map(d=>d.id);
                const ok = confirm(`Отправить ${ids.length} броней на ${email}?`);
                if (!ok) return;

                const r2 = await fetch('/api/sales/bookings/batch/send/', {
                  method:'POST', headers:{'Content-Type':'application/json'},
                  body: JSON.stringify({ booking_ids: ids, email })
                });
                const s = await r2.json();
                if (!r2.ok) { alert('Ошибка отправки: ' + (s?.detail || r2.status)); return; }
                alert(`Отправлено. Пакет ${s.batch_code}, записей: ${s.count}`);
                setDrafts([]);
              }}
            >
              Отправить бронь
            </button>
          </div>
        </div>
      )}

    </div>
  )

}
