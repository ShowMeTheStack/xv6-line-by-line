/* SPDX-License-Identifier: GPL-3.0-or-later
   Copyright (c) 2026 Jyotiprakash Mishra. Based on "xv6, line by line" by Jyotiprakash Mishra
   (https://xv6.jyotiprakash.org); see NOTICE for the attribution term (GPLv3 section 7(b)). */
/* Test Yourself: grading, feedback and progress (kept in this browser only). */
(function () {
  "use strict";
  var KEY = "xv6-test-v1";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  function load() {
    try { return JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch (e) { return {}; }
  }
  function save(db) { try { localStorage.setItem(KEY, JSON.stringify(db)); } catch (e) {} }
  function record(id, ok) {
    var db = load(), r = db[id] || { n: 0 };
    if (r.n === 0) r.f = ok ? 1 : 0;
    r.l = ok ? 1 : 0; r.n += 1; r.t = Date.now();
    db[id] = r; save(db);
  }
  function decode(s) {
    var bin = atob(s), bytes = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return JSON.parse(new TextDecoder().decode(bytes));
  }
  function parseNum(s) {
    s = String(s).trim().toLowerCase().replace(/[_,\s]/g, "");
    if (!s) return null;
    var neg = s[0] === "-"; if (neg) s = s.slice(1);
    var v = null;
    if (/^0x[0-9a-f]+$/.test(s)) v = parseInt(s.slice(2), 16);
    else if (/^0b[01]+$/.test(s)) v = parseInt(s.slice(2), 2);
    else if (/^[0-9]+$/.test(s)) v = parseInt(s, 10);
    return v === null ? null : (neg ? -v : v);
  }

  function fbOk(text) {
    return '<div class="fb ok"><p class="fbh">✓ Correct.</p>' + text + "</div>";
  }
  function fbBad(mis, right) {
    return '<div class="fb bad"><p class="fbh">✗ Not quite.</p>' +
      (mis ? '<h4>How you might have thought about it</h4><div class="fbmis">' + mis + "</div>" : "") +
      '<h4>The right way to think about it</h4><div class="fbright">' + right + "</div></div>";
  }

  // ---- one question
  function setup(el) {
    var t = el.dataset.type, P = null, picked = [];
    function pay() { if (!P) P = decode(el.dataset.k); return P; }
    var btn = $(".qcheck", el), retry = $(".qretry", el), fb = $(".qfb", el);

    if (t === "line") {
      $$(".qcode .l", el).forEach(function (l) {
        var a = $(".n2", l);
        var n = a ? parseInt(a.textContent, 10) : 0;
        l.dataset.n = n; l.classList.add("pickable"); l.tabIndex = 0;
        function pick(ev) {
          if (ev) ev.preventDefault();
          if (el.classList.contains("done")) return;
          $$(".qcode .l.picked", el).forEach(function (x) { x.classList.remove("picked"); });
          l.classList.add("picked"); picked = [n];
          $(".qpicked", el).textContent = "line " + n;
        }
        l.addEventListener("click", pick);
        l.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") pick(e); });
      });
    }
    if (t === "order") {
      el.addEventListener("click", function (e) {
        var b = e.target.closest(".qup, .qdn");
        if (!b || el.classList.contains("done")) return;
        var li = b.closest("li"), ol = li.parentNode;
        if (b.classList.contains("qup") && li.previousElementSibling) ol.insertBefore(li, li.previousElementSibling);
        if (b.classList.contains("qdn") && li.nextElementSibling) ol.insertBefore(li.nextElementSibling, li);
        b.focus();
      });
    }

    function finish(ok, html) {
      fb.innerHTML = html; fb.hidden = false;
      el.classList.add("done"); el.classList.toggle("ok", ok); el.classList.toggle("bad", !ok);
      $$("input, select", el).forEach(function (x) { x.disabled = true; });
      btn.hidden = true; retry.hidden = false;
      record(el.dataset.id, ok); status(el); refresh();
    }
    function need(msg) {
      fb.innerHTML = '<div class="fb need">' + msg + "</div>"; fb.hidden = false;
    }

    btn.addEventListener("click", function () {
      var p = pay(), ex = p.ex || "";
      if (t === "choice") {
        var c = $("input:checked", el);
        if (!c) return need("Choose an answer first.");
        var j = +c.value, o = p.o[j], ci = p.o.findIndex(function (x) { return x.c; });
        mark(el, ".qopt", function (i) { return p.o[i].c; }, [j]);
        return o.c ? finish(true, fbOk(o.w + ex))
          : finish(false, fbBad(o.w, "<p><b>The answer:</b> " + p.o[ci].x + "</p>" + p.o[ci].w + ex));
      }
      if (t === "multi") {
        var sel = $$("input:checked", el).map(function (x) { return +x.value; });
        if (!sel.length) return need("Tick at least one answer first.");
        var mis = [], okAll = true;
        p.o.forEach(function (o, i) {
          var s = sel.indexOf(i) >= 0;
          if (s !== o.c) {
            okAll = false;
            mis.push("<p><b>" + (s ? "You ticked: " : "You left out: ") + "</b>" + o.x + "</p>" + o.w);
          }
        });
        mark(el, ".qopt", function (i) { return p.o[i].c; }, sel);
        var right = "<p><b>The answer:</b> " + p.o.filter(function (o) { return o.c; })
          .map(function (o) { return o.x; }).join("; ") + "</p>" + ex;
        return okAll ? finish(true, fbOk(ex)) : finish(false, fbBad(mis.join(""), right));
      }
      if (t === "number") {
        var raw = $(".qnum input", el).value, v = parseNum(raw);
        if (v === null) return need("Type a whole number: decimal, 0x hex or 0b binary.");
        if (p.a.indexOf(v) >= 0) return finish(true, fbOk(ex));
        return finish(false, fbBad(p.wr[String(v)] || p.g, "<p><b>The answer:</b> " + p.as + "</p>" + ex));
      }
      if (t === "order") {
        var cur = $$(".qorder li", el).map(function (li) { return +li.dataset.i; });
        var bad = cur.findIndex(function (x, i) { return x !== i; });
        $$(".qorder li", el).forEach(function (li, i) { li.classList.add(+li.dataset.i === i ? "right" : "wrong"); });
        var corr = "<ol class=\"qcorr\">" + p.x.map(function (x) { return "<li>" + x + "</li>"; }).join("") + "</ol>";
        if (bad < 0) return finish(true, fbOk(ex));
        var item = cur[bad];
        return finish(false, fbBad("<p><b>First out of place:</b> " + p.x[item] + "</p>" + (p.w[item] || p.g),
          "<p><b>The correct order:</b></p>" + corr + ex));
      }
      if (t === "line") {
        if (!picked.length) return need("Click a line in the code first.");
        var n = picked[0];
        $$(".qcode .l", el).forEach(function (l) {
          if (p.a.indexOf(+l.dataset.n) >= 0) l.classList.add("right");
        });
        if (p.a.indexOf(n) >= 0) return finish(true, fbOk(ex));
        $$(".qcode .l.picked", el).forEach(function (l) { l.classList.add("wrong"); });
        return finish(false, fbBad(p.wl[String(n)] || p.g,
          "<p><b>The answer:</b> line " + p.a.join(" or ") + "</p>" + ex));
      }
      if (t === "state" || t === "bits") {
        var sels = $$(".qfield select", el);
        if (sels.some(function (s) { return !s.value; })) return need("Choose a value for every field first.");
        var wrong = [];
        sels.forEach(function (s, i) {
          var f = p.f[i], ok = f.a === "*" || s.value === f.a;
          s.closest(".qfield").classList.add(ok ? "right" : "wrong");
          if (!ok) wrong.push("<p><b>" + f.l + ":</b> you chose " + esc(s.options[s.selectedIndex].text) +
            ", but it is <b>" + esc(f.d) + "</b>.</p>" + (f.w || ""));
        });
        var notes = p.f.filter(function (f) { return f.n; }).map(function (f) { return f.n; }).join("");
        if (!wrong.length) return finish(true, fbOk(notes + ex));
        return finish(false, fbBad(wrong.join("") + (p.g || ""), notes + ex));
      }
      if (t === "match") {
        var ms = $$(".qfield select", el);
        if (ms.some(function (s) { return !s.value; })) return need("Match every item first.");
        var wr = [];
        ms.forEach(function (s, i) {
          var ok = s.value === p.a[i];
          s.closest(".qfield").classList.add(ok ? "right" : "wrong");
          if (!ok) wr.push("<p><b>" + p.l[i] + "</b> goes with <b>" + p.x[i] + "</b>, not " +
            esc(s.options[s.selectedIndex].text) + ".</p>" + p.w[i]);
        });
        if (!wr.length) return finish(true, fbOk(ex));
        return finish(false, fbBad(wr.join(""), ex));
      }
      if (t === "tf") {
        var tf = $(".qtf input:checked", el), rs = $(".qreasons input:checked", el);
        if (!tf || !rs) return need("Choose True or False, and a reason.");
        var tv = tf.value === "1", rj = +rs.value, r = p.r[rj];
        var cr = p.r.find(function (x) { return x.c; });
        mark(el, ".qreasons .qopt", function (i) { return p.r[i].c; }, [rj]);
        var right = "<p><b>The answer:</b> " + (p.a ? "True" : "False") + ", because " + cr.x + "</p>" + cr.w + ex;
        if (tv === p.a && r.c) return finish(true, fbOk(cr.w + ex));
        var mis = (tv !== p.a ? p.wtf : "") + (!r.c ? r.w : "");
        if (tv === p.a && !r.c) mis = "<p>True/false was right, but not the reason.</p>" + mis;
        return finish(false, fbBad(mis, right));
      }
    });

    retry.addEventListener("click", function () {
      el.classList.remove("done", "ok", "bad");
      $$("input, select", el).forEach(function (x) {
        x.disabled = false; if (x.type === "radio" || x.type === "checkbox") x.checked = false;
        else if (x.tagName === "SELECT") x.value = ""; else x.value = "";
      });
      $$(".right, .wrong, .picked", el).forEach(function (x) { x.classList.remove("right", "wrong", "picked"); });
      picked = []; var pk = $(".qpicked", el); if (pk) pk.textContent = "none yet";
      fb.hidden = true; fb.innerHTML = ""; btn.hidden = false; retry.hidden = true;
    });
    status(el);
  }

  function mark(el, sel, isRight, chosen) {
    $$(sel, el).forEach(function (lab, i) {
      if (isRight(i)) lab.classList.add("right");
      else if (chosen.indexOf(i) >= 0) lab.classList.add("wrong");
    });
  }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }

  function status(el) {
    var r = load()[el.dataset.id], s = $(".qstatus", el);
    if (!s) return;
    el.classList.toggle("was-ok", !!(r && r.l)); el.classList.toggle("was-bad", !!(r && !r.l));
    s.textContent = !r ? "" : r.l ? (r.f ? "✓ right first time" : "✓ right on a later try") : "✗ wrong last time";
  }

  // ---- page-level
  var FILTER = "all";
  function refresh() {
    var db = load();
    var list = $$(".qlist:not(.quick) .qz");
    if (list.length) {
      var ans = list.filter(function (q) { return db[q.dataset.id]; });
      var first = ans.filter(function (q) { return db[q.dataset.id].f; });
      var sc = $(".qscore"); if (sc) sc.textContent = "Answered " + ans.length + " of " + list.length +
        " · right first time: " + first.length;
      list.forEach(function (q) {
        var r = db[q.dataset.id];
        q.hidden = FILTER === "todo" ? !!r : FILTER === "wrong" ? !(r && !r.l) : false;
      });
    }
    $$(".qcard").forEach(function (c) {
      var ids = c.dataset.ids.split(" "), n = 0, f = 0;
      ids.forEach(function (id) { if (db[id]) { n++; if (db[id].f) f++; } });
      var pg = $(".qprog", c);
      if (pg) pg.textContent = n ? n + " answered · " + f + " right first time" : "not started";
      c.classList.toggle("started", n > 0); c.classList.toggle("complete", n === ids.length);
    });
    var tot = $(".qtotal");
    if (tot) {
      var all = Object.keys(db).length, ff = Object.keys(db).filter(function (k) { return db[k].f; }).length;
      tot.textContent = all ? "Answered " + all + " of " + tot.dataset.total + " · right first time: " + ff : "";
    }
    var quick = $(".qlist.quick");
    if (quick) {
      var shown = $$(".qwrap:not([hidden]) .qz", quick);
      var done = shown.filter(function (q) { return q.classList.contains("done"); });
      var good = done.filter(function (q) { return q.classList.contains("ok"); });
      var qs = $(".qscore"); if (qs) qs.textContent = done.length + " of " + shown.length + " answered · " + good.length + " right";
    }
  }

  function pickQuick() {
    var quick = $(".qlist.quick"); if (!quick) return;
    var db = load();
    var all = $$(".qwrap", quick);
    all.forEach(function (w) { w.hidden = true; var r = $(".qretry", w); if (r && !r.hidden) r.click(); });
    function rank(w) { var r = db[$(".qz", w).dataset.id]; return !r ? 0 : !r.l ? 1 : 2; }
    var shuffled = all.map(function (w) { return [rank(w), Math.random(), w]; })
      .sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; }).slice(0, 10).map(function (x) { return x[2]; });
    shuffled.forEach(function (w, i) {
      w.hidden = false; quick.appendChild(w);
      var n = $(".qn", w); if (n) n.textContent = i + 1;
      if (!$(".qfrom", w)) $(".qh", w).insertAdjacentHTML("beforeend",
        '<a class="qfrom" href="' + w.dataset.href + '">' + esc(w.dataset.cat) + "</a>");
    });
    refresh(); window.scrollTo(0, 0);
  }

  document.addEventListener("DOMContentLoaded", function () {
    $$(".qz").forEach(setup);
    $$(".qfilter [data-f]").forEach(function (b) {
      b.addEventListener("click", function () {
        FILTER = b.dataset.f;
        $$(".qfilter [data-f]").forEach(function (x) { x.classList.toggle("on", x === b); });
        refresh();
      });
    });
    var rc = $(".qreset");
    if (rc) rc.addEventListener("click", function () {
      if (!confirm("Forget your answers in this category?")) return;
      var db = load(); $$(".qz").forEach(function (q) { delete db[q.dataset.id]; }); save(db);
      $$(".qz").forEach(function (q) { var r = $(".qretry", q); if (!r.hidden) r.click(); status(q); });
      refresh();
    });
    var ra = $(".qresetall");
    if (ra) ra.addEventListener("click", function () {
      if (!confirm("Forget all your Test Yourself answers?")) return;
      save({}); refresh();
    });
    var nw = $(".qnew"); if (nw) nw.addEventListener("click", pickQuick);
    pickQuick();
    refresh();
    if (location.hash) { var t = document.getElementById(location.hash.slice(1)); if (t) t.scrollIntoView(); }
  });
})();
