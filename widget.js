function getWidgetUserId() {

  let uid = localStorage.getItem("widget_user_id");

  if (!uid) {

    uid = "widget_" + crypto.randomUUID();

    localStorage.setItem("widget_user_id", uid);

  }

  return uid;

}



(function () {

  const cfg = window.__NO_CODE_BOT__;

  if (!cfg || !cfg.BOT_ID || !cfg.HOST) {

    console.error("Widget config missing");

    return;

  }



  /* ---------- Bubble ---------- */
  const bubble = document.createElement("div");
  bubble.innerHTML = `<svg viewBox="0 0 24 24" width="24" height="24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>`;
  bubble.style = `
    position:fixed;
    bottom:24px;
    right:24px;
    width:56px;
    height:56px;
    background:linear-gradient(135deg, #667eea, #764ba2);
    color:#fff;
    border-radius:50%;
    cursor:pointer;
    display:flex;
    align-items:center;
    justify-content:center;
    z-index:99999;
    box-shadow:0 8px 24px rgba(102,126,234,0.4);
    transition:transform 0.2s ease, box-shadow 0.2s ease;
  `;

  bubble.onmouseover = () => bubble.style.transform = "scale(1.05) translateY(-2px)";
  bubble.onmouseout = () => bubble.style.transform = "scale(1) translateY(0)";
  document.body.appendChild(bubble);



  /* ---------- Chat Window ---------- */
  const panel = document.createElement("div");
  panel.style = `
    position:fixed;
    bottom:96px;
    right:24px;
    width:360px;
    height:540px;
    background:#fff;
    border-radius:16px;
    box-shadow:0 12px 40px rgba(0,0,0,0.15);
    display:flex;
    flex-direction:column;
    z-index:99999;
    overflow:hidden;
    font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    transform-origin:bottom right;
    transform:scale(0.8);
    opacity:0;
    pointer-events:none;
    transition:all 0.3s cubic-bezier(0.68, -0.55, 0.265, 1.55);
  `;

  panel.innerHTML = `
    <div style="padding:16px 20px;font-weight:600;background:linear-gradient(135deg, #667eea, #764ba2);color:white;display:flex;justify-content:space-between;align-items:center;">
      <div style="display:flex;align-items:center;gap:10px;">
        <span style="width:8px;height:8px;background:#10a37f;border-radius:50%;display:inline-block;box-shadow:0 0 0 2px rgba(16,163,127,0.3);"></span>
        <span style="font-size:16px;">Chatbot</span>
      </div>
      <button id="widget-close" style="background:none;border:none;color:white;font-size:24px;cursor:pointer;opacity:0.8;padding:0;line-height:1;">&times;</button>
    </div>

    <div id="widget-messages" style="flex:1;padding:16px;overflow-y:auto;background:#f9fafb;display:flex;flex-direction:column;gap:12px;">
       <div style="text-align:center;font-size:12px;color:#9ca3af;margin-bottom:8px;">Powered by CodeFree AI</div>
    </div>

    <div style="display:flex;border-top:1px solid #e5e7eb;padding:12px;background:#fff;gap:8px;">
      <input id="widget-input"
        placeholder="Ask something..."
        style="flex:1;padding:12px 16px;border:1px solid #e5e7eb;border-radius:24px;outline:none;font-size:14px;transition:border 0.2s;"
        onfocus="this.style.borderColor='#667eea'"
        onblur="this.style.borderColor='#e5e7eb'"
      />
      <button id="widget-send"
        style="width:42px;height:42px;border:none;background:linear-gradient(135deg, #667eea, #764ba2);color:#fff;border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:transform 0.2s;flex-shrink:0;">
        <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>
      </button>
    </div>
  `;
  document.body.appendChild(panel);



  /* ---------- Toggle ---------- */
  let isOpen = false;
  bubble.onclick = () => {
    isOpen = !isOpen;
    if (isOpen) {
      panel.style.transform = "scale(1)";
      panel.style.opacity = "1";
      panel.style.pointerEvents = "all";
      bubble.innerHTML = `<svg viewBox="0 0 24 24" width="24" height="24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>`;
    } else {
      panel.style.transform = "scale(0.8)";
      panel.style.opacity = "0";
      panel.style.pointerEvents = "none";
      bubble.innerHTML = `<svg viewBox="0 0 24 24" width="24" height="24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>`;
    }
  };

  const closeBtn = panel.querySelector("#widget-close");
  closeBtn.onclick = () => {
    isOpen = false;
    panel.style.transform = "scale(0.8)";
    panel.style.opacity = "0";
    panel.style.pointerEvents = "none";
    bubble.innerHTML = `<svg viewBox="0 0 24 24" width="24" height="24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>`;
  };



  /* ---------- Chat Logic ---------- */

  const messages = panel.querySelector("#widget-messages");

  const input = panel.querySelector("#widget-input");

  const sendBtn = panel.querySelector("#widget-send");



  function addMessage(text, fromUser) {
    const div = document.createElement("div");
    div.style = `
      display:flex;
      justify-content:${fromUser ? "flex-end" : "flex-start"};
      animation: cf-fadeIn 0.3s ease forwards;
    `;
    
    // Create message span
    const span = document.createElement("span");
    span.style = `
      display:inline-block;
      padding:10px 14px;
      border-radius:16px;
      border-bottom-${fromUser ? "right" : "left"}-radius:4px;
      background:${fromUser ? "linear-gradient(135deg, #667eea, #764ba2)" : "#fff"};
      color:${fromUser ? "#fff" : "#1f2937"};
      border:${fromUser ? "none" : "1px solid #e5e7eb"};
      box-shadow:0 2px 5px rgba(0,0,0,0.02);
      max-width:85%;
      font-size:14px;
      line-height:1.4;
      word-wrap:break-word;
    `;
    
    // Safe text rendering - prevents XSS
    span.textContent = text;
    
    div.appendChild(span);
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
  }

  function showTyping() {
    const div = document.createElement("div");
    div.id = "widget-typing";
    div.style = `display:flex;justify-content:flex-start;animation: cf-fadeIn 0.2s ease forwards;`;
    div.innerHTML = `
      <span style="padding:12px 14px;border-radius:16px;border-bottom-left-radius:4px;background:#fff;border:1px solid #e5e7eb;box-shadow:0 2px 5px rgba(0,0,0,0.02);display:flex;gap:4px;align-items:center;">
        <span style="width:6px;height:6px;background:#9ca3af;border-radius:50%;animation:cf-bounce 1.4s infinite ease-in-out both;"></span>
        <span style="width:6px;height:6px;background:#9ca3af;border-radius:50%;animation:cf-bounce 1.4s infinite ease-in-out both;animation-delay:-0.32s;"></span>
        <span style="width:6px;height:6px;background:#9ca3af;border-radius:50%;animation:cf-bounce 1.4s infinite ease-in-out both;animation-delay:-0.16s;"></span>
      </span>
    `;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
  }

  function hideTyping() {
    const typing = messages.querySelector("#widget-typing");
    if (typing) typing.remove();
  }

  // Inject animations
  const style = document.createElement("style");
  style.textContent = `
    @keyframes cf-fadeIn {
      from { opacity: 0; transform: translateY(8px); }
      to { opacity: 1; transform: translateY(0); }
    }
    @keyframes cf-bounce {
      0%, 80%, 100% { transform: scale(0); opacity: 0.5; }
      40% { transform: scale(1); opacity: 1; }
    }
  `;
  document.head.appendChild(style);



  async function handleSend() {
    const msg = input.value.trim();
    if (!msg) return;

    addMessage(msg, true);
    input.value = "";

    // Disable input while waiting for response
    input.disabled = true;
    sendBtn.disabled = true;
    sendBtn.style.opacity = "0.7";
    showTyping();

    try {
      const res = await fetch(cfg.HOST + "/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: msg,
          user_id: getWidgetUserId(),
          bot_id: cfg.BOT_ID,
        }),
      });

      const data = await res.json();
      hideTyping();
      addMessage(data.response || "No response", false);
    } catch (err) {
      hideTyping();
      addMessage("Something went wrong. Please try again.", false);
    } finally {
      input.disabled = false;
      sendBtn.disabled = false;
      sendBtn.style.opacity = "1";
      input.focus();
    }
  }

  sendBtn.onclick = handleSend;

  // Enter key to send message
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") handleSend();
  });

})();

