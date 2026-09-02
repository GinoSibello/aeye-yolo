"use strict";

const elements = {
  date: document.querySelector("#report-date"),
  refresh: document.querySelector("#refresh"),
  csv: document.querySelector("#csv-link"),
  timezone: document.querySelector("#timezone"),
  updated: document.querySelector("#updated"),
  error: document.querySelector("#error"),
  pending: document.querySelector("#pending"),
  summary: document.querySelector("#summary"),
  workstations: document.querySelector("#workstations"),
  timelines: document.querySelector("#timelines"),
  specialAreas: document.querySelector("#special-areas"),
  quality: document.querySelector("#quality"),
};

const statusText = {
  ready: "Completa",
  partial: "Parcial",
  pending: "Pendiente",
};

function localISODate(value = new Date()) {
  const offset = value.getTimezoneOffset() * 60000;
  return new Date(value.getTime() - offset).toISOString().slice(0, 10);
}

function escapeHTML(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function display(value, suffix = "", digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "Pendiente";
  }
  const rendered = typeof value === "number"
    ? value.toLocaleString("es-AR", { maximumFractionDigits: digits })
    : value;
  return `${rendered}${suffix}`;
}

function estimate(metric, key, suffix = "") {
  const status = metric?.status
    || metric?.early_departures_status
    || metric?.overtime_status;
  if (status === "not_configured") return "Pendiente";
  if (status === "insufficient_data") return "Sin datos";
  return display(metric?.[key], suffix, 1);
}

function metric(label, value, tone = "") {
  return `<div class="metric ${tone}">
    <span class="label">${escapeHTML(label)}</span>
    <strong>${escapeHTML(value)}</strong>
  </div>`;
}

function renderSummary(report) {
  const row = report.summary;
  const metrics = [
    ["Puestos", display(row.workstations, "", 0)],
    ["Personas esperadas", display(row.expected_people, "", 0)],
    ["Cobertura de datos", display(row.data_coverage_percent, "%")],
    ["Dotacion completa", display(row.staffing_coverage_percent, "%")],
    ["Horas-persona", display(row.person_hours, " h")],
    ["Horas-persona faltantes", display(row.missing_person_hours, " h")],
    ["Llegadas tarde estimadas", display(row.late_arrivals_estimated, "", 0)],
    ["Pausas excedidas estimadas", display(row.meal_overruns_estimated, "", 0)],
  ];
  elements.summary.innerHTML = metrics.map(([label, value]) =>
    metric(label, value)
  ).join("");
}

function statusBadge(status) {
  return `<span class="status ${escapeHTML(status)}">${escapeHTML(
    statusText[status] || status
  )}</span>`;
}

function renderWorkstations(rows) {
  if (!rows.length) {
    elements.workstations.innerHTML =
      '<tr><td class="empty" colspan="11">No hay puestos configurados.</td></tr>';
    return;
  }
  elements.workstations.innerHTML = rows.map((row) => {
    const schedule = row.shift_start && row.shift_end
      ? `${row.shift_start} - ${row.shift_end}`
      : "Pendiente";
    const late = estimate(
      row.arrival, "late_arrivals_estimated"
    );
    const early = row.departure?.early_departures_status === "estimated"
      ? display(row.departure.early_departures_estimated, "", 0)
      : row.departure?.early_departures_status === "insufficient_data"
        ? "Sin datos" : "Pendiente";
    const overtime = row.departure?.overtime_status === "estimated"
      ? display(row.departure.overtime_departures_estimated, "", 0)
      : row.departure?.overtime_status === "insufficient_data"
        ? "Sin datos" : "Pendiente";
    const meal = estimate(row.meal, "overruns_estimated");
    return `<tr>
      <td><span class="primary-text">${escapeHTML(row.name)}</span>
        <span class="secondary-text">${escapeHTML(row.camera_id)} · ${escapeHTML(row.zone)}</span>
      </td>
      <td>${escapeHTML(schedule)}<span class="secondary-text">${statusBadge(row.configuration_status)}</span></td>
      <td>${escapeHTML(display(row.expected_people, "", 0))}</td>
      <td>${escapeHTML(display(row.average_occupancy))}</td>
      <td>${escapeHTML(display(row.data_coverage_percent, "%"))}</td>
      <td>${escapeHTML(display(row.staffing_coverage_percent, "%"))}</td>
      <td class="${(row.missing_person_hours || 0) > 0 ? "value-danger" : ""}">${escapeHTML(display(row.missing_person_hours, " h"))}</td>
      <td class="${late !== "0" && late !== "Pendiente" ? "value-danger" : ""}">${escapeHTML(late)}</td>
      <td>${escapeHTML(early)}</td>
      <td>${escapeHTML(overtime)}</td>
      <td>${escapeHTML(meal)}</td>
    </tr>`;
  }).join("");
}

