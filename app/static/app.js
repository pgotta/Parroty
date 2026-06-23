/* Parroty front-end. Plain JS, no build step. ------------------------- */

const CATALOG = {};   // filled from /engines
let JOB = null;
let CHAPTERS = [];    // [{title, text}]
let SELECTED_ENGINE = null;

const ROMAN = ["i","ii","iii","iv","v","vi","vii","viii","ix","x","xi","xii",
  "xiii","xiv","xv","xvi","xvii","xviii","xix","xx"];
function roman(n){ return ROMAN[n] || String(n+1); }

const $ = (id) => document.getElementById(id);
function show(id){ $(id).classList.remove("hidden"); }
function hide(id){ $(id).classList.add("hidden"); }

/* ---- Step 1: upload ---------------------------------------------------- */
const dz = $("dropzone");
const epubInput = $("epubInput");
dz.addEventListener("click", () => epubInput.click());
dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("drag"); });
dz.addEventListener("dragleave", () => dz.classList.remove("drag"));
dz.addEventListener("drop", (e) => {
  e.preventDefault(); dz.classList.remove("drag");
  if (e.dataTransfer.files[0]) uploadEpub(e.dataTransfer.files[0]);
});
epubInput.addEventListener("change", () => {
  if (epubInput.files[0]) uploadEpub(epubInput.files[0]);
});

async function uploadEpub(file){
  const fd = new FormData();
  fd.append("epub", file);
  dz.querySelector(".drop-main").textContent = "Parsing…";
  const r = await fetch("/upload", { method: "POST", body: fd });
  const data = await r.json();
  const resetText = `Drop a <strong>book or document</strong> here`;
  if (data.error){ alert(data.error); dz.querySelector(".drop-main").innerHTML = resetText; return; }

  JOB = data.job_id;
  CHAPTERS = data.chapters.map(c => ({ title: c.title, text: "", _preview: c.preview, _count: c.char_count }));
  // We only got previews; fetch full text lazily isn't needed — server keeps it.
  // For editing we store preview; full text lives server-side until synth.
  const meta = $("bookMeta");
  meta.innerHTML = `<div class="bt">${escapeHtml(data.title)}</div>
                    <div class="ba">${escapeHtml(data.author)}</div>
                    <div class="chapter-meta" style="margin-top:8px">${data.chapters.length} chapters detected</div>`;
  show("bookMeta");
  dz.querySelector(".drop-main").innerHTML = resetText;

  renderChapters(data.chapters);
  show("step-chapters");
  buildEngineCards();
  show("step-voice");
  $("step-chapters").scrollIntoView({ behavior: "smooth" });
}

/* ---- Step 2: chapters -------------------------------------------------- */
function renderChapters(chapters){
  const list = $("chapterList");
  list.innerHTML = "";
  chapters.forEach((c, i) => {
    const div = document.createElement("div");
    div.className = "chapter";
    div.dataset.index = i;
    div.innerHTML = `
      <div class="chapter-top">
        <span class="chapter-roman">${roman(i)}</span>
        <input class="chapter-title" value="${escapeHtml(c.title)}">
        <span class="chapter-meta">${c.char_count} chars</span>
        <div class="chapter-actions">
          <button class="icon-btn" data-act="del">delete</button>
        </div>
      </div>`;
    list.appendChild(div);
  });

  list.onclick = async (e) => {
    const btn = e.target.closest(".icon-btn");
    if (!btn) return;
    const card = btn.closest(".chapter");
    const idx = parseInt(card.dataset.index, 10);
    const act = btn.dataset.act;
    if (act === "del"){ await deleteChapter(idx); }
  };
}

$("addChapterBtn").addEventListener("click", async () => {
  await collectAndSave();             // persist current edits
  CHAPTERS.push({ title: "New chapter", text: "" });
  await pushChapters();
});

$("saveChaptersBtn").addEventListener("click", collectAndSave);

function gatherTitles(){
  return [...document.querySelectorAll(".chapter")].map(c => ({
    index: parseInt(c.dataset.index, 10),
    title: c.querySelector(".chapter-title").value,
  }));
}

async function collectAndSave(){
  // Titles are edited in the browser; text stays server-side. We send titles
  // back and let the server keep the matching text by index.
  const titles = gatherTitles();
  const r = await fetch(`/chapters/${JOB}/titles`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ titles }),
  });
  const data = await r.json();
  if (data && data.chapters) renderChapters(data.chapters);
}

async function deleteChapter(idx){
  const r = await fetch(`/chapters/${JOB}/delete`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ index: idx }),
  });
  const data = await r.json();
  if (data.chapters) renderChapters(data.chapters);
}

