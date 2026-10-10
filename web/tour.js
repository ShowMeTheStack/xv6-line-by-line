/* SPDX-License-Identifier: GPL-3.0-or-later
   Copyright (c) 2026 Jyotiprakash Mishra. Based on "xv6, line by line" by Jyotiprakash Mishra
   (https://xv6.jyotiprakash.org); see NOTICE for the attribution term (GPLv3 section 7(b)). */
// Guided-tour player and the tours index (completion marks).
(function () {
  "use strict";
  function $(s, el) { return (el || document).querySelector(s); }
  function $$(s, el) { return Array.prototype.slice.call((el || document).querySelectorAll(s)); }
  function load(k) { try { return JSON.parse(localStorage.getItem(k) || "null"); } catch (e) { return null; } }
  function save(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }

  var done = load("tours-done") || {};

  // ---------------------------------------------------------- index pages
  $$("[data-tour]").forEach(function (el) {
    if (el.classList.contains("tour")) return;
    if (done[el.dataset.tour]) el.classList.add("is-done");
  });

  // ---------------------------------------------------------- player
  var tour = $(".tour");
  if (!tour) return;
  var num = tour.dataset.tour;
  var steps = $$(".tstep", tour);
  var segs = $$(".seg", tour);
  var count = $(".count", tour);
  var last = steps.length - 1;
  var cur = -1;

  function show(i, focus) {
    i = Math.max(0, Math.min(last, i));
    if (i === cur) return;
    var dir = i > cur ? "fwd" : "back";
    steps.forEach(function (s, k) {
      s.hidden = k !== i;
      s.classList.remove("enter-fwd", "enter-back");
    });
    var s = steps[i];
    void s.offsetWidth;
    if (cur >= 0) s.classList.add("enter-" + dir);
    segs.forEach(function (g, k) {
      g.classList.toggle("past", k < i);
      g.classList.toggle("now", k === i);
      g.setAttribute("aria-selected", String(k === i));
    });
    count.textContent = i === 0 ? "Introduction" : i === last ? "Wrap-up" : "Step " + i + " of " + (last - 1);
    cur = i;
    var h = i === 0 ? location.pathname : "#step-" + i;
    if ((i === 0 && location.hash) || (i > 0 && location.hash !== h)) history.replaceState(null, "", h);
    requestAnimationFrame(function () { window.scrollTo(0, 0); });
    window.scrollTo(0, 0);
    var stage = $(".tstage", tour);
    if (stage) stage.scrollTop = 0;
    // Bring the focus lines of the excerpt into view.
    var code = $(".excerpt", s);
    var fx = code && $(".l.fx", code);
    if (fx) code.scrollTop = Math.max(0, fx.offsetTop - code.offsetTop - 40);
    if (focus !== false) { var h2 = $("h1, h2", s); if (h2) { h2.setAttribute("tabindex", "-1"); h2.focus({ preventScroll: true }); } }
    var prog = load("tour-pos") || {};
    prog[num] = i; save("tour-pos", prog);
    if (i === last && !done[num]) { done[num] = 1; save("tours-done", done); }
  }

  tour.addEventListener("click", function (e) {
    var b = e.target.closest("[data-go], [data-step]");
    if (!b || !tour.contains(b)) return;
    e.preventDefault();
    if (b.dataset.go != null) show(+b.dataset.go);
    else show(cur + (+b.dataset.step));
  });

  document.addEventListener("keydown", function (e) {
    if (/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === "ArrowRight" || e.key === "PageDown") { show(cur + 1); e.preventDefault(); }
    else if (e.key === "ArrowLeft" || e.key === "PageUp") { show(cur - 1); e.preventDefault(); }
    else if (e.key === "Home") { show(0); e.preventDefault(); }
    else if (e.key === "End") { show(last); e.preventDefault(); }
  });

  // Swipe on touch screens.
  var x0 = null;
  tour.addEventListener("touchstart", function (e) { x0 = e.touches[0].clientX; }, { passive: true });
  tour.addEventListener("touchend", function (e) {
    if (x0 == null) return;
    var dx = e.changedTouches[0].clientX - x0; x0 = null;
    if (Math.abs(dx) > 70 && !e.target.closest(".excerpt")) show(cur + (dx < 0 ? 1 : -1));
  });

  function fromHash() {
    var m = /^#step-(\d+)$/.exec(location.hash);
    return m ? +m[1] : 0;
  }
  // Offer to resume where the reader left off.
  var saved = (load("tour-pos") || {})[num];
  if (saved > 0 && saved < last && !/^#step-/.test(location.hash)) {
    var start = $(".intro .btn.big", tour);
    if (start) start.insertAdjacentHTML("afterend",
      ' <button class="btn big resume" data-go="' + saved + '">Resume at step ' + saved + "</button>");
  }
  window.addEventListener("hashchange", function () { show(fromHash()); });
  show(fromHash(), false);
})();
