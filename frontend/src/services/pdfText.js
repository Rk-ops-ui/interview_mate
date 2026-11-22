// pdfText.js
// Extracts the text of a PDF in the browser (no backend call), using pdf.js.
// pdf.js is loaded on demand so it does not slow down the first page load.

let pdfjsPromise = null;
let pdfWorker = null;

function loadPdfJs() {
  pdfjsPromise ??= import("pdfjs-dist").catch((error) => {
    pdfjsPromise = null; // allow a retry on the next file
    throw error;
  });
  return pdfjsPromise;
}

// Create pdf.js's worker ourselves (bundled by Vite through `new URL`) and
// hand it over as a port. This avoids pdf.js trying to import the worker
// script at runtime, which fails with "Setting up fake worker failed" when
// the Vite dev server has just re-optimized its dependencies.
function getWorkerPort() {
  pdfWorker ??= new Worker(
    new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url),
    { type: "module" }
  );
  return pdfWorker;
}

function resetWorker() {
  pdfWorker?.terminate();
  pdfWorker = null;
}

export async function extractPdfText(file) {
  const data = await file.arrayBuffer();
  try {
    return await readPdf(data.slice(0));
  } catch (error) {
    // Content errors (bad or encrypted PDF) will not be fixed by a retry.
    if (["InvalidPDFException", "PasswordException"].includes(error?.name)) throw error;
    // Otherwise the worker may be broken: start a fresh one and try once more.
    console.warn("PDF read failed, retrying with a new worker:", error);
    resetWorker();
    return readPdf(data);
  }
}

async function readPdf(data) {
  const pdfjs = await loadPdfJs();
  pdfjs.GlobalWorkerOptions.workerPort = getWorkerPort();
  const pdf = await pdfjs.getDocument({ data }).promise;

  const pages = [];
  for (let n = 1; n <= pdf.numPages; n++) {
    const page = await pdf.getPage(n);
    const content = await page.getTextContent();
    let text = "";
    for (const item of content.items) {
      if (!("str" in item)) continue;
      text += item.str + (item.hasEOL ? "\n" : " ");
    }
    pages.push(text);
  }
  await pdf.destroy();

  return pages
    .join("\n\n")
    .replace(/[ \t]+/g, " ")
    .replace(/ *\n */g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}