async function pushChapters(){
  const r = await fetch(`/chapters/${JOB}/append`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  const data = await r.json();
  if (data.chapters) renderChapters(data.chapters);
}

/* ---- Step 3: voice ----------------------------------------------------- */
function buildEngineCards(){
  const grid = $("engineGrid");
  grid.innerHTML = "";
  Object.entries(CATALOG).forEach(([key, info]) => {
    const card = document.createElement("div");
    card.className = "engine-card";
    card.dataset.engine = key;
    const free = !info.needs_key;
    const tags = [
      `<span class="tag ${free ? "free" : "paid"}">${free ? "free" : "paid"}</span>`,
      info.cloning ? `<span class="tag clone">cloning</span>` : "",
      free ? `<span class="tag">local</span>` : `<span class="tag">cloud</span>`,
    ].join("");
    card.innerHTML = `<div class="ec-name">${escapeHtml(info.label)}</div>
                      <div class="ec-tags">${tags}</div>`;
    card.addEventListener("click", () => selectEngine(key, card));
    grid.appendChild(card);
  });
}

function selectEngine(key, card){
  SELECTED_ENGINE = key;
  document.querySelectorAll(".engine-card").forEach(c => c.classList.remove("sel"));
  card.classList.add("sel");
  const info = CATALOG[key];
  show("voiceConfig");

  // --- Fixed voice list (OpenAI / ElevenLabs) ---
  const vsel = $("voiceSelect");
  const voices = info.voices || {};
  vsel.innerHTML = "";                       // clear stale options every time
  if (Object.keys(voices).length){
    vsel.innerHTML = Object.entries(voices)
      .map(([v, g]) => `<option value="${v}">${v} — ${g}</option>`).join("");
    show("voiceField");
  } else {
    hide("voiceField");
  }

  // --- Built-in voices (Chatterbox) ---
  const bsel = $("builtinSelect");
  const builtins = info.builtin_voices || {};
  bsel.innerHTML = "";
  if (Object.keys(builtins).length){
    bsel.innerHTML = Object.entries(builtins)
      .map(([k, b]) => `<option value="${k}">${b.label}</option>`).join("");
    show("builtinField");
  } else {
    hide("builtinField");
  }

  // --- API key ---
  if (info.needs_key){
    show("keyField");
    $("keyLink").href = info.key_url || "#";
  } else {
    hide("keyField");
  }

  // --- Custom sample upload (any cloning engine) ---
  if (info.cloning){ show("cloneField"); } else { hide("cloneField"); }

  // --- Chatterbox collapsible parameter panel + device selector ---
  if (info.params){
    buildCbPanel(info.params);
    show("cbPanel");
  } else {
    hide("cbPanel");
  }

  // Device + model selectors are Chatterbox-only.
  if (key === "chatterbox"){
    show("deviceField");
    // Populate the speed/quality model selector.
    const msel = $("modelSelect");
    const models = info.models || {};
    if (msel && Object.keys(models).length){
      msel.innerHTML = Object.entries(models)
        .map(([k, m]) => `<option value="${k}" data-default="${m.default ? 1 : 0}">${m.label}</option>`).join("");
      // Default to the model flagged default (Standard).
      const def = Object.entries(models).find(([k, m]) => m.default);
      msel.value = def ? def[0] : Object.keys(models)[0];
      show("modelField");
      // Grey out the tuning sliders when Turbo is selected (it ignores them).
      msel.onchange = applyModelPanelState;
      applyModelPanelState();
    } else {
      hide("modelField");
    }
  } else {
    hide("deviceField");
    hide("modelField");
  }

  show("step-narrate");
}

// Turbo ignores CFG / exaggeration / temperature, so disable the panel and
// show a note when Turbo is selected. Standard re-enables it.
function applyModelPanelState(){
  const msel = $("modelSelect");
  const panel = $("cbPanel");
  if (!msel || !panel) return;
  const isTurbo = msel.value === "turbo";
  panel.classList.toggle("disabled", isTurbo);
  panel.querySelectorAll("input, button").forEach(el => {
    // Leave the collapse toggle usable so the note can still be read.
    if (el.id === "cbToggle") return;
    el.disabled = isTurbo;
  });
  const note = $("cbTurboNote");
  if (note) note.classList.toggle("hidden", !isTurbo);
}

// Build the collapsible Chatterbox sliders from catalog param specs.
function buildCbPanel(params){
  const body = $("cbBody");
  body.innerHTML =
    `<p class="cb-turbo-note hidden" id="cbTurboNote">These controls only apply to the <strong>Standard</strong> model. <strong>Turbo</strong> ignores them, so they're disabled. Switch to Standard above to use them.</p>` +
    Object.entries(params).map(([name, p]) => `
    <div class="cb-row">
      <div class="cb-row-head">
        <label>${p.label} <span class="cb-default">(default ${p.default})</span></label>
        <output id="cb_out_${name}">${p.default}</output>
      </div>
      <input type="range" id="cb_${name}" min="${p.min}" max="${p.max}"
             step="${p.step}" value="${p.default}" data-default="${p.default}"
             oninput="document.getElementById('cb_out_${name}').textContent = this.value">
      <p class="cb-hint">${p.hint || ""}</p>
    </div>`).join("") +
    `<button type="button" class="ghost cb-reset" id="cbReset">↺ Reset to defaults</button>`;
  // Start collapsed every time the panel is (re)built.
  body.classList.add("hidden");
  const caret = document.querySelector("#cbToggle .cb-caret");
  if (caret) caret.textContent = "▸";

  // Wire the reset button (rebuilt each time, so attach fresh).
  const reset = $("cbReset");
  if (reset){
    reset.addEventListener("click", () => {
      Object.keys(params).forEach(name => {
        const el = $(`cb_${name}`);
        const out = $(`cb_out_${name}`);
        if (el){ el.value = el.dataset.default; if (out) out.textContent = el.dataset.default; }
      });
      // Reset the speed/quality model back to its default (Standard).
      const msel = $("modelSelect");
      if (msel){
        const def = Array.from(msel.options).find(o => o.dataset.default === "1");
        if (def) msel.value = def.value;
      }
      applyModelPanelState();   // re-enable sliders if we reverted to Standard
    });
  }

  // Reflect the current model's enabled/disabled state on the fresh sliders.
  applyModelPanelState();
}

// Collapse/expand the Chatterbox panel.
$("cbToggle").addEventListener("click", () => {
  const body = $("cbBody");
  body.classList.toggle("hidden");
  const caret = document.querySelector("#cbToggle .cb-caret");
  if (caret) caret.textContent = body.classList.contains("hidden") ? "▸" : "▾";
});

$("sampleInput")?.addEventListener("change", async (e) => {
  if (!e.target.files[0]) return;
  const fd = new FormData();
  fd.append("sample", e.target.files[0]);
  await fetch(`/sample/${JOB}`, { method: "POST", body: fd });
  // Show the status row with the remove option.
  $("sampleStatusText").textContent = `✓ Using your uploaded sample (${e.target.files[0].name}).`;
  show("sampleStatus");
  $("previewNote").textContent = "Sample uploaded — click Preview to hear it.";
});

$("sampleRemove")?.addEventListener("click", async () => {
  await fetch(`/sample/${JOB}/clear`, { method: "POST" });
  $("sampleInput").value = "";          // clear the file picker
  hide("sampleStatus");
  $("previewNote").textContent = "Reverted to the built-in voice. Click Preview to hear it.";
});

// Read the low-memory (process-recycling) settings from the UI. When the
// checkbox is on, narration runs in batches that each fully restart the process
// to flush RAM + page file. Defaults to ON if the control isn't on screen.
// Pass control ids to read a specific pair (the main setup vs the resume panel).
function recycleSettings(cbId, numId){
  const lm = $(cbId || "lowMem");
  const rb = $(numId || "recycleBatch");
  return {
    recycle: lm ? !!lm.checked : true,
    recycle_batch: Math.max(1, Math.min(500, parseInt(rb && rb.value, 10) || 10)),
  };
}

// Build the voice-settings body shared by Preview and Narrate.
function currentVoiceBody(){
  const info = CATALOG[SELECTED_ENGINE] || {};
  const body = {
    engine: SELECTED_ENGINE,
    voice: $("voiceSelect").value || null,
    api_key: $("apiKey").value || null,
  };
  if (info.builtin_voices && Object.keys(info.builtin_voices).length){
    body.builtin_voice = $("builtinSelect").value || null;
  }
  if (info.params){
    const params = {};
    Object.keys(info.params).forEach(name => {
      const el = $(`cb_${name}`);
      if (el) params[name] = parseFloat(el.value);
    });
    body.params = params;
  }
  if (SELECTED_ENGINE === "chatterbox"){
    const dsel = $("deviceSelect");
    body.device = (dsel && dsel.value) || "auto";
    const msel = $("modelSelect");
    body.variant = (msel && msel.value) || "standard";
  }
  // Low-memory mode (sent to /estimate so the ETA includes restart overhead,
  // and to /synthesize to actually run in recycled batches). reload_every is
  // left at 0 — recycling, or the in-process low-RAM safety net, handles memory.
  Object.assign(body, recycleSettings());
  body.reload_every = 0;
  return body;
}

// Format seconds as a friendly ETA string.
function fmtEta(sec){
  if (sec == null || !isFinite(sec)) return "";
  sec = Math.max(0, Math.round(sec));
  if (sec < 60) return `~${sec}s left`;
  const m = Math.floor(sec / 60), s = sec % 60;
  if (m < 60) return `~${m}m ${s}s left`;
  const h = Math.floor(m / 60), mm = m % 60;
  return `~${h}h ${mm}m left`;
}

// Consume a Server-Sent Events POST stream, calling onEvent for each event.
async function streamSSE(url, body, onEvent){
  const resp = await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true){
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split("\n\n");
    buf = parts.pop();                 // keep incomplete trailing chunk
    for (const part of parts){
      const line = part.split("\n").find(l => l.startsWith("data: "));
      if (line){
        try { onEvent(JSON.parse(line.slice(6))); } catch (_) {}
      }
    }
  }
}

// Preview: render one short sentence with a live progress bar, then play it.
$("previewBtn").addEventListener("click", async () => {
  const btn = $("previewBtn");
  const note = $("previewNote");
  const bar = $("previewBar"), fill = $("previewFill"), label = $("previewLabel");
  btn.disabled = true;
  btn.textContent = "Generating…";
  note.textContent = "Loading the voice model… (first run can take a moment)";
  bar.classList.remove("hidden");
  fill.style.width = "0%"; label.textContent = "0%";
  $("previewAudio").classList.add("hidden");

  try {
    await streamSSE(`/preview/${JOB}`, currentVoiceBody(), (ev) => {
      if (ev.type === "loading"){
        note.textContent = ev.message;
      } else if (ev.type === "progress"){
        const pct = Math.round((ev.overall || 0) * 100);
        fill.style.width = pct + "%";
        label.textContent = pct + "%" + (ev.eta_sec != null ? "  ·  " + fmtEta(ev.eta_sec) : "");
        note.textContent = "Rendering sample…";
      } else if (ev.type === "error"){
        bar.classList.add("hidden");
        note.innerHTML = `<span class="preview-err">${escapeHtml(ev.message)}</span>`;
      } else if (ev.type === "done"){
        fill.style.width = "100%"; label.textContent = "Done";
        const audio = $("previewAudio");
        audio.src = ev.url;
        audio.classList.remove("hidden");
        audio.play().catch(() => {});
        note.textContent = "Here's how it sounds. Adjust settings and preview again if needed.";
      }
    });
  } catch (err) {
    bar.classList.add("hidden");
    note.textContent = "Preview request failed. Is the engine installed?";
  }
  btn.disabled = false;
  btn.textContent = "▶ Preview voice";
});

/* ---- Step 4: narrate --------------------------------------------------- */

