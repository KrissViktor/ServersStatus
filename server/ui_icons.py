"""Small original line icons shared by the portal views."""
PATHS={
 'filter':'<path d="M3 4h18l-7 8v7l-4 2v-9Z"/>',
 'sort':'<path d="M8 19V5m-4 4 4-4 4 4M15 7h6m-6 5h4m-4 5h2"/>',
 'table':'<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M3 9h18M9 9v12M3 15h18"/>',
 'cards':'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
 'heatmap':'<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M3 9h18M3 15h18M9 3v18m6-18v18"/><path d="M10 10h4v4h-4Z" fill="currentColor"/>',
 'timeline':'<path d="M6 3v18m0-15h13M6 12h9M6 18h13"/><circle cx="6" cy="6" r="2"/><circle cx="6" cy="12" r="2"/><circle cx="6" cy="18" r="2"/>',
 'wallboard':'<rect x="2" y="3" width="20" height="15" rx="2"/><path d="M8 22h8m-4-4v4M6 8h5m-5 4h12"/>',
 'dependencies':'<rect x="8" y="2" width="8" height="6" rx="1"/><path d="M12 8v6M4 17v-3h16v3"/><rect x="1" y="17" width="6" height="5" rx="1"/><rect x="17" y="17" width="6" height="5" rx="1"/>',
 'news':'<path d="M19 10a7 7 0 0 0-14 0c0 7-2 7-2 8h18c0-1-2-1-2-8ZM9 21h6"/>',
 'reboot':'<path d="M3 10a9 9 0 1 1 2 8M3 3v7h7"/>',
 'update':'<path d="M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6"/>',
 'incident':'<path d="m12 2 11 20H1ZM12 9v5m0 3v1"/>',
 'equipment':'<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M9 1v3m6-3v3M9 20v3m6-3v3M1 9h3m-3 6h3m16-6h3m-3 6h3M9 9h6v6H9Z"/>',
 'connection':'<path d="M3 9a15 15 0 0 1 18 0M6 13a10 10 0 0 1 12 0m-9 4a5 5 0 0 1 6 0"/><circle cx="12" cy="21" r="1"/>'}


def icon(name):
    return '<svg class="portal-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+PATHS.get(name,PATHS['timeline'])+'</svg>'
