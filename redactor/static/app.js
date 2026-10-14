const state = {
  doc: null,
  page: 0,
  width: 0,
  height: 0,
  words: [],
  redactions: [],
  strings: [],
  mode: "click",
  color: "#111111",
  colorName: "Black",
  custom: false,
  prompt: null,
  assurance: "The original file stays untouched.",
};

const openButton = document.getElementById("open-button");
const emptyOpen = document.getElementById("empty-open");
const fileInput = document.getElementById("file-input");
const filename = document.getElementById("filename");
const pager = document.getElementById("pager");
const pageLabel = document.getElementById("page-label");
const prevButton = document.getElementById("prev");
const nextButton = document.getElementById("next");
const empty = document.getElementById("empty");
const paperFrame = document.getElementById("paper-frame");
const paper = document.getElementById("paper");
const pageImage = document.getElementById("page-image");
const overlay = document.getElementById("overlay");
const stageError = document.getElementById("stage-error");
const modeDrag = document.getElementById("mode-drag");
const modeClick = document.getElementById("mode-click");
const prompt = document.getElementById("prompt");
const promptText = document.getElementById("prompt-text");
const promptAll = document.getElementById("prompt-all");
const promptOne = document.getElementById("prompt-one");
const swatches = document.querySelectorAll(".swatch");
const customWrap = document.getElementById("custom-wrap");
const customColor = document.getElementById("custom-color");
const colorName = document.getElementById("color-name");
const stringList = document.getElementById("strings");
const list = document.getElementById("list");
const elsewhere = document.getElementById("elsewhere");
const alertBox = document.getElementById("alert");
const assurance = document.getElementById("assurance");
const saveButton = document.getElementById("save");
const dropVeil = document.getElementById("drop-veil");
const live = document.getElementById("live");

let loadToken = 0;
let drag = null;
let hover = null;
let band = null;
let saving = false;
let opening = false;
let dragDepth = 0;

openButton.addEventListener("click", () => fileInput.click());
emptyOpen.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => {
  const file = fileInput.files && fileInput.files[0];
  fileInput.value = "";
  if (file) openFile(file);
});
prevButton.addEventListener("click", () => changePage(-1));
nextButton.addEventListener("click", () => changePage(1));
modeDrag.addEventListener("click", () => setMode("drag"));
modeClick.addEventListener("click", () => setMode("click"));
promptAll.addEventListener("click", redactAll);
promptOne.addEventListener("click", dismissPrompt);
saveButton.addEventListener("click", saveCopy);

swatches.forEach((swatch) => {
  swatch.addEventListener("click", () => selectSwatch(swatch.dataset.color, swatch.dataset.name));
});
customColor.addEventListener("input", () => selectCustom(customColor.value));

overlay.addEventListener("pointermove", onPointerMove);
overlay.addEventListener("pointerdown", onPointerDown);
overlay.addEventListener("pointerup", onPointerUp);
overlay.addEventListener("pointercancel", cancelDrag);
overlay.addEventListener("click", onClick);

window.addEventListener("keydown", onKeyDown);
window.addEventListener("dragenter", onDragEnter);
window.addEventListener("dragover", onDragOver);
window.addEventListener("dragleave", onDragLeave);
window.addEventListener("drop", onDrop);

renderChrome();
loadSession();

async function loadSession() {
  try {
    const session = await request("/api/session");
    if (session.open) applySession(session, 0);
  } catch (error) {
    showStageError(error.message);
  }
}

async function openFile(file) {
  if (opening) return;
  if (state.redactions.length > 0) {
    const discard = window.confirm("Opening another PDF discards redactions you have not saved.");
    if (!discard) return;
  }
  opening = true;
  openButton.disabled = true;
  emptyOpen.disabled = true;
  clearStageError();
  try {
    const session = await request("/api/open", {
      method: "POST",
      headers: {
        "Content-Type": "application/pdf",
        "X-Filename": encodeURIComponent(file.name || "document.pdf"),
      },
      body: file,
    });
    state.prompt = null;
    clearDownload();
    applySession(session, 0);
    live.textContent = `Opened ${session.name}.`;
  } catch (error) {
    showStageError(error.message);
  } finally {
    opening = false;
    openButton.disabled = false;
    emptyOpen.disabled = false;
  }
}

function applySession(session, page) {
  state.doc = { id: session.docId, name: session.name, pageCount: session.pageCount };
  state.redactions = session.redactions || [];
  state.strings = session.strings || [];
  state.page = clampPage(page);
  renderChrome();
  showPage(state.page);
}

