// بوت المحرك: يستقبل ضغطات سيدي في تيليجرام.
// «انشر» ينسخ الصورة ونصها إلى القناة، و«بديل جديد» أو رسالة تبدأ بـ«عدّل» يطلبان منشورًا جديدًا من GitHub.
// الأسرار: TELEGRAM_BOT_TOKEN, OWNER_CHAT_ID, CHANNEL_ID, WEBHOOK_SECRET, GH_TOKEN, GH_REPO

const OK = () => new Response("ok");

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    // ربط البوت بهذا الـWorker بزيارة واحدة لـ /setup (لا يكشف أي سر)
    if (req.method === "GET" && url.pathname === "/setup") {
      const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/setWebhook`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ url: `${url.origin}/`, secret_token: env.WEBHOOK_SECRET, allowed_updates: ["message", "callback_query"] }),
      }).then((r) => r.json());
      return new Response(r.ok ? "تم ربط البوت ✅" : "تعذّر الربط: " + r.description, { headers: { "content-type": "text/plain; charset=utf-8" } });
    }
    if (req.method !== "POST") return OK();
    if (req.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET) return new Response("forbidden", { status: 403 });

    const u = await req.json();
    const owner = String(env.OWNER_CHAT_ID);
    const api = (m, b) =>
      fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${m}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(b),
      }).then((r) => r.json());

    if (u.callback_query) {
      const q = u.callback_query;
      if (String(q.from.id) !== owner) return OK();
      const [act, arg] = String(q.data || "").split(":");
      let note = "";
      if (act === "pub") {
        const r = await api("copyMessage", { chat_id: env.CHANNEL_ID, from_chat_id: owner, message_id: Number(arg) });
        note = r.ok ? "نُشر في القناة ✅" : "تعذّر النشر: " + (r.description || "");
        if (r.ok)
          await api("editMessageReplyMarkup", {
            chat_id: owner,
            message_id: q.message.message_id,
            reply_markup: { inline_keyboard: [[{ text: "✅ نُشر في القناة", callback_data: "done:0" }]] },
          });
      } else if (act === "regen") {
        note = (await dispatch(env, { slot: arg || "morning", force: "1", note: "" }))
          ? "يُعَدّ بديل جديد، يصلك خلال دقائق ⏳"
          : "تعذّر طلب البديل";
      }
      await api("answerCallbackQuery", { callback_query_id: q.id, text: note || "تم" });
      return OK();
    }

    const m = u.message;
    // قبل ضبط OWNER_CHAT_ID: يرد البوت على أول رسالة برقم المحادثة ليُحفظ سرًّا
    if (m && !env.OWNER_CHAT_ID) {
      await api("sendMessage", { chat_id: m.chat.id, text: "رقم محادثتك: " + m.chat.id + "\nضعه في السر OWNER_CHAT_ID." });
      return OK();
    }
    if (m && String(m.chat.id) === owner && m.text) {
      const t = m.text.trim();
      if (/^(عدّل|عدل|منشور)/.test(t)) {
        const ok = await dispatch(env, { slot: "morning", force: "1", note: t });
        await api("sendMessage", { chat_id: owner, text: ok ? "حاضر يا مولاي 🫡 يُعَدّ منشور بملاحظتك، يصلك خلال دقائق." : "تعذّر الطلب، حاول بعد قليل." });
      } else {
        await api("sendMessage", {
          chat_id: owner,
          text: "أوامري يا مولاي 🫡\n• «✅ انشر» تحت أي منشور: يُنشر في القناة.\n• «🔁 بديل جديد»: منشور آخر.\n• اكتب «عدّل: ملاحظتك» أو «منشور: فكرتك» لمنشور جديد بتوجيهك.",
        });
      }
    }
    return OK();
  },
};

async function dispatch(env, inputs) {
  const r = await fetch(`https://api.github.com/repos/${env.GH_REPO}/actions/workflows/engine.yml/dispatches`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.GH_TOKEN}`,
      accept: "application/vnd.github+json",
      "user-agent": "teacher-meshal-engine",
      "content-type": "application/json",
    },
    body: JSON.stringify({ ref: "main", inputs }),
  });
  return r.status === 204;
}
