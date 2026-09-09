"use strict";

const elements = {
  title: document.querySelector("#page-title"),
  back: document.querySelector("#back-to-grid"),
  toggle: document.querySelector("#preview-toggle"),
  statusDot: document.querySelector("#preview-status"),
  statusLabel: document.querySelector("#preview-label"),
  cameraCount: document.querySelector("#camera-count"),
  error: document.querySelector("#error"),
  loading: document.querySelector("#loading"),
  grid: document.querySelector("#camera-grid"),
};

const cards = new Map();
let focusedCamera = null;
let previewEnabled = false;
let refreshMs = 1000;

const ruleLabels = {
  ok: "Dotación normal",
  missing: "Faltantes",
  extra: "Sobrantes",
  confirming: "Confirmando",
  recovering: "Recuperando",
  countdown: "Incidente activo",
  alert: "Alerta",
  disabled: "Solo métricas",
  no_data: "Sin datos",
  starting: "Iniciando",
  unknown: "Desconocido",
};

function cameraDisplayName(cameraId, camera) {
  return camera.name || cameraId;
}

function makeElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function settleCameraImage(cameraId, imageIndex, loaded) {
  const view = cards.get(cameraId);
  if (!view || view.pendingImage !== imageIndex) return;
  const image = view.images[imageIndex];
  if (!loaded) {
    image.removeAttribute("src");
    view.pendingImage = null;
    view.pendingRevision = null;
    if (view.activeImage === null) {
      view.frame.classList.remove("available");
      view.placeholder.textContent = "Imagen no disponible";
    }
    return;
  }

  for (const [index, candidate] of view.images.entries()) {
    const active = index === imageIndex;
    candidate.classList.toggle("active", active);
    candidate.setAttribute("aria-hidden", String(!active));
    candidate.alt = active ? view.imageAlt : "";
  }
  view.activeImage = imageIndex;
  view.loadedRevision = view.pendingRevision;
  view.pendingImage = null;
  view.pendingRevision = null;
  view.frame.classList.add("available");
  view.placeholder.textContent = "Esperando imagen";
}

function createCameraCard(cameraId, camera) {
  const card = makeElement("article", "camera-card");
  card.dataset.cameraId = cameraId;
  card.setAttribute("aria-hidden", "false");

  const header = makeElement("header", "camera-header");
  const titleGroup = makeElement("div", "camera-title");
  const title = makeElement("h2");
  const meta = makeElement("div", "camera-meta");
  titleGroup.append(title, meta);

  const actions = makeElement("div", "camera-actions");
  const connection = makeElement("span", "connection");
  const expand = makeElement("button", "expand-button", "⛶");
  expand.type = "button";
  expand.title = `Ampliar ${cameraDisplayName(cameraId, camera)}`;
  expand.setAttribute(
    "aria-label",
    `Ampliar ${cameraDisplayName(cameraId, camera)}`
  );
  expand.setAttribute("aria-pressed", "false");
  expand.addEventListener("click", () => focusCamera(cameraId));
  actions.append(connection, expand);
  header.append(titleGroup, actions);

  const frame = makeElement("div", "camera-frame");
  frame.tabIndex = 0;
  frame.setAttribute("role", "button");
  frame.setAttribute(
    "aria-label",
    `Ampliar ${cameraDisplayName(cameraId, camera)}`
  );
  const images = [0, 1].map((imageIndex) => {
    const image = makeElement("img", "camera-image");
    image.decoding = "async";
    image.alt = "";
    image.setAttribute("aria-hidden", "true");
    image.addEventListener(
      "load", () => settleCameraImage(cameraId, imageIndex, true)
    );
    image.addEventListener(
      "error", () => settleCameraImage(cameraId, imageIndex, false)
    );
    return image;
  });
  const placeholder = makeElement(
    "span",
    "frame-placeholder",
    "Esperando imagen"
  );
  frame.addEventListener("dblclick", () => {
    if (focusedCamera === cameraId) {
      clearFocus();
    } else {
      focusCamera(cameraId);
    }
  });
  frame.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    if (focusedCamera === cameraId) {
      clearFocus();
    } else {
      focusCamera(cameraId);
    }
  });
  frame.append(...images, placeholder);

  const footer = makeElement("footer", "camera-footer");
  const people = makeElement("span", "people-count");
  const rule = makeElement("span", "rule-state");
  footer.append(people, rule);

  card.append(header, frame, footer);
  cards.set(cameraId, {
    card,
    title,
    meta,
    connection,
    expand,
    frame,
    images,
    activeImage: null,
    imageAlt: "",
    imageRevision: null,
    loadedRevision: null,
    pendingImage: null,
    pendingRevision: null,
    placeholder,
    people,
    rule,
  });
  elements.grid.append(card);
  updateCameraCard(cameraId, camera);
}

function updateCameraCard(cameraId, camera) {
  const view = cards.get(cameraId);
  if (!view) return;

  const displayName = cameraDisplayName(cameraId, camera);
  view.title.textContent = displayName;
  view.meta.textContent = [cameraId, camera.zone].filter(Boolean).join(" · ");
  view.connection.textContent = camera.connected ? "En línea" : "Sin conexión";
  view.connection.classList.toggle("offline", !camera.connected);
  view.people.textContent = camera.people === null
    || camera.people === undefined
    ? "Sin datos"
    : `${camera.people} persona${camera.people === 1 ? "" : "s"}`;

  const state = camera.rule_state || camera.data_status || "unknown";
  view.rule.textContent = ruleLabels[state] || state;
  view.rule.className = "rule-state";
  if (["missing", "extra", "confirming", "countdown"].includes(state)) {
    view.rule.classList.add("warning");
  }
  if (state === "alert") view.rule.classList.add("alert");

  view.expand.title = `Ampliar ${displayName}`;
  view.expand.setAttribute("aria-label", `Ampliar ${displayName}`);
  view.frame.setAttribute("aria-label", `Ampliar ${displayName}`);
  view.imageAlt = `Vista de ${displayName}`;
  view.imageRevision = camera.image_revision ?? null;
  if (view.activeImage !== null) {
    view.images[view.activeImage].alt = view.imageAlt;
  }
}

