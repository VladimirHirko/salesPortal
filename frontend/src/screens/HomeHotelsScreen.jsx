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
      if (qv.length < 3) { setItems([]); setLoading(false); return } // ⇐ синхронизируем с подсказкой
      setLoading(true)
      try{
        const r = await fetch(`/api/sales/hotels/?search=${encodeURIComponent(qv)}`)
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
  }, [q])

  return (
    <div className="app-padding container">
      {/* Хедер */}
      <div className="section" style={{marginBottom:12}}>
        <div className="section__body" style={{display:'flex', alignItems:'center', justifyContent:'space-between', gap:8}}>
          <h1>Выбор отеля</h1>
          {/* место под правый action при необходимости */}
          <span className="muted" style={{fontSize:12}}>{items.length ? `Найдено: ${items.length}` : ''}</span>
        </div>
      </div>

      {/* Поиск */}
      <div className="section">
        <div className="section__head">Поиск</div>
        <div className="section__body stack-8">
          <input
            value={q}
            onChange={e=>setQ(e.target.value)}
            placeholder="Начните вводить название отеля (минимум 3 символа)"
            className="input"
            autoFocus
            inputMode="search"
          />
          <div className="muted" role="status" aria-live="polite">
            {loading
              ? 'Загрузка…'
              : (q.trim().length < 3
                  ? 'Введите минимум 3 символа (например: benal, mar, sol)…'
                  : `Найдено: ${items.length}`)}
          </div>
        </div>
      </div>

      {/* Список отелей */}
      {items.length > 0 && (
        <div className="section" style={{marginTop:12}}>
          <div className="section__head">Результаты</div>
          <div className="section__body" style={{display:'grid', gap:10}}>
            {items.map(h=>(
              <button
                key={h.id}
                onClick={()=> nav(`/hotel/${h.id}?name=${encodeURIComponent(h.name || 'Отель')}`)}
                className="btn btn-ghost"
                style={{display:'flex', gap:12, justifyContent:'flex-start', width:'100%'}}
                aria-label={`Открыть отель ${h.name}`}
              >
                <img
                  src={h.photo_url || '/vite.svg'}
                  alt=""
                  style={{width:56, height:56, borderRadius:12, objectFit:'cover', flex:'0 0 56px'}}
                />
                <div style={{textAlign:'left', flex:1, minWidth:0}}>
                  <div className="title" style={{fontWeight:700, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>
                    {h.name}
                  </div>
                  <div className="meta" style={{fontSize:12}}>
                    {h.tourists_count ?? 0} туристов
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
