import { createApp } from "vue";
import App from "./App.vue";
import "./styles.css";
import { resolveRoute } from "./formProfiles";

const route = resolveRoute();
const profile = route.profile;
const rootStyle = document.documentElement.style;
const cssProfileMap = {
  accent: "--accent",
  accentDark: "--accent-dark",
  activeLinkColor: "--active-link",
  heroAStart: "--hero-a-start",
  heroAEnd: "--hero-a-end",
  heroBStart: "--hero-b-start",
  heroBEnd: "--hero-b-end",
};

Object.entries(cssProfileMap).forEach(([profileKey, cssVar]) => {
  const value = profile?.[profileKey];
  if (typeof value === "string" && value.trim()) {
    rootStyle.setProperty(cssVar, value.trim());
  }
});

const title = String(
  route.type === "analytics" ? "PDF/Analytics" : profile?.siteTitle || profile?.brandTitle || "PDF Portal"
).trim();
if (title) {
  document.title = title;
}

createApp(App).mount("#app");
