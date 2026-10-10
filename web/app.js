// xv6, line by line: hover cards, go-to-definition, the symbol panel and search.
// Data comes from xref.js (window.XREF) and src.js (window.SRC), both generated.
(function () {
  "use strict";
  var X = window.XREF, SRC = window.SRC;
  var body = document.body;
  var ROOT = body.dataset.root || "";
  var CUR = body.dataset.file || "";
  var FILES = X.files;               // [path, lang, group, nlines, generated]
  var SYMS = X.syms;                 // [name, kind, type, group, lang, defFile, defLine, occ[]]
  var ROLE = ["def", "decl", "set", "use"];
  var LANG = { c: "C", asm: "assembly", ld: "linker script", make: "Makefile" };
  var curIdx = -1;
  FILES.forEach(function (f, i) { if (f[0] === CUR) curIdx = i; });

  function $(sel, el) { return (el || document).querySelector(sel); }
  function $$(sel, el) { return Array.prototype.slice.call((el || document).querySelectorAll(sel)); }
  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function pageUrl(fi) { return ROOT + "src/" + FILES[fi][0] + ".html"; }
  function symUrl(fi, line, sid) {
    return pageUrl(fi) + (sid != null ? "?s=" + sid : "") + (line ? "#L" + line : "");
  }
  function srcLine(fi, line) { var f = SRC[fi]; return (f && f[line - 1]) || ""; }
  function sidsOf(a) { return a.dataset.s.split(",").map(Number); }
  function store(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }

  // ------------------------------------------------------------ theme
  $("#theme").addEventListener("click", function () {
    var root = document.documentElement;
    var dark = root.dataset.theme ? root.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    store("theme", root.dataset.theme);
  });
  $("#tree-toggle").addEventListener("click", function () { body.classList.toggle("tree-open"); });
  var here = $(".tree a.here");
  if (here) here.scrollIntoView({ block: "center" });

  // ------------------------------------------------------------ lines
  function gotoLine(n, flash) {
    var el = document.getElementById("L" + n);
    if (!el) return;
    $$(".l.target, .l.flash").forEach(function (e) { e.classList.remove("target", "flash"); });
    el.classList.add("target");
    el.scrollIntoView({ block: "center" });
    if (flash) { el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash"); }
  }
  function lineFromHash() { var m = /^#L(\d+)$/.exec(location.hash); return m ? +m[1] : 0; }

  // ------------------------------------------------------------ panel
  var panel = $("#panel");
  function showTab(name) {
    if (!panel) return;
    $$(".panel-tabs [role=tab]").forEach(function (t) {
      t.setAttribute("aria-selected", String(t.dataset.tab === name));
    });
    $("#tab-notes").hidden = name !== "notes";
    $("#tab-refs").hidden = name !== "refs";
    body.classList.add("panel-open");
  }
  if (panel) {
    $$(".panel-tabs [role=tab]").forEach(function (t) {
      t.addEventListener("click", function () { showTab(t.dataset.tab); });
    });
    $("#panel-close").addEventListener("click", function () { body.classList.remove("panel-open"); });
  }

  function highlight(sids) {
    $$("a.sy.hl").forEach(function (a) { a.classList.remove("hl"); });
    if (!sids) return;
    $$("a.sy").forEach(function (a) {
      if (sidsOf(a).some(function (s) { return sids.indexOf(s) >= 0; })) a.classList.add("hl");
    });
  }

  function snippet(fi, line, col, len) {
    var t = srcLine(fi, line), lead = t.length - t.replace(/^\s+/, "").length;
    var c = col - 1;
    function sq(x) { return esc(x.replace(/\s{2,}/g, " ")); }   // drop column alignment
    if (c < lead || len <= 0) return sq(t.trim());
    return sq(t.slice(lead, c)) + "<b>" + esc(t.slice(c, c + len)) + "</b>" + sq(t.slice(c + len));
  }

  function where(s) { return FILES[s[5]][0] + ":" + s[6]; }

  function renderSymbol(sid) {
    var s = SYMS[sid], occ = s[7], name = s[0];
    var groups = {}, order = [], counts = [0, 0, 0, 0];
    for (var i = 0; i < occ.length; i += 4) {
      var fi = occ[i];
      if (!groups[fi]) { groups[fi] = []; order.push(fi); }
      groups[fi].push([occ[i + 1], occ[i + 2], occ[i + 3]]);
      counts[occ[i + 3]]++;
    }
    order.sort(function (a, b) {
      if (a === s[5]) return -1; if (b === s[5]) return 1;
      if (a === curIdx) return -1; if (b === curIdx) return 1;
      return FILES[a][0] < FILES[b][0] ? -1 : 1;
    });
    var h = '<h2 class="sym-head"><span class="kind">' + esc(s[1]) + "</span>" + esc(name) + "</h2>";
    if (s[2]) h += '<div class="sym-type">' + esc(s[2]) + "</div>";
    h += '<p class="sym-def">Defined in <a href="' + symUrl(s[5], s[6], sid) + '" data-go="' +
      s[5] + ":" + s[6] + '">' + esc(where(s)) + "</a>" +
      (LANG[s[4]] ? " (" + LANG[s[4]] + (s[3] ? ", " + esc(s[3]) : "") + ")" : "") + "</p>";
    var bits = [];
    if (counts[1]) bits.push(counts[1] + " declaration" + (counts[1] > 1 ? "s" : ""));
    if (counts[2]) bits.push(counts[2] + " more assignment" + (counts[2] > 1 ? "s" : ""));
    bits.push(counts[3] + " use" + (counts[3] === 1 ? "" : "s"));
    bits.push(order.length + " file" + (order.length === 1 ? "" : "s"));
    h += '<p class="sum">' + bits.join(" · ") + "</p>";
    order.forEach(function (fi) {
      h += '<div class="occ-file"><span>' + esc(FILES[fi][0]) + "</span><span>" +
        groups[fi].length + "</span></div>";
      groups[fi].forEach(function (o) {
        var cur = fi === curIdx && lineFromHash() === o[0] ? " cur" : "";
        h += '<a class="occ' + cur + '" href="' + symUrl(fi, o[0], sid) + '" data-go="' + fi + ":" +
          o[0] + '"><span class="ol">' + o[0] + '</span><span class="os">' +
          snippet(fi, o[0], o[1], name.length) + "</span>" +
          (o[2] < 3 ? '<span class="role">' + ROLE[o[2]] + "</span>" : "") + "</a>";
      });
    });
    return h;
  }

  function showSymbols(sids) {
    if (!panel) return;
    var box = $("#tab-refs");
    if (sids.length === 1) {
      box.innerHTML = renderSymbol(sids[0]);
    } else {
      box.innerHTML = '<p class="sum">This name has ' + sids.length + " different definitions " +
        "(each program has its own). Pick one:</p><div class=\"pick\">" +
        sids.map(function (sid) {
          var s = SYMS[sid];
          return '<a href="' + symUrl(s[5], s[6], sid) + '" data-go="' + s[5] + ":" + s[6] +
            '" data-pick="' + sid + '">' + esc(where(s)) + "</a>";
        }).join("") + "</div>";
    }
    highlight(sids);
    showTab("refs");
  }

  // Navigate to file:line, showing symbol sid in the panel. Same page: no reload.
  function go(fi, line, sid, push) {
    if (fi === curIdx) {
      var url = "?" + (sid != null ? "s=" + sid : "") + "#L" + line;
      if (push !== false) history.pushState({ sid: sid, line: line }, "", url);
      if (sid != null) showSymbols([sid]);
      gotoLine(line, true);
    } else {
      location.href = symUrl(fi, line, sid);
    }
  }

  document.addEventListener("click", function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var a = e.target.closest("a");
    if (!a) return;
    if (a.closest(".tip")) hideTip();
    if (a.classList.contains("sy")) {
      e.preventDefault();
      hideTip();
      var sids = sidsOf(a);
      if (sids.length > 1) { showSymbols(sids); return; }
      var s = SYMS[sids[0]];
      var row = a.closest(".l"), line = row ? +row.id.slice(1) : 0;
      if (row && (a.classList.contains("def") || (s[5] === curIdx && s[6] === line))) {
        history.replaceState({ sid: sids[0], line: line }, "", "?s=" + sids[0] + "#L" + line);
        showSymbols(sids);
        gotoLine(line, false);
      } else {
        go(s[5], s[6], sids[0]);
      }
      return;
    }
    if (a.dataset.go) {
      e.preventDefault();
      var p = a.dataset.go.split(":").map(Number);
      var sid = a.dataset.pick != null ? +a.dataset.pick : sidFromUrl();
      go(p[0], p[1], sid);
      body.classList.remove("panel-open");
      return;
    }
    if (a.classList.contains("n")) {
      e.preventDefault();
      var n = +a.getAttribute("href").slice(2);
      selectLine(n, true);
      return;
    }
    if (a.classList.contains("ln-ref") && a.dataset.line) {
      e.preventDefault();
      var from = +a.dataset.line, to = +(a.dataset.to || from);
      if (a.closest("#tab-notes")) { gotoLine(from, true); markRange(from, to); }
      else selectLine(from, true);
      return;
    }
  });

  // Clicking a RISC-V name in the code opens its glossary entry.
  document.addEventListener("click", function (e) {
    var g = e.target.closest && e.target.closest("[data-g]");
    if (!g || e.defaultPrevented || e.target.closest("a")) return;
    var entry = (X.gloss || {})[g.dataset.g];
    if (!entry) return;
    e.preventDefault();
    location.href = ROOT + "glossary.html#" + entry[0];
  }, true);

  // Clicking on a code line (not on a link) selects it and shows its notes.
  document.addEventListener("click", function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.target.closest("a, .inline-note")) return;
    var row = e.target.closest(".code .l");
    if (!row || (window.getSelection && String(window.getSelection()))) return;
    selectLine(+row.id.slice(1), true);
  });

  function sidFromUrl() {
    var m = /[?&]s=(\d+)/.exec(location.search);
    return m ? +m[1] : null;
  }
  function fromUrl(flash) {
    var sid = sidFromUrl();
    var n = lineFromHash();
    if (sid != null && SYMS[sid]) { showSymbols([sid]); if (n) gotoLine(n, flash); }
    else { highlight(null); if (n) selectLine(n, false, flash); }
  }

  // ------------------------------------------------------------ notes
  var TOURLINES = {};
  try { TOURLINES = JSON.parse(($("#tourlines") || {}).textContent || "{}"); } catch (e) {}
  var STACKPTS = {};
  try { STACKPTS = JSON.parse(($("#stackpts") || {}).textContent || "{}"); } catch (e) {}
  var STACKNAME = { user: "user stack", kernel: "kernel stack", scheduler: "scheduler stack",
                    boot: "boot stack", none: "no usable stack", same: "the same stack" };
  Object.keys(STACKPTS).forEach(function (k) {
    var el = document.getElementById("L" + k);
    if (!el) return;
    el.classList.add("spx");
    el.dataset.spto = STACKPTS[k].to;
    var num = el.querySelector(".n");
    if (num) num.title = "Stack switch: sp moves to the " + (STACKNAME[STACKPTS[k].to] || STACKPTS[k].to);
  });
  var LOCKPTS = {};
  try { LOCKPTS = JSON.parse(($("#lockpts") || {}).textContent || "{}"); } catch (e) {}
  var LOCKOP = { acquire: "acquire", release: "release", acquiresleep: "acquire (may sleep)",
                 releasesleep: "release", holding: "check held", holdingsleep: "check held",
                 initlock: "initialize", initsleeplock: "initialize",
                 push_off: "push_off: noff + 1, interrupts off", pop_off: "pop_off: noff \u2212 1",
                 intr_on: "interrupts on (SIE = 1)", intr_off: "interrupts off (SIE = 0)" };
  Object.keys(LOCKPTS).forEach(function (k) {
    var el = document.getElementById("L" + k);
    if (!el) return;
    var ops = LOCKPTS[k];
    el.classList.add("lkx");
    el.dataset.lk = ops[0].kind;
    var num = el.querySelector(".n");
    if (num && !el.classList.contains("spx"))
      num.title = ops.map(function (o) { return o.name ? LOCKOP[o.op] + " " + o.name : LOCKOP[o.op]; }).join("; ");
  });
  var NOTES = $$("#notes-data .note").map(function (el) {
    return { a: +el.dataset.a, b: +el.dataset.b, block: el.classList.contains("block"), el: el };
  });
  var STOPS = [];      // lines where a note begins, in order
  NOTES.forEach(function (n) { if (STOPS.indexOf(n.a) < 0) STOPS.push(n.a); });
  STOPS.sort(function (x, y) { return x - y; });
  var selected = 0;

  function markRange(a, b) {
    $$(".l.rng").forEach(function (e) { e.classList.remove("rng"); });
    for (var i = a; i <= b; i++) { var el = document.getElementById("L" + i); if (el) el.classList.add("rng"); }
  }

  function notesFor(n) {
    return NOTES.filter(function (x) { return x.a <= n && n <= x.b; })
      .sort(function (x, y) { return (y.b - y.a) - (x.b - x.a) || x.a - y.a; });
  }

  function renderNotes(n) {
    var box = $("#tab-notes");
    if (!box) return;
    var list = notesFor(n);
    var prev = STOPS.filter(function (x) { return x < n; }).pop();
    var next = STOPS.filter(function (x) { return x > n; })[0];
    var h = '<div class="note-nav"><button class="btn" data-step="-1"' + (prev ? "" : " disabled") +
      '>&larr; Prev</button><span>Line ' + n + "</span>" + '<button class="btn" data-step="1"' +
      (next ? "" : " disabled") + ">Next &rarr;</button></div>";
    box.innerHTML = h;
    if (!list.length) {
      // Blank lines have no note of their own: show the nearest note instead.
      var near = null, best = Infinity;
      NOTES.forEach(function (x) {
        var d = x.a > n ? x.a - n : n - x.b;
        if (d < best || (d === best && x.a > n)) { best = d; near = x; }
      });
      var blank = !srcLine(curIdx, n).trim();
      box.insertAdjacentHTML("beforeend", '<p class="empty">' +
        (blank ? "This line is blank." : "No note covers this line.") +
        (near ? " The nearest note:" : "") + "</p>");
      if (near) list = [near];
    }
    var sw = STACKPTS[n];
    if (sw) {
      box.insertAdjacentHTML("beforeend", '<div class="spbox st-' + esc(sw.to) + '"><div class="spk">' +
        '<span class="swi">&#8644;</span> Stack switch: ' +
        (sw.from ? esc(STACKNAME[sw.from] || sw.from) + " &rarr; " : "") +
        '<a href="' + ROOT + 'concepts/stacks.html#' + esc(sw.to) + '">' +
        esc(STACKNAME[sw.to] || sw.to) + "</a></div><div>" + sw.note + "</div></div>");
    }
    (LOCKPTS[n] || []).forEach(function (o) {
      var irq = o.kind === "irq";
      var href = ROOT + "concepts/locks.html#" + (irq ? (o.op.indexOf("intr") === 0 ? "sie" : "noff") : "lock-" + o.id);
      box.insertAdjacentHTML("beforeend", '<div class="lkbox ' + esc(o.kind) + '"><div class="spk">' +
        (irq ? "Interrupt state: " : (o.kind === "sleep" ? "Sleep-lock: " : "Spinlock: ")) +
        '<a href="' + href + '">' + (irq ? esc(LOCKOP[o.op]) : esc(LOCKOP[o.op]) + " <code>" + esc(o.name) + "</code>") +
        "</a></div>" + (o.protects ? "<div>Protects " + o.protects + ".</div>" : "") + "</div>");
    });
    var tl = TOURLINES[n];
    if (tl && tl.length) {
      box.insertAdjacentHTML("beforeend", '<div class="intours"><b>In the guided tours:</b> ' +
        tl.map(function (t) {
          return '<a href="' + ROOT + t[3] + "#step-" + t[1] + '">Tour ' + t[0] + ", step " + t[1] +
            ": " + esc(t[2]) + "</a>";
        }).join("") + "</div>");
    }
    list.forEach(function (x) {
      var c = x.el.cloneNode(true);
      c.addEventListener("mouseenter", function () { markRange(x.a, x.b); });
      c.addEventListener("mouseleave", function () { markRange(0, -1); });
      box.appendChild(c);
    });
    box.scrollTop = 0;
  }

  function selectLine(n, push, flash) {
    if (!document.getElementById("L" + n)) return;
    selected = n;
    if (push) history.pushState({ line: n }, "", location.pathname + "#L" + n);
    highlight(null);
    gotoLine(n, flash);
    if (NOTES.length) { renderNotes(n); showTab("notes"); }
  }

  function step(d) {
    var cur = selected || 0;
    var target = d > 0 ? STOPS.filter(function (x) { return x > cur; })[0]
      : STOPS.filter(function (x) { return x < cur; }).pop();
    if (target) selectLine(target, true, true);
  }

  if ($("#tab-notes")) {
    $("#tab-notes").addEventListener("click", function (e) {
      var b = e.target.closest("[data-step]");
      if (b) step(+b.dataset.step);
    });
  }
  if ($("#read-start")) {
    $("#read-start").addEventListener("click", function () { if (STOPS.length) selectLine(STOPS[0], true, true); });
  }

  // Inline mode: notes appear between the lines of code.
  var inlineBox = $("#inline");
  function setInline(on) {
    $$(".inline-note").forEach(function (e) { e.remove(); });
    body.classList.toggle("inline-mode", on);
    if (!on) return;
    NOTES.forEach(function (x) {
      var c = x.el.cloneNode(true);
      c.classList.add("inline-note");
      var anchor = document.getElementById("L" + (x.block ? x.a : x.b));
      if (!anchor) return;
      if (x.block) anchor.parentNode.insertBefore(c, anchor);
      else anchor.parentNode.insertBefore(c, anchor.nextSibling);
    });
  }
  if (inlineBox) {
    try { inlineBox.checked = localStorage.getItem("inline") === "1"; } catch (e) {}
    setInline(inlineBox.checked);
    inlineBox.addEventListener("change", function () {
      store("inline", inlineBox.checked ? "1" : "0");
      setInline(inlineBox.checked);
    });
  }
  window.addEventListener("popstate", function () { fromUrl(false); });

  fromUrl(true);

  // ------------------------------------------------------------ hover cards
  // Cards stack: a link inside a card opens another card on top of it. A card
  // stays open while the pointer is over it, over its anchor, or over a card
  // stacked on it; leaving starts a short grace period so the pointer can cross
  // the gap between a word and its card.
  var TRIGGERS = "a.sy, [data-g], a.gl";
  var tips = [];                         // [{el, anchor}], index = depth
  var openTimer = 0, closeTimer = 0, keep = 0;

  function closeFrom(level) {
    while (tips.length > level) tips.pop().el.remove();
  }
  function hideTip() {
    clearTimeout(openTimer); clearTimeout(closeTimer); closeFrom(0);
  }
  function levelOf(node) {               // depth of the card containing node, or -1
    for (var i = tips.length - 1; i >= 0; i--) if (tips[i].el.contains(node)) return i;
    return -1;
  }
  function wantDepth(n) {                // keep cards 0..n-1, close the rest soon
    keep = n;
    clearTimeout(closeTimer);
    if (tips.length > n) closeTimer = setTimeout(function () { closeFrom(keep); }, 300);
  }

  var GLOSS = {
    insn: "RISC-V instruction", csr: "RISC-V control and status register (CSR)",
    reg: "RISC-V register", dir: "assembler directive", ld: "linker script keyword",
    flag: "compiler / tool option", make: "make built-in"
  };

  function tipHtml(el) {
    if (el.classList.contains("sy")) {
      var sids = sidsOf(el);
      if (sids.length > 1) {
        var s0 = SYMS[sids[0]];
        return '<div class="tn">' + esc(s0[0]) + '</div><div class="tw">' + sids.length +
          " definitions, one per program. Click to choose.</div>";
      }
      var s = SYMS[sids[0]], uses = 0;
      for (var i = 3; i < s[7].length; i += 4) if (s[7][i] === 3) uses++;
      return '<div class="tn"><span class="kind">' + esc(s[1]) + "</span>" + esc(s[0]) + "</div>" +
        (s[2] ? '<div class="tt">' + esc(s[2]) + "</div>" : "") +
        '<div class="tw">defined in ' + esc(where(s)) + " · " + uses + " use" + (uses === 1 ? "" : "s") +
        "</div><pre>" + esc(srcLine(s[5], s[6]).trim()) + "</pre>" +
        '<div class="hint">' + (el.classList.contains("def") ? "Click to list every use"
          : "Click to go to the definition") + "</div>";
    }
    var key = el.dataset.gk || el.dataset.g, entry = (X.gloss || {})[key];
    if (entry) {
      return '<div class="tn"><span class="kind">' + esc(entry[2]) + "</span>" + esc(entry[1]) +
        '</div><div class="gs">' + entry[3].replace(/@@\//g, ROOT) + "</div>" +
        (el.dataset.gk ? "" : '<div class="hint">Click for the full glossary entry</div>');
    }
    var k = key.split(":")[0], name = key.slice(k.length + 1);
    return '<div class="tn"><span class="kind">' + esc(GLOSS[k] || k) + "</span>" + esc(name) +
      '</div><div class="hint">No glossary entry yet.</div>';
  }

  function openTip(anchor, level) {
    closeFrom(level);
    var el = document.createElement("div");
    el.className = "tip";
    el.setAttribute("role", "tooltip");
    el.style.zIndex = 50 + level;
    el.innerHTML = tipHtml(anchor);
    body.appendChild(el);
    var r = anchor.getBoundingClientRect();
    var w = el.offsetWidth, h = el.offsetHeight;
    var x = Math.min(Math.max(8, r.left), innerWidth - w - 8);
    var y = r.bottom + 6;
    if (y + h > innerHeight - 8) y = r.top - h - 6;
    el.style.left = x + "px"; el.style.top = Math.max(8, y) + "px";
    tips.push({ el: el, anchor: anchor });
  }

  document.addEventListener("mouseover", function (e) {
    var t = e.target;
    if (!t.closest) return;
    var inTip = levelOf(t);
    var trig = t.closest(TRIGGERS);
    clearTimeout(openTimer);
    if (trig) {
      var level = inTip + 1;
      if (tips[level] && tips[level].anchor === trig) { wantDepth(level + 1); return; }
      wantDepth(level);
      openTimer = setTimeout(function () { openTip(trig, level); wantDepth(level + 1); }, 250);
    } else {
      wantDepth(inTip + 1);
    }
  });
  document.addEventListener("scroll", function (e) {
    if (!(e.target.closest && e.target.closest(".tip"))) hideTip();
  }, true);

  // ------------------------------------------------------------ search
  var q = $("#q"), results = $("#results"), sel = -1, hits = [];
  var HIDE = { local: 1, parameter: 1 };

  function search(text) {
    text = text.trim().toLowerCase();
    if (!text) return [];
    var out = [];
    FILES.forEach(function (f, fi) {
      var p = f[0].toLowerCase(), base = p.split("/").pop();
      var score = base === text ? 0 : base.indexOf(text) === 0 ? 1 : p.indexOf(text) >= 0 ? 3 : -1;
      if (score >= 0) out.push({ score: score, html: '<span class="kind">file</span><span class="r-name">' +
        esc(f[0]) + "</span>", href: pageUrl(fi), go: null });
    });
    SYMS.forEach(function (s, sid) {
      var n = s[0].toLowerCase();
      var score = n === text ? 0 : n.indexOf(text) === 0 ? 2 : n.indexOf(text) >= 0 ? 4 : -1;
      if (score < 0) return;
      if (HIDE[s[1]] && !(score === 0 && s[5] === curIdx)) return;
      out.push({ score: score + (HIDE[s[1]] ? 1 : 0), html: '<span class="kind">' + esc(s[1]) +
        '</span><span class="r-name">' + esc(s[0]) + '</span><span class="r-where">' +
        esc(where(s)) + "</span>", href: symUrl(s[5], s[6], sid), go: [s[5], s[6], sid] });
    });
    out.sort(function (a, b) { return a.score - b.score; });
    return out.slice(0, 40);
  }

  function renderResults() {
    if (!hits.length) {
      results.innerHTML = q.value.trim() ? '<div class="none">No matches</div>' : "";
      results.hidden = !q.value.trim();
      return;
    }
    results.innerHTML = hits.map(function (h, i) {
      return '<a role="option" href="' + h.href + '" data-i="' + i + '"' + (i === sel ? ' class="sel"' : "") +
        ">" + h.html + "</a>";
    }).join("");
    results.hidden = false;
    var s = $(".sel", results);
    if (s) s.scrollIntoView({ block: "nearest" });
  }

  function choose(i) {
    var h = hits[i];
    if (!h) return;
    results.hidden = true; q.blur();
    if (h.go) go(h.go[0], h.go[1], h.go[2]); else location.href = h.href;
  }

  q.addEventListener("input", function () { hits = search(q.value); sel = hits.length ? 0 : -1; renderResults(); });
  q.addEventListener("keydown", function (e) {
    if (e.key === "ArrowDown") { sel = Math.min(sel + 1, hits.length - 1); renderResults(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { sel = Math.max(sel - 1, 0); renderResults(); e.preventDefault(); }
    else if (e.key === "Enter") { choose(sel); e.preventDefault(); }
    else if (e.key === "Escape") { results.hidden = true; q.blur(); }
  });
  q.addEventListener("focus", function () { if (q.value.trim()) renderResults(); });
  results.addEventListener("click", function (e) {
    var a = e.target.closest("a[data-i]");
    if (!a || e.metaKey || e.ctrlKey) return;
    e.preventDefault(); e.stopPropagation(); choose(+a.dataset.i);
  });
  document.addEventListener("mousedown", function (e) {
    if (!e.target.closest(".search")) results.hidden = true;
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "/" && document.activeElement !== q && !/INPUT|TEXTAREA/.test(document.activeElement.tagName)) {
      e.preventDefault(); q.focus(); q.select();
    } else if ((e.key === "j" || e.key === "k") && !/INPUT|TEXTAREA/.test(document.activeElement.tagName) &&
               !e.metaKey && !e.ctrlKey && NOTES.length) {
      step(e.key === "j" ? 1 : -1);
    } else if (e.key === "Escape") {
      hideTip(); body.classList.remove("tree-open"); body.classList.remove("panel-open");
    }
  });
})();