function renderTimelines(rows) {
  if (!rows.length) {
    elements.timelines.innerHTML =
      '<p class="empty">No hay ocupacion horaria disponible.</p>';
    return;
  }
  elements.timelines.innerHTML = rows.map((row) => {
    const hours = row.hourly.map((hour) => {
      const noData = hour.data_coverage_percent === null
        || hour.data_coverage_percent < 10;
      const complete = !noData
        && hour.staffing_coverage_percent !== null
        && hour.staffing_coverage_percent >= 90;
      const expected = row.expected_people || 1;
      const height = hour.average_occupancy === null
        ? 0 : Math.max(6, Math.min(100, hour.average_occupancy / expected * 100));
      const className = noData ? "no-data" : complete ? "complete" : "partial";
      const title = noData
        ? `${hour.hour}: sin datos suficientes`
        : `${hour.hour}: promedio ${display(hour.average_occupancy)}; cobertura ${display(hour.data_coverage_percent, "%")}`;
      return `<div class="hour-cell ${className}" title="${escapeHTML(title)}">
        <span class="hour-fill" style="height:${height}%"></span>
      </div>`;
    }).join("");
    return `<div class="timeline-row">
      <div class="timeline-label"><span class="primary-text">${escapeHTML(row.name)}</span>
        <span class="secondary-text">${escapeHTML(row.zone)}</span>
      </div>
      <div class="timeline-track">${hours}</div>
    </div>`;
  }).join("");
}

function areaMetric(label, value) {
  return `<dt>${escapeHTML(label)}</dt><dd>${escapeHTML(value)}</dd>`;
}

function renderSpecialAreas(rows) {
  if (!rows.length) {
    elements.specialAreas.innerHTML =
      '<p class="empty">No hay areas comunes configuradas.</p>';
    return;
  }
  elements.specialAreas.innerHTML = rows.map((row) => {
    const visitPending = row.visit_measurement === "access_line_pending";
    const role = row.role === "restroom" ? "Bano" : "Comedor";
    return `<article class="area">
      <header><div><h3>${escapeHTML(row.name)}</h3>
        <span class="secondary-text">${escapeHTML(role)} · ${escapeHTML(row.camera_id)}</span></div>
        ${statusBadge(row.configuration_status)}
      </header>
      <dl>
        ${areaMetric("Ocupacion promedio", display(row.average_occupancy))}
        ${areaMetric("Cobertura de datos", display(row.data_coverage_percent, "%"))}
        ${areaMetric("Tracks locales observados", display(row.anonymous_tracks_seen, "", 0))}
        ${areaMetric("Tiempo visible promedio", display(row.average_visible_minutes, " min"))}
        ${areaMetric("Entradas / salidas", visitPending ? "Linea pendiente" : `${row.entries} / ${row.exits}`)}
        ${areaMetric("Visitas completas", visitPending ? "Pendiente" : display(row.completed_visits, "", 0))}
        ${areaMetric("Duracion media de visita", visitPending ? "Pendiente" : display(row.average_visit_minutes, " min"))}
      </dl>
    </article>`;
  }).join("");
}

function renderQuality(report) {
  const summary = report.summary;
  const items = [
    ["Zona horaria", report.timezone],
    ["Configuracion completa", `${summary.configured_workstations}/${summary.workstations}`],
    ["Elementos pendientes", display(summary.pending_configuration, "", 0)],
    ["Cobertura del reporte", display(summary.data_coverage_percent, "%")],
  ];
  elements.quality.innerHTML = items.map(([label, value]) =>
    `<div><dt>${escapeHTML(label)}</dt><dd>${escapeHTML(value)}</dd></div>`
  ).join("");
}

function renderPending(report) {
  const count = report.summary.pending_configuration;
  elements.pending.classList.toggle("hidden", !count);
  elements.pending.textContent = count
    ? `${count} camara(s) tienen configuracion pendiente. Sus horarios, dotaciones o duraciones se muestran como pendientes.`
    : "";
}

async function loadReport() {
  const day = elements.date.value;
  elements.error.classList.add("hidden");
  elements.refresh.disabled = true;
  elements.refresh.textContent = "Actualizando...";
  elements.csv.href = `/api/reports/daily.csv?day=${encodeURIComponent(day)}`;
  try {
    const response = await fetch(
      `/api/reports/daily?day=${encodeURIComponent(day)}`,
      { cache: "no-store" }
    );
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const report = await response.json();
    elements.timezone.textContent = report.timezone;
    elements.updated.textContent = `Generado ${new Date(report.generated_at).toLocaleString("es-AR")}`;
    renderPending(report);
    renderSummary(report);
    renderWorkstations(report.workstations);
    renderTimelines(report.workstations);
    renderSpecialAreas(report.special_areas);
    renderQuality(report);
  } catch (error) {
    elements.error.textContent =
      `No se pudo cargar el reporte: ${error.message}`;
    elements.error.classList.remove("hidden");
  } finally {
    elements.refresh.disabled = false;
    elements.refresh.textContent = "Actualizar";
  }
}

elements.date.value = localISODate();
elements.date.addEventListener("change", loadReport);
elements.refresh.addEventListener("click", loadReport);
loadReport();

