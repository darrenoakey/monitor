(function () {
    'use strict';

    // ── Configuration ──────────────────────────────────────────────
    const CONFIG = {
        host: location.hostname || 'localhost',
        port: 19103,
        pollInterval: 1000,
        staleness: 300,
        prefix: 'monitor'
    };

    // Token: query param > server-injected meta tag
    let TOKEN = new URLSearchParams(location.search).get('token')
        || (document.querySelector('meta[name="pubsub-token"]') || {}).content || '';

    // ── State ──────────────────────────────────────────────────────
    let localTree = {};   // merged tree from pubsub deltas
    let lastTime = 0;     // pubsub time for delta polling
    let needsRender = true;

    // Hidden paths (server-persisted)
    let hiddenPaths = new Set();

    function savePrefs() {
        var payload = { hidden: [...hiddenPaths] };
        fetch('/prefs', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        }).then(function () {
            console.log('Saved prefs:', payload.hidden.length, 'hidden paths');
        }).catch(function (err) { console.warn('savePrefs failed:', err); });
    }

    function loadPrefs() {
        return fetch('/prefs').then(function (r) { return r.json(); }).then(function (prefs) {
            if (prefs.hidden) {
                hiddenPaths = new Set(prefs.hidden);
                console.log('Loaded prefs: hiding', prefs.hidden.length, 'paths');
            }
        }).catch(function (err) { console.warn('loadPrefs failed:', err); });
    }

    // Zoom/pan state
    let scale = 1;
    let translateX = 0;
    let translateY = 0;
    let dragging = false;
    let dragStartX = 0;
    let dragStartY = 0;
    let dragStartTX = 0;
    let dragStartTY = 0;

    const viewport = document.getElementById('viewport');
    const treemap = document.getElementById('treemap');
    const tooltip = document.getElementById('tooltip');

    // ── Pubsub Polling ─────────────────────────────────────────────
    async function poll() {
        if (!TOKEN) return;
        const url = `http://${CONFIG.host}:${CONFIG.port}/get/${CONFIG.prefix}?time=${lastTime}&token=${TOKEN}`;
        try {
            const resp = await fetch(url);
            if (!resp.ok) return;
            const data = await resp.json();
            if (data.time !== undefined) lastTime = data.time;
            if (data.value !== undefined || data.nodes !== undefined) {
                mergeUpdate(localTree, data);
                needsRender = true;
            }
        } catch (e) {
            // Network error, will retry next poll
        }
    }

    function mergeUpdate(local, update) {
        if (update.value !== undefined) {
            local.value = update.value;
        }
        if (update.nodes) {
            if (!local.nodes) local.nodes = {};
            for (const key in update.nodes) {
                if (!local.nodes[key]) local.nodes[key] = {};
                mergeUpdate(local.nodes[key], update.nodes[key]);
            }
            // Prune dead children: no value and no sub-nodes with content
            for (const key in local.nodes) {
                if (isDead(local.nodes[key])) {
                    delete local.nodes[key];
                }
            }
        }
    }

    // A node is dead if it has no real value (null/undefined)
    // and none of its descendants have real values.
    function isDead(node) {
        if (node.value !== null && node.value !== undefined) return false;
        if (!node.nodes) return true;
        for (const key in node.nodes) {
            if (!isDead(node.nodes[key])) return false;
        }
        return true;
    }

    // ── Build Render Tree ──────────────────────────────────────────
    function buildRenderTree(node, name, parentPath) {
        const path = parentPath ? parentPath + '/' + name : name;
        if (hiddenPaths.has(path)) return null;

        const item = { name: name, path: path, children: [] };
        const hasValue = node.value && typeof node.value === 'object' && node.value !== null;
        // A "real" value means something worth displaying as a leaf (non-empty value field).
        const hasRealValue = hasValue && !!node.value.value;

        // Extract info from value blob if present
        if (hasValue) {
            item.weight = node.value.weight || 1;
            item.status = node.value.status || 'good';
            item.displayName = node.value.name || name;
            item.displayValue = node.value.value || '';
            item.details = node.value.details || '';
            item.timestamp = node.value.timestamp || 0;
        } else {
            item.weight = 1;
            item.status = 'good';
            item.displayName = name;
            item.displayValue = '';
            item.details = '';
            item.timestamp = 0;
        }

        // Build children, pruning empty branches
        if (node.nodes) {
            for (const key in node.nodes) {
                const child = buildRenderTree(node.nodes[key], key, path);
                if (child) item.children.push(child);
            }
        }

        // Branch nodes default to weight 1, but respect an explicit weight
        // from a published value blob (lets the agent control category sizing).
        if (item.children.length > 0 && !hasValue) {
            item.weight = 1;
        }

        // Prune: a node must have at least one leaf descendant with a real
        // non-null value to be shown. Nodes with only metadata (category
        // weights) but no displayable leaves are suppressed.
        if (item.children.length === 0 && !hasRealValue) {
            return null;
        }

        return item;
    }

    // ── Squarified Treemap Layout ──────────────────────────────────
    function squarify(items, x, y, w, h) {
        if (items.length === 0 || w <= 0 || h <= 0) return [];
        const totalWeight = items.reduce((s, i) => s + i.weight, 0);
        if (totalWeight <= 0) return [];

        // Sort by weight descending
        const sorted = items.slice().sort((a, b) => b.weight - a.weight);

        // Standard layout
        const rects = [];
        layoutItems(sorted, x, y, w, h, totalWeight, rects);

        // If >4 children and any cell has aspect ratio worse than 8:1,
        // split into two pseudo-groups and re-layout
        if (items.length > 4) {
            const hasBadRatio = rects.some(function (r) {
                return r.w > 0 && r.h > 0 && Math.max(r.w / r.h, r.h / r.w) > 6;
            });
            if (hasBadRatio) {
                return squarifyWithSplit(sorted, x, y, w, h, totalWeight);
            }
        }

        return rects;
    }

    function squarifyWithSplit(sorted, x, y, w, h, totalWeight) {
        // Split items into two groups, as close to half by weight as possible
        const halfWeight = totalWeight / 2;
        var group1 = [], group2 = [];
        var g1Weight = 0;
        for (var i = 0; i < sorted.length; i++) {
            if (g1Weight < halfWeight && group1.length < sorted.length - 1) {
                group1.push(sorted[i]);
                g1Weight += sorted[i].weight;
            } else {
                group2.push(sorted[i]);
            }
        }

        if (group1.length === 0 || group2.length === 0) {
            // Can't split meaningfully, return standard layout
            var rects = [];
            layoutItems(sorted, x, y, w, h, totalWeight, rects);
            return rects;
        }

        var g2Weight = totalWeight - g1Weight;

        // Layout two pseudo-nodes
        var pseudoItems = [
            { weight: g1Weight, _group: group1 },
            { weight: g2Weight, _group: group2 }
        ];
        pseudoItems.sort(function (a, b) { return b.weight - a.weight; });
        var pseudoRects = [];
        layoutItems(pseudoItems, x, y, w, h, totalWeight, pseudoRects);

        // Recursively squarify each group within its allocated rect
        var result = [];
        for (var j = 0; j < pseudoRects.length; j++) {
            var pr = pseudoRects[j];
            var groupRects = squarify(pr.item._group, pr.x, pr.y, pr.w, pr.h);
            result.push.apply(result, groupRects);
        }
        return result;
    }

    function layoutItems(items, x, y, w, h, totalWeight, rects) {
        if (items.length === 0) return;
        if (items.length === 1) {
            rects.push({ item: items[0], x, y, w, h });
            return;
        }

        const shortSide = Math.min(w, h);
        const totalArea = w * h;

        // Greedily add items to row while aspect ratio improves
        let row = [items[0]];
        let rowWeight = items[0].weight;
        let bestWorst = worstRatio(row, rowWeight, shortSide, totalArea, totalWeight);

        let i = 1;
        while (i < items.length) {
            const candidate = items[i];
            const newRowWeight = rowWeight + candidate.weight;
            const newRow = row.concat(candidate);
            const newWorst = worstRatio(newRow, newRowWeight, shortSide, totalArea, totalWeight);

            if (newWorst <= bestWorst) {
                row = newRow;
                rowWeight = newRowWeight;
                bestWorst = newWorst;
                i++;
            } else {
                break;
            }
        }

        // Layout this row
        const rowFraction = rowWeight / totalWeight;
        const remaining = items.slice(i);
        const remainingWeight = totalWeight - rowWeight;

        if (w >= h) {
            // Lay row along left side
            const rowW = w * rowFraction;
            layoutRow(row, x, y, rowW, h, totalArea, totalWeight, rects);
            if (remaining.length > 0) {
                layoutItems(remaining, x + rowW, y, w - rowW, h, remainingWeight, rects);
            }
        } else {
            // Lay row along top
            const rowH = h * rowFraction;
            layoutRow(row, x, y, w, rowH, totalArea, totalWeight, rects);
            if (remaining.length > 0) {
                layoutItems(remaining, x, y + rowH, w, h - rowH, remainingWeight, rects);
            }
        }
    }

    function layoutRow(row, x, y, w, h, totalArea, totalWeight, rects) {
        const rowWeight = row.reduce((s, i) => s + i.weight, 0);
        if (w >= h) {
            // Stack vertically within the row strip
            let cy = y;
            for (const item of row) {
                const itemH = h * (item.weight / rowWeight);
                rects.push({ item, x, y: cy, w, h: itemH });
                cy += itemH;
            }
        } else {
            // Stack horizontally within the row strip
            let cx = x;
            for (const item of row) {
                const itemW = w * (item.weight / rowWeight);
                rects.push({ item, x: cx, y, w: itemW, h });
                cx += itemW;
            }
        }
    }

    function worstRatio(row, rowWeight, shortSide, totalArea, totalWeight) {
        // Area allocated to this row
        const rowArea = totalArea * (rowWeight / totalWeight);
        const rowSide = rowArea / shortSide;
        let worst = 0;
        for (const item of row) {
            const itemArea = totalArea * (item.weight / totalWeight);
            const itemSide = itemArea / rowSide;
            const ratio = Math.max(rowSide / itemSide, itemSide / rowSide);
            if (ratio > worst) worst = ratio;
        }
        return worst;
    }

    // ── DOM Rendering ──────────────────────────────────────────────
    function render() {
        const vw = viewport.clientWidth;
        const vh = viewport.clientHeight;
        if (vw === 0 || vh === 0) return;

        treemap.style.width = vw + 'px';
        treemap.style.height = vh + 'px';

        const renderTree = buildRenderTree(localTree, 'root', '');
        treemap.innerHTML = '';

        if (renderTree.children.length > 0) {
            // Skip the root node itself - layout its children directly
            const rects = squarify(renderTree.children, 0, 0, vw, vh);
            for (const rect of rects) {
                renderNode(rect.item, rect.x, rect.y, rect.w, rect.h, treemap);
            }
        } else if (renderTree.displayValue) {
            renderLeaf(renderTree, 0, 0, vw, vh, treemap);
        }

        applyTransform();
    }

    function renderNode(item, x, y, w, h, container) {
        if (w < 1 || h < 1) return;

        if (item.children.length === 0) {
            renderLeaf(item, x, y, w, h, container);
            return;
        }

        // Branch node: title bar + children area
        const div = document.createElement('div');
        div.className = 'node node-branch status-good';
        div.dataset.path = item.path;
        div.style.left = x + 'px';
        div.style.top = y + 'px';
        div.style.width = w + 'px';
        div.style.height = h + 'px';

        const titleH = Math.min(Math.max(h * 0.08, 14), 24);
        const titleDiv = document.createElement('div');
        titleDiv.className = 'node-title';
        titleDiv.style.height = titleH + 'px';
        titleDiv.style.fontSize = Math.max(titleH * 0.65, 9) + 'px';
        titleDiv.textContent = item.displayName;
        div.appendChild(titleDiv);

        container.appendChild(div);

        // Layout children in remaining space
        const childY = 0 + titleH;
        const childH = h - titleH;
        if (childH > 0) {
            const rects = squarify(item.children, 0, childY, w, childH);
            for (const rect of rects) {
                renderNode(rect.item, rect.x, rect.y, rect.w, rect.h, div);
            }
        }
    }

    // Wrap text into spans: each "token" (number-with-dots or word) is a
    // nowrap unit, with line-break opportunities only between tokens.
    function wrappableHTML(str) {
        // Split at number/letter boundaries and spaces
        const tokens = str.match(/[\d.]+|[a-zA-Z]+|[^\s\da-zA-Z]+|\s+/g) || [str];
        return tokens.map(function (t) {
            if (/^\s+$/.test(t)) return ' ';
            return '<span style="white-space:nowrap">' + esc(t) + '</span>\u200B';
        }).join('');
    }

    // Fit text by measuring an inner span against the container bounds.
    // Wraps content in a span so we measure text size, not container size.
    function fitText(el, maxW, maxH, maxFont) {
        let span = el.querySelector('.fit-span');
        if (!span) {
            span = document.createElement('span');
            span.className = 'fit-span';
            // Move all child nodes into the span
            while (el.firstChild) span.appendChild(el.firstChild);
            el.appendChild(span);
        }
        if (maxW < 2 || maxH < 2) return;

        // Binary search for the largest font size that fits
        let lo = 4, hi = Math.max(Math.min(maxW, maxH) * 1.5, 8);
        if (maxFont) hi = Math.min(hi, maxFont);
        while (hi - lo > 0.5) {
            const mid = (lo + hi) / 2;
            span.style.fontSize = mid + 'px';
            if (span.offsetWidth <= maxW && span.offsetHeight <= maxH) {
                lo = mid;
            } else {
                hi = mid;
            }
        }
        span.style.fontSize = lo + 'px';
    }

    function renderLeaf(item, x, y, w, h, container) {
        if (w < 1 || h < 1) return;

        const now = Date.now() / 1000;
        const isStale = item.timestamp > 0 && (now - item.timestamp) > CONFIG.staleness;
        const statusClass = isStale ? 'status-stale' : ('status-' + item.status);

        const div = document.createElement('div');
        div.className = 'node node-leaf ' + statusClass;
        div.dataset.path = item.path;
        div.style.left = x + 'px';
        div.style.top = y + 'px';
        div.style.width = w + 'px';
        div.style.height = h + 'px';

        // Title - absolute positioned top-left, full cell height.
        // Overlaps with value area since title is left-aligned and value is centered.
        const titleDiv = document.createElement('div');
        titleDiv.className = 'node-title';
        titleDiv.style.position = 'absolute';
        titleDiv.style.top = '0';
        titleDiv.style.left = '0';
        titleDiv.style.width = w + 'px';
        titleDiv.style.height = h + 'px';
        titleDiv.textContent = item.displayName;
        div.appendChild(titleDiv);

        // Value - absolute positioned, full cell, centered.
        var valueDiv = null;
        if (item.displayValue) {
            valueDiv = document.createElement('div');
            valueDiv.className = 'node-value';
            valueDiv.style.position = 'absolute';
            valueDiv.style.top = '0';
            valueDiv.style.left = '0';
            valueDiv.style.width = w + 'px';
            valueDiv.style.height = h + 'px';
            valueDiv.innerHTML = wrappableHTML(item.displayValue);
            div.appendChild(valueDiv);
        }

        // Tooltip events
        div.addEventListener('mouseenter', function (e) {
            showTooltip(e, item, isStale);
        });
        div.addEventListener('mousemove', positionTooltip);
        div.addEventListener('mouseleave', hideTooltip);

        // Append first so we can measure
        container.appendChild(div);

        // Fit title - constrain width to 45% so it stays small and left-aligned,
        // full height so it never clips vertically, cap font scales with cell
        fitText(titleDiv, w * 0.45, h, Math.max(h * 0.25, 10));

        // Fit value - full cell
        if (valueDiv) fitText(valueDiv, w - 4, h);
    }

    // ── Tooltip ────────────────────────────────────────────────────
    function showTooltip(e, item, isStale) {
        let html = `<div class="tip-name">${esc(item.displayName)}</div>`;
        if (item.displayValue) {
            html += `<div class="tip-value">${esc(item.displayValue)}</div>`;
        }
        if (item.details) {
            html += `<div class="tip-details">${esc(item.details)}</div>`;
        }
        if (item.timestamp > 0) {
            const age = Math.floor(Date.now() / 1000 - item.timestamp);
            const ageStr = age < 60 ? age + 's ago' : Math.floor(age / 60) + 'm ago';
            html += `<div class="tip-age">${ageStr}${isStale ? ' (STALE)' : ''}</div>`;
        }
        tooltip.innerHTML = html;
        tooltip.style.display = 'block';
        positionTooltip(e);
    }

    function positionTooltip(e) {
        const pad = 12;
        let tx = e.clientX + pad;
        let ty = e.clientY + pad;
        if (tx + tooltip.offsetWidth > window.innerWidth) {
            tx = e.clientX - tooltip.offsetWidth - pad;
        }
        if (ty + tooltip.offsetHeight > window.innerHeight) {
            ty = e.clientY - tooltip.offsetHeight - pad;
        }
        tooltip.style.left = tx + 'px';
        tooltip.style.top = ty + 'px';
    }

    function hideTooltip() {
        tooltip.style.display = 'none';
    }

    function esc(str) {
        const d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    }

    // ── Zoom & Pan ─────────────────────────────────────────────────
    function applyTransform() {
        treemap.style.transform = `translate(${translateX}px, ${translateY}px) scale(${scale})`;
    }

    viewport.addEventListener('wheel', function (e) {
        e.preventDefault();
        const factor = e.deltaY > 0 ? 0.9 : 1.1;
        const newScale = Math.max(1, Math.min(scale * factor, 50));

        // Zoom toward cursor position
        const rect = viewport.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;

        // Point in content space before zoom
        const cx = (mx - translateX) / scale;
        const cy = (my - translateY) / scale;

        scale = newScale;

        // Adjust translate so the same content point stays under cursor
        translateX = mx - cx * scale;
        translateY = my - cy * scale;

        clampTranslate();
        applyTransform();
    }, { passive: false });

    viewport.addEventListener('mousedown', function (e) {
        if (scale <= 1) return;
        dragging = true;
        dragStartX = e.clientX;
        dragStartY = e.clientY;
        dragStartTX = translateX;
        dragStartTY = translateY;
        viewport.classList.add('dragging');
        e.preventDefault();
    });

    window.addEventListener('mousemove', function (e) {
        if (!dragging) return;
        translateX = dragStartTX + (e.clientX - dragStartX);
        translateY = dragStartTY + (e.clientY - dragStartY);
        clampTranslate();
        applyTransform();
    });

    window.addEventListener('mouseup', function () {
        if (!dragging) return;
        dragging = false;
        viewport.classList.remove('dragging');
    });

    function clampTranslate() {
        const vw = viewport.clientWidth;
        const vh = viewport.clientHeight;
        const contentW = vw * scale;
        const contentH = vh * scale;

        // Keep content covering the viewport (no empty edges)
        translateX = Math.min(0, Math.max(translateX, vw - contentW));
        translateY = Math.min(0, Math.max(translateY, vh - contentH));
    }

    // ── Context Menu ─────────────────────────────────────────────
    const contextMenu = document.getElementById('context-menu');

    let contextMenuPath = '';

    document.addEventListener('contextmenu', function (e) {
        const node = e.target.closest('.node[data-path]');
        if (!node) { dismissContextMenu(); return; }
        e.preventDefault();
        contextMenuPath = node.dataset.path;

        contextMenu.innerHTML = '<div class="menu-item" data-action="hide">Hide</div>';
        contextMenu.style.display = 'block';

        // Position, keeping on screen
        let mx = e.clientX;
        let my = e.clientY;
        const menuW = contextMenu.offsetWidth;
        const menuH = contextMenu.offsetHeight;
        if (mx + menuW > window.innerWidth) mx = window.innerWidth - menuW;
        if (my + menuH > window.innerHeight) my = window.innerHeight - menuH;
        contextMenu.style.left = mx + 'px';
        contextMenu.style.top = my + 'px';
    });

    contextMenu.addEventListener('click', function (ev) {
        const action = ev.target.dataset.action;
        if (action === 'hide' && contextMenuPath) {
            hiddenPaths.add(contextMenuPath);
            savePrefs();
            needsRender = true;
            render();
        }
        dismissContextMenu();
    });

    function dismissContextMenu() {
        contextMenu.style.display = 'none';
        contextMenuPath = '';
    }

    document.addEventListener('mousedown', function (e) {
        if (!contextMenu.contains(e.target)) dismissContextMenu();
    });
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') dismissContextMenu();
    });

    // ── Main Loop ──────────────────────────────────────────────────
    async function init() {
        if (!TOKEN) {
            TOKEN = prompt('Enter pubsub token:') || '';
        }
        await loadPrefs();
        await poll();
        render();

        setInterval(async function () {
            await poll();
            if (needsRender) {
                render();
                needsRender = false;
            }
        }, CONFIG.pollInterval);
    }

    let resizeTimer;
    window.addEventListener('resize', function () {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(function () {
            needsRender = true;
            render();
        }, 150);
    });

    init();
})();
