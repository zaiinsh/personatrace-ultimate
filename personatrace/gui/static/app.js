// PersonaTrace dashboard v8.0.0 — live data only by default; demo data only when PERSONATRACE_DEMO=1 is set on the server.
(function () {
  "use strict";
  var inv = null;
  var settings = null;
  var selectedId = null;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function filteredProfiles() {
    var q = (document.getElementById("search").value || "").toLowerCase();
    var sel = Array.prototype.slice.call(
      document.getElementById("platform-filter").selectedOptions).map(function (o) { return o.value; });
    var minConf = parseInt(document.getElementById("confidence-slider").value, 10) || 0;
    var confirmedOnly = document.getElementById("confirmed-only").checked;
    return inv.profiles.filter(function (p) {
      if (q && (p.username + " " + p.platform).toLowerCase().indexOf(q) === -1) return false;
      if (sel.length && sel.indexOf(p.platform) === -1) return false;
      if ((p.confidence || 0) < minConf) return false;
      if (confirmedOnly && p.status !== "confirmed") return false;
      var prov = (document.getElementById("provenance-filter")||{}).value || "";
      if (prov && p.status !== prov) return false;
      return true;
    });
  }

  var nodePos = {};
  var timelineCutoff = null;
  function renderGraph() {
    var profiles = filteredProfiles();
    if (timelineCutoff) {
      profiles = profiles.filter(function (p) {
        return !p.created_at || p.created_at <= timelineCutoff;
      });
    }
    var byId = {};
    profiles.forEach(function (p) { byId[p.node_id] = p; });
    var cx = 320, cy = 230, radii = [0, 80, 140, 195];
    var pos = nodePos;
    var ringCounts = {};
    profiles.forEach(function (p) {
      if (!pos[p.node_id]) {
        var ring = Math.min(p.ring || 1, 3);
        var idx = ringCounts[ring] || 0;
        ringCounts[ring] = idx + 1;
        var siblings = profiles.filter(function (x) { return Math.min(x.ring || 1, 3) === ring; }).length;
        var angle = siblings <= 1 ? -Math.PI / 2 : (idx / siblings) * Math.PI * 2 - Math.PI / 2;
        var r = radii[ring];
        pos[p.node_id] = { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) };
      }
    });
    var edgesEl = document.getElementById("graph-edges");
    var nodesEl = document.getElementById("graph-nodes");
    var ringsSvg = radii.slice(1).map(function (r) {
      return '<circle class="graph-ring" cx="' + cx + '" cy="' + cy + '" r="' + r + '"/>';
    }).join("");
    edgesEl.innerHTML = ringsSvg + inv.edges.filter(function (e) {
      return byId[e.from_id] && byId[e.to_id] && pos[e.from_id] && pos[e.to_id];
    }).map(function (e) {
      var cls = e.band === "High" ? "edge-strong" : (e.band === "Medium" ? "edge-medium" : "edge-weak");
      var a = pos[e.from_id], b = pos[e.to_id];
      return '<line class="' + cls + '" x1="' + a.x + '" y1="' + a.y + '" x2="' + b.x + '" y2="' + b.y + '">' +
        '<title>' + esc(e.kind) + " — " + e.confidence + " (" + e.band + ")</title></line>";
    }).join("");
    nodesEl.innerHTML = profiles.map(function (p) {
      var pt = pos[p.node_id];
      var cls = "node" + (p.ring === 0 ? " seed" : "") + (p.bridge ? " bridge" : "");
      return '<g class="' + cls + '" data-id="' + esc(p.node_id) + '">' +
        '<circle cx="' + pt.x + '" cy="' + pt.y + '" r="' + (p.ring === 0 ? 26 : 18) + '"/>' +
        '<text x="' + pt.x + '" y="' + (pt.y + 32) + '">' + esc(p.username) + "</text></g>";
    }).join("");
    document.getElementById("graph-stats").textContent =
      "Nodes: " + profiles.length + " · Edges: " + inv.edges.length + " · Clusters: " + (new Set(profiles.map(function (p) { return p.platform; }))).size + " platforms shown";
    nodesEl.querySelectorAll(".node").forEach(function (g) {
      g.addEventListener("click", function () { selectProfile(g.getAttribute("data-id")); });
      g.addEventListener("mousedown", function (e) {
        var id = g.getAttribute("data-id");
        var svg = document.getElementById("graph");
        var move = function (ev) {
          var rect = svg.getBoundingClientRect();
          var x = (ev.clientX - rect.left) * (640 / rect.width);
          var y = (ev.clientY - rect.top) * (460 / rect.height);
          pos[id] = { x: x, y: y };
          renderGraph();
        };
        var up = function () { document.removeEventListener("mousemove", move); document.removeEventListener("mouseup", up); };
        document.addEventListener("mousemove", move);
        document.addEventListener("mouseup", up);
        e.preventDefault();
      });
    });
  }

  function renderProfiles() {
    var list = document.getElementById("profile-list");
    list.innerHTML = filteredProfiles().map(function (p) {
      return '<div class="profile-card' + (p.bridge ? " bridge" : "") +
        (p.node_id === selectedId ? " selected" : "") + '" data-id="' + esc(p.node_id) + '">' +
        "<strong>" + esc(p.username) + "</strong> " +
        '<span class="badge">' + esc(p.platform) + "</span> " +
        '<span class="badge">' + esc(p.status) + "</span> " +
        (p.bridge ? '<span class="badge bridge-badge">bridge node</span> ' : "") +
        '<div class="meta">Confidence ' + p.confidence + " — " + esc(p.bio) + "</div>" +
        '<div class="drivers">Why: ' + esc((p.confidence_drivers || []).join("; ")) + "</div></div>";
    }).join("") || "<p>No profiles match the filters.</p>";
    list.querySelectorAll(".profile-card").forEach(function (el) {
      el.addEventListener("click", function () { selectProfile(el.getAttribute("data-id")); });
    });
  }

  function selectProfile(nodeId) {
    selectedId = nodeId;
    var p = inv.profiles.filter(function (x) { return x.node_id === nodeId; })[0];
    var summary = document.getElementById("summary-content");
    if (summary) {
      summary.innerHTML = p ? "<p><strong>Entity:</strong> " + esc(p.username) + "</p>" +
        "<p><strong>Status:</strong> " + esc(p.status) + " · <strong>Created:</strong> " + esc(p.created_at || "unknown") + "</p>" +
        "<p><strong>Bio:</strong> " + esc(p.bio || "") + "</p>" +
        "<p><strong>Followers:</strong> " + esc(String(p.follower_count == null ? "unknown" : p.follower_count)) +
        " · <strong>Following:</strong> " + esc(String(p.following_count == null ? "unknown" : p.following_count)) + "</p>" +
        "<p><strong>Confidence signals:</strong> " + esc((p.confidence_drivers || []).join("; ")) + "</p>" +
        "<p><strong>Interests (from public posts):</strong> " + esc(JSON.stringify((inv.analysis && inv.analysis.behaviour_summary && inv.analysis.behaviour_summary.top_words) || [])) + "</p>" : "<p>Select a profile.</p>";
    }
    renderProfiles();
    var box = document.getElementById("evidence-list");
    if (!p) { box.innerHTML = "<p>Select a profile to see its evidence.</p>"; return; }
    box.innerHTML = "<h3>" + esc(p.username) + " (" + esc(p.platform) + ")</h3>" +
      (p.evidence || []).map(function (e) {
        return '<div class="evidence-item"><strong>' + esc(e.field) + ":</strong> " + esc(e.value) +
          ' — <a href="' + esc(e.source_url) + '">' + esc(e.source_url) + "</a>" +
          '<div class="prov">Captured ' + esc(e.captured_at_utc) + " · method " + esc(e.method) +
          " · confidence " + e.confidence + "</div></div>";
      }).join("");
  }

  function renderTimeline() {
    var slider = document.getElementById("timeline-slider");
    var events = inv.timeline || [];
    if (inv.analysis && inv.analysis.timeline && inv.analysis.timeline.length) {
      events = inv.analysis.timeline.map(function (e) {
        return { ts_utc: e.date || e.ts_utc || "", kind: e.kind || "activity", description: e.title || e.description || "" };
      });
    }
    slider.max = Math.max(events.length - 1, 0);
    var show = function () {
      var ev = events[parseInt(slider.value, 10) || 0];
      document.getElementById("timeline-event").textContent =
        ev ? ev.ts_utc + " — " + ev.kind + ": " + ev.description : "No timeline events.";
      timelineCutoff = ev ? (ev.ts_utc || "").slice(0, 10) : null;
      renderGraph();
    };
    slider.oninput = show;
    var playBtn = document.getElementById("timeline-play");
    if (playBtn) {
      playBtn.onclick = function () {
        var i = 0;
        var timer = setInterval(function () {
          if (i >= events.length) { clearInterval(timer); return; }
          slider.value = i; show(); i++;
        }, 800);
      };
    }
    show();
  }

  function renderAlerts() {
    document.getElementById("alerts-list").innerHTML =
      (inv.alerts || []).map(function (a) {
        return '<div class="alert-item">' + esc(a.ts_utc) + " — " + esc(a.message) + "</div>";
      }).join("") || "<p>No alerts.</p>";
    document.getElementById("possible-list").innerHTML =
      (inv.possible_matches || []).map(function (m, idx) {
        var name = m.profile.username || m.profile.platforms || "?";
        var plat = m.profile.platform || (m.profile.platforms || []).join(", ");
        return "<p>" + esc(name) + " (" + esc(plat) + ") — score " +
          m.score + " — " + esc((m.reasons || []).join(", ")) + " — status: " + esc(m.status) +
          ' <button type="button" onclick="window.__ptMerge(' + idx + ')">Merge</button>' +
          ' <button type="button" onclick="window.__ptReject(' + idx + ')">Reject</button>' +
          ' <button type="button" onclick="window.__ptKeep(' + idx + ')">Keep separate</button></p>';
      }).join("") || "<p>No possible matches queued.</p>";
    window.__ptMerge = function (idx) {
      fetch("/api/review", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ index: idx, action: "merge" }) })
        .then(function (r) { return r.json(); }).then(function (d) { alert(d.message || JSON.stringify(d)); });
    };
    window.__ptReject = function (idx) {
      fetch("/api/review", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ index: idx, action: "reject" }) })
        .then(function (r) { return r.json(); }).then(function (d) { alert(d.message || JSON.stringify(d)); });
    };
    window.__ptKeep = function (idx) {
      fetch("/api/review", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ index: idx, action: "keep" }) })
        .then(function (r) { return r.json(); }).then(function (d) { alert(d.message || JSON.stringify(d)); });
    };
  }

  function renderSettings() {
    var adapters = (settings && settings.adapters) || [];
    var active = adapters.filter(function (a) { return a.status === "active"; });
    var missing = adapters.filter(function (a) { return a.status !== "active"; });
    document.getElementById("before-run-text").textContent =
      active.length + " sources active, " + missing.length + " not checked.";
    document.getElementById("before-run-list").innerHTML =
      adapters.map(function (a) {
        return "<li>" + esc(a.name) + ": " + esc(a.status) +
          (a.status === "active" ? "" : ' — <span class="missing-prompt">' + esc(a.message) + "</span>") + "</li>";
      }).join("");
    document.getElementById("adapter-list").innerHTML =
      adapters.map(function (a) {
        var toggle = a.status === "active"
          ? '<span class="toggle active">Active</span>'
          : '<span class="toggle not-checked">Not checked</span>';
        return '<div class="adapter-row"><strong>' + esc(a.name) + "</strong> " + toggle +
          '<span class="missing-prompt">' + (a.status === "active" ? "" : esc(a.message)) + "</span></div>";
      }).join("");
  }

  function ptBadge(status) {
    status = (status || "").toLowerCase();
    if (status === "found" || status === "active" || status === "ok" || status === "confirmed") {
      return '<span class="pt-badge pt-badge-found">' + esc(status) + '</span>';
    } else if (status === "not_found" || status === "rejected") {
      return '<span class="pt-badge pt-badge-notfound">' + esc(status) + '</span>';
    } else if (status === "not_checked" || status === "pending") {
      return '<span class="pt-badge pt-badge-notchecked">' + esc(status) + '</span>';
    } else if (status === "blocked" || status === "rate_limited" || status === "error") {
      return '<span class="pt-badge pt-badge-warn">' + esc(status) + '</span>';
    }
    return '<span class="pt-badge pt-badge-info">' + esc(status || "unknown") + '</span>';
  }

  function ptChips(items) {
    if (!items || (Array.isArray(items) && items.length === 0)) {
      return '<span class="pt-empty">None recorded</span>';
    }
    if (typeof items === "string") items = [items];
    if (!Array.isArray(items)) {
      items = Object.keys(items).map(function(k) { return k + ": " + items[k]; });
    }
    return '<div class="pt-chip-group">' + items.map(function(it) {
      return '<span class="pt-chip">' + esc(String(it)) + '</span>';
    }).join("") + '</div>';
  }

  function ptFormatList(items, emptyMsg) {
    if (!items || !items.length) {
      return '<p class="pt-empty">' + (emptyMsg || "None detected.") + '</p>';
    }
    return '<ul class="pt-checklist">' + items.map(function(it) {
      var text = typeof it === "object" ? (it.title || it.message || it.detail || it.reason || JSON.stringify(it)) : String(it);
      return '<li class="pt-checklist-item"><span class="pt-checklist-icon">▸</span> <span>' + esc(text) + '</span></li>';
    }).join("") + '</ul>';
  }

  function ptFormatSiteChecks(siteChecks) {
    if (!siteChecks || typeof siteChecks !== "object" || Object.keys(siteChecks).length === 0) {
      return '<p class="pt-empty">No site checks recorded. Run a live search to query supported platforms.</p>';
    }
    var keys = Object.keys(siteChecks).sort();
    var found = [];
    var other = [];
    keys.forEach(function(k) {
      var val = siteChecks[k];
      var status = typeof val === "string" ? val : (val && val.status) || "checked";
      var url = typeof val === "object" && val ? (val.url || "") : "";
      var card = '<div class="pt-site-card">' +
        '<span class="pt-site-name">' + esc(k) + '</span>' +
        ptBadge(status) +
        (url ? ' <a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer" class="pt-site-link">Profile ↗</a>' : '') +
        '</div>';
      if (status === "found") found.push(card);
      else other.push(card);
    });
    var html = '';
    if (found.length) {
      html += '<h4 style="margin:.6rem 0 .4rem;color:var(--green)">✓ Found on ' + found.length + ' Platform(s)</h4>' +
        '<div class="pt-grid-3">' + found.join("") + '</div>';
    }
    if (other.length) {
      html += '<h4 style="margin:1rem 0 .4rem;color:var(--muted)">Other Checked Sources (' + other.length + ')</h4>' +
        '<div class="pt-grid-4">' + other.join("") + '</div>';
    }
    return html;
  }

  function refresh() {
    renderGraph();
    renderProfiles();
    renderCompareSelects();
    renderProgress();
    renderRiskPlanner();
    renderBehaviour();
    renderV2();
    renderQuota();
    renderAnalysis();
  }

  function renderAnalysis() {
    var box = document.getElementById("analysis-content");
    if (!box) return;
    var a = inv && inv.analysis;
    if (!a) { box.innerHTML = '<p class="empty-note">No analysis yet — run a live search.</p>'; return; }

    var summary = a.behaviour_summary || {};
    var platforms = summary.platforms || [];
    var bioDomains = a.bio_domains || {};
    var avatarReuse = a.avatar_reuse || [];
    var languages = a.languages || {};
    var stylometry = a.stylometry || [];
    var bridgePersons = a.bridge_persons || [];
    var githubGroups = a.github_groups || [];

    var footprintHtml = '<div class="pt-card">' +
      '<div class="pt-card-header"><h4>🌐 Cross-Platform Footprint</h4></div>' +
      '<div class="pt-card-body">' +
      '<p><strong>Active Platforms:</strong> ' + (platforms.length ? ptChips(platforms) : '<span class="pt-empty">None confirmed</span>') + '</p>' +
      '<p style="margin-top:.6rem"><strong>Linked Bio Domains:</strong> ' + (Object.keys(bioDomains).length ? ptChips(bioDomains) : '<span class="pt-empty">No external bio links</span>') + '</p>' +
      '</div></div>';

    var identitySignalsHtml = '<div class="pt-card">' +
      '<div class="pt-card-header"><h4>🖼️ Image & Identity Reuse (pHash)</h4></div>' +
      '<div class="pt-card-body">' +
      (avatarReuse.length ?
        '<p><strong>Reused Avatars Detected:</strong></p>' + ptFormatList(avatarReuse) :
        '<p class="pt-empty">No identical image perceptual hash (pHash) reuse across accounts detected.</p>') +
      '</div></div>';

    var contentHtml = '<div class="pt-card">' +
      '<div class="pt-card-header"><h4>🗣️ Language & Content Patterns</h4></div>' +
      '<div class="pt-card-body">' +
      '<p><strong>Detected Languages:</strong> ' + (Object.keys(languages).length ? ptChips(languages) : '<span class="pt-empty">English</span>') + '</p>' +
      (stylometry.length ? '<p><strong>Stylometry Markers:</strong></p>' + ptFormatList(stylometry) : '<p class="pt-empty">Stylometry writing signals neutral (capped weak signal).</p>') +
      '</div></div>';

    var networkHtml = '<div class="pt-card">' +
      '<div class="pt-card-header"><h4>🤝 Network Overlap & Bridge Persons</h4></div>' +
      '<div class="pt-card-body">' +
      (bridgePersons.length ?
        '<p><strong>Bridge Contacts:</strong></p>' + ptChips(bridgePersons) :
        '<p class="pt-empty">No bridge persons connecting distinct identity clusters found.</p>') +
      (githubGroups.length ?
        '<p style="margin-top:.5rem"><strong>Communities & Orgs:</strong></p>' + ptChips(githubGroups) : '') +
      '</div></div>';

    box.innerHTML = '<div class="pt-grid-2">' + footprintHtml + identitySignalsHtml + contentHtml + networkHtml + '</div>';
  }

  function renderProgress() {
    var box = document.getElementById("progress-content");
    if (!box) return;
    fetch("/api/progress").then(function (r) { return r.json(); }).then(function (data) {
      var pct = Math.min(100, Math.max(0, data.progress_percent || 0));
      var stages = data.stages || ["Seed Ingestion", "Profile Enumeration", "Entity Scoring", "Graph Building", "Audit Finalization"];
      var sources = data.sources || [];

      box.innerHTML =
        '<div class="pt-card">' +
          '<div class="pt-card-header">' +
            '<h4>⚡ Real-time Investigation Pipeline</h4>' +
            '<span class="pt-badge pt-badge-info">' + pct + '% Complete</span>' +
          '</div>' +
          '<div class="pt-card-body">' +
            '<div class="pt-progress-container">' +
              '<div class="pt-progress-bar-bg">' +
                '<div class="pt-progress-bar-fill" style="width:' + pct + '%"></div>' +
              '</div>' +
            '</div>' +
            '<div style="display:flex;gap:1.5rem;margin:.6rem 0;font-size:.9rem;flex-wrap:wrap">' +
              '<span><strong>Profiles Found:</strong> ' + esc(String(data.profiles || 0)) + '</span>' +
              '<span><strong>Identity Edges:</strong> ' + esc(String(data.edges || 0)) + '</span>' +
              '<span><strong>Active Sources:</strong> ' + esc(String(sources.length || 0)) + '</span>' +
            '</div>' +
            '<h5 style="margin:.8rem 0 .4rem;color:var(--muted)">Pipeline Stages</h5>' +
            ptChips(stages) +
            (sources.length ?
              '<h5 style="margin:.8rem 0 .4rem;color:var(--muted)">Connected Data Sources</h5>' +
              ptChips(sources) : '') +
          '</div>' +
        '</div>';
    });
  }

  function renderRiskPlanner() {
    var box = document.getElementById("risk-planner-content");
    if (!box) return;
    var a = inv && inv.analysis;
    if (!a) { box.innerHTML = '<p class="empty-note">No analysis yet — run a live search.</p>'; return; }

    var signals = a.risk_signals || [];
    var nextSteps = a.next_steps || [];

    var signalsHtml = '<div class="pt-card">' +
      '<div class="pt-card-header"><h4>🛡️ Risk & Threat Signals</h4>' +
        (signals.length ? '<span class="pt-badge pt-badge-warn">' + signals.length + ' Flag(s)</span>' : '<span class="pt-badge pt-badge-found">Clear</span>') +
      '</div><div class="pt-card-body">' +
      (signals.length ? ptFormatList(signals) : '<p class="pt-empty">No automated manipulation, bot swarm, or high-risk signals detected.</p>') +
      '</div></div>';

    var stepsHtml = '<div class="pt-card">' +
      '<div class="pt-card-header"><h4>📋 Investigator Next Steps</h4> <span class="pt-badge pt-badge-info">Checklist</span></div>' +
      '<div class="pt-card-body">' +
      (nextSteps.length ? ptFormatList(nextSteps) :
        '<ul class="pt-checklist">' +
        '<li class="pt-checklist-item"><span class="pt-checklist-icon">☐</span> <span>Verify pending items in the Possible Matches queue before merging.</span></li>' +
        '<li class="pt-checklist-item"><span class="pt-checklist-icon">☐</span> <span>Inspect Wayback machine profile diffs for retroactive bio modifications.</span></li>' +
        '<li class="pt-checklist-item"><span class="pt-checklist-icon">☐</span> <span>Check WHOIS / DNS SPF & DKIM records if a domain was associated with this user.</span></li>' +
        '<li class="pt-checklist-item"><span class="pt-checklist-icon">☐</span> <span>Human sign-off required prior to exporting case evidence for external review.</span></li>' +
        '</ul>') +
      '</div></div>';

    box.innerHTML = '<div class="pt-grid-2">' + signalsHtml + stepsHtml + '</div>';
  }

  function renderQuota() {
    var banner = document.getElementById("quota-banner");
    var a = inv && inv.analysis;
    if (!banner) return;
    if (a && a.quota_banner) {
      banner.hidden = false;
      banner.textContent = a.quota_banner.text + " Sources: " + (a.quota_banner.sources || []).join(", ");
    } else { banner.hidden = true; }
  }

  function renderBehaviour() {
    var box = document.getElementById("behaviour-content");
    if (!box) return;
    var a = inv && inv.analysis;
    if (!a) { box.innerHTML = '<p class="empty-note">No analysis yet — run a live search.</p>'; return; }

    var bTime = a.behaviour_over_time || {};
    var photos = a.photo_descriptions || {};
    var nativeEntities = a.native_entities || {};
    var commonName = a.common_name_check || {};

    var routineHtml = '<div class="pt-card">' +
      '<div class="pt-card-header"><h4>🕒 Posting Routine & Timeline Activity</h4></div>' +
      '<div class="pt-card-body">' +
      (Object.keys(bTime).length ?
        '<table class="pt-table-styled">' +
        Object.keys(bTime).map(function(k) {
          var v = bTime[k];
          return '<tr><th style="width:40%">' + esc(k.replace(/_/g, " ")) + '</th><td>' + esc(typeof v === "object" ? JSON.stringify(v) : String(v)) + '</td></tr>';
        }).join("") + '</table>' :
        '<p class="pt-empty">No public posting timestamps available from connected sources to calculate daily routines.</p>') +
      '</div></div>';

    var photoHtml = '<div class="pt-card">' +
      '<div class="pt-card-header"><h4>🖼️ Visual & Avatar Clues (Machine Heuristics)</h4></div>' +
      '<div class="pt-card-body">' +
      (Object.keys(photos).length ?
        ptChips(photos) :
        '<p class="pt-empty">No avatar OCR or scene elements extracted (no face recognition used by design).</p>') +
      '</div></div>';

    var entityHtml = '<div class="pt-card">' +
      '<div class="pt-card-header"><h4>🌐 Extracted Entities & Languages</h4></div>' +
      '<div class="pt-card-body">' +
      (Object.keys(nativeEntities).length ?
        ptChips(nativeEntities) :
        '<p class="pt-empty">Standard Latin script detected. No specialized native-script entities isolated.</p>') +
      '</div></div>';

    var nameHtml = '<div class="pt-card">' +
      '<div class="pt-card-header"><h4>🔍 Handle & Name Uniqueness Check</h4></div>' +
      '<div class="pt-card-body">' +
      (Object.keys(commonName).length ?
        '<table class="pt-table-styled">' +
        Object.keys(commonName).map(function(k) {
          return '<tr><th style="width:45%">' + esc(k.replace(/_/g, " ")) + '</th><td>' + esc(String(commonName[k])) + '</td></tr>';
        }).join("") + '</table>' :
        '<p class="pt-empty">Uniqueness heuristic evaluated: distinctive handle pattern.</p>') +
      '</div></div>';

    box.innerHTML = '<div class="pt-grid-2">' + routineHtml + photoHtml + entityHtml + nameHtml + '</div>';
  }

  function renderV2() {
    var box = document.getElementById("v2-content");
    if (!box) return;
    var a = inv && inv.analysis;
    if (!a) { box.innerHTML = '<p class="empty-note">No analysis yet — run a live search.</p>'; return; }

    var siteHtml = '<div class="pt-card">' +
      '<div class="pt-card-header"><h4>🌐 Platform & Site Checks (Two-Signal Verified)</h4></div>' +
      '<div class="pt-card-body">' + ptFormatSiteChecks(a.site_checks) + '</div>' +
      '</div>';

    var variants = a.v2_variants || {};
    var variantKeys = Object.keys(variants);
    var variantList = [];
    variantKeys.forEach(function(k) {
      var arr = variants[k];
      if (Array.isArray(arr)) arr.forEach(function(v) { variantList.push(v); });
      else variantList.push(k + ": " + arr);
    });

    var variantsHtml = '<div class="pt-card">' +
      '<div class="pt-card-header"><h4>🔤 Handle Variations & Leetspeak Scanned</h4> <span class="pt-badge pt-badge-info">' + variantList.length + ' Variations</span></div>' +
      '<div class="pt-card-body">' + ptChips(variantList) + '</div>' +
      '</div>';

    var wayback = a.wayback_profiles || {};
    var waybackKeys = Object.keys(wayback);
    var waybackHtml = '<div class="pt-card">' +
      '<div class="pt-card-header"><h4>🏛️ Wayback Machine & Archival Snapshots</h4></div>' +
      '<div class="pt-card-body">' +
      (waybackKeys.length ?
        '<table class="pt-table-styled"><thead><tr><th>Platform / URL</th><th>Snapshots</th><th>History</th></tr></thead><tbody>' +
        waybackKeys.map(function(k) {
          var item = wayback[k];
          var count = typeof item === "object" && item ? (item.count || item.snapshots || "Found") : String(item);
          var wbUrl = typeof item === "object" && item && item.archive_url ? item.archive_url : ("https://web.archive.org/web/*/" + k);
          return '<tr><td><strong>' + esc(k) + '</strong></td><td><span class="pt-badge pt-badge-found">' + esc(String(count)) + '</span></td><td><a href="' + esc(wbUrl) + '" target="_blank" rel="noopener noreferrer" class="pt-site-link">View archive.org ↗</a></td></tr>';
        }).join("") + '</tbody></table>' :
        '<p class="pt-empty">No historical snapshots found in the Wayback CDX index for these profile URLs.</p>') +
      '</div></div>';

    var dns = a.dns_spf_dkim || {};
    var dnsKeys = Object.keys(dns);
    var dnsHtml = '<div class="pt-card">' +
      '<div class="pt-card-header"><h4>🔒 Domain Infrastructure, SPF & DKIM</h4></div>' +
      '<div class="pt-card-body">' +
      (dnsKeys.length ?
        '<table class="pt-table-styled">' +
        dnsKeys.map(function(k) {
          var val = typeof dns[k] === "object" ? JSON.stringify(dns[k]) : String(dns[k]);
          return '<tr><th style="width:35%">' + esc(k) + '</th><td><code>' + esc(val) + '</code></td></tr>';
        }).join("") + '</table>' :
        '<p class="pt-empty">No custom domain linked directly in the primary profile bio.</p>') +
      '</div></div>';

    var signoff = a.report_signoff || {};
    var reportHtml = '<div class="pt-card">' +
      '<div class="pt-card-header">' +
        '<h4>📑 Investigative Case Report Draft</h4>' +
        (signoff.signed_off ? '<span class="pt-badge pt-badge-found">Signed Off by ' + esc(signoff.signed_by || "Analyst") + '</span>' :
          '<span class="pt-badge pt-badge-notchecked">Pending Sign-off</span>') +
      '</div>' +
      '<div class="pt-card-body">' +
        '<div class="pt-report-box">' + esc(a.report_draft || "Report draft pending profile data collection.") + '</div>' +
        '<div class="pt-action-bar">' +
          (!signoff.signed_off ?
            '<button type="button" class="search-btn btn-small" onclick="window.__ptSignoff()">✍️ Sign Off Report (Human Review)</button>' :
            '<span class="meta">Signed off at ' + esc(signoff.signed_at || "UTC") + '</span>') +
        '</div>' +
      '</div></div>';

    box.innerHTML = siteHtml + '<div class="pt-grid-2">' + variantsHtml + waybackHtml + '</div>' + dnsHtml + reportHtml;

    window.__ptSignoff = function () {
      fetch("/api/signoff", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ signed_by: "analyst" }) })
        .then(function (r) { return r.json(); }).then(function (d) {
          alert(d.message || "Report signed off successfully!");
          if (inv && inv.analysis) {
            inv.analysis.report_signoff = d.report_signoff || { signed_off: true, signed_by: "analyst" };
            renderV2();
          }
        });
    };
  }
  function renderCompareSelects() {
    var a = document.getElementById("compare-a");
    var b = document.getElementById("compare-b");
    if (!a || !b || !inv) return;
    var opts = inv.profiles.map(function (p, i) {
      return '<option value="' + i + '">' + esc(p.platform) + ": " + esc(p.username) + "</option>";
    }).join("");
    a.innerHTML = opts; b.innerHTML = opts;
    if (inv.profiles.length > 1) b.value = "1";
  }

  function renderCost() {
    fetch("/api/cost").then(function (r) { return r.json(); }).then(function (data) {
      var rows = data.cost_before_run || [];
      document.getElementById("cost-text").textContent =
        "Cost before run: " + rows.map(function (r) {
          return r.name + " (" + r.status + ", " +
            (r.cost_units == null ? r.cost_note : r.cost_units + " units") + ")";
        }).join("; ");
      document.getElementById("cost-list").innerHTML = rows.map(function (r) {
        return "<li>" + esc(r.name) + ": " + esc(r.status) + " — " +
          esc(r.cost_units == null ? r.cost_note : String(r.cost_units) + " units") + "</li>";
      }).join("");
    });
  }

  document.getElementById("search").addEventListener("input", refresh);
  document.getElementById("platform-filter").addEventListener("change", refresh);
  document.getElementById("confidence-slider").addEventListener("input", function (e) {
    document.getElementById("confidence-value").textContent = e.target.value;
    refresh();
  });
  document.getElementById("confirmed-only").addEventListener("change", refresh);
  var _provEl = document.getElementById("provenance-filter");
  if (_provEl) _provEl.addEventListener("change", refresh);
  document.getElementById("nav-dashboard").addEventListener("click", function () {
    document.getElementById("dashboard-view").hidden = false;
    document.getElementById("settings-view").hidden = true;
    this.classList.add("active");
    document.getElementById("nav-settings").classList.remove("active");
  });
  document.getElementById("nav-settings").addEventListener("click", function () {
    document.getElementById("dashboard-view").hidden = true;
    document.getElementById("settings-view").hidden = false;
    this.classList.add("active");
    document.getElementById("nav-dashboard").classList.remove("active");
  });
  document.getElementById("key-form").addEventListener("submit", function (e) {
    e.preventDefault();
    var name = document.getElementById("key-name").value;
    var key = document.getElementById("key-value").value;
    fetch("/api/settings/keys", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name, key: key })
    }).then(function (r) { return r.json(); }).then(function (data) {
      document.getElementById("key-result").textContent =
        "Stored key name: " + data.name + " (" + data.stored + "). The value was not echoed back.";
      document.getElementById("key-value").value = "";
      return fetch("/api/settings").then(function (r) { return r.json(); });
    }).then(function (data) { settings = data; renderSettings(); });
  });

  document.getElementById("live-search-form").addEventListener("submit", function (e) {
    e.preventDefault();
    var seed = document.getElementById("live-seed").value;
    var keys = {};
    var yt = document.getElementById("live-youtube-key").value;
    var agg = document.getElementById("live-aggregator-key").value;
    var aggUrl = document.getElementById("live-aggregator-url").value;
    if (yt) keys.youtube_api_key = yt;
    if (agg) keys.licensed_aggregator_key = agg;
    if (aggUrl) keys.licensed_aggregator_base_url = aggUrl;
    var watch = document.getElementById("live-watch-domains").value;
    if (watch) keys.watch_domains = watch;
    document.getElementById("live-search-result").textContent = "Searching live sources…";
    fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        seed: seed,
        seed_type: (function(){var ty=document.getElementById("live-seed-type").value; var sd=document.getElementById("live-seed").value; if((ty==="username"||ty==="auto") && sd.indexOf("@")>0) return "email"; return ty;})(),
        seed_context: (document.getElementById("live-seed-context")||{}).value || "",
        direct: !!((document.getElementById("live-direct")||{}).checked),
        screenshots: !!((document.getElementById("live-screenshots")||{}).checked),
        use_cache: !((document.getElementById("live-cache")||{}).checked === false),
        keys: keys
      })
    }).then(function (r) { return r.json(); }).then(function (data) {
      if (data.error) {
        document.getElementById("live-search-result").textContent = data.error;
        return;
      }
      inv = data.investigation;
      // v6 fix: a live search replaces the initial demo view entirely.
      // Clear the previously selected demo profile first, so a 0-profile
      // live result can never leave demo_user_01 visible as the result.
      selectedId = null;
      document.getElementById("summary-content").innerHTML = "<p>Select a profile to see its summary.</p>";
      document.getElementById("evidence-list").innerHTML = "<p>Select a profile to see its evidence.</p>";
      document.getElementById("mode-badge").textContent =
        data.mode === "live" ? "LIVE — real public sources" : "DEMO DATA";
      document.getElementById("live-search-result").textContent =
        "Found " + inv.profiles.length + " profile(s) for " + inv.seed + ". " +
        data.sources.map(function (s) { return s.platform + ": " + s.status; }).join("; ");
      document.getElementById("live-youtube-key").value = "";
      document.getElementById("live-aggregator-key").value = "";
      refresh();
      renderTimeline();
      renderAlerts();
      renderAnalysis();
      if (inv.profiles.length) selectProfile(inv.profiles[0].node_id);
      else {
        document.getElementById("summary-content").innerHTML =
          "<p><strong>No profiles found for " + esc(inv.seed) + ".</strong> Routes tried: " +
          esc(data.sources.map(function (s) { return s.platform + ": " + s.status; }).join("; ")) +
          ". Instagram / X / TikTok are gated without a key or login — that is not_checked, not not_found. " +
          "Add a key in Settings, enable the login opt-in, or try a search dork. No demo data is shown here.</p>";
      }
    });
  });

  document.getElementById("compare-btn").addEventListener("click", function () {
    var a = inv.profiles[parseInt(document.getElementById("compare-a").value, 10)];
    var b = inv.profiles[parseInt(document.getElementById("compare-b").value, 10)];
    if (!a || !b) return;
    fetch("/api/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ a: a, b: b })
    }).then(function (r) { return r.json(); }).then(function (data) {
      var rows = data.fields.map(function (f) {
        return "<tr><td>" + esc(f) + "</td><td>" + esc(data.a[f]) + "</td><td>" + esc(data.b[f]) + "</td></tr>";
      }).join("");
      document.getElementById("compare-result").innerHTML =
        "<table><tr><th>Field</th><th>First</th><th>Second</th></tr>" + rows + "</table>";
    });
  });

  var exportSel = document.getElementById("export-select");
  if (exportSel) {
    exportSel.addEventListener("change", function () {
      if (this.value) window.open("/api/export?fmt=" + this.value + "&live=1", "_blank");
      this.value = "";
    });
  }
  fetch("/api/investigation").then(function (r) { return r.json(); }).then(function (data) {
    inv = data;
    // v6 UI: if a live search already ran on this server, the reload shows
    // THAT live result (badge + seed + first profile), not the demo badge.
    if (inv.label === "live" && inv.seed) {
      document.getElementById("mode-badge").textContent = "LIVE — real public sources";
      document.getElementById("live-seed").value = inv.seed;
      document.getElementById("live-search-result").textContent =
        "Found " + inv.profiles.length + " profile(s) for " + inv.seed + " (last live search on this server).";
    }
    refresh();
    renderTimeline();
    renderAlerts();
    renderCost();
    if (inv.profiles.length) selectProfile(inv.profiles[0].node_id);
  });
  fetch("/api/settings").then(function (r) { return r.json(); }).then(function (data) {
    settings = data;
    renderSettings();
  });
})();
