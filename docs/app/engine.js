// In-browser PDF engine. MuPDF (AGPL-3.0) renders pages and removes
// redacted content. The PDF bytes stay in this tab.
import * as mupdf from "./vendor/mupdf.js";

const MAX_PDF_BYTES = 100 * 1024 * 1024;

export class DocError extends Error {
  constructor(message) {
    super(message);
    this.name = "DocError";
  }
}

export function safeFilename(name) {
  const base = String(name || "document.pdf").replaceAll("\\", "/").split("/").pop().trim();
  let cleaned = "";
  for (const character of base) {
    const code = character.codePointAt(0);
    if (code < 32 || code === 127 || '<>:"|?*'.includes(character)) continue;
    cleaned += character;
  }
  cleaned = cleaned.trim().replace(/^\.+|\.+$/g, "");
  if (!cleaned) cleaned = "document.pdf";
  if (!cleaned.toLowerCase().endsWith(".pdf")) cleaned += ".pdf";
  return cleaned.slice(0, 180);
}

export function redactedFilename(name) {
  const safe = safeFilename(name);
  const stem = safe.slice(0, -4);
  if (stem.toLowerCase().endsWith("-redacted")) return safe;
  return `${stem}-redacted.pdf`;
}

export function normalizeColor(color) {
  if (typeof color !== "string") throw new DocError("Choose a block color.");
  let raw = color.trim();
  if (raw.startsWith("#")) raw = raw.slice(1);
  if (raw.length === 3) raw = raw.split("").map((character) => character + character).join("");
  if (raw.length !== 6 || /[^0-9a-fA-F]/.test(raw)) throw new DocError("Choose a color like #111111.");
  return `#${raw.toLowerCase()}`;
}

function colorToRgb(color) {
  const value = normalizeColor(color).slice(1);
  return [0, 2, 4].map((index) => parseInt(value.slice(index, index + 2), 16) / 255);
}

function finite(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) throw new DocError("That area is off the page.");
  return number;
}

function round3(value) {
  return Math.round(value * 1000) / 1000;
}

function pdfNum(value) {
  return String(Math.round(value * 1000) / 1000);
}

function copyBytes(data) {
  const view = data instanceof Uint8Array ? data : new Uint8Array(data);
  const copy = new Uint8Array(view.byteLength);
  copy.set(view);
  return copy;
}

function openPdf(bytes) {
  let doc;
  try {
    doc = mupdf.Document.openDocument(bytes, "application/pdf");
  } catch {
    throw new DocError("This file couldn't be opened. Choose a PDF.");
  }
  if (doc.needsPassword() && !doc.authenticatePassword("")) {
    doc.destroy();
    throw new DocError("This PDF is password-protected.");
  }
  if (!doc.isPDF()) {
    doc.destroy();
    throw new DocError("This file couldn't be opened. Choose a PDF.");
  }
  const pdf = doc.asPDF();
  if (!pdf || pdf.countPages() < 1) {
    doc.destroy();
    throw new DocError("This PDF has no pages.");
  }
  return pdf;
}

function geometryOf(page) {
  const bounds = page.getBounds();
  return {
    originX: bounds[0],
    originY: bounds[1],
    width: bounds[2] - bounds[0],
    height: bounds[3] - bounds[1],
  };
}

function extractWords(page, geometry) {
  const structured = page.toStructuredText("preserve-whitespace");
  const words = [];
  let current = null;
  const push = () => {
    if (!current) return;
    words.push(current);
    current = null;
  };
  try {
    structured.walk({
      onChar(character, _origin, _font, _size, quad) {
        if (!character || /\s/.test(character)) {
          push();
          return;
        }
        const xs = [quad[0], quad[2], quad[4], quad[6]];
        const ys = [quad[1], quad[3], quad[5], quad[7]];
        const box = {
          x0: Math.min(...xs) - geometry.originX,
          y0: Math.min(...ys) - geometry.originY,
          x1: Math.max(...xs) - geometry.originX,
          y1: Math.max(...ys) - geometry.originY,
        };
        if (!current) {
          current = { text: character, ...box };
          return;
        }
        current.text += character;
        current.x0 = Math.min(current.x0, box.x0);
        current.y0 = Math.min(current.y0, box.y0);
        current.x1 = Math.max(current.x1, box.x1);
        current.y1 = Math.max(current.y1, box.y1);
      },
      endLine() {
        push();
      },
    });
    push();
  } finally {
    structured.destroy();
  }
  return words;
}

