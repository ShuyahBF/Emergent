/**
 * WhatsApp Template helpers
 *
 * Parses a Meta template's `components` array into a normalized structure
 * and builds the Meta-compliant outbound `components` payload for send.
 */

const HEADER_FORMATS = new Set(["TEXT", "IMAGE", "DOCUMENT", "VIDEO"]);

/** Count the highest {{N}} placeholder in a text. */
export function countVars(text) {
  if (!text) return 0;
  const matches = [...text.matchAll(/\{\{\s*(\d+)\s*\}\}/g)].map((m) => parseInt(m[1], 10));
  return matches.length ? Math.max(...matches) : 0;
}

/**
 * Returns { header, body, footer, buttons } where
 *  - header: { format, text, varCount }  or null
 *  - body:   { text, varCount }
 *  - footer: { text }  or null
 *  - buttons: [{ type, text, url, urlVarCount }, ...] (dynamic URL buttons only add 1 var each)
 */
export function parseTemplate(template) {
  const out = { header: null, body: { text: "", varCount: 0 }, footer: null, buttons: [] };
  const comps = template?.components || [];
  for (const c of comps) {
    const type = (c.type || "").toUpperCase();
    if (type === "HEADER") {
      const format = (c.format || "TEXT").toUpperCase();
      const text = c.text || "";
      out.header = {
        format: HEADER_FORMATS.has(format) ? format : "TEXT",
        text,
        varCount: format === "TEXT" ? countVars(text) : 0,
      };
    } else if (type === "BODY") {
      out.body = { text: c.text || "", varCount: countVars(c.text || "") };
    } else if (type === "FOOTER") {
      out.footer = { text: c.text || "" };
    } else if (type === "BUTTONS") {
      const btns = (c.buttons || []).map((b) => {
        const btype = (b.type || "").toUpperCase();
        const urlVarCount = btype === "URL" ? countVars(b.url || "") : 0;
        return {
          type: btype,
          text: b.text || "",
          url: b.url || "",
          phone_number: b.phone_number,
          urlVarCount,
        };
      });
      out.buttons = btns;
    }
  }
  return out;
}

/**
 * Build the Meta-compliant `components` payload from values.
 *
 * @param parsed from parseTemplate()
 * @param values {
 *   headerText?: string,
 *   headerMedia?: { link: string, kind: "image"|"document"|"video", filename?: string },
 *   bodyVars: string[],       // length = parsed.body.varCount
 *   buttonVars: string[][],   // index = button index
 * }
 */
export function buildComponentsPayload(parsed, values) {
  const components = [];

  // HEADER
  if (parsed.header) {
    const h = parsed.header;
    if (h.format === "TEXT" && h.varCount > 0) {
      const t = values.headerText || "";
      components.push({
        type: "header",
        parameters: [{ type: "text", text: t }],
      });
    } else if (h.format === "IMAGE" && values.headerMedia?.link) {
      components.push({
        type: "header",
        parameters: [{ type: "image", image: { link: values.headerMedia.link } }],
      });
    } else if (h.format === "DOCUMENT" && values.headerMedia?.link) {
      components.push({
        type: "header",
        parameters: [{
          type: "document",
          document: {
            link: values.headerMedia.link,
            filename: values.headerMedia.filename || "document.pdf",
          },
        }],
      });
    } else if (h.format === "VIDEO" && values.headerMedia?.link) {
      components.push({
        type: "header",
        parameters: [{ type: "video", video: { link: values.headerMedia.link } }],
      });
    }
  }

  // BODY
  if (parsed.body.varCount > 0) {
    const vars = (values.bodyVars || []).slice(0, parsed.body.varCount);
    components.push({
      type: "body",
      parameters: vars.map((v) => ({ type: "text", text: v || "" })),
    });
  }

  // BUTTONS (only URL buttons with {{N}} need parameters)
  (parsed.buttons || []).forEach((btn, index) => {
    if (btn.type === "URL" && btn.urlVarCount > 0) {
      const params = (values.buttonVars?.[index] || []).slice(0, btn.urlVarCount);
      components.push({
        type: "button",
        sub_type: "url",
        index: String(index),
        parameters: params.map((v) => ({ type: "text", text: v || "" })),
      });
    }
  });

  return components;
}

