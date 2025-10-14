// frontend/src/screens/FamilyScreen.jsx
import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { DayPicker } from 'react-day-picker';
import Modal from '../components/Modal.jsx';
import SpecialTravelerFields from '../components/SpecialTravelerFields.jsx';

// ⚠️ используем API-хелперы — они сами ставят X-CSRFToken и делают ретрай
import {
  previewBatch,
  sendBatch,
  patchTraveler,
  cancelBooking,         // ← добавлено
  jsonFetch,             // ← для batch cancel
} from '../lib/api.js';

// ===== helpers: дни недели / даты ============================================
const WEEKDAY_CODE_TO_NUM = { mon:1, tue:2, wed:3, thu:4, fri:5, sat:6, sun:0 };

function toWeekdayNums(ex) {
  if (!ex) return [];
  if (Array.isArray(ex.available_days) && ex.available_days.length) {
    return ex.available_days.map(n => (Number(n) + 1) % 7); // Mon(1)..Sun(0)
  }
  if (Array.isArray(ex.days) && ex.days.length) {
    return ex.days.map(c => WEEKDAY_CODE_TO_NUM[c]).filter(n => n !== undefined);
  }
  return [];
}

function buildNextDates(weekdayNums, daysAhead = 60) {
  const set = new Set(weekdayNums);
  const out = [];
  const today = new Date();
  for (let i = 0; i <= daysAhead; i++) {
    const d = new Date(today);
    d.setDate(today.getDate() + i);
    if (set.size === 0 || set.has(d.getDay())) {
      const yyyy = d.getFullYear();
      const mm = String(d.getMonth() + 1).padStart(2, '0');
      const dd = String(d.getDate()).padStart(2, '0');
      out.push({ iso: `${yyyy}-${mm}-${dd}`, label: d.toLocaleDateString() });
    }
  }
  return out;
}

// ===== helpers: цены / форматирование ========================================
function normalizeQuote(raw, { adults = 0, children = 0 } = {}) {
  if (!raw || typeof raw !== 'object') return { ok: false };
  if (raw.detail) return { ok: false, error: String(raw.detail) };

  const cur = raw.currency || 'EUR';
  let gross = raw.gross ?? raw.gross_total ?? raw.total;
  if (typeof gross === 'string') gross = Number(gross.replace(',', '.'));

  let perAdult =
    raw.meta?.adult_price ?? raw.price_adult ?? raw.adult_price ?? raw.details?.price_adult ?? null;
  let perChild =
    raw.meta?.child_price ?? raw.price_child ?? raw.child_price ?? raw.details?.price_child ?? null;

  perAdult = perAdult != null ? Number(perAdult) : null;
  perChild = perChild != null ? Number(perChild) : null;

  if ((gross == null || Number.isNaN(Number(gross))) && (perAdult != null || perChild != null)) {
    const a = perAdult ?? 0;
    const c = perChild ?? perAdult ?? 0;
    gross = a * adults + c * children;
  }

  const grossNum = Number(gross ?? 0);
  return {
    ok: grossNum > 0 || perAdult != null || perChild != null,
    currency: cur,
    gross: grossNum,
    perAdult,
    perChild,
    source: raw.meta?.source || raw.source || null,
  };
}

// Универсальный парсер форматов: [], {items:[...]}, {results:[...]}
function parseItemsPayload(json) {
  if (Array.isArray(json)) return json;
  if (!json || typeof json !== 'object') return [];
  if (Array.isArray(json.items)) return json.items;
  if (Array.isArray(json.results)) return json.results;
  return [];
}

// ===== helpers: суммы/форматирование =========================================
const asNumber = v => parseFloat(String(v || 0).replace(',', '.')) || 0;

function sumByStatuses(list, statuses) {
  return (list || [])
    .filter(b => statuses.has(b.status || b.ui_state))
    .reduce((acc, b) => acc + asNumber(b.gross_total), 0);
}

const fmtMoney = (v, cur = 'EUR') =>
  new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: cur,
    maximumFractionDigits: 2,
  }).format(Number(v || 0));

// ===== helpers: черновики / сравнение ========================================
function extractTravelerIdsFromDraft(d) {
  if (!d) return [];
  if (Array.isArray(d.travelers)) return d.travelers.map(Number);
  if (typeof d.travelers_csv === 'string' && d.travelers_csv.trim()) {
    return d.travelers_csv.split(',').map(x => Number(x.trim())).filter(Number.isFinite);
  }
  return [];
}
function sameSet(a = [], b = []) {
  const A = new Set(a.map(Number)), B = new Set(b.map(Number));
  if (A.size !== B.size) return false;
  for (const v of A) if (!B.has(v)) return false;
  return true;
}
function isSameBooking(draft, body) {
  const keySame =
    String(draft.excursion_id) === String(body.excursion_id) &&
    String(draft.date) === String(body.date) &&
    Number(draft.pickup_point_id || 0) === Number(body.pickup_point_id || 0);

  if (!keySame) return false;

  const dTrav = extractTravelerIdsFromDraft(draft);
  const bTrav = Array.isArray(body.travelers) ? body.travelers.map(Number) : [];

  if (dTrav.length && bTrav.length) return sameSet(dTrav, bTrav);

  const dA = Number(draft.adults || 0);
  const dC = Number(draft.children || 0);
  const dI = Number(draft.infants || 0);
  const bA = Number(body.adults || 0);
  const bC = Number(body.children || 0);
  const bI = Number(body.infants || 0);

  return dA === bA && dC === bC && dI === bI;
}