// Format a duration in seconds as "about X hours Y min" etc.
function fmtDuration(sec){
  if (sec == null || !isFinite(sec)) return "unknown";
  sec = Math.round(sec);
  if (sec < 90) return `about ${sec} seconds`;
  const m = Math.round(sec / 60);
  if (m < 90) return `about ${m} minutes`;
  const h = Math.floor(m / 60), mm = m % 60;
  return mm ? `about ${h}h ${mm}m` : `about ${h} hours`;
}

$("estimateBtn").addEventListener("click", async () => {
  await collectAndSave();
  const btn = $("estimateBtn"), note = $("estimateNote");
  btn.disabled = true; btn.textContent = "Calibrating…";
  note.textContent = "Rendering a short calibration clip on your hardware…";
  try {
    const r = await fetch(`/estimate/${JOB}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(currentVoiceBody()),
    });
    const d = await r.json();
    if (d.error){
      note.innerHTML = `<span class="preview-err">${escapeHtml(d.error)}</span>`;
    } else {
      const dev = d.device ? ` on ${d.device.toUpperCase()}` : "";
      // d.est_seconds already includes the per-batch restart overhead when
      // low-memory mode is on (added server-side). We add the bind allowance
      // here and spell out what's included so the number isn't a mystery.
      let total = d.est_seconds || 0;
      const parts = [];
      if (d.recycle && d.recycle_overhead_seconds){
        parts.push(`~${fmtDuration(d.recycle_overhead_seconds)} for memory-flush restarts`);
      }
      if ($("bindCombine").checked || $("makeVideo").checked){
        const combineSec = Math.max(10, total * 0.02);   // ~quick
        const videoSec = $("makeVideo").checked ? Math.max(60, total * 0.15) : 0;
        total += combineSec + videoSec;
        parts.push("combining" + ($("makeVideo").checked ? " + video" : ""));
      }
      const extra = parts.length ? ` (including ${parts.join(" and ")})` : "";
      // Projected length of the finished audiobook (real spoken duration).
      let lengthLine = "";
      if (d.est_audio_seconds){
        lengthLine = ` The finished audiobook will be about ${fmtDuration(d.est_audio_seconds)} long.`;
      }
      note.textContent =
        `Estimated time to create: ${fmtDuration(total)}${dev}${extra} ` +
        `(${d.total_chars.toLocaleString()} characters).${lengthLine} ` +
        `These are estimates — actual figures vary by chapter.`;
    }
  } catch (err) {
    note.textContent = "Couldn't estimate — try narrating directly.";
  }
  btn.disabled = false; btn.textContent = "⏱ Estimate time";
});

// Toggle cover field with the MP4 checkbox.
// Keep the main button's label honest about what it will do.
function updateNarrateLabel(){
  const willBind = $("bindCombine").checked || $("makeVideo").checked;
  $("narrateBtn").innerHTML = willBind ? "Narrate &amp; bind" : "Narrate";
}

$("makeVideo").addEventListener("change", (e) => {
  e.target.checked ? show("coverField") : hide("coverField");
  updateNarrateLabel();
});
$("bindCombine").addEventListener("change", updateNarrateLabel);

// Upload cover as soon as it's picked, so it's ready before narration starts.
$("coverInput")?.addEventListener("change", async (e) => {
  if (!e.target.files[0]) return;
  const fd = new FormData();
  fd.append("cover", e.target.files[0]);
  await fetch(`/cover/${JOB}`, { method: "POST", body: fd });
  $("coverNote").textContent = `✓ Cover set: ${e.target.files[0].name}`;
});

function renderResults(data){
  const res = $("results");
  show("results");
  let html = `<h3>Your audiobook is ready</h3>`;
  const links = [];
  if (data.audio_file) links.push(dlLink(JOB, data.audio_file, "Download audiobook"));
  if (data.video_file) links.push(dlLink(JOB, data.video_file, "Download video"));
  if (data.timestamps_file) links.push(dlLink(JOB, data.timestamps_file, "Download YouTube chapters"));
  if (data.drive_chapters_file) links.push(dlLink(JOB, data.drive_chapters_file, "Download Google Drive chapter page"));
  if (links.length) html += `<div class="report-links">${links.join(" · ")}</div>`;
  if (data.video_error)
    html += `<div class="line err">Video step: ${escapeHtml(data.video_error)}</div>`;
  if (data.timestamps){
    html += `<pre id="tsBlock">${escapeHtml(data.timestamps)}</pre>`;
    html += `<button class="copy-ts" onclick="copyTs()">Copy timestamps for YouTube</button>`;
    html += `<p class="results-tip">Paste these timestamps into your YouTube video description and YouTube will create the chapter markers automatically.</p>`;
  }
  res.innerHTML = html;
}

$("narrateBtn").addEventListener("click", async () => {
  await collectAndSave();
  const prog = $("narrateProgress");
  const bar = $("narrateBar"), fill = $("narrateFill"), label = $("narrateLabel");
  show("narrateProgress");
  show("narrateBar");
  hide("results");
  prog.innerHTML = `<div class="line">Starting narration with ${SELECTED_ENGINE}…</div>`;
  fill.style.width = "0%"; fill.style.background = ""; label.textContent = "0%";
  $("narrateBtn").disabled = true;

  const body = currentVoiceBody();
  body.language = "en";
  // Bind configuration runs automatically after narration, in one pass.
  body.bind = {
    enabled: $("bindCombine").checked || $("makeVideo").checked,
    make_video: $("makeVideo").checked,
    format: "mp3",
  };

  try {
    await streamSSE(`/synthesize/${JOB}`, body, (ev) => {
      if (ev.type === "loading"){
        prog.innerHTML += `<div class="line">${escapeHtml(ev.message)}</div>`;
      } else if (ev.type === "progress"){
        // Narration occupies 0–90% of the bar; bind takes the last 10%.
        const pct = Math.round((ev.overall || 0) * 90);
        fill.style.width = pct + "%";
        const eta = ev.eta_sec != null ? "  ·  " + fmtEta(ev.eta_sec) : "";
        const mem = ev.mem_avail_gb != null
          ? `  ·  RAM ${ev.mem_avail_gb}GB free` + (ev.mem_pct != null ? ` (${ev.mem_pct}%)` : "")
          : "";
        label.textContent =
          `${pct}%  ·  ch ${ev.chapter}/${ev.total_chapters}${eta}${mem}`;
        if (ev.mem_note){
          prog.innerHTML += `<div class="line">↻ ${escapeHtml(ev.mem_note)}</div>`;
          prog.scrollTop = prog.scrollHeight;
        }
      } else if (ev.type === "chapter_done"){
        prog.innerHTML +=
          `<div class="line done">✓ ${escapeHtml(ev.chapter_title)} (chapter ${ev.chapter}/${ev.total_chapters})</div>`;
        prog.scrollTop = prog.scrollHeight;
      } else if (ev.type === "bind_progress"){
        if (ev.stage === "video"){
          // Map video encode 0..1 onto the 92–99% slice of the bar.
          const vpct = Math.round((ev.frac || 0) * 100);
          fill.style.width = (92 + Math.round((ev.frac || 0) * 7)) + "%";
          const eta = ev.eta_sec != null ? "  ·  " + fmtEta(ev.eta_sec) : "";
          label.textContent = `Building video… ${vpct}%${eta}`;
          // Log only the first video message, not every tick.
          if (!window._videoLogged){
            prog.innerHTML += `<div class="line">${escapeHtml(ev.message)}</div>`;
            prog.scrollTop = prog.scrollHeight;
            window._videoLogged = true;
          }
        } else {
          fill.style.width = "92%";
          label.textContent = "Combining…";
          prog.innerHTML += `<div class="line">${escapeHtml(ev.message)}</div>`;
          prog.scrollTop = prog.scrollHeight;
        }
      } else if (ev.type === "bind_done"){
        window._videoLogged = false;
        prog.innerHTML += `<div class="line done">✓ Audiobook assembled.</div>`;
        renderResults(ev);
      } else if (ev.type === "bind_error"){
        prog.innerHTML += `<div class="line err">✕ ${escapeHtml(ev.message)}</div>`;
      } else if (ev.type === "error"){
        fill.style.width = "100%";
        fill.style.background = "var(--spine)";
        label.textContent = "Error";
        prog.innerHTML += `<div class="line err">✕ ${escapeHtml(ev.message)}</div>`;
      } else if (ev.type === "done"){
        fill.style.width = "100%"; label.textContent = "100%  ·  Complete";
        prog.scrollTop = prog.scrollHeight;
        if (ev.report){
          renderReport(ev.report, ev.report_file);
        }
      }
    });
  } catch (err) {
    prog.innerHTML += `<div class="line err">✕ Narration request failed.</div>`;
  }
  $("narrateBtn").disabled = false;
});

// Render the end-of-run status report (timings) into the results area.
function fmtSecs(sec){
  if (sec == null) return "—";
  sec = Math.round(sec);
  const h = Math.floor(sec/3600), m = Math.floor((sec%3600)/60), s = sec%60;
  if (h) return `${h}h ${m}m ${s}s`;
  if (m) return `${m}m ${s}s`;
  return `${s}s`;
}
function renderReport(r, reportFile){
  const res = $("results");
  show("results");
  const rows = [
    ["Narration", fmtSecs(r.narrate_seconds)],
    r.combine_seconds != null ? ["Combining", fmtSecs(r.combine_seconds)] : null,
    r.video_seconds != null ? ["Video (MP4)", fmtSecs(r.video_seconds)] : null,
    ["Total", fmtSecs(r.total_seconds)],
  ].filter(Boolean);
  const cps = (r.characters && r.narrate_seconds)
    ? Math.round(r.characters / r.narrate_seconds) : null;
  let html = `<div class="report-card"><h3>Status report</h3>`;
  html += `<div class="report-sub">${escapeHtml(r.title || "")}${r.device ? " · " + r.device.toUpperCase() : ""}${r.variant ? " · " + r.variant : ""}</div>`;
  html += `<table class="report-table">`;
  rows.forEach(([k,v]) => { html += `<tr><td>${k}</td><td>${v}</td></tr>`; });
  if (r.audio_length_seconds) html += `<tr><td>Audiobook length</td><td>${fmtSecs(r.audio_length_seconds)}</td></tr>`;
  if (r.chapters) html += `<tr><td>Chapters</td><td>${r.chapters}</td></tr>`;
  if (cps) html += `<tr><td>Speed</td><td>${cps.toLocaleString()} chars/sec</td></tr>`;
  html += `</table>`;
  if (reportFile) html += dlLink(JOB, reportFile, "Download status report");
  html += `</div>`;
  // Prepend the report above any existing results (audiobook links etc.)
  res.innerHTML = html + res.innerHTML;
}

function copyTs(){
  navigator.clipboard.writeText($("tsBlock").textContent);
}
window.copyTs = copyTs;

/* ---- Recovery: bind already-narrated chapter files --------------------- */
$("recoveryToggle")?.addEventListener("click", async () => {
  const body = $("recoveryBody");
  body.classList.toggle("hidden");
  const caret = document.querySelector("#recoveryToggle .cb-caret");
  if (caret) caret.textContent = body.classList.contains("hidden") ? "▸" : "▾";
  // Populate the job picker the first time it's opened.
  if (!body.classList.contains("hidden") && !body.dataset.loaded){
    body.dataset.loaded = "1";
    try {
      const r = await fetch("/jobs");
      const d = await r.json();
      const sel = $("recoverJob");
      // Show where the folders live, so the names make sense.
      const loc = $("recoverLocation");
      if (loc && d.output_dir){
        loc.textContent = `Narrated runs are stored in: ${d.output_dir}`;
      }
      if (sel && d.jobs && d.jobs.length){
        sel.innerHTML = d.jobs.map(j => {
          // Build a human-readable label: book title (or filename) + date.
          const name = j.title || j.epub_filename || j.job_id;
          const when = j.created ? j.created.replace("T", " ") : "";
          const bound = j.already_bound ? " · already bound" : "";
          const label = `${name} — ${j.chapters} chapters${when ? " · " + when : ""}${bound}`;
          return `<option value="${j.job_id}">${escapeHtml(label)}</option>`;
        }).join("");
        // Default to the current job if it's in the list, else the newest.
        const cur = Array.from(sel.options).find(o => o.value === JOB);
        sel.value = cur ? JOB : sel.options[0].value;
      } else if (sel){
        sel.innerHTML = `<option value="">(no recoverable runs found)</option>`;
      }
    } catch (e) {}
  }
});

$("recoverBtn")?.addEventListener("click", async () => {
  const btn = $("recoverBtn");
  const prog = $("recoverProgress");
  const sel = $("recoverJob");
  const targetJob = (sel && sel.value) || JOB;
  if (!targetJob){
    return;
  }
  btn.disabled = true; btn.textContent = "Binding…";
  show("recoverProgress");
  prog.innerHTML = `<div class="line">Combining existing chapter files…</div>`;

  const body = { make_video: $("makeVideo").checked, format: "mp3" };
  try {
    const r = await fetch(`/recover/${targetJob}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const d = await r.json();
    if (d.error){
      prog.innerHTML += `<div class="line err">✕ ${escapeHtml(d.error)}</div>`;
    } else {
      prog.innerHTML += `<div class="line done">✓ Bound ${d.chapters_found} chapters.</div>`;
      const res = $("recoverResults");
      show("recoverResults");
      let html = `<h3>Your audiobook is ready</h3>`;
      const rlinks = [];
      if (d.audio_file) rlinks.push(dlLink(targetJob, d.audio_file, "Download audiobook"));
      if (d.video_file) rlinks.push(dlLink(targetJob, d.video_file, "Download video"));
      if (d.timestamps_file) rlinks.push(dlLink(targetJob, d.timestamps_file, "Download YouTube chapters"));
      if (d.drive_chapters_file) rlinks.push(dlLink(targetJob, d.drive_chapters_file, "Download Google Drive chapter page"));
      if (rlinks.length) html += `<div class="report-links">${rlinks.join(" · ")}</div>`;
      if (d.video_error)
        html += `<div class="line err">Video step: ${escapeHtml(d.video_error)}</div>`;
      if (d.timestamps){
        html += `<pre id="tsBlock">${escapeHtml(d.timestamps)}</pre>`;
        html += `<button class="copy-ts" onclick="copyTs()">Copy timestamps for YouTube</button>`;
        html += `<p class="results-tip">Paste these into your YouTube description for automatic chapters.</p>`;
      }
      res.innerHTML = html;
    }
  } catch (err) {
    prog.innerHTML += `<div class="line err">✕ Recovery request failed.</div>`;
  }
  btn.disabled = false; btn.textContent = "Bind existing files";
});

/* ---- utils ------------------------------------------------------------- */
function escapeHtml(s){
  return String(s).replace(/[&<>"']/g, m => (
    {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]));
}

// Build a compact download link: shows a short label, but the full filename
// appears on hover (title tooltip) and is used as the saved file's name
// (download attribute). job/file are URL path parts; label is what's shown.
function dlLink(job, file, label){
  if (!file) return "";
  const safeFile = escapeHtml(file);
  return `<a href="/download/${job}/${encodeURIComponent(file)}" `
       + `download="${safeFile}" title="${safeFile}">⬇ ${escapeHtml(label)}</a>`;
}

/* boot */
fetch("/engines").then(r => r.json()).then(c => { Object.assign(CATALOG, c); });

// Populate the Chatterbox compute-device selector with what this machine has.
fetch("/devices").then(r => r.json()).then(d => {
  const sel = $("deviceSelect");
  if (!sel || !d.devices) return;
  sel.innerHTML = d.devices
    .map(dev => `<option value="${dev.id}">${dev.label}</option>`).join("");
  sel.value = "auto";

  // Show a GPU status line so the user knows whether the GPU is actually used.
  const gpu = d.gpu || {};
  const caveat = $("deviceCaveat");
  if (caveat){
    if (gpu.cuda_available){
      caveat.innerHTML = `✅ ${escapeHtml(gpu.message || "GPU is available and will be used.")}`;
      caveat.classList.add("device-ok");
    } else if (gpu.message){
      const fix = gpu.fix
        ? `<br><br><strong>How to enable your GPU:</strong><br><code class="gpu-fix">${escapeHtml(gpu.fix)}</code>`
        : "";
      caveat.innerHTML =
        `⚠️ ${escapeHtml(gpu.message)} On CPU this is <strong>very slow</strong>.` +
        fix +
        `<br><br>Integrated Intel/AMD graphics can't be used — only a discrete NVIDIA (CUDA) or Apple (Metal) GPU accelerates Chatterbox.`;
    }
  }
}).catch(() => {});

/* ---- Restore a previous session (landing page) ------------------------- */
let RESTORE_JOBS = [];
fetch("/jobs").then(r => r.json()).then(d => {
  const panel = $("restorePanel");
  const sel = $("restoreJob");
  if (!panel || !sel || !d.jobs || !d.jobs.length) return;
  RESTORE_JOBS = d.jobs;
  const loc = $("restoreLocation");
  if (loc && d.output_dir) loc.textContent = `Stored in: ${d.output_dir}`;
  sel.innerHTML = d.jobs.map(j => {
    const name = j.title || j.epub_filename || j.job_id;
    const when = j.created ? j.created.replace("T", " ") : "";
    // Clear status: complete, unfinished (x/y), or bound.
    let status;
    if (j.total_chapters){
      status = j.complete ? `${j.total_chapters} chapters · complete`
                          : `${j.chapters}/${j.total_chapters} chapters · unfinished`;
    } else {
      status = `${j.chapters} chapters`;
    }
    if (j.already_bound) status += " · audiobook built";
    return `<option value="${j.job_id}">${escapeHtml(`${name} — ${status}${when ? " · " + when : ""}`)}</option>`;
  }).join("");
  sel.addEventListener("change", updateRestoreButtons);
  updateRestoreButtons();
  show("restorePanel");
}).catch(() => {});

// Show only the actions that make sense for the selected run.
function updateRestoreButtons(){
  const sel = $("restoreJob");
  const j = RESTORE_JOBS.find(x => x.job_id === (sel && sel.value));
  const resumeBtn = $("restoreResumeBtn");
  const bindBtn = $("restoreBindBtn");
  const note = $("restoreStatusNote");
  if (!j){ return; }

  if (j.complete){
    // Nothing left to narrate — guide to binding.
    if (resumeBtn) resumeBtn.classList.add("hidden");
    if (bindBtn){ bindBtn.classList.remove("hidden"); bindBtn.classList.add("primary"); bindBtn.classList.remove("ghost"); }
    if (note) note.textContent = j.already_bound
      ? "This run is complete and already has an audiobook. You can re-bind it (e.g. to add an MP4) below."
      : "✓ This run finished narrating all chapters. Click below to combine them into the audiobook.";
  } else if (j.can_resume){
    if (resumeBtn) resumeBtn.classList.remove("hidden");
    if (bindBtn){ bindBtn.classList.remove("hidden"); bindBtn.classList.add("ghost"); bindBtn.classList.remove("primary"); }
    if (note) note.textContent = `This run stopped partway (${j.chapters} of ${j.total_chapters} chapters). Resume to finish it, or bind just what's done.`;
  } else {
    // Unfinished but no saved text (older run): can only bind what exists.
    if (resumeBtn) resumeBtn.classList.add("hidden");
    if (bindBtn){ bindBtn.classList.remove("hidden"); bindBtn.classList.add("primary"); bindBtn.classList.remove("ghost"); }
    if (note) note.textContent = `${j.chapters} chapters are on disk. (This run predates resume support, so it can't continue narrating — but you can bind what's there.)`;
  }
}

$("restoreToggle")?.addEventListener("click", () => {
  const body = $("restoreBody");
  body.classList.toggle("hidden");
  const caret = document.querySelector("#restoreToggle .cb-caret");
  if (caret) caret.textContent = body.classList.contains("hidden") ? "▸" : "▾";
});

// Resume narrating a previous run: restore it into memory, then jump to the
// voice step. The narrate flow skips chapters already on disk.
let RESUME_SETTINGS = null;   // saved voice settings for an in-progress resume

$("restoreResumeBtn")?.addEventListener("click", async () => {
  const sel = $("restoreJob");
  const jobId = sel && sel.value;
  if (!jobId) return;
  const prog = $("restoreProgress");
  show("restoreProgress");
  prog.innerHTML = `<div class="line">Restoring session…</div>`;
  try {
    const r = await fetch(`/restore/${jobId}`, { method: "POST" });
    const d = await r.json();
    if (d.error){
      prog.innerHTML += `<div class="line err">✕ ${escapeHtml(d.error)}</div>`;
      return;
    }
    if (d.already_done >= d.total_chapters){
      prog.innerHTML += `<div class="line done">✓ This run is already complete (${d.already_done}/${d.total_chapters} chapters). Use "Just bind what's done" to build the audiobook — there's nothing left to narrate.</div>`;
      return;
    }
    JOB = jobId;
    const vs = d.voice_settings || {};
    if (vs.engine){
      // We know the exact voice this run used — resume directly, no re-asking.
      RESUME_SETTINGS = vs;
      const vlabel = vs.variant ? `${vs.engine} (${vs.variant})` : vs.engine;
      prog.innerHTML += `<div class="line done">✓ Restored "${escapeHtml(d.title || jobId)}" — ${d.already_done}/${d.total_chapters} chapters done. It will resume with the same voice (${escapeHtml(vlabel)}).</div>`;
      prog.innerHTML += `<div class="line" style="display:flex;gap:10px;flex-wrap:wrap;">` +
        `<button class="primary" id="doResumeBindBtn">Resume &amp; bind (finish, then combine)</button>` +
        `<button class="ghost" id="doResumeBtn">Resume narrating only</button>` +
        `</div>`;
      prog.innerHTML += `<div class="line muted">"Resume &amp; bind" finishes the remaining chapters, then combines them into the audiobook${'' }${$("restoreMakeVideo") && $("restoreMakeVideo").checked ? " + MP4" : " (tick \"Also build an MP4\" above for video)"} — all in one run. Memory is released between narration and binding.</div>`;
      $("doResumeBtn").addEventListener("click", () => resumeNarration(d, false));
      $("doResumeBindBtn").addEventListener("click", () => resumeNarration(d, true));
    } else {
      // Older run without saved settings: fall back to choosing the voice,
      // but warn that it must match the original.
      RESUME_SETTINGS = null;
      prog.innerHTML += `<div class="line done">✓ Restored "${escapeHtml(d.title || jobId)}" — ${d.already_done}/${d.total_chapters} chapters done.</div>`;
      prog.innerHTML += `<div class="line">This run didn't save its voice settings (older run). Pick the <strong>same voice</strong> you used originally, then click Narrate to resume.</div>`;
      buildEngineCards();
      show("step-voice");
      show("step-narrate");
      $("step-voice").scrollIntoView({ behavior: "smooth" });
    }
  } catch (e) {
    prog.innerHTML += `<div class="line err">✕ Restore failed.</div>`;
  }
});

// Resume narration directly using the saved settings — no voice/cover step.
// If withBind is true, it auto-combines (and optionally builds MP4) when the
// remaining chapters finish, all in one run.
async function resumeNarration(restoreData, withBind){
  const vs = RESUME_SETTINGS || {};
  const container = $("restoreProgress");
  const makeVideo = withBind && $("restoreMakeVideo") && $("restoreMakeVideo").checked;
  resumeBindFiles = null;
  const body = {
    engine: vs.engine,
    voice: vs.voice,
    builtin_voice: vs.builtin_voice,
    params: vs.params || {},
    device: vs.device,
    variant: vs.variant,
    language: vs.language || "en",
    reload_every: 0,
    ...recycleSettings("restoreLowMem", "restoreRecycleBatch"),
    // When binding, the server auto-combines after narration in the same
    // stream, freeing the model first so memory is released between phases.
    bind: withBind
      ? { enabled: true, make_video: !!makeVideo, format: "mp3" }
      : { enabled: false },
  };
  show("restoreProgress");

  // CRITICAL: the progress bar and the scrolling log must be SEPARATE sibling
  // DOM nodes. Appending log lines with innerHTML += would tear down and
  // recreate every child of the container — including the bar — which orphans
  // our fill/label references so the visible bar never updates. We keep the bar
  // in its own node and append log lines via appendChild to a different node,
  // so the bar element is never destroyed and its references stay valid.
  container.innerHTML = "";
  const barWrap = document.createElement("div");
  barWrap.className = "pbar pbar-lg";
  const fill = document.createElement("div");
  fill.className = "pbar-fill";
  const label = document.createElement("span");
  label.className = "pbar-label";
  barWrap.appendChild(fill);
  barWrap.appendChild(label);
  container.appendChild(barWrap);

  const log = document.createElement("div");
  container.appendChild(log);
  const addLine = (cls, html) => {
    const d = document.createElement("div");
    d.className = "line" + (cls ? " " + cls : "");
    d.innerHTML = html;
    log.appendChild(d);
    container.scrollTop = container.scrollHeight;
  };
  const setBar = (frac, text) => {
    const pct = Math.round((frac || 0) * 100);
    fill.style.width = pct + "%";
    label.textContent = text;
  };

  let firstNarrate = true;
  let narrateStartTime = null;
  let narratedSinceResume = 0;

  try {
    await streamSSE(`/synthesize/${JOB}`, body, (ev) => {
      if (ev.type === "progress"){
        // Within-chapter progress (Standard model emits this).
        const eta = ev.eta_sec != null ? " · " + fmtEta(ev.eta_sec) : "";
        const mem = ev.mem_avail_gb != null
          ? ` · RAM ${ev.mem_avail_gb}GB free` + (ev.mem_pct != null ? ` (${ev.mem_pct}%)` : "")
          : "";
        setBar(ev.overall,
          `${Math.round((ev.overall || 0) * 100)}% · ch ${ev.chapter}/${ev.total_chapters}${eta}${mem}`);
        if (ev.mem_note) addLine("", `↻ ${escapeHtml(ev.mem_note)}`);
      } else if (ev.type === "chapter_done"){
        const isSkip = ev.chapter_title.includes("already done");
        if (isSkip){
          setBar(ev.overall,
            `${Math.round((ev.overall || 0) * 100)}% · skipping done chapters (${ev.chapter}/${ev.total_chapters})`);
        } else {
          if (firstNarrate){
            firstNarrate = false;
            narrateStartTime = Date.now();
            addLine("", `▶ Resuming narration from chapter ${ev.chapter}…`);
          }
          narratedSinceResume++;
          // Chapter-based ETA (works even when within-chapter progress isn't
          // emitted, e.g. with the Turbo model).
          let etaTxt = "";
          if (narrateStartTime && narratedSinceResume > 0){
            const elapsed = (Date.now() - narrateStartTime) / 1000;
            const perCh = elapsed / narratedSinceResume;
            const remaining = ev.total_chapters - ev.chapter;
            if (remaining > 0) etaTxt = " · ~" + fmtEta(perCh * remaining) + " left";
          }
          setBar(ev.overall,
            `${Math.round((ev.overall || 0) * 100)}% · narrating ch ${ev.chapter}/${ev.total_chapters}${etaTxt}`);
        }
        addLine("done", `✓ ${escapeHtml(ev.chapter_title)} (${ev.chapter}/${ev.total_chapters})`);
      } else if (ev.type === "loading"){
        addLine("", escapeHtml(ev.message));
      } else if (ev.type === "bind_progress"){
        // Update the bar in place — do NOT add a log line per event, or the
        // many ffmpeg progress ticks flood the log.
        if (ev.stage === "video"){
          const frac = ev.frac || 0;
          // Map video encoding into the last slice of the bar (95%–100%).
          const barFrac = 0.95 + frac * 0.05;
          const pct = Math.round(frac * 100);
          const eta = ev.eta_sec != null ? " · " + fmtEta(ev.eta_sec) + " left" : "";
          setBar(barFrac, `Building MP4 video… ${pct}%${eta}`);
        } else {
          setBar(0.95, "Combining chapters into one audiobook…");
        }
      } else if (ev.type === "bind_done"){
        setBar(1, "Audiobook assembled");
        // Stash the produced file names so the final report card can link them.
        resumeBindFiles = {
          audio_file: ev.audio_file,
          video_file: ev.video_file,
          video_error: ev.video_error,
          timestamps_file: ev.timestamps_file,
          drive_chapters_file: ev.drive_chapters_file,
        };
      } else if (ev.type === "bind_error"){
        addLine("err", `✕ ${escapeHtml(ev.message)}`);
      } else if (ev.type === "error"){
        addLine("err", `✕ ${escapeHtml(ev.message)}`);
      } else if (ev.type === "done"){
        setBar(1, withBind ? "100% · Complete (narrated + bound)" : "100% · Narration complete");
        if (!withBind){
          addLine("done", `✓ All chapters narrated. Now use "Just bind what's done" above to build the audiobook${$("restoreMakeVideo") && $("restoreMakeVideo").checked ? " + MP4" : ""}.`);
        } else {
          addLine("done", `✓ Done — narrated and bound in one run.`);
          // Render the same polished report card the normal flow shows, with
          // download links for the audiobook, video, and YouTube chapters.
          renderResumeReport(ev.report, ev.report_file, resumeBindFiles,
                             ev.failed_chapters);
        }
      }
    });
  } catch (e) {
    addLine("err", "✕ Resume failed.");
  }
}

let resumeBindFiles = null;

// Render the status-report card (timings, audiobook length, speed) plus the
// download links, into the restore results area — matching the main flow.
function renderResumeReport(r, reportFile, files, failed){
  const res = $("restoreResults");
  if (!res) return;
  show("restoreResults");
  files = files || {};
  let html = `<div class="report-card"><h3>Your audiobook is ready</h3>`;

  // Download links first (most important).
  const links = [];
  if (files.audio_file) links.push(dlLink(JOB, files.audio_file, "Download audiobook"));
  if (files.video_file) links.push(dlLink(JOB, files.video_file, "Download video"));
  if (files.timestamps_file) links.push(dlLink(JOB, files.timestamps_file, "Download YouTube chapters"));
  if (files.drive_chapters_file) links.push(dlLink(JOB, files.drive_chapters_file, "Download Google Drive chapter page"));
  if (reportFile) links.push(dlLink(JOB, reportFile, "Download status report"));
  if (links.length) html += `<div class="report-links">${links.join(" · ")}</div>`;
  if (files.video_error) html += `<div class="line err">Video step: ${escapeHtml(files.video_error)}</div>`;
  if (failed && failed.length) html += `<div class="line err">Skipped chapters (resume again to retry): ${failed.join(", ")}</div>`;

  // Stats table, if we got a report.
  if (r){
    const fmt = (s) => (typeof fmtSecs === "function" ? fmtSecs(s) : (s + "s"));
    const rows = [
      r.narrate_seconds != null ? ["Narration", fmt(r.narrate_seconds)] : null,
      r.combine_seconds != null ? ["Combining", fmt(r.combine_seconds)] : null,
      r.video_seconds != null ? ["Video (MP4)", fmt(r.video_seconds)] : null,
      r.total_seconds != null ? ["Total", fmt(r.total_seconds)] : null,
    ].filter(Boolean);
    const cps = (r.characters && r.narrate_seconds)
      ? Math.round(r.characters / r.narrate_seconds) : null;
    html += `<div class="report-sub">${escapeHtml(r.title || "")}${r.device ? " · " + r.device.toUpperCase() : ""}${r.variant ? " · " + r.variant : ""}</div>`;
    html += `<table class="report-table">`;
    rows.forEach(([k,v]) => { html += `<tr><td>${k}</td><td>${v}</td></tr>`; });
    if (r.audio_length_seconds) html += `<tr><td>Audiobook length</td><td>${fmt(r.audio_length_seconds)}</td></tr>`;
    if (r.chapters) html += `<tr><td>Chapters</td><td>${r.chapters}</td></tr>`;
    if (cps) html += `<tr><td>Speed</td><td>${cps.toLocaleString()} chars/sec</td></tr>`;
    html += `</table>`;
  }
  html += `</div>`;
  res.innerHTML = html;
}

// Bind what's already narrated in a previous run (no re-narrating).
// Toggle the cover field with the restore MP4 checkbox.
$("restoreMakeVideo")?.addEventListener("change", (e) => {
  e.target.checked ? show("restoreCoverField") : hide("restoreCoverField");
});

// Upload a cover for the selected restored run (saved to its folder on disk).
$("restoreCoverInput")?.addEventListener("change", async (e) => {
  if (!e.target.files[0]) return;
  const sel = $("restoreJob");
  const jobId = sel && sel.value;
  if (!jobId) return;
  const fd = new FormData();
  fd.append("cover", e.target.files[0]);
  await fetch(`/cover/${jobId}`, { method: "POST", body: fd });
  $("restoreCoverNote").textContent = `✓ Cover set: ${e.target.files[0].name}`;
});

$("restoreBindBtn")?.addEventListener("click", async () => {
  const sel = $("restoreJob");
  const jobId = sel && sel.value;
  if (!jobId) return;
  const makeVideo = $("restoreMakeVideo") && $("restoreMakeVideo").checked;
  const btn = $("restoreBindBtn"), prog = $("restoreProgress");
  btn.disabled = true; btn.textContent = "Binding…";
  show("restoreProgress");
  prog.innerHTML = `<div class="line">Combining existing chapter files…</div>`;
  let videoLogged = false;
  try {
    await streamSSE(`/recover/${jobId}`, { make_video: makeVideo, format: "mp3" }, (ev) => {
      if (ev.type === "bind_progress"){
        if (ev.stage === "video"){
          const vpct = Math.round((ev.frac || 0) * 100);
          const eta = ev.eta_sec != null ? "  ·  " + fmtEta(ev.eta_sec) : "";
          if (!videoLogged){
            prog.innerHTML += `<div class="line" id="rvLine">Building MP4 video… ${vpct}%${eta}</div>`;
            videoLogged = true;
          } else {
            const el = document.getElementById("rvLine");
            if (el) el.textContent = `Building MP4 video… ${vpct}%${eta}`;
          }
          prog.scrollTop = prog.scrollHeight;
        }
      } else if (ev.type === "bind_done"){
        prog.innerHTML += `<div class="line done">✓ Bound ${ev.chapters_found} chapters.</div>`;
        const res = $("restoreResults"); show("restoreResults");
        let html = `<h3>Your audiobook is ready</h3>`;
        const blinks = [];
        if (ev.audio_file) blinks.push(dlLink(jobId, ev.audio_file, "Download audiobook"));
        if (ev.video_file) blinks.push(dlLink(jobId, ev.video_file, "Download video"));
        if (ev.timestamps_file) blinks.push(dlLink(jobId, ev.timestamps_file, "Download YouTube chapters"));
        if (ev.drive_chapters_file) blinks.push(dlLink(jobId, ev.drive_chapters_file, "Download Google Drive chapter page"));
        if (blinks.length) html += `<div class="report-links">${blinks.join(" · ")}</div>`;
        if (ev.video_error) html += `<div class="line err">Video step: ${escapeHtml(ev.video_error)}</div>`;
        if (ev.timestamps){
          html += `<pre id="tsBlock">${escapeHtml(ev.timestamps)}</pre>`;
          html += `<button class="copy-ts" onclick="copyTs()">Copy timestamps for YouTube</button>`;
        }
        res.innerHTML = html;
      } else if (ev.type === "bind_error"){
        prog.innerHTML += `<div class="line err">✕ ${escapeHtml(ev.message)}</div>`;
      }
    });
  } catch (e) {
    prog.innerHTML += `<div class="line err">✕ Bind failed.</div>`;
  }
  btn.disabled = false; btn.textContent = "Just bind what's done";
});

// ---- Choose which chapters to include (e.g. to fit YouTube's 12h limit) ----
const YT_LIMIT_MS = 12 * 3600 * 1000;

function fmtHMS(ms){
  const s = Math.round(ms / 1000);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m ${sec}s`;
  return `${sec}s`;
}

$("chooseChaptersBtn")?.addEventListener("click", async () => {
  const sel = $("restoreJob");
  const jobId = sel && sel.value;
  if (!jobId) { alert("Pick a run first."); return; }
  const box = $("chapterSelect");
  show("chapterSelect");
  box.innerHTML = `<div class="line">Loading chapters…</div>`;
  try {
    const r = await fetch(`/chapters/${jobId}`);
    const d = await r.json();
    if (d.error){ box.innerHTML = `<div class="line err">${escapeHtml(d.error)}</div>`; return; }
    renderChapterSelect(jobId, d.chapters, d.total_ms, d.suspicious_count || 0);
  } catch (e) {
    box.innerHTML = `<div class="line err">Couldn't load chapters.</div>`;
  }
});