function intersectionArea(a, b) {
  const width = Math.max(0, Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0));
  const height = Math.max(0, Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0));
  return width * height;
}

function rectArea(rect) {
  return Math.max(0, rect.x1 - rect.x0) * Math.max(0, rect.y1 - rect.y0);
}

function appendFills(doc, page, fills) {
  if (fills.length === 0) return;
  const commands = ["q"];
  for (const fill of fills) {
    const x = Math.min(fill.rect[0], fill.rect[2]);
    const y = Math.min(fill.rect[1], fill.rect[3]);
    const width = Math.abs(fill.rect[2] - fill.rect[0]);
    const height = Math.abs(fill.rect[3] - fill.rect[1]);
    if (width < 0.2 || height < 0.2) continue;
    commands.push(`${fill.rgb.map(pdfNum).join(" ")} rg ${pdfNum(x)} ${pdfNum(y)} ${pdfNum(width)} ${pdfNum(height)} re f`);
  }
  commands.push("Q");
  if (commands.length === 2) return;
  const stream = doc.addStream(`${commands.join("\n")}\n`);
  const pageObject = page.getObject();
  const contents = pageObject.get("Contents");
  const array = doc.newArray();
  if (contents && contents.isArray()) {
    for (let index = 0; index < contents.length; index += 1) array.push(contents.get(index));
  } else if (contents && !contents.isNull()) {
    array.push(contents);
  }
  array.push(stream);
  pageObject.put("Contents", array);
}

function scrubMetadata(doc, needles) {
  const keys = [
    "info:Title",
    "info:Author",
    "info:Subject",
    "info:Keywords",
    "info:Creator",
    "info:Producer",
    "info:CreationDate",
    "info:ModDate",
  ];
  for (const key of keys) {
    const value = doc.getMetaData(key);
    if (value && needles.some((needle) => value.includes(needle))) doc.setMetaData(key, "");
  }
  try {
    const info = doc.getTrailer().get("Info");
    if (info && !info.isNull() && info.isDictionary()) {
      const resolved = info.resolve();
      const names = [];
      resolved.forEach((_value, key) => names.push(String(key)));
      for (const key of names) {
        let text = "";
        try {
          text = resolved.get(key).asString();
        } catch {
          text = "";
        }
        if (text && needles.some((needle) => text.includes(needle))) doc.setMetaData(`info:${key}`, "");
      }
    }
  } catch {
    // Metadata that cannot be read stays as it is.
  }
  try {
    const root = doc.getTrailer().get("Root").resolve();
    const metadata = root.get("Metadata");
    if (metadata && !metadata.isNull() && metadata.isStream()) {
      const xml = metadata.readStream().asString();
      if (needles.some((needle) => xml.includes(needle))) root.delete("Metadata");
    }
  } catch {
    // No XMP metadata to remove.
  }
}

function scrubOutline(doc, needles) {
  const outline = doc.loadOutline();
  if (!outline || outline.length === 0) return;
  const iterator = doc.outlineIterator();
  const visit = () => {
    for (;;) {
      const item = iterator.item();
      if (item && item.title && needles.some((needle) => item.title.includes(needle))) {
        iterator.update({ title: "Redacted", uri: item.uri, open: Boolean(item.open) });
      }
      if (iterator.down() === 0) {
        visit();
        iterator.up();
      }
      if (iterator.next() !== 0) break;
    }
  };
  try {
    visit();
  } catch {
    // An outline that cannot be rewritten is left in place.
  } finally {
    iterator.destroy();
  }
}

export class BrowserSession {
  constructor(bytes, name) {
    if (!bytes || bytes.byteLength === 0) throw new DocError("This file is empty.");
    if (bytes.byteLength > MAX_PDF_BYTES) throw new DocError("This PDF is larger than 100 MB.");
    this.data = copyBytes(bytes);
    this.name = safeFilename(name);
    this.doc = openPdf(this.data);
    this.docId = crypto.randomUUID().replaceAll("-", "");
    this.redactions = [];
    this.pages = new Map();
    this.wordCache = new Map();
  }