async function showPage(index) {
  if (!state.doc) return;
  const token = ++loadToken;
  const page = clampPage(index);
  state.page = page;
  renderChrome();
  try {
    const info = await request(`/api/pages/${page}/words`);
    if (token !== loadToken) return;
    state.width = info.width;
    state.height = info.height;
    state.words = info.words;
    paper.style.aspectRatio = `${info.width} / ${info.height}`;
    paperFrame.hidden = false;
    empty.hidden = true;
    const scale = pageScale(info.width);
    pageImage.style.opacity = "0";
    pageImage.alt = `Page ${page + 1} of ${state.doc.pageCount}`;
    pageImage.onload = () => {
      if (token === loadToken) pageImage.style.opacity = "1";
    };
    pageImage.src = `/api/pages/${page}?scale=${scale}&doc=${encodeURIComponent(state.doc.id)}`;
    drawOverlay();
  } catch (error) {
    if (token !== loadToken) return;
    showStageError(error.message);
  }
}

function pageScale(pdfWidth) {
  const target = Math.min(paperFrame.clientWidth || 780, 780);
  const raw = (target * (window.devicePixelRatio || 1)) / pdfWidth;
  return Math.max(1.25, Math.min(3, Math.round(raw * 100) / 100));
}

function setMode(mode) {
  if (!state.doc) return;
  state.mode = mode;
  renderChrome();
  drawOverlay();
}

function selectSwatch(color, name) {
  state.color = color;
  state.colorName = name;
  state.custom = false;
  renderChrome();
}

function selectCustom(color) {
  state.color = color;
  state.colorName = "Custom";
  state.custom = true;
  renderChrome();
}

function changePage(delta) {
  if (!state.doc) return;
  const next = state.page + delta;
  if (next < 0 || next >= state.doc.pageCount) return;
  showPage(next);
}

async function onClick(event) {
  if (state.mode !== "click" || !state.doc || drag) return;
  const point = eventToPdf(event);
  const word = wordAt(point.x, point.y);
  if (!word) return;
  await addRedaction(word.x0, word.y0, word.x1, word.y1, word.text);
}

function onPointerDown(event) {
  if (state.mode !== "drag" || !state.doc) return;
  if (event.button !== undefined && event.button !== 0) return;
  const point = eventToPdf(event);
  drag = { x: point.x, y: point.y, pointerId: event.pointerId };
  overlay.setPointerCapture(event.pointerId);
  ensureBand();
  placeBox(band, point.x, point.y, point.x, point.y);
  paintBand();
}

function onPointerMove(event) {
  if (drag) {
    const point = eventToPdf(event);
    placeBox(band, drag.x, drag.y, point.x, point.y);
    return;
  }
  if (state.mode !== "click" || !state.doc) {
    clearHover();
    return;
  }
  const point = eventToPdf(event);
  const word = wordAt(point.x, point.y);
  if (!word) {
    clearHover();
    return;
  }
  if (!hover) {
    hover = document.createElement("div");
    hover.className = "hover-word";
    overlay.append(hover);
  }
  placeBox(hover, word.x0, word.y0, word.x1, word.y1);
}

function cancelDrag() {
  drag = null;
  if (band) band.remove();
  band = null;
}

function onPointerUp(event) {
  if (!drag) return;
  const point = eventToPdf(event);
  const start = drag;
  drag = null;
  if (band) band.remove();
  band = null;
  const x0 = Math.min(start.x, point.x);
  const y0 = Math.min(start.y, point.y);
  const x1 = Math.max(start.x, point.x);
  const y1 = Math.max(start.y, point.y);
  if (x1 - x0 < 3 || y1 - y0 < 3) return;
  addRedaction(x0, y0, x1, y1, null);
}

async function addRedaction(x0, y0, x1, y1, text) {
  clearAlert();
  const color = state.color;
  try {
    const result = await request("/api/redactions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page: state.page, x0, y0, x1, y1, text, color }),
    });
    applyActivity(result);
    if (text && result.remaining > 0) {
      state.prompt = { text, color, remaining: result.remaining };
    } else if (state.prompt && state.prompt.text === text) {
      state.prompt = null;
    }
    live.textContent = text ? `Redacted ${text}.` : "Redacted the marked area.";
    renderChrome();
    drawOverlay();
  } catch (error) {
    showAlert(error.message);
  }
}

async function redactAll() {
  if (!state.prompt) return;
  await redactString(state.prompt.text, state.prompt.color);
}

async function redactString(text, color) {
  clearAlert();
  try {
    const result = await request("/api/redactions/all", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, color }),
    });
    applyActivity(result);
    if (state.prompt && state.prompt.text === text) state.prompt = null;
    live.textContent = result.added ? `Redacted every ${text}.` : `Every ${text} is already redacted.`;
    renderChrome();
    drawOverlay();
  } catch (error) {
    showAlert(error.message);
  }
}

