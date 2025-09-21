import { useEffect, useState } from 'react'
import { useParams, useSearchParams, useNavigate } from 'react-router-dom'

export default function TouristsScreen(){
  const { hotelId } = useParams()
  const [sp] = useSearchParams()
  const nav = useNavigate()
  const hotelName = decodeURIComponent(sp.get('name') || '')

  const [q, setQ] = useState('')
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)

  useEffect(()=>{
    let stop = false
    const t = setTimeout(async ()=>{
      const qv = q.trim()
      setLoading(true)
      try{
        const url = `/api/sales/tourists/?hotel_id=${encodeURIComponent(hotelId)}&hotel_name=${encodeURIComponent(hotelName)}&search=${encodeURIComponent(qv)}`
        const r = await fetch(url)
        const data = await r.json()
        const list = Array.isArray(data) ? data : (data?.items || [])
        if(!stop) setItems(list)
      }catch{
        if(!stop) setItems([])
      }finally{
        if(!stop) setLoading(false)
      }
    }, 250)
    return ()=>{ stop = true; clearTimeout(t) }
  }, [hotelId, hotelName, q])

  return (
    <div className="app-padding container">
      {/* Навигация */}
      <div className="section" style={{marginBottom:12}}>
        <div className="section__body" style={{display:'flex', gap:8}}>
          <button onClick={()=>nav(-1)} className="btn btn-outline" style={{width:'auto'}}>← Назад</button>
          <div style={{alignSelf:'center'}}>
            <h1>{hotelName || 'Туристы'}</h1>
          </div>
        </div>
      </div>

      {/* Поиск */}
      <div className="section">
        <div className="section__head">Поиск по фамилии</div>
        <div className="section__body stack-8">
          <input
            value={q}
            onChange={e=>setQ(e.target.value)}
            placeholder="Начните вводить фамилию"
            className="input"
            inputMode="search"
          />
          <div className="muted" role="status" aria-live="polite">
            {loading ? 'Загрузка…' : `Найдено: ${items.length}`}
          </div>
        </div>
      </div>

      {/* Список семей */}
      {items.length > 0 && (
        <div className="section" style={{marginTop:12}}>
          <div className="section__head">Результаты</div>
          <div className="section__body" style={{display:'grid', gap:10}}>
            {items.map(t => (
              <button
                key={t.id}
                onClick={()=> nav(`/family/${t.id}`)}
                className="btn btn-ghost"
                style={{display:'block', textAlign:'left', width:'100%'}}
                aria-label={`Открыть семью ${t.last_name} ${t.first_name}`}
              >
                <div style={{fontWeight:700}}>
                  {t.last_name} {t.first_name}
                </div>
                <div className="muted" style={{fontSize:12}}>
                  Заезд {t.checkin || '—'} — {t.checkout || '—'}
                </div>
                {Array.isArray(t.party) && t.party.length > 0 && (
                  <div className="muted" style={{marginTop:6, fontSize:12}}>
                    {t.party.map(p => `• ${p.full_name}${p.is_child ? ' (ребёнок)' : ''}`).join('  ')}
                  </div>
                )}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
