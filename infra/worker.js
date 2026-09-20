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

// Secrets pasted into a dashboard pick up stray whitespace and newlines more
// often than not, and a token with a trailing newline fails as a flat 404 with
// nothing to distinguish it from a wrong token. Trimming here costs nothing
// and removes a whole afternoon of confusion.
const clean = (value) => String(value ?? "").trim();

const REPO = "ikervillena/agent-liga-fantasy";
const RAW = `https://raw.githubusercontent.com/${REPO}/main/state`;
const MODEL = "claude-sonnet-5";

export default {
  async fetch(request, env, ctx) {
    // A relay that fails silently is untestable from outside, and the first
    // time it broke that is exactly what happened: Telegram reported a clean
    // delivery, the Worker returned 200, and nothing arrived. This says which
    // half is at fault without exposing a single secret value.
    if (new URL(request.url).pathname === "/health") return health(env);
    if (request.method !== "POST") return new Response("ok");
    // Telegram echoes this header back; without it anyone could post here.
    if (request.headers.get("x-telegram-bot-api-secret-token") !== clean(env.WEBHOOK_SECRET)) {
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

  await react(message, env);

  const [digest, persona] = await Promise.all([text(`${RAW}/digest.txt`), text(`${RAW}/persona.txt`)]);
  if (!digest) return send("No tengo el informe de la liga todavía.", env);

  // Telegram's typing indicator expires after about five seconds and the model
  // takes fifteen or more, so a single `sendChatAction` showed "escribiendo…"
  // briefly and then left the chat looking dead for the rest of the wait. It
  // has to be renewed while the thinking happens.
  const stop = keepTyping(env);
  let reply;
  try {
    reply = await ask(question, digest, persona, env);
  } finally {
    stop();
  }

  // Sent one at a time, with the indicator up and a pause in between, because
  // three messages arriving in the same instant is not what several messages
  // from a person looks like — it is one wall of text in three pieces.
  const parts = split(reply);
  for (const [index, part] of parts.entries()) {
    if (index > 0) {
      await typing(env);
      await sleep(pause(part));
    }
    await send(part, env);
  }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Long enough to read as composed rather than pasted, short enough that three
// messages do not add ten seconds to an answer that already took fifteen.
const pause = (part) => Math.min(2500, 500 + part.length * 8);

// Renews the typing action until the returned function is called. Waiting on a
// timer costs no CPU time on Workers, which bills execution rather than wall
// clock, so this is free — but it must be stoppable in a `finally`, or a failed
// model call would leave the loop running for the life of the instance.
function keepTyping(env) {
  let live = true;
  (async () => {
    while (live) {
      await typing(env);
      await sleep(4000);
    }
  })();
  return () => {
    live = false;
  };
}

async function ask(question, digest, persona, env) {
  const response = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": clean(env.ANTHROPIC_API_KEY),
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify({
      model: MODEL,
      // Headroom for adaptive thinking, which spends over a thousand tokens
      // before writing a word. At 1500 the reply was truncated or empty.
      max_tokens: 3000,
      thinking: { type: "adaptive" },
      output_config: { effort: "medium" },
      system: [
        { type: "text", text: persona },
        { type: "text", text: digest, cache_control: { type: "ephemeral" } },
      ],
      messages: [{ role: "user", content: question }],
    }),
  });

  const data = await response.json().catch(() => null);
  if (!response.ok || !data) {
    console.error(`anthropic ${response.status}: ${JSON.stringify(data)}`);
    return `No he podido responder: ${data?.error?.message ?? response.status}`;
  }
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
      authorization: `Bearer ${clean(env.GITHUB_TOKEN)}`,
      accept: "application/vnd.github+json",
      "content-type": "application/json",
      "user-agent": "fantasy-agent-relay",
    },
    body: JSON.stringify({ event_type: "decision", client_payload: { key, verdict } }),
  });
}

