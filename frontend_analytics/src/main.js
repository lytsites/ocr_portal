import { createApp } from "vue";
import App from "./App.vue";
import "./styles.css";

const title = String(import.meta.env.VITE_SITE_TITLE || "PDF/Analytics").trim();
if (title) document.title = title;

createApp(App).mount("#app");
