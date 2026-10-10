/* SPDX-License-Identifier: GPL-3.0-or-later
   Copyright (c) 2026 Jyotiprakash Mishra. Based on "xv6, line by line" by Jyotiprakash Mishra
   (https://xv6.jyotiprakash.org); see NOTICE for the attribution term (GPLv3 section 7(b)). */
/* Extension labs: progressive hints and reveals, remembered in this browser (honour system). */
(function () {
  "use strict";
  var KEY = "xv6-labs-v1";
  function load() { try { return JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch (e) { return {}; } }
  function save(d) { try { localStorage.setItem(KEY, JSON.stringify(d)); } catch (e) {} }
  var lab = document.querySelector(".lab");
  if (!lab) return;
  var id = "lab" + lab.dataset.lab;
  var db = load(), st = db[id] || (db[id] = { h: {}, a: {}, w: {} });

  function showHints(card, n) {
    var hs = card.querySelectorAll(".hint");
    hs.forEach(function (h) { h.hidden = +h.dataset.h > n; });
    var b = card.querySelector(".nexthint");
    if (n >= hs.length) { b.hidden = true; } else { b.hidden = false; b.textContent = "Show hint " + (n + 1); }
  }
  document.querySelectorAll(".think").forEach(function (card) {
    var t = card.dataset.t;
    showHints(card, st.h[t] || 0);
    if (st.a[t]) { card.querySelector(".ans").hidden = false; card.querySelector(".showans").hidden = true; }
    card.querySelector(".nexthint").addEventListener("click", function () {
      st.h[t] = (st.h[t] || 0) + 1; save(db); showHints(card, st.h[t]);
    });
    card.querySelector(".showans").addEventListener("click", function () {
      st.a[t] = 1; save(db); card.querySelector(".ans").hidden = false; this.hidden = true;
    });
  });
  document.querySelectorAll(".bug").forEach(function (card) {
    var c = card.dataset.c;
    if (st.w[c]) { card.querySelector(".why").hidden = false; card.querySelector(".showwhy").hidden = true; }
    card.querySelector(".showwhy").addEventListener("click", function () {
      st.w[c] = 1; save(db); card.querySelector(".why").hidden = false; this.hidden = true;
    });
  });
})();
