"use strict";

const elements = {
  date: document.querySelector("#report-date"),
  dateLabel: document.querySelector("#date-label"),
  weeklyMode: document.querySelector("#weekly-mode"),
  monthlyMode: document.querySelector("#monthly-mode"),
  dailyMode: document.querySelector("#daily-mode"),
  weeklyView: document.querySelector("#weekly-view"),
  dailyView: document.querySelector("#daily-view"),
  cameraView: document.querySelector("#camera-view"),
  refresh: document.querySelector("#refresh"),
  csv: document.querySelector("#csv-link"),
  image: document.querySelector("#image-download"),
  pdf: document.querySelector("#pdf-print"),
  timezone: document.querySelector("#timezone"),
  updated: document.querySelector("#updated"),
  error: document.querySelector("#error"),
  pending: document.querySelector("#pending"),
  downloadStatus: document.querySelector("#download-status"),
  summary: document.querySelector("#summary"),
  workstations: document.querySelector("#workstations"),
  shiftQuality: document.querySelector("#shift-quality"),
  timelines: document.querySelector("#timelines"),
  specialAreas: document.querySelector("#special-areas"),
  quality: document.querySelector("#quality"),
  weeklyPeriod: document.querySelector("#weekly-period"),
  weeklyCoverage: document.querySelector("#weekly-coverage"),
  overallGauge: document.querySelector("#overall-gauge"),
  weeklyFacts: document.querySelector("#weekly-facts"),
  workstationGauges: document.querySelector("#workstation-gauges"),
  hourlyChart: document.querySelector("#hourly-chart"),
  weeklyEvents: document.querySelector("#weekly-events"),
  occupancyRanking: document.querySelector("#occupancy-ranking"),
  weeklySpecialAreas: document.querySelector("#weekly-special-areas"),
  weeklyQuality: document.querySelector("#weekly-quality"),
  weeklyGenerated: document.querySelector("#weekly-generated"),
  weeklySheet: document.querySelector("#weekly-sheet"),
  weeklyTitle: document.querySelector("#weekly-title"),
  periodEventComparison: document.querySelector("#period-event-comparison"),
  periodTrendLabel: document.querySelector("#period-trend-label"),
  dailyEventComparison: document.querySelector("#daily-event-comparison"),
  scopeTabs: document.querySelector("#scope-tabs"),
  cameraRole: document.querySelector("#camera-role"),
  cameraTitle: document.querySelector("#camera-title"),
  cameraPeriod: document.querySelector("#camera-period"),
  cameraStatus: document.querySelector("#camera-status"),
  cameraSummary: document.querySelector("#camera-summary"),
  cameraOccupancyChart: document.querySelector("#camera-occupancy-chart"),
  cameraHourValues: document.querySelector("#camera-hour-values"),
  cameraEvents: document.querySelector("#camera-events"),
  cameraDailyEvents: document.querySelector("#camera-daily-events"),
  cameraAudit: document.querySelector("#camera-audit"),
};

const statusText = {
  ready: "Completa",
  partial: "Parcial",
  pending: "Pendiente",
  complete: "Completo",
  in_progress: "En curso",
  not_started: "No iniciado",
  not_scheduled: "No laborable",
};

let currentMode = "weekly";
let selectedCameraId = "general";
let latestReport = null;
let latestWeeklyReport = null;
let downloadStatusTimer = null;

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

function scheduleText(row) {
  if (Array.isArray(row.shifts) && row.shifts.length) {
    return row.shifts.map((shift) =>
      `${shift.name}: ${shift.start}-${shift.end}`
    ).join(" · ");
  }
  return row.shift_start && row.shift_end
    ? `${row.shift_start} - ${row.shift_end}` : "Pendiente";
}

function estimate(metric, key, suffix = "") {
  const status = metric?.status
    || metric?.early_departures_status
    || metric?.overtime_status;
  if (status === "not_configured") return "Pendiente";
  if (status === "insufficient_data") return "Sin datos";
  return display(metric?.[key], suffix, 1);
}

function formatDate(value, options) {
  return new Date(`${value}T12:00:00`).toLocaleDateString("es-AR", options);
}

