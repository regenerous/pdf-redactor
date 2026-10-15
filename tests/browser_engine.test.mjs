import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  DocError,
  createBackend,
  createLocalRequest,
  normalizeColor,
  openSession,
  redactedFilename,
  safeFilename,
} from "../docs/app/engine.js";

const root = fileURLToPath(new URL("..", import.meta.url));
const dir = mkdtempSync(join(tmpdir(), "redactor-browser-"));
const TOKEN = "472-19-8831";
let failed = 0;

function check(condition, message) {
  if (condition) {
    console.log(`ok ${message}`);
    return;
  }
  failed += 1;
  console.error(`FAIL ${message}`);
}

function python(script, args = []) {
  return execFileSync("python3", ["-c", script, ...args], {
    cwd: root,
    encoding: "utf8",
  });
}

python(`
import pathlib, pymupdf, sys
out = pathlib.Path(sys.argv[1])
token = sys.argv[2]
document = pymupdf.open()
first = document.new_page()
first.insert_text((72, 80), f"SSN {token} remains", fontsize=14)
first.insert_text((72, 120), f"{token} again and KeepMe", fontsize=14)
second = document.new_page()
second.insert_text((72, 80), f"Page two {token}", fontsize=14)
document.set_metadata({"title": token, "author": "Ada"})
document.set_toc([[1, token, 1]])
(out / "form.pdf").write_bytes(document.tobytes())

rot = pymupdf.open()
page = rot.new_page(width=400, height=500)
page.insert_text((72, 100), "RotateMe stays", fontsize=20)
page.set_rotation(90)
(out / "rot.pdf").write_bytes(rot.tobytes())

img = pymupdf.open()
page = img.new_page(width=200, height=200)
pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 80, 80), 0)
pixmap.set_rect(pixmap.irect, (255, 0, 0))
page.insert_image(pymupdf.Rect(40, 40, 140, 140), pixmap=pixmap)
page.draw_line((20, 100), (180, 100), color=(0, 1, 0), width=4)
(out / "scan.pdf").write_bytes(img.tobytes())

locked = pymupdf.open()
page = locked.new_page()
page.insert_text((72, 72), "Secret")
(out / "locked.pdf").write_bytes(locked.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner-pass", user_pw="user-pass"))
`, [dir, TOKEN]);

function inspect(bytes) {
  const path = join(dir, "saved.pdf");
  writeFileSync(path, bytes);
  return JSON.parse(python(`
import json, pymupdf, sys
doc = pymupdf.open(sys.argv[1])
pix = doc[0].get_pixmap(alpha=False, colorspace=pymupdf.csRGB)
def sample(x, y):
    if x < 0 or y < 0 or x >= pix.width or y >= pix.height:
        return None
    i = (y * pix.width + x) * pix.n
    return list(pix.samples[i:i+3])
print(json.dumps({
    "pages": [page.get_text() for page in doc],
    "title": doc.metadata["title"],
    "author": doc.metadata["author"],
    "toc": doc.get_toc(),
    "sample": {
        "inside": sample(55, 70),
        "image": sample(120, 70),
        "line": sample(30, 100),
        "rotate": sample(407, 110),
        "stays": sample(407, 185),
    },
}))
`, [path]));
}

function word(session, page, text) {
  return session.wordsForDisplay(page).words.find((item) => item.text === text);
}

const expected = JSON.parse(python(`
import json, sys
from redactor.engine import DocumentSession
session = DocumentSession(open(sys.argv[1], "rb").read(), "intake.pdf")
rotated = DocumentSession(open(sys.argv[2], "rb").read(), "rotated.pdf")
print(json.dumps({
    "form": [session.words_for_display(0), session.words_for_display(1)],
    "rot": rotated.words_for_display(0),
}))
`, [join(dir, "form.pdf"), join(dir, "rot.pdf")]));

const form = openSession(readFileSync(join(dir, "form.pdf")), "intake.pdf");
for (const page of [0, 1]) {
  const actual = form.wordsForDisplay(page);
  check(Math.abs(actual.width - expected.form[page].width) < 0.01, `page ${page} width`);
  check(Math.abs(actual.height - expected.form[page].height) < 0.01, `page ${page} height`);
  check(actual.words.length === expected.form[page].words.length, `page ${page} word count`);
  for (let index = 0; index < actual.words.length; index += 1) {
    const got = actual.words[index];
    const want = expected.form[page].words[index];
    const close = ["x0", "y0", "x1", "y1"].every((key) => Math.abs(got[key] - want[key]) < 0.02);
    check(got.text === want.text && close, `page ${page} word ${want.text}`);
  }
}