// Paragraphs become separate messages: a person making three points in a chat
// sends three messages, not one essay.
//
// The previous version only ever split on blank lines, and only above 320
// characters. A single dense paragraph — which is most of what the model
// actually writes — passed through whole however long it was. That was the
// "biblia": not a formatting failure so much as a splitter that gave up
// whenever there was nothing convenient to split on.
const SOFT_LIMIT = 260;

function split(body) {
  const parts = [];
  for (const block of body.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean)) {
    if (block.length <= SOFT_LIMIT) parts.push(block);
    else parts.push(...sentences(block));
  }
  if (!parts.length) return [body];
  // Never more than three: past that it stops reading as a conversation and
  // starts reading as a notification storm.
  return parts.length > 3 ? [...parts.slice(0, 2), parts.slice(2).join(" ")] : parts;
}

// Break a long block at sentence ends, packing as much into each message as
// fits under the limit. Splitting mid-sentence would read worse than not
// splitting at all.
function sentences(block) {
  const out = [];
  let current = "";
  for (const piece of block.split(/(?<=[.!?…])\s+/)) {
    if (current && `${current} ${piece}`.length > SOFT_LIMIT) {
      out.push(current);
      current = piece;
    } else {
      current = current ? `${current} ${piece}` : piece;
    }
  }
  if (current) out.push(current);
  return out;
}

const react = (message, env) =>
  api("setMessageReaction", {
    chat_id: message.chat.id,
    message_id: message.message_id,
    reaction: [{ type: "emoji", emoji: "👀" }],
  }, env);

const typing = (env) => api("sendChatAction", { chat_id: clean(env.TELEGRAM_CHAT_ID), action: "typing" }, env);

const send = (text, env) =>
  api("sendMessage", { chat_id: clean(env.TELEGRAM_CHAT_ID), text, disable_web_page_preview: true }, env);

// Failures are logged rather than swallowed: discarding them turned a wrong
// chat id into total silence, with a clean 200 on the wire and nothing to look
// at. Returns Telegram's own parsed reply rather than the HTTP response, since
// the API answers 200 with `ok:false` often enough that the status alone is
// not the answer.
async function api(method, payload, env) {
  try {
    const response = await fetch(`https://api.telegram.org/bot${clean(env.TELEGRAM_TOKEN)}/${method}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await response.json().catch(() => ({ ok: false, description: "unparseable" }));
    if (!body.ok) console.error(`telegram ${method}: ${body.description}`);
    return body;
  } catch (error) {
    console.error(`telegram ${method} threw: ${error}`);
    return { ok: false, description: String(error) };
  }
}

// Which half is broken, without revealing what any secret contains.
async function health(env) {
  const present = (name) => Boolean(env[name] && String(env[name]).trim());
  // A token that differs only by a trailing newline looks identical in a
  // dashboard, so the length is reported: it is the one property that
  // distinguishes "wrong value" from "right value, stray whitespace".
  const report = {
    token_length: clean(env.TELEGRAM_TOKEN).length,
    secrets: Object.fromEntries(
      ["ANTHROPIC_API_KEY", "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID", "WEBHOOK_SECRET", "GITHUB_TOKEN"]
        .map((name) => [name, present(name)]),
    ),
    chat_id_looks_numeric: /^-?\d+$/.test(String(env.TELEGRAM_CHAT_ID ?? "").trim()),
    digest_chars: (await text(`${RAW}/digest.txt`)).length,
    persona_chars: (await text(`${RAW}/persona.txt`)).length,
  };

  // getMe proves the token; a send to the configured chat proves the chat id.
  const me = await api("getMe", {}, env);
  report.telegram_token_ok = Boolean(me.ok);
  const probe = await api(
    "sendMessage",
    { chat_id: clean(env.TELEGRAM_CHAT_ID), text: "✅ Relay operativo." },
    env,
  );
  report.can_send_to_chat = Boolean(probe.ok);
  if (!probe.ok) report.send_error = probe.description;

  return new Response(JSON.stringify(report, null, 2), {
    headers: { "content-type": "application/json" },
  });
}

async function text(url) {
  const response = await fetch(url, { cf: { cacheTtl: 60 } });
  return response.ok ? response.text() : "";
}
