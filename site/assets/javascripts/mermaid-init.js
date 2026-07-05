/**
 * mermaid-init.js
 * Initializes Mermaid.js with dark theme to match the slate color scheme.
 */
document.addEventListener('DOMContentLoaded', function() {
  if (typeof mermaid !== 'undefined') {
    mermaid.initialize({
      startOnLoad: true,
      theme: 'dark',
      themeVariables: {
        primaryColor: '#7c3aed',
        primaryTextColor: '#e6edf3',
        primaryBorderColor: '#a78bfa',
        lineColor: '#a78bfa',
        secondaryColor: '#1e1b4b',
        tertiaryColor: '#0d1117',
        fontSize: '14px'
      },
      flowchart: {
        useMaxWidth: true,
        htmlLabels: true,
        curve: 'basis'
      },
      sequence: {
        showSequenceNumbers: true
      }
    });
  }
});
