// src/screens/HomeHotelsScreen.jsx
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

export default function HomeHotelsScreen(){
  const nav = useNavigate()
  const [q, setQ] = useState('')
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)

  useEffect(()=>{
    let stop = false
    const t = setTimeout(async ()=>{
      const qv = q.trim()
      if (qv.length < 2) { setItems([]); setLoading(false); return } // ← минимум 3 символа
      setLoading(true)
      try{
        const r = await fetch(`/api/sales/hotels/?search=${encodeURIComponent(qv)}`)
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
  }, [q])

  return (
    <div style={{padding:16, fontFamily:'system-ui'}}>
      <h1 style={{fontSize:24, fontWeight:600, marginBottom:12}}>Выбор отеля</h1>

      <input
        value={q}
        onChange={e=>setQ(e.target.value)}
        placeholder="Начните вводить название отеля"
        style={{width:'100%', padding:'12px 14px', border:'1px solid #e5e7eb', borderRadius:12}}
      />

      <div style={{marginTop:12, fontSize:12, color:'#6b7280'}}>
        {loading
          ? 'Загрузка…'
          : (q.trim().length < 3
              ? 'Введите минимум 3 символа (например: benal, mar, sol)…'
              : `Найдено: ${items.length}`)}
      </div>

      <div style={{marginTop:12, display:'grid', gap:12}}>
        {items.map(h=>(
          <button
            key={h.id}
            onClick={()=> nav(`/hotel/${h.id}?name=${encodeURIComponent(h.name || 'Отель')}`)}
            style={{
              textAlign:'left', display:'flex', gap:12,
              border:'1px solid #e5e7eb', borderRadius:16, padding:12,
              background:'white', cursor:'pointer'
            }}
          >
            <img
              src={h.photo_url || '/vite.svg'}
              alt=""
              style={{width:64, height:64, borderRadius:12, objectFit:'cover'}}
            />
            <div>
              <div style={{fontWeight:600}}>{h.name}</div>
              <div style={{fontSize:12, color:'#6b7280'}}>
                {h.tourists_count ?? 0} туристов
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}
