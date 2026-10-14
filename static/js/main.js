/* SK STORE — interactions */
(function () {
  "use strict";

  /* ---- hero letter stagger ---- */
  document.querySelectorAll(".hero-title").forEach(function (el) {
    var text = el.textContent;
    el.textContent = "";
    Array.prototype.forEach.call(text, function (ch, i) {
      var s = document.createElement("span");
      s.className = "ch";
      s.textContent = ch === " " ? "\u00a0" : ch;
      s.style.animationDelay = (i * 0.06) + "s";
      el.appendChild(s);
    });
  });

  /* ---- reveal on scroll (staggered) ---- */
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
    });
  }, { threshold: 0.08 });
  document.querySelectorAll(".reveal").forEach(function (el, i) {
    el.style.transitionDelay = ((i % 8) * 0.06) + "s";
    io.observe(el);
  });

  /* ---- 3D tilt on product cards ---- */
  if (window.matchMedia("(hover: hover)").matches) {
    document.querySelectorAll(".card").forEach(function (card) {
      card.addEventListener("mousemove", function (e) {
        var r = card.getBoundingClientRect();
        var x = (e.clientX - r.left) / r.width - 0.5;
        var y = (e.clientY - r.top) / r.height - 0.5;
        card.classList.add("tilting");
        card.style.transform = "translateY(-8px) perspective(700px) rotateY(" + (x * 10) + "deg) rotateX(" + (-y * 10) + "deg)";
      });
      card.addEventListener("mouseleave", function () {
        card.classList.remove("tilting");
        card.style.transform = "";
      });
    });
  }

  /* ---- top banner carousel (5s Ken Burns) ---- */
  document.querySelectorAll(".carousel").forEach(function (car) {
    var slides = Array.prototype.slice.call(car.querySelectorAll(".slide"));
    var dotsBox = car.querySelector(".dots");
    if (slides.length < 2 || !dotsBox) return;
    var idx = 0, timer = null;
    slides.forEach(function (_, i) {
      var d = document.createElement("button");
      d.setAttribute("aria-label", "banner " + (i + 1));
      d.addEventListener("click", function () { show(i); restart(); });
      dotsBox.appendChild(d);
    });
    var dots = Array.prototype.slice.call(dotsBox.children);
    function show(i) {
      idx = (i + slides.length) % slides.length;
      slides.forEach(function (s, k) { s.classList.toggle("on", k === idx); });
      dots.forEach(function (d, k) { d.classList.toggle("on", k === idx); });
    }
    function restart() { clearInterval(timer); timer = setInterval(function () { show(idx + 1); }, 5000); }
    car.addEventListener("mouseenter", function () { clearInterval(timer); });
    car.addEventListener("mouseleave", restart);
    show(0); restart();
  });

  /* ---- product gallery ---- */
  document.querySelectorAll("[data-gallery]").forEach(function (gal) {
    var imgs;
    try { imgs = JSON.parse(gal.getAttribute("data-images") || "[]"); } catch (e) { imgs = []; }
    if (!imgs.length) return;
    var n = imgs.length, idx = 0;
    var main = gal.querySelector(".gallery-main img");
    var count = gal.querySelector(".g-count");
    var thumbs = Array.prototype.slice.call(gal.querySelectorAll(".g-thumbs img"));
    var timer = null;
    function stop() { if (timer) { clearInterval(timer); timer = null; } }
    function start() { stop(); if (n > 1) timer = setInterval(function () { show(idx + 1); }, 4000); }
    function show(i) {
      idx = (i + n) % n;
      main.style.transform = "scale(1)";
      main.src = imgs[idx];
      if (count) count.textContent = (idx + 1) + " / " + n;
      thumbs.forEach(function (t, k) { t.classList.toggle("on", k === idx); });
      start();
    }
    var prev = gal.querySelector(".g-prev"), next = gal.querySelector(".g-next");
    if (prev) prev.addEventListener("click", function (e) { e.stopPropagation(); show(idx - 1); });
    if (next) next.addEventListener("click", function (e) { e.stopPropagation(); show(idx + 1); });
    thumbs.forEach(function (t, k) { t.addEventListener("click", function () { show(k); }); });
    imgs.forEach(function (u) { var im = new Image(); im.src = u; });
    var wrap = gal.querySelector(".gallery-main");
    wrap.addEventListener("mousemove", function (e) {
      var r = wrap.getBoundingClientRect();
      var x = ((e.clientX - r.left) / r.width) * 100;
      var y = ((e.clientY - r.top) / r.height) * 100;
      main.style.transformOrigin = x + "% " + y + "%";
      main.style.transform = "scale(1.9)";
    });
    wrap.addEventListener("mouseenter", stop);
    wrap.addEventListener("mouseleave", function () { main.style.transform = "scale(1)"; start(); });
    /* touch swipe */
    var sx = 0;
    wrap.addEventListener("touchstart", function (e) { sx = e.touches[0].clientX; }, { passive: true });
    wrap.addEventListener("touchend", function (e) {
      var dx = e.changedTouches[0].clientX - sx;
      if (Math.abs(dx) > 40) show(idx + (dx < 0 ? 1 : -1));
    }, { passive: true });
    show(0);
  });

  /* ---- star rating input (click = select, required) ---- */
  document.querySelectorAll(".star-input").forEach(function (box) {
    var hidden = document.getElementById(box.getAttribute("data-target"));
    var stars = Array.prototype.slice.call(box.querySelectorAll("span"));
    function paint(v) {
      stars.forEach(function (s) {
        s.classList.toggle("lit", parseInt(s.getAttribute("data-v"), 10) <= v);
      });
    }
    stars.forEach(function (s) {
      s.addEventListener("click", function () {
        var v = parseInt(s.getAttribute("data-v"), 10);
        if (hidden) hidden.value = v;
        paint(v);
      });
      s.addEventListener("mouseenter", function () { paint(parseInt(s.getAttribute("data-v"), 10)); });
    });
    box.addEventListener("mouseleave", function () { paint(parseInt((hidden && hidden.value) || 0, 10)); });
  });

  /* ---- admin: live profit preview ---- */
  var profitBox = document.getElementById("profit-live");
  if (profitBox) {
    var f = function (id) { return parseFloat((document.getElementById(id) || {}).value || 0) || 0; };
    function upd() {
      var sp = f("f_discount") > 0 ? f("f_discount") : f("f_price");
      var profit = sp - f("f_buy") - f("f_dexp") - f("f_pexp");
      var codPct = parseFloat(profitBox.getAttribute("data-cod-pct") || 0) || 0;
      var dfee = parseFloat(profitBox.getAttribute("data-delivery-fee") || 0) || 0;
      var codFee = (sp + dfee) * codPct / 100;
      var net = profit - codFee;
      var txt = "💰 Profit per unit: Rs " + Math.round(profit).toLocaleString() +
        "  (sale " + Math.round(sp).toLocaleString() + " − buy − delivery − packing)";
      if (codPct > 0) {
        txt += "  · After " + codPct + "% COD fee (−Rs " + Math.round(codFee).toLocaleString() + "): Rs " + Math.round(net).toLocaleString();
      }
      if (net < 0) txt = "⚠️ Loss per unit" + (codPct > 0 ? " after COD fee" : "") + ": Rs " + Math.round(net).toLocaleString() + " — check your pricing!";
      profitBox.textContent = txt;
      profitBox.className = "profit-live " + (net >= 0 ? "profit-pos" : "profit-neg");
    }
    ["f_price", "f_discount", "f_buy", "f_dexp", "f_pexp"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.addEventListener("input", upd);
    });
    upd();
  }

  /* ---- admin: video source toggle ---- */
  document.querySelectorAll('input[name="video_choice"]').forEach(function (r) {
    r.addEventListener("change", toggleVideo);
  });
  function toggleVideo() {
    var sel = document.querySelector('input[name="video_choice"]:checked');
    var v = sel ? sel.value : "none";
    var up = document.getElementById("video_upload_wrap");
    var yt = document.getElementById("video_yt_wrap");
    if (up) up.style.display = v === "upload" ? "" : "none";
    if (yt) yt.style.display = v === "youtube" ? "" : "none";
  }
  toggleVideo();

  /* ---- admin: new category toggle ---- */
  var catSel = document.getElementById("f_category");
  function toggleCat() {
    var w = document.getElementById("new_cat_wrap");
    if (w) w.style.display = catSel && catSel.value === "__new__" ? "" : "none";
  }
  if (catSel) { catSel.addEventListener("change", toggleCat); toggleCat(); }

  /* ---- review form: rating required ---- */
  document.querySelectorAll('form[data-needs-rating]').forEach(function (form) {
    form.addEventListener("submit", function (e) {
      var h = form.querySelector('input[name="rating"]');
      if (!h || !parseInt(h.value || 0, 10)) {
        e.preventDefault();
        alert("⭐ Please tap the stars to select a rating first.");
      }
    });
  });
})();