function formatRange(report) {
  const startValue = report.period_start || report.date;
  const endValue = report.period_end || report.date;
  const start = formatDate(startValue, {
    day: "2-digit",
    month: "short",
  });
  const end = formatDate(endValue, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
  return startValue === endValue ? end : `${start} al ${end}`;
}

function metric(label, value, tone = "") {
  return `<div class="metric ${tone}">
    <span class="label">${escapeHTML(label)}</span>
    <strong>${escapeHTML(value)}</strong>
  </div>`;
}

function statusBadge(status) {
  return `<span class="status ${escapeHTML(status)}">${escapeHTML(
    statusText[status] || status
  )}</span>`;
}

function polarPoint(cx, cy, radius, angle) {
  const radians = angle * Math.PI / 180;
  return {
    x: cx + radius * Math.cos(radians),
    y: cy - radius * Math.sin(radians),
  };
}

function gaugeArc(startAngle, endAngle, color) {
  const start = polarPoint(110, 105, 78, startAngle);
  const end = polarPoint(110, 105, 78, endAngle);
  return `<path d="M ${start.x.toFixed(2)} ${start.y.toFixed(2)}
    A 78 78 0 0 1 ${end.x.toFixed(2)} ${end.y.toFixed(2)}"
    fill="none" stroke="${color}" stroke-width="19" stroke-linecap="butt"/>`;
}

function gaugeMarkup(value, label, detail = "", large = false) {
  const valid = typeof value === "number" && Number.isFinite(value);
  const bounded = valid ? Math.max(0, Math.min(100, value)) : 0;
  const needle = polarPoint(110, 105, 61, 180 - bounded * 1.8);
  const segments = [
    [180, 153, "#ef5350"],
    [151, 124, "#f36b45"],
    [122, 95, "#f5a623"],
    [93, 66, "#d7b813"],
    [64, 37, "#97bd14"],
    [35, 8, "#55a61b"],
    [6, 0, "#3f951b"],
  ].map(([start, end, color]) => gaugeArc(start, end, color)).join("");
  const needleMarkup = valid
    ? `<line x1="110" y1="105" x2="${needle.x.toFixed(2)}"
        y2="${needle.y.toFixed(2)}" stroke="#24332c" stroke-width="2"/>
       <circle cx="110" cy="105" r="6" fill="#fff" stroke="#24332c" stroke-width="2"/>`
    : `<circle cx="110" cy="105" r="6" fill="#fff" stroke="#8d9993" stroke-width="2"/>`;
  const valueText = valid ? display(value, "%") : "Pendiente";
  return `<div class="gauge ${large ? "large" : ""}">
    <svg viewBox="0 0 220 132" role="img"
      aria-label="${escapeHTML(label)}: ${escapeHTML(valueText)}">
      ${segments}
      ${needleMarkup}
      <text x="110" y="129" text-anchor="middle">${escapeHTML(valueText)}</text>
    </svg>
    <strong>${escapeHTML(label)}</strong>
    <span>${escapeHTML(detail)}</span>
  </div>`;
}

function renderWeeklyFacts(report) {
  const row = report.summary;
  const facts = [
    ["Puestos configurados", `${row.configured_workstations}/${row.workstations}`],
    ["Dotación simultánea", display(row.expected_people, "", 0)],
    ["Horas-persona", display(row.person_hours, " h")],
    ["Cobertura de datos", display(row.data_coverage_percent, "%")],
    ["Alertas emitidas", display(row.alerts_total, "", 0)],
  ];
  elements.weeklyFacts.innerHTML = facts.map(([label, value]) =>
    `<div><dt>${escapeHTML(label)}</dt><dd>${escapeHTML(value)}</dd></div>`
  ).join("");
}

function renderWeeklyGauges(rows) {
  if (!rows.length) {
    elements.workstationGauges.innerHTML =
      '<p class="empty">No hay puestos configurados.</p>';
    return;
  }
  elements.workstationGauges.innerHTML = rows.map((row) => {
    const expected = row.expected_people === null
      ? "Dotación pendiente"
      : `Dotación: ${row.expected_people} · Datos: ${display(
        row.data_coverage_percent, "%"
      )}`;
    return gaugeMarkup(row.occupancy_percent, row.name, expected);
  }).join("");
}

function chartMarkup(rows, options = {}) {
  const valueKey = options.valueKey || "occupancy_percent";
  const suffix = options.suffix || "%";
  const values = rows.map((row) => row[valueKey]);
  if (!values.some((value) => typeof value === "number")) {
    return '<p class="empty chart-empty">No hay ocupación horaria suficiente.</p>';
  }

  const width = 760;
  const height = 248;
  const left = 48;
  const right = 18;
  const top = 18;
  const bottom = 38;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const numeric = values.filter((value) => typeof value === "number");
  const step = options.minimumMaximum === 1 ? 1 : 20;
  const maximum = Math.max(
    options.minimumMaximum || 100,
    Math.ceil(Math.max(...numeric) / step) * step
  );
  const x = (index) => left + plotWidth * index / 23;
  const y = (value) => top + plotHeight * (1 - value / maximum);

  const gridValues = [0, maximum / 2, maximum];
  const grid = gridValues.map((value) =>
    `<g><line x1="${left}" y1="${y(value)}" x2="${width - right}"
      y2="${y(value)}" class="chart-grid"/>
      <text x="${left - 8}" y="${y(value) + 4}" text-anchor="end"
      class="chart-label">${display(value, suffix)}</text></g>`
  ).join("");

  let path = "";
  let drawing = false;
  rows.forEach((row, index) => {
    if (typeof row[valueKey] !== "number") {
      drawing = false;
      return;
    }
    path += `${drawing ? " L" : " M"} ${x(index).toFixed(1)}
      ${y(row[valueKey]).toFixed(1)}`;
    drawing = true;
  });

  const labels = rows.map((row, index) => (
    index % 3 === 0
      ? `<text x="${x(index)}" y="${height - 12}" text-anchor="middle"
        class="chart-label">${escapeHTML(row.hour.slice(0, 2))} h</text>`
      : ""
  )).join("");

  const points = rows.map((row, index) => (
    typeof row[valueKey] === "number"
      ? `<circle cx="${x(index)}" cy="${y(row[valueKey])}" r="3">
        <title>${escapeHTML(row.hour)} · ${escapeHTML(
          display(row[valueKey], suffix)
        )}</title></circle>`
      : ""
  )).join("");

  return `<svg viewBox="0 0 ${width} ${height}" role="img"
    aria-label="Ocupación promedio por hora">
    ${grid}
    ${options.target === false ? "" : `<line x1="${left}" y1="${y(100)}"
      x2="${width - right}" y2="${y(100)}" class="chart-target"/>`}
    <path d="${path.trim()}" class="chart-line"/>
    <g class="chart-points">${points}</g>
    ${labels}
  </svg>`;
}

function eventItem(label, value, detail) {
  return `<div><dt>${escapeHTML(label)}</dt>
    <dd>${escapeHTML(value)}</dd>
    <span>${escapeHTML(detail)}</span></div>`;
}

function renderWeeklyEvents(summary) {
  const events = [
    [
      "Llegadas tarde",
      display(summary.late_arrivals_estimated, "", 0),
      `Promedio: ${display(summary.average_late_minutes, " min")}`,
    ],
    [
      "Salidas anticipadas",
      display(summary.early_departures_estimated, "", 0),
      "Estimadas por dotación",
    ],
    [
      "Salidas después de hora",
      display(summary.overtime_departures_estimated, "", 0),
      "Estimadas por dotación",
    ],
    [
      "Pausas excedidas",
      display(summary.meal_overruns_estimated, "", 0),
      `Pausa media: ${display(summary.average_break_minutes, " min")}`,
    ],
  ];
  elements.weeklyEvents.innerHTML = events.map((row) =>
    eventItem(...row)
  ).join("");
}


function eventValue(value) {
  return typeof value === "number" ? value : null;
}

function eventComparisonMarkup(rows) {
  if (!rows.length) {
    return '<p class="empty">No hay puestos configurados.</p>';
  }
  const values = rows.flatMap((row) => [
    eventValue(row.arrival?.late_arrivals_estimated),
    eventValue(row.departure?.early_departures_estimated),
    row.alerts?.total || 0,
  ]).filter((value) => value !== null);
  const maximum = Math.max(1, ...values);

  const legend = `<div class="comparison-legend">
    <span><i class="late"></i>Llegadas tarde</span>
    <span><i class="early"></i>Salidas anticipadas</span>
    <span><i class="alerts"></i>Alertas</span>
  </div>`;
  const content = rows.map((row) => {
    const series = [
      ["late", eventValue(row.arrival?.late_arrivals_estimated)],
      ["early", eventValue(row.departure?.early_departures_estimated)],
      ["alerts", row.alerts?.total || 0],
    ];
    return `<div class="comparison-row">
      <strong title="${escapeHTML(row.name)}">${escapeHTML(row.name)}</strong>
      <div class="comparison-series">
        ${series.map(([className, value]) => {
          const width = value === null ? 0 : value / maximum * 100;
          return `<div><span class="comparison-track">
            <i class="${className}" style="width:${width}%"></i>
          </span><b>${escapeHTML(display(value, "", 0))}</b></div>`;
        }).join("")}
      </div>
    </div>`;
  }).join("");
  return legend + content;
}

function renderRanking(rows) {
  const ranked = rows
    .filter((row) => typeof row.occupancy_percent === "number")
    .sort((left, right) => left.occupancy_percent - right.occupancy_percent);

  if (!ranked.length) {
    elements.occupancyRanking.innerHTML =
      '<p class="empty">Agregue la dotación esperada de cada puesto para generar el ranking.</p>';
    return;
  }

  elements.occupancyRanking.innerHTML = ranked.map((row, index) => {
    const width = Math.max(3, Math.min(100, row.occupancy_percent));
    return `<div class="ranking-row">
      <span class="ranking-position">${index + 1}</span>
      <span class="ranking-name">${escapeHTML(row.name)}</span>
      <span class="ranking-bar"><i style="width:${width}%"></i></span>
      <strong>${escapeHTML(display(row.occupancy_percent, "%"))}</strong>
    </div>`;
  }).join("");
}

function renderWeeklySpecialAreas(rows) {
  if (!rows.length) {
    elements.weeklySpecialAreas.innerHTML =
      '<p class="empty">No hay áreas comunes configuradas.</p>';
    return;
  }
  elements.weeklySpecialAreas.innerHTML = rows.map((row) => {
    const role = row.role === "restroom" ? "Baño" : "Comedor";
    const measured = row.visit_measurement !== "access_line_pending";
    const duration = measured
      ? display(row.average_visit_minutes, " min")
      : "Pendiente";
    const detail = measured
      ? `${display(row.completed_visits, "", 0)} visitas completas`
      : "Falta configurar la línea de acceso";
    return `<article class="weekly-area">
      <div>
        <span class="area-role">${escapeHTML(role)}</span>
        <h4>${escapeHTML(row.name)}</h4>
      </div>
      <strong>${escapeHTML(duration)}</strong>
      <span>${escapeHTML(detail)}</span>
      <small>Ocupación media: ${escapeHTML(
        display(row.average_occupancy)
      )} · Datos: ${escapeHTML(display(row.data_coverage_percent, "%"))}</small>
    </article>`;
  }).join("");
}

function renderWeeklyPending(report) {
  const pendingWorkstations = report.workstations.filter(
    (row) => row.configuration_status !== "ready"
  ).length;
  const pendingAreas = report.special_areas.filter(
    (row) => row.configuration_status !== "ready"
  ).length;
  const pending = pendingWorkstations + pendingAreas;
  elements.pending.classList.toggle("hidden", !pending);
  elements.pending.textContent = pending
    ? `${pending} cámara(s) tienen configuración pendiente. El informe marca
      esas métricas como pendientes y no las reemplaza por cero.`
    : "";
}

function renderWeekly(report) {
  latestWeeklyReport = report;
  const summary = report.summary;
  const range = formatRange(report);
  const monthly = report.period === "monthly";
  elements.weeklyTitle.textContent = monthly
    ? "Resumen mensual de planta" : "Resumen semanal de planta";
  elements.periodTrendLabel.textContent = monthly
    ? "Comportamiento mensual" : "Comportamiento semanal";
  elements.weeklyPeriod.textContent =
    `${monthly ? "Mes" : "Semana"} del ${range}`;
  elements.overallGauge.innerHTML = gaugeMarkup(
    summary.occupancy_percent,
    "Promedio general",
    "Solo puestos con dotación configurada",
    true
  );
  renderWeeklyFacts(report);
  renderWeeklyGauges(report.workstations);
  elements.hourlyChart.innerHTML = chartMarkup(summary.hourly);
  renderWeeklyEvents(summary);
  elements.periodEventComparison.innerHTML =
    eventComparisonMarkup(report.workstations);
  renderRanking(report.workstations);
  renderWeeklySpecialAreas(report.special_areas);
  renderWeeklyPending(report);

  const coverage = summary.data_coverage_percent;
  elements.weeklyCoverage.className = "coverage-badge";
  if (typeof coverage === "number") {
    elements.weeklyCoverage.classList.add(
      coverage >= 80 ? "good" : coverage >= 50 ? "medium" : "low"
    );
  }
  elements.weeklyCoverage.textContent =
    `Cobertura ${display(coverage, "%")}`;

  elements.weeklyQuality.textContent = summary.scheduled_station_days
    ? `${summary.measured_station_days}/${summary.scheduled_station_days}
      jornadas-puesto con datos`
    : "Horarios pendientes · ocupación calculada sobre días calendario";
  elements.weeklyGenerated.textContent =
    `Generado ${new Date(report.generated_at).toLocaleString("es-AR")}`;
  elements.image.disabled = false;
  elements.pdf.disabled = false;
}

function renderSummary(report) {
  const row = report.summary;
  const metrics = [
    ["Puestos", display(row.workstations, "", 0)],
    ["Dotación simultánea", display(row.expected_people, "", 0)],
    ["Cobertura de datos", display(row.data_coverage_percent, "%")],
    ["Dotación completa", display(row.staffing_coverage_percent, "%")],
    ["Horas-persona", display(row.person_hours, " h")],
    ["Horas-persona faltantes", display(row.missing_person_hours, " h")],
    ["Llegadas tarde estimadas", display(row.late_arrivals_estimated, "", 0)],
    ["Promedio de demora", display(row.average_late_minutes, " min")],
    ["Pausas excedidas estimadas", display(row.meal_overruns_estimated, "", 0)],
    ["Alertas emitidas", display(row.alerts_total, "", 0)],
  ];
  elements.summary.innerHTML = metrics.map(([label, value]) =>
    metric(label, value)
  ).join("");
}

function renderWorkstations(rows) {
  if (!rows.length) {
    elements.workstations.innerHTML =
      '<tr><td class="empty" colspan="12">No hay puestos configurados.</td></tr>';
    return;
  }
  elements.workstations.innerHTML = rows.map((row) => {
    const schedule = scheduleText(row);
    const late = estimate(row.arrival, "late_arrivals_estimated");
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
      <td class="${(row.alerts?.total || 0) > 0 ? "value-danger" : ""}">${escapeHTML(
        display(row.alerts?.total || 0, "", 0)
      )}</td>
    </tr>`;
  }).join("");
}


function shiftEvent(metric, statusKey, valueKey) {
  const status = metric?.[statusKey];
  if (status === "not_configured") return "No aplica";
  if (status === "pending") return "Pendiente";
  if (status === "insufficient_data") return "Sin datos";
  return display(metric?.[valueKey], "", 0);
}

function renderShiftQuality(rows) {
  const shiftRows = rows.flatMap((row) =>
    (row.shifts || []).map((shift) => ({ row, shift }))
  );
  if (!shiftRows.length) {
    elements.shiftQuality.innerHTML =
      `<tr><td class="empty" colspan="9">
        No hay turnos configurados para esta fecha.
      </td></tr>`;
    return;
  }
  elements.shiftQuality.innerHTML = shiftRows.map(({ row, shift }) => {
    const coverage = shift.data_coverage_percent;
    const coverageClass = typeof coverage !== "number"
      ? "" : coverage >= 95 ? "value-good" : "value-danger";
    return `<tr>
      <td><span class="primary-text">${escapeHTML(row.name)}</span>
        <span class="secondary-text">${escapeHTML(row.camera_id)} · ${escapeHTML(row.zone)}</span>
      </td>
      <td><span class="primary-text">${escapeHTML(shift.name)}</span>
        <span class="secondary-text">${escapeHTML(`${shift.start}-${shift.end}`)}</span>
      </td>
      <td>${statusBadge(shift.period_status)}</td>
      <td class="${coverageClass}">${escapeHTML(display(coverage, "%"))}</td>
      <td>${escapeHTML(display(shift.average_occupancy))}</td>
      <td>${escapeHTML(display(shift.staffing_coverage_percent, "%"))}</td>
      <td>${escapeHTML(shiftEvent(
        shift.arrival, "status", "late_arrivals_estimated"
      ))}</td>
      <td>${escapeHTML(shiftEvent(
        shift.departure,
        "early_departures_status",
        "early_departures_estimated"
      ))}</td>
      <td>${escapeHTML(shiftEvent(
        shift.meal, "status", "overruns_estimated"
      ))}</td>
    </tr>`;
  }).join("");
}

function renderTimelines(rows) {
  if (!rows.length) {
    elements.timelines.innerHTML =
      '<p class="empty">No hay ocupación horaria disponible.</p>';
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
      '<p class="empty">No hay áreas comunes configuradas.</p>';
    return;
  }
  elements.specialAreas.innerHTML = rows.map((row) => {
    const visitPending = row.visit_measurement === "access_line_pending";
    const role = row.role === "restroom" ? "Baño" : "Comedor";
    return `<article class="area">
      <header><div><h3>${escapeHTML(row.name)}</h3>
        <span class="secondary-text">${escapeHTML(role)} · ${escapeHTML(row.camera_id)}</span></div>
        ${statusBadge(row.configuration_status)}
      </header>
      <dl>
        ${areaMetric("Ocupación promedio", display(row.average_occupancy))}
        ${areaMetric("Cobertura de datos", display(row.data_coverage_percent, "%"))}
        ${areaMetric("Tracks locales observados", display(row.anonymous_tracks_seen, "", 0))}
        ${areaMetric("Tiempo visible promedio", display(row.average_visible_minutes, " min"))}
        ${areaMetric("Entradas / salidas", visitPending ? "Línea pendiente" : `${row.entries} / ${row.exits}`)}
        ${areaMetric("Visitas completas", visitPending ? "Pendiente" : display(row.completed_visits, "", 0))}
        ${areaMetric("Duración media de visita", visitPending ? "Pendiente" : display(row.average_visit_minutes, " min"))}
      </dl>
    </article>`;
  }).join("");
}

function renderQuality(report) {
  const summary = report.summary;
  const items = [
    ["Zona horaria", report.timezone],
    ["Configuración completa", `${summary.configured_workstations}/${summary.workstations}`],
    ["Elementos pendientes", display(summary.pending_configuration, "", 0)],
    ["Cobertura del reporte", display(summary.data_coverage_percent, "%")],
  ];
  elements.quality.innerHTML = items.map(([label, value]) =>
    `<div><dt>${escapeHTML(label)}</dt><dd>${escapeHTML(value)}</dd></div>`
  ).join("");
}

function renderDailyPending(report) {
  const count = report.summary.pending_configuration;
  elements.pending.classList.toggle("hidden", !count);
  elements.pending.textContent = count
    ? `${count} cámara(s) tienen configuración pendiente. Sus horarios,
      dotaciones o duraciones se muestran como pendientes.`
    : "";
}

function renderDaily(report) {
  renderDailyPending(report);
  renderSummary(report);
  elements.dailyEventComparison.innerHTML =
    eventComparisonMarkup(report.workstations);
  renderWorkstations(report.workstations);
  renderShiftQuality(report.workstations);
  renderTimelines(report.workstations);
  renderSpecialAreas(report.special_areas);
  renderQuality(report);
}


function reportCameras(report) {
  return [...(report.workstations || []), ...(report.special_areas || [])];
}

function roleName(role) {
  if (role === "restroom") return "Baño";
  if (role === "dining") return "Comedor";
  return "Puesto de trabajo";
}

function renderScopeTabs(report) {
  const cameras = reportCameras(report);
  const buttons = [
    { id: "general", name: "General" },
    ...cameras.map((row) => ({ id: row.camera_id, name: row.name })),
  ];
  elements.scopeTabs.innerHTML = buttons.map((row) =>
    `<button class="scope-option" type="button" data-camera="${escapeHTML(row.id)}">
      ${escapeHTML(row.name)}
    </button>`
  ).join("");
  elements.scopeTabs.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      selectedCameraId = button.dataset.camera;
      renderCurrentScope();
    });
  });
}

function workstationHourly(row) {
  return (row.hourly || []).map((hour) => ({
    ...hour,
    occupancy_percent: typeof hour.occupancy_percent === "number"
      ? hour.occupancy_percent
      : row.expected_people && typeof hour.average_occupancy === "number"
        ? hour.average_occupancy / row.expected_people * 100 : null,
  }));
}

function cameraDailyRows(row, report) {
  if (Array.isArray(row.daily)) return row.daily;
  if (row.role !== "workstation") return [];
  return [{
    date: report.date,
    scheduled: row.scheduled,
    occupancy_percent: row.occupancy_percent,
    data_coverage_percent: row.data_coverage_percent,
    late_arrivals_estimated: row.arrival?.late_arrivals_estimated ?? null,
    early_departures_estimated:
      row.departure?.early_departures_estimated ?? null,
    overtime_departures_estimated:
      row.departure?.overtime_departures_estimated ?? null,
    meal_overruns_estimated: row.meal?.overruns_estimated ?? null,
    alerts_total: row.alerts?.total || 0,
  }];
}

function eventBarsMarkup(items) {
  const numeric = items
    .map((item) => item.value)
    .filter((value) => typeof value === "number");
  const maximum = Math.max(1, ...numeric);
  return items.map((item) => {
    const width = typeof item.value === "number"
      ? item.value / maximum * 100 : 0;
    return `<div class="event-bar-row">
      <span>${escapeHTML(item.label)}</span>
      <span class="event-bar-track"><i class="${item.tone}"
        style="width:${width}%"></i></span>
      <strong>${escapeHTML(display(item.value, "", 0))}</strong>
      <small>${escapeHTML(item.detail || "")}</small>
    </div>`;
  }).join("");
}

function dailyEventChart(rows) {
  const measured = rows.filter((row) => row.scheduled !== false);
  if (!measured.length) {
    return '<p class="empty">No hay jornadas configuradas para este período.</p>';
  }
  const values = measured.flatMap((row) => [
    row.late_arrivals_estimated,
    row.early_departures_estimated,
    row.alerts_total,
  ]).filter((value) => typeof value === "number");
  const maximum = Math.max(1, ...values);
  return `<div class="daily-chart-legend">
      <span><i class="late"></i>Tarde</span>
      <span><i class="early"></i>Anticipada</span>
      <span><i class="alerts"></i>Alertas</span>
    </div>
    <div class="daily-columns">
      ${measured.map((row) => {
        const bars = [
          ["late", row.late_arrivals_estimated],
          ["early", row.early_departures_estimated],
          ["alerts", row.alerts_total],
        ];
        return `<div class="daily-column">
          <div class="daily-bars">
            ${bars.map(([tone, value]) => {
              const height = typeof value === "number" && value > 0
                ? Math.max(8, value / maximum * 100) : 0;
              return `<i class="${tone}" style="height:${height}%"
                title="${escapeHTML(row.date)} · ${tone}: ${escapeHTML(
                  display(value, "", 0)
                )}"></i>`;
            }).join("")}
          </div>
          <time datetime="${escapeHTML(row.date)}">${escapeHTML(
            formatDate(row.date, { day: "2-digit", month: "2-digit" })
          )}</time>
        </div>`;
      }).join("")}
    </div>`;
}

function auditMarkup(items) {
  return items.map(([label, value]) =>
    `<div><dt>${escapeHTML(label)}</dt><dd>${escapeHTML(value)}</dd></div>`
  ).join("");
}

function renderCamera(row) {
  const workstation = row.role === "workstation";
  const alerts = row.alerts || { total: 0, missing: 0, extra: 0 };
  elements.cameraRole.textContent =
    `${roleName(row.role)} · ${row.camera_id} · ${row.zone}`;
  elements.cameraTitle.textContent = row.name;
  elements.cameraPeriod.textContent = formatRange(latestReport);
  elements.cameraStatus.className =
    `status ${row.configuration_status || "pending"}`;
  elements.cameraStatus.textContent =
    statusText[row.configuration_status] || row.configuration_status;

  if (workstation) {
    elements.cameraSummary.innerHTML = [
      ["Ocupación promedio", display(row.occupancy_percent, "%")],
      ["Esperadas por turno", display(row.expected_people, "", 0)],
      ["Cobertura de datos", display(row.data_coverage_percent, "%")],
      ["Dotación completa", display(row.staffing_coverage_percent, "%")],
      ["Llegadas tarde", display(row.arrival?.late_arrivals_estimated, "", 0)],
      ["Demora promedio", display(row.arrival?.average_late_minutes, " min")],
      ["Salidas anticipadas", display(
        row.departure?.early_departures_estimated, "", 0
      )],
      ["Alertas emitidas", display(alerts.total, "", 0)],
    ].map(([label, value]) => metric(label, value)).join("");

    const hourly = workstationHourly(row);
    elements.cameraOccupancyChart.innerHTML = chartMarkup(hourly);
    elements.cameraHourValues.innerHTML = hourly.map((hour) =>
      `<div><time>${escapeHTML(hour.hour)}</time><strong>${escapeHTML(
        display(hour.occupancy_percent, "%")
      )}</strong><small>Datos ${escapeHTML(
        display(hour.data_coverage_percent, "%")
      )}</small></div>`
    ).join("");
    elements.cameraEvents.innerHTML = eventBarsMarkup([
      {
        label: "Llegadas tarde", tone: "late",
        value: row.arrival?.late_arrivals_estimated,
        detail: `Promedio ${display(row.arrival?.average_late_minutes, " min")}`,
      },
      {
        label: "Salidas anticipadas", tone: "early",
        value: row.departure?.early_departures_estimated,
        detail: `Promedio ${display(
          row.departure?.average_early_minutes, " min"
        )}`,
      },
      {
        label: "Después de hora", tone: "overtime",
        value: row.departure?.overtime_departures_estimated,
        detail: `Promedio ${display(
          row.departure?.average_overtime_minutes, " min"
        )}`,
      },
      {
        label: "Pausas excedidas", tone: "breaks",
        value: row.meal?.overruns_estimated,
        detail: `Pausa media ${display(
          row.meal?.average_break_minutes, " min"
        )}`,
      },
      {
        label: "Alertas de dotación", tone: "alerts",
        value: alerts.total,
        detail: `${alerts.missing} faltantes · ${alerts.extra} sobrantes`,
      },
    ]);
    elements.cameraDailyEvents.innerHTML =
      dailyEventChart(cameraDailyRows(row, latestReport));
    elements.cameraAudit.innerHTML = auditMarkup([
      ["Turnos", scheduleText(row)],
      ["Tolerancia de llegada", display(
        row.arrival_grace_minutes, " min"
      )],
      ["Días medidos", display(
        row.measured_days ?? (row.valid_seconds > 0 ? 1 : 0), "", 0
      )],
      ["Horas-persona faltantes", display(row.missing_person_hours, " h")],
      ["Método", "Estimación anónima por cupos de ocupación"],
      ["Cobertura", display(row.data_coverage_percent, "%")],
    ]);
  } else {
    elements.cameraSummary.innerHTML = [
      ["Ocupación promedio", display(row.average_occupancy)],
      ["Cobertura de datos", display(row.data_coverage_percent, "%")],
      ["Entradas", display(row.entries, "", 0)],
      ["Salidas", display(row.exits, "", 0)],
      ["Visitas completas", display(row.completed_visits, "", 0)],
      ["Duración media", display(row.average_visit_minutes, " min")],
      ["Percentil 95", display(row.p95_visit_minutes, " min")],
      ["Alertas emitidas", display(alerts.total, "", 0)],
    ].map(([label, value]) => metric(label, value)).join("");
    elements.cameraOccupancyChart.innerHTML = chartMarkup(
      row.hourly || [],
      {
        valueKey: "average_occupancy",
        suffix: " personas",
        minimumMaximum: 1,
        target: false,
      }
    );
    elements.cameraHourValues.innerHTML = (row.hourly || []).map((hour) =>
      `<div><time>${escapeHTML(hour.hour)}</time><strong>${escapeHTML(
        display(hour.average_occupancy)
      )}</strong><small>personas</small></div>`
    ).join("");
    elements.cameraEvents.innerHTML = eventBarsMarkup([
      { label: "Entradas", value: row.entries, tone: "late", detail: "" },
      { label: "Salidas", value: row.exits, tone: "early", detail: "" },
      {
        label: "Visitas completas", value: row.completed_visits,
        tone: "breaks", detail: "",
      },
      {
        label: "Alertas configuradas", value: alerts.total,
        tone: "alerts", detail: "No son eventos de llegada laboral",
      },
    ]);
    elements.cameraDailyEvents.innerHTML =
      '<p class="empty">La evolución diaria de visitas estará disponible cuando la línea de acceso esté configurada y genere cruces.</p>';
    elements.cameraAudit.innerHTML = auditMarkup([
      ["Tipo de cámara", roleName(row.role)],
      ["Medición de visitas", row.visit_measurement === "fifo_estimate"
        ? "Estimación FIFO anónima" : "Línea de acceso pendiente"],
      ["Sesiones visibles", display(row.visible_sessions, "", 0)],
      ["Tiempo visible promedio", display(row.average_visible_minutes, " min")],
      ["Cobertura", display(row.data_coverage_percent, "%")],
    ]);
  }
}

function renderCurrentScope() {
  const general = selectedCameraId === "general";
  const longPeriod = currentMode !== "daily";
  elements.weeklyView.classList.toggle("hidden", !general || !longPeriod);
  elements.dailyView.classList.toggle("hidden", !general || longPeriod);
  elements.cameraView.classList.toggle("hidden", general);
  elements.csv.classList.toggle("hidden", currentMode !== "daily" || !general);
  elements.image.classList.toggle("hidden", !longPeriod || !general);
  elements.pdf.classList.toggle("hidden", !longPeriod || !general);
  elements.scopeTabs.querySelectorAll("button").forEach((button) => {
    const active = button.dataset.camera === selectedCameraId;
    button.classList.toggle("active", active);
    button.setAttribute("aria-current", active ? "page" : "false");
  });
  if (!general && latestReport) {
    const row = reportCameras(latestReport).find(
      (camera) => camera.camera_id === selectedCameraId
    );
    if (row) renderCamera(row);
  }
}

function setMode(mode, load = true) {
  currentMode = mode;
  selectedCameraId = "general";
  latestReport = null;
  const states = {
    weekly: elements.weeklyMode,
    monthly: elements.monthlyMode,
    daily: elements.dailyMode,
  };
  Object.entries(states).forEach(([name, button]) => {
    const active = name === mode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  elements.dateLabel.textContent = mode === "weekly"
    ? "Semana que contiene"
    : mode === "monthly" ? "Mes que contiene" : "Fecha";
  renderCurrentScope();
  if (load) loadReport();
}

async function loadReport() {
  const selected = elements.date.value;
  const longPeriod = currentMode !== "daily";
  elements.error.classList.add("hidden");
  elements.refresh.disabled = true;
  elements.refresh.textContent = "Actualizando...";
  elements.image.disabled = true;
  elements.pdf.disabled = true;
  elements.csv.href =
    `/api/reports/daily.csv?day=${encodeURIComponent(selected)}`;

  try {
    const endpoint = currentMode === "weekly"
      ? `/api/reports/weekly?week=${encodeURIComponent(selected)}`
      : currentMode === "monthly"
        ? `/api/reports/monthly?month=${encodeURIComponent(selected)}`
        : `/api/reports/daily?day=${encodeURIComponent(selected)}`;
    const response = await fetch(endpoint, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const report = await response.json();
    latestReport = report;
    latestWeeklyReport = longPeriod ? report : null;
    selectedCameraId = "general";
    elements.timezone.textContent = report.timezone;
    elements.updated.textContent =
      `Generado ${new Date(report.generated_at).toLocaleString("es-AR")}`;
    if (longPeriod) {
      renderWeekly(report);
    } else {
      renderDaily(report);
    }
    renderScopeTabs(report);
    renderCurrentScope();
  } catch (error) {
    elements.error.textContent =
      `No se pudo cargar el reporte: ${error.message}`;
    elements.error.classList.remove("hidden");
  } finally {
    elements.refresh.disabled = false;
    elements.refresh.textContent = "Actualizar";
    if (!longPeriod) {
      elements.image.disabled = true;
      elements.pdf.disabled = true;
    }
  }
}

function stylesheetText() {
  const rules = [];
  for (const sheet of document.styleSheets) {
    try {
      rules.push(...Array.from(sheet.cssRules, (rule) => rule.cssText));
    } catch (error) {
      continue;
    }
  }
  return rules.join("\n");
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.style.display = "none";
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 10000);
}

function showDownloadStatus(message) {
  window.clearTimeout(downloadStatusTimer);
  elements.downloadStatus.textContent = message;
  elements.downloadStatus.classList.remove("hidden");
  downloadStatusTimer = window.setTimeout(() => {
    elements.downloadStatus.classList.add("hidden");
  }, 10000);
}

async function downloadWeeklyImage() {
  if (!latestWeeklyReport) return;
  elements.image.disabled = true;
  elements.image.textContent = "Preparando imagen...";
  const stage = document.createElement("div");
  stage.className = "export-stage";
  const clone = elements.weeklySheet.cloneNode(true);
  clone.classList.add("export-copy");
  stage.append(clone);
  document.body.append(stage);

  try {
    if (document.fonts?.ready) await document.fonts.ready;
    await new Promise((resolve) => requestAnimationFrame(resolve));
    const width = 1400;
    const height = Math.ceil(clone.scrollHeight);
    const markup = new XMLSerializer().serializeToString(clone);
    const svg = `<svg xmlns="http://www.w3.org/2000/svg"
      width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
      <foreignObject width="100%" height="100%">
        <div xmlns="http://www.w3.org/1999/xhtml">
          <style>${stylesheetText()}</style>
          ${markup}
        </div>
      </foreignObject>
    </svg>`;
    const svgBlob = new Blob([svg], { type: "image/svg+xml;charset=utf-8" });
    const source = URL.createObjectURL(svgBlob);
    const image = new Image();
    await new Promise((resolve, reject) => {
      image.onload = resolve;
      image.onerror = reject;
      image.src = source;
    });
    const scale = 1.5;
    const canvas = document.createElement("canvas");
    canvas.width = width * scale;
    canvas.height = height * scale;
    const context = canvas.getContext("2d");
    context.scale(scale, scale);
    context.drawImage(image, 0, 0, width, height);
    URL.revokeObjectURL(source);
    const png = await new Promise((resolve) =>
      canvas.toBlob(resolve, "image/png")
    );
    if (!png) throw new Error("El navegador no pudo generar el PNG");
    const prefix = latestWeeklyReport.period === "monthly"
      ? "mes" : "semana";
    const start = latestWeeklyReport.period_start
      || latestWeeklyReport.week_start;
    const end = latestWeeklyReport.period_end
      || latestWeeklyReport.week_end;
    const filename = `aeye-${prefix}-${start}-${end}.png`;
    downloadBlob(png, filename);
    showDownloadStatus(
      `Descarga iniciada: ${filename}. Revise Descargas en este equipo.`
    );
  } catch (error) {
    elements.error.textContent =
      `No se pudo generar la imagen: ${error.message}`;
    elements.error.classList.remove("hidden");
  } finally {
    stage.remove();
    elements.image.disabled = false;
    elements.image.textContent = "Descargar imagen";
  }
}

function printWeeklyReport() {
  if (!latestWeeklyReport) return;
  showDownloadStatus(
    "Se abrió la impresión. Elija Guardar como PDF y seleccione una carpeta."
  );
  document.body.classList.add("printing-weekly");
  window.print();
  window.setTimeout(() => {
    document.body.classList.remove("printing-weekly");
  }, 500);
}

elements.date.value = localISODate();
elements.weeklyMode.addEventListener("click", () => setMode("weekly"));
elements.monthlyMode.addEventListener("click", () => setMode("monthly"));
elements.dailyMode.addEventListener("click", () => setMode("daily"));
elements.date.addEventListener("change", loadReport);
elements.refresh.addEventListener("click", loadReport);
elements.image.addEventListener("click", downloadWeeklyImage);
elements.pdf.addEventListener("click", printWeeklyReport);
window.addEventListener("afterprint", () => {
  document.body.classList.remove("printing-weekly");
});

setMode("weekly", false);
loadReport();
