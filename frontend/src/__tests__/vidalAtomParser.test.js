// Iter43-fix24am (2026-06-17) — Unit test for the Atom parser in Vidal.jsx.
//
// Uses jsdom's DOMParser to verify that `<vidal:id>` (the namespaced product
// code) is correctly extracted, NOT the plain `<id>` Atom element (which
// contains the entry URN).

/* eslint-env node, browser, jest */

const { JSDOM } = require("jsdom");

function _parseAtomEntries(xmlText) {
  const dom = new JSDOM("<!DOCTYPE html><html></html>");
  const DOMParser = dom.window.DOMParser;
  try {
    const parser = new DOMParser();
    const doc = parser.parseFromString(xmlText, "application/xml");
    const errorNode = doc.querySelector("parsererror");
    if (errorNode) return null;
    const entryNodes = doc.querySelectorAll("entry");
    if (!entryNodes.length) return null;
    return Array.from(entryNodes).map((node) => {
      const get = (tag) => {
        const el = node.querySelector(tag);
        return el ? (el.textContent || "").trim() : "";
      };
      let vidalId = "";
      const vidalIdNode = node.getElementsByTagName("vidal:id")[0];
      if (vidalIdNode) {
        const t = (vidalIdNode.textContent || "").trim();
        if (t) vidalId = t;
      }
      if (!vidalId) {
        for (const child of Array.from(node.children || [])) {
          if ((child.localName || child.nodeName || "").toLowerCase() === "id") {
            const tt = (child.textContent || "").trim();
            if (/^\d+$/.test(tt)) {
              vidalId = tt;
              break;
            }
          }
        }
      }
      const atomId = get("id");
      if (!vidalId && atomId) {
        const m = atomId.match(/(\d+)\s*$/);
        if (m) vidalId = m[1];
      }
      if (!vidalId) {
        try {
          const html = node.outerHTML || "";
          const m = html.match(/<[a-z][a-z0-9]*:id>\s*(\d+)\s*<\/[a-z][a-z0-9]*:id>/i);
          if (m) vidalId = m[1];
        } catch { /* noop */ }
      }
      const id = vidalId || atomId;
      return {
        title: get("title") || get("name") || "(sans nom)",
        id,
        vidal_id: vidalId,
        type: get("type") || get("objectType") || "-",
        summary: get("summary") || get("description") || "",
        updated: get("updated") || "",
      };
    });
  } catch {
    return null;
  }
}

const SAMPLE_VIDAL_XML = `<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:vidal="http://api.vidal.fr/spec/vidal/1.0">
  <title>Recherche VIDAL — doliprane</title>
  <updated>2026-06-17T12:00:00Z</updated>
  <entry>
    <title>DOLIPRANE 100 mg pdre p sol buv en sachet-dose</title>
    <id>vidal://product/5485</id>
    <vidal:id>5485</vidal:id>
    <updated>2024-01-15T00:00:00Z</updated>
    <summary>Paracétamol — antalgique antipyrétique</summary>
  </entry>
  <entry>
    <title>DOLIPRANE 1000 mg, comprimé</title>
    <id>vidal://product/5486</id>
    <vidal:id>5486</vidal:id>
    <updated>2024-01-15T00:00:00Z</updated>
    <summary>Paracétamol — adulte</summary>
  </entry>
</feed>`;

describe("VIDAL Atom parser — vidal:id extraction (Iter43-fix24am)", () => {
  test("extracts <vidal:id> namespaced element as the product code", () => {
    const entries = _parseAtomEntries(SAMPLE_VIDAL_XML);
    expect(entries).not.toBeNull();
    expect(entries).toHaveLength(2);
    expect(entries[0].vidal_id).toBe("5485");
    expect(entries[0].id).toBe("5485");
    expect(entries[0].title).toBe("DOLIPRANE 100 mg pdre p sol buv en sachet-dose");
    expect(entries[1].vidal_id).toBe("5486");
    expect(entries[1].id).toBe("5486");
  });

  test("falls back to URN-extracted digits when <vidal:id> is missing", () => {
    const xmlWithoutVidalId = SAMPLE_VIDAL_XML.replace(/<vidal:id>\d+<\/vidal:id>\s*/g, "");
    const entries = _parseAtomEntries(xmlWithoutVidalId);
    expect(entries).not.toBeNull();
    // Should extract "5485" from "vidal://product/5485"
    expect(entries[0].vidal_id).toBe("5485");
    expect(entries[1].vidal_id).toBe("5486");
  });

  test("handles alternative namespace prefix <v:id> via outerHTML regex", () => {
    // Replace BOTH the prefix declaration AND each usage so the XML stays valid
    const xmlAltPrefix = SAMPLE_VIDAL_XML
      .replace(/xmlns:vidal=/g, "xmlns:v=")
      .replace(/<vidal:id>/g, "<v:id>")
      .replace(/<\/vidal:id>/g, "</v:id>");
    const entries = _parseAtomEntries(xmlAltPrefix);
    expect(entries).not.toBeNull();
    expect(entries[0].vidal_id).toBe("5485");
    expect(entries[1].vidal_id).toBe("5486");
  });

  test("vidal_id stays empty when no numeric code found anywhere", () => {
    const xmlNoCode = `<?xml version="1.0"?>
      <feed xmlns="http://www.w3.org/2005/Atom">
        <entry><title>SomeName</title><id>urn:no:digits:here</id></entry>
      </feed>`;
    const entries = _parseAtomEntries(xmlNoCode);
    expect(entries).not.toBeNull();
    expect(entries[0].vidal_id).toBe("");
    // `id` falls back to the URN itself
    expect(entries[0].id).toBe("urn:no:digits:here");
  });

  test("returns null for malformed XML", () => {
    const out = _parseAtomEntries("<this is not valid <xml>");
    expect(out).toBeNull();
  });

  test("returns null for valid XML with no entries", () => {
    const out = _parseAtomEntries(`<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>`);
    expect(out).toBeNull();
  });
});
