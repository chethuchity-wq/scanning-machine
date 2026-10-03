// Worklist and report editor behaviour. No build step, no libraries.
(function () {
  "use strict";

  // Whole table rows open the scan (links and buttons inside keep working)
  document.querySelectorAll("tr.clickable").forEach(function (row) {
    row.addEventListener("click", function (e) {
      if (e.target.closest("a, button, input, select")) return;
      window.location = row.dataset.href;
    });
  });

  // Alt+Up / Alt+Down: previous / next patient of the day
  document.addEventListener("keydown", function (e) {
    if (!e.altKey || (e.key !== "ArrowUp" && e.key !== "ArrowDown")) return;
    var label = e.key === "ArrowUp" ? "Previous" : "Next";
    var link = Array.prototype.find.call(document.querySelectorAll(".crumbs a.day-nav"), function (a) {
      return a.textContent.indexOf(label) !== -1;
    });
    if (link) { e.preventDefault(); window.location = link.href; }
  });

  // Remake the report as another form (wrong exam type chosen on the scanner)
  var typeForm = document.querySelector(".type-form");
  if (typeForm) {
    var typeSelect = typeForm.querySelector("select");
    var typeBtn = typeForm.querySelector("button");
    typeSelect.addEventListener("change", function () {
      typeBtn.disabled = !typeSelect.value || typeSelect.value === typeForm.dataset.current;
    });
    typeForm.addEventListener("submit", function (e) {
      var name = typeSelect.options[typeSelect.selectedIndex].text;
      var msg = "Make a new report for this scan as \"" + name + "\"?\n\n" +
                "The page will then show the new report. The current report's file is kept in the folder.";
      if (typeForm.dataset.reviewed) {
        msg += "\n\nThe current report was already edited - those edits are NOT carried over to the new one.";
      }
      if (window.__editorDirty && window.__editorDirty()) {
        msg += "\n\nYou have unsaved changes on this page - they will be lost.";
      }
      if (!window.confirm(msg)) { e.preventDefault(); return; }
      window.__skipUnloadWarning = true;
      typeBtn.disabled = true;
      typeBtn.textContent = "Remaking… (up to a minute)";
    });
  }

  var ed = document.getElementById("editor");
  if (!ed) return;

  // ---------------------------------------------------------------------------
  // Report editor. The page shows the Word report's paragraphs; each <p> carries
  // data-pid, its position in the .docx. Saving sends every paragraph back in
  // order and the server writes the text into the same Word paragraphs.
  // ---------------------------------------------------------------------------
  var saveBtn = document.getElementById("save-btn");
  var stateEl = document.getElementById("save-state");
  var pdfBtn = document.getElementById("pdf-btn");
  var version = ed.dataset.version;
  var dirty = false;
  var saving = false;
  var savedText = "All changes saved";

  document.execCommand("defaultParagraphSeparator", false, "p");

  function showState(text, kind) {
    stateEl.textContent = text;
    stateEl.className = "save-state" + (kind ? " " + kind : "");
  }

  function setDirty(value) {
    dirty = value;
    saveBtn.disabled = !dirty || saving;
    if (dirty) showState("Unsaved changes", "unsaved");
    else showState(savedText);
  }

  ed.addEventListener("input", function () { setDirty(true); });

  // Paste and drop as plain text: no fonts or colours from other programs
  ed.addEventListener("paste", function (e) {
    e.preventDefault();
    var text = (e.clipboardData || window.clipboardData).getData("text/plain");
    document.execCommand("insertText", false, text);
  });
  ed.addEventListener("drop", function (e) { e.preventDefault(); });

  document.querySelectorAll(".tool").forEach(function (btn) {
    // Keep the text selection when the button is pressed
    btn.addEventListener("mousedown", function (e) { e.preventDefault(); });
    btn.addEventListener("click", function () {
      document.execCommand(btn.dataset.cmd, false, null);
      ed.focus();
      setDirty(true);
    });
  });

  // Text typed straight into a table cell or the page (e.g. after deleting a
  // whole paragraph) is wrapped back into a paragraph so it gets saved.
  var INLINE = { B: 1, STRONG: 1, I: 1, EM: 1, U: 1, SPAN: 1, BR: 1, FONT: 1 };
  function normalize() {
    var containers = [ed].concat(Array.prototype.slice.call(ed.querySelectorAll("td")));
    containers.forEach(function (box) {
      var run = null;
      Array.prototype.slice.call(box.childNodes).forEach(function (node) {
        var stray = (node.nodeType === 3 && node.textContent.trim()) ||
                    (node.nodeType === 1 && INLINE[node.tagName]);
        if (node.nodeType === 1 && node.tagName === "DIV" &&
            !node.classList.contains("dp-img") && !node.classList.contains("page-break")) {
          var p = document.createElement("p");
          p.className = "dp";
          while (node.firstChild) p.appendChild(node.firstChild);
          box.replaceChild(p, node);
          run = null;
          return;
        }
        if (stray) {
          if (!run) {
            run = document.createElement("p");
            run.className = "dp";
            box.insertBefore(run, node);
          }
          run.appendChild(node);
        } else if (node.nodeType === 1) {
          run = null;
        }
      });
    });
  }

  function collectBlocks() {
    normalize();
    return Array.prototype.map.call(ed.querySelectorAll("p"), function (p) {
      var block = { pid: p.dataset.pid !== undefined ? Number(p.dataset.pid) : null, html: p.innerHTML };
      if (block.pid === null) {
        // A new paragraph opening a table cell is placed before the cell's first one
        var prev = p.previousElementSibling;
        while (prev && prev.tagName !== "P") prev = prev.previousElementSibling;
        if (!prev) {
          var next = p.nextElementSibling;
          while (next && !(next.tagName === "P" && next.dataset.pid !== undefined)) next = next.nextElementSibling;
          if (next) block.before = Number(next.dataset.pid);
        }
      }
      return block;
    });
  }

  function structureChanged(blocks) {
    var seen = {};
    var changed = blocks.some(function (b) {
      if (b.pid === null || seen[b.pid]) return true;
      seen[b.pid] = true;
      return false;
    });
    return changed || blocks.length !== Number(ed.dataset.paragraphs);
  }
  ed.dataset.paragraphs = ed.querySelectorAll("p[data-pid]").length;

  function markReviewed() {
    var badge = document.getElementById("status-badge");
    if (badge) badge.innerHTML = '<span class="status-badge status-reviewed" title="Edited and saved since it was generated">&#10003; Reviewed</span>';
  }

  function save() {
    if (saving) return Promise.resolve(false);
    if (!dirty) return Promise.resolve(true);
    saving = true;
    saveBtn.disabled = true;
    showState("Saving…");
    var blocks = collectBlocks();
    var reload = structureChanged(blocks);
    return fetch(ed.dataset.url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": ed.dataset.csrf },
      body: JSON.stringify({ version: version, blocks: blocks }),
    }).then(function (res) {
      return res.json().catch(function () { return { detail: res.statusText }; }).then(function (data) {
        if (!res.ok) throw new Error(data.detail || "Save failed");
        version = data.version;
        savedText = "Saved at " + data.saved_at;
        if (!reload) return data;
        // Paragraphs were added or removed: re-read so their positions are right
        return fetch(ed.dataset.url).then(function (r) { return r.json(); }).then(function (fresh) {
          ed.innerHTML = fresh.html;
          version = fresh.version;
          ed.dataset.paragraphs = ed.querySelectorAll("p[data-pid]").length;
          return data;
        });
      });
    }).then(function () {
      saving = false;
      setDirty(false);
      markReviewed();
      return true;
    }).catch(function (err) {
      saving = false;
      saveBtn.disabled = false;
      showState("⚠ " + err.message, "error");
      return false;
    });
  }

  saveBtn.addEventListener("click", save);
  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
      e.preventDefault();
      save();
    }
  });

  // PDF / Print: save first, so the PDF is made from what is on screen
  pdfBtn.addEventListener("click", function (e) {
    if (!dirty) return;
    e.preventDefault();
    var win = window.open("about:blank", "_blank");
    save().then(function (ok) {
      if (ok && win) win.location = pdfBtn.href;
      else if (win) win.close();
    });
  });

  // ---------------------------------------------------------------------------
  // Page markers. The sheet is shown as one continuous page; on paper every
  // page gets the letterhead's header and footer space. Mark where each new
  // page will start, the way Word breaks: before the paragraph or table row
  // that no longer fits (rows never split), and at explicit page breaks.
  // An estimate - Word's own layout can differ by a line.
  // ---------------------------------------------------------------------------
  var sheet = ed.closest(".page");
  var pageCount = document.getElementById("page-count");
  var PX_PER_IN = 96;
  var usable = (Number(ed.dataset.pageHeight) - Number(ed.dataset.marginTop) -
                Number(ed.dataset.marginBottom)) * PX_PER_IN;

  function layoutUnits() {
    // A short "keep" table moves as a whole; other tables break between rows
    var units = [];
    Array.prototype.forEach.call(ed.children, function (el) {
      if (el.tagName === "TABLE" && !(el.classList.contains("keep") && el.offsetHeight <= usable)) {
        units = units.concat(Array.prototype.slice.call(el.rows));
      } else {
        units.push(el);
      }
    });
    return units;
  }

  function markPages() {
    sheet.querySelectorAll(".pg-mark").forEach(function (m) { m.remove(); });
    // No page size from the server (e.g. an older dashboard still running):
    // no markers rather than wrong ones
    if (!(usable > 2 * PX_PER_IN)) { pageCount.textContent = ""; return; }
    var edTop = ed.getBoundingClientRect().top;
    var start = 0, pages = 1, forceNext = false;
    var units = layoutUnits();
    units.forEach(function (el, i) {
      if (el.classList && el.classList.contains("page-break")) { forceNext = true; return; }
      var r = el.getBoundingClientRect();
      var top = r.top - edTop, bottom = r.bottom - edTop;
      if ((forceNext || bottom - start > usable) && top > start) {
        // Headings marked keep-with-next move to the new page with it
        for (var j = i - 1; j >= 0 && units[j].classList && units[j].classList.contains("kwn"); j--) {
          var t = units[j].getBoundingClientRect().top - edTop;
          if (t <= start) break;
          top = t;
        }
        start = top;
        pages += 1;
        var mark = document.createElement("div");
        mark.className = "pg-mark";
        mark.style.top = (ed.offsetTop + top - 3) + "px";
        mark.innerHTML = "<span>Page " + pages + "</span>";
        sheet.appendChild(mark);
      }
      forceNext = false;
    });
    pageCount.textContent = pages === 1 ? "1 page" : pages + " pages";
  }

  var markTimer = null;
  function scheduleMarks() {
    clearTimeout(markTimer);
    markTimer = setTimeout(markPages, 250);
  }
  ed.addEventListener("input", scheduleMarks);
  window.addEventListener("resize", scheduleMarks);
  ed.querySelectorAll("img").forEach(function (img) { img.addEventListener("load", scheduleMarks); });
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(markPages);
  markPages();
  // Re-mark after a save that re-reads the report
  new MutationObserver(function (records) {
    if (records.some(function (r) { return r.target === ed && r.type === "childList" && r.addedNodes.length > 5; })) scheduleMarks();
  }).observe(ed, { childList: true });

  // ---------------------------------------------------------------------------
  // Scan values: click in the report, then click a value to put it there.
  // The editor's last caret position is remembered because clicking the
  // value button moves focus away from the report.
  // ---------------------------------------------------------------------------
  var lastRange = null;

  // A caret in or touching a "____" blank selects the whole blank, so the
  // value replaces it
  function blankAround(range) {
    var node = range.startContainer;
    if (!range.collapsed || node.nodeType !== 3) return range;
    var re = /_{2,}/g, m, at = range.startOffset;
    while ((m = re.exec(node.textContent))) {
      if (at >= m.index && at <= m.index + m[0].length) {
        var r = document.createRange();
        r.setStart(node, m.index);
        r.setEnd(node, m.index + m[0].length);
        return r;
      }
    }
    return range;
  }

  document.addEventListener("selectionchange", function () {
    var sel = window.getSelection();
    if (sel.rangeCount && ed.contains(sel.getRangeAt(0).commonAncestorContainer)) {
      lastRange = sel.getRangeAt(0).cloneRange();
    }
  });
  document.querySelectorAll(".value-chip").forEach(function (chip) {
    chip.addEventListener("mousedown", function (e) { e.preventDefault(); });
    chip.addEventListener("click", function () {
      if (!lastRange) {
        showState("Click in the report where the value goes first", "unsaved");
        return;
      }
      ed.focus();
      var sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(blankAround(lastRange));
      document.execCommand("insertText", false, chip.dataset.value);
      chip.classList.add("used");
      setDirty(true);
    });
  });

  window.__editorDirty = function () { return dirty; };
  window.addEventListener("beforeunload", function (e) {
    if (dirty && !window.__skipUnloadWarning) { e.preventDefault(); e.returnValue = ""; }
  });
})();
