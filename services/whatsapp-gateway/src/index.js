// WAINT WhatsApp Gateway
// - Maintains the WhatsApp Web session (whatsapp-web.js, LocalAuth on a volume)
// - Forwards inbound messages to the backend internal endpoint
// - Exposes POST /send for the backend/workers to deliver outbound messages
//
// This is the ONE stateful, hard-to-scale component. It is intentionally thin so it
// can be swapped for the official WhatsApp Cloud API behind the same /send + inbound
// webhook contract.

import express from 'express';
import pkg from 'whatsapp-web.js';
import qrcode from 'qrcode-terminal';
import axios from 'axios';
import pino from 'pino';

const { Client, LocalAuth } = pkg;
const log = pino({ level: 'info' });

const INBOUND_URL = process.env.WA_BACKEND_INBOUND_URL || 'http://backend:8000/api/v1/internal/wa/inbound';
const INTERNAL_TOKEN = process.env.INTERNAL_TOKEN || 'change-me';
const SESSION_PATH = process.env.WA_SESSION_PATH || '/data/wa-session';
const PORT = parseInt(process.env.PORT || '3000', 10);

const client = new Client({
  authStrategy: new LocalAuth({ dataPath: SESSION_PATH }),
  puppeteer: {
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  },
});

let ready = false;

client.on('qr', (qr) => {
  log.warn('Scan this QR code with the company WhatsApp number:');
  qrcode.generate(qr, { small: true });
});

client.on('ready', () => {
  ready = true;
  log.info('WhatsApp client ready');
});

client.on('disconnected', (reason) => {
  ready = false;
  log.error({ reason }, 'WhatsApp disconnected — re-auth may be required');
});

// inbound: forward to backend, reply with whatever the AI returns
client.on('message', async (msg) => {
  if (msg.isStatus || msg.from.endsWith('@g.us')) return; // ignore status & group msgs
  const waId = '+' + msg.from.split('@')[0];
  try {
    const { data } = await axios.post(
      INBOUND_URL,
      { wa_id: waId, message_id: msg.id?._serialized, text: msg.body, timestamp: msg.timestamp },
      { headers: { 'X-Internal-Token': INTERNAL_TOKEN }, timeout: 30000 }
    );
    if (data?.reply) await msg.reply(data.reply);
  } catch (err) {
    log.error({ err: err.message, waId }, 'inbound handling failed');
    await msg.reply('⚠️ Sorry, I had trouble with that. Please try again in a moment.');
  }
});

client.initialize();

// ---- HTTP API for outbound (reminders, broadcasts, escalations) ----
const app = express();
app.use(express.json());

function auth(req, res, next) {
  if (req.headers['x-internal-token'] !== INTERNAL_TOKEN) return res.status(401).json({ error: 'unauthorized' });
  next();
}

app.get('/healthz', (_req, res) => res.json({ status: ready ? 'ready' : 'starting' }));

app.post('/send', auth, async (req, res) => {
  const { wa_id, text } = req.body || {};
  if (!wa_id || !text) return res.status(422).json({ error: 'wa_id and text required' });
  if (!ready) return res.status(503).json({ error: 'wa_not_ready' });
  try {
    const chatId = wa_id.replace('+', '') + '@c.us';
    // human-like jitter to reduce ban risk on bulk sends
    await new Promise((r) => setTimeout(r, 200 + Math.floor(Math.random() * 600)));
    await client.sendMessage(chatId, text);
    res.json({ ok: true });
  } catch (err) {
    log.error({ err: err.message, wa_id }, 'send failed');
    res.status(500).json({ error: 'send_failed' });
  }
});

app.listen(PORT, () => log.info(`gateway HTTP listening on ${PORT}`));
