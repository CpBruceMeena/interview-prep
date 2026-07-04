/**
 * sidebar-click.js
 * Makes MkDocs Material sidebar section headers clickable.
 * Clicking the section title navigates to the first child page.
 * Clicking the chevron icon still toggles expand/collapse.
 */
(function() {
  'use strict';

  // Single delegated click listener
  document.addEventListener('click', function(e) {
    // Must be clicking on a section header label
    var label = e.target.closest('.md-nav__item--nested > .md-nav__link');
    if (!label) return;

    // If clicking the chevron icon, let it toggle normally
    if (e.target.closest('.md-nav__icon')) return;

    // Find the first child link
    // Find the immediate child nav (the children list)
    var nav = label.parentElement.querySelector(':scope > .md-nav') || label.nextElementSibling;
    if (!nav || !nav.classList.contains('md-nav')) return;

    var firstLink = nav.querySelector('.md-nav__item > a.md-nav__link');
    if (!firstLink || !firstLink.href) return;

    // Navigate to the first child's URL
    e.preventDefault();
    window.location.href = firstLink.href;
  });
})();
