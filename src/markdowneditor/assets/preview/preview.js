(() => {
  "use strict";
  let bridge = null;
  let currentRevision = 0;
  let currentTotalLines = 1;
  let suppressScrollReport = false;
  let scrollFrame = 0;
  const alignmentMargin = 18;

  function scrollRatio() {
    const max = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
    return window.scrollY / max;
  }

  function restoreScroll(ratio, report = true) {
    const max = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
    if (!report) suppressScrollReport = true;
    window.scrollTo(0, Math.max(0, Math.min(1, ratio || 0)) * max);
    if (!report) {
      requestAnimationFrame(() => requestAnimationFrame(() => {
        suppressScrollReport = false;
      }));
    }
  }

  function sourceAnchors(totalLines = currentTotalLines) {
    const byLine = new Map();
    for (const element of document.querySelectorAll("#content [data-line]")) {
      const line = Number.parseInt(element.dataset.line || "", 10);
      if (!Number.isFinite(line) || line < 1) continue;
      const y = Math.max(0, window.scrollY + element.getBoundingClientRect().top);
      const current = byLine.get(line);
      if (!current || y < current.y) byLine.set(line, { line, y });
    }
    const anchors = Array.from(byLine.values()).sort((a, b) => a.line - b.line);
    if (!anchors.length) return anchors;
    if (anchors[0].line > 1) anchors.unshift({ line: 1, y: 0 });
    const boundedTotal = Math.max(1, Number(totalLines) || 1);
    if (anchors[anchors.length - 1].line < boundedTotal) {
      const maxScroll = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
      anchors.push({ line: boundedTotal, y: maxScroll + alignmentMargin });
    }
    return anchors;
  }

  function interpolateY(line, anchors) {
    let before = anchors[0];
    let after = anchors[anchors.length - 1];
    for (const anchor of anchors) {
      if (anchor.line <= line) before = anchor;
      if (anchor.line >= line) {
        after = anchor;
        break;
      }
    }
    if (after.line === before.line || after.y <= before.y) return before.y;
    const fraction = Math.max(0, Math.min(1, (line - before.line) / (after.line - before.line)));
    return before.y + fraction * (after.y - before.y);
  }

  function sourceLineAtScroll() {
    const anchors = sourceAnchors();
    if (!anchors.length) {
      return 1 + scrollRatio() * Math.max(0, currentTotalLines - 1);
    }
    const y = window.scrollY + alignmentMargin;
    let before = anchors[0];
    let after = anchors[anchors.length - 1];
    for (const anchor of anchors) {
      if (anchor.y <= y) before = anchor;
      if (anchor.y >= y) {
        after = anchor;
        break;
      }
    }
    if (after.y === before.y || after.line <= before.line) return before.line;
    const fraction = Math.max(0, Math.min(1, (y - before.y) / (after.y - before.y)));
    return before.line + fraction * (after.line - before.line);
  }

  function alignToSourceLine(line, totalLines, fallbackRatio = 0) {
    currentTotalLines = Math.max(1, Number(totalLines) || 1);
    const requestedLine = Math.max(1, Math.min(currentTotalLines, Number(line) || 1));
    const anchors = sourceAnchors(currentTotalLines);
    if (!anchors.length) {
      restoreScroll(fallbackRatio, false);
      return { ok: true, mode: "ratio-fallback", requestedLine, targetY: window.scrollY };
    }
    const maxScroll = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
    const targetY = Math.max(
      0,
      Math.min(maxScroll, interpolateY(requestedLine, anchors) - alignmentMargin)
    );
    suppressScrollReport = true;
    window.scrollTo(0, targetY);
    requestAnimationFrame(() => requestAnimationFrame(() => {
      suppressScrollReport = false;
    }));
    return {
      ok: true,
      mode: "source-line",
      requestedLine,
      targetY,
      firstAnchorLine: anchors[0].line,
      lastAnchorLine: anchors[anchors.length - 1].line
    };
  }

  function markImages() {
    const images = Array.from(document.querySelectorAll("#content img"));
    for (const img of images) {
      if (img.dataset.externalBlocked === "true") {
        const box = document.createElement("div");
        box.className = "external-image-blocked";
        box.textContent = "외부 이미지가 차단되었습니다.";
        img.replaceWith(box);
        continue;
      }
      const showError = () => {
        if (img.dataset.errorShown) return;
        img.dataset.errorShown = "true";
        img.style.display = "none";
        const box = document.createElement("div");
        box.className = "image-error";
        box.textContent = `이미지를 찾을 수 없음: ${img.getAttribute("src") || "(경로 없음)"}`;
        img.insertAdjacentElement("afterend", box);
      };
      img.addEventListener("error", showError, { once: true });
      if (img.complete && img.naturalWidth === 0) showError();
    }
  }

  async function waitForImages() {
    const images = Array.from(document.querySelectorAll("#content img"));
    await Promise.all(images.map((img) => {
      if (img.complete) return Promise.resolve();
      return new Promise((resolve) => {
        const done = () => resolve();
        img.addEventListener("load", done, { once: true });
        img.addEventListener("error", done, { once: true });
        window.setTimeout(done, 5000);
      });
    }));
  }

  async function renderMermaid() {
    const nodes = Array.from(document.querySelectorAll("#content pre.mermaid"));
    let ok = 0;
    let errors = 0;
    if (!window.mermaid) {
      for (const node of nodes) {
        node.className = "mermaid-error";
        node.textContent = `Mermaid 엔진을 불러오지 못했습니다.\n${node.textContent}`;
        errors += 1;
      }
      return { ok, errors };
    }
    const darkMode = document.documentElement.dataset.theme === "dark";
    const darkThemeVariables = {
      background: "#15171a",
      primaryColor: "#252a31",
      primaryTextColor: "#f4f6f8",
      primaryBorderColor: "#94a3b8",
      secondaryColor: "#1f2937",
      tertiaryColor: "#334155",
      textColor: "#f4f6f8",
      lineColor: "#d9e2f0",
      edgeLabelBackground: "#15171a",
      actorBkg: "#252a31",
      actorBorder: "#94a3b8",
      actorLineColor: "#94a3b8",
      actorTextColor: "#f4f6f8",
      signalColor: "#d9e2f0",
      signalTextColor: "#f4f6f8",
      labelBoxBkgColor: "#252a31",
      labelBoxBorderColor: "#64748b",
      labelTextColor: "#f4f6f8",
      loopTextColor: "#f4f6f8",
      sequenceNumberColor: "#f4f6f8",
      noteBkgColor: "#3a3320",
      noteBorderColor: "#d6b85d",
      noteTextColor: "#fff7d6",
      activationBkgColor: "#334155",
      activationBorderColor: "#cbd5e1"
    };
    window.mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      fontFamily: "Pretendard",
      theme: darkMode ? "base" : "default",
      themeVariables: darkMode ? darkThemeVariables : {}
    });
    for (let i = 0; i < nodes.length; i += 1) {
      const node = nodes[i];
      const source = node.textContent;
      try {
        const id = `mdeditor-mermaid-${currentRevision}-${i}`;
        const result = await window.mermaid.render(id, source);
        const holder = document.createElement("div");
        holder.className = "mermaid-rendered";
        holder.innerHTML = result.svg;
        node.replaceWith(holder);
        if (result.bindFunctions) result.bindFunctions(holder);
        ok += 1;
      } catch (error) {
        node.className = "mermaid-error";
        node.textContent = `Mermaid 문법 오류\n${String(error && error.message ? error.message : error)}\n\n${source}`;
        document.querySelectorAll("body > [id^='dmermaid-'], body > svg[id^='dmermaid-']").forEach((item) => item.remove());
        errors += 1;
      }
    }
    return { ok, errors };
  }

  function parseCssColor(value) {
    const match = String(value || "").match(/rgba?\(([^)]+)\)/i);
    if (!match) return null;
    const channels = match[1].split(/[,\s/]+/).filter(Boolean).map(Number);
    if (channels.length < 3 || channels.slice(0, 3).some((item) => !Number.isFinite(item))) {
      return null;
    }
    return channels.slice(0, 3).map((item) => Math.max(0, Math.min(255, item)));
  }

  function relativeLuminance(rgb) {
    const linear = rgb.map((value) => {
      const channel = value / 255;
      return channel <= 0.04045
        ? channel / 12.92
        : ((channel + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
  }

  function contrastRatio(foreground, background) {
    const foregroundRgb = parseCssColor(foreground);
    const backgroundRgb = parseCssColor(background);
    if (!foregroundRgb || !backgroundRgb) return null;
    const foregroundLuminance = relativeLuminance(foregroundRgb);
    const backgroundLuminance = relativeLuminance(backgroundRgb);
    const lighter = Math.max(foregroundLuminance, backgroundLuminance);
    const darker = Math.min(foregroundLuminance, backgroundLuminance);
    return (lighter + 0.05) / (darker + 0.05);
  }

  function mermaidContrastStats() {
    const background = getComputedStyle(document.body).backgroundColor;
    const probes = [
      { name: "flowchartLine", selector: ".flowchart-link", property: "stroke" },
      { name: "arrowhead", selector: "marker path", property: "fill" },
      {
        name: "flowchartLabel",
        selector: ".edgeLabel span, .edgeLabel p, .edgeLabel text, .edgeLabel",
        property: "color"
      },
      {
        name: "sequenceLine",
        selector: ".messageLine0, .messageLine1",
        property: "stroke"
      },
      { name: "sequenceText", selector: ".messageText", property: "fill" }
    ];
    const samples = [];
    const missing = [];
    for (const probe of probes) {
      const element = document.querySelector(`.mermaid-rendered svg ${probe.selector}`);
      if (!element) {
        missing.push(probe.name);
        continue;
      }
      const style = getComputedStyle(element);
      let color = style.getPropertyValue(probe.property);
      if (!parseCssColor(color) && probe.property === "color") color = style.fill;
      const ratio = contrastRatio(color, background);
      if (ratio === null) {
        missing.push(probe.name);
        continue;
      }
      samples.push({ name: probe.name, color, background, ratio });
    }
    return {
      theme: document.documentElement.dataset.theme || "light",
      background,
      minimumRatio: samples.length ? Math.min(...samples.map((sample) => sample.ratio)) : null,
      samples,
      missing
    };
  }

  function stats(mermaidStats = { ok: 0, errors: 0 }) {
    const images = Array.from(document.querySelectorAll("#content img"));
    return {
      revision: currentRevision,
      tables: document.querySelectorAll("#content table").length,
      images: images.length,
      imagesLoaded: images.filter((img) => img.complete && img.naturalWidth > 0).length,
      imageErrors: document.querySelectorAll(".image-error").length,
      headings: document.querySelectorAll("#content h1,#content h2,#content h3,#content h4,#content h5,#content h6").length,
      mermaidSvg: document.querySelectorAll(".mermaid-rendered svg").length,
      mermaidErrors: mermaidStats.errors,
      mermaidContrast: mermaidContrastStats(),
      scriptPwned: Boolean(window.__pwned),
      contentLength: document.getElementById("content").innerText.length,
      url: window.location.href
    };
  }

  async function updateContent(markup, ratio, revision, totalLines = 1) {
    currentRevision = revision;
    currentTotalLines = Math.max(1, Number(totalLines) || 1);
    window.__markdownEditorBusy = true;
    const content = document.getElementById("content");
    content.innerHTML = markup;
    markImages();
    await waitForImages();
    const mermaidStats = await renderMermaid();
    requestAnimationFrame(() => {
      restoreScroll(ratio, false);
      const value = stats(mermaidStats);
      value.busy = false;
      window.__markdownEditorBusy = false;
      window.__lastMarkdownEditorStats = value;
      if (bridge) bridge.renderComplete(JSON.stringify(value));
    });
  }

  document.addEventListener("click", (event) => {
    const anchor = event.target.closest("a");
    if (!anchor) return;
    event.preventDefault();
    const raw = anchor.getAttribute("href") || "";
    if (raw.startsWith("#")) {
      const id = decodeURIComponent(raw.slice(1));
      const target = document.getElementById(id) || document.querySelector(`[name="${CSS.escape(id)}"]`);
      if (target) target.scrollIntoView({ block: "start" });
      else if (bridge) bridge.reportMessage(`문서 안에서 '${raw}'을 찾을 수 없습니다.`);
      return;
    }
    if (bridge) bridge.openLink(raw);
  });

  window.addEventListener("scroll", () => {
    if (suppressScrollReport || !bridge) return;
    if (scrollFrame) cancelAnimationFrame(scrollFrame);
    scrollFrame = requestAnimationFrame(() => {
      scrollFrame = 0;
      if (!suppressScrollReport && bridge) {
        bridge.scrollSourceLineChanged(sourceLineAtScroll());
        bridge.scrollChanged(scrollRatio());
      }
    });
  }, { passive: true });

  window.markdownEditorUpdate = updateContent;
  window.markdownEditorScrollRatio = scrollRatio;
  window.markdownEditorSetScrollRatio = restoreScroll;
  window.markdownEditorSourceLineAtTop = sourceLineAtScroll;
  window.markdownEditorAlignToSourceLine = alignToSourceLine;
  window.markdownEditorMermaidContrast = mermaidContrastStats;
  window.markdownEditorStats = () => {
    const value = window.__lastMarkdownEditorStats || stats();
    value.busy = Boolean(window.__markdownEditorBusy);
    return value;
  };

  if (window.qt && window.QWebChannel) {
    new QWebChannel(qt.webChannelTransport, (channel) => {
      bridge = channel.objects.bridge;
      bridge.shellReady();
    });
  }
})();