function renderChapterSelect(jobId, chapters, totalMs, suspiciousCount){
  const box = $("chapterSelect");
  let warnBanner = "";
  if (suspiciousCount > 0){
    warnBanner = `<div class="cs-warn">
        ⚠ ${suspiciousCount} chapter${suspiciousCount > 1 ? "s" : ""} look${suspiciousCount > 1 ? "" : "s"} short for their text
        (possibly truncated by a memory error mid-narration). They're <strong>deselected
        below</strong> and shown in orange. Some chapters really are short, so check each
        first — if one is actually fine, re-select it. <strong>Leave the truly-truncated
        ones deselected and click "Re-narrate flagged chapters"</strong> to redo them: each
        is overwritten with a fresh narration and then re-included automatically.
      </div>`;
  }
  let html = warnBanner + `<div class="cs-head">
      <strong>Choose chapters to include</strong>
      <div class="cs-tools">
        <button type="button" class="ghost" id="csAll">Select all</button>
        <button type="button" class="ghost" id="csNone">Clear</button>
      </div>
    </div>
    <div class="cs-total" id="csTotal"></div>
    <div class="cs-list">`;
  chapters.forEach(c => {
    const sus = c.suspicious ? " cs-suspicious" : "";
    const flag = c.suspicious ? ` <span class="cs-flag" title="Looks truncated — leave it deselected and click 'Re-narrate flagged chapters' to redo it">⚠ truncated?</span>` : "";
    html += `<label class="cs-row${sus}">
        <input type="checkbox" class="cs-ck" data-idx="${c.index}" data-ms="${c.duration_ms}" data-suspicious="${c.suspicious ? 1 : 0}"${c.suspicious ? "" : " checked"}>
        <span class="cs-num">${c.index}</span>
        <span class="cs-title">${escapeHtml(c.title)}${flag}</span>
        <span class="cs-dur">${fmtHMS(c.duration_ms)}</span>
      </label>`;
  });
  html += `</div>`;
  if (suspiciousCount > 0){
    html += `<div class="cs-redo-row">
        <button type="button" class="warn-btn" id="csRedoBtn">Re-narrate flagged chapters</button>
      </div>
      <div id="csRedoProgress" class="progress hidden"></div>`;
  }
  html += `<p class="muted" style="margin:12px 0 0">To recombine into the final audiobook: tick "Also build an MP4" above if you want video, then —</p>
    <button type="button" class="primary" id="csBindBtn" style="margin-top:8px">Recombine selected chapters</button>
    <p class="muted" style="margin:8px 0 0;font-size:.82rem">Deselect any other chapters to leave them out of the final audiobook (e.g. to fit YouTube's 12-hour limit). Only the flagged ones get re-narrated.</p>
    <div id="csProgress" class="progress hidden"></div>
    <div id="csResults" class="results hidden"></div>`;
  box.innerHTML = html;

  const updateTotal = () => {
    const cks = [...box.querySelectorAll(".cs-ck")];
    const chosen = cks.filter(c => c.checked);
    const ms = chosen.reduce((a, c) => a + Number(c.dataset.ms || 0), 0);
    const over = ms > YT_LIMIT_MS;
    $("csTotal").innerHTML =
      `Selected: <strong>${chosen.length}/${cks.length}</strong> chapters · ` +
      `<strong class="${over ? 'cs-over' : 'cs-ok'}">${fmtHMS(ms)}</strong>` +
      (over ? ` <span class="cs-over">— over YouTube's 12h limit, deselect some</span>`
            : ` <span class="cs-ok">— within YouTube's 12h limit</span>`);
  };
  box.querySelectorAll(".cs-ck").forEach(c => c.addEventListener("change", updateTotal));
  $("csAll").addEventListener("click", () => { box.querySelectorAll(".cs-ck").forEach(c => c.checked = true); updateTotal(); });
  $("csNone").addEventListener("click", () => { box.querySelectorAll(".cs-ck").forEach(c => c.checked = false); updateTotal(); });
  updateTotal();

  $("csBindBtn").addEventListener("click", () => bindSelectedChapters(jobId));

  if ($("csRedoBtn")){
    $("csRedoBtn").addEventListener("click", () => reNarrateChapters(jobId));
  }
}