function applyActivity(result) {
  state.redactions = result.redactions || [];
  state.strings = result.strings || [];
}

function dismissPrompt() {
  state.prompt = null;
  renderChrome();
}

async function undo(id) {
  clearAlert();
  try {
    const result = await request(`/api/redactions/${encodeURIComponent(id)}`, { method: "DELETE" });
    applyActivity(result);
    if (state.prompt && !state.redactions.some((item) => item.text === state.prompt.text)) {
      state.prompt = null;
    }
    live.textContent = "Removed a redaction.";
    renderChrome();
    drawOverlay();
  } catch (error) {
    showAlert(error.message);
  }
}

let downloadUrl = "";

async function saveCopy() {
  if (!state.doc || state.redactions.length === 0 || saving) return;
  saving = true;
  saveButton.disabled = true;
  saveButton.textContent = "Saving…";
  clearAlert();
  const suggested = suggestedName(state.doc.name);
  try {
    const chosen = await chooseSavePath(suggested);
    if (chosen === null) return;
    if (chosen) {
      await request("/api/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: chosen }),
      });
      noteSaved("Saved the copy. The original was not changed.");
      return;
    }
    const response = await fetch("/api/save", { method: "POST" });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || "The copy couldn't be saved. Try again.");
    }
    const blob = await response.blob();
    const name = filenameFromDisposition(response.headers.get("Content-Disposition")) || suggested;
    offerDownload(blob, name);
    noteSaved("Saved a copy to your downloads. The original was not changed.");
  } catch (error) {
    showAlert(plainError(error));
  } finally {
    saving = false;
    saveButton.textContent = "Save a copy";
    renderChrome();
  }
}

function clearDownload() {
  if (downloadUrl) URL.revokeObjectURL(downloadUrl);
  downloadUrl = "";
  const link = document.getElementById("download-link");
  link.hidden = true;
  link.removeAttribute("href");
}

function offerDownload(blob, name) {
  if (downloadUrl) URL.revokeObjectURL(downloadUrl);
  downloadUrl = URL.createObjectURL(blob);
  const link = document.getElementById("download-link");
  link.href = downloadUrl;
  link.download = name;
  link.textContent = "Download the copy";
  link.hidden = false;
  const trigger = document.createElement("a");
  trigger.href = downloadUrl;
  trigger.download = name;
  document.body.append(trigger);
  trigger.click();
  trigger.remove();
}

function plainError(error) {
  const message = error && error.message ? error.message : "";
  if (!message || /Failed to execute|user agent|FileSystemFileHandle/.test(message)) {
    return "The copy couldn't be saved. Try again.";
  }
  return message;
}

async function chooseSavePath(suggested) {
  const api = window.pywebview && window.pywebview.api;
  if (!api || typeof api.choose_save_path !== "function") return "";
  try {
    const path = await api.choose_save_path(suggested);
    return path || null;
  } catch {
    return "";
  }
}

function noteSaved(message) {
  assurance.textContent = message;
  window.setTimeout(() => {
    assurance.textContent = state.assurance;
  }, 4000);
}

function renderChrome() {
  const open = Boolean(state.doc);
  filename.hidden = !open;
  filename.textContent = open ? state.doc.name : "";
  pager.hidden = !open;
  if (open) {
    pageLabel.textContent = `${state.page + 1} / ${state.doc.pageCount}`;
    prevButton.disabled = state.page === 0;
    nextButton.disabled = state.page >= state.doc.pageCount - 1;
  }
  modeDrag.disabled = !open;
  modeClick.disabled = !open;
  modeDrag.setAttribute("aria-pressed", state.mode === "drag" ? "true" : "false");
  modeClick.setAttribute("aria-pressed", state.mode === "click" ? "true" : "false");
  overlay.classList.toggle("mode-drag", state.mode === "drag");
  swatches.forEach((swatch) => {
    swatch.disabled = !open;
    const selected = !state.custom && swatch.dataset.color === state.color;
    swatch.setAttribute("aria-checked", selected ? "true" : "false");
  });
  customColor.disabled = !open;
  customWrap.classList.toggle("is-selected", state.custom);
  colorName.textContent = state.colorName;
  if (state.prompt && open) {
    const count = state.prompt.remaining;
    prompt.hidden = false;
    promptText.textContent = `\u201C${state.prompt.text}\u201D appears ${count} more ${count === 1 ? "time" : "times"}.`;
  } else {
    prompt.hidden = true;
  }
  renderStrings();
  renderList();
  saveButton.disabled = !open || state.redactions.length === 0 || saving;
  if (!open) {
    empty.hidden = false;
    paperFrame.hidden = true;
  }
}

