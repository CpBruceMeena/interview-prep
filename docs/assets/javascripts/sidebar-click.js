/**
 * sidebar-click.js
 * Makes MkDocs Material sidebar section headers clickable.
 * Clicking the section title navigates to the first child page.
 * Clicking the chevron icon still toggles expand/collapse.
 */
(function() {
  'use strict';

  document.addEventListener('click', function(e) {
    // Find the clicked nav link label
    var label = e.target.closest('.md-nav__link');
    if (!label) return;

    // Only handle nested section headers (not leaf pages)
    var item = label.closest('.md-nav__item--nested');
    if (!item) return;

    // Skip sections that already use md-nav__container (top-level sections with URLs)
    if (item.querySelector('.md-nav__container')) return;

    // If clicking the chevron icon, let it toggle normally
    if (e.target.closest('.md-nav__icon')) return;

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
