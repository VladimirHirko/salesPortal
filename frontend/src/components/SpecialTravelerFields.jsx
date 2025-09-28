// frontend/src/components/SpecialTravelerFields.jsx
import { useMemo } from "react"
import DatePicker from "react-datepicker";
import "react-datepicker/dist/react-datepicker.css";

function Field({ name, children, traveler, onChange, need }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-gray-500">{children}</span>
      {name.includes("expiry") || name==="dob" ? (
        <DatePicker
          className="input"
          dateFormat="yyyy-MM-dd"
          placeholderText="дд.мм.гггг"
          selected={traveler?.[name] ? new Date(traveler[name]) : null}
          onChange={d => onChange(traveler.id, name, d ? d.toISOString().slice(0,10) : "")}
        />
      ) : (
        <input
          className="input"
          type="text"
          required={need.includes(name)}
          value={traveler?.[name] ?? ""}
          onChange={e => onChange(traveler.id, name, e.target.value)}
        />
      )}
    </label>
  );
}

export default function SpecialTravelerFields({
  traveler,       // {id, first_name, last_name, dob, nationality, passport, gender, doc_type, doc_expiry}
  excursionTitle, // строка
  onChange,       // (id, field, value) => void
}) {
  const type = useMemo(() => {
    const s = (excursionTitle||"").toLowerCase()
    if (s.includes("танжер") || s.includes("tang")) return "tangier"
    if (s.includes("гранад")) return "granada"
    if (s.includes("гибрал") || s.includes("gibr")) return "gibraltar"
    if (s.includes("севиль") || s.includes("sevil")) return "seville"
    return "regular"
  }, [excursionTitle])

  if (type === "regular") return null

  const need = {
    granada:   ["passport","nationality"],
    gibraltar: ["nationality"],
    tangier:   ["gender","doc_type","doc_expiry","passport","nationality","dob"],
    seville:   ["passport","nationality","dob"],
  }[type]

  return (
    <div className="card" style={{padding:12, marginTop:8}}>
      <div className="text-sm font-semibold mb-2">
        Доп. данные: {traveler.last_name} {traveler.first_name}
      </div>

      {type==="tangier" && (
        <div className="grid" style={{gridTemplateColumns:"repeat(3,1fr)", gap:8}}>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-gray-500">Пол</span>
            <select className="input" value={traveler.gender||""}
                    onChange={e=>onChange(traveler.id,"gender",e.target.value)}>
              <option value="">—</option>
              <option value="M">M</option>
              <option value="F">F</option>
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-gray-500">Тип документа</span>
            <select className="input" value={traveler.doc_type||""}
                    onChange={e=>onChange(traveler.id,"doc_type",e.target.value)}>
              <option value="">—</option>
              <option value="passport">Passport</option>
              <option value="dni">DNI</option>
            </select>
          </label>
          <Field name="doc_expiry" traveler={traveler} onChange={onChange} need={need}>
            Срок действия документа
          </Field>
        </div>
      )}

      {/* Общие нужные поля */}
      <div className="grid" style={{gridTemplateColumns:"repeat(3,1fr)", gap:8, marginTop:8}}>
        {need.includes("passport") && (
          <Field name="passport" traveler={traveler} onChange={onChange} need={need}>
            Номер документа
          </Field>
        )}
        {need.includes("nationality") && (
          <Field name="nationality" traveler={traveler} onChange={onChange} need={need}>
            Национальность
          </Field>
        )}
        {need.includes("dob") && (
          <Field name="dob" traveler={traveler} onChange={onChange} need={need}>
            Дата рождения
          </Field>
        )}
      </div>
    </div>
  )
}