function syncCameras(cameras) {
  const cameraIds = Object.keys(cameras).sort((left, right) =>
    left.localeCompare(right, undefined, { numeric: true })
  );

  for (const [cameraId, view] of cards) {
    if (cameraIds.includes(cameraId)) continue;
    view.card.remove();
    cards.delete(cameraId);
  }

  for (const cameraId of cameraIds) {
    if (!cards.has(cameraId)) {
      createCameraCard(cameraId, cameras[cameraId]);
    } else {
      updateCameraCard(cameraId, cameras[cameraId]);
    }
  }

  elements.loading.classList.add("hidden");
  elements.cameraCount.textContent =
    `${cameraIds.length} cámara${cameraIds.length === 1 ? "" : "s"}`;

  if (focusedCamera && !cards.has(focusedCamera)) clearFocus();
  const hashCamera = decodeURIComponent(location.hash.slice(1));
  if (!focusedCamera && hashCamera && cards.has(hashCamera)) {
    focusCamera(hashCamera, false);
  }
}

function setPreviewState(enabled) {
  previewEnabled = Boolean(enabled);
  elements.statusDot.classList.toggle("active", previewEnabled);
  elements.statusLabel.textContent = previewEnabled
    ? "Preview activo"
    : "Preview desactivado";
  elements.toggle.textContent = previewEnabled
    ? "Desactivar preview"
    : "Activar preview";
  elements.toggle.href = previewEnabled ? "/preview/off" : "/preview/on";
  elements.toggle.classList.toggle("active", previewEnabled);

  if (!previewEnabled) {
    for (const view of cards.values()) {
      view.frame.classList.remove("available");
      for (const image of view.images) {
        image.removeAttribute("src");
        image.classList.remove("active");
        image.alt = "";
        image.setAttribute("aria-hidden", "true");
      }
      view.activeImage = null;
      view.loadedRevision = null;
      view.pendingImage = null;
      view.pendingRevision = null;
      view.placeholder.textContent = "Preview desactivado";
    }
  }
}

function refreshImages() {
  if (!previewEnabled) return;
  for (const [cameraId, view] of cards) {
    if (focusedCamera && focusedCamera !== cameraId) continue;
    const revision = view.imageRevision;
    if (
      revision === null
      || revision === undefined
      || revision === view.loadedRevision
      || view.pendingImage !== null
    ) {
      continue;
    }
    const imageIndex = view.activeImage === 0 ? 1 : 0;
    const image = view.images[imageIndex];
    view.pendingImage = imageIndex;
    view.pendingRevision = revision;
    if (view.activeImage === null) {
      view.placeholder.textContent = "Esperando imagen";
    }
    image.src = `/camera/${encodeURIComponent(cameraId)}.jpg?v=${
      encodeURIComponent(revision)
    }`;
  }
}

function focusCamera(cameraId, updateHash = true) {
  if (!cards.has(cameraId)) return;
  focusedCamera = cameraId;
  document.body.classList.add("focus-mode");
  elements.grid.classList.add("focus-mode");
  elements.back.classList.remove("hidden");

  for (const [currentId, view] of cards) {
    const selected = currentId === cameraId;
    view.card.classList.toggle("is-focused", selected);
    view.card.setAttribute("aria-hidden", String(!selected));
    view.expand.setAttribute("aria-pressed", String(selected));
  }

  const selected = cards.get(cameraId);
  elements.title.textContent = selected.title.textContent;
  document.title = `${selected.title.textContent} · AEYE Preview`;
  if (updateHash) {
    history.replaceState(null, "", `#${encodeURIComponent(cameraId)}`);
  }
  refreshImages();
}

function clearFocus(updateHash = true) {
  focusedCamera = null;
  document.body.classList.remove("focus-mode");
  elements.grid.classList.remove("focus-mode");
  elements.back.classList.add("hidden");
  elements.title.textContent = "Preview de cámaras";
  document.title = "AEYE Preview";

  for (const view of cards.values()) {
    view.card.classList.remove("is-focused");
    view.card.setAttribute("aria-hidden", "false");
    view.expand.setAttribute("aria-pressed", "false");
  }

  if (updateHash) {
    history.replaceState(null, "", location.pathname + location.search);
  }
  refreshImages();
}

async function updateViewer() {
  try {
    const response = await fetch("/preview-state.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    refreshMs = Math.max(500, Number(payload.refresh_ms) || 1000);
    syncCameras(payload.cameras || {});
    setPreviewState(payload.preview_enabled);
    refreshImages();
    elements.error.classList.add("hidden");
  } catch (error) {
    elements.error.textContent =
      `No se pudo actualizar el visor: ${error.message}`;
    elements.error.classList.remove("hidden");
  } finally {
    window.setTimeout(updateViewer, refreshMs);
  }
}

elements.back.addEventListener("click", () => clearFocus());
window.addEventListener("hashchange", () => {
  const cameraId = decodeURIComponent(location.hash.slice(1));
  if (cameraId && cards.has(cameraId)) {
    focusCamera(cameraId, false);
  } else {
    clearFocus(false);
  }
});
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && focusedCamera) clearFocus();
});

updateViewer();