  close() {
    for (const page of this.pages.values()) page.destroy();
    this.pages.clear();
    this.doc.destroy();
  }

  get pageCount() {
    return this.doc.countPages();
  }

  page(index) {
    this.assertPage(index);
    let page = this.pages.get(index);
    if (!page) {
      page = this.doc.loadPage(index);
      this.pages.set(index, page);
    }
    return page;
  }

  assertPage(index) {
    if (!Number.isInteger(index) || index < 0 || index >= this.doc.countPages()) {
      throw new DocError("That page is not in this PDF.");
    }
  }

  geometry(index) {
    return geometryOf(this.page(index));
  }

  words(index) {
    this.assertPage(index);
    let words = this.wordCache.get(index);
    if (!words) {
      words = extractWords(this.page(index), this.geometry(index));
      this.wordCache.set(index, words);
    }
    return words;
  }

  wordsForDisplay(index) {
    const geometry = this.geometry(index);
    return {
      width: round3(geometry.width),
      height: round3(geometry.height),
      words: this.words(index).map((word, position) => ({
        i: position,
        text: word.text,
        x0: round3(word.x0),
        y0: round3(word.y0),
        x1: round3(word.x1),
        y1: round3(word.y1),
      })),
    };
  }

  renderPng(index, scale, docId) {
    if (docId && docId !== this.docId) throw new DocError("Open the PDF again.");
    const geometry = this.geometry(index);
    let zoom = Number(scale);
    if (!Number.isFinite(zoom)) zoom = 2;
    zoom = Math.max(0.5, Math.min(zoom, 3));
    const area = geometry.width * geometry.height;
    if (area > 0 && area * zoom * zoom > 12_000_000) zoom = Math.sqrt(12_000_000 / area);
    const pixmap = this.page(index).toPixmap(mupdf.Matrix.scale(zoom, zoom), mupdf.ColorSpace.DeviceRGB, false);
    try {
      return copyBytes(pixmap.asPNG());
    } finally {
      pixmap.destroy();
    }
  }

  clipRect(index, x0, y0, x1, y1) {
    const geometry = this.geometry(index);
    const left = Math.min(x0, x1);
    const top = Math.min(y0, y1);
    const right = Math.max(x0, x1);
    const bottom = Math.max(y0, y1);
    const clipped = {
      x0: Math.max(0, left),
      y0: Math.max(0, top),
      x1: Math.min(geometry.width, right),
      y1: Math.min(geometry.height, bottom),
    };
    if (clipped.x1 - clipped.x0 < 0.4 || clipped.y1 - clipped.y0 < 0.4) {
      const outside = right <= 0 || bottom <= 0 || left >= geometry.width || top >= geometry.height;
      throw new DocError(outside ? "That area is outside the page." : "That area is too small to redact.");
    }
    return clipped;
  }

  covered(index, rect) {
    const area = rectArea(rect);
    if (area <= 0) return false;
    return this.redactions.some((item) => {
      if (item.page !== index) return false;
      return intersectionArea(rect, item) >= area * 0.6;
    });
  }

  nearlySame(index, rect) {
    return this.redactions.find((item) => (
      item.page === index
      && Math.abs(item.x0 - rect.x0) < 0.6
      && Math.abs(item.y0 - rect.y0) < 0.6
      && Math.abs(item.x1 - rect.x1) < 0.6
      && Math.abs(item.y1 - rect.y1) < 0.6
    )) || null;
  }

  label(text) {
    if (typeof text !== "string") return null;
    const trimmed = text.trim();
    return trimmed ? trimmed.slice(0, 200) : null;
  }

  addArea(page, x0, y0, x1, y1, text, color) {
    this.assertPage(page);
    const rect = this.clipRect(page, finite(x0), finite(y0), finite(x1), finite(y1));
    const marked = this.label(text);
    const existing = this.nearlySame(page, rect);
    if (existing) return { remaining: this.remainingMatches(marked) };
    this.redactions.push({
      id: crypto.randomUUID().replaceAll("-", "").slice(0, 12),
      page,
      ...rect,
      text: marked,
      color: normalizeColor(color),
    });
    return { remaining: this.remainingMatches(marked) };
  }

