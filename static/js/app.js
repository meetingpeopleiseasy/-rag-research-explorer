document.addEventListener("click", async function (event) {
  if (event.target.classList.contains("copy-cite")) {
    try {
      await navigator.clipboard.writeText(event.target.dataset.text || "");
      event.target.textContent = "Copied";
    } catch (error) {
      event.target.textContent = "Copy failed";
    }
    return;
  }

  const button = event.target.closest("[data-analysis]");
  if (!button) return;

  const paperId = button.dataset.paperId;
  const analysisType = button.dataset.analysis;
  const output = document.querySelector(".ai-output");
  if (!output) return;

  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "…";
  output.textContent = "Analyzing…";
  try {
    const response = await fetch("/api/ai/paper-analysis", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paper_id: paperId, analysis_type: analysisType }),
    });
    const data = await response.json();
    if (!response.ok) {
      output.textContent = data.error || "Analysis failed.";
      return;
    }
    output.innerHTML = safeMarkdown(data.content);
  } catch (error) {
    output.textContent = "Analysis failed. Please try again.";
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
});

async function loadCollections() {
  const selects = document.querySelectorAll(".collection-select");
  if (!selects.length) return;
  try {
    const response = await fetch("/api/collections");
    const data = await response.json();
    const options = data.collections || [];
    for (const select of selects) {
      select.innerHTML =
        '<option value="">Choose collection…</option>' +
        options
          .map((collection) => `<option value="${collection.id}">${escapeHtml(collection.name)}</option>`)
          .join("");
    }
  } catch (error) {
    // Collections are optional; leave the select empty on failure.
  }
}

function showToast(message) {
  let toast = document.getElementById("toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "toast";
    toast.setAttribute("role", "status");
    document.body.appendChild(toast);
  }
  toast.textContent = message;
  toast.classList.add("visible");
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => toast.classList.remove("visible"), 2200);
}

async function addPapers(collectionId, paperIds) {
  for (const paperId of paperIds) {
    await fetch(`/api/collections/${collectionId}/papers`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paper_id: paperId }),
    });
  }
}

document.addEventListener("DOMContentLoaded", loadCollections);

function updateBulkActions() {
  const count = selectedPaperIds().length;
  for (const id of ["overview-btn", "qa-btn", "add-selected-btn"]) {
    const button = document.getElementById(id);
    if (button) button.disabled = count === 0;
  }
}

