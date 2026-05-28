# 🤖 Liluvine PRO — Templates n8n prêts à l'emploi

> **Itération** : Iter38r-fix8
> **Endpoint cible** : `POST {SAWALI_BASE_URL}/api/webhooks/liluvine-pro/{source}/{secret}`
> **Pré-requis** : Dans Admin Settings → Liluvine PRO, configurer :
> - `liluvine_pro_inbound_secret` (le `{secret}` du webhook ci-dessous)
> - `liluvine_pro_n8n_outbound_url` (URL n8n « Catch & Forward » pour le retour)
> - `liluvine_pro_n8n_outbound_token` (Bearer token pour sécuriser le retour vers n8n)
>
> **Sources supportées** par l'endpoint : `n8n` · `whatsapp` · `facebook` · `custom`

---

## 1️⃣ WhatsApp (Meta Cloud API) ➜ Liluvine PRO

Reçoit un message WhatsApp via la webhook Meta, extrait le texte + numéro,
et appelle Liluvine. Si une réponse vient en retour (workflow #5), un autre
nœud HTTP renvoie la réponse via Meta Graph API.

```json
{
  "name": "Liluvine PRO — WhatsApp Inbound",
  "nodes": [
    {
      "parameters": {
        "httpMethod": "POST",
        "path": "liluvine-whatsapp",
        "responseMode": "lastNode",
        "options": {}
      },
      "id": "webhook-wa-in",
      "name": "Webhook (Meta WA)",
      "type": "n8n-nodes-base.webhook",
      "typeVersion": 1.1,
      "position": [240, 300]
    },
    {
      "parameters": {
        "jsCode": "const entry = (items[0].json.entry || [])[0] || {};\nconst change = (entry.changes || [])[0] || {};\nconst value = change.value || {};\nconst msg = (value.messages || [])[0] || {};\nconst from = msg.from || '';\nconst text = (msg.text && msg.text.body) || (msg.button && msg.button.text) || '';\nreturn [{ json: { from, text, raw: items[0].json } }];"
      },
      "id": "extract-wa",
      "name": "Extract text",
      "type": "n8n-nodes-base.code",
      "typeVersion": 2,
      "position": [480, 300]
    },
    {
      "parameters": {
        "conditions": {
          "string": [
            { "value1": "={{$json.text}}", "operation": "isNotEmpty" }
          ]
        }
      },
      "id": "if-text",
      "name": "Skip empty",
      "type": "n8n-nodes-base.if",
      "typeVersion": 1,
      "position": [720, 300]
    },
    {
      "parameters": {
        "method": "POST",
        "url": "={{$env.SAWALI_BASE_URL}}/api/webhooks/liluvine-pro/whatsapp/{{$env.LILUVINE_INBOUND_SECRET}}",
        "sendBody": true,
        "specifyBody": "json",
        "jsonBody": "={\n  \"text\": $json.text,\n  \"from\": $json.from,\n  \"channel\": \"whatsapp\",\n  \"session_id\": \"wa-\" + $json.from\n}",
        "options": { "timeout": 30000 }
      },
      "id": "call-liluvine",
      "name": "POST Liluvine PRO",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.2,
      "position": [960, 220]
    }
  ],
  "connections": {
    "Webhook (Meta WA)": { "main": [[{ "node": "Extract text", "type": "main", "index": 0 }]] },
    "Extract text":     { "main": [[{ "node": "Skip empty",   "type": "main", "index": 0 }]] },
    "Skip empty":       { "main": [[{ "node": "POST Liluvine PRO", "type": "main", "index": 0 }]] }
  }
}
```

---

## 2️⃣ Facebook Messenger ➜ Liluvine PRO

```json
{
  "name": "Liluvine PRO — Facebook Inbound",
  "nodes": [
    {
      "parameters": { "httpMethod": "POST", "path": "liluvine-facebook", "responseMode": "lastNode" },
      "id": "webhook-fb-in",
      "name": "Webhook (Messenger)",
      "type": "n8n-nodes-base.webhook",
      "typeVersion": 1.1,
      "position": [240, 300]
    },
    {
      "parameters": {
        "jsCode": "const entry = (items[0].json.entry || [])[0] || {};\nconst event = (entry.messaging || [])[0] || {};\nconst from = (event.sender && event.sender.id) || '';\nconst text = (event.message && event.message.text) || '';\nreturn [{ json: { from, text } }];"
      },
      "id": "extract-fb",
      "name": "Extract text",
      "type": "n8n-nodes-base.code",
      "typeVersion": 2,
      "position": [480, 300]
    },
    {
      "parameters": {
        "method": "POST",
        "url": "={{$env.SAWALI_BASE_URL}}/api/webhooks/liluvine-pro/facebook/{{$env.LILUVINE_INBOUND_SECRET}}",
        "sendBody": true,
        "specifyBody": "json",
        "jsonBody": "={\n  \"text\": $json.text,\n  \"from\": $json.from,\n  \"channel\": \"facebook\",\n  \"session_id\": \"fb-\" + $json.from\n}",
        "options": { "timeout": 30000 }
      },
      "id": "call-liluvine-fb",
      "name": "POST Liluvine PRO",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.2,
      "position": [720, 300]
    }
  ],
  "connections": {
    "Webhook (Messenger)": { "main": [[{ "node": "Extract text", "type": "main", "index": 0 }]] },
    "Extract text":        { "main": [[{ "node": "POST Liluvine PRO", "type": "main", "index": 0 }]] }
  }
}
```

---

## 3️⃣ SMS générique (Twilio / InfoBip / OrangeAPI) ➜ Liluvine PRO

```json
{
  "name": "Liluvine PRO — SMS Inbound",
  "nodes": [
    {
      "parameters": { "httpMethod": "POST", "path": "liluvine-sms", "responseMode": "lastNode" },
      "id": "webhook-sms-in",
      "name": "Webhook (SMS provider)",
      "type": "n8n-nodes-base.webhook",
      "typeVersion": 1.1,
      "position": [240, 300]
    },
    {
      "parameters": {
        "jsCode": "// Adapter Twilio / Infobip / Orange selon le provider.\n// Twilio :     From + Body\n// Infobip :    sender + text\n// Orange SMS : msisdn + text\nconst j = items[0].json;\nconst from = j.From || j.sender || j.msisdn || j.from || '';\nconst text = j.Body || j.text || j.message || '';\nreturn [{ json: { from, text } }];"
      },
      "id": "normalize-sms",
      "name": "Normalize",
      "type": "n8n-nodes-base.code",
      "typeVersion": 2,
      "position": [480, 300]
    },
    {
      "parameters": {
        "method": "POST",
        "url": "={{$env.SAWALI_BASE_URL}}/api/webhooks/liluvine-pro/custom/{{$env.LILUVINE_INBOUND_SECRET}}",
        "sendBody": true,
        "specifyBody": "json",
        "jsonBody": "={\n  \"text\": $json.text,\n  \"from\": $json.from,\n  \"channel\": \"sms\",\n  \"session_id\": \"sms-\" + $json.from\n}",
        "options": { "timeout": 30000 }
      },
      "id": "call-liluvine-sms",
      "name": "POST Liluvine PRO",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.2,
      "position": [720, 300]
    }
  ],
  "connections": {
    "Webhook (SMS provider)": { "main": [[{ "node": "Normalize", "type": "main", "index": 0 }]] },
    "Normalize":              { "main": [[{ "node": "POST Liluvine PRO", "type": "main", "index": 0 }]] }
  }
}
```

---

## 4️⃣ Email (IMAP / Mailgun / SendGrid Inbound Parse) ➜ Liluvine PRO

```json
{
  "name": "Liluvine PRO — Email Inbound",
  "nodes": [
    {
      "parameters": {
        "protocol": "imap",
        "mailbox": "INBOX",
        "options": { "downloadAttachments": false }
      },
      "id": "imap-in",
      "name": "IMAP Trigger",
      "type": "n8n-nodes-base.emailReadImap",
      "typeVersion": 2,
      "position": [240, 300]
    },
    {
      "parameters": {
        "jsCode": "const j = items[0].json;\nconst from = j.from || j.headers?.from || '';\nconst text = (j.text || j.textHtml || j.subject || '').toString().slice(0, 4000);\nreturn [{ json: { from, text, subject: j.subject || '' } }];"
      },
      "id": "extract-mail",
      "name": "Extract body",
      "type": "n8n-nodes-base.code",
      "typeVersion": 2,
      "position": [480, 300]
    },
    {
      "parameters": {
        "method": "POST",
        "url": "={{$env.SAWALI_BASE_URL}}/api/webhooks/liluvine-pro/custom/{{$env.LILUVINE_INBOUND_SECRET}}",
        "sendBody": true,
        "specifyBody": "json",
        "jsonBody": "={\n  \"text\": $json.subject + \"\\n\\n\" + $json.text,\n  \"from\": $json.from,\n  \"channel\": \"email\",\n  \"session_id\": \"mail-\" + $json.from\n}",
        "options": { "timeout": 30000 }
      },
      "id": "call-liluvine-mail",
      "name": "POST Liluvine PRO",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.2,
      "position": [720, 300]
    }
  ],
  "connections": {
    "IMAP Trigger": { "main": [[{ "node": "Extract body", "type": "main", "index": 0 }]] },
    "Extract body": { "main": [[{ "node": "POST Liluvine PRO", "type": "main", "index": 0 }]] }
  }
}
```

---

## 5️⃣ Liluvine PRO ➜ n8n (réponse sortante)

Liluvine envoie la réponse à `liluvine_pro_n8n_outbound_url` avec `Authorization: Bearer <token>`.
n8n dispatche ensuite vers le canal d'origine (`channel` dans le payload).

```json
{
  "name": "Liluvine PRO — Outbound Dispatcher",
  "nodes": [
    {
      "parameters": {
        "httpMethod": "POST",
        "path": "liluvine-outbound",
        "responseMode": "lastNode",
        "options": { "rawBody": false }
      },
      "id": "webhook-out",
      "name": "Webhook (Liluvine→n8n)",
      "type": "n8n-nodes-base.webhook",
      "typeVersion": 1.1,
      "position": [240, 300]
    },
    {
      "parameters": {
        "conditions": {
          "string": [
            { "value1": "={{$headers.authorization}}", "operation": "equals", "value2": "=Bearer {{$env.LILUVINE_OUTBOUND_TOKEN}}" }
          ]
        }
      },
      "id": "auth-guard",
      "name": "Auth Guard",
      "type": "n8n-nodes-base.if",
      "typeVersion": 1,
      "position": [480, 300]
    },
    {
      "parameters": {
        "rules": {
          "rules": [
            { "value2": "whatsapp", "operation": "equals" },
            { "value2": "facebook", "operation": "equals" },
            { "value2": "sms",      "operation": "equals" },
            { "value2": "email",    "operation": "equals" }
          ]
        },
        "value1": "={{$json.channel}}"
      },
      "id": "switch-channel",
      "name": "Channel Switch",
      "type": "n8n-nodes-base.switch",
      "typeVersion": 1,
      "position": [720, 300]
    }
  ],
  "connections": {
    "Webhook (Liluvine→n8n)": { "main": [[{ "node": "Auth Guard", "type": "main", "index": 0 }]] },
    "Auth Guard":              { "main": [[{ "node": "Channel Switch", "type": "main", "index": 0 }]] }
  }
}
```

> Ajoutez derrière chaque sortie du `Switch` un nœud HTTP qui appelle l'API
> du provider correspondant (Meta Graph pour WhatsApp/Facebook, Twilio pour SMS,
> votre SMTP/Mailgun pour email). Le payload entrant contient :
>
> ```json
> { "channel": "whatsapp|facebook|sms|email",
>   "to": "+228...",
>   "text": "<réponse Liluvine PRO>",
>   "session_id": "wa-..." }
> ```

---

## 🔧 Variables d'environnement n8n à définir

| Variable | Description | Exemple |
|---|---|---|
| `SAWALI_BASE_URL` | URL de production SAWALI | `https://sawalismartsystems.com` |
| `LILUVINE_INBOUND_SECRET` | Secret de l'admin pour l'inbound | `<token aléatoire 32 caractères>` |
| `LILUVINE_OUTBOUND_TOKEN` | Bearer pour valider le retour Liluvine→n8n | `<token aléatoire 32 caractères>` |

---

## 🚦 Tests rapides (curl)

```bash
# Test direct sur l'inbound
curl -X POST "$SAWALI_BASE_URL/api/webhooks/liluvine-pro/n8n/$LILUVINE_INBOUND_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"text":"Bonjour Liluvine, donne-moi un résumé des derniers paiements.","channel":"n8n","from":"test"}'
```

Vérifiez la réponse JSON :
- `session_id`
- `reply` (texte généré par Claude)
- `tokens_used`
- `forwarded_to_n8n` (true si l'outbound est configuré)

---
*Document généré automatiquement par l'agent Emergent · Iter38r-fix8 · 2026-05-28*
