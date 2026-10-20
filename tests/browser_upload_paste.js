// Run on the upload page with agent-browser eval --stdin < tests/browser_upload_paste.js.
// Stub /api/health as {"ready":true} before loading to test submission too.
(async () => {
  const input = document.querySelector("#video-file");
  const button = document.querySelector("#upload-button");
  const error = document.querySelector("#upload-error");
  const ready = document.querySelector("#service-status").classList.contains("ready");
  const passed = [];
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const video = new File(["video-content"], "访谈.MOV", { type: "" });
  const image = new File(["image"], "cover.png", { type: "image/png" });
  const paste = (files, target = document.body, text = "") => {
    const clipboardData = new DataTransfer();
    files.forEach(file => clipboardData.items.add(file));
    if (text) clipboardData.setData("text/plain", text);
    const event = new ClipboardEvent("paste", { clipboardData, bubbles: true, cancelable: true });
    target.dispatchEvent(event);
    return event;
  };
  assert(paste([video]).defaultPrevented, "Video paste must be handled");
  assert(input.files[0]?.name === "访谈.MOV", "Paste must select the video even without a MIME type");
  assert(document.querySelector("#file-title").textContent === "访谈.MOV", "Selected video must appear");
  assert(button.disabled === !ready, "Pasting must respect the speech service gate");
  passed.push("paste file, filename fallback, service gate");

  paste([image]);
  assert(!error.hidden, "Non-video paste must explain why it was rejected");
  assert(input.files[0]?.name === video.name, "Rejected paste must preserve the selected video");
  paste([], document.body, "https://example.com/video.mp4");
  assert(!error.hidden, "A copied link must not be silently treated as a file");
  const next = new File(["next-video"], "next.webm", { type: "video/webm" });
  paste([image, next]);
  assert(input.files[0]?.name === "next.webm", "Mixed clipboard must choose the first video");
  assert(error.hidden, "A valid paste must clear the previous error");
  passed.push("reject images and links, preserve selection, mixed clipboard");

  const brand = document.querySelector("#clip-brand");
  brand.closest("#clip-template-options").hidden = false;
  brand.focus();
  assert(!paste([video], brand).defaultPrevented, "Paste in text input must remain native");
  assert(input.files[0]?.name === "next.webm", "Text input paste must not replace the video");
  brand.blur();
  brand.closest("#clip-template-options").hidden = true;
  passed.push("preserve native paste in text fields");

  if (ready) {
    const originalSend = XMLHttpRequest.prototype.send;
    const uploads = [];
    XMLHttpRequest.prototype.send = function(form) { uploads.push({ xhr: this, form }); };
    try {
      paste([video]);
      button.click();
      assert(uploads.length === 1, "Analyze must submit exactly once");
      const uploaded = uploads[0].form.get("file");
      assert(uploaded.name === "访谈.MOV" && await uploaded.text() === "video-content", "Upload must contain the pasted bytes and filename");
      paste([next]);
      assert(input.files[0]?.name === "访谈.MOV", "Paste during upload must preserve the in-flight file");
      button.click();
      assert(uploads.length === 1, "Paste during upload must not enable a duplicate upload");
      uploads[0].xhr.onerror();
      paste([next]);
      button.click();
      assert(uploads.length === 2 && uploads[1].form.get("file").name === "next.webm", "Failed upload must allow replacement and retry");
      uploads[1].xhr.onerror();
      passed.push("correct multipart bytes, upload lock, failure retry");
    } finally {
      XMLHttpRequest.prototype.send = originalSend;
    }
  }
  return { ready, passed };
})();