// Re-narrate the flagged-and-deselected chapters (the ones still marked
// truncated). Deletes their old (short) files and narrates them fresh; the
// panel then reloads so they come back full-length and re-selected.
async function reNarrateChapters(jobId){
  const box = $("chapterSelect");
  // Target only chapters that are BOTH flagged as suspicious AND left
  // deselected — so deselecting chapters to fit the 12h limit never triggers a
  // redo, and re-selecting a flagged chapter (because it's actually fine)
  // excludes it from the redo.
  const selected = [...box.querySelectorAll(".cs-ck")]
                    .filter(c => c.dataset.suspicious === "1" && !c.checked)
                    .map(c => Number(c.dataset.idx));
  if (!selected.length){
    alert("No flagged chapters are deselected. Leave the truncated (orange) chapters deselected, then click this to re-narrate them.");
    return;
  }
  if (!confirm(`Re-narrate ${selected.length} flagged chapter(s)? Their current audio will be overwritten.`)) return;

  // Need the run restored (chapters + voice settings) to narrate.
  let vs = RESUME_SETTINGS;
  if (!vs || JOB !== jobId){
    try {
      const rr = await fetch(`/restore/${jobId}`, { method: "POST" });
      const rd = await rr.json();
      if (rd.error){ alert("Couldn't load this run: " + rd.error); return; }
      JOB = jobId;
      vs = rd.voice_settings || {};
      RESUME_SETTINGS = vs;
    } catch (e){ alert("Couldn't load this run."); return; }
  }
  if (!vs || !vs.engine){
    alert("This run didn't save its voice settings, so it can't auto re-narrate. (Older run.)");
    return;
  }

  const btn = $("csRedoBtn"), container = $("csRedoProgress");
  btn.disabled = true; btn.textContent = "Re-narrating…";
  show("csRedoProgress");
  container.innerHTML = "";
  const barWrap = document.createElement("div"); barWrap.className = "pbar pbar-lg";
  const fill = document.createElement("div"); fill.className = "pbar-fill";
  const label = document.createElement("span"); label.className = "pbar-label";
  barWrap.appendChild(fill); barWrap.appendChild(label); container.appendChild(barWrap);
  const log = document.createElement("div"); container.appendChild(log);
  const addLine = (cls, h) => { const d = document.createElement("div"); d.className = "line" + (cls?" "+cls:""); d.innerHTML = h; log.appendChild(d); container.scrollTop = container.scrollHeight; };
  const setBar = (f, t) => { fill.style.width = Math.round((f||0)*100) + "%"; label.textContent = t; };
  setBar(0.02, `Re-narrating ${selected.length} flagged chapter(s)…`);

  const body = {
    engine: vs.engine, voice: vs.voice, builtin_voice: vs.builtin_voice,
    params: vs.params || {}, device: vs.device, variant: vs.variant,
    language: vs.language || "en", reload_every: 10,
    only_chapters: selected, bind: { enabled: false },
  };
  try {
    await streamSSE(`/synthesize/${jobId}`, body, (ev) => {
      if (ev.type === "progress"){
        setBar(ev.overall, `${Math.round((ev.overall||0)*100)}% · ch ${ev.chapter}/${ev.total_chapters}`);
      } else if (ev.type === "chapter_done"){
        addLine("done", `✓ ${escapeHtml(ev.chapter_title)} (${ev.chapter})`);
      } else if (ev.type === "chapter_skipped"){
        addLine("err", `✕ ${escapeHtml(ev.message)}`);
      } else if (ev.type === "loading"){
        addLine("", escapeHtml(ev.message));
      } else if (ev.type === "error"){
        addLine("err", `✕ ${escapeHtml(ev.message)}`);
      } else if (ev.type === "done"){
        setBar(1, "Done re-narrating");
        addLine("done", `✓ Re-narrated and re-included. Reloading chapter list…`);
        // Refresh the panel so durations/flags update (the redone chapters come
        // back full-length, no longer flagged, and selected again).
        setTimeout(() => $("chooseChaptersBtn")?.click(), 800);
      }
    });
  } catch (e){
    addLine("err", "✕ Re-narrate failed.");
  }
  btn.disabled = false; btn.textContent = "Re-narrate flagged chapters";
}

