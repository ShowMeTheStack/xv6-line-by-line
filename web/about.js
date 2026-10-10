/* About page: count-up stats and gentle reveal on scroll (skipped with reduced motion). */
(function () {
  "use strict";
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce || !("IntersectionObserver" in window)) return;
  var nums = Array.prototype.slice.call(document.querySelectorAll(".ab-stat b[data-n]"));
  nums.forEach(function (b) { b.textContent = "0" + (b.dataset.suffix || ""); });
  function count(b) {
    var n = +b.dataset.n, s = b.dataset.suffix || "", t0 = null;
    function step(t) {
      if (!t0) t0 = t;
      var k = Math.min(1, (t - t0) / 1400), e = 1 - Math.pow(1 - k, 3);
      b.textContent = Math.round(n * e) + s;
      if (k < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }
  var io = new IntersectionObserver(function (es) {
    es.forEach(function (e) {
      if (!e.isIntersecting) return;
      if (e.target.matches(".ab-stat b")) count(e.target); else e.target.classList.add("in");
      io.unobserve(e.target);
    });
  }, { threshold: 0.2 });
  nums.forEach(function (b) { io.observe(b); });
  document.querySelectorAll(".ab-sec, .ab-card, .ab-book, .ab-tool").forEach(function (el) {
    el.classList.add("ab-reveal"); io.observe(el);
  });
})();