function renderStrings() {
  stringList.replaceChildren();
  if (!state.doc) {
    const item = document.createElement("li");
    item.className = "empty-row";
    item.textContent = "Strings you redact are kept here.";
    stringList.append(item);
    return;
  }
  if (state.strings.length === 0) {
    const item = document.createElement("li");
    item.className = "empty-row";
    item.textContent = "No strings yet.";
    stringList.append(item);
    return;
  }
  for (const entry of state.strings) {
    const item = document.createElement("li");
    item.className = "item";
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.style.background = entry.color;
    if (isLight(entry.color)) chip.classList.add("light-chip");
    const copy = document.createElement("span");
    copy.className = "string-copy";
    const label = document.createElement("span");
    label.className = "item-label";
    label.textContent = entry.text;
    const meta = document.createElement("span");
    meta.className = "string-meta";
    meta.textContent = entry.remaining === 0
      ? "All redacted"
      : `${entry.remaining} more in this file`;
    copy.append(label, meta);
    item.append(chip, copy);
    if (entry.remaining > 0) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "string-action";
      button.textContent = "Redact all";
      button.setAttribute("aria-label", `Redact every ${entry.text}`);
      button.addEventListener("click", () => redactString(entry.text, state.color));
      item.append(button);
    }
    stringList.append(item);
  }
}

function renderList() {
  list.replaceChildren();
  if (!state.doc) {
    const item = document.createElement("li");
    item.className = "empty-row";
    item.textContent = "Open a PDF to start.";
    list.append(item);
    elsewhere.hidden = true;
    return;
  }
  const onPage = state.redactions.filter((item) => item.page === state.page).slice().reverse();
  const other = state.redactions.length - onPage.length;
  if (onPage.length === 0) {
    const item = document.createElement("li");
    item.className = "empty-row";
    item.textContent = "Nothing on this page yet.";
    list.append(item);
  } else {
    for (const redaction of onPage) {
      const item = document.createElement("li");
      item.className = "item";
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.style.background = redaction.color;
      if (isLight(redaction.color)) chip.classList.add("light-chip");
      const label = document.createElement("span");
      label.className = "item-label";
      label.textContent = redaction.text || "Marked area";
      const undoButton = document.createElement("button");
      undoButton.type = "button";
      undoButton.className = "undo";
      undoButton.setAttribute("aria-label", `Undo ${redaction.text || "marked area"}`);
      undoButton.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" d="M8 8.5H4.8V5.2M5.2 13.2a6.6 6.6 0 1 0 1.1-4.1L4.8 8.5"/></svg> Undo';
      undoButton.addEventListener("click", () => undo(redaction.id));
      item.append(chip, label, undoButton);
      list.append(item);
    }
  }
  elsewhere.hidden = other === 0;
  elsewhere.textContent = other === 1 ? "1 more on another page" : `${other} more on other pages`;
}

function drawOverlay() {
  clearHover();
  overlay.querySelectorAll(".block").forEach((node) => node.remove());
  if (!state.width || !state.height) return;
  for (const redaction of state.redactions) {
    if (redaction.page !== state.page) continue;
    const block = document.createElement("div");
    block.className = "block";
    block.style.background = redaction.color;
    if (isLight(redaction.color)) block.classList.add("light-block");
    placeBox(block, redaction.x0, redaction.y0, redaction.x1, redaction.y1);
    overlay.append(block);
  }
}

function ensureBand() {
  if (band) return;
  band = document.createElement("div");
  band.className = "band";
  overlay.append(band);
}

function paintBand() {
  if (!band) return;
  band.style.background = hexToRgba(state.color, 0.35);
  band.style.border = `1.5px solid ${isLight(state.color) ? "#1c1b19" : state.color}`;
}

function placeBox(element, x0, y0, x1, y1) {
  if (!state.width || !state.height) return;
  const left = Math.min(x0, x1);
  const top = Math.min(y0, y1);
  const width = Math.abs(x1 - x0);
  const height = Math.abs(y1 - y0);
  element.style.left = `${(left / state.width) * 100}%`;
  element.style.top = `${(top / state.height) * 100}%`;
  element.style.width = `${(width / state.width) * 100}%`;
  element.style.height = `${(height / state.height) * 100}%`;
}

function eventToPdf(event) {
  const rect = overlay.getBoundingClientRect();
  return {
    x: ((event.clientX - rect.left) / rect.width) * state.width,
    y: ((event.clientY - rect.top) / rect.height) * state.height,
  };
}

