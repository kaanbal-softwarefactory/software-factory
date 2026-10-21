"use client";
import { useEffect, useState } from "react";
import { calendarDay, calendarWindow, monday, shiftDay } from "../lib/calendar";

type Appointment = { id: string; starts_at: string; ends_at: string; service: string; resource: string; state: string };
export default function AppointmentCalendar({ organization, timezone, revision }: { organization: string; timezone: string; revision: unknown }) {
  const today = calendarDay(new Date(), timezone);
  const [start, setStart] = useState(() => monday(today));
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [status, setStatus] = useState("Cargando calendario…");
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    setStatus("Cargando calendario…"); setFailed(false); setAppointments([]);
    const window = calendarWindow(start);
    fetch(`/api/business/${organization}/appointments?${new URLSearchParams(window)}`, { cache: "no-store" })
      .then(async (response) => {
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "No se pudo cargar el calendario");
        if (active) { setAppointments(data); setStatus(""); }
      })
      .catch((error) => { if (active) { setFailed(true); setStatus(error.message); } });
    return () => { active = false; };
  }, [organization, start, revision]);
  const days = Array.from({ length: 7 }, (_, index) => shiftDay(start, index));
  const time = (value: string) => new Intl.DateTimeFormat("es-MX", { timeZone: timezone, hour: "2-digit", minute: "2-digit" }).format(new Date(value));
  const label = (day: string) => new Intl.DateTimeFormat("es-MX", { timeZone: "UTC", weekday: "short", day: "numeric", month: "short" }).format(new Date(`${day}T12:00:00Z`));
  return <section className="card calendar" aria-label="Calendario de citas">
    <div className="section-head"><div><span className="eyebrow">Agenda del equipo</span><h2>Tu semana, a la vista.</h2><p className="muted">{label(start)} — {label(shiftDay(start, 6))} · {timezone}</p></div>
      <div className="row"><button className="secondary small" aria-label="Semana anterior" onClick={() => setStart(shiftDay(start, -7))}>←</button><button className="secondary small" onClick={() => setStart(monday(today))}>Hoy</button><button className="secondary small" aria-label="Semana siguiente" onClick={() => setStart(shiftDay(start, 7))}>→</button></div>
    </div>
    {status ? <p role={failed ? "alert" : "status"}>{status}</p> : <>
      {appointments.length >= 1000 && <p role="alert" className="status">Se alcanzó el límite de 1,000 citas del intervalo. Esta vista puede estar incompleta.</p>}
      <div className="calendar-scroll"><div className="calendar-week">{days.map((day) => {
        const items = appointments.filter((item) => item.state === "confirmed" && calendarDay(new Date(item.starts_at), timezone) === day).sort((a, b) => a.starts_at.localeCompare(b.starts_at));
        return <section key={day} className={`calendar-day${day === today ? " is-today" : ""}`}><h3>{label(day)}</h3>{items.length ? items.map((item) => <article className="calendar-event" key={item.id}><time dateTime={item.starts_at}>{time(item.starts_at)} – {time(item.ends_at)}</time><strong>{item.service}</strong><small>{item.resource}</small></article>) : <p className="muted">Sin citas</p>}</section>;
      })}</div></div>
    </>}
  </section>;
}
