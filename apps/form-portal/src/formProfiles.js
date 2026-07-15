const FORM_PROFILES = {
  "2-19": {
    slug: "2-19",
    formId: "form_2_19",
    formLabel: "2-19",
    brandTitle: "PDF/2-19",
    siteTitle: "PDF 2-19",
    accent: "#84653a",
    accentDark: "#624a27",
    activeLinkColor: "#624a27",
    heroAStart: "rgba(132,101,58,0.24)",
    heroAEnd: "rgba(255,255,255,0)",
    heroBStart: "rgba(98,74,39,0.18)",
    heroBEnd: "rgba(255,255,255,0)",
  },
  "2-43": {
    slug: "2-43",
    formId: "form_2_43",
    formLabel: "2-43",
    brandTitle: "PDF/2-43",
    siteTitle: "PDF 2-43",
    accent: "#0f8f7b",
    accentDark: "#0c6f5f",
    activeLinkColor: "#0c6f5f",
    heroAStart: "rgba(15,143,123,0.24)",
    heroAEnd: "rgba(255,255,255,0)",
    heroBStart: "rgba(12,111,95,0.20)",
    heroBEnd: "rgba(255,255,255,0)",
  },
  "4-20": {
    slug: "4-20",
    formId: "form_4_20",
    formLabel: "4-20",
    brandTitle: "PDF/4-20",
    siteTitle: "PDF 4-20",
    accent: "#255fb3",
    accentDark: "#1b4888",
    activeLinkColor: "#1b4888",
    heroAStart: "rgba(37,95,179,0.22)",
    heroAEnd: "rgba(255,255,255,0)",
    heroBStart: "rgba(27,72,136,0.18)",
    heroBEnd: "rgba(255,255,255,0)",
  },
  "5-52": {
    slug: "5-52",
    formId: "form_5_52",
    formLabel: "5-52",
    brandTitle: "PDF/5-52",
    siteTitle: "PDF 5-52",
    accent: "#7d4db3",
    accentDark: "#5f3988",
    activeLinkColor: "#5f3988",
    heroAStart: "rgba(125,77,179,0.24)",
    heroAEnd: "rgba(255,255,255,0)",
    heroBStart: "rgba(95,57,136,0.18)",
    heroBEnd: "rgba(255,255,255,0)",
  },
};

const DEFAULT_FORM_SLUG = "2-43";

function normalizePathname(pathname) {
  const value = String(pathname || "/").trim();
  return value.startsWith("/") ? value : `/${value}`;
}

export function resolveRoute(pathname = window.location.pathname) {
  const cleanPath = normalizePathname(pathname);
  const segments = cleanPath.split("/").filter(Boolean);
  const first = String(segments[0] || "").toLowerCase();

  if (first === "analytics") {
    return {
      type: "analytics",
      slug: "analytics",
      profile: FORM_PROFILES[DEFAULT_FORM_SLUG],
      pathname: cleanPath,
    };
  }

  const matchedProfile = FORM_PROFILES[first] || FORM_PROFILES[DEFAULT_FORM_SLUG];
  return {
    type: "form",
    slug: matchedProfile.slug,
    profile: matchedProfile,
    pathname: cleanPath,
  };
}

export function buildFormPath(slug) {
  const value = String(slug || DEFAULT_FORM_SLUG).trim();
  return `/${value}`;
}

export function buildAnalyticsPath() {
  return "/analytics";
}

export function listFormProfiles() {
  return Object.values(FORM_PROFILES);
}

export function getDefaultFormProfile() {
  return FORM_PROFILES[DEFAULT_FORM_SLUG];
}
