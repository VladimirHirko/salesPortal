import { useEffect, useState } from 'react'
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

  useEffect(()=>{
    (async ()=>{
      const f = await fetch(`/api/sales/families/${famId}/`).then(r=>r.json())
      setFam(f); setSel(f.party?.map(p=>p.id) || [])
      // подгрузим самые популярные экскурсии (сжатый список)
      const ex = await fetch(`/api/sales/excursions/?compact=1&limit=20`).then(r=>r.json())
      setExcursions(ex.items || [])
    })()
  }, [famId])

  // когда выбрана экскурсия и дата — подтягиваем пикапы и цену
  useEffect(() => {
    if (!excursionId || !date || !fam) return;

    const adults = fam.party.filter(p => !p.is_child && sel.includes(p.id)).length || 1;
    const children = fam.party.filter(p => p.is_child && sel.includes(p.id)).length || 0;

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


  const submitBooking = async ()=>{
    if (!fam || !excursionId || !date || sel.length===0) return
    setLoading(true)
    try{
      const body = {
        family_id: fam.id,
        hotel_name: fam.hotel_name || '',
        travelers: sel,                    // список traveler.id
        excursion_id: Number(excursionId),
        date,                              // YYYY-MM-DD
        pickup_point_id: pickup?.results?.[0]?.id || null,
        pickup_time: pickup?.results?.[0]?.time || null,
        quote
      }
      const res = await fetch(`/api/sales/bookings/create/`, {
        method: 'POST',
        headers: { 'Content-Type':'application/json' },
        body: JSON.stringify(body)
      })
      const data = await res.json()
      alert(`Бронь создана: ${data.booking_code || data.status}`)
      nav(-1)
    }catch(e){
      alert('Ошибка бронирования: '+e.message)
    }finally{
      setLoading(false)
    }
  }

  if(!fam) return <div style={{padding:16}}>Загрузка…</div>

  const toggle = (id)=> setSel(s => s.includes(id) ? s.filter(x=>x!==id) : [...s, id])

  const adultsCount = fam.party.filter(p=>!p.is_child && sel.includes(p.id)).length
  const childrenCount = fam.party.filter(p=> p.is_child && sel.includes(p.id)).length

  return (
    <div className="app-padding container">
      <button onClick={()=>nav(-1)} className="card" style={{marginBottom:12, padding:'6px 10px'}}>
        ← Назад
      </button>

      <h1 style={{fontSize:20, fontWeight:700, marginBottom:8}}>
        {fam.hotel_name}
      </h1>
      <div className="muted" style={{marginBottom:12}}>
        Заезд {fam.checkin || '—'} — {fam.checkout || '—'}
      </div>

      <div style={{marginBottom:8, fontWeight:600}}>Кто едет</div>
      <div style={{display:'grid', gap:8, marginBottom:12}}>
        {fam.party.map(p=>(
          <label key={p.id} className="card person-row" style={{display:'flex', gap:8, alignItems:'center'}}>
            <input type="checkbox" checked={sel.includes(p.id)} onChange={()=>toggle(p.id)} />
            <span>{p.full_name}{p.is_child ? ' (ребёнок)' : ''}</span>
          </label>
        ))}
      </div>

      <div className="muted" style={{marginBottom:12}}>
        Выбрано: взрослых {adultsCount}, детей {childrenCount}
      </div>

      <div style={{display:'grid', gap:12, marginTop:12}}>
        <div>
          <div style={{marginBottom:6, fontWeight:600}}>Экскурсия</div>
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

        <div>
          <div style={{marginBottom:6, fontWeight:600}}>Дата</div>

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
            )
          })()}

          <div className="muted" style={{marginTop:8}}>
            {date ? `Выбрано: ${new Date(date).toLocaleDateString()}` : 'Выберите доступный день'}
          </div>
        </div>
      </div>

      {pickup?.results?.length > 0 && (
        <div className="card" style={{marginTop:12, padding:10, fontSize:14}}>
          Точка сбора: {pickup.results[0]?.point || '—'}{pickup.results[0]?.time ? ` в ${pickup.results[0].time}` : ''}
        </div>
      )}

      {(excursionId && date && sel.length>0) && (
        <div className="card" style={{marginTop:12, padding:12}}>
          <div style={{display:'flex', justifyContent:'space-between', alignItems:'baseline', gap:12}}>
            <div style={{fontWeight:700}}>Ориентировочная стоимость</div>
            {quoteLoading && <div className="muted" style={{fontSize:12}}>считаем…</div>}
          </div>

          {(() => {
            if (quoteLoading) {
              return <div className="muted" style={{marginTop:8}}>Пожалуйста, подождите…</div>
            }
            const adults = fam.party.filter(p=>!p.is_child && sel.includes(p.id)).length || 0
            const children = fam.party.filter(p=> p.is_child && sel.includes(p.id)).length || 0
            const qn = normalizeQuote(quote, { adults, children, infants:0 });
            if (!qn.ok) {
              return (
                <div className="muted" style={{marginTop:8}}>
                  Цена пока недоступна для выбранных параметров.
                  {quote?.detail && <div style={{marginTop:6}}>{String(quote.detail)}</div>}
                </div>
              );
            }


            return (
              <div style={{marginTop:10}}>
                <div style={{fontSize:22, fontWeight:800, marginBottom:6}}>
                  {fmtMoney(qn.gross, qn.currency)}
                </div>

                {(qn.perAdult != null || qn.perChild != null) && (
                  <div className="muted" style={{fontSize:14, marginTop:4}}>
                    {qn.perAdult != null && <>Взрослый: {fmtMoney(qn.perAdult, qn.currency)}</>}
                    {qn.perChild != null && <> · Ребёнок: {fmtMoney(qn.perChild, qn.currency)}</>}
                  </div>
                )}
              </div>
            )
          })()}

        </div>
      )}

      <button
        className="btn sticky-cta"
        disabled={loading || quoteLoading || !excursionId || !date || sel.length===0}
        onClick={submitBooking}
        style={{marginTop:16}}
      >
        {loading ? 'Бронирую…' : 'Забронировать'}
      </button>
    </div>
  )
}

