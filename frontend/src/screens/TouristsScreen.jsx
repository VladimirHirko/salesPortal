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
        const r = await fetch(`/api/sales/tourists/?hotel_id=${encodeURIComponent(hotelId)}&hotel_name=${encodeURIComponent(hotelName)}&search=${encodeURIComponent(qv)}`)
        const data = await r.json()
        const list = Array.isArray(data) ? data : (data?.items || [])
        if(!stop) setItems(list)
      }catch(e){
        if(!stop) setItems([])
      }finally{
        if(!stop) setLoading(false)
      }
    }, 250)
    return ()=>{ stop = true; clearTimeout(t) }
  }, [hotelId, q])

  return (
    <div style={{padding:16, fontFamily:'system-ui'}}>
      <button onClick={()=>nav(-1)} style={{marginBottom:12, border:'1px solid #e5e7eb', borderRadius:10, padding:'6px 10px'}}>← Назад</button>
      <h1 style={{fontSize:20, fontWeight:600, marginBottom:8}}>
        Туристы {hotelName ? `— ${hotelName}` : ''}
      </h1>
      <input
        value={q}
        onChange={e=>setQ(e.target.value)}
        placeholder="Поиск по фамилии"
        style={{width:'100%', padding:'12px 14px', border:'1px solid #e5e7eb', borderRadius:12}}
      />
      <div style={{marginTop:12, fontSize:12, color:'#6b7280'}}>
        {loading ? 'Загрузка…' : `Найдено: ${items.length}`}
      </div>

      <div style={{marginTop:12, display:'grid', gap:12}}>
        {items.map(t => (
          <div key={t.id} style={{border:'1px solid #e5e7eb', borderRadius:16, padding:12}}>
            <div style={{fontWeight:600}}>
              {t.last_name} {t.first_name}
            </div>
            <div style={{fontSize:12, color:'#6b7280'}}>
              Заезд {t.checkin} — {t.checkout}{t.room ? ` • Комната ${t.room}` : ''}
            </div>
            {Array.isArray(t.party) && t.party.length > 0 && (
              <div style={{marginTop:6, fontSize:12, color:'#6b7280'}}>
                {t.party.map(p => `• ${p.full_name}${p.is_child?' (ребёнок)':''}`).join('  ')}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
