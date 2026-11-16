(function () {
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

  // current section in nav
  var ids = ['features', 'how', 'privacy', 'pricing'];
  var links = [].slice.call(document.querySelectorAll('.nav__links a, .nav__menu a:not(.btn)'));
  function spy() {
    var y = window.scrollY + 160, cur = null;
    ids.forEach(function (id) { var s = document.getElementById(id); if (s && s.offsetTop <= y) cur = id; });
    var dl = document.getElementById('download'); if (dl && dl.offsetTop <= y) cur = null;
    links.forEach(function (a) { if (cur && a.getAttribute('href') === '#' + cur) a.setAttribute('aria-current', 'true'); else a.removeAttribute('aria-current'); });
  }
  window.addEventListener('scroll', spy, { passive: true }); spy();

  // showcase tabs (WAI-ARIA tabs, vertical)
  var tabs = [].slice.call(document.querySelectorAll('[role=tab]'));
  function select(tab, focus) {
    tabs.forEach(function (t) {
      var on = t === tab;
      t.setAttribute('aria-selected', on); t.tabIndex = on ? 0 : -1;
      document.getElementById(t.getAttribute('aria-controls')).hidden = !on;
    });
    if (focus) tab.focus();
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
  // show the first panel only
  tabs.forEach(function (t, i) { document.getElementById(t.getAttribute('aria-controls')).hidden = i !== 0; });

  // how-it-works steps
  var steps = [].slice.call(document.querySelectorAll('.how__steps button'));
  steps.forEach(function (b) {
    b.addEventListener('click', function () {
      steps.forEach(function (o) {
        var on = o === b; o.setAttribute('aria-pressed', on);
        document.getElementById(o.dataset.shot).hidden = !on;
      });
    });
  });

  // redaction demo (synthetic strings; the mask format is the one the app shows)
  var box = document.getElementById('maskBox'), note = document.getElementById('maskNote');
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
  function show(v) {
    seg.forEach(function (b) { b.setAttribute('aria-pressed', b.dataset.view === v); });
    box.innerHTML = views[v].html; note.textContent = views[v].note;
  }
  seg.forEach(function (b) { b.addEventListener('click', function () { show(b.dataset.view); }); });
  show('raw');
})();
