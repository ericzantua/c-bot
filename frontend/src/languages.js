// Supported conversation languages. `code` goes to the backend; `bcp47` sets
// the browser speech-recognition locale.
export const LANGUAGES = [
  { code: "en", label: "English", bcp47: "en-CA" },
  { code: "yue", label: "中文（廣東話）", bcp47: "yue-Hant-HK" },
  { code: "es", label: "Español", bcp47: "es-ES" },
  { code: "fr", label: "Français", bcp47: "fr-CA" },
];

export const bcp47For = (code) =>
  (LANGUAGES.find((l) => l.code === code) || LANGUAGES[0]).bcp47;