async function bindSelectedChapters(jobId){
  const box = $("chapterSelect");
  const selected = [...box.querySelectorAll(".cs-ck")].filter(c => c.checked)
                    .map(c => Number(c.dataset.idx));
  if (!selected.length){ alert("Select at least one chapter."); return; }
  const makeVideo = $("restoreMakeVideo") && $("restoreMakeVideo").checked;
  const btn = $("csBindBtn"), container = $("csProgress");
  btn.disabled = true; btn.textContent = "Recombining…";
  show("csProgress");

  // Bar + log as SEPARATE sibling nodes (appending log lines must not destroy
  // the bar element, or its fill/label references get orphaned).
  container.innerHTML = "";
  const barWrap = document.createElement("div");
  barWrap.className = "pbar pbar-lg";
  const fill = document.createElement("div"); fill.className = "pbar-fill";
  const label = document.createElement("span"); label.className = "pbar-label";
  barWrap.appendChild(fill); barWrap.appendChild(label);
  container.appendChild(barWrap);
  const log = document.createElement("div"); container.appendChild(log);
  const addLine = (cls, html) => {
    const d = document.createElement("div");
    d.className = "line" + (cls ? " " + cls : "");
    d.innerHTML = html; log.appendChild(d);
    container.scrollTop = container.scrollHeight;
  };
  const setBar = (frac, text) => {
    fill.style.width = Math.round((frac || 0) * 100) + "%";
    label.textContent = text;
  };

  // Combining is quick; show it as the first slice of the bar. Video encoding
  // (if selected) fills the rest with a real % and ETA from ffmpeg.
  setBar(makeVideo ? 0.05 : 0.4, `Combining ${selected.length} selected chapters…`);

  try {
    await streamSSE(`/recover/${jobId}`,
      { make_video: makeVideo, format: "mp3", selected_chapters: selected },
      (ev) => {
        if (ev.type === "bind_progress"){
          if (ev.stage === "video"){
            const frac = ev.frac || 0;
            const barFrac = 0.10 + frac * 0.90;   // video spans 10%–100%
            const pct = Math.round(frac * 100);
            const eta = ev.eta_sec != null ? " · " + fmtEta(ev.eta_sec) + " left" : "";
            setBar(barFrac, `Building MP4 video… ${pct}%${eta}`);
          } else {
            setBar(0.08, "Combining chapters into one audiobook…");
          }
        } else if (ev.type === "bind_done"){
          setBar(1, "Done");
          addLine("done", `✓ Recombined ${ev.chapters_found} chapters.`);
          const res = $("csResults"); show("csResults");
          let html = `<h3>Your new audiobook is ready</h3>`;
          const links = [];
          if (ev.audio_file) links.push(dlLink(jobId, ev.audio_file, "Download audiobook"));
          if (ev.video_file) links.push(dlLink(jobId, ev.video_file, "Download video"));
          if (ev.timestamps_file) links.push(dlLink(jobId, ev.timestamps_file, "Download YouTube chapters"));
          if (ev.drive_chapters_file) links.push(dlLink(jobId, ev.drive_chapters_file, "Download Google Drive chapter page"));
          if (links.length) html += `<div class="report-links">${links.join(" · ")}</div>`;
          if (ev.video_error) html += `<div class="line err">Video step: ${escapeHtml(ev.video_error)}</div>`;
          if (ev.timestamps){
            html += `<p class="muted">New chapter list (renumbered for your selection):</p>`;
            html += `<pre id="tsBlock">${escapeHtml(ev.timestamps)}</pre>`;
            html += `<button class="copy-ts" onclick="copyTs()">Copy timestamps for YouTube</button>`;
          }
          res.innerHTML = html;
        } else if (ev.type === "bind_error"){
          addLine("err", `✕ ${escapeHtml(ev.message)}`);
        }
      });
  } catch (e) {
    addLine("err", "✕ Recombine failed.");
  }
  btn.disabled = false; btn.textContent = "Recombine selected chapters";
}
