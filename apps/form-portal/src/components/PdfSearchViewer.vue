<template>
  <div class="pdf-search-viewer" :style="{ height }">
    <div class="pdf-viewer-shell">
      <div ref="containerRef" class="pdf-viewer-container">
        <div ref="viewerRef" class="pdfViewer"></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import * as pdfjsLib from "pdfjs-dist/build/pdf.mjs";
import workerSrc from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import "pdfjs-dist/web/pdf_viewer.css";

const props = defineProps({
  src: { type: String, default: "" },
  query: { type: String, default: "" },
  height: { type: String, default: "360px" },
});

pdfjsLib.GlobalWorkerOptions.workerSrc = workerSrc;
globalThis.pdfjsLib = pdfjsLib;

const containerRef = ref(null);
const viewerRef = ref(null);

let eventBus = null;
let linkService = null;
let findController = null;
let viewer = null;
let loadingTask = null;
let pdfDoc = null;
let viewerModule = null;

function applySearch() {
  if (!eventBus) return;
  const q = String(props.query || "").trim();
  eventBus.dispatch("find", {
    source: "external-search",
    type: "",
    query: q,
    phraseSearch: true,
    caseSensitive: false,
    entireWord: false,
    highlightAll: true,
    findPrevious: false,
  });
}

async function loadPdf() {
  const src = String(props.src || "").trim();
  if (!viewer || !findController) return;

  if (loadingTask) {
    try { loadingTask.destroy(); } catch (_e) {}
    loadingTask = null;
  }
  if (pdfDoc) {
    try { pdfDoc.destroy(); } catch (_e) {}
    pdfDoc = null;
  }

  if (!src) {
    viewer.setDocument(null);
    linkService.setDocument(null);
    return;
  }

  loadingTask = pdfjsLib.getDocument(src);
  pdfDoc = await loadingTask.promise;
  viewer.setDocument(pdfDoc);
  linkService.setDocument(pdfDoc, null);
  applySearch();
}

async function initViewer() {
  viewerModule = await import("pdfjs-dist/web/pdf_viewer.mjs");
  const { EventBus, PDFFindController, PDFLinkService, PDFViewer } = viewerModule;
  eventBus = new EventBus();
  linkService = new PDFLinkService({ eventBus });
  findController = new PDFFindController({ eventBus, linkService });
  viewer = new PDFViewer({
    container: containerRef.value,
    viewer: viewerRef.value,
    eventBus,
    linkService,
    findController,
    textLayerMode: 2,
  });
  linkService.setViewer(viewer);
}

onMounted(async () => {
  await initViewer();
  loadPdf();
});

watch(() => props.src, () => {
  loadPdf();
});

watch(() => props.query, () => {
  applySearch();
});

onBeforeUnmount(() => {
  if (loadingTask) {
    try { loadingTask.destroy(); } catch (_e) {}
    loadingTask = null;
  }
  if (pdfDoc) {
    try { pdfDoc.destroy(); } catch (_e) {}
    pdfDoc = null;
  }
});
</script>

<style scoped>
.pdf-search-viewer {
  width: 100%;
}

.pdf-viewer-shell {
  position: relative;
  width: 100%;
  height: 100%;
}

.pdf-viewer-container {
  position: absolute;
  inset: 0;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #f5f7fb;
}

.pdfViewer {
  padding: 8px 0;
}
</style>