/* ---- toast ---- */
function showToast(msg, isErr, withCartLink) {
  var box = document.getElementById("toastBox");
  if (!box) { alert(msg); return; }
  var t = document.createElement("div");
  t.className = "toast" + (isErr ? " err" : "");
  var span = document.createElement("span");
  span.textContent = msg;
  t.appendChild(span);
  if (withCartLink && !isErr) {
    var a = document.createElement("a");
    a.href = "/cart"; a.className = "toast-cart-link"; a.textContent = "View Cart \u2192";
    t.appendChild(a);
  }
  box.appendChild(t);
  requestAnimationFrame(function () { t.classList.add("show"); });
  setTimeout(function () {
    t.classList.remove("show");
    setTimeout(function () { t.remove(); }, 350);
  }, 3200);
}

/* ---- AJAX add-to-cart (no page refresh) ---- */
document.addEventListener("DOMContentLoaded", function () {
  var form = document.getElementById("addForm");
  if (!form) return;
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var fd = new FormData(form);
    fetch(form.getAttribute("action"), {
      method: "POST",
      body: fd,
      headers: { "X-Requested-With": "XMLHttpRequest" }
    }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
    .then(function (res) {
      if (res.ok && res.d.success) {
        showToast(res.d.message, false, true);
        var badge = document.querySelector(".cart-badge");
        var link = document.querySelector('a[href*="cart"]');
        if (typeof res.d.cart_count === "number") {
          if (badge) { badge.textContent = res.d.cart_count;
            badge.classList.remove("pop"); void badge.offsetWidth; badge.classList.add("pop"); }
          else if (link && res.d.cart_count > 0) {
            var s = document.createElement("span");
            s.className = "cart-badge"; s.textContent = res.d.cart_count;
            link.appendChild(s);
          }
        }
      } else {
        showToast(res.d.message || "Could not add to cart.", true);
      }
    }).catch(function () { showToast("Network error. Please try again.", true); });
  });
});

