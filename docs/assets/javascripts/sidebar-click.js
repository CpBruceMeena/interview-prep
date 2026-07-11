/**
 * sidebar-click.js
 * Makes MkDocs Material sidebar section headers clickable.
 * Clicking the section title navigates to the first child page.
 * Clicking the chevron icon still toggles expand/collapse.
 *
 * IMPORTANT: Only intercepts <label> elements (section headers),
 * NOT <a> elements (leaf page links). This prevents the script
 * from hijacking clicks on HLD/Code/Questions links.
 */
(function() {
  'use strict';

  document.addEventListener('click', function(e) {
    var label = e.target.closest('.md-nav__link');
    if (!label) return;

    // ── ONLY intercept <label> elements (section headers) ──
    // Leaf pages use <a> links — never intercept those.
    if (label.tagName === 'A') return;

    var item = label.closest('.md-nav__item--nested');
    if (!item) return;

    // Skip sections that already use md-nav__container (top-level sections with URLs)
    if (item.querySelector('.md-nav__container')) return;

    // If clicking the chevron icon, let it toggle normally
    if (e.target.closest('.md-nav__icon')) return;

    // ── On mobile/tablet, let taps just toggle expand/collapse ──
    // 76.1875em matches Material's own mobile-to-desktop breakpoint (minus 1px).
    if (window.matchMedia('(max-width: 76.1875em)').matches) return;

    // Find the first child link inside this section
    var nav = item.querySelector(':scope > .md-nav');
    if (!nav) nav = label.nextElementSibling;
    if (!nav || !nav.classList.contains('md-nav')) return;

    var firstLink = nav.querySelector('.md-nav__item > a.md-nav__link');
    if (!firstLink || !firstLink.href) return;

    // Navigate to the first child's URL (prevents the label toggle)
    e.preventDefault();
    e.stopPropagation();
    window.location.href = firstLink.href;
  });
})();
