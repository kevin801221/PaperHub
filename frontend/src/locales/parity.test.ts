import { describe, expect, it } from "vitest";

import { SUPPORTED_LANGUAGES } from "../lib/i18n";

// Eagerly load every locale catalog. Glob keys look like "./en/common.json".
const modules = import.meta.glob<{ default: Record<string, unknown> }>(
  "./*/*.json",
  { eager: true },
);

/** Flatten a nested catalog into its set of leaf key paths (e.g.
 * "field.PAPERHUB_LOG_LEVEL.help"). */
function flatten(obj: Record<string, unknown>, prefix = ""): string[] {
  const out: string[] = [];
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v !== null && typeof v === "object" && !Array.isArray(v)) {
      out.push(...flatten(v as Record<string, unknown>, key));
    } else {
      out.push(key);
    }
  }
  return out;
}

// catalogs[locale][namespace] = parsed JSON
const catalogs: Record<string, Record<string, Record<string, unknown>>> = {};
for (const [path, mod] of Object.entries(modules)) {
  const m = /\.\/([^/]+)\/([^/]+)\.json$/.exec(path);
  if (!m) continue;
  const locale = m[1];
  const ns = m[2];
  if (!locale || !ns) continue;
  (catalogs[locale] ??= {})[ns] = mod.default;
}

const enCatalogs = catalogs.en ?? {};
const namespaces = Object.keys(enCatalogs).sort();

describe("locale catalog parity (en is the source of truth)", () => {
  it("loads catalogs for every supported language", () => {
    for (const locale of SUPPORTED_LANGUAGES) {
      expect(catalogs[locale], `no catalogs found for "${locale}"`).toBeDefined();
    }
    expect(namespaces.length).toBeGreaterThan(0);
  });

  for (const ns of namespaces) {
    const enKeys = flatten(enCatalogs[ns] ?? {}).sort();
    for (const locale of SUPPORTED_LANGUAGES) {
      if (locale === "en") continue;
      it(`${locale}/${ns}.json has exactly the same keys as en`, () => {
        const cat = catalogs[locale]?.[ns];
        expect(cat, `${locale}/${ns}.json is missing entirely`).toBeDefined();
        const keys = flatten(cat as Record<string, unknown>).sort();
        const missing = enKeys.filter((k) => !keys.includes(k));
        const extra = keys.filter((k) => !enKeys.includes(k));
        expect(missing, `keys missing in ${locale}/${ns}.json`).toEqual([]);
        expect(extra, `extra keys in ${locale}/${ns}.json (not in en)`).toEqual([]);
      });
    }
  }
});