// ---- Admin product form: IDM-style upload progress (XHR) ----
(function () {
  var form = document.getElementById("product-form");
  if (!form || !window.XMLHttpRequest || !window.FormData) return;
  var panel = document.getElementById("upload-progress");
  var fill = document.getElementById("up-fill");
  var pctEl = document.getElementById("up-pct");
  var mbEl = document.getElementById("up-mb");
  var totalEl = document.getElementById("up-total");
  var speedEl = document.getElementById("up-speed");
  var msgEl = document.getElementById("up-msg");
  var titleEl = document.getElementById("up-title");
  var btn = document.getElementById("product-save-btn");
  if (!panel || !fill) return;

  function fmtMB(bytes) { return (bytes / 1048576).toFixed(1) + " MB"; }
  function fmtSpeed(bps) {
    if (bps <= 0) return "—";
    if (bps >= 1048576) return (bps / 1048576).toFixed(1) + " MB/s";
    return Math.round(bps / 1024) + " KB/s";
  }

  form.addEventListener("submit", function (e) {
    var files = form.querySelectorAll('input[type="file"]');
    var hasFiles = false;
    files.forEach(function (inp) { if (inp.files && inp.files.length) hasFiles = true; });
    e.preventDefault();
    if (hasFiles) { panel.style.display = "block"; titleEl.textContent = "Uploading product…"; }
    if (msgEl) msgEl.textContent = "";
    if (btn) { btn.disabled = true; btn.textContent = "⏳ Saving…"; }
    var fd = new FormData(form);
    var xhr = new XMLHttpRequest();
    var start = Date.now();
    xhr.open("POST", form.action || window.location.href, true);
    xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
    xhr.upload.onprogress = function (ev) {
      if (!ev.lengthComputable) return;
      var pct = Math.round((ev.loaded / ev.total) * 100);
      fill.style.width = pct + "%";
      pctEl.textContent = pct + "%";
      mbEl.textContent = fmtMB(ev.loaded);
      totalEl.textContent = fmtMB(ev.total);
      var secs = (Date.now() - start) / 1000;
      speedEl.textContent = secs > 0 ? fmtSpeed(ev.loaded / secs) : "—";
      if (pct >= 100) titleEl.textContent = "Finishing up… (server is saving)";
    };
    xhr.onload = function () {
      if (btn) { btn.disabled = false; btn.textContent = "💾 Save Product"; }
      // Server redirects to the product list on success; XHR follows it.
      if (xhr.status >= 200 && xhr.status < 300) {
        if (xhr.responseURL && xhr.responseURL !== window.location.href) {
          window.location.href = xhr.responseURL;
          return;
        }
        // No redirect = validation errors re-rendered. Surface the flashes.
        try {
          var doc = new DOMParser().parseFromString(xhr.responseText, "text/html");
          var flashes = doc.querySelectorAll(".flash");
          if (flashes.length) {
            panel.style.display = "none";
            var box = document.createElement("div");
            flashes.forEach(function (f) { box.appendChild(f.cloneNode(true)); });
            form.parentNode.insertBefore(box, form);
            window.scrollTo({ top: 0, behavior: "smooth" });
            return;
          }
        } catch (err) { /* fall through */ }
        window.location.reload();
      } else {
        panel.style.display = "none";
        if (msgEl) msgEl.textContent = "Upload failed (server error). Please try again.";
      }
    };
    xhr.onerror = function () {
      if (btn) { btn.disabled = false; btn.textContent = "💾 Save Product"; }
      panel.style.display = "none";
      if (msgEl) msgEl.textContent = "Network error — upload did not complete. Please try again.";
    };
    xhr.send(fd);
  });
})();