/**
 * Build `button_specs` payload for backend (used when the backend will
 * substitute per-recipient `{{token}}` variables but still needs to know
 * the exact sub_type / index / parameter type of each button so it can
 * emit a Meta-compliant `components` array.
 *
 * Iter43-fix24aj (2026-06-17) — fixes Meta error #131009
 * "Components sub_type invalid at index: N and type: 0" which previously
 * happened because the backend hardcoded `sub_type=url` for every button.
 *
 * @param parsed from parseTemplate()
 * @param buttonVars string[][] (index = button position, inner array = vars)
 * @returns Array<{ sub_type, index, parameters }> ready to pass as `button_specs`,
 *          OR null if the template has no parameterized buttons.
 */
export function buildButtonSpecs(parsed, buttonVars) {
  const specs = [];
  (parsed.buttons || []).forEach((btn, index) => {
    const btype = (btn.type || "").toUpperCase();
    if (btype === "URL" && btn.urlVarCount > 0) {
      const params = (buttonVars?.[index] || []).slice(0, btn.urlVarCount);
      const cleaned = params.filter((v) => v != null && String(v).trim() !== "");
      if (!cleaned.length) return;
      specs.push({
        sub_type: "url",
        index,
        parameters: cleaned.map((v) => ({ type: "text", text: String(v) })),
      });
    }
    // QUICK_REPLY / FLOW / COPY_CODE / OTP / VOICE_CALL: no per-message
    // parameter component is required for the static cases we currently
    // support — we deliberately do NOT emit a component for them.
  });
  return specs.length ? specs : null;
}

/**
 * Validate all required inputs for a template are present.
 * Returns { ok:true } or { ok:false, message }.
 */
export function validateTemplateValues(parsed, values) {
  if (parsed.header) {
    const h = parsed.header;
    if (h.format === "TEXT" && h.varCount > 0 && !(values.headerText || "").trim()) {
      return { ok: false, message: "Renseignez la variable de l'en-tête texte" };
    }
    if (["IMAGE", "DOCUMENT", "VIDEO"].includes(h.format) && !values.headerMedia?.link) {
      return { ok: false, message: `Sélectionnez un fichier pour l'en-tête ${h.format.toLowerCase()}` };
    }
  }
  if (parsed.body.varCount > 0) {
    for (let i = 0; i < parsed.body.varCount; i++) {
      if (!(values.bodyVars?.[i] || "").toString().trim()) {
        return { ok: false, message: `Renseignez toutes les variables du corps ({{${i + 1}}})` };
      }
    }
  }
  for (let bi = 0; bi < (parsed.buttons || []).length; bi++) {
    const btn = parsed.buttons[bi];
    if (btn.type === "URL" && btn.urlVarCount > 0) {
      const arr = values.buttonVars?.[bi] || [];
      for (let i = 0; i < btn.urlVarCount; i++) {
        if (!(arr[i] || "").toString().trim()) {
          return { ok: false, message: `Renseignez le paramètre du bouton « ${btn.text} »` };
        }
      }
    }
  }
  return { ok: true };
}

/** Human-readable preview of the body with tokens + contact fallbacks substituted. */
export function renderPreview(parsed, values, tokens, contact) {
  if (!parsed.body.text) return "";
  let out = parsed.body.text;
  (values.bodyVars || []).forEach((raw, idx) => {
    let rendered = raw || `{{${idx + 1}}}`;
    (tokens || []).forEach((tk) => {
      rendered = rendered.split(tk.token).join(tk.example || tk.token);
    });
    rendered = rendered
      .split("{{full_name}}").join(contact?.name || "")
      .split("{{company}}").join(contact?.company || "")
      .split("{{phone}}").join(contact?.whatsapp || contact?.phone || "")
      .split("{{email}}").join(contact?.email || "");
    out = out.replace(new RegExp(`\\{\\{\\s*${idx + 1}\\s*\\}\\}`, "g"), rendered);
  });
  return out;
}
