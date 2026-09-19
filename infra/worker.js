// The chat relay: Telegram in, Claude out.
//
// This exists because GitHub Actions is not a chat transport. A workflow
// scheduled every five minutes ran twice in nine hours — GitHub drops
// high-frequency cron under load — so questions went unanswered for hours and
// then arrived three at a time. A webhook fixes that, but a webhook needs
// something always listening, which the agent is not.
//
// The important property of this file is how little it knows. It holds no
// opinion about fantasy football: it fetches the digest and the persona that
// the Python agent publishes on every sync, posts them to the model verbatim,
// and sends back what comes out. Every question of what the agent knows and how
// it speaks stays in the repository, in one language, under test. If this file
// ever starts making decisions, that is the bug.
//
// Button presses take the other path: they change state that lives in the repo,
// so they are forwarded to GitHub Actions as a dispatch and applied there.

const REPO = "ikervillena/agent-liga-fantasy";
const RAW = `https://raw.githubusercontent.com/${REPO}/main/state`;
const MODEL = "claude-sonnet-5";

export default {
  async fetch(request, env, ctx) {
    if (request.method !== "POST") return new Response("ok");
    // Telegram echoes this header back; without it anyone could post here.
    if (request.headers.get("x-telegram-bot-api-secret-token") !== env.WEBHOOK_SECRET) {
      return new Response("forbidden", { status: 403 });
    }

    const update = await request.json();
    // Acknowledge Telegram at once and keep working afterwards: without
    // `waitUntil` the runtime cancels the pending work the moment this
    // response is returned, and without the early return Telegram would retry
    // the same update while the model is still thinking — answering twice.
    ctx.waitUntil(
      update.callback_query ? decide(update.callback_query, env) : answer(update.message, env),
    );
    return new Response("ok", { headers: { "content-type": "text/plain" } });
  },
};

async function answer(message, env) {
  const question = message?.text?.trim();
  if (!question) return;

  await Promise.all([react(message, env), typing(env)]);

  const [digest, persona] = await Promise.all([text(`${RAW}/digest.txt`), text(`${RAW}/persona.txt`)]);
  if (!digest) return send("No tengo el informe de la liga todavía.", env);

  const reply = await ask(question, digest, persona, env);
  for (const part of split(reply)) await send(part, env);
}

async function ask(question, digest, persona, env) {
  const response = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": env.ANTHROPIC_API_KEY,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify({
      model: MODEL,
      max_tokens: 1500,
      thinking: { type: "adaptive" },
      output_config: { effort: "medium" },
      system: [
        { type: "text", text: persona },
        { type: "text", text: digest, cache_control: { type: "ephemeral" } },
      ],
      messages: [{ role: "user", content: question }],
    }),
  });

  const data = await response.json();
  if (!response.ok) return `No he podido responder: ${data?.error?.message ?? response.status}`;
  const out = (data.content ?? [])
    .filter((b) => b.type === "text")
    .map((b) => b.text)
    .join("\n")
    .trim();
  return out || "No he podido responder.";
}

// A tapped button changes approval state, which lives in the repository, so it
// is applied there rather than here.
async function decide(callback, env) {
  const [key, verdict] = String(callback.data ?? "").split(":");
  await api("answerCallbackQuery", { callback_query_id: callback.id, text: "Hecho" }, env);
  if (!key) return;

  await fetch(`https://api.github.com/repos/${REPO}/dispatches`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.GITHUB_TOKEN}`,
      accept: "application/vnd.github+json",
      "content-type": "application/json",
      "user-agent": "fantasy-agent-relay",
    },
    body: JSON.stringify({ event_type: "decision", client_payload: { key, verdict } }),
  });
}

// Paragraphs become separate messages: a person making three points in a chat
// sends three messages, not one essay.
function split(body) {
  if (body.length <= 320) return [body];
  const parts = body.split("\n\n").map((p) => p.trim()).filter(Boolean);
  if (parts.length < 2) return [body];
  return parts.length > 3 ? [...parts.slice(0, 2), parts.slice(2).join("\n\n")] : parts;
}

const react = (message, env) =>
  api("setMessageReaction", {
    chat_id: message.chat.id,
    message_id: message.message_id,
    reaction: [{ type: "emoji", emoji: "👀" }],
  }, env);

const typing = (env) => api("sendChatAction", { chat_id: env.TELEGRAM_CHAT_ID, action: "typing" }, env);

const send = (text, env) =>
  api("sendMessage", { chat_id: env.TELEGRAM_CHAT_ID, text, disable_web_page_preview: true }, env);

async function api(method, payload, env) {
  return fetch(`https://api.telegram.org/bot${env.TELEGRAM_TOKEN}/${method}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  }).catch(() => null);
}

async function text(url) {
  const response = await fetch(url, { cf: { cacheTtl: 60 } });
  return response.ok ? response.text() : "";
}
