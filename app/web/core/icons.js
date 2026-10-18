/** Local SVG icon set: replaces remote icon fonts so the shell stays offline-capable.
 *  Names kept compatible with module registry icons (home/projects/link/calendar/code). */
const PATHS = {
  home: ['M3 11.5 12 4l9 7.5V20H3z', 'M9 14c.8.8 1.9 1.2 3 1.2s2.2-.4 3-1.2'],
  projects: ['M4 4h6v6H4z', 'M14 4h6v6h-6z', 'M4 14h6v6H4z', 'M14 14h6v6h-6z'],
  link: ['M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-2 2', 'M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l2-2'],
  code: ['m8 7-5 5 5 5', 'm16 7 5 5-5 5', 'M14 4l-4 16'],
  folder: ['M3 6h6l2 2.5h10V19H3z'],
  image: ['M3 5h18v14H3z', 'M3 16l5-5 4 4 3-3 6 6', 'M8.5 9.5a1.2 1.2 0 1 0 0-2.4 1.2 1.2 0 0 0 0 2.4'],
  arrow: ['M5 12h14', 'm13 6 6 6-6 6'],
  checklist: ['M4 7h.01', 'M4 12h.01', 'M4 17h.01', 'M8 7h12', 'M8 12h12', 'M8 17h12'],
  calendar: ['M4 6h16v14H4z', 'M4 10h16', 'M8 3v4', 'M16 3v4'],
  'calendar-date': ['M4 6h16v14H4z', 'M4 10h16', 'M8 3v4', 'M16 3v4', 'M8 14h3v3H8z'],
  'add-circle': ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18', 'M12 8v8', 'M8 12h8'],
  'check-circle': ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18', 'm8 12 3 3 5-6'],
  circle: ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18'],
  'close-circle': ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18', 'm9 9 6 6', 'm15 9-6 6'],
  'alt-arrow-right': ['m9 6 6 6-6 6'],
  'alt-arrow-down': ['m6 9 6 6 6-6'],
  'arrow-up-right': ['M7 17 17 7', 'M9 7h8v8'],
  bell: ['M18 8a6 6 0 1 0-12 0c0 6-3 6-3 8h18c0-2-3-2-3-8', 'M10 20h4'],
  bag: ['M6 8h12l-1 12H7z', 'M9 8V6a3 3 0 0 1 6 0v2'],
  book: ['M5 4h9a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z', 'M5 17h12'],
  bookmark: ['M6 4h12v16l-6-4-6 4z'],
  'bookmark-opened': ['M4 5h9l7 7-7 7H4z'],
  'cloud-sun': ['M7 15a4 4 0 1 1 1-7.8 5 5 0 0 1 9.5 2.3A3.5 3.5 0 0 1 17 15z'],
  'cup-hot': ['M5 8h10v6a4 4 0 0 1-4 4H9a4 4 0 0 1-4-4z', 'M15 9h2a2 2 0 0 1 0 4h-2', 'M8 4v2', 'M11 3v3'],
  hamburger: ['M4 7h16', 'M4 12h16', 'M4 17h16'],
  leaf: ['M4 20c0-8 6-14 16-14 0 10-6 14-16 14z', 'M4 20 12 12'],
  'magic-stick': ['m5 19 9-9', 'M14 5l1 3 3 1-3 1-1 3-1-3-3-1 3-1z'],
  magnifer: ['M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14', 'm16 16 5 5'],
  'map-point': ['M12 21s7-6.2 7-11a7 7 0 1 0-14 0c0 4.8 7 11 7 11z', 'M12 8a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5'],
  notebook: ['M6 3h11a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6z', 'M9 8h6', 'M9 12h6'],
  'pen-square': ['M4 4h16v16H4z', 'm9 15 1-3 5-5 2 2-5 5z'],
  refresh: ['M4 12a8 8 0 0 1 13.7-5.6L20 8', 'M20 4v4h-4', 'M20 12a8 8 0 0 1-13.7 5.6L4 16', 'M4 20v-4h4'],
  settings: ['M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7', 'M19 12a7 7 0 0 0-.2-1.6l2-1.6-2-3.4-2.4 1a7 7 0 0 0-2.8-1.6L13.2 2h-3.9l-.4 2.8a7 7 0 0 0-2.8 1.6l-2.4-1L1.7 8.8l2 1.6A7 7 0 0 0 3.5 12a7 7 0 0 0 .2 1.6l-2 1.6 2 3.4 2.4-1a7 7 0 0 0 2.8 1.6l.4 2.8h3.9l.4-2.8a7 7 0 0 0 2.8-1.6l2.4 1 2-3.4-2-1.6A7 7 0 0 0 19 12z'],
  star: ['m12 4 2.4 5 5.6.8-4 4 1 5.6-5-2.7-5 2.7 1-5.6-4-4 5.6-.8z'],
  widget: ['M4 4h7v7H4z', 'M4 14h7v6H4z', 'M14 4h6v6h-6z', 'M14 13h6v7h-6z'],
  clock: ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18', 'M12 7v5l3 2'],
};

const NAMESPACE = 'http://www.w3.org/2000/svg';

/* 原型使用 iconify 的 solar:* 命名；这里做本地映射，保持调用方语义不变。 */
const ALIAS = {
  'home-smile': 'home', 'widget-4': 'widget', 'widget-5': 'widget',
  'checklist-minimalistic': 'checklist', 'folder-with-files': 'folder',
  'folder-2': 'folder', 'book-2': 'book', 'bookmark-opened': 'bookmark',
  'pen-new-square': 'pen-square', 'cloud-sun-2': 'cloud-sun',
  'cup-hot': 'cup-hot', 'bag-4': 'bag', 'magic-stick-3': 'magic-stick',
  'arrow-right': 'arrow', 'check-circle-bold': 'check-circle',
  'hamburger-menu': 'hamburger', 'add-circle': 'add-circle',
  'alt-arrow-down': 'alt-arrow-down', 'alt-arrow-right': 'alt-arrow-right',
  'close-circle': 'close-circle',
};

function resolve(name) {
  return PATHS[name] ? name : (PATHS[ALIAS[name]] ? ALIAS[name] : 'widget');
}

export function sprite() {
  const svg = document.createElementNS(NAMESPACE, 'svg');
  svg.setAttribute('hidden', '');
  svg.setAttribute('aria-hidden', 'true');
  for (const [name, paths] of Object.entries(PATHS)) {
    const symbol = document.createElementNS(NAMESPACE, 'symbol');
    symbol.setAttribute('id', 'i-' + name);    symbol.setAttribute('viewBox', '0 0 24 24');
    for (const d of paths) {
      const path = document.createElementNS(NAMESPACE, 'path');
      path.setAttribute('d', d);
      symbol.append(path);
    }
    svg.append(symbol);
  }
  return svg;
}

export function icon(name, size = 18) {
  const node = document.createElementNS(NAMESPACE, 'svg');
  node.setAttribute('class', 'wb-icon');
  node.setAttribute('width', String(size));
  node.setAttribute('height', String(size));
  node.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS(NAMESPACE, 'use');
  use.setAttribute('href', '#i-' + resolve(name));
  node.append(use);
  return node;
}
