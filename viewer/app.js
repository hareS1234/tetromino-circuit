/* A2 pipeline replay viewer — plain JavaScript, no framework, no server state (U18, guide §12.1).
   Reads an a2-trace-v1 file (results/traces/*.json): per-cycle bank valid/tag arrays, handshakes, best
   registers and compactor samples from the Verilated RTL, plus per-candidate reference payloads linked
   by tag.  Nothing shown is synthetic: token positions come from the trace records; playback freezes
   when the trace says advance = 0; a reset clears every token at the recorded edge. */
(function () {
  "use strict";
  const GROUPS = [["landing", 0, 1], ["merge", 2, 3], ["ranks", 4, 9], ["select", 10, 12], ["features", 13, 19], ["score", 20, 22]];
  const PIECES = ["I", "O", "T", "S", "Z", "J", "L"];
  // piece cells are derived from the payloads (merged_rows minus the original rows): no geometry is duplicated here
  let trace = null, stages = null, idx = 0, playing = false, timer = null, expanded = null, filter = "all";
  const $ = (id) => document.getElementById(id);

  function status(msg) { $("status").textContent = msg; }

  async function loadUrl(url) {
    status("loading " + url + " …");
    try {
      const r = await fetch(url);
      if (!r.ok) throw new Error(r.status + " " + r.statusText);
      setTrace(await r.json(), url);
    } catch (e) {
      status("could not load " + url + " (" + e.message + "). Serve the repository root with `python -m http.server` or open a local file.");
    }
    try { const m = await fetch("../architecture/a2_stages.json"); if (m.ok) stages = (await m.json()).stages; } catch (e) { stages = null; }
  }

  function setTrace(doc, name) {
    if (doc.schema !== "a2-trace-v1") { status("not an a2-trace-v1 file"); return; }
    trace = doc; idx = 0; expanded = null;
    $("main").hidden = false;
    const req = doc.requests[0];
    status(`${name}: ${doc.scenario} (${doc.scenario_kind || ""}) — ${doc.cycles.length} cycles, ${req.candidate_count} candidates, piece ${PIECES[req.piece]}`);
    const jump = $("jump");
    jump.innerHTML = "";
    const add = (label, cyc) => { const o = document.createElement("option"); o.value = cyc; o.textContent = label; jump.appendChild(o); };
    add("— events —", "");
    const ev = doc.events || [];
    const firstOf = (k) => ev.find((e) => e.kind === k);
    const lastOf = (k) => [...ev].reverse().find((e) => e.kind === k);
    if (firstOf("request_accepted")) add("request accepted", firstOf("request_accepted").cycle);
    if (firstOf("candidate_accepted")) add("first candidate accepted", firstOf("candidate_accepted").cycle);
    if (firstOf("candidate_retired")) add("first candidate retired", firstOf("candidate_retired").cycle);
    ev.filter((e) => e.kind === "best_changed").forEach((e, i) => add(`best update ${i + 1}: id ${e.best.id} score ${e.best.score}`, e.cycle));
    const stall = firstOf("output_blocked"); if (stall) add("output blocked (m_ready = 0)", stall.cycle);
    const frozenCycle = doc.cycles.find((cc, i) => i > 2 && !cc.advance && !cc.rst); if (frozenCycle) add("pipeline frozen (stall, advance = 0)", frozenCycle.cycle);
    const rst = ev.filter((e) => e.kind === "reset").find((e) => e.cycle > 3); if (rst) add("reset with occupied stages", rst.cycle);
    const lastRet = lastOf("candidate_retired"); if (lastRet) add("last result (final retirement)", lastRet.cycle);
    const rsp = firstOf("response_consumed"); if (rsp) add("response consumed", rsp.cycle);
    jump.onchange = () => { if (jump.value !== "") { goTo(parseInt(jump.value, 10) - 1); } };
    $("trace-meta").textContent = `backend ${doc.backend} top ${doc.top} native_key ${doc.native_key.slice(0, 12)}… source ${doc.source_sha256.slice(0, 12)}… ` +
      `manifest ${doc.stage_manifest_sha256.slice(0, 12)}… sampling: ${doc.sampling}; timing projection: ${doc.timing_projection === null ? "none (cycles only)" : doc.timing_projection}\n` +
      `fixture: ${JSON.stringify(doc.fixture)}`;
    render();
  }

  function payloadOf(tag) { return trace.requests[0].candidates.find((p) => p.tag === tag) || null; }
  function payloadOfId(id) { return trace.requests[0].candidates.find((p) => p.candidate_id === id) || null; }

  function drawBoard(canvas, rows, hi, fullRows) {
    const ctx = canvas.getContext("2d"), cw = canvas.width / 10, ch = canvas.height / 20;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (let y = 0; y < 20; y++) for (let x = 0; x < 10; x++) {
      const filled = rows ? (rows[y] >> x) & 1 : 0;
      const isHi = hi && ((hi[y] >> x) & 1) && !filled;
      ctx.fillStyle = isHi ? "#d95f02" : filled ? "#4d4d4d" : "#fff";
      ctx.fillRect(x * cw, canvas.height - (y + 1) * ch, cw, ch);
      ctx.strokeStyle = "#ccc"; ctx.lineWidth = 0.5;
      ctx.strokeRect(x * cw, canvas.height - (y + 1) * ch, cw, ch);
      if (isHi) { ctx.strokeStyle = "#000"; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x * cw, canvas.height - y * ch); ctx.lineTo((x + 1) * cw, canvas.height - (y + 1) * ch); ctx.stroke(); }
    }
    (fullRows || []).forEach((r) => { ctx.strokeStyle = "#000"; ctx.setLineDash([4, 3]); ctx.lineWidth = 2; ctx.strokeRect(1, canvas.height - (r + 1) * ch + 1, canvas.width - 2, ch - 2); ctx.setLineDash([]); });
  }

  function selectedTag(c) {
    if (c.banks[22]) return { tag: c.banks[22].tag, why: "in P22, retires on the next edge" };
    const occ = c.banks.filter(Boolean).map((b) => b.tag);
    if (occ.length) return { tag: Math.max(...occ), why: "newest token in flight" };
    if (c.m) return { tag: c.m.tag, why: "retired on this edge" };
    if (c.best && c.best.valid && trace.cycles.slice(0, idx + 1).some((cc) => cc.m)) {
      const bp = payloadOfId(c.best.id); if (bp) return { tag: bp.tag, why: "search complete: final best (winner)" };
    }
    return null;
  }

  function render() {
    if (!trace) return;
    const c = trace.cycles[idx], req = trace.requests[0];
    const sel = selectedTag(c), pl = sel ? payloadOf(sel.tag) : null;
    const best = c.best || { valid: 0 };
    // board region
    const hi = pl && pl.legal ? pl.merged_rows.map((m, y) => m & ~req.rows[y]) : null;
    drawBoard($("board"), req.rows, hi, pl && pl.legal ? pl.full_rows : []);
    drawBoard($("merged"), pl && pl.legal ? pl.merged_rows : req.rows, null, pl && pl.legal ? pl.full_rows : []);
    const meta = $("cand-meta");
    meta.innerHTML = "";
    const dd = (k, v) => { const a = document.createElement("dt"); a.textContent = k; const b = document.createElement("dd"); b.textContent = v; meta.append(a, b); };
    dd("piece", PIECES[req.piece] + ` (${req.candidate_count} dense candidates)`);
    if (pl) {
      dd("selected", `tag ${pl.tag}, candidate id ${pl.candidate_id} — ${sel.why}`);
      dd("placement", `rotation ${pl.rotation}, x ${pl.x}` + (pl.legal ? `, y ${pl.y}` : ""));
      dd("legal", pl.legal ? "yes" : "no (canonical y 0, score 0)");
    } else dd("selected", "none");
    if (req.response && trace.cycles.slice(0, idx + 1).some((cc) => cc.rsp_valid)) {
      const r = req.response;
      dd("response", r.no_move ? "no move" : `rotation ${r.rotation} x ${r.x} y ${r.y} score ${r.score}; ${r.cycles} cycles = N + 29`);
    } else if (req.response === null) dd("response", "none — standalone harness, no core");
    // pipeline
    const pipe = $("pipe");
    pipe.innerHTML = "";
    const frozen = !c.advance && !c.rst;
    pipe.classList.toggle("frozen", frozen);
    GROUPS.forEach(([name, lo, hi2]) => {
      const block = document.createElement("div"); block.className = "block"; block.tabIndex = 0; block.setAttribute("role", "listitem");
      block.setAttribute("aria-label", `${name} block, banks P${lo} to P${hi2}`);
      const title = document.createElement("div"); title.className = "title"; title.textContent = `${name} P${lo}–P${hi2}`; block.appendChild(title);
      const banks = document.createElement("div"); banks.className = "banks";
      for (let i = lo; i <= hi2; i++) {
        const b = c.banks[i];
        const el = document.createElement("div"); el.className = "bank";
        el.setAttribute("aria-label", b ? `bank P${i}: tag ${b.tag} id ${b.id}${b.last ? " last" : ""}` : `bank P${i}: empty`);
        if (b) {
          el.classList.add("occupied");
          const isSel = sel && b.tag === sel.tag;
          const bp = payloadOf(b.tag);
          const isBest = best.valid && bp && bp.candidate_id === best.id;
          if (isSel) el.classList.add("selected");
          if (isBest) el.classList.add("best");
          if ((filter === "selected" && !isSel) || (filter === "best" && !isBest)) el.classList.add("dimmed");
          el.innerHTML = `<span>${b.tag}</span>` + (b.last ? `<span class="last">last</span>` : "");
        }
        const ix = document.createElement("span"); ix.className = "idx"; ix.textContent = "P" + i; el.appendChild(ix);
        banks.appendChild(el);
      }
      block.appendChild(banks);
      block.onclick = () => { expanded = expanded === name ? null : name; renderDetail(); };
      block.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); block.onclick(); } };
      pipe.appendChild(block);
    });
    const st = $("pipe-state");
    const occ = c.banks.filter(Boolean).length;
    st.innerHTML = c.rst ? `<span class="reset">RESET</span> — every valid bank cleared at this edge (${occ}/23 occupied after)` :
      frozen ? `<span class="warn">STALL: advance = 0</span> — output blocked (m_ready = 0), tokens frozen in place, input not accepted; occupancy ${occ}/23` :
      `advance = 1 — occupancy ${occ}/23` + (c.s ? `; accepted tag ${c.s.tag} (id ${c.s.id})${c.s.last ? " [last]" : ""}` : "") +
      (c.m ? `; retired tag ${c.m.tag} (legal ${c.m.legal}, y ${c.m.y}, score ${c.m.score})${c.m.consumed === 0 ? " — NOT consumed (blocked)" : ""}` : "");
    renderDetail();
    // explanation
    const lines = [];
    if (pl && pl.legal) {
      lines.push(`token ${pl.tag} (candidate id ${pl.candidate_id}) — reference model, linked by tag`);
      lines.push(`full rows: ${pl.full_rows.length ? pl.full_rows.join(", ") : "none"}    L = ${pl.lines}`);
      lines.push(`keep bits (rows 0..19): ${pl.keep.map((k) => (k ? "k" : "·")).join("")}`);
      lines.push(`inclusive ranks:        ${pl.ranks.map((r) => String(r).padStart(2)).join(" ")}`);
      lines.push(`features after clear: A ${pl.A}  Q ${pl.Q}  U ${pl.U}`);
      lines.push(`score = 76·${pl.lines} − 51·${pl.A} − 36·${pl.Q} − 18·${pl.U} = ${pl.score}`);
    } else if (pl) lines.push(`token ${pl.tag} (id ${pl.candidate_id}) is an illegal placement: legal 0, y 0, score 0 (canonical)`);
    else lines.push("no token selected");
    if (c.m) {
      const rp = payloadOf(c.m.tag);
      const ok = rp && (rp.legal ? (c.m.score === rp.score && c.m.y === rp.y && c.m.legal === 1) : c.m.legal === 0);
      lines.push(`RTL retired on this edge: tag ${c.m.tag} legal ${c.m.legal} y ${c.m.y} score ${c.m.score}  ${ok ? "✓ equals the reference" : "✗ MISMATCH"}`);
    }
    if (c.p9) { const p = payloadOf(c.p9.tag); const ok = p && p.legal && c.p9.ranks.join() === p.ranks.join(); lines.push(`RTL P9 (tag ${c.p9.tag}): keep 0x${c.p9.keep.toString(16)} ranks ${c.p9.ranks.join(" ")} ${p && p.legal ? (ok ? "✓" : "✗") : "(illegal token: not compared)"}`); }
    if (c.p12) { const p = payloadOf(c.p12.tag); lines.push(`RTL P12 (tag ${c.p12.tag}): cleared board sampled from the compactor register` + (p && p.legal ? (boardHex(p.cleared_rows) === c.p12.board ? " ✓ equals the reference" : " ✗ MISMATCH") : "")); }
    $("explain").textContent = lines.join("\n");
    drawBoard($("cleared"), pl && pl.legal ? pl.cleared_rows : null, null, []);
    const bb = $("best-box");
    if (!c.best) bb.innerHTML = `standalone candidate_pipe harness: no reducer.<br>story phase: <b>${c.phase || ""}</b>${c.m_ready === 0 ? " (m_ready = 0)" : ""}`;
    else if (best.valid) { const bp = payloadOfId(best.id); bb.innerHTML = `<b>current best (RTL best_reducer)</b><br>candidate id ${best.id}${bp ? ` (tag ${bp.tag})` : ""}<br>score ${best.score}, y ${best.y}` + (c.best_changed ? `<br><span class="changed">▶ updated on this edge</span>` : ""); }
    else bb.innerHTML = "<b>current best</b><br>none yet (no legal candidate retired)";
    // timeline + label
    drawTimeline();
    $("cycle-label").textContent = `cycle ${c.cycle} / ${trace.cycles.length}` + (c.phase ? ` — ${c.phase}` : "");
    $("btn-play").textContent = playing ? "Pause" : "Play";
  }

  function boardHex(rows) { let s = ""; for (let w = 6; w >= 0; w--) { let v = 0; for (let b = 0; b < 32; b++) { const bit = 32 * w + b; if (bit < 200 && ((rows[Math.floor(bit / 10)] >> (bit % 10)) & 1)) v |= (1 << b); } s += (v >>> 0).toString(16).padStart(8, "0"); } return s; }

  function renderDetail() {
    const d = $("bank-detail");
    if (!trace || !expanded) { d.textContent = "click a block to list its banks and the fields each bank registers (from architecture/a2_stages.json when served)."; return; }
    const g = GROUPS.find((x) => x[0] === expanded), c = trace.cycles[idx];
    const out = [];
    for (let i = g[1]; i <= g[2]; i++) {
      const name = (trace.bank_names && trace.bank_names[i]) || `P${i}`;
      const b = c.banks[i];
      const fields = stages ? stages[i].out_fields.map((f) => `${f.name}[${f.bits}]`).join(" ") : "(fields: serve architecture/a2_stages.json)";
      out.push(`${name}: ${b ? `tag ${b.tag} id ${b.id}${b.last ? " last" : ""}` : "empty"}\n    registers: ${fields}`);
    }
    d.textContent = out.join("\n");
  }

  function drawTimeline() {
    const cv = $("timeline"), ctx = cv.getContext("2d"), n = trace.cycles.length, w = cv.width - 90, x0 = 80;
    ctx.clearRect(0, 0, cv.width, cv.height);
    ctx.font = "11px system-ui"; ctx.fillStyle = "#444";
    ["accept", "retire", "advance", "reset"].forEach((l, r) => ctx.fillText(l, 4, 16 + r * 18));
    trace.cycles.forEach((cc, i) => {
      const x = x0 + (i + 0.5) * (w / n);
      if (cc.s) { ctx.fillStyle = "#444"; ctx.fillRect(x - 1.5, 6, 3, 10); }
      if (cc.m && cc.m.consumed !== 0) { ctx.fillStyle = "#444"; ctx.fillRect(x - 1.5, 24, 3, 10); }
      ctx.fillStyle = cc.advance ? "#9ccc9c" : "#d95f02"; ctx.fillRect(x - 1.5, 42, 3, cc.advance ? 6 : 12);
      if (cc.rst) { ctx.fillStyle = "#000"; ctx.fillRect(x - 2, 60, 4, 12); }
      if (cc.best_changed) { ctx.fillStyle = "#1b9e77"; ctx.fillRect(x - 1, 78, 2, 8); }
    });
    const xc = x0 + (idx + 0.5) * (w / n);
    ctx.strokeStyle = "#d95f02"; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(xc, 2); ctx.lineTo(xc, cv.height - 2); ctx.stroke();
    ctx.fillStyle = "#444"; ctx.fillText("best ▮", 4, 86);
    cv.onclick = (e) => { const r = cv.getBoundingClientRect(); const rel = (e.clientX - r.left) * (cv.width / r.width) - x0; goTo(Math.floor(rel / (w / n))); };
  }

  function goTo(i) { if (!trace) return; idx = Math.max(0, Math.min(trace.cycles.length - 1, i)); render(); }
  function step(d) { goTo(idx + d); }
  function play() {
    playing = !playing; $("btn-play").textContent = playing ? "Pause" : "Play";
    clearInterval(timer);
    if (playing) timer = setInterval(() => { if (idx >= trace.cycles.length - 1) { playing = false; clearInterval(timer); render(); return; } step(1); }, 1000 / parseInt($("speed").value, 10));
  }

  $("load-btn").onclick = () => loadUrl($("trace-select").value);
  $("trace-file").onchange = (e) => { const f = e.target.files[0]; if (!f) return; const rd = new FileReader(); rd.onload = () => { try { setTrace(JSON.parse(rd.result), f.name); } catch (err) { status("invalid JSON: " + err.message); } }; rd.readAsText(f); };
  $("btn-first").onclick = () => goTo(0);
  $("btn-last").onclick = () => goTo(1e9);
  $("btn-prev").onclick = () => step(-1);
  $("btn-next").onclick = () => step(1);
  $("btn-play").onclick = play;
  $("speed").oninput = () => { $("speed-val").textContent = $("speed").value; if (playing) { playing = false; play(); } };
  $("btn-cand").onclick = () => { const t = parseInt($("jump-cand").value, 10); const i = trace.cycles.findIndex((cc) => cc.s && cc.s.tag === t); if (i >= 0) goTo(i); else status(`candidate tag ${t} is never accepted in this trace`); };
  $("filter").onchange = () => { filter = $("filter").value; render(); };
  document.addEventListener("keydown", (e) => { if (!trace || e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return; if (e.key === "ArrowRight") step(1); if (e.key === "ArrowLeft") step(-1); if (e.key === " ") { e.preventDefault(); play(); } });
  if (window.A2_EMBEDDED_STAGES) stages = window.A2_EMBEDDED_STAGES;
  if (window.A2_EMBEDDED_TRACE) setTrace(window.A2_EMBEDDED_TRACE, "embedded demo");
})();
