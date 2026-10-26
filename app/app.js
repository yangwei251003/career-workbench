"use strict";

(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
  const arr = value => Array.isArray(value) ? value : [];
  const text = value => typeof value === "string" || typeof value === "number" ? String(value) : "";
  const pretty = value => text(value) || "尚未填写";
  const icons = {
    overview:'<path d="M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z"/>',
    roadmap:'<path d="M5 4v16M5 6h12l-3 4 3 4H5M3 20h8"/>',
    projects:'<path d="M4 4h16v16H4zM4 9h16M9 9v11"/>',
    evidence:'<path d="M6 3h9l4 4v14H6zM14 3v5h5M9 12h7M9 16h5"/>',
    facts:'<path d="M12 3 3 7v6c0 4 9 8 9 8s9-4 9-8V7zM8 12l3 3 5-6"/>',
    decisions:'<path d="M4 5h16v12H9l-5 4zM8 9h8M8 13h5"/>',
    backup:'<path d="M4 15v5h16v-5M12 3v12M7 10l5 5 5-5"/>',
    close:'<path d="m6 6 12 12M18 6 6 18"/>',
    star:'<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9z"/>',
    arrow:'<path d="M4 12h16m-6-6 6 6-6 6"/>',
    plus:'<path d="M12 5v14M5 12h14"/>',
    download:'<path d="M4 15v5h16v-5M12 3v12M7 10l5 5 5-5"/>',
    copy:'<rect x="8" y="8" width="12" height="13" rx="1"/><path d="M16 8V3H3v13h5"/>'
  };
  const icon = (name, filled = false) => `<svg viewBox="0 0 24 24" aria-hidden="true" fill="${filled ? "currentColor" : "none"}" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${icons[name] || icons.arrow}</svg>`;
  const views = [
    ["overview", "概览", "01"], ["roadmap", "十年路线", "02"], ["projects", "40 项目库", "03"],
    ["evidence", "成果证据", "04"], ["facts", "事实中心", "05"], ["decisions", "决策复盘", "06"], ["backup", "备份与导出", "07"]
  ];
  const readinessLabels = {now:"现在可做",conditional:"条件成熟再做",blueprint:"先存蓝图",extend:"延续已有项目"};
  const statusLabels = {idea:"候选想法",active:"正在推进",validated:"已有验证",paused:"暂缓推进",archived:"已归档"};
  const evidenceLabels = {documented:"有材料支持",self_reported:"本人陈述",pending:"待补证据",demo:"演示 / 模拟成果"};
  const factLabels = {pending:"待确认",confirmed:"已确认",retired:"已退役"};
  const flagLabels = {expired:"已到期",conflict:"存在冲突",pending:"待确认",missing_expiry:"未设置有效期",missing_validity:"未设置有效期",missing_source:"缺少来源",retired:"已退役",due_soon:"即将到期",unconfirmed:"尚未确认"};
  let store = null;
  let currentView = "overview";
  let decisionTab = "decisions";
  let factFilter = "all";
  let evidenceQuery = "";
  let evidenceStatus = "";
  let filters = {query:"",category:"",readiness:"",horizon:"",favorite:false};
  let activeProjectId = null;
  let projectRevision = 0;
  let editorContext = null;
  let importBackup = null;
  let importRevision = null;
  let importFileName = "";
  let importSequence = 0;
  let toastTimer = null;

  function badge(label, tone = "") { return `<span class="badge ${esc(tone)}">${esc(label)}</span>`; }
  function readinessBadge(value) { return badge(readinessLabels[value] || value, value === "now" || value === "extend" ? "green" : value === "conditional" ? "copper" : ""); }
  function stateOf(id) { return store.state.projectStates?.[id] || {status:"idea",favorite:false,notes:""}; }
  function projectById(id) { return arr(store.catalog.projects).find(project => String(project.id) === String(id)); }
  function titleForProject(id) { return projectById(id)?.name || `项目 ${id}`; }
  function currentDate() { return store?.today || new Date().toLocaleDateString("sv-SE"); }
  function plusDays(days) { const date = new Date(`${currentDate()}T12:00:00`); date.setDate(date.getDate() + days); return date.toLocaleDateString("sv-SE"); }
  function isSoon(date) { return /^\d{4}-\d{2}-\d{2}$/.test(date || "") && date >= currentDate() && date <= plusDays(30); }
  function dateBadge(date, prefix = "复盘") { return !date ? badge(`未设${prefix}日期`) : date < currentDate() ? badge(`${prefix}已到期 · ${date}`, "red") : isSoon(date) ? badge(`${prefix}临近 · ${date}`, "copper") : badge(`${prefix} · ${date}`); }

  function notify(message, error = false) {
    clearTimeout(toastTimer);
    $("#toast-region").innerHTML = `<div class="toast ${error ? "error" : ""}" ${error ? 'role="alert"' : ""}><button type="button" aria-label="关闭提示" data-action="dismiss-toast">×</button>${esc(message)}</div>`;
    toastTimer = setTimeout(() => { $("#toast-region").innerHTML = ""; }, error ? 12000 : 5500);
  }

  async function responseError(response) {
    let message = "操作没有完成，请稍后重试。";
    try { const body = await response.json(); message = body.error || message; } catch { /* A non-JSON service error still has a useful status. */ }
    const error = new Error(message); error.status = response.status; return error;
  }

  async function api(path, body) {
    const options = {method: body === undefined ? "GET" : "POST",headers:{"Accept":"application/json"},cache:"no-store"};
    if (body !== undefined) { options.headers["Content-Type"] = "application/json"; options.headers["X-App-Token"] = store.token; options.body = JSON.stringify(body); }
    let response;
    try { response = await fetch(path, options); } catch { throw new Error("暂时无法连接本机工作台。请重新运行“启动工作台.cmd”后重试；你填写的内容仍会保留。"); }
    if (!response.ok) throw await responseError(response);
    return response.json();
  }

  function updateState(result) {
    if (result.state) store.state = result.state;
    if (result.derived) store.derived = result.derived;
  }

  async function bootstrap(initial = false) {
    try {
      const data = await api("/api/bootstrap");
      if (!data.catalog || !data.state || !data.token) throw new Error("工作台资料不完整，请重新启动后再试。");
      store = data;
      $("#profile-name").textContent = data.catalog.profile?.name || "示例用户";
      $("#today-label").textContent = String(data.today || "").replaceAll("-", " / ");
      renderNavigation();
      render();
      if (!initial) notify("已读取最新记录。尚未保存的表单内容保留在原处。");
      return true;
    } catch (error) {
      if (!store) {
        $("#main").innerHTML = `<div class="loading-state"><span class="eyebrow">暂时未能打开</span><h1>暂时没有读到记录，请重试</h1><p>${esc(error.message)}</p><button class="button primary" data-action="retry">重新读取</button><p class="fine-print space-top">请通过“启动工作台.cmd”打开工作台。服务在本机后台运行，无须保留启动窗口。</p></div>`;
      } else notify(error.message, true);
      return false;
    }
  }

  function viewFromHash() { const value = location.hash.replace(/^#/, ""); return views.some(view => view[0] === value) ? value : "overview"; }
  function navigate(view) { if (location.hash === `#${view}`) render(); else location.hash = view; }
  function renderNavigation() {
    currentView = viewFromHash();
    $("#navigation").innerHTML = views.map(([id,label,index]) => `<a class="nav-link ${id === currentView ? "active" : ""}" href="#${id}" ${id === currentView ? 'aria-current="page"' : ""}>${icon(id)}<span>${label}</span><span class="nav-index">${index}</span></a>`).join("");
    $("#breadcrumb").textContent = `成长手册 / ${views.find(view => view[0] === currentView)?.[1] || "概览"}`;
  }

  function intro(kicker, title, description, actions = "") {
    return `<div class="page-intro"><div><span class="eyebrow">${esc(kicker)}</span><h1>${esc(title)}</h1><p>${esc(description)}</p></div>${actions ? `<div class="page-actions">${actions}</div>` : ""}</div>`;
  }
  function sectionHeading(number,title,right = "") { return `<div class="section-heading"><h2><span class="section-no">${esc(number)}</span>${esc(title)}</h2>${right}</div>`; }
  function empty(title,description,action = "") { return `<div class="empty-state"><span class="empty-mark" aria-hidden="true">—</span><h3>${esc(title)}</h3><p>${esc(description)}</p>${action}</div>`; }
  function addButton(collection,label) { return `<button class="button primary" data-action="add-record" data-collection="${collection}">${icon("plus")}${esc(label)}</button>`; }
  function exportButton(kind,format = "markdown",label = "导出记录") { return `<button class="button" data-action="export" data-kind="${kind}" data-format="${format}">${icon("download")}${esc(label)}</button>`; }
  function projectChips(ids) { return `<div class="project-chips">${arr(ids).map(id => `<button class="project-chip" data-action="open-project" data-id="${esc(id)}">${esc(id)} · ${esc(titleForProject(id))}</button>`).join("")}</div>`; }

  function render() {
    if (!store) return;
    renderNavigation();
    const renderers = {overview:renderOverview,roadmap:renderRoadmap,projects:renderProjects,evidence:renderEvidence,facts:renderFacts,decisions:renderDecisions,backup:renderBackup};
    $("#main").innerHTML = renderers[currentView]();
    if (currentView === "projects") renderProjectResults();
    document.title = `${views.find(view => view[0] === currentView)?.[1]} · 职业发展工作台`;
  }

  function renderOverview() {
    const profile = store.catalog.profile || {};
    const projects = arr(store.catalog.projects);
    const active = Object.values(store.state.projectStates || {}).filter(record => record.status === "active").length;
    const stats = store.derived?.stats || {};
    const principles = arr(profile.principles);
    return `<section class="hero"><div><span class="eyebrow">${esc(profile.name || "示例用户")} / 从在校积累，到行业立足</span><h1>把每一次积累，<br>变成<em>下一次机会。</em></h1><p class="lead">${esc(profile.positioning || "以技术销售为主线，把电气、无人机实践、组织管理与 AI 协作连接起来。用真实反馈，逐步建立自己的选择权。")}</p><div class="hero-actions"><button class="button primary" data-action="view-now">从现在可做的项目开始 ${icon("arrow")}</button><a class="button" href="#roadmap">查看十年路线</a></div></div><aside class="field-note"><span class="note-label">给未来的自己 / FIELD NOTE</span><blockquote>不急着押中风口，<br>先成为能接住<br>机会的人。</blockquote><div class="note-footer">${esc(profile.weeklyHours || "每周 9—15 小时")}<br>一次行动，一份证据，一次复盘。</div></aside></section>
      <div class="stat-grid"><div class="stat"><span class="stat-value">${projects.length}</span><span class="stat-label">候选项目 · 不等于已开发</span></div><div class="stat"><span class="stat-value">${active.toString().padStart(2,"0")}</span><span class="stat-label">正在推进的项目</span></div><div class="stat"><span class="stat-value">${arr(store.state.evidence).length.toString().padStart(2,"0")}</span><span class="stat-label">已记录的成果证据</span></div><div class="stat"><span class="stat-value">${Number(stats.pendingFacts || 0).toString().padStart(2,"0")}</span><span class="stat-label">需要确认的事实</span></div></div>
      <div class="split-section"><section>${sectionHeading("01","眼下值得做的三件事")}<div class="paper-panel"><ol class="action-list"><li><span class="action-number">1.</span><div><h3>选一个近期就能用的项目</h3><p>让现有教学、活动、宣传或求职场景提供反馈。先跑通一个问题，再扩展功能。</p><button class="text-button" data-action="view-now">查看现在可做的项目 →</button></div></li><li><span class="action-number">2.</span><div><h3>把“做过”变成可说明的成果</h3><p>写清自己的贡献、材料出处和未验证的边界，为求职与成长留下证据。</p><button class="text-button" data-action="add-record" data-collection="evidence">记录一项成果 →</button></div></li><li><span class="action-number">3.</span><div><h3>给重要选择设置复盘日期</h3><p>就业、读研与创业都用真实机会比较，不必一次决定十年。</p><button class="text-button" data-action="add-record" data-collection="decisions">建立一个决策记录 →</button></div></li></ol></div></section><section>${sectionHeading("02","这本手册的使用原则")}<div class="paper-panel"><ul class="principles">${(principles.length ? principles : ["技术销售为主线，项目服务于实际能力与机会。","最多同时推进两个项目，为使用与复盘留时间。","未来情景用于准备，不作为确定预测。","示例、模拟与真实成果分开记录。"] ).map(item => `<li>${esc(item)}</li>`).join("")}</ul><p class="fine-print space-top">个人基线：${esc(profile.baselineDate || "2026-10-24")} · 预计毕业：${esc(profile.graduation || "2028")}</p></div></section></div>
      <section class="section">${sectionHeading("03","十年，看四个观察点",'<a class="text-button" href="#roadmap">展开三种情景 →</a>')}<div class="route-strip">${arr(store.catalog.roadmap).map(item => `<div class="route-stop"><span class="horizon">${esc(item.horizon)} 年后 / 观察与调整</span><span class="year">${esc(item.year)}</span><h3>${esc(item.title)}</h3><p>${esc(item.baseline)}</p></div>`).join("")}</div></section>
      <section class="section">${sectionHeading("04","值得跟踪的机会",'<span>事实与判断，分开阅读</span>')}${arr(store.catalog.opportunities).map(item => `<article class="opportunity"><h3>${esc(item.title)}</h3><p><span class="label">已有证据　</span>${esc(item.evidence)}</p><p><span class="label">条件式判断　</span>${esc(item.inference)}</p><details><summary class="text-button">观察哪些信号与风险</summary><ul class="fine-print">${arr(item.signals).map(signal => `<li>${esc(signal)}</li>`).join("")}</ul><p class="fine-print">风险：${esc(item.risk)}</p>${sourceList(item.sourceIds)}</details></article>`).join("")}</section>`;
  }

  function renderRoadmap() {
    return intro("LONG VIEW / 2027 · 2028 · 2031 · 2036","方向可以坚定，路径持续调整。","最好、基准和压力情景是准备不同选择的方法；不会把创业、升职或某项技术发展写成必然。") +
      `<div class="notice">先积累能带到下一阶段的能力、作品与合作经验。每到一个观察点，用当前事实重新判断，而不是机械完成旧计划。</div><div class="timeline">${arr(store.catalog.roadmap).map(item => `<section class="timeline-block"><div class="timeline-heading"><span class="timeline-year">${esc(item.year)}</span><div><span class="eyebrow">${esc(item.horizon)} 年观察点</span><h2>${esc(item.title)}</h2></div></div><div class="scenario-grid"><div class="scenario"><span class="label">最好情景 / 机会打开</span><p>${esc(item.best)}</p></div><div class="scenario"><span class="label">基准情景 / 持续积累</span><p>${esc(item.baseline)}</p></div><div class="scenario stress"><span class="label">压力情景 / 留好退路</span><p>${esc(item.stress)}</p></div></div><div class="response"><strong>调整方式</strong>${esc(item.response)}</div>${projectChips(item.projectIds)}</section>`).join("")}</div>
      <section class="section">${sectionHeading("01","跨阶段都值得积累的能力")}<div class="capability-list">${arr(store.catalog.capabilities).map(item => `<article class="capability"><h3>${esc(item.name)}</h3><div><p>${esc(item.focus)}</p><p class="muted"><span class="label">用什么证明　</span>${esc(item.proof)}</p>${projectChips(item.projectIds)}</div></article>`).join("")}</div></section>
      ${arr(store.catalog.profile?.unknowns).length ? `<section class="section">${sectionHeading("02","仍需持续确认的条件")}<div class="notice warning"><ul>${store.catalog.profile.unknowns.map(item => `<li>${esc(item)}</li>`).join("")}</ul></div></section>` : ""}`;
  }

  function options(values,selected,first) { return (first !== undefined ? `<option value="">${esc(first)}</option>` : "") + values.map(([value,label]) => `<option value="${esc(value)}" ${String(selected) === String(value) ? "selected" : ""}>${esc(label)}</option>`).join(""); }
  function renderProjects() {
    const categories = [...new Map(arr(store.catalog.projects).map(project => [project.category,project.categoryName])).entries()].sort((a,b)=>String(a[0]).localeCompare(String(b[0])));
    return intro("PROJECT LIBRARY / 40 个可发展方向","做有用的项目，留下能复用的积累。","每张卡都有真实问题、首版范围、启动条件、验收方法和 Codex 提示词。它们是候选蓝图，收藏不等于立项，开发完成也不等于已经有人需要。") +
      `<form id="project-filters" class="filters" role="search"><div class="filter-field"><label for="project-search">搜索项目</label><input id="project-search" name="query" type="search" placeholder="搜项目名、场景或要解决的问题" value="${esc(filters.query)}" autocomplete="off"></div><div class="filter-field"><label for="category-filter">方向</label><select id="category-filter" name="category">${options(categories,filters.category,"全部方向")}</select></div><div class="filter-field"><label for="readiness-filter">什么时候做</label><select id="readiness-filter" name="readiness">${options(Object.entries(readinessLabels),filters.readiness,"全部启动条件")}</select></div><div class="filter-field"><label for="horizon-filter">适用观察点</label><select id="horizon-filter" name="horizon">${options([[1,"1 年 · 2027"],[2,"2 年 · 2028"],[5,"5 年 · 2031"],[10,"10 年 · 2036"]],filters.horizon,"全部阶段")}</select></div><div class="filter-bottom"><label class="checkbox-label"><input type="checkbox" name="favorite" ${filters.favorite ? "checked" : ""}>只看我的收藏</label><button type="button" class="text-button" data-action="reset-filters">清除筛选</button></div></form><div id="project-results" aria-live="polite"></div>`;
  }

  function renderProjectResults() {
    const target = $("#project-results"); if (!target) return;
    const query = filters.query.trim().toLocaleLowerCase();
    const results = arr(store.catalog.projects).filter(project => (!query || [project.id,project.name,project.problem,project.audience,project.categoryName,project.personalFit].join(" ").toLocaleLowerCase().includes(query)) && (!filters.category || project.category === filters.category) && (!filters.readiness || project.readiness === filters.readiness) && (!filters.horizon || arr(project.horizons).map(String).includes(filters.horizon)) && (!filters.favorite || stateOf(project.id).favorite));
    target.innerHTML = `<div class="result-summary"><span>找到 <strong>${results.length}</strong> 个项目 / 全部 ${arr(store.catalog.projects).length} 个</span><span>一次专注一个问题，让结果说话。</span></div>` + (results.length ? `<div class="project-list">${results.map(project => {
      const progress = stateOf(project.id);
      return `<article class="project-row"><span class="project-number">${esc(project.id)}</span><div><div class="badge-row">${badge(project.categoryName)}${readinessBadge(project.readiness)}${progress.status && progress.status !== "idea" ? badge(statusLabels[progress.status] || progress.status,"green") : ""}</div><h3><button class="title-button" data-action="open-project" data-id="${esc(project.id)}">${esc(project.name)}</button></h3><p>${esc(project.problem)}</p><div class="project-meta"><span>给谁用：${esc(project.audience)}</span><span>观察点：${arr(project.horizons).map(year=>`${esc(year)} 年`).join(" / ")}</span></div></div><div class="project-tools"><button class="icon-button ${progress.favorite ? "selected" : ""}" data-action="favorite" data-id="${esc(project.id)}" aria-pressed="${!!progress.favorite}" aria-label="${progress.favorite ? "取消收藏" : "收藏"}${esc(project.name)}">${icon("star",!!progress.favorite)}</button><button class="button small" data-action="open-project" data-id="${esc(project.id)}">读项目卡 ${icon("arrow")}</button></div></article>`;
    }).join("")}</div>` : empty("没有匹配的项目","尝试减少一个筛选条件，或者换一个问题关键词。",'<button class="button" data-action="reset-filters">查看全部项目</button>'));
  }

  function safeWebUrl(value) { try { const url = new URL(value); return ["http:","https:"].includes(url.protocol) ? url.href : null; } catch { return null; } }
  function sourceList(ids) {
    const sources = arr(ids).map(id => arr(store.catalog.sources).find(source => source.id === id)).filter(Boolean);
    if (!sources.length) return '<p class="fine-print">以公开资料、个人已确认经历及后续真实反馈继续核实。</p>';
    return `<ul class="source-list">${sources.map(source => { const url = safeWebUrl(source.url); return `<li>${url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(source.title)}</a>` : `<strong>${esc(source.title)}</strong>`}${source.path ? `<div class="source-row"><code>${esc(source.path)}</code><button class="text-button" data-action="copy-text" data-text="${esc(source.path)}">复制路径</button></div>` : ""}<span class="source-note">${esc(source.date || "日期待核实")}${source.kind ? ` · ${esc(source.kind)}` : ""}${source.note ? ` · ${esc(source.note)}` : ""}</span></li>`; }).join("")}</ul>`;
  }
  function detailSection(title,body) { return `<section class="detail-section"><h3>${esc(title)}</h3>${body}</section>`; }
  function bullets(items) { return arr(items).length ? `<ul>${items.map(item => `<li>${esc(item)}</li>`).join("")}</ul>` : '<p class="muted">在具体立项前补充。</p>'; }
  function openProject(id) {
    const project = projectById(id); if (!project) return notify("没有找到这个项目。",true);
    activeProjectId = id; projectRevision = store.state.revision;
    const progress = stateOf(id);
    $("#project-dialog-content").innerHTML = `<div class="drawer-header"><span class="eyebrow">PROJECT ${esc(project.id)} / ${esc(project.categoryName)}</span><button class="icon-button" data-action="close-project" aria-label="关闭项目详情">${icon("close")}</button></div><div class="drawer-body"><div class="badge-row">${readinessBadge(project.readiness)}${badge(arr(project.horizons).map(year=>`${year} 年`).join(" / "))}</div><h2 id="project-dialog-title">${esc(project.name)}</h2><p class="intro-text">${esc(project.problem)}</p><div class="notice warning">这是可逐步验证的项目蓝图。请先确认使用者、数据与启动条件，再把提示词交给 Codex 开始开发。</div><div class="button-stack"><button class="button primary" data-action="copy-prompt" data-id="${esc(id)}">${icon("copy")}复制 Codex 提示词</button><button class="button" data-action="download-card" data-id="${esc(id)}">${icon("download")}下载项目卡</button></div>
      ${detailSection("为什么值得考虑",`<div class="detail-grid"><div><h4>为谁解决问题</h4><p>${esc(project.audience)}</p></div><div><h4>与你的经历如何连接</h4><p>${esc(project.personalFit)}</p></div></div><h4 class="small-heading">已有替代方案</h4><p>${esc(project.alternatives)}</p>`)}
      ${detailSection("什么条件下开始",`<p>${esc(project.trigger)}</p>`)}
      ${detailSection("第一版，只完成这些",`<p>${esc(project.firstVersion)}</p><div class="detail-grid"><div><h4>需要的输入</h4>${bullets(project.inputs)}</div><div><h4>应得到的输出</h4>${bullets(project.outputs)}</div></div><h4 class="small-heading">本轮不做</h4>${bullets(project.nonGoals)}`)}
      ${detailSection("用什么判断有用",`${bullets(project.acceptance)}<div class="detail-grid"><div><h4>继续投入的条件</h4><p>${esc(project.continueWhen)}</p></div><div><h4>暂停或停止的条件</h4><p>${esc(project.stopWhen)}</p></div></div>`)}
      <section class="project-progress"><h3>我的推进记录</h3><form id="project-progress-form"><div class="progress-top"><div class="field"><label for="project-status">当前进度</label><select id="project-status" name="status">${options(Object.entries(statusLabels),progress.status || "idea")}</select></div><label class="checkbox-label"><input type="checkbox" name="favorite" ${progress.favorite ? "checked" : ""}>加入收藏</label></div><div class="field"><label for="project-notes">我的备注与下一步</label><textarea id="project-notes" name="notes" rows="4" placeholder="记录遇到的真实问题、打算请谁试用，以及下一步最小行动。">${esc(progress.notes)}</textarea></div><button class="button primary" type="submit">保存进度与备注</button><div class="form-feedback" id="project-feedback" role="alert"></div></form><p class="fine-print space-top-small">“已有验证”由你依据真实结果设置；建议同时记录一次试用与反馈。</p><button class="text-button" data-action="review-project" data-id="${esc(id)}">记录一次试用反馈 →</button></section>
      ${detailSection("可直接使用的 Codex 提示词",`<pre class="prompt-box">${esc(project.prompt)}</pre><button class="text-button" data-action="copy-prompt" data-id="${esc(id)}">复制完整提示词</button>`)}
      ${detailSection("依据与参考",sourceList(project.sourceIds))}</div>`;
    if (!$("#project-dialog").open) $("#project-dialog").showModal();
    $("#project-dialog").scrollTop = 0;
  }

  function recordActions(collection,record) { return `<div class="record-actions"><button class="button small" data-action="edit-record" data-collection="${collection}" data-id="${esc(record.id)}">编辑</button><button class="button small" data-action="delete-record" data-collection="${collection}" data-id="${esc(record.id)}">删除</button></div>`; }
  function recordField(label,value,full = false) { return `<div class="record-field ${full ? "full" : ""}"><span class="label">${esc(label)}</span><p>${esc(pretty(value))}</p></div>`; }
  function sourceField(value) { return `<div class="record-field full"><span class="label">来源与材料位置</span>${value ? `<div class="source-row"><code>${esc(value)}</code><button class="text-button" data-action="copy-text" data-text="${esc(value)}">复制来源</button></div>` : '<p class="muted">尚未填写</p>'}</div>`; }
  function recordDate(record) { return text(record.updatedAt).slice(0,10) || "尚未记录"; }

  function renderEvidence() {
    return intro("EVIDENCE / 让经历经得起追问","留下成果，也留下边界。","一份清楚的贡献说明，胜过模糊的“参与过”。区分实际成果、本人陈述和演示，保留能找回的材料来源。",addButton("evidence","记录成果") + exportButton("evidence")) +
      `<form id="evidence-search-form" class="record-search" role="search"><div class="filter-field"><label for="evidence-search">搜索成果</label><input type="search" id="evidence-search" value="${esc(evidenceQuery)}" placeholder="搜标题、贡献、来源、边界或类别" autocomplete="off"></div><div class="filter-field"><label for="evidence-status">证据状态</label><select id="evidence-status">${options(Object.entries(evidenceLabels),evidenceStatus,"全部证据状态")}</select></div></form><div id="evidence-results" aria-live="polite">${evidenceResultsHtml()}</div>`;
  }
  function evidenceResultsHtml() {
    const query = evidenceQuery.trim().toLocaleLowerCase();
    const allRecords = arr(store.state.evidence);
    const records = allRecords.filter(record=>(!query || [record.title,record.contribution,record.source,record.boundary,record.category].join(" ").toLocaleLowerCase().includes(query)) && (!evidenceStatus || record.status === evidenceStatus));
    return `<div class="result-summary"><span>${records.length} 项成果 / 全部 ${allRecords.length} 项</span><span>贡献、来源与边界，一起保留。</span></div>` +
      (records.length ? `<div class="records-list">${records.slice().reverse().map(record => `<article class="record"><div class="record-header"><div><div class="badge-row">${badge(record.category || "未分类")}${badge(evidenceLabels[record.status] || record.status,record.status === "documented" ? "green" : record.status === "pending" ? "copper" : "")}</div><h3>${esc(record.title)}</h3></div>${recordActions("evidence",record)}</div><div class="record-grid">${recordField("我的具体贡献",record.contribution,true)}${recordField("尚未验证或不应夸大的部分",record.boundary,true)}${sourceField(record.source)}</div><div class="record-bottom"><span>成果日期：${esc(record.date || "待补充")}</span><span>最近更新：${esc(recordDate(record))}</span></div></article>`).join("")}</div>` : allRecords.length ? empty("没有找到匹配的成果","换一个关键词或取消状态筛选，看看其他积累。",'<button class="button" data-action="reset-evidence-search">清除成果筛选</button>') : empty("从一项真实成果开始","项目演示、教学活动、宣传材料或一次客户沟通都可以。先写清自己的贡献和证据位置。",addButton("evidence","添加第一项成果")));
  }

  function factWarnings(record) {
    const labels = arr(record.flags).map(flag => ({"待核实":"待确认","已过期":"已到期","存在口径冲突":"存在冲突","有效期待核实":"未设置有效期"}[flag] || flagLabels[flag] || flag));
    if (record.status === "pending" && !labels.includes("待确认")) labels.push("待确认");
    if (record.validUntil && record.validUntil < currentDate() && !labels.includes("已到期")) labels.push("已到期");
    if (!record.validUntil && record.status !== "retired" && !labels.some(label=>label.includes("有效期"))) labels.push("未设置有效期");
    if (record.status !== "retired" && isSoon(record.validUntil)) labels.push("30 天内到期");
    return [...new Set(labels)].filter(label => label !== factLabels[record.status]);
  }
  function renderFacts() {
    const facts = arr(store.derived?.facts).length || !arr(store.state.facts).length ? arr(store.derived?.facts) : arr(store.state.facts);
    const conflicts = arr(store.derived?.conflicts);
    const stats = store.derived?.stats || {};
    const filtered = facts.filter(record => factFilter === "all" || (factFilter === "ready" && record.ready) || (factFilter === "attention" && record.status !== "retired" && (!record.ready || isSoon(record.validUntil))) || (factFilter === "retired" && record.status === "retired"));
    return intro("FACT DESK / 当前事实，有据可查","把矛盾留在这里，把可信内容带出去。","把课程学时、费用、证书与宣传口径集中核实；同一主体、字段和范围出现不同值时保留冲突。确认仅为本人保存的核验记录，不等于机构批准发布。",addButton("facts","新增事实") + '<button class="button" data-action="publication">导出当前可用文案</button>') +
      `<div class="fact-stats"><span><strong>${stats.readyFacts || 0}</strong>当前可用</span><span><strong>${stats.pendingFacts || 0}</strong>待确认</span><span><strong>${stats.conflictGroups || 0}</strong>组冲突</span><span><strong>${stats.expiredFacts || 0}</strong>已到期</span></div>
      ${conflicts.length ? `<section aria-label="待核实冲突"><div class="section-heading"><h2>需要核实的不同说法</h2><span>不自动判断谁对</span></div>${conflicts.map(conflict => `<div class="conflict-block"><h3>${esc(conflict.subject)} · ${esc(conflict.field)}</h3><p class="fine-print">适用范围：${esc(conflict.scope || "未填写")}。请查看原始来源，编辑或退役过时记录；单位不同也需要分别核实。</p><div class="conflict-values">${arr(conflict.ids).map(id => { const fact = facts.find(item=>item.id===id); return `<button class="button small" data-action="edit-record" data-collection="facts" data-id="${esc(id)}">${esc(fact ? `${fact.value} ${fact.unit || ""}` : id)} · 核实</button>`; }).join("")}</div></div>`).join("")}</section>` : ""}
      <div class="toolbar"><label class="visually-hidden" for="fact-filter">筛选事实</label><select id="fact-filter">${options([["all","全部事实"],["ready","当前可用"],["attention","需要关注"],["retired","已退役"]],factFilter)}</select><span class="fine-print">${filtered.length} 条记录</span><div class="push">${exportButton("facts","csv","导出全部 CSV")}</div></div>
      ${filtered.length ? `<div class="records-list">${filtered.slice().reverse().map(record => `<article class="record ${record.ready ? "fact-ready" : record.status !== "retired" ? "fact-warning" : ""}"><div class="record-header"><div><div class="badge-row">${badge(record.ready ? "当前可用" : factLabels[record.status] || record.status,record.ready ? "green" : "")}${factWarnings(record).map(label=>badge(label,label.includes("冲突") || label.includes("到期") && !label.includes("30") ? "red" : "copper")).join("")}</div><h3>${esc(record.subject)} · ${esc(record.field)}</h3><span class="fine-print">适用范围：${esc(record.scope || "未填写")}</span></div>${recordActions("facts",record)}</div><div class="record-grid">${recordField("采用内容 / 数值",`${record.value || ""}${record.unit ? ` ${record.unit}` : ""}`,true)}${sourceField(record.source)}${recordField("来源日期",record.sourceDate)}${recordField("有效截止",record.validUntil)}${recordField("确认人",record.reviewer)}${recordField("确认日期",record.confirmedAt)}${record.notes ? recordField("核实备注",record.notes,true) : ""}</div><div class="record-bottom"><span>最近更新：${esc(recordDate(record))}</span><span class="record-id">${esc(record.id)}</span></div></article>`).join("")}</div>` : empty(facts.length ? "这个筛选下没有记录" : "先收好一条可以核实的事实",facts.length ? "切换到全部事实，查看已有记录。" : "例如课程学时、服务费用或证书说明。填写课程版本和来源，避免把不同阶段的宣传口径混在一起。",addButton("facts","新增事实"))}`;
  }

  function renderDecisions() {
    const decisions = arr(store.state.decisions);
    const reviews = arr(store.state.reviews);
    return intro("DECISIONS & FEEDBACK / 把判断放回现实","记录当时为什么选，也记录后来发生了什么。","决策记录帮助比较就业、读研和创业；试用反馈帮助判断一个项目是否值得继续。保留原来的假设，比事后只写结论更有用。",addButton(decisionTab,decisionTab === "decisions" ? "记录决策" : "记录试用反馈") + exportButton(decisionTab,"markdown",decisionTab === "reviews" ? "导出使用反馈" : "导出决策记录")) +
      `<div class="tabs" role="tablist" aria-label="决策与反馈"><button class="tab-button ${decisionTab === "decisions" ? "active" : ""}" role="tab" aria-selected="${decisionTab === "decisions"}" data-action="decision-tab" data-tab="decisions">决策记录 · ${decisions.length}</button><button class="tab-button ${decisionTab === "reviews" ? "active" : ""}" role="tab" aria-selected="${decisionTab === "reviews"}" data-action="decision-tab" data-tab="reviews">试用与反馈 · ${reviews.length}</button></div>` +
      (decisionTab === "decisions" ? (decisions.length ? `<div class="records-list">${decisions.slice().reverse().map(record => `<article class="record"><div class="record-header"><div><div class="badge-row">${badge(record.kind || "其他")}${badge(record.status === "closed" ? "已复盘" : "待复盘",record.status === "closed" ? "green" : "copper")}${record.status === "open" ? dateBadge(record.reviewDate) : ""}</div><h3>${esc(record.title)}</h3></div>${recordActions("decisions",record)}</div><div class="record-grid">${recordField("当时的假设",record.assumptions,true)}${recordField("支持或反对的证据",record.evidence,true)}${recordField("下一步验证",record.nextStep)}${recordField("改变方向的条件",record.exitCondition)}${record.outcome ? recordField("后续结果与复盘",record.outcome,true) : ""}</div><div class="record-bottom"><span>复盘日期：${esc(record.reviewDate || "待设置")}</span><span>最近更新：${esc(recordDate(record))}</span></div></article>`).join("")}</div>` : empty("先把一个重要选择写下来","不急着给人生打分。写清楚当前选项、依据，以及什么新证据会让你改变主意。",addButton("decisions","建立第一条决策"))) :
      (reviews.length ? `<div class="records-list">${reviews.slice().reverse().map(record => `<article class="record"><div class="record-header"><div>${badge(`${record.projectId} · ${titleForProject(record.projectId)}`)}<h3>${esc(record.date || "未设置日期")} 的试用与反馈</h3></div>${recordActions("reviews",record)}</div><div class="record-grid">${recordField("使用前的情况",record.baseline,true)}${recordField("观察到的实际结果",record.result,true)}${recordField("使用者反馈",record.feedback,true)}${recordField("据此决定的下一步",record.nextStep,true)}</div><div class="record-bottom"><button class="text-button" data-action="open-project" data-id="${esc(record.projectId)}">返回项目卡 →</button><span>最近更新：${esc(recordDate(record))}</span></div></article>`).join("")}</div>` : empty("让一次真实使用留下痕迹","记录使用前、实际结果和使用者原话。没有达到预期的结果，也能帮助你减少无效开发。",addButton("reviews","记录第一次反馈"))));
  }

  function renderBackup() {
    return intro("KEEP & CARRY / 记录由你保管","带得走，也能重新打开。","完整备份用于恢复工作台；Markdown 与 CSV 便于阅读、分享或交给其他工具继续处理。建议在重要阶段后，把备份另存到其他可靠位置。") +
      `<div class="export-grid"><section class="export-panel"><span class="panel-number">01 / 完整保存</span><h2>备份全部个人记录</h2><p>包含项目收藏与进度、成果、事实、决策和反馈。不会把项目蓝图误作已完成的成果。</p><button class="button primary" data-action="export" data-kind="all" data-format="json">${icon("download")}下载完整备份</button><p class="fine-print space-top">文件为 JSON 格式，可通过右侧恢复。仅在本机下载，不会自动上传。</p></section><section class="export-panel"><span class="panel-number">02 / 恢复记录</span><h2>先预览，再导入</h2><p>导入会替换当前个人记录；确认前会展示记录数量，替换前本机会自动保存原记录备份。</p><label for="backup-file" class="label">选择本工作台导出的 JSON 备份</label><input class="file-input" id="backup-file" type="file" accept=".json,application/json"><div id="import-feedback" class="form-feedback" role="alert"></div><div id="import-preview"></div></section></div>
      <section class="section">${sectionHeading("03","普通格式导出",'<span>便于阅读与继续使用</span>')}<div class="paper-panel"><div class="button-stack">${exportButton("all","markdown","全部记录 · Markdown")}${exportButton("evidence","markdown","成果 · Markdown")}${exportButton("facts","csv","事实 · CSV")}${exportButton("decisions","csv","决策 · CSV")}<button class="button" data-action="publication">当前可用事实文案</button></div><p class="fine-print space-top">“当前可用事实文案”只含已经确认、未到期且没有冲突的事实。普通导出保留全部记录及原有状态，不能直接视为已审核内容。</p></div></section>
      <section class="section">${sectionHeading("04","保留资料时记住这几件事")}<div class="notice"><ul><li>材料路径只是位置索引，完整备份不会自动包含路径指向的照片、证书或项目文件。</li><li>完整备份可能包含个人经历和业务备注，分享前请检查内容。</li><li>重要成果建议同时保留源文件、可阅读副本与对应说明。</li><li>本机历史备份仍在这台电脑上，不能代替你另存的一份独立副本。</li></ul></div></section>`;
  }

  const schemas = {
    evidence: {title:"成果证据",fields:[
      ["title","成果标题","text",true,true,"例如：无人机课程活动交付与复盘"],
      ["category","成果类别","text",false,false,"例如：教学 / 竞赛 / 实习 / 项目"],
      ["status","证据状态","select",true,false,Object.entries(evidenceLabels)],
      ["date","成果日期","date",false,false],
      ["contribution","我的具体贡献","textarea",true,true,"写清本人完成的工作，区分个人贡献与团队成果。"],
      ["source","材料来源或本地路径","textarea",false,true,"记录文件路径或公开链接；路径只作为索引保存。"],
      ["boundary","尚未验证或不应夸大的部分","textarea",false,true,"例如：使用模拟数据，尚未真实客户试用；不把演示效果写成经营收益。"]
    ]},
    facts: {title:"事实记录",fields:[
      ["subject","主体","text",true,false,"例如：示例团队装调课程"],
      ["field","事实字段","text",true,false,"例如：总学时"],
      ["scope","适用范围","text",true,true,"例如：2026版中级课程"],
      ["value","内容或数值","textarea",true,true,"保留能够由原始资料支持的准确表述。"],
      ["unit","单位（如适用）","text",false,false,"例如：学时 / 元；无单位可留空"],
      ["status","核实状态","select",true,false,Object.entries(factLabels)],
      ["source","来源或材料位置","textarea",false,true,"填写原始文件、官方网页或本人确认记录。"],
      ["sourceDate","来源日期","date",false,false],
      ["validUntil","有效截止日期","date",false,false],
      ["reviewer","确认人","text",false,false,"由谁核对这条事实"],
      ["confirmedAt","确认日期","date",false,false],
      ["notes","核实备注","textarea",false,true,"说明冲突如何核实，或者为什么退役这条记录。"]
    ]},
    decisions: {title:"决策记录",fields:[
      ["title","正在考虑的决定","text",true,true,"例如：选择哪类大四实习机会"],
      ["kind","决策方向","select",true,false,["就业","读研","创业","其他"].map(value=>[value,value])],
      ["status","当前状态","select",true,false,[["open","待复盘"],["closed","已复盘"]]],
      ["assumptions","当时的假设","textarea",true,true,"写出你的预期，以及哪些条件尚不确定。"],
      ["evidence","支持或反对的证据","textarea",false,true,"区分真实岗位、实际反馈与尚未核实的说法。"],
      ["nextStep","下一步如何验证","textarea",true,true,"一个具体且可完成的行动。"],
      ["exitCondition","什么条件下改变方向","textarea",false,true,"例如：岗位始终无法接触目标业务；关键条件与预期不符。"],
      ["reviewDate","复盘日期","date",true,false],
      ["outcome","后续结果与复盘","textarea",false,true,"实际发生了什么；下次会怎样做。"]
    ]},
    reviews: {title:"试用与反馈",fields:[
      ["projectId","关联项目","project",true,true],
      ["date","试用日期","date",true,false],
      ["baseline","使用前的情况","textarea",true,true,"记录原先如何做、耗费多少时间或遇到了什么问题。"],
      ["result","实际观察到的结果","textarea",true,true,"保留测量方法与边界；没有数据就记录具体观察，不编造比例。"],
      ["feedback","使用者反馈","textarea",false,true,"可记录原话、使用场景和仍未解决的问题。"],
      ["nextStep","据此决定的下一步","textarea",true,true,"继续、调整、暂停，或者再做一次验证。"]
    ]}
  };

  function fieldMarkup(definition,record) {
    const [name,label,type,required,wide,extra] = definition;
    const value = record[name] || "";
    const id = `edit-${name}`;
    const common = `id="${id}" name="${name}" ${required ? "required" : ""}`;
    let control;
    if (type === "select") control = `<select ${common}>${options(extra,value)}</select>`;
    else if (type === "project") control = `<select ${common}><option value="">请选择项目</option>${options(arr(store.catalog.projects).map(project=>[project.id,`${project.id} · ${project.name}`]),value)}</select>`;
    else if (type === "textarea") control = `<textarea ${common} rows="3" maxlength="20000" placeholder="${esc(typeof extra === "string" ? extra : "")}">${esc(value)}</textarea>`;
    else control = `<input ${common} type="${type}" value="${esc(value)}" ${type === "date" ? "" : 'maxlength="2000"'} placeholder="${esc(typeof extra === "string" ? extra : "")}">`;
    return `<div class="field ${wide ? "wide" : ""}"><label for="${id}">${esc(label)}${required ? '<span class="required" aria-hidden="true">*</span>' : ""}</label>${control}${name === "validUntil" ? '<p class="field-help">截止日期包含当天。已确认的事实必须设置；到期后需重新核实。</p>' : ""}</div>`;
  }

  function openEditor(collection,id = null,defaults = {}) {
    const schema = schemas[collection]; if (!schema) return;
    const existing = id ? arr(store.state[collection]).find(record=>record.id===id) : null;
    if (id && !existing) return notify("这条记录已不存在，请刷新查看最新内容。",true);
    const record = existing || {date:currentDate(),status:collection === "evidence" ? "pending" : collection === "facts" ? "pending" : "open",reviewDate:plusDays(30),reviewer:store.catalog.profile?.name || "",confirmedAt:currentDate(),kind:"就业",...defaults};
    editorContext = {collection,id,revision:store.state.revision};
    $("#editor-dialog-content").innerHTML = `<div class="modal-header"><div><span class="eyebrow">${existing ? "更新记录" : "新的一次积累"}</span><h2 id="editor-dialog-title">${existing ? "编辑" : "新增"}${schema.title}</h2></div><button type="button" class="icon-button" data-action="close-editor" aria-label="关闭编辑表单">${icon("close")}</button></div><div class="modal-body">${collection === "facts" ? '<div class="notice warning">设为“已确认”时，需要填写来源、确认人、确认日期和有效期。冲突不会自动消失，请核对后修改或退役不再适用的记录。</div>' : ""}<form id="record-form"><div class="form-grid">${schema.fields.map(field=>fieldMarkup(field,record)).join("")}</div><div id="record-feedback" class="form-feedback" role="alert"></div><div class="form-footer"><button type="button" class="button" data-action="close-editor">取消</button><button type="submit" class="button primary">保存记录</button></div></form></div>`;
    if (!$("#editor-dialog").open) $("#editor-dialog").showModal();
    $("#editor-dialog").scrollTop = 0;
    updateFactRequirements();
  }

  function updateFactRequirements() {
    if (editorContext?.collection !== "facts") return;
    const confirmed = $("#edit-status")?.value === "confirmed";
    for (const name of ["source","reviewer","confirmedAt","validUntil"]) {
      const input = $(`#edit-${name}`); if (!input) continue;
      input.required = confirmed;
      const label = $(`label[for="edit-${name}"]`);
      const star = $(".required",label); if (star) star.remove();
      if (confirmed) label.insertAdjacentHTML("beforeend",'<span class="required" aria-hidden="true">*</span>');
    }
  }

  function feedback(id,message,error = null,success = false) {
    const element = $(`#${id}`); if (!element) return;
    element.className = `form-feedback visible${success ? " success" : ""}`;
    element.innerHTML = `${esc(message)}${error?.status === 409 ? '<button type="button" class="button small" data-action="refresh-draft">读取最新记录，保留当前填写内容</button><p class="fine-print space-top-small">刷新后请核对这份内容，再决定是否保存；不会自动覆盖。</p>' : ""}`;
  }
  function lockForm(form,locked) { for (const element of form.elements) element.disabled = locked; }

  async function saveRecord(form) {
    if (!editorContext || !form.reportValidity()) return;
    const context = {...editorContext};
    const record = Object.fromEntries(new FormData(form).entries()); if (context.id) record.id = context.id;
    lockForm(form,true);
    try {
      const result = await api("/api/save",{expectedRevision:context.revision,collection:context.collection,record});
      updateState(result); $("#editor-dialog").close(); editorContext = null; render(); notify("记录已保存到本机。");
    } catch (error) { feedback("record-feedback",error.message,error); }
    finally { lockForm(form,false); }
  }

  async function saveProject(form) {
    const values = new FormData(form);
    const patch = {status:values.get("status"),favorite:values.has("favorite"),notes:values.get("notes") || ""};
    lockForm(form,true);
    try {
      const result = await api("/api/project",{expectedRevision:projectRevision,id:activeProjectId,patch});
      updateState(result); projectRevision = store.state.revision; render(); feedback("project-feedback","进度与备注已保存。",null,true); notify("项目进度已保存。");
    } catch(error) { feedback("project-feedback",error.message,error); }
    finally { lockForm(form,false); }
  }

  async function favoriteProject(id,button) {
    button.disabled = true;
    try { const next = !stateOf(id).favorite; const result = await api("/api/project",{expectedRevision:store.state.revision,id,patch:{favorite:next}}); updateState(result); renderProjectResults(); notify(next ? "已加入收藏。" : "已取消收藏。"); }
    catch(error) { notify(error.status === 409 ? `${error.message} 请点击“刷新工作台”后重试。` : error.message,true); }
    finally { button.disabled = false; }
  }

  function confirmDelete(collection,id) {
    const record = arr(store.state[collection]).find(item=>item.id===id); if (!record) return;
    const label = record.title || (record.subject ? `${record.subject} · ${record.field}` : `${record.date || ""} 的试用反馈`);
    const revision = store.state.revision;
    $("#confirm-dialog-content").innerHTML = `<div class="modal-header"><h2 id="confirm-dialog-title">删除这条记录？</h2><button class="icon-button" data-action="close-confirm" aria-label="关闭确认">${icon("close")}</button></div><div class="modal-body"><p><strong>${esc(label)}</strong></p><p class="muted">删除前会在本机自动备份原记录。确认后，这条内容会从当前工作台移除。</p><div id="delete-feedback" class="form-feedback" role="alert"></div><div class="form-footer"><button class="button" data-action="close-confirm">保留记录</button><button class="button danger" id="confirm-delete-button">确认删除</button></div></div>`;
    $("#confirm-dialog").showModal();
    $("#confirm-delete-button").addEventListener("click",async event=>{
      event.currentTarget.disabled = true;
      try { const result = await api("/api/delete",{expectedRevision:revision,collection,id}); updateState(result); $("#confirm-dialog").close(); render(); notify("记录已删除，原记录已自动备份。"); }
      catch(error) { feedback("delete-feedback",error.status === 409 ? `${error.message} 请关闭此窗口，刷新工作台后重新核对。` : error.message); }
      finally { const button = $("#confirm-delete-button"); if (button) button.disabled = false; }
    });
  }

  async function copy(value) {
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(String(value));
      else {
        const input = document.createElement("textarea"); input.value = String(value); input.setAttribute("readonly",""); input.className = "visually-hidden";
        (document.querySelector("dialog[open]") || document.body).append(input); input.select();
        const copied = document.execCommand("copy"); input.remove(); if (!copied) throw new Error("copy");
      }
      notify("已复制，可粘贴到需要的位置。");
    } catch { notify("未能自动复制。请选中内容后手动复制。",true); }
  }

  async function download(path,filename) {
    try {
      const response = await fetch(path,{cache:"no-store"}); if (!response.ok) throw await responseError(response);
      const blob = await response.blob(); const url = URL.createObjectURL(blob); const anchor = document.createElement("a"); anchor.href = url; anchor.download = filename; document.body.append(anchor); anchor.click(); anchor.remove(); setTimeout(()=>URL.revokeObjectURL(url),30000); notify("文件已准备下载，请查看浏览器下载位置。");
    } catch(error) { notify(error.message || "下载未完成，请重试。",true); }
  }

  async function previewImport(file) {
    const sequence = ++importSequence;
    importBackup = null; importRevision = null; importFileName = "";
    $("#import-preview").innerHTML = "";
    $("#import-feedback").className = "form-feedback";
    if (!file) return;
    try {
      if (file.size > 5 * 1024 * 1024) throw new Error("这份文件超过 5 MB。请选择工作台导出的个人记录备份，不要把项目材料打包导入。");
      const backup = JSON.parse(await file.text());
      const result = await api("/api/import/preview",{backup});
      if (sequence !== importSequence || currentView !== "backup" || !$("#import-preview")) return;
      importBackup = backup; importRevision = store.state.revision; importFileName = file.name;
      const labels = {facts:"事实",evidence:"成果",decisions:"决策",reviews:"反馈",projectStates:"项目状态"};
      $("#import-preview").innerHTML = `<div class="import-preview"><h3>备份可以读取，请核对内容</h3><p class="fine-print">${esc(file.name)}</p><div class="import-counts">${Object.entries(labels).map(([key,label])=>`<span>${label} <strong>${Number(result.counts?.[key] || 0)}</strong></span>`).join("")}</div><p class="fine-print">${esc(result.message || "确认后将替换本机当前记录，替换前自动备份原记录。")}</p><div class="button-stack"><button class="button primary" data-action="confirm-import">确认替换本机记录</button><button class="button" data-action="cancel-import">取消导入</button></div></div>`;
    } catch(error) { if (sequence === importSequence && currentView === "backup") feedback("import-feedback",error instanceof SyntaxError ? "文件不是有效的 JSON 备份。请选择本工作台导出的完整备份。" : error.message,error); }
  }

  async function commitImport(button) {
    if (!importBackup || importRevision === null) return;
    button.disabled = true;
    try { const result = await api("/api/import",{expectedRevision:importRevision,backup:importBackup}); updateState(result); importBackup = null; importRevision = null; render(); notify("备份已导入，替换前的本机记录已自动保存。"); }
    catch(error) { feedback("import-feedback",error.status === 409 ? `${error.message} 当前记录已变化，请刷新后重新选择备份并核对预览。` : error.message); }
    finally { button.disabled = false; }
  }

  document.addEventListener("click",async event=>{
    const button = event.target.closest("[data-action]"); if (!button || button.disabled) return;
    const {action,id,collection,kind,format} = button.dataset;
    if (action === "retry") return bootstrap(true);
    if (action === "dismiss-toast") { $("#toast-region").innerHTML = ""; return; }
    if (!store) return;
    if (action === "view-now") { filters = {query:"",category:"",readiness:"now",horizon:"",favorite:false}; navigate("projects"); }
    else if (action === "reset-filters") { filters = {query:"",category:"",readiness:"",horizon:"",favorite:false}; render(); }
    else if (action === "reset-evidence-search") { evidenceQuery = ""; evidenceStatus = ""; render(); }
    else if (action === "open-project") openProject(id);
    else if (action === "close-project") { $("#project-dialog").close(); activeProjectId = null; }
    else if (action === "favorite") await favoriteProject(id,button);
    else if (action === "copy-prompt") await copy(projectById(id)?.prompt || "");
    else if (action === "copy-text") await copy(button.dataset.text || "");
    else if (action === "download-card") await download(`/api/project-card?id=${encodeURIComponent(id)}`,`项目${id}-${titleForProject(id).replace(/[\\/:*?"<>|]/g,"_")}.md`);
    else if (action === "add-record") openEditor(collection);
    else if (action === "edit-record") openEditor(collection,id);
    else if (action === "delete-record") confirmDelete(collection,id);
    else if (action === "close-editor") { $("#editor-dialog").close(); editorContext = null; }
    else if (action === "close-confirm") $("#confirm-dialog").close();
    else if (action === "review-project") { $("#project-dialog").close(); openEditor("reviews",null,{projectId:id}); }
    else if (action === "decision-tab") { decisionTab = button.dataset.tab; render(); }
    else if (action === "export") await download(`/api/export?format=${encodeURIComponent(format)}&kind=${encodeURIComponent(kind)}`,`职业发展工作台-${kind}-${currentDate()}.${format === "markdown" ? "md" : format}`);
    else if (action === "publication") await download("/api/facts/publication",`当前可用事实-${currentDate()}.md`);
    else if (action === "confirm-import") await commitImport(button);
    else if (action === "cancel-import") { importSequence++; importBackup = null; importRevision = null; importFileName = ""; $("#backup-file").value = ""; $("#import-preview").innerHTML = ""; $("#import-feedback").className = "form-feedback"; }
    else if (action === "refresh-draft") {
      const ok = await bootstrap();
      if (ok) {
        if (editorContext) { editorContext.revision = store.state.revision; feedback("record-feedback","已读取最新记录，当前填写内容保持不变。请核对后再保存。",null,true); }
        if (activeProjectId) { projectRevision = store.state.revision; feedback("project-feedback","已读取最新记录，当前填写内容保持不变。请核对后再保存。",null,true); }
      }
    }
  });

  document.addEventListener("input",event=>{
    if (event.target.closest("#project-filters")) { const values = new FormData($("#project-filters")); filters = {query:String(values.get("query") || ""),category:String(values.get("category") || ""),readiness:String(values.get("readiness") || ""),horizon:String(values.get("horizon") || ""),favorite:values.has("favorite")}; renderProjectResults(); }
    if (event.target.closest("#evidence-search-form")) { evidenceQuery = $("#evidence-search").value; evidenceStatus = $("#evidence-status").value; $("#evidence-results").innerHTML = evidenceResultsHtml(); }
  });
  document.addEventListener("change",event=>{
    if (event.target.id === "fact-filter") { factFilter = event.target.value; render(); }
    if (event.target.id === "edit-status") updateFactRequirements();
    if (event.target.id === "backup-file") previewImport(event.target.files?.[0]);
  });
  document.addEventListener("submit",event=>{
    if (event.target.id === "record-form") { event.preventDefault(); saveRecord(event.target); }
    if (event.target.id === "project-progress-form") { event.preventDefault(); saveProject(event.target); }
    if (event.target.id === "project-filters") event.preventDefault();
    if (event.target.id === "evidence-search-form") event.preventDefault();
  });
  document.addEventListener("keydown",event=>{
    if (event.target.getAttribute("role") === "tab" && ["ArrowLeft","ArrowRight","Home","End"].includes(event.key)) {
      event.preventDefault(); decisionTab = event.key === "Home" ? "decisions" : event.key === "End" ? "reviews" : decisionTab === "decisions" ? "reviews" : "decisions"; render(); $(`[data-tab="${decisionTab}"]`)?.focus();
    }
  });
  $("#editor-dialog").addEventListener("close",()=>{ editorContext = null; });
  $("#project-dialog").addEventListener("close",()=>{ activeProjectId = null; });
  $("#refresh-button").addEventListener("click",()=>bootstrap());
  $("#refresh-top-button").addEventListener("click",()=>bootstrap());
  window.addEventListener("hashchange",()=>{ if (store) { render(); $("#main").focus({preventScroll:true}); window.scrollTo({top:0,behavior:"instant"}); } });
  bootstrap(true);
})();
