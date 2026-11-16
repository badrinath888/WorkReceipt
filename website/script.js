(function () {
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
  var nav = document.getElementById('nav');
  var toggle = document.getElementById('navToggle');
  var menu = document.getElementById('navMenu');

  // mobile menu
  function setMenu(open) {
    menu.classList.toggle('open', open);
    toggle.setAttribute('aria-expanded', open);
    toggle.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
    toggle.querySelector('use').setAttribute('href', open ? '#i-x' : '#i-menu');
  }
  toggle.addEventListener('click', function () { setMenu(!menu.classList.contains('open')); });
  menu.addEventListener('click', function (e) { if (e.target.closest('a')) setMenu(false); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && menu.classList.contains('open')) { setMenu(false); toggle.focus(); } });
  document.addEventListener('click', function (e) { if (!nav.contains(e.target)) setMenu(false); });

  // current section in nav (homepage only)
  var ids = ['features', 'how', 'privacy', 'pricing'];
  var links = [].slice.call(document.querySelectorAll('.nav__links a, .nav__menu a:not(.btn)'));
  if (document.getElementById('features')) {
    var spy = function () {
      var y = window.scrollY + 160, cur = null;
      ids.forEach(function (id) { var s = document.getElementById(id); if (s && s.offsetTop <= y) cur = id; });
      var dl = document.getElementById('download'); if (dl && dl.offsetTop <= y) cur = null;
      links.forEach(function (a) {
        if (a.getAttribute('aria-current') === 'page') return;
        if (cur && a.getAttribute('href') === '#' + cur) a.setAttribute('aria-current', 'true'); else a.removeAttribute('aria-current');
      });
    };
    window.addEventListener('scroll', spy, { passive: true }); spy();
  }

  // walkthrough tabs (WAI-ARIA tabs, vertical). Panels share one grid cell, so nothing moves on change.
  var tabs = [].slice.call(document.querySelectorAll('[role=tab]'));
  function select(tab, focus) {
    tabs.forEach(function (t) {
      var on = t === tab;
      t.setAttribute('aria-selected', on); t.tabIndex = on ? 0 : -1;
      document.getElementById(t.getAttribute('aria-controls')).classList.toggle('is-active', on);
    });
    if (focus) tab.focus();
    var lazy = document.querySelector('#' + tab.getAttribute('aria-controls') + ' img[loading=lazy]');
    if (lazy) lazy.loading = 'eager';
  }
  tabs.forEach(function (t, i) {
    t.addEventListener('click', function () { select(t); });
    t.addEventListener('keydown', function (e) {
      var n = null;
      if (e.key === 'ArrowDown' || e.key === 'ArrowRight') n = tabs[(i + 1) % tabs.length];
      if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') n = tabs[(i - 1 + tabs.length) % tabs.length];
      if (e.key === 'Home') n = tabs[0];
      if (e.key === 'End') n = tabs[tabs.length - 1];
      if (n) { e.preventDefault(); select(n, true); }
    });
  });

  // full-screen screenshot viewer (shown on small screens, where the preview is a zoomed crop)
  var viewer = document.getElementById('viewer');
  if (viewer) {
    var vImg = document.getElementById('viewerImg'), vTitle = document.getElementById('viewerTitle');
    var opener = null;
    [].forEach.call(document.querySelectorAll('.show__zoom'), function (b) {
      b.addEventListener('click', function () {
        opener = b;
        vImg.src = b.dataset.full; vImg.alt = b.dataset.title + ' screen, full size, synthetic data';
        vTitle.textContent = b.dataset.title;
        viewer.showModal();
        viewer.querySelector('.viewer__scroll').scrollTo(0, 0);
      });
    });
    document.getElementById('viewerClose').addEventListener('click', function () { viewer.close(); });
    viewer.addEventListener('click', function (e) { if (e.target === viewer) viewer.close(); });
    viewer.addEventListener('close', function () { if (opener) opener.focus(); });
  }

  // redaction demo (synthetic strings; the mask format is the one the app shows)
  var box = document.getElementById('maskBox'), note = document.getElementById('maskNote');
  if (box && note) {
    var views = {
      raw: {
        html: 'Add CSV export for orders on the admin page. Use AWS key <mark>AKIAIOSFODNN7EXAMPLE</mark> for the S3 upload. Contact: <mark>dev@example.com</mark>',
        note: 'What you typed in Claude Code. Both values are made-up examples.'
      },
      out: {
        html: 'Add CSV export for orders on the admin page. Use AWS key <mark class="safe">[REDACTED:aws-key]</mark> for the S3 upload. Contact: <mark class="safe">[REDACTED:email]</mark>',
        note: 'What the report keeps. A masked key counts as high severity, so export waits until you have reviewed it.'
      }
    };
    var seg = [].slice.call(document.querySelectorAll('.mask__seg button'));
    var show = function (v) {
      seg.forEach(function (b) { b.setAttribute('aria-pressed', b.dataset.view === v); });
      box.innerHTML = views[v].html; note.textContent = views[v].note;
    };
    seg.forEach(function (b) { b.addEventListener('click', function () { show(b.dataset.view); }); });
    show('raw');
  }

  // Questions page: smooth open and close for <details>
  [].forEach.call(document.querySelectorAll('.qlist details'), function (d) {
    var sum = d.querySelector('summary'), body = d.querySelector('.qa'), anim = null;
    sum.addEventListener('click', function (e) {
      if (reduce.matches) return; // native toggle, no motion
      e.preventDefault();
      if (anim) anim.cancel();
      var opening = !d.open;
      if (opening) d.open = true;
      var h = body.offsetHeight;
      var from = opening ? 0 : h, to = opening ? h : 0;
      body.style.overflow = 'hidden';
      anim = body.animate({ height: [from + 'px', to + 'px'], opacity: opening ? [0, 1] : [1, 0] }, { duration: 240, easing: 'cubic-bezier(.2,.7,.2,1)' });
      anim.onfinish = anim.oncancel = function () {
        if (!opening) d.open = false;
        body.style.overflow = ''; anim = null;
      };
    });
  });

  // Questions page: highlight the category in view
  var qlinks = [].slice.call(document.querySelectorAll('.qnav a'));
  if (qlinks.length && 'IntersectionObserver' in window) {
    var secs = qlinks.map(function (a) { return document.querySelector(a.getAttribute('href')); });
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        qlinks.forEach(function (a) { a.toggleAttribute('data-on', a.getAttribute('href') === '#' + en.target.id); });
      });
    }, { rootMargin: '-25% 0px -65% 0px' });
    secs.forEach(function (s) { if (s) io.observe(s); });
  }

  // demo video: click-to-play with sound, no autoplay, pause when out of view or tab hidden
  var v = document.getElementById('demoVideo');
  if (v) {
    var box = document.getElementById('demo'), playBtn = document.getElementById('demoPlay');
    var started = function () { box.classList.add('is-started'); };
    playBtn.addEventListener('click', function () { v.muted = false; started(); v.play().catch(function () {}); });
    v.addEventListener('play', started);
    v.addEventListener('ended', function () { box.classList.remove('is-started'); v.currentTime = 0; v.load(); });
    v.addEventListener('error', function () { box.classList.remove('is-started'); });
    document.addEventListener('visibilitychange', function () { if (document.hidden && !v.paused) v.pause(); });
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(function (es) { if (!es[0].isIntersecting && !v.paused) v.pause(); }, { threshold: 0.15 }).observe(box);
    }
  }
})();
