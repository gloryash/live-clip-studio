(() => {
  const body = document.body;
  const page = body.dataset.page;
  const qs = (selector) => document.querySelector(selector);
  const qsa = (selector) => [...document.querySelectorAll(selector)];
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  async function requestJson(url, options = {}) {
    const response = await fetch(url, options);
    let data = {};
    try { data = await response.json(); } catch (_) { data = {}; }
    if (!response.ok && response.status !== 202) {
      const error = new Error(data?.detail?.message || data?.message || `请求失败 ${response.status}`);
      error.payload = data;
      throw error;
    }
    return { response, data };
  }

  function formatBytes(bytes) {
    if (!Number.isFinite(bytes)) return "";
    const units = ["B", "KB", "MB", "GB"];
    let value = bytes, index = 0;
    while (value >= 1024 && index < units.length - 1) { value /= 1024; index += 1; }
    return `${value.toFixed(index > 1 ? 1 : 0)} ${units[index]}`;
  }

  function formatTime(seconds) {
    const ms = Math.max(0, Math.round(Number(seconds || 0) * 1000));
    const hours = Math.floor(ms / 3600000);
    const minutes = Math.floor((ms % 3600000) / 60000);
    const secs = Math.floor((ms % 60000) / 1000);
    const millis = ms % 1000;
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}.${String(millis).padStart(3, "0")}`;
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[character]);
  }

  async function initUpload() {
    const input = qs("#video-file"), button = qs("#upload-button"), drop = qs("#drop-zone");
    const warning = qs("#whisper-warning"), status = qs("#service-status"), error = qs("#upload-error");
    let ready = false;

    async function checkHealth() {
      status.className = "service-pill checking";
      status.lastElementChild.textContent = "检测语音服务";
      try {
        const { data } = await requestJson("/api/health");
        ready = Boolean(data.ready);
        status.className = `service-pill ${ready ? "ready" : "error"}`;
        status.lastElementChild.textContent = ready ? "语音服务已就绪" : "语音服务未开启";
        warning.hidden = ready;
      } catch (healthError) {
        ready = false;
        status.className = "service-pill error";
        status.lastElementChild.textContent = "语音服务未开启";
        warning.hidden = false;
      }
      button.disabled = !ready || !input.files.length;
    }

    function showFile(file) {
      if (!file) return;
      qs("#file-title").textContent = file.name;
      qs("#file-meta").textContent = `${formatBytes(file.size)} · ${file.type || "VIDEO"}`;
      button.disabled = !ready;
    }

    function displayHistory(jobs) {
      const list = qs("#history-list"), empty = qs("#history-empty");
      list.replaceChildren();
      empty.hidden = jobs.length > 0;
      jobs.forEach((job) => {
        const row = document.createElement("a");
        row.className = "history-row";
        row.href = job.workspace_url;
        const title = document.createElement("strong");
        title.textContent = job.filename || "未命名直播录像";
        const duration = document.createElement("span");
        duration.textContent = Number.isFinite(job.duration_seconds) ? formatTime(job.duration_seconds) : "时长待识别";
        const state = document.createElement("span");
        state.className = "history-state";
        state.textContent = `${({uploaded:"已上传",queued:"等待处理",transcribing:"正在转写",diarizing:"识别说话人",ready:"分析就绪",failed:"任务失败"})[job.stage] || job.stage || "未知状态"} · ${String(job.progress || 0).padStart(2, "0")}%`;
        const artifacts = document.createElement("span");
        const speaker = job.speaker_count == null ? "说话人待识别" : `${job.speaker_count} 位说话人`;
        const frames = job.keyframe_count == null ? "关键帧未提取" : `${job.keyframe_count} 张关键帧`;
        artifacts.textContent = `${job.turn_count || 0} 条字幕 · ${speaker} · ${frames}`;
        const arrow = document.createElement("b");
        arrow.textContent = "继续查看 →";
        row.append(title, duration, state, artifacts, arrow);
        list.append(row);
      });
    }

    async function loadHistory() {
      const loading = qs("#history-loading"), empty = qs("#history-empty");
      try {
        const { data } = await requestJson("/api/jobs");
        displayHistory(data.jobs || []);
      } catch (_) {
        empty.textContent = "历史记录暂时无法读取。刷新页面后可以重试。";
        empty.hidden = false;
      } finally {
        loading.hidden = true;
      }
    }

    input.addEventListener("change", () => showFile(input.files[0]));
    ["dragenter", "dragover"].forEach((name) => drop.addEventListener(name, (event) => { event.preventDefault(); drop.classList.add("dragging"); }));
    ["dragleave", "drop"].forEach((name) => drop.addEventListener(name, (event) => { event.preventDefault(); drop.classList.remove("dragging"); }));
    drop.addEventListener("drop", (event) => {
      if (!event.dataTransfer.files.length) return;
      const transfer = new DataTransfer();
      transfer.items.add(event.dataTransfer.files[0]);
      input.files = transfer.files;
      showFile(input.files[0]);
    });

    button.addEventListener("click", () => {
      if (!ready || !input.files[0]) return;
      error.hidden = true;
      button.disabled = true;
      qs("#upload-progress").hidden = false;
      const form = new FormData();
      form.append("file", input.files[0]);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/jobs");
      xhr.upload.onprogress = (event) => {
        if (!event.lengthComputable) return;
        const percent = Math.round(event.loaded / event.total * 100);
        qs("#upload-bar").value = percent;
        qs("#upload-percent").textContent = `${percent}%`;
      };
      xhr.onload = () => {
        let data = {};
        try { data = JSON.parse(xhr.responseText); } catch (_) { data = {}; }
        if (xhr.status >= 200 && xhr.status < 300 && data.workspace_url) {
          if (data.reused) {
            sessionStorage.setItem("liveClipReuseNotice", "已加载上次记录：内容完全相同，未重复分析。");
          }
          window.location.assign(data.workspace_url);
        } else {
          error.textContent = data?.detail?.message || "视频上传失败";
          error.hidden = false;
          button.disabled = false;
        }
      };
      xhr.onerror = () => { error.textContent = "无法连接本地处理服务"; error.hidden = false; button.disabled = false; };
      xhr.send(form);
    });
    await Promise.all([checkHealth(), loadHistory()]);
  }

  async function initClipWorkbench() {
    const sourceList = qs("#clip-source-list");
    const templateList = qs("#clip-template-list");
    const start = qs("#clip-start");
    const error = qs("#clip-error");
    const panel = qs("#clip-run-panel");
    let sources = [], templates = [], runs = [], selectedSource = null, selectedTemplate = null;
    let selectedRunId = null, pollTimer = null, pollingRunId = null, submitting = false;
    const runLabels = { queued: "排队中", running: "转换中", completed: "已完成", needs_review: "已生成 · 需复核", failed: "转换失败" };

    function elapsedLabel(seconds) {
      if (typeof seconds !== "number" || !Number.isFinite(seconds)) return "未记录";
      const total = Math.max(0, Math.round(seconds));
      const hours = Math.floor(total / 3600), minutes = Math.floor(total % 3600 / 60), rest = total % 60;
      return `${hours ? `${hours} 小时 ` : ""}${minutes ? `${minutes} 分 ` : ""}${rest} 秒`;
    }

    function timingLabel(run) {
      if (run.status === "queued") return "等待开始计时";
      const prefix = run.status === "running" ? "已处理" : "处理耗时";
      return `${prefix} ${elapsedLabel(run.timing?.elapsed_seconds)}${run.timing?.origin === "pipeline_history" ? "（最近一次处理）" : ""}`;
    }

    const optionDrafts = new Map();
    function optionsKey() { return `${selectedSource || ""}:${selectedTemplate || ""}`; }
    function currentOptions() {
      if (selectedTemplate !== "editorial") return {};
      const value = optionDrafts.get(optionsKey()) || {};
      return {brand: (value.brand || "").trim(), series: (value.series || "").trim(),
        participants: (value.participants || []).map(p => ({speaker_id:p.speaker_id,name:p.name.trim(),identity:p.identity.trim(),screen_position:"auto"}))
          .filter(p => p.name || p.identity).sort((a,b) => a.speaker_id.localeCompare(b.speaker_id))};
    }
    function sameOptions(a, b) {
      return JSON.stringify(a || {}) === JSON.stringify(b || {});
    }
    function renderOptions() {
      const box = qs("#clip-template-options");
      box.hidden = selectedTemplate !== "editorial";
      if (box.hidden) return;
      const value = currentOptions();
      qs("#clip-brand").value = value.brand;
      qs("#clip-series").value = value.series;
      const speakers = sources.find(s => s.job_id === selectedSource)?.clip_speakers || [];
      qs("#clip-participant-fields").innerHTML = speakers.length ? speakers.map(s => {
        const p = value.participants.find(p => p.speaker_id === s.id) || {};
        return `<div class="clip-person-fields" data-speaker-id="${escapeHtml(s.id)}"><strong>${escapeHtml(s.name)} · ${escapeHtml(s.id)}</strong><label>姓名／称呼<input data-person-name maxlength="16" value="${escapeHtml(p.name || "")}" placeholder="确认后填写"></label><label>身份／职务<input data-person-identity maxlength="32" value="${escapeHtml(p.identity || "")}" placeholder="例如：某公司创始人；未知留空"></label><p class="muted">出镜人物根据本段声音与画面自动匹配，无需选择左右或小窗。</p></div>`;
      }).join("") : '<p>先选择直播，即可按说话人填写资料。</p>';
    }
    qs("#clip-template-options").addEventListener("input", () => {
      optionDrafts.set(optionsKey(), {brand:qs("#clip-brand").value,series:qs("#clip-series").value,
        participants:[...qs("#clip-participant-fields").querySelectorAll("[data-speaker-id]")].map(el => ({
          speaker_id:el.dataset.speakerId,name:el.querySelector("[data-person-name]").value,
          identity:el.querySelector("[data-person-identity]").value,screen_position:el.querySelector("input[type=radio]:checked")?.value || "auto"}))});
      updateStart();
    });

    function matchingRun() {
      return runs.find((run) => run.job_id === selectedSource && run.template_id === selectedTemplate
        && ["queued", "running", "completed", "needs_review"].includes(run.status)
        && (run.template_revision || 1) === (templates.find(t => t.id === selectedTemplate)?.revision || 1)
        && sameOptions(run.template_options, currentOptions()));
    }

    function updateStart() {
      const existing = matchingRun();
      const ready = sources.find((source) => source.job_id === selectedSource)?.clip_ready;
      start.disabled = submitting || !selectedSource || !selectedTemplate || !(existing || ready);
      start.querySelector("span").textContent = existing ? existing.result?.count ? "查看已有成片" : "查看转换进度" : "开始转换";
      start.querySelector("b").textContent = existing ? "OPEN SAVED RESULT →" : "RUN PIPELINE →";
    }

    function renderHistory() {
      qs("#clip-history-list").innerHTML = runs.length ? runs.map((run) => `
        <button type="button" class="clip-history-row${selectedRunId === run.run_id ? " selected" : ""}" data-clip-run="${escapeHtml(run.run_id)}" aria-pressed="${selectedRunId === run.run_id}">
          <strong>${escapeHtml(run.source_filename || "未命名直播")}</strong>
          <span>${escapeHtml(run.template_name || run.template_id)} v${run.template_revision || 1} · ${run.result?.count || 0} 条成片 · ${timingLabel(run)} · ${escapeHtml(runLabels[run.status] || run.status)}</span>
          <time>${escapeHtml(new Date(run.created_at).toLocaleString("zh-CN"))}</time><b>查看记录 →</b>
        </button>`).join("") : '<p class="history-empty">尚无转换记录。生成的成片、评分和评价会自动保留在这里。</p>';
      qsa("[data-clip-run]").forEach((button) => button.addEventListener("click", async () => {
        try {
          const { data } = await requestJson(`/api/clip-runs/${button.dataset.clipRun}`);
          selectedSource = data.job_id;
          selectedTemplate = data.template_id;
          optionDrafts.set(optionsKey(), data.template_options || {});
          renderSources(); renderTemplates(); renderOptions(); renderRun(data);
          panel.scrollIntoView({ behavior: "smooth", block: "start" });
        } catch (historyError) { error.textContent = historyError.message; error.hidden = false; }
      }));
    }

    function rememberRun(run) {
      runs = [run, ...runs.filter((item) => item.run_id !== run.run_id)]
        .sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
    }

    function renderSources() {
      if (!sources.length) {
        sourceList.innerHTML = '<p class="history-empty">还没有可用直播。请先完成字幕和说话人标注。</p>';
        return;
      }
      sourceList.innerHTML = sources.map((source) => {
        const saved = runs.filter((run) => run.job_id === source.job_id && run.result?.count);
        const count = saved.reduce((total, run) => total + run.result.count, 0);
        return `
        <button type="button" class="clip-source-card${selectedSource === source.job_id ? " selected" : ""}" data-clip-source="${escapeHtml(source.job_id)}" aria-pressed="${selectedSource === source.job_id}" ${source.clip_ready || saved.length ? "" : "disabled"}>
          <strong>${escapeHtml(source.filename || "未命名直播")}</strong>
          <span>${source.duration_seconds ? formatTime(source.duration_seconds) : "时长待识别"} · ${source.turn_count || 0} 条字幕 · ${source.speaker_count || 0} 位说话人</span>
          <em>${count ? `已生成 ${count} 条成片 · ${saved.length} 次转换记录` : escapeHtml(source.clip_ready_reason || "")}</em>
        </button>`;
      }).join("");
      qsa("[data-clip-source]").forEach((button) => button.addEventListener("click", () => {
        selectedSource = button.dataset.clipSource;
        renderSources(); renderOptions();
        updateStart();
      }));
    }

    function renderTemplates() {
      templateList.innerHTML = templates.map((template) => `
        <button type="button" class="clip-template-card${selectedTemplate === template.id ? " selected" : ""}" data-clip-template="${escapeHtml(template.id)}" aria-pressed="${selectedTemplate === template.id}">
          <strong>${escapeHtml(template.name)}</strong><p>${escapeHtml(template.description)}</p><span>${template.count} 条候选切片 · ${escapeHtml(template.style_summary || "固定访谈镜头规则")}</span>
        </button>`).join("");
      qsa("[data-clip-template]").forEach((button) => button.addEventListener("click", () => {
        selectedTemplate = button.dataset.clipTemplate;
        renderTemplates(); renderOptions();
        updateStart();
      }));
    }

    function stageLabel(stage) {
      return ({queued: "排队", preflight: "检查输入", ai_selection: "AI 选题", select: "生成配置", plan: "生成剪辑计划", render: "渲染切片", quality_check: "质量检查", qa: "质量检查", completed: "已完成", failed: "失败"})[stage] || stage || "准备中";
    }

    function renderRun(run) {
      selectedRunId = run.run_id;
      rememberRun(run);
      renderHistory(); renderSources(); updateStart();
      panel.hidden = false;
      qs("#clip-run-title").textContent = `${run.source_filename || "自动切片任务"} · ${run.template_name || ""} v${run.template_revision || 1}`;
      qs("#clip-run-status").textContent = run.status === "failed" ? "转换失败" : run.status === "completed" ? "转换完成" : run.status === "needs_review" ? "需要人工复核" : stageLabel(run.stage);
      const seconds = run.timing?.elapsed_seconds;
      const count = run.result?.count || 0;
      const finished = ["completed", "needs_review"].includes(run.status);
      const average = finished && count && typeof seconds === "number" ? ` · 平均每条 ${elapsedLabel(seconds / count)}` : "";
      const mode = run.timing?.origin === "pipeline_history" ? "历史阶段记录还原，可能包含配置或成片复用" : run.timing?.selection_mode === "reuse_decisions" ? "复用已有选题配置" : "";
      qs("#clip-run-timing").textContent = `${count} 条成片 · ${timingLabel(run)}${average}。从开始处理到成片与质检结束，不含排队、转写及手动标注。${mode}`;
      const params = run.template_options;
      if (run.template_id === "editorial" && params) {
        qs("#clip-run-timing").textContent += ` 本次资料：品牌 ${params.brand || "未填"}；栏目 ${params.series || "未填"}；` +
          (params.participants || []).map(p => `${p.name}${p.identity ? `（${p.identity}）` : ""}`).join("、");
      }
      qs("#clip-progress-bar").style.width = `${Math.max(0, Math.min(100, Number(run.progress || 0)))}%`;
      const stages = ["preflight", "ai_selection", "select", "plan", "render", "qa", "completed"];
      const current = stages.indexOf(run.stage);
      qs("#clip-stage-list").innerHTML = stages.map((stage, index) => {
        const elapsed = run.pipeline_stages?.[stage]?.elapsed_seconds;
        return `<span class="clip-stage ${index < current || run.status === "completed" ? "done" : index === current ? "active" : ""}">${stageLabel(stage)}${typeof elapsed === "number" ? ` · ${elapsedLabel(elapsed)}` : ""}</span>`;
      }).join("");
      error.hidden = !run.error;
      if (run.error) {
        error.textContent = run.error.message || "自动切片失败";
        error.hidden = false;
      }
      const clips = run.result?.clips || [];
      qs("#clip-result-list").replaceChildren();
      if (clips.length) {
        qs("#clip-result-list").innerHTML = clips.map((clip) => {
          const virality = clip.virality || {};
          const qa = clip.qa || {};
          const holds = qa.source_visual?.source_holds || [];
          const visualNotes = holds.slice(0, 3).map((hold) => `<p>原直播画面疑似停顿：成片 ${Number(hold.start).toFixed(1)}～${Number(hold.end).toFixed(1)} 秒，请回看确认。</p>`).join("");
          return `<article class="clip-result-card"><video controls playsinline preload="none" poster="${escapeHtml(clip.cover_url)}" src="${escapeHtml(clip.video_url)}" aria-label="${escapeHtml(clip.title || clip.id)}"></video><h4>${escapeHtml(clip.title || clip.id)}</h4><p>${escapeHtml(clip.hook || "")} · ${Number(clip.duration || 0).toFixed(1)} 秒</p><div class="clip-score">${Number(virality.score || 0)}<small>/100 传播系数</small></div><p>${escapeHtml(virality.reason || "暂无模型评价")}</p>${virality.risk ? `<p>传播阻力：${escapeHtml(virality.risk)}</p>` : ""}${qa.status ? `<p>质检：${escapeHtml(qa.status)}</p>` : ""}${visualNotes}<div class="clip-links"><a href="${escapeHtml(clip.video_url)}?download=true" download>下载视频</a><a href="${escapeHtml(clip.cover_url)}?download=true" download>下载封面</a><a href="${escapeHtml(clip.subtitle_url)}?download=true" download>下载字幕</a></div></article>`;
        }).join("");
      }
      const running = run.status === "queued" || run.status === "running";
      if (pollTimer && (pollingRunId !== run.run_id || !running)) {
        clearInterval(pollTimer); pollTimer = null; pollingRunId = null;
      }
      if (running && !pollTimer) {
        pollingRunId = run.run_id;
        pollTimer = window.setInterval(async () => {
          try {
            const { data } = await requestJson(`/api/clip-runs/${run.run_id}`);
            if (selectedRunId === data.run_id) renderRun(data);
          } catch (pollError) { error.textContent = `进度暂时无法读取：${pollError.message}`; error.hidden = false; }
        }, 2000);
      }
    }

    start.addEventListener("click", async () => {
      if (!selectedSource || !selectedTemplate) return;
      submitting = true;
      updateStart();
      error.hidden = true;
      try {
        const existing = matchingRun();
        const { data } = existing
          ? await requestJson(`/api/clip-runs/${existing.run_id}`)
          : await requestJson("/api/clip-runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ job_id: selectedSource, template_id: selectedTemplate, template_options: currentOptions() }) });
        renderRun(data);
        panel.scrollIntoView({ behavior: "smooth", block: "start" });
      } catch (runError) {
        error.textContent = runError.message;
        error.hidden = false;
      } finally {
        submitting = false;
        updateStart();
      }
    });

    try {
      const [{ data: sourceData }, { data: templateData }, { data: runData }] = await Promise.all([
        requestJson("/api/clip-sources"), requestJson("/api/clip-templates"), requestJson("/api/clip-runs"),
      ]);
      sources = sourceData.sources || [];
      templates = templateData.templates || [];
      runs = runData.runs || [];
      qs("#clip-storage-note").textContent = `成片统一保存在：${runData.storage_directory || "exports/auto-clips/"}。刷新或重新启动后记录仍会保留。`;
      renderSources();
      renderTemplates();
      renderHistory();
      const active = runs.find((run) => ["queued", "running"].includes(run.status)) || runs[0];
      if (active) renderRun(active);
    } catch (loadError) {
      sourceList.innerHTML = `<p class="history-empty">${escapeHtml(loadError.message || "自动切片暂时无法读取")}</p>`;
    }
    qs("#clip-history-refresh").addEventListener("click", async () => {
      try {
        const { data } = await requestJson("/api/clip-runs");
        runs = data.runs || [];
        renderHistory(); renderSources(); updateStart();
        const selected = runs.find((run) => run.run_id === selectedRunId);
        if (selected) renderRun(selected);
      } catch (refreshError) { error.textContent = refreshError.message; error.hidden = false; }
    });
  }

  async function initWorkspace() {
    const jobId = body.dataset.jobId;
    const video = qs("#source-video");
    let turns = [], activeSpeaker = "ALL", annotations = {}, deletedTurnIds = new Set(), keyframes = [], keyframeStatus = "not_started", currentPage = 1;
    let autoAnnotationEnabled = false, activeTurnId = null, annotationBusy = false;
    let playbackDebugEntries = [], pendingPlaybackDebug = null;
    let manualSpeakerLabels = { SPEAKER_00: "说话人 1", SPEAKER_01: "说话人 2" };
    let speakerCandidates = [], candidateAllConfirmed = false, candidateSampleEnd = null, classificationReady = false;
    const speakerShortcuts = {
      ArrowLeft: "SPEAKER_00",
      ArrowRight: "SPEAKER_01",
      ArrowDown: "SPEAKER_02",
      ArrowUp: "SPEAKER_03",
    };

    const reuseMessage = sessionStorage.getItem("liveClipReuseNotice");
    if (reuseMessage) {
      qs("#reuse-notice-text").textContent = reuseMessage;
      qs("#reuse-notice").hidden = false;
      sessionStorage.removeItem("liveClipReuseNotice");
    }
    qs("#close-reuse-notice").addEventListener("click", () => { qs("#reuse-notice").hidden = true; });

    video.addEventListener("timeupdate", () => {
      qs("#player-time").textContent = formatTime(video.currentTime);
      if (candidateSampleEnd != null && video.currentTime >= candidateSampleEnd) {
        video.pause();
        candidateSampleEnd = null;
      }
    });
    video.addEventListener("loadedmetadata", () => { qs("#video-duration").textContent = formatTime(video.duration); });
    video.addEventListener("seeked", () => {
      if (!pendingPlaybackDebug) return;
      const difference = video.currentTime - pendingPlaybackDebug.target;
      appendPlaybackDebug(`SEEKED #${pendingPlaybackDebug.turnId}`, `实际 ${formatTime(video.currentTime)} · 与目标差 ${difference.toFixed(3)}s`);
    });
    video.addEventListener("playing", () => {
      if (!pendingPlaybackDebug) return;
      appendPlaybackDebug(`PLAYING #${pendingPlaybackDebug.turnId}`, `真正开始播放 ${formatTime(video.currentTime)}`);
      pendingPlaybackDebug = null;
    });

    function appendPlaybackDebug(label, detail) {
      const clock = new Date().toLocaleTimeString("zh-CN", { hour12: false });
      playbackDebugEntries.unshift(`[${clock}] ${label} · ${detail}`);
      playbackDebugEntries = playbackDebugEntries.slice(0, 30);
      qs("#playback-debug-log").textContent = playbackDebugEntries.join("\n");
    }

    function seekTo(seconds) {
      video.currentTime = Number(seconds);
      video.play().catch(() => {});
      video.scrollIntoView({ behavior: "smooth", block: "center" });
    }

    function visibleTurns() {
      const activeTurns = turns.filter((turn) => !deletedTurnIds.has(String(turn.id)));
      return activeSpeaker === "ALL"
        ? activeTurns
        : activeTurns.filter((turn) => (annotations[String(turn.id)] || turn.speaker) === activeSpeaker);
    }

    function setActiveTurn(turnId, { scroll = true, autoplay = false, reason = "选择字幕" } = {}) {
      const turn = turns.find((item) => String(item.id) === String(turnId));
      if (!turn) return;
      activeTurnId = turn.id;
      video.pause();
      const start = Math.max(0, Number(turn.start) || 0);
      const end = Math.max(start, Number(turn.end) || start);
      const forwardOffset = 0;
      const target = start + forwardOffset;
      pendingPlaybackDebug = { turnId: turn.id, target };
      appendPlaybackDebug(
        `${reason} #${turn.id}`,
        `原始 ${formatTime(start)}–${formatTime(end)} · 时长 ${(end - start).toFixed(3)}s · 前进 ${forwardOffset.toFixed(3)}s · 目标 ${formatTime(target)}`,
      );
      video.currentTime = target;
      if (autoplay) video.play().catch((error) => showAnnotationError(`无法播放视频：${error.message}`));
      qsa("[data-turn-card]").forEach((card) => card.classList.toggle("auto-current", String(card.dataset.turnCard) === String(turn.id)));
      const card = qs(`[data-turn-card="${turn.id}"]`);
      if (scroll && card) card.scrollIntoView({ behavior: "smooth", block: "center" });
    }

    function setAutoAnnotationMode(enabled) {
      autoAnnotationEnabled = Boolean(enabled);
      const toggle = qs("#auto-annotation-mode");
      toggle.setAttribute("aria-pressed", String(autoAnnotationEnabled));
      toggle.textContent = autoAnnotationEnabled ? "快捷标注 ON" : "快捷标注 OFF";
      qs("#annotation-shortcuts").classList.toggle("active", autoAnnotationEnabled);
      if (!autoAnnotationEnabled) {
        activeTurnId = null;
        qsa("[data-turn-card]").forEach((card) => card.classList.remove("auto-current"));
        return;
      }
      activeSpeaker = "ALL";
      renderSpeakerFilters();
      renderTurns();
      const available = visibleTurns();
      const firstUnmarked = available.find((turn) => !annotations[String(turn.id)]) || available[0];
      if (firstUnmarked) setActiveTurn(firstUnmarked.id);
    }

    function renderAnnotationSummary() {
      const activeTurns = turns.filter((turn) => !deletedTurnIds.has(String(turn.id)));
      const annotated = activeTurns.filter((turn) => annotations[String(turn.id)]).length;
      const deleted = deletedTurnIds.size;
      const percentage = activeTurns.length ? (annotated / activeTurns.length) * 100 : 0;
      qs("#annotation-progress").textContent = `人工标注 ${annotated} / ${activeTurns.length || "—"}${deleted ? ` · 已删除 ${deleted}` : ""}`;
      qs("#annotation-percent").textContent = `${percentage.toFixed(2)}%`;
      qs("#export-training").disabled = !activeTurns.length || annotated !== activeTurns.length;
    }

    function renderAiTranscriptExportState() {
      const button = qs("#export-ai-transcript");
      button.disabled = !classificationReady;
      button.title = classificationReady
        ? "导出逐字时间、逐词时间与说话人的 JSON"
        : "请先确认候选说话人并应用到全部字幕";
    }

    function showAnnotationError(message = "") {
      const error = qs("#annotation-error");
      error.textContent = message;
      error.hidden = !message;
    }

    function showCandidateError(message = "") {
      const error = qs("#candidate-error");
      error.textContent = message;
      error.hidden = !message;
    }

    function playCandidateSample(sample) {
      const start = Math.max(0, Number(sample.start) || 0);
      const end = Math.max(start, Number(sample.end) || start);
      candidateSampleEnd = end;
      video.currentTime = start;
      video.play().catch((error) => showCandidateError(`无法播放候选音频：${error.message}`));
      video.scrollIntoView({ behavior: "smooth", block: "center" });
    }

    function renderSpeakerCandidates() {
      const review = qs("#candidate-review");
      review.hidden = false;
      qs("#candidate-status").textContent = `${speakerCandidates.length} 个候选 · ${speakerCandidates.filter((candidate) => candidate.resolved).length} 个已处理`;
      qs("#apply-speaker-classification").disabled = !candidateAllConfirmed;
      qs("#candidate-list").innerHTML = speakerCandidates.map((candidate, candidateIndex) => {
        const options = Object.entries(manualSpeakerLabels).map(([speakerId, label]) => `<option value="${speakerId}"${candidate.speaker_id === speakerId ? " selected" : ""}>${escapeHtml(label)}</option>`).join("");
        const excludedOption = `<option value="__EXCLUDED__"${candidate.resolution === "excluded" ? " selected" : ""}>混合声音 / 错误候选（排除注册）</option>`;
        const samples = (candidate.samples || []).map((sample, sampleIndex) => `
          <button type="button" class="candidate-sample" data-candidate-index="${candidateIndex}" data-sample-index="${sampleIndex}">
            <span>▶ ${formatTime(sample.start)}–${formatTime(sample.end)}</span><small>${escapeHtml(sample.text)}</small>
          </button>`).join("");
        return `
          <article class="candidate-card" data-candidate-id="${escapeHtml(candidate.candidate_id)}">
            <header><div><b>候选 ${String(candidateIndex + 1).padStart(2, "0")}</b><span>${escapeHtml(candidate.candidate_id)}</span></div><small>${candidate.turn_count} 条 · ${Number(candidate.total_duration || 0).toFixed(1)} 秒</small></header>
            <div class="candidate-samples">${samples}</div>
            <div class="candidate-mapping">
              <select aria-label="候选 ${candidateIndex + 1} 对应的真实说话人" data-candidate-speaker>
                <option value="">自动分配下一位</option>${options}${excludedOption}
              </select>
              <input type="text" maxlength="40" placeholder="可选：输入姓名" aria-label="候选 ${candidateIndex + 1} 的姓名" data-candidate-name>
              <button type="button" data-save-candidate>${candidate.resolution === "excluded" ? "已排除 · 混合声音" : candidate.speaker_id ? `已确认 · ${escapeHtml(candidate.speaker_label)}` : "确认人物"}</button>
            </div>
          </article>`;
      }).join("");
      qsa("[data-candidate-index]").forEach((button) => button.addEventListener("click", () => {
        const candidate = speakerCandidates[Number(button.dataset.candidateIndex)];
        const sample = candidate?.samples?.[Number(button.dataset.sampleIndex)];
        if (sample) playCandidateSample(sample);
      }));
      qsa("[data-save-candidate]").forEach((button) => button.addEventListener("click", async () => {
        const card = button.closest("[data-candidate-id]");
        button.disabled = true;
        try {
          await saveCandidateAssignment(card.dataset.candidateId, {
            speakerId: card.querySelector("[data-candidate-speaker]").value,
            speakerName: card.querySelector("[data-candidate-name]").value,
          });
        } catch (error) {
          showCandidateError(error.message);
        } finally {
          button.disabled = false;
        }
      }));
    }

    async function loadSpeakerCandidates() {
      try {
        const { data } = await requestJson(`/api/jobs/${jobId}/speaker-candidates`);
        speakerCandidates = data.candidates || [];
        candidateAllConfirmed = Boolean(data.all_confirmed);
        manualSpeakerLabels = data.speakers || manualSpeakerLabels;
        renderSpeakerCandidates();
      } catch (error) {
        qs("#candidate-review").hidden = false;
        qs("#candidate-status").textContent = "候选不可用";
        qs("#candidate-list").innerHTML = '<p class="candidate-empty">重新生成字幕后，将在这里出现可试听的候选人物。</p>';
        qs("#apply-speaker-classification").disabled = true;
      }
    }

    async function saveCandidateAssignment(candidateId, { speakerId = "", speakerName = "" } = {}) {
      showCandidateError();
      const payload = {};
      if (speakerId === "__EXCLUDED__") payload.resolution = "excluded";
      else if (speakerId) payload.speaker_id = speakerId;
      if (speakerName.trim()) payload.speaker_name = speakerName.trim();
      await requestJson(`/api/jobs/${jobId}/speaker-candidates/${candidateId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      classificationReady = false;
      renderAiTranscriptExportState();
      await Promise.all([loadSpeakerCandidates(), loadAnnotations()]);
      renderSpeakerFilters();
      renderTurns();
    }

    function formatAccuracy(metric) {
      return metric?.accuracy == null ? "—" : `${(metric.accuracy * 100).toFixed(2)}%`;
    }

    async function loadSpeakerMetrics() {
      try {
        const { data } = await requestJson(`/api/jobs/${jobId}/speaker-metrics`);
        const panel = qs("#speaker-metrics");
        panel.hidden = !data.available;
        if (!data.available) return;
        qs("#metrics-coverage").textContent = `标注覆盖 ${(Number(data.coverage || 0) * 100).toFixed(2)}% · ${data.annotated_count}/${data.active_total_count}`;
        qs("#all-labeled-accuracy").textContent = formatAccuracy(data.all_labeled);
        qs("#all-labeled-detail").textContent = `${data.all_labeled.correct} / ${data.all_labeled.count}`;
        qs("#held-out-accuracy").textContent = formatAccuracy(data.held_out);
        qs("#held-out-detail").textContent = `${data.held_out.correct} / ${data.held_out.count} · 已排除注册片段`;
        qs("#long-accuracy").textContent = formatAccuracy(data.long);
        qs("#long-detail").textContent = `${data.long.correct} / ${data.long.count} · ≥ 1 秒`;
        qs("#short-accuracy").textContent = formatAccuracy(data.short);
        qs("#short-detail").textContent = `${data.short.correct} / ${data.short.count} · < 1 秒`;
        qs("#speaker-metric-table").innerHTML = Object.entries(data.speakers || {}).map(([speakerId, metric]) => `
          <div><b>${escapeHtml(manualSpeakerLabels[speakerId] || speakerId)}</b><span>${metric.correct}/${metric.support}</span><span>召回 ${(metric.recall * 100).toFixed(2)}%</span><span>F1 ${(metric.f1 * 100).toFixed(2)}%</span></div>`).join("");
        const confusion = Object.entries(data.confusion || {})
          .map(([pair, count]) => ({ pair: pair.split("->"), count }))
          .filter((item) => item.pair.length === 2 && item.pair[0] !== item.pair[1] && item.count > 0)
          .sort((left, right) => right.count - left.count)
          .slice(0, 8);
        qs("#speaker-confusion-wrap").hidden = confusion.length === 0;
        qs("#speaker-confusion").innerHTML = confusion.map(({ pair, count }) => `
          <span><b>${escapeHtml(manualSpeakerLabels[pair[0]] || pair[0])}</b><i>→</i><b>${escapeHtml(manualSpeakerLabels[pair[1]] || pair[1])}</b><em>${count} 条</em></span>`).join("");
      } catch (_) {
        qs("#speaker-metrics").hidden = true;
      }
    }

    async function applySpeakerClassification() {
      const button = qs("#apply-speaker-classification");
      button.disabled = true;
      classificationReady = false;
      renderAiTranscriptExportState();
      showCandidateError();
      try {
        await requestJson(`/api/jobs/${jobId}/speaker-classification`, { method: "POST" });
        await loadTranscript();
        await loadSpeakerMetrics();
      } catch (error) {
        showCandidateError(error.message);
      } finally {
        button.disabled = !candidateAllConfirmed;
      }
    }

    async function loadAnnotations() {
      const { data } = await requestJson(`/api/jobs/${jobId}/annotations`);
      annotations = data.annotations || {};
      manualSpeakerLabels = data.speakers || manualSpeakerLabels;
      deletedTurnIds = new Set((data.deleted_turn_ids || []).map(String));
      renderAnnotationSummary();
    }

    async function saveAnnotation(turnId, speaker) {
      showAnnotationError();
      const { data } = await requestJson(`/api/jobs/${jobId}/annotations/${turnId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ speaker }),
      });
      annotations[String(data.turn_id)] = data.speaker;
      renderAnnotationSummary();
      qsa(`[data-turn-id="${data.turn_id}"]`).forEach((button) => {
        button.setAttribute("aria-pressed", String(button.dataset.manualSpeaker === data.speaker));
      });
    }

    async function annotateAndAdvance(turnId, speaker) {
      if (annotationBusy) return;
      annotationBusy = true;
      try {
        await saveAnnotation(turnId, speaker);
        if (!autoAnnotationEnabled) return;
        const list = visibleTurns();
        const index = list.findIndex((turn) => String(turn.id) === String(turnId));
        const next = index >= 0 ? list[index + 1] : null;
        if (next) {
          setActiveTurn(next.id, { autoplay: true, reason: "标注后下一条" });
        } else {
          qs("#auto-annotation-mode").textContent = "快捷标注 · 已到末尾";
          video.pause();
        }
      } finally {
        annotationBusy = false;
      }
    }

    async function deleteAndAdvance(turnId) {
      if (annotationBusy) return;
      annotationBusy = true;
      const list = visibleTurns();
      const index = list.findIndex((turn) => String(turn.id) === String(turnId));
      const next = index >= 0 ? list[index + 1] : null;
      try {
        const { data } = await requestJson(`/api/jobs/${jobId}/transcript/turns/${turnId}`, { method: "DELETE" });
        deletedTurnIds = new Set((data.deleted_turn_ids || []).map(String));
        activeTurnId = null;
        renderSpeakerFilters();
        renderTurns();
        renderAnnotationSummary();
        if (next) {
          setActiveTurn(next.id, { autoplay: true, reason: "删除后下一条" });
        } else {
          qs("#auto-annotation-mode").textContent = "快捷标注 · 已到末尾";
          video.pause();
        }
      } finally {
        annotationBusy = false;
      }
    }

    async function addManualSpeaker() {
      showAnnotationError();
      try {
        const { data } = await requestJson(`/api/jobs/${jobId}/speakers`, { method: "POST" });
        manualSpeakerLabels = data.speakers || manualSpeakerLabels;
        renderSpeakerFilters();
        renderTurns();
      } catch (error) {
        showAnnotationError(error.message);
      }
    }

    function renderTurns() {
      const visible = visibleTurns();
      qs("#transcript-list").innerHTML = visible.map((turn) => `
        <article class="transcript-turn${String(turn.id) === String(activeTurnId) ? " auto-current" : ""}" data-turn-card="${turn.id}">
          <button class="transcript-seek" type="button" data-start="${turn.start}">
            <span class="turn-meta"><b class="turn-speaker">${turn.speaker_label}</b><time class="turn-time">${formatTime(turn.start)} — ${formatTime(turn.end)}</time></span>
            <span class="turn-text"></span>
          </button>
          <span class="manual-speaker-actions" role="group" aria-label="人工标记第 ${turn.id} 条字幕的说话人">
            ${Object.entries(manualSpeakerLabels).map(([speaker, label]) => `<button type="button" data-turn-id="${turn.id}" data-manual-speaker="${speaker}" aria-pressed="${annotations[String(turn.id)] === speaker}">${label}</button>`).join("")}
          </span>
        </article>`).join("");
      qsa(".transcript-seek").forEach((element, index) => {
        element.querySelector(".turn-text").textContent = visible[index].text;
        element.addEventListener("click", () => {
          if (autoAnnotationEnabled) setActiveTurn(visible[index].id, { scroll: false });
          else seekTo(element.dataset.start);
        });
      });
      qsa("[data-manual-speaker]").forEach((button) => {
        button.addEventListener("click", async (event) => {
          event.stopPropagation();
          button.disabled = true;
          try {
            if (autoAnnotationEnabled) setActiveTurn(button.dataset.turnId, { scroll: false });
            await annotateAndAdvance(button.dataset.turnId, button.dataset.manualSpeaker);
          } catch (error) {
            showAnnotationError(error.message);
          } finally {
            button.disabled = false;
          }
        });
      });
    }

    function renderSpeakerFilters() {
      const speakers = Object.entries(manualSpeakerLabels);
      const addButton = '<button type="button" class="add-speaker" id="add-speaker" aria-label="添加说话人">＋</button>';
      qs("#speaker-filters").innerHTML = [["ALL", "全部"], ...speakers].map(([id, label]) => `<button type="button" data-speaker="${id}" class="${id === activeSpeaker ? "active" : ""}">${label}</button>`).join("") + addButton;
      qsa("[data-speaker]").forEach((button) => button.addEventListener("click", () => {
        activeSpeaker = button.dataset.speaker;
        renderSpeakerFilters();
        renderTurns();
        if (autoAnnotationEnabled) {
          const first = visibleTurns()[0];
          if (first) setActiveTurn(first.id, { scroll: false });
        }
      }));
      qs("#add-speaker")?.addEventListener("click", addManualSpeaker);
    }

    async function loadTranscript() {
      const { response, data } = await requestJson(`/api/jobs/${jobId}/transcript`);
      if (response.status === 202) {
        classificationReady = false;
        renderAiTranscriptExportState();
        qs("#transcript-stage").textContent = data.stage === "diarizing" ? "正在区分说话人" : "正在识别每一句话";
        return false;
      }
      turns = data.turns || [];
      classificationReady = data.speaker_count_status === "confirmed";
      renderAiTranscriptExportState();
      qs("#transcript-loading").hidden = true;
      qs("#speaker-count").textContent = data.speaker_count == null
        ? "人数未知"
        : data.speaker_count_status === "candidates"
          ? `${data.speaker_count} 个候选人物`
          : `${data.speaker_count} 位说话人`;
      if (data.diarization?.status !== "ready") {
        qs("#diarization-warning").hidden = false;
        qs("#diarization-detail").textContent = data.diarization?.detail || "字幕文字仍然保留。";
      }
      try {
        await loadAnnotations();
      } catch (error) {
        annotations = {};
        deletedTurnIds = new Set();
        showAnnotationError(`无法加载人工标注：${error.message}`);
        renderAnnotationSummary();
      }
      await loadSpeakerCandidates();
      renderSpeakerFilters(); renderTurns();
      await loadSpeakerMetrics();
      return true;
    }

    async function pollWorkspace() {
      try {
        const { data: job } = await requestJson(`/api/jobs/${jobId}`);
        qs("#job-stage").textContent = ({uploaded:"已上传",transcribing:"正在转写",diarizing:"识别说话人",ready:"分析就绪",failed:"任务失败"})[job.stage] || job.stage;
        qs("#job-progress").textContent = `${String(job.progress || 0).padStart(2, "0")}%`;
        qs("#video-filename").textContent = job.filename || "直播录像";
        qs("#retry-failed-transcript").hidden = true;
        if (job.status === "ready") { await loadTranscript(); return; }
        if (job.status === "failed") {
          qs("#transcript-loading").innerHTML = `<b>字幕处理失败</b><small>${job.error?.message || "请重新提交"}</small>`;
          qs("#retry-failed-transcript").hidden = false;
          return;
        }
        await loadTranscript();
      } catch (pollError) {
        qs("#transcript-stage").textContent = pollError.message;
      }
      await sleep(1200); pollWorkspace();
    }

    function switchTab(target) {
      const keyframesTab = target === "keyframes";
      qs("#tab-transcript").classList.toggle("active", !keyframesTab);
      qs("#tab-keyframes").classList.toggle("active", keyframesTab);
      qs("#tab-transcript").setAttribute("aria-selected", String(!keyframesTab));
      qs("#tab-keyframes").setAttribute("aria-selected", String(keyframesTab));
      qs("#panel-transcript").hidden = keyframesTab;
      qs("#panel-keyframes").hidden = !keyframesTab;
      if (keyframesTab) activateKeyframes();
    }

    async function activateKeyframes() {
      try {
        const status = await loadKeyframes();
        if (status === "not_started") startKeyframes();
      } catch (error) {
        qs("#keyframe-error").textContent = error.message;
        qs("#keyframe-error").hidden = false;
      }
    }

    async function startKeyframes() {
      qs("#keyframe-error").hidden = true;
      try {
        const { data } = await requestJson(`/api/jobs/${jobId}/keyframes`, { method: "POST" });
        keyframeStatus = data.status;
        showKeyframeState();
        pollKeyframes();
      } catch (error) {
        qs("#keyframe-error").textContent = error.message;
        qs("#keyframe-error").hidden = false;
      }
    }

    async function reprocessTranscript() {
      if (!window.confirm("只重新生成字幕与说话人；已有关键帧会保留。确定继续吗？")) return;
      const action = qs("#reprocess-transcript");
      action.disabled = true;
      qs("#retry-failed-transcript").hidden = true;
      try {
        await requestJson(`/api/jobs/${jobId}/transcript/reprocess`, { method: "POST" });
        classificationReady = false;
        renderAiTranscriptExportState();
        qs("#transcript-loading").innerHTML = '<span class="spinner"></span><b>正在生成精准字幕时间轴</b><small id="transcript-stage">已重新排队，等待 Whisper</small>';
        qs("#transcript-loading").hidden = false;
        qs("#transcript-list").replaceChildren();
        pollWorkspace();
      } catch (error) {
        qs("#transcript-stage").textContent = error.message;
        qs("#retry-failed-transcript").hidden = false;
      } finally {
        action.disabled = false;
      }
    }

    async function rebuildSpeakerCandidates() {
      if (!window.confirm("只重新生成候选说话人；字幕文字和时间轴不会改变，但旧的候选确认和 AI 说话人分类结果会清除。确定继续吗？")) return;
      const action = qs("#rebuild-speaker-candidates");
      const originalLabel = action.textContent;
      action.disabled = true;
      action.textContent = "正在重新聚类候选…";
      showCandidateError("");
      try {
        await requestJson(`/api/jobs/${jobId}/speaker-candidates/rebuild`, { method: "POST" });
        classificationReady = false;
        renderAiTranscriptExportState();
        await loadCandidateReview();
        await loadTranscript();
      } catch (error) {
        showCandidateError(error.message);
      } finally {
        action.disabled = false;
        action.textContent = originalLabel;
      }
    }

    async function reprocessKeyframes() {
      if (!window.confirm("只重新提取关键帧；已有字幕与说话人记录会保留。确定继续吗？")) return;
      const action = qs("#reprocess-keyframes");
      action.disabled = true;
      try {
        const { data } = await requestJson(`/api/jobs/${jobId}/keyframes?force=true`, { method: "POST" });
        keyframeStatus = data.status;
        showKeyframeState();
        pollKeyframes();
      } catch (error) {
        qs("#keyframe-error").textContent = error.message;
        qs("#keyframe-error").hidden = false;
      } finally {
        action.disabled = false;
      }
    }

    function showKeyframeState() {
      qs("#keyframe-launch").hidden = keyframeStatus !== "not_started" && keyframeStatus !== "failed";
      qs("#keyframe-loading").hidden = !["queued", "running"].includes(keyframeStatus);
      qs("#keyframe-results").hidden = keyframeStatus !== "ready";
    }

    async function loadKeyframes() {
      const { data } = await requestJson(`/api/jobs/${jobId}/keyframes`);
      keyframeStatus = data.status;
      keyframes = data.frames || [];
      if (keyframeStatus === "ready") {
        qs("#frame-count").textContent = `${data.frame_count || keyframes.length} 张 / 已去重`;
        renderKeyframes();
      }
      if (keyframeStatus === "failed") {
        qs("#keyframe-error").textContent = data.error?.message || "关键帧处理失败";
        qs("#keyframe-error").hidden = false;
      }
      showKeyframeState();
      return keyframeStatus;
    }

    async function pollKeyframes() {
      const status = await loadKeyframes();
      if (["queued", "running"].includes(status)) { await sleep(1200); pollKeyframes(); }
    }

    function renderKeyframes() {
      const columns = Math.max(2, Math.min(10, Number(qs("#grid-columns").value) || 5));
      const rows = Math.max(1, Math.min(20, Number(qs("#grid-rows").value) || 10));
      const pageSize = columns * rows;
      const pageCount = Math.max(1, Math.ceil(keyframes.length / pageSize));
      currentPage = Math.max(1, Math.min(pageCount, currentPage));
      const pageFrames = keyframes.slice((currentPage - 1) * pageSize, currentPage * pageSize);
      const grid = qs("#keyframe-grid");
      grid.style.setProperty("--grid-columns", columns);
      grid.innerHTML = pageFrames.map((frame) => `<figure class="keyframe-card" data-time="${frame.timestamp}"><img src="${frame.image_url}" alt="${formatTime(frame.timestamp)} 的关键帧" loading="lazy"><figcaption><span>#${String(frame.id).padStart(3,"0")}</span><span>${formatTime(frame.timestamp)}</span></figcaption></figure>`).join("");
      qsa(".keyframe-card").forEach((card) => card.addEventListener("click", () => seekTo(card.dataset.time)));
      qs("#grid-capacity").textContent = `${pageSize} 张/页`;
      qs("#page-status").textContent = `第 ${currentPage} / ${pageCount} 页`;
      qs("#page-previous").disabled = currentPage <= 1;
      qs("#page-next").disabled = currentPage >= pageCount;
    }

    async function handleAutoAnnotationKeydown(event) {
      if (!autoAnnotationEnabled || qs("#panel-transcript").hidden) return;
      if (event.metaKey || event.ctrlKey || event.altKey || event.target.matches("input, textarea, select, [contenteditable='true']")) return;
      const isSpeakerKey = event.key in speakerShortcuts;
      const isDeleteKey = event.key.toLowerCase() === "d";
      const isPlaybackKey = event.code === "Space";
      if (!isSpeakerKey && !isDeleteKey && !isPlaybackKey) return;
      event.preventDefault();
      if (event.repeat) return;
      if (isPlaybackKey) {
        if (video.paused) video.play().catch((error) => showAnnotationError(`无法播放视频：${error.message}`));
        else video.pause();
        return;
      }
      if (activeTurnId == null) {
        const first = visibleTurns()[0];
        if (first) setActiveTurn(first.id);
        return;
      }
      try {
        if (isDeleteKey) {
          await deleteAndAdvance(activeTurnId);
        } else {
          const speaker = speakerShortcuts[event.key];
          if (!manualSpeakerLabels[speaker]) {
            showAnnotationError(`请先点击 + 添加${speaker === "SPEAKER_02" ? "说话人 3" : "说话人 4"}`);
            return;
          }
          await annotateAndAdvance(activeTurnId, speaker);
        }
      } catch (error) {
        showAnnotationError(error.message);
      }
    }

    qs("#tab-transcript").addEventListener("click", () => switchTab("transcript"));
    qs("#tab-keyframes").addEventListener("click", () => switchTab("keyframes"));
    qs("#annotation-percentage").addEventListener("click", () => {
      switchTab("transcript");
      qs("#panel-transcript").scrollIntoView({ behavior: "smooth", block: "start" });
    });
    qs("#start-keyframes").addEventListener("click", startKeyframes);
    qs("#reprocess-transcript").addEventListener("click", reprocessTranscript);
    qs("#rebuild-speaker-candidates").addEventListener("click", rebuildSpeakerCandidates);
    qs("#retry-failed-transcript").addEventListener("click", reprocessTranscript);
    qs("#auto-annotation-mode").addEventListener("click", () => setAutoAnnotationMode(!autoAnnotationEnabled));
    qs("#apply-speaker-classification").addEventListener("click", applySpeakerClassification);
    qs("#export-ai-transcript").addEventListener("click", () => {
      window.location.assign(`/api/jobs/${jobId}/ai-transcript-export`);
    });
    qs("#export-training").addEventListener("click", () => {
      window.location.assign(`/api/jobs/${jobId}/training-export`);
    });
    qs("#reprocess-keyframes").addEventListener("click", reprocessKeyframes);
    [qs("#grid-columns"), qs("#grid-rows")].forEach((input) => input.addEventListener("change", () => { currentPage = 1; renderKeyframes(); }));
    qsa("[data-matrix]").forEach((button) => button.addEventListener("click", () => {
      const [columns, rows] = button.dataset.matrix.split("x").map(Number);
      qs("#grid-columns").value = columns; qs("#grid-rows").value = rows; currentPage = 1; renderKeyframes();
    }));
    qs("#page-previous").addEventListener("click", () => { currentPage -= 1; renderKeyframes(); });
    qs("#page-next").addEventListener("click", () => { currentPage += 1; renderKeyframes(); });
    document.addEventListener("keydown", handleAutoAnnotationKeydown);
    renderAiTranscriptExportState();
    pollWorkspace();
  }

  if (page === "upload") { initUpload(); initClipWorkbench(); }
  if (page === "workspace") initWorkspace();
})();