const target = word(form, 0, TOKEN);
const original = Buffer.from(form.data);
const first = form.addArea(0, target.x0, target.y0, target.x1, target.y1, TOKEN, "#000000");
check(first.remaining === 2, "one click leaves two copies");
const savedOnce = form.exportPdf();
check(Buffer.from(form.data).equals(original), "original bytes stay unchanged");
const once = inspect(savedOnce);
check(once.pages[0].split(TOKEN).length - 1 === 1, "first page keeps one copy");
check(once.pages[0].includes("remains") && once.pages[0].includes("KeepMe"), "neighbors stay");
check(once.pages[1].includes(TOKEN), "page two is untouched");

const other = word(form, 0, "KeepMe");
form.addArea(0, other.x0, other.y0, other.x1, other.y1, "KeepMe", "#c4453c");
const summary = Object.fromEntries(form.stringSummary().map((row) => [row.text, row]));
check(form.stringSummary()[0].text === "KeepMe", "newest string is first");
check(summary[TOKEN].count === 1 && summary[TOKEN].remaining === 2, "token summary before redact all");
check(summary.KeepMe.remaining === 0, "KeepMe has no copies left");
check(form.redactAll(TOKEN, "#111111") === 2, "redact all covers the copies still open");
const finished = Object.fromEntries(form.stringSummary().map((row) => [row.text, row]));
check(finished[TOKEN].remaining === 0 && finished[TOKEN].count === 3, "every token copy is marked");
const tokenItem = form.redactions.find((item) => item.text === TOKEN);
form.remove(tokenItem.id);
const afterUndo = Object.fromEntries(form.stringSummary().map((row) => [row.text, row]));
check(afterUndo[TOKEN].remaining === 1 && afterUndo[TOKEN].count === 2, "undo brings one copy back");
form.close();

const all = openSession(readFileSync(join(dir, "form.pdf")), "intake.pdf");
check(all.redactAll(TOKEN, "#c4453c") === 3, "redact all finds three copies");
const wiped = all.exportPdf();
const wipedInfo = inspect(wiped);
const wipedText = wipedInfo.pages.join("\n");
check(!wipedText.includes(TOKEN), "saved text has no token");
check(wipedText.includes("KeepMe") && wipedText.includes("remains"), "other words survive redact all");
check(!Buffer.from(wiped).includes(Buffer.from(TOKEN)), "token bytes are gone");
check(wipedInfo.title === "" || wipedInfo.title == null, "title metadata is cleared");
check(wipedInfo.author === "Ada", "other metadata stays");
check(wipedInfo.toc[0][1] === "Redacted", "outline title is redacted");
all.close();

const boxed = openSession(readFileSync(join(dir, "form.pdf")), "intake.pdf");
const keep = word(boxed, 0, "KeepMe");
boxed.addArea(0, keep.x0 + 1, keep.y0 + 1, keep.x1 - 1, keep.y1 - 1, null, "#111111");
const boxedText = inspect(boxed.exportPdf()).pages[0];
check(!boxedText.includes("KeepMe") && boxedText.includes("remains"), "a box removes the text under it");
boxed.close();

const rotated = openSession(readFileSync(join(dir, "rot.pdf")), "rotated.pdf");
const shown = rotated.wordsForDisplay(0);
check(Math.abs(shown.width - expected.rot.width) < 0.01, "rotated page width");
const rotateWord = shown.words.find((item) => item.text === "RotateMe");
const wanted = expected.rot.words.find((item) => item.text === "RotateMe");
check(rotateWord && ["x0", "y0", "x1", "y1"].every((key) => Math.abs(rotateWord[key] - wanted[key]) < 0.02), "rotated word box");
rotated.addArea(0, rotateWord.x0, rotateWord.y0, rotateWord.x1, rotateWord.y1, "RotateMe", "#0000ff");
const rotatedInfo = inspect(rotated.exportPdf());
check(!rotatedInfo.pages[0].includes("RotateMe") && rotatedInfo.pages[0].includes("stays"), "rotated redaction hits the visible word");
check(rotatedInfo.sample.rotate[2] === 255 && rotatedInfo.sample.rotate[0] === 0, "rotated block is blue");
check(rotatedInfo.sample.stays[0] === 255, "text beside the block stays");
rotated.close();

