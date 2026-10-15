import { createBackend, createLocalRequest } from "./engine.js";

const emptyCopy = document.querySelector(".empty-copy");
const stageError = document.getElementById("stage-error");
const readyCopy = "Open a file, then click a word or drag a box over anything that should be gone. Saving writes a new PDF with that information removed.";

try {
  const backend = createBackend();
  const images = new Map();

  function clearImages() {
    for (const url of images.values()) URL.revokeObjectURL(url);
    images.clear();
  }

  const request = createLocalRequest({
    ...backend,
    open(bytes, name) {
      clearImages();
      return backend.open(bytes, name);
    },
  });

  window.redactorLocal = {
    request,
    pageURL(page, scale, docId) {
      const key = `${docId}:${page}:${scale}`;
      const cached = images.get(key);
      if (cached) {
        images.delete(key);
        images.set(key, cached);
        return cached;
      }
      const png = backend.render(page, scale, docId);
      const url = URL.createObjectURL(new Blob([png], { type: "image/png" }));
      images.set(key, url);
      while (images.size > 12) {
        const oldest = images.keys().next().value;
        URL.revokeObjectURL(images.get(oldest));
        images.delete(oldest);
      }
      return url;
    },
    save() {
      const saved = backend.save();
      return {
        blob: new Blob([saved.bytes], { type: "application/pdf" }),
        name: saved.name,
      };
    },
  };

  if (emptyCopy) emptyCopy.textContent = readyCopy;
  await import("./app.js");
} catch (error) {
  if (stageError) {
    stageError.hidden = false;
    stageError.textContent = "The redactor couldn't load in this browser.";
  }
  if (emptyCopy) emptyCopy.textContent = "The redactor couldn't load in this browser.";
  console.error(error);
}
