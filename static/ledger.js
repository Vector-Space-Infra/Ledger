// Index filters: status chips plus thesis and horizon-year selects. The table reads fully with
// JavaScript off; this only hides rows. Nothing is stored.
(function () {
  var box = document.querySelector("[data-filters]");
  var table = document.querySelector("[data-calls]");
  if (!box || !table) return;
  var rows = Array.prototype.slice.call(table.querySelectorAll("tbody tr[data-status]"));
  var empty = document.querySelector("[data-empty]");
  var state = { status: "", thesis: "", year: "" };

  function apply() {
    var shown = 0;
    rows.forEach(function (r) {
      var ok = (!state.status || r.getAttribute("data-status") === state.status) &&
               (!state.thesis || r.getAttribute("data-thesis") === state.thesis) &&
               (!state.year || r.getAttribute("data-year") === state.year);
      if (ok) { r.removeAttribute("hidden"); shown++; } else { r.setAttribute("hidden", ""); }
    });
    if (empty) { if (shown) empty.setAttribute("hidden", ""); else empty.removeAttribute("hidden"); }
  }

  box.querySelectorAll("button[data-filter]").forEach(function (b) {
    b.addEventListener("click", function () {
      var group = b.parentNode;
      group.querySelectorAll("button").forEach(function (x) { x.classList.remove("is-active"); });
      b.classList.add("is-active");
      state[b.getAttribute("data-filter")] = b.getAttribute("data-value");
      apply();
    });
  });
  box.querySelectorAll("select[data-filter]").forEach(function (s) {
    s.addEventListener("change", function () {
      state[s.getAttribute("data-filter")] = s.value;
      apply();
    });
  });
})();