function wordAt(x, y) {
  let inside = null;
  let insideArea = Infinity;
  let closest = null;
  let closestDistance = 8;
  for (const word of state.words) {
    if (covered(word)) continue;
    const area = Math.max(0, word.x1 - word.x0) * Math.max(0, word.y1 - word.y0);
    if (x >= word.x0 && x <= word.x1 && y >= word.y0 && y <= word.y1) {
      if (area < insideArea) {
        inside = word;
        insideArea = area;
      }
      continue;
    }
    const nearestX = Math.min(Math.max(x, word.x0), word.x1);
    const nearestY = Math.min(Math.max(y, word.y0), word.y1);
    const distance = Math.hypot(x - nearestX, y - nearestY);
    if (distance < closestDistance) {
      closestDistance = distance;
      closest = word;
    }
  }
  return inside || closest;
}

function covered(word) {
  return state.redactions.some((redaction) => {
    if (redaction.page !== state.page) return false;
    const width = Math.max(0, Math.min(word.x1, redaction.x1) - Math.max(word.x0, redaction.x0));
    const height = Math.max(0, Math.min(word.y1, redaction.y1) - Math.max(word.y0, redaction.y0));
    const wordArea = Math.max(0.001, (word.x1 - word.x0) * (word.y1 - word.y0));
    return (width * height) / wordArea >= 0.6;
  });
}

function clearHover() {
  if (hover) hover.remove();
  hover = null;
}

function clampPage(page) {
  if (!state.doc) return 0;
  return Math.max(0, Math.min(state.doc.pageCount - 1, page));
}

function isLight(hex) {
  const value = hex.replace("#", "");
  if (value.length !== 6) return false;
  const red = parseInt(value.slice(0, 2), 16);
  const green = parseInt(value.slice(2, 4), 16);
  const blue = parseInt(value.slice(4, 6), 16);
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue > 220;
}

function hexToRgba(hex, alpha) {
  const value = hex.replace("#", "");
  const red = parseInt(value.slice(0, 2), 16);
  const green = parseInt(value.slice(2, 4), 16);
  const blue = parseInt(value.slice(4, 6), 16);
  return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

function suggestedName(name) {
  const stem = name.replace(/\.pdf$/i, "");
  if (stem.toLowerCase().endsWith("-redacted")) return `${stem}.pdf`;
  return `${stem}-redacted.pdf`;
}

function filenameFromDisposition(header) {
  if (!header) return "";
  const star = header.match(/filename\*=UTF-8''([^;]+)/i);
  if (star) return decodeURIComponent(star[1]);
  const plain = header.match(/filename="([^"]+)"/i);
  return plain ? plain[1] : "";
}

function showStageError(message) {
  stageError.hidden = false;
  stageError.textContent = message;
}

function clearStageError() {
  stageError.hidden = true;
  stageError.textContent = "";
}

function showAlert(message) {
  alertBox.hidden = false;
  alertBox.textContent = message;
}

function clearAlert() {
  alertBox.hidden = true;
  alertBox.textContent = "";
}

function onKeyDown(event) {
  const key = event.key.toLowerCase();
  const command = event.ctrlKey || event.metaKey;
  if (command && key === "o") {
    event.preventDefault();
    fileInput.click();
    return;
  }
  if (command && key === "s") {
    event.preventDefault();
    saveCopy();
    return;
  }
  if (event.target && event.target.closest && event.target.closest("input, textarea")) return;
  if (event.key === "ArrowRight") {
    event.preventDefault();
    changePage(1);
  } else if (event.key === "ArrowLeft") {
    event.preventDefault();
    changePage(-1);
  } else if (event.key === "Escape") {
    dismissPrompt();
  }
}

function isFileDrag(event) {
  return Array.from(event.dataTransfer ? event.dataTransfer.types : []).includes("Files");
}

function onDragEnter(event) {
  if (!isFileDrag(event)) return;
  event.preventDefault();
  dragDepth += 1;
  dropVeil.hidden = false;
}

function onDragOver(event) {
  if (!isFileDrag(event)) return;
  event.preventDefault();
}

function onDragLeave(event) {
  if (!isFileDrag(event)) return;
  dragDepth -= 1;
  if (dragDepth <= 0) {
    dragDepth = 0;
    dropVeil.hidden = true;
  }
}

function onDrop(event) {
  if (!isFileDrag(event)) return;
  event.preventDefault();
  dragDepth = 0;
  dropVeil.hidden = true;
  const file = event.dataTransfer.files && event.dataTransfer.files[0];
  if (file) openFile(file);
}

async function request(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || "Something went wrong. Try that again.");
  return payload;
}