document.addEventListener("change", function (event) {
  if (event.target.classList.contains("select-paper")) {
    updateBulkActions();
  }
  if (event.target.classList.contains("reading-status")) {
    const collectionId = event.target.dataset.collection;
    const paperId = event.target.dataset.paperId;
    fetch(`/api/collections/${collectionId}/papers/${encodeURIComponent(paperId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reading_status: event.target.value }),
    });
  }
});

document.addEventListener("submit", async function (event) {
  if (event.target.id !== "create-collection") return;
  event.preventDefault();
  const form = event.target;
  const message = document.getElementById("collection-message");
  const name = form.elements.name.value.trim();
  const description = form.elements.description.value.trim();
  if (!name) {
    message.textContent = "Collection name is required.";
    return;
  }
  try {
    const response = await fetch("/api/collections", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, description }),
    });
    const data = await response.json();
    if (!response.ok) {
      message.textContent = data.error || "Could not create collection.";
      return;
    }
    window.location.reload();
  } catch (error) {
    message.textContent = "Could not create collection. Please try again.";
  }
});

document.addEventListener("click", async function (event) {
  if (event.target.classList.contains("add-to-collection")) {
    const select = document.querySelector("[data-collection-select]");
    const collectionId = select && select.value;
    if (!collectionId) {
      showToast("Choose a collection first.");
      return;
    }
    await addPapers(collectionId, [event.target.dataset.paperId]);
    showToast("Added to collection.");
  }

  if (event.target.classList.contains("quick-save")) {
    const response = await fetch("/api/collections/quick-save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paper_id: event.target.dataset.paperId }),
    });
    const data = await response.json();
    if (!response.ok) {
      showToast(data.error || "Could not save.");
      return;
    }
    showToast(`Saved to ${data.collection_name}.`);
  }

  if (event.target.id === "add-selected-btn") {
    const select = document.getElementById("collection-select");
    const collectionId = select && select.value;
    if (!collectionId) {
      showToast("Choose a collection first.");
      return;
    }
    const ids = selectedPaperIds();
    if (event.target.dataset.seedId) ids.unshift(event.target.dataset.seedId);
    if (!ids.length) {
      showToast("Select at least one paper.");
      return;
    }
    await addPapers(collectionId, [...new Set(ids)]);
    showToast("Added to collection.");
  }

  if (event.target.classList.contains("remove-paper")) {
    const collectionId = event.target.dataset.collection;
    const paperId = event.target.dataset.paperId;
    await fetch(`/api/collections/${collectionId}/papers/${encodeURIComponent(paperId)}`, {
      method: "DELETE",
    });
    window.location.reload();
  }

  if (event.target.id === "export-cite-btn") {
    const collectionId = window.location.pathname.split("/").pop();
    const output = document.getElementById("export-output");
    const response = await fetch(`/api/collections/${collectionId}/export`);
    const data = await response.json();
    const citations = data.citations || [];
    output.innerHTML =
      "<h3>APA</h3><ol>" +
      citations.map((c) => `<li>${escapeHtml(c.apa)}</li>`).join("") +
      "</ol><h3>IEEE</h3><ol>" +
      citations.map((c) => `<li>${escapeHtml(c.ieee)}</li>`).join("") +
      "</ol>";
  }

  if (event.target.id === "compare-btn") {
    const ids = selectedPaperIds();
    if (ids.length < 2 || ids.length > 5) {
      const output = document.getElementById("compare-output");
      output.textContent = "Select between 2 and 5 papers to compare.";
      return;
    }
    const output = document.getElementById("compare-output");
    event.target.disabled = true;
    event.target.textContent = "Comparing…";
    output.textContent = "Comparing…";
    try {
      const response = await fetch("/api/ai/compare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paper_ids: ids }),
      });
      const data = await response.json();
      if (!response.ok) {
        output.textContent = data.error || "Comparison failed.";
        return;
      }
      output.innerHTML = renderComparison(data);
    } catch (error) {
      output.textContent = "Comparison failed. Please try again.";
    } finally {
      event.target.disabled = false;
      event.target.textContent = "Compare selected (2–5)";
    }
  }
});

function renderComparison(data) {
  const structured = data.structured;
  const citations = data.citations || [];
  if (!structured || !Array.isArray(structured.dimensions)) {
    return safeMarkdown(data.content || "");
  }
  const header =
    "<tr><th>Dimension</th>" +
    citations.map((citation) => `<th>${escapeHtml(citation.marker)}</th>`).join("") +
    "</tr>";
  const body = structured.dimensions
    .map((dimension) => {
      const cells = citations
        .map((citation) => {
          const value = (dimension.cells && dimension.cells[citation.marker]) || "insufficient_information";
          return `<td>${escapeHtml(value)}</td>`;
        })
        .join("");
      return `<tr><th>${escapeHtml(dimension.dimension)}</th>${cells}</tr>`;
    })
    .join("");
  return `<table class="compare-table"><thead>${header}</thead><tbody>${body}</tbody></table>`;
}

function renderOverview(data) {
  let html = "";
  if (data.structured && typeof data.structured === "object") {
    for (const key of Object.keys(data.structured)) {
      const value = data.structured[key];
      html += `<details class="overview-section" open><summary>${escapeHtml(key)}</summary>`;
      if (Array.isArray(value)) {
        html += "<ul>" + value.map((item) => `<li>${escapeHtml(String(item))}</li>`).join("") + "</ul>";
      } else if (value && typeof value === "object") {
        html += "<ul>" + Object.entries(value)
          .map(([marker, text]) => `<li><strong>${escapeHtml(marker)}</strong>: ${escapeHtml(String(text))}</li>`)
          .join("") + "</ul>";
      } else {
        html += `<p>${escapeHtml(String(value))}</p>`;
      }
      html += "</details>";
    }
  } else {
    html = safeMarkdown(data.content || "");
  }
  if (data.citations && data.citations.length) {
    html += "<h3>Citations</h3><ol class=\"citation-list\">" + data.citations
      .map((citation) => {
        const detail = `/paper/${encodeURIComponent(citation.paper_id)}`;
        const doiLink = citation.doi_url
          ? `<a href="${escapeHtml(citation.doi_url)}" target="_blank" rel="noopener">DOI</a>`
          : "DOI: [missing]";
        return `<li><a href="${detail}">[${escapeHtml(citation.marker)}]</a> ${escapeHtml(citation.title)} (${escapeHtml(String(citation.year))}) · ${doiLink}</li>`;
      })
      .join("") + "</ol>";
  }
  return html;
}

let overviewContextId = null;

document.addEventListener("click", async function (event) {
  const context = document.getElementById("overview-context");
  if (!context) return;
  const paperIds = JSON.parse(context.dataset.paperIds || "[]");
  const status = document.getElementById("overview-status");

  if (event.target.id === "generate-overview") {
    const output = document.getElementById("overview-output");
    event.target.disabled = true;
    event.target.textContent = "Generating…";
    output.textContent = "Generating…";
    try {
      const response = await fetch("/api/ai/research-overview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: currentQuery(), paper_ids: paperIds }),
      });
      const data = await response.json();
      if (!response.ok) {
        output.textContent = data.error || "Generation failed.";
        return;
      }
      overviewContextId = data.context_id;
      if (status) status.textContent = `Based on ${data.context.paper_count} papers.`;
      output.innerHTML = renderOverview(data);
      const clear = document.getElementById("clear-context");
      if (clear) clear.disabled = false;
    } catch (error) {
      output.textContent = "Generation failed. Please try again.";
    } finally {
      event.target.disabled = false;
      event.target.textContent = "Generate Research Overview";
    }
  }

  if (event.target.id === "followup-btn") {
    const question = document.getElementById("followup-question").value.trim();
    if (!question) return;
    const output = document.getElementById("followup-output");
    event.target.disabled = true;
    event.target.textContent = "…";
    output.textContent = "Thinking…";
    try {
      const response = await fetch("/api/ai/qa", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, context_id: overviewContextId }),
      });
      const data = await response.json();
      if (!response.ok) {
        output.textContent = data.error || "Question failed.";
        return;
      }
      let html = safeMarkdown(data.content || "");
      if (data.citations && data.citations.length) {
        html += "<p class=\"small\">Sources: " + data.citations
          .map((c) => `<a href="/paper/${encodeURIComponent(c.paper_id)}">[${escapeHtml(c.marker)}]</a>`)
          .join(" ") + "</p>";
      }
      output.innerHTML = html;
    } catch (error) {
      output.textContent = "Question failed. Please try again.";
    } finally {
      event.target.disabled = false;
      event.target.textContent = "Ask";
    }
  }

  if (event.target.id === "clear-context") {
    if (overviewContextId) {
      await fetch(`/api/ai/context/${overviewContextId}`, { method: "DELETE" });
      overviewContextId = null;
    }
    document.getElementById("overview-output").innerHTML = "";
    document.getElementById("followup-output").innerHTML = "";
    if (status) status.textContent = "";
    event.target.disabled = true;
  }
});

function selectedPaperIds() {
  return Array.from(document.querySelectorAll(".select-paper:checked")).map(
    (checkbox) => checkbox.value
  );
}

function currentQuery() {
  const input = document.querySelector('input[name="q"]');
  return input ? input.value : "";
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function safeMarkdown(text) {
  const escaped = escapeHtml(text);
  const lines = escaped.split(/\r?\n/);
  const html = [];
  let listOpen = false;
  let paragraph = [];
  const inline = (value) => value.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  const flushParagraph = () => {
    if (paragraph.length) {
      html.push("<p>" + paragraph.join("<br>") + "</p>");
      paragraph = [];
    }
  };

  for (const line of lines) {
    if (/^\s*[-*]\s+/.test(line)) {
      flushParagraph();
      if (!listOpen) {
        html.push("<ul>");
        listOpen = true;
      }
      html.push("<li>" + inline(line.replace(/^\s*[-*]\s+/, "")) + "</li>");
      continue;
    }
    if (listOpen) {
      html.push("</ul>");
      listOpen = false;
    }
    if (/^\s*#\s+/.test(line)) {
      flushParagraph();
      html.push("<h1>" + inline(line.replace(/^\s*#\s+/, "")) + "</h1>");
    } else if (/^\s*##\s+/.test(line)) {
      flushParagraph();
      html.push("<h2>" + inline(line.replace(/^\s*##\s+/, "")) + "</h2>");
    } else if (/^\s*###\s+/.test(line)) {
      flushParagraph();
      html.push("<h3>" + inline(line.replace(/^\s*###\s+/, "")) + "</h3>");
    } else if (line.trim() === "") {
      flushParagraph();
    } else {
      paragraph.push(inline(line));
    }
  }
  flushParagraph();
  if (listOpen) html.push("</ul>");
  return html.join("");
}

async function postAi(url, payload, output) {
  output.textContent = "Generating…";
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      output.textContent = data.error || "Request failed.";
      return;
    }
    let text = data.content || "";
    if (data.citations && data.citations.length) {
      text += "\n\nCitations:\n" + data.citations
        .map((citation) => `${citation.marker}: ${citation.title} (${citation.year})`)
        .join("\n");
    }
    output.innerHTML = safeMarkdown(text);
  } catch (error) {
    output.textContent = "Request failed. Please try again.";
  }
}

document.addEventListener("click", async function (event) {
  const output = document.getElementById("ai-output");
  if (!output) return;

  if (event.target.id === "overview-btn") {
    const ids = selectedPaperIds();
    if (!ids.length) {
      output.textContent = "Select at least one paper.";
      return;
    }
    await postAi("/api/ai/research-overview", { query: currentQuery(), paper_ids: ids }, output);
  }

  if (event.target.id === "qa-btn") {
    const question = document.getElementById("qa-question").value.trim();
    const ids = selectedPaperIds();
    if (!question) {
      output.textContent = "Enter a question.";
      return;
    }
    if (!ids.length) {
      output.textContent = "Select at least one paper.";
      return;
    }
    await postAi("/api/ai/qa", { question: question, paper_ids: ids }, output);
  }
});