  remainingMatches(text) {
    if (!text) return 0;
    return this.uncoveredMatches(text).length;
  }

  uncoveredMatches(text) {
    const matches = [];
    for (let index = 0; index < this.pageCount; index += 1) {
      for (const word of this.words(index)) {
        if (word.text !== text || this.covered(index, word)) continue;
        matches.push({ page: index, rect: word });
      }
    }
    return matches;
  }

  redactAll(text, color) {
    const marked = this.label(text);
    if (!marked) throw new DocError("There is no text to redact.");
    const fill = normalizeColor(color);
    const matches = this.uncoveredMatches(marked);
    for (const match of matches) {
      this.redactions.push({
        id: crypto.randomUUID().replaceAll("-", "").slice(0, 12),
        page: match.page,
        x0: match.rect.x0,
        y0: match.rect.y0,
        x1: match.rect.x1,
        y1: match.rect.y1,
        text: marked,
        color: fill,
      });
    }
    return matches.length;
  }

  remove(id) {
    const before = this.redactions.length;
    this.redactions = this.redactions.filter((item) => item.id !== id);
    if (this.redactions.length === before) throw new DocError("That redaction is already gone.");
  }

  removeText(text) {
    const marked = this.label(text);
    if (!marked) throw new DocError("That redaction is already gone.");
    const before = this.redactions.length;
    this.redactions = this.redactions.filter((item) => item.text !== marked);
    if (this.redactions.length === before) throw new DocError("That redaction is already gone.");
  }

  stringSummary() {
    const order = [];
    const counts = new Map();
    const colors = new Map();
    for (const item of this.redactions) {
      if (!item.text) continue;
      counts.set(item.text, (counts.get(item.text) || 0) + 1);
      colors.set(item.text, item.color);
      const existing = order.indexOf(item.text);
      if (existing !== -1) order.splice(existing, 1);
      order.push(item.text);
    }
    return order.reverse().map((text) => ({
      text,
      count: counts.get(text),
      remaining: this.remainingMatches(text),
      color: colors.get(text),
    }));
  }

  publicRedactions() {
    return this.redactions.map((item) => ({
      id: item.id,
      page: item.page,
      x0: round3(item.x0),
      y0: round3(item.y0),
      x1: round3(item.x1),
      y1: round3(item.y1),
      text: item.text,
      color: item.color,
    }));
  }

  activity() {
    return { redactions: this.publicRedactions(), strings: this.stringSummary() };
  }

  snapshot() {
    return {
      open: true,
      docId: this.docId,
      name: this.name,
      pageCount: this.pageCount,
      ...this.activity(),
    };
  }

  exportPdf() {
    if (this.redactions.length === 0) throw new DocError("Redact something before saving a copy.");
    const copy = openPdf(this.data);
    try {
      const grouped = new Map();
      for (const item of this.redactions) {
        const list = grouped.get(item.page) || [];
        list.push(item);
        grouped.set(item.page, list);
      }
      for (const [index, items] of grouped) {
        const page = copy.loadPage(index);
        try {
          const geometry = geometryOf(page);
          const fills = [];
          for (const item of items) {
            const annot = page.createAnnotation("Redact");
            annot.setRect([
              item.x0 + geometry.originX,
              item.y0 + geometry.originY,
              item.x1 + geometry.originX,
              item.y1 + geometry.originY,
            ]);
            const stored = annot.getObject().resolve().get("Rect");
            if (!stored || stored.length !== 4) continue;
            const rect = [0, 1, 2, 3].map((part) => stored.get(part).asNumber());
            fills.push({ rect, rgb: colorToRgb(item.color) });
          }
          page.applyRedactions(
            false,
            mupdf.PDFPage.REDACT_IMAGE_PIXELS,
            mupdf.PDFPage.REDACT_LINE_ART_REMOVE_IF_COVERED,
            mupdf.PDFPage.REDACT_TEXT_REMOVE,
          );
          appendFills(copy, page, fills);
        } finally {
          page.destroy();
        }
      }
      const needles = this.redactions.map((item) => item.text).filter((text) => text && text.length >= 4);
      if (needles.length > 0) {
        scrubMetadata(copy, needles);
        scrubOutline(copy, needles);
      }
      return copyBytes(copy.saveToBuffer("garbage=4,compress=yes,clean=yes").asUint8Array());
    } catch (error) {
      if (error instanceof DocError) throw error;
      throw new DocError("The copy couldn't be saved.");
    } finally {
      copy.destroy();
    }
  }
}