const scan = openSession(readFileSync(join(dir, "scan.pdf")), "scan.pdf");
scan.addArea(0, 40, 40, 90, 140, null, "#0000ff");
const pixels = inspect(scan.exportPdf()).sample;
check(pixels.inside.join(",") === "0,0,255", "picture pixels inside the box are replaced");
check(pixels.image.join(",") === "255,0,0", "picture pixels outside the box stay");
check(pixels.line[1] > 200, "a line crossing the box remains outside it");
scan.close();

const duplicate = openSession(readFileSync(join(dir, "form.pdf")), "intake.pdf");
const remains = word(duplicate, 0, "remains");
duplicate.addArea(0, remains.x0, remains.y0, remains.x1, remains.y1, "remains", "#000");
duplicate.addArea(0, remains.x0, remains.y0, remains.x1, remains.y1, "remains", "#000");
check(duplicate.redactions.length === 1, "a second click does not stack");
duplicate.close();

const undo = openSession(readFileSync(join(dir, "form.pdf")), "intake.pdf");
const marked = word(undo, 0, "remains");
undo.addArea(0, marked.x0, marked.y0, marked.x1, marked.y1, "remains", "#fff");
undo.removeText("remains");
check(undo.redactions.length === 0, "undo removes the string");
let refused = false;
try {
  undo.exportPdf();
} catch (error) {
  refused = error instanceof DocError;
}
check(refused, "saving with nothing redacted is refused");
undo.close();

for (const [bytes, name, message] of [
  [readFileSync(join(dir, "locked.pdf")), "locked.pdf", "password-protected"],
  [new TextEncoder().encode("not a pdf"), "notes.txt", "Choose a PDF"],
  [new Uint8Array(), "empty.pdf", "empty"],
]) {
  let matched = false;
  try {
    openSession(bytes, name);
  } catch (error) {
    matched = error instanceof DocError && error.message.includes(message);
  }
  check(matched, `rejects ${name}`);
}

check(safeFilename("../../secret.pdf") === "secret.pdf", "safe filename");
check(redactedFilename("secret.pdf") === "secret-redacted.pdf", "redacted filename");
check(redactedFilename("secret-redacted.pdf") === "secret-redacted.pdf", "already redacted filename");
check(normalizeColor("#abc") === "#aabbcc", "short color");

const backend = createBackend();
const request = createLocalRequest(backend);
const opened = await request("/api/open", {
  method: "POST",
  headers: { "X-Filename": encodeURIComponent("intake.pdf") },
  body: new Blob([readFileSync(join(dir, "form.pdf"))]),
});
check(opened.open && opened.name === "intake.pdf" && opened.pageCount === 2, "local open request");
const png = backend.render(0, 2, opened.docId);
check(png[0] === 0x89 && png[1] === 0x50, "page render is a png");
const saved = backend.save;
let saveRefused = false;
try {
  backend.save();
} catch (error) {
  saveRefused = error instanceof DocError;
}
check(saveRefused, "save request waits for a redaction");
void saved;
backend.close();

const page = readFileSync(join(root, "docs/index.html"), "utf8");
check(page.includes(">In Browser<"), "landing page has the browser button");
check(page.includes("file stays locally in browser"), "landing page has the local-file note");
check(!page.includes("dl-linux"), "linux download button is gone");
check(page.includes('href="app/index.html"'), "browser button opens the app");
check(page.includes('rel="apple-touch-icon" href="apple-touch-icon.png"'), "landing page uses the app icon on iOS");
const appPage = readFileSync(join(root, "docs/app/index.html"), "utf8");
check(appPage.includes('rel="icon" href="../images/icon.png"'), "browser app favicon is the app icon");
check(appPage.includes('rel="apple-touch-icon" href="../apple-touch-icon.png"'), "browser app uses the app icon on iOS");

if (failed) {
  console.error(`${failed} failed`);
  process.exit(1);
}
console.log("all browser engine checks passed");