/* спец-экскурсии + правила кнопок */
function detectSpecialKey(title='') {
  const s = String(title).toLowerCase();
  if (s.includes('танжер') || s.includes('tang')) return 'tangier';
  if (s.includes('гранад')) return 'granada';
  if (s.includes('гибрал') || s.includes('gibr')) return 'gibraltar';
  if (s.includes('севиль') || s.includes('sevil')) return 'seville';
  return 'regular';
}
const canDelete = b => (b.status || b.ui_state) === 'DRAFT';
const canCancel = b => {
  const s = (b.status || b.ui_state) || '';
  return s !== 'DRAFT' && s !== 'CANCELLED';
};
const canSend = b => (b.is_sendable === true) || ((b.status||b.ui_state) === 'DRAFT');

// ===== компонент ==============================================================
export default function FamilyScreen() {
  const params = useParams();
  const familyId = params.id ?? params.famId ?? params.familyID ?? params.familyId;
  const nav = useNavigate();

  // данные
  const [fam, setFam] = useState(null);
  const [excursions, setExcursions] = useState([]);
  const [companies, setCompanies] = useState([]);

  // выбор
  const [sel, setSel] = useState([]); // traveler.id[]
  const [roomNumber, setRoomNumber] = useState('');
  const [companyId, setCompanyId] = useState(null);
  const [excursionLanguage, setExcursionLanguage] = useState(''); // 'ru'|'en'|...
  const [excursionId, setExcursionId] = useState('');
  const [date, setDate] = useState('');

  const selectedExcursion = useMemo(
    () => excursions.find(x => String(x.id) === String(excursionId)) || null,
    [excursions, excursionId]
  );
  const selectedExcursionTitle =
    selectedExcursion?.title || selectedExcursion?.localized_title || '';

  // производные
  const [availableDates, setAvailableDates] = useState([]);
  const [pickup, setPickup] = useState(null);

  // цены
  const [quoteLoading, setQuoteLoading] = useState(false);
  const [quote, setQuote] = useState(null);

  // черновики
  const [drafts, setDrafts] = useState([]);

  // суммы
  const totalActive = useMemo(
    () => sumByStatuses(drafts, new Set(['DRAFT','PENDING','HOLD','PAID','CONFIRMED'])),
    [drafts]
  );
  const totalCancelled = useMemo(
    () => sumByStatuses(drafts, new Set(['CANCELLED','EXPIRED'])),
    [drafts]
  );

  // загрузки/ошибки
  const [bookingLoading, setBookingLoading] = useState(false);
  const [pageError, setPageError] = useState('');

  // предпросмотр (модалка)
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState('');
  const [previewData, setPreviewData] = useState(null);
  const [sending, setSending] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState([]); // id черновиков

  // ===== загрузка семьи, экскурсий, компаний =================================
  useEffect(() => {
    if (!familyId) {
      setPageError('В URL отсутствует идентификатор семьи.');
      return;
    }
    let ignore = false;

    (async () => {
      try {
        // семья
        const fRes = await fetch(`/api/sales/families/${familyId}/`, { credentials: 'include' });
        const f = await fRes.json().catch(() => null);
        if (!fRes.ok || !f) throw new Error(f?.detail || `HTTP ${fRes.status}`);
        if (ignore) return;
        setFam(f);
        setSel(Array.isArray(f.party) ? f.party.map(p => p.id) : []);
      } catch (e) {
        if (!ignore) setPageError(`Не удалось загрузить семью #${familyId}: ${e?.message || e}`);
        return;
      }

      // экскурсии
      try {
        const exRes = await fetch(`/api/sales/excursions/?compact=1&limit=20`, { credentials: 'include' });
        const exJson = exRes.ok ? await exRes.json() : null;
        if (!ignore) setExcursions(Array.isArray(exJson?.items) ? exJson.items : []);
      } catch { if (!ignore) setExcursions([]); }

      // компании
      try {
        const cRes = await fetch(`/api/sales/companies/`, { credentials: 'include' });
        const cJson = cRes.ok ? await cRes.json() : [];
        if (!ignore) setCompanies(Array.isArray(cJson) ? cJson : []);
      } catch { if (!ignore) setCompanies([]); }
    })();

    return () => { ignore = true; };
  }, [familyId]);

  // перечитать брони по семье (все статусы) + безопасный фолбэк на preview
  useEffect(() => {
    if (!familyId) return;
    let aborted = false;

    (async () => {
      try {
        const url = `/api/sales/bookings/family/${familyId}/drafts/?_=${Date.now()}`;
        const r = await fetch(url, { cache: 'no-store', credentials: 'include' });
        const text = await r.text();
        if (aborted) return;

        if (r.ok) {
          let json = [];
          try { json = text ? JSON.parse(text) : []; } catch { json = []; }
          const items = parseItemsPayload(json);
          if (aborted) return;
          if (items.length) { setDrafts(items); return; }
        }
      } catch { /* ignore */ }

      try {
        const prev = await previewBatch(familyId);
        const items = Array.isArray(prev?.items) ? prev.items : [];
        if (!aborted) setDrafts(items);
      } catch { if (!aborted) setDrafts([]); }
    })();

    return () => { aborted = true; };
  }, [familyId]);

  // доступные языки для выбранной экскурсии
  const availableLangs = useMemo(() => {
    const ex = excursions.find(x => String(x.id) === String(excursionId));
    const codesRaw = Array.isArray(ex?.languages) ? ex.languages : [];
    const codes = codesRaw.map(c => String(c).trim().toLowerCase()).filter(Boolean);

    let dn;
    try { dn = new Intl.DisplayNames([navigator.language || 'ru'], { type: 'language' }); }
    catch { dn = null; }

    return codes.map(c => ({ code: c, label: dn ? dn.of(c) || c.toUpperCase() : c.toUpperCase() }));
  }, [excursions, excursionId]);

  // если язык единственный — автоподставим
  useEffect(() => {
    if (availableLangs.length === 1) setExcursionLanguage(availableLangs[0].code);
  }, [availableLangs]);

  // если есть список экскурсий — выбрать первую и посчитать даты
  useEffect(() => {
    if (excursions.length && !excursionId) {
      const first = excursions[0];
      setExcursionId(String(first.id));
      setAvailableDates(buildNextDates(toWeekdayNums(first), 60));
    }
  }, [excursions, excursionId]);

  // когда выбрана экскурсия и дата — подтягиваем пикапы и цену
  useEffect(() => {
    if (!excursionId || !date || !fam) return;

    const adults   = (fam.party || []).filter(p => !p.is_child && sel.includes(p.id)).length || 1;
    const children = (fam.party || []).filter(p =>  p.is_child && sel.includes(p.id)).length || 0;

    const ctrl = new AbortController();
    (async () => {
      setQuoteLoading(true);
      try {
        // pickups v2
        const p = new URLSearchParams({
          excursion_id: String(excursionId),
          hotel_id: String(fam.hotel_id || ''),
          hotel_name: fam.hotel_name || '',
          date,
        });
        const pickRes = await fetch('/api/sales/pickups/v2/?' + p.toString(), {
          signal: ctrl.signal, credentials: 'include'
        });
        const pick = pickRes.ok ? await pickRes.json() : null;
        if (ctrl.signal.aborted) return;
        setPickup(pick);

        // pricing quote
        const qp = new URLSearchParams({
          excursion_id: String(excursionId),
          adults: String(adults),
          children: String(children),
          infants: '0',
          lang: 'ru',
          hotel_id: String(fam.hotel_id || ''),
          hotel_name: fam.hotel_name || '',
          date,
        });
        const quoteRes = await fetch('/api/sales/pricing/quote/?' + qp.toString(), {
          signal: ctrl.signal, credentials: 'include'
        });
        const qraw = await quoteRes.json().catch(() => null);
        if (ctrl.signal.aborted) return;
        setQuote(qraw);
      } finally {
        if (!ctrl.signal.aborted) setQuoteLoading(false);
      }
    })();

    return () => ctrl.abort();
  }, [excursionId, date, fam, sel]);

  // ===== имена/карта id -> имя ================================================
  function namesByIds(ids = [], id2name = {}) { return ids.map(id => id2name[id]).filter(Boolean); }
  const id2name = useMemo(() => {
    const map = {};
    const party = Array.isArray(fam?.party) ? fam.party : [];
    for (const p of party) {
      const full = p.full_name || [p.first_name, p.last_name].filter(Boolean).join(' ');
      map[p.id] = full || `#${p.id}`;
    }
    return map;
  }, [fam]);

  // ===== обработчик доп. полей у туристов ====================================
  function onTravelerExtraChange(id, field, value) {
    // нормализация под Django choices
    let v = value;
    if (field === 'gender') {
      const s = String(value || '').trim().toUpperCase().replace('.', '');
      v = (s === 'M' || s === 'MALE' || s === 'М' || s === 'МУЖ' || s === 'MR') ? 'M'
        : (s === 'F' || s === 'FEMALE' || s === 'Ж' || s === 'ЖЕН' || ['MRS','MS','MISS'].includes(s)) ? 'F'
        : '';
    }
    if (field === 'doc_type') {
      const s = String(value || '').trim().toLowerCase().replace('.', '');
      v = (['passport','pass','паспорт','загранпаспорт'].includes(s)) ? 'passport'
        : (['dni','id','id card','ид','удостоверение','нацпаспорт'].includes(s)) ? 'dni'
        : '';
    }
    // оптимистично обновляем локально
    setFam(f => {
      if (!f) return f;
      const party = Array.isArray(f.party) ? f.party : [];
      return { ...f, party: party.map(t => t.id === id ? { ...t, [field]: v } : t) };
    });
    // сохраняем на бэке (через API-хелпер)
    patchTraveler(id, { [field]: v }).catch(err => {
      console.error('patchTraveler failed', err);
    });
  }

  // ===== бронирование ==========================================================
  const submitBooking = async () => {
    if (!fam || !excursionId || !date || sel.length === 0 || !companyId || !excursionLanguage) return;

    const adults   = (fam.party || []).filter(p => !p.is_child && sel.includes(p.id)).length || 0;
    const children = (fam.party || []).filter(p =>  p.is_child && sel.includes(p.id)).length || 0;
    const qn = normalizeQuote(quote, { adults, children, infants: 0 });
    const p0 = pickup?.results?.[0] || null;

    const body = {
      date, adults, children, infants: 0,
      excursion_id: Number(excursionId),
      excursion_title: excursions.find(x => String(x.id) === String(excursionId))?.title || '',
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

    if ((drafts || []).some(d => isSameBooking(d, body))) {
      alert('Похоже, такая бронь уже есть в списке черновиков. Дубликаты не допускаются.');
      return;
    }

    setBookingLoading(true);
    try {
      const res = await fetch(`/api/sales/bookings/create/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(body),
      });
      const text = await res.text();
      const data = text ? JSON.parse(text) : null;
      if (!res.ok) throw new Error(data?.detail || JSON.stringify(data));

      // попытка взять id из ответа API
      let newId =
        data?.id ??
        data?.booking_id ??
        data?.booking?.id ??
        data?.result?.id ?? null;

      // перечитать черновики и найти только что созданную бронь, если id не пришёл
      let draftsList = [];
      try {
        const r2 = await fetch(`/api/sales/bookings/family/${familyId}/drafts/`, { credentials: 'include' });
        if (r2.ok) {
          const j2 = await r2.json();
          draftsList = Array.isArray(j2) ? j2 : (j2.items || []);
          setDrafts(draftsList);
        }
      } catch { /* ignore */ }

      // если id неизвестен — ищем по совпадению полей (твоя isSameBooking)
      if (!newId && draftsList.length) {
        const found = draftsList.find(d => isSameBooking(d, body));
        if (found?.id) newId = found.id;
      }

      // 🖨️ печать PDF
      openTicketAndPrint(newId);

      // сброс формы
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
      setBookingLoading(false);
    }
  };

  // ===== предпросмотр/отправка пакета ========================================
  async function loadPreview() {
    setPreviewOpen(true);
    setPreviewError('');
    setPreviewLoading(true);
    try {
      const data = await previewBatch(familyId);
      setPreviewData(data);
      setEditMode(false);
      const items = Array.isArray(data?.items) ? data.items : [];
      setSelectedIds(items.filter(canSend).map(it => it.id).filter(Boolean));
    } catch (e) {
      setPreviewData(null);
      setPreviewError(e.message || 'Ошибка предпросмотра');
    } finally {
      setPreviewLoading(false);
    }
  }

  async function sendBatchNow() {
    const items = Array.isArray(previewData?.items) ? previewData.items : [];
    const idsToSend = (editMode ? selectedIds : items.filter(canSend).map(x => x.id)).filter(Boolean);

    if (!idsToSend.length) {
      setPreviewError('Нет строк для отправки');
      return;
    }

    setSending(true);
    setPreviewError('');
    try {
      // можно и через ваш sendBatch(familyId), но тут — явные ids
      await jsonFetch('/api/sales/bookings/batch/send/', {
        method: 'POST',
        body: JSON.stringify({ booking_ids: idsToSend }),
      });

      // перечитать черновики
      const r2 = await fetch(`/api/sales/bookings/family/${familyId}/drafts/`, { credentials: 'include' });
      const j2 = r2.ok ? await r2.json() : [];
      setDrafts(Array.isArray(j2) ? j2 : (j2.items || []));
      setPreviewOpen(false);
    } catch (e) {
      setPreviewError(e.message || 'Не удалось отправить пакет');
    } finally {
      setSending(false);
    }
  }

  function openTicketAndPrint(id) {
    if (!id) return;
    const url = `/api/sales/bookings/${id}/ticket.pdf`;

    // скрытый iframe: печать после загрузки
    const iframe = document.createElement("iframe");
    iframe.style.position = "fixed";
    iframe.style.right = "0";
    iframe.style.bottom = "0";
    iframe.style.width = "0";
    iframe.style.height = "0";
    iframe.style.border = "0";
    iframe.src = url;

    iframe.onload = () => {
      try {
        iframe.contentWindow?.focus();
        iframe.contentWindow?.print();
      } catch (e) {
        // запасной путь — отдельная вкладка
        const w = window.open(url, "_blank");
        if (!w) alert("Разрешите всплывающие окна для печати билета.");
      } finally {
        setTimeout(() => iframe.remove(), 1500);
      }
    };

    document.body.appendChild(iframe);
  }

  
  function toggleRow(id) {
    setSelectedIds(ids => ids.includes(id) ? ids.filter(x => x !== id) : [...ids, id]);
  }
  function toggleAll() {
    const all = (previewData?.items || []).map(it => it.id).filter(Boolean);
    setSelectedIds(ids => ids.length === all.length ? [] : all);
  }

  async function handleDeleteSelected() {
    if (!selectedIds.length) return;
    if (!confirm(`Удалить ${selectedIds.length} черновик(ов)?`)) return;

    try {
      const ids = selectedIds.slice();
      await Promise.all(ids.map(id =>
        fetch(`/api/sales/bookings/${id}/`, { method: 'DELETE', credentials: 'include' })
      ));

      await Promise.all([
        fetch(`/api/sales/bookings/family/${familyId}/drafts/`, { credentials:'include' })
          .then(r=>r.json()).then(j=> setDrafts(Array.isArray(j)? j : (j.items||[]))),
        loadPreview()
      ]);
    } catch (e) {
      setPreviewError(e.message || 'Не удалось удалить выбранные черновики');
    }
  }

  // ←––––––––– ИСПРАВЛЕНО: используем cancelBooking/jsonFetch (CSRF ок) ––––––––→
  async function cancelOne(id) {
    const reason = window.prompt('Причина аннуляции (необязательно):', '');
    if (reason === null) return;
    try {
      await cancelBooking(id, reason); // ← всегда с токеном
      const r2 = await fetch(`/api/sales/bookings/family/${familyId}/drafts/?_=${Date.now()}`, {
        credentials: 'include'
      });
      const j2 = r2.ok ? await r2.json() : [];
      setDrafts(Array.isArray(j2) ? j2 : (j2.items || []));
    } catch (e) {
      alert('Не удалось аннулировать: ' + (e?.message || String(e)));
    }
  }

  async function handleCancelSelected() {
    if (!selectedIds.length) return;

    const items = Array.isArray(previewData?.items) ? previewData.items : [];
    const ids = items.filter(it => selectedIds.includes(it.id) && canCancel(it)).map(it => it.id);

    if (!ids.length) {
      setPreviewError('Нет строк, доступных для аннуляции.');
      return;
    }
    if (!confirm(`Аннулировать ${ids.length} бронирование(я)?`)) return;

    try {
      await jsonFetch('/api/sales/bookings/batch/cancel/', {
        method:'POST',
        body: JSON.stringify({ booking_ids: ids }),
      });
      await Promise.all([
        fetch(`/api/sales/bookings/family/${familyId}/drafts/`, { credentials:'include' })
          .then(r=>r.json()).then(j=> setDrafts(Array.isArray(j)? j : (j.items||[]))),
        loadPreview()
      ]);
    } catch (e) {
      setPreviewError(e.message || 'Не удалось аннулировать выбранные брони');
    }
  }

  function handleEdit(id) { nav(`/bookings/${id}/edit`); }

  // ===== рендер ===============================================================
  if (pageError) return <div style={{padding:16, color:'#b91c1c'}}>{pageError}</div>;
  if (!fam)     return <div style={{ padding: 16 }}>Загрузка…</div>;

  const toggle = idVal =>
    setSel(s => (s.includes(idVal) ? s.filter(x => x !== idVal) : [...s, idVal]));

  const adultsCount   = (fam.party || []).filter(p => !p.is_child && sel.includes(p.id)).length;
  const childrenCount = (fam.party || []).filter(p =>  p.is_child && sel.includes(p.id)).length;

  return (
    <div className="app-padding container">
      {/* Навигация */}
      <div className="section" style={{ marginBottom: 12 }}>
        <div className="section__body" style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => nav(-1)} className="btn btn-outline" style={{ width: 'auto' }}>
            ← Назад
          </button>
          <div className="muted" style={{ alignSelf: 'center' }}>
            Заезд {fam?.checkin || '—'} — {fam?.checkout || '—'}
          </div>
        </div>
      </div>

      {/* Шапка: отель + номер комнаты */}
      <div className="section">
        <div className="section__head">
          <h1>{fam?.hotel_name || 'Отель'}</h1>
        </div>
        <div className="section__body" style={{ display: 'grid', gap: 10 }}>
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
            onChange={e => setCompanyId(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">— выберите компанию —</option>
            {(Array.isArray(companies) ? companies : []).map(c => (
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
              onChange={e => setExcursionLanguage(e.target.value)}
            >
              <option value="">— выберите язык —</option>
              {availableLangs.map(l => (
                <option key={l.code} value={l.code}>{l.label}</option>
              ))}
            </select>
          </div>
        </div>
      )}

      {/* Состав группы */}
      <div className="section">
        <div className="section__head">Кто едет</div>
        <div className="section__body" style={{ display: 'grid', gap: 8 }}>
          {(fam?.party || []).map(p => (
            <label key={p.id} className="draft" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <input type="checkbox" checked={sel.includes(p.id)} onChange={() => toggle(p.id)} />
              <span>{p.full_name}{p.is_child ? ' (ребёнок)' : ''}</span>
            </label>
          ))}
          <div className="muted">Выбрано: взрослых {adultsCount}, детей {childrenCount}</div>
        </div>
      </div>

      {/* Доп. поля для спец-экскурсий */}
      {detectSpecialKey(selectedExcursionTitle) !== 'regular' && (
        <div className="section">
          <div className="section__head">Дополнительные данные для спец-экскурсии</div>
          <div className="section__body" style={{ display:'grid', gap:12 }}>
            {(fam?.party || [])
              .filter(t => sel.includes(t.id))
              .map(t => (
                <SpecialTravelerFields
                  key={t.id}
                  traveler={t}
                  excursionTitle={selectedExcursionTitle}
                  onChange={onTravelerExtraChange}
                />
              ))}
          </div>
        </div>
      )}

      {/* Экскурсия */}
      <div className="section">
        <div className="section__head">Экскурсия</div>
        <div className="section__body">
          <select
            className="input"
            value={excursionId}
            onChange={e => {
              const idSel = e.target.value;
              setExcursionId(idSel);
              const ex = excursions.find(x => String(x.id) === String(idSel));
              const weekdays = toWeekdayNums(ex);
              setAvailableDates(buildNextDates(weekdays, 60));
              setDate('');
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
            const allowed  = new Set(availableDates.map(d => d.iso));
            const fromDate = new Date();
            const toDate   = new Date(); toDate.setDate(toDate.getDate() + 60);
            const disabled = d => {
              const yyyy = d.getFullYear();
              const mm   = String(d.getMonth() + 1).padStart(2, '0');
              const dd   = String(d.getDate()).padStart(2, '0');
              const iso  = `${yyyy}-${mm}-${dd}`;
              if (d < fromDate || d > toDate) return true;
              return !allowed.has(iso);
            };
            return (
              <>
                <DayPicker
                  mode="single"
                  fromDate={fromDate}
                  toDate={toDate}
                  selected={date ? new Date(date) : undefined}
                  onSelect={d => {
                    if (!d) { setDate(''); return; }
                    const yyyy = d.getFullYear();
                    const mm   = String(d.getMonth() + 1).padStart(2, '0');
                    const dd   = String(d.getDate()).padStart(2, '0');
                    const iso  = `${yyyy}-${mm}-${dd}`;
                    if (allowed.has(iso)) setDate(iso);
                  }}
                  disabled={disabled}
                  weekStartsOn={1}
                  captionLayout="dropdown"
                />
                <div className="muted" style={{ marginTop: 8 }}>
                  {date ? `Выбрано: ${new Date(date).toLocaleDateString()}`
                        : 'Выберите доступный день'}
                </div>
              </>
            );
          })()}
        </div>
      </div>

      {/* Точка сбора */}
      {pickup?.results?.length > 0 && (() => {
        const p0 = pickup.results[0] || {};
        const mapHref =
          p0.lat && p0.lng ? `https://maps.google.com/?q=${p0.lat},${p0.lng}`
          : p0.point      ? `https://maps.google.com/?q=${encodeURIComponent(p0.point)}`
          : null;
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
        );
      })()}

      {/* Стоимость */}
      {excursionId && date && sel.length > 0 && (
        <div className="section">
          <div className="section__head">
            <div>Стоимость выбранной экскурсии</div>
            {quoteLoading && <div className="muted" style={{ fontSize: 12 }}>считаем…</div>}
          </div>
          <div className="section__body">
            {(() => {
              if (quoteLoading) return <div className="muted">Пожалуйста, подождите…</div>;
              const adults   = (fam?.party || []).filter(p => !p.is_child && sel.includes(p.id)).length || 0;
              const children = (fam?.party || []).filter(p =>  p.is_child && sel.includes(p.id)).length || 0;
              const qn = normalizeQuote(quote, { adults, children });
              if (!qn.ok) {
                return (
                  <div className="muted">
                    Цена пока недоступна для выбранных параметров.
                    {quote?.detail && <div style={{ marginTop: 6 }}>{String(quote.detail)}</div>}
                  </div>
                );
              }
              return (
                <div>
                  <div style={{ fontSize: 22, fontWeight: 800, marginBottom: 6 }}>
                    {fmtMoney(qn.gross, qn.currency)}
                  </div>
                  {(qn.perAdult != null || qn.perChild != null) && (
                    <div className="muted" style={{ fontSize: 14 }}>
                      {qn.perAdult != null && <>Взрослый: {fmtMoney(qn.perAdult, qn.currency)}</>}
                      {qn.perChild  != null && <> · Ребёнок: {fmtMoney(qn.perChild,  qn.currency)}</>}
                    </div>
                  )}
                </div>
              );
            })()}
          </div>
        </div>
      )}

      {/* Основная кнопка */}
      <button
        className="btn btn-primary sticky-cta"
        disabled={
          bookingLoading || quoteLoading ||
          !excursionId || !date || sel.length === 0 ||
          !companyId || !excursionLanguage
        }
        onClick={submitBooking}
        style={{ marginTop: 16 }}
      >
        {bookingLoading ? 'Бронирую…' : 'Забронировать'}
      </button>

      {/* Черновики + предпросмотр */}
      {Array.isArray(drafts) && (
        <div className="section" style={{ marginTop: 16 }}>
          <div className="section__head">Черновики для этой семьи</div>

          <div className="muted" style={{ marginBottom: 8 }}>
            <span className="badge badge-info">Готово к отправке</span>
            <span className="badge badge-warning" style={{ marginLeft: 8 }}>Отправлено</span>
            <span className="badge badge-success" style={{ marginLeft: 8 }}>Подтверждено</span>
            <span className="badge badge-muted" style={{ marginLeft: 8 }}>Отменено</span>
          </div>

          <div className="section__body drafts">
            {drafts.length === 0 && <div className="muted">Черновиков пока нет.</div>}

            {drafts.map(b => {
              const travNames =
                Array.isArray(b.travelers_names) && b.travelers_names.length
                  ? b.travelers_names
                  : namesByIds(extractTravelerIdsFromDraft(b), id2name);

              const st = b.status || b.ui_state;

              return (
                <div key={b.id} className="draft">
                  <div className="draft__row">
                    <div className="draft__title">
                      {(b.excursion_title_bi || (b.excursion_title_es && `${b.excursion_title} (${b.excursion_title_es})`) || b.excursion_title || `Экскурсия #${b.excursion_id}`)}
                      {st === "DRAFT"     && <span className="badge badge-info"     style={{ marginLeft: 8 }}>Готово к отправке</span>}
                      {st === "PENDING"   && <span className="badge badge-warning"  style={{ marginLeft: 8 }}>Отправлено</span>}
                      {st === "CONFIRMED" && <span className="badge badge-success"  style={{ marginLeft: 8 }}>Подтверждено</span>}
                      {st === "CANCELLED" && <span className="badge badge-muted"    style={{ marginLeft: 8 }}>Отменено</span>}
                    </div>
                    <div className="draft__meta">{b.date || '—'}</div>
                  </div>

                  <div className="draft__meta" style={{ marginTop: 4 }}>
                    {b.pickup_point_name
                      ? `Пикап: ${b.pickup_point_name}${b.pickup_time_str ? `, ${b.pickup_time_str}` : ''}`
                      : 'Пикап: —'}
                    {b.excursion_language ? ` · Язык: ${String(b.excursion_language).toUpperCase()}` : ''}
                    {b.room_number ? ` · Комната: ${b.room_number}` : ''}
                    {b.maps_url && <> · <a href={b.maps_url} target="_blank" rel="noreferrer">Карта</a></>}
                  </div>

                  {travNames.length > 0 && (
                    <div className="draft__meta" style={{ marginTop: 4 }}>
                      Участники: {travNames.join(', ')}
                    </div>
                  )}

                  <div className="draft__sum">{fmtMoney(b.gross_total || 0, 'EUR')}</div>
                  <div className="draft__actions" style={{ marginTop: 6, display: 'flex', gap: 6 }}>
                    {/* ПЕЧАТЬ — доступна всегда */}
                    <button
                      className="btn btn-xs btn-primary"
                      onClick={() => openTicketAndPrint(b.id)}
                      title="Печать билета"
                    >
                      Печать
                    </button>

                    {canCancel(b) && (
                      <button
                        className="btn btn-xs btn-warning"
                        onClick={() => cancelOne(b.id)}
                        title="Аннулировать бронь и отправить письмо в офис"
                      >
                        Аннулировать
                      </button>
                    )}

                    {canDelete(b) && (
                      <button
                        className="btn btn-xs btn-outline"
                        onClick={async () => {
                          if (!confirm('Удалить черновик?')) return;
                          await fetch(`/api/sales/bookings/${b.id}/`, { method: 'DELETE', credentials: 'include' });
                          const r2 = await fetch(`/api/sales/bookings/family/${familyId}/drafts/?_=${Date.now()}`, { credentials: 'include' });
                          const j2 = r2.ok ? await r2.json() : [];
                          setDrafts(Array.isArray(j2) ? j2 : (j2.items || []));
                        }}
                        title="Удалить черновик"
                      >
                        Удалить
                      </button>
                    )}
                  </div>

                </div>
              );
            })}
          </div>

          <div className="section__foot">
            <div className="muted" style={{ marginRight: 'auto' }}>
              Итого по активным: <b>{fmtMoney(totalActive, 'EUR')}</b>
              <span className="muted" style={{ marginLeft: 12 }}>
                (отменённые: {fmtMoney(totalCancelled, 'EUR')})
              </span>
            </div>
            <button className="btn btn-secondary" onClick={loadPreview}>Предпросмотр</button>
          </div>
        </div>
      )}

      {/* ===== МОДАЛКА ПРЕДПРОСМОТРА ===== */}
      <Modal open={previewOpen} onClose={() => setPreviewOpen(false)} title="Предпросмотр пакета броней">
        {previewLoading && <div className="muted">Загружаем…</div>}
        {previewError && <div className="err" style={{ marginBottom: 8 }}>{previewError}</div>}

        {previewData && (
          <>
            <div className="muted" style={{ marginBottom: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
              <span>Всего строк: <b>{previewData.count}</b> · Итого: <b>{fmtMoney(previewData.total, 'EUR')}</b></span>
              <span style={{ marginLeft: 'auto' }} />
              <button className="btn btn-outline" onClick={() => setEditMode(m => !m)}>
                {editMode ? 'Готово' : 'Редактировать'}
              </button>
            </div>

            <div className="table-wrap">
              <table className="table compact">
                <thead>
                  <tr>
                    {editMode && (
                      <th style={{ width: 28 }}>
                        <input
                          type="checkbox"
                          checked={
                            selectedIds.length > 0 &&
                            selectedIds.length === (previewData.items?.length || 0)
                          }
                          onChange={toggleAll}
                        />
                      </th>
                    )}
                    <th>Код</th>
                    <th>Экскурсия</th>
                    <th>Дата</th>
                    <th>Язык</th>
                    <th>Комната</th>
                    <th>Пикап</th>
                    <th>Время</th>
                    <th>A</th>
                    <th>C</th>
                    <th>Сумма</th>
                    {editMode && <th style={{ width: 110 }}>Действия</th>}
                  </tr>
                </thead>
                <tbody>
                  {(previewData.items || []).map(it => (
                    <tr key={it.id}>
                      {editMode && (
                        <td>
                          <input
                            type="checkbox"
                            checked={selectedIds.includes(it.id)}
                            onChange={() => toggleRow(it.id)}
                          />
                        </td>
                      )}
                      <td>{it.booking_code}</td>
                      <td>{it.excursion_title_bi || (it.excursion_title_es && `${it.excursion_title} (${it.excursion_title_es})`) || it.excursion_title}</td>
                      <td>{it.date || '—'}</td>
                      <td>{it.excursion_language || '—'}</td>
                      <td>{it.room_number || '—'}</td>
                      <td>{it.pickup_point_name || '—'}</td>
                      <td>{it.pickup_time_str || '—'}</td>
                      <td>{it.adults}</td>
                      <td>{it.children}</td>
                      <td>{fmtMoney(it.gross_total ?? 0, 'EUR')}</td>

                      {editMode && (
                        <td style={{ display: 'flex', gap: 6 }}>
                          <button className="btn btn-xs" onClick={() => handleEdit(it.id)}>Изм.</button>

                          {canDelete(it) && (
                            <button
                              className="btn btn-xs btn-outline"
                              onClick={async () => { setSelectedIds([it.id]); await handleDeleteSelected(); }}
                              title="Удалить черновик"
                            >
                              Удал.
                            </button>
                          )}

                          {canCancel(it) && (
                            <button
                              className="btn btn-xs btn-warning"
                              onClick={async () => { setSelectedIds([it.id]); await handleCancelSelected(); }}
                              title="Аннулировать бронь"
                            >
                              Аннул.
                            </button>
                          )}
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {editMode && (() => {
              const items = Array.isArray(previewData?.items) ? previewData.items : [];
              const selected = items.filter(it => selectedIds.includes(it.id));
              const canDeleteAll = selected.length > 0 && selected.every(canDelete);
              const canCancelAny = selected.some(canCancel);

              return (
                <div className="muted" style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
                  <span>Выбрано: <b>{selectedIds.length}</b></span>
                  <span style={{ marginLeft: 'auto' }} />

                  <button
                    className="btn btn-outline"
                    disabled={!canDeleteAll}
                    onClick={handleDeleteSelected}
                    title={canDeleteAll ? '' : 'Удалять можно только черновики (DRAFT)'}
                  >
                    Удалить выбранные
                  </button>

                  <button
                    className="btn btn-warning"
                    disabled={!canCancelAny}
                    onClick={handleCancelSelected}
                    title={!canCancelAny ? 'Нет строк, доступных для аннуляции' : ''}
                  >
                    Аннулировать выбранные
                  </button>
                </div>
              );
            })()}
          </>
        )}

        <div className="modal__footer">
          <button className="btn" onClick={() => setPreviewOpen(false)}>Закрыть</button>
          <button
            className="btn btn-primary"
            onClick={sendBatchNow}
            disabled={
              sending ||
              !previewData ||
              (
                editMode
                  ? selectedIds.filter(id => {
                      const it = (previewData.items || []).find(x => x.id === id);
                      return it && canSend(it);
                    }).length === 0
                  : (previewData.items || []).filter(canSend).length === 0
              )
            }
          >
            {sending ? 'Отправляем…' : 'Отправить в офис'}
          </button>
        </div>
      </Modal>
    </div>
  );
}