export function openSession(bytes, name) {
  return new BrowserSession(bytes, name);
}

export function createBackend() {
  let session = null;
  const requireSession = () => {
    if (!session) throw new DocError("Open a PDF first.");
    return session;
  };
  return {
    snapshot() {
      return session ? session.snapshot() : { open: false };
    },
    open(bytes, name) {
      const next = openSession(bytes, name);
      if (session) session.close();
      session = next;
      return session.snapshot();
    },
    words(page) {
      return requireSession().wordsForDisplay(page);
    },
    render(page, scale, docId) {
      return requireSession().renderPng(page, scale, docId);
    },
    addArea(payload) {
      const current = requireSession();
      const page = payloadPage(payload);
      const result = current.addArea(page, payload.x0, payload.y0, payload.x1, payload.y1, payload.text, payload.color);
      return { remaining: result.remaining, ...current.activity() };
    },
    redactAll(payload) {
      const current = requireSession();
      const added = current.redactAll(payload.text, payload.color);
      return { added, ...current.activity() };
    },
    undo(id) {
      const current = requireSession();
      current.remove(id);
      return current.activity();
    },
    undoText(text) {
      const current = requireSession();
      current.removeText(text);
      return current.activity();
    },
    save() {
      const current = requireSession();
      return { bytes: current.exportPdf(), name: redactedFilename(current.name) };
    },
    close() {
      if (session) session.close();
      session = null;
    },
  };
}

function payloadPage(payload) {
  const page = payload && payload.page;
  if (typeof page !== "number" || !Number.isInteger(page)) throw new DocError("That page is not in this PDF.");
  return page;
}

function jsonBody(options) {
  try {
    const payload = JSON.parse(options.body || "{}");
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      throw new DocError("That redaction couldn't be read.");
    }
    return payload;
  } catch (error) {
    if (error instanceof DocError) throw error;
    throw new DocError("That redaction couldn't be read.");
  }
}

export function createLocalRequest(backend) {
  return async function request(url, options = {}) {
    const method = String(options.method || "GET").toUpperCase();
    const path = String(url || "").split("?")[0];
    const parts = path.split("/").filter(Boolean);
    if (method === "GET" && path === "/api/session") return backend.snapshot();
    if (method === "POST" && path === "/api/open") {
      const body = options.body;
      if (!body) throw new DocError("The upload was incomplete.");
      const bytes = body instanceof Uint8Array ? body : new Uint8Array(await body.arrayBuffer());
      const headers = options.headers || {};
      const rawName = headers["X-Filename"] || headers["x-filename"] || "";
      const name = rawName ? decodeURIComponent(rawName) : "document.pdf";
      return backend.open(bytes, name);
    }
    if (method === "GET" && parts.length === 4 && parts[0] === "api" && parts[1] === "pages" && parts[3] === "words") {
      const page = Number(parts[2]);
      if (!Number.isInteger(page)) throw new DocError("That page is not in this PDF.");
      return backend.words(page);
    }
    if (method === "POST" && path === "/api/redactions") return backend.addArea(jsonBody(options));
    if (method === "POST" && path === "/api/redactions/all") return backend.redactAll(jsonBody(options));
    if (method === "POST" && path === "/api/redactions/undo") return backend.undoText(String(jsonBody(options).text || ""));
    if (method === "DELETE" && parts.length === 3 && parts[0] === "api" && parts[1] === "redactions") {
      return backend.undo(decodeURIComponent(parts[2]));
    }
    throw new DocError("That page isn't part of PDF Redactor.");
  };
}
