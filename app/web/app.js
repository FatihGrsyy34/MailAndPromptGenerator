// PromptGenerator arayüzü. Masaüstünde pywebview'in `window.pywebview.api` köprüsüyle Python motoruna bağlanır;
// tarayıcıda tek başına açılırsa sahte (mock) API ile çalışır, böylece tasarım bağımsız denenebilir.
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const win = $("#win");
const shell = $("#shell");
function busyFx(on) { win.classList.toggle("busy", on); shell.classList.toggle("busy", on); }
const stage = $("#stage");

const DEFAULT_OPTIONS = {
  tone: [["resmi", "Resmi"], ["normal", "Normal"], ["kibar", "Kibar"], ["samimi", "Samimi"], ["insancil", "İnsancıl"], ["net", "Net"], ["ozur", "Özür"], ["tesekkur", "Teşekkür"]],
  recipient: [["ust_yonetici", "Üst yönetici"], ["meslektas", "Meslektaş"], ["musteri", "Müşteri"], ["ekip", "Ekip"], ["tedarikci", "Tedarikçi"], ["genel", "Genel"]],
  length: [["kisa", "Kısa"], ["orta", "Orta"], ["uzun", "Uzun"]],
  lang: [["tr", "TR"], ["en", "EN"]],
  task: [["kod", "Kod"], ["arastirma", "Araştırma"], ["yazi", "Yazı"], ["gorsel", "Görsel"], ["veri", "Veri"], ["agent", "Agent"], ["genel", "Genel"]],
  target: [["claude", "Claude"], ["chatgpt", "ChatGPT"], ["gemini", "Gemini"], ["midjourney", "Midjourney"], ["kodlama_ajani", "Cursor / Claude Code"], ["genel", "Genel"]],
  detail: [["kisa", "Kısa"], ["detayli", "Detaylı"], ["cok_detayli", "Çok detaylı"]],
  plang: [["tr", "TR"], ["en", "EN"]],
  fixlevel: [["iyilestir", "Dili iyileştir"], ["yazim", "Sadece yazım / noktalama"]],
  fixtone: [["", "Tonu koru"]],
};
const NUMBERED = { mail: "tone", prompt: "task", fix: "fixlevel" };
const GROUPS = { mail: ["tone", "recipient", "length", "lang"], prompt: ["task", "target", "detail", "plang"], fix: ["fixlevel", "fixtone"] };

const state = {
  step: "mode",
  mode: null,
  options: DEFAULT_OPTIONS,
  sel: { tone: "normal", recipient: "meslektas", length: "orta", lang: "tr", task: "genel", target: "genel", detail: "detayli", plang: "tr", fixlevel: "iyilestir", fixtone: "" },
  captured: "",
  focusGroup: 0,
  answers: {},
  result: null,
  busy: false,
  mailSeg: "free",   // "free" | "tpl"
  templates: [],
  tpl: null,         // seçili şablon id
  lastTpl: null,     // son doldurulan şablon (uyarlama için)
};

const MOCK_TEMPLATES = [
  { id: "pdd_gonderim", label: "PDD gönderimi", source: "gercek", fields: [
    { key: "alici", label: "Alıcı", type: "text", placeholder: "Ayşe Hanım" },
    { key: "surec", label: "Süreç adı", type: "text", required: true, placeholder: "Fatura Onay Süreci" },
    { key: "poc", label: "PoC / Demo çalışması", type: "bool" },
    { key: "bekleyenler", label: "Ayrıca hatırlatılacak bekleyen konular", type: "list" }] },
  { id: "uat_daveti", label: "UAT toplantısı daveti", source: "taslak", fields: [
    { key: "alici", label: "Alıcı", type: "text" }, { key: "surec", label: "Süreç adı", type: "text", required: true },
    { key: "tarih", label: "Toplantı tarihi/saati", type: "text" }] },
];

// ---------------------------------------------------------------- API köprüsü
const mock = {
  async init() { return { options: DEFAULT_OPTIONS, defaults: {}, captured: new URLSearchParams(location.search).get("sel") || "" }; },
  async generate_mail(p) {
    await fakeProgress(["Taslak yazılıyor", "İnsansılaştırılıyor", "Yazım kontrolü"]);
    const short = p.revision === "Daha kısa yap";
    return {
      subject: p.reply ? "" : "Perşembe demo saati",
      body: short
        ? "Merhaba Ahmet Bey,\n\nPerşembe demosunu 16.00'ya almamız gerekiyor, test ortamı öğlene kadar hazır olmayacak. Uymazsa cuma 10.00 da olur.\n\nİyi çalışmalar,\nFatih Gürsoy"
        : "Merhaba Ahmet Bey,\n\nPerşembe günkü demoyu 14.00'ten 16.00'ya almamız gerekiyor. Test ortamındaki güncelleme öğlene kadar bitmeyecek ve size yarım bir sürüm göstermek istemiyoruz.\n\nSaat size uyuyorsa takvim davetini hemen güncelliyorum. Uymazsa cuma sabahı 10.00 da bizim için mümkün.\n\nAnlayışınız için teşekkür ederim, iyi çalışmalar,\nFatih Gürsoy",
      placeholders: [], notes: "", warnings: [], score: 44,
    };
  },
  async prompt_start(p) {
    await fakeProgress(["İsteğin analiz ediliyor"]);
    if (p.idea.trim().split(/\s+/).length < 5) {
      return { questions: [
        { question: "Sunum ne hakkında ve kime yapılacak?", options: ["Müşteriye ürün tanıtımı", "Yönetime aylık rapor", "Ekip içi eğitim"], default: "Genel bir iş sunumu" },
        { question: "Ne teslim edilsin?", options: ["Slayt slayt içerik", "Sadece taslak/iskelet", "Konuşmacı notlarıyla birlikte"], default: "Slayt slayt içerik" },
      ] };
    }
    return mock.prompt_finish({});
  },
  async prompt_finish() {
    await fakeProgress(["Prompt yazılıyor", "İstekle karşılaştırılıyor"]);
    return {
      understood: "satislar.xlsx'teki verilerden her ay için bölge bazında toplam satış çıkaran, sonucu yeni bir Excel sayfasına yazan bir pandas scripti istiyorsunuz.",
      prompt: "## Rol\nDeneyimli bir Python veri analisti olarak çalış.\n\n## Görev\n`satislar.xlsx` dosyasını pandas ile oku ve her ay için bölge bazında toplam satışı hesaplayan bir Python scripti yaz.\n\n## Gereksinimler\n- Kütüphane: pandas (Excel yazımı için openpyxl).\n- Tarih sütununu aya çevir, `Bölge` ve ay bazında satış tutarlarını topla.\n- Sonucu aynı dosyada `Aylık Özet` adlı yeni bir sayfaya yaz; mevcut sayfalara dokunma.\n- Sütun adları farklıysa script başında değiştirilebilir sabitler olarak tanımla: {$TARIH_SUTUNU}, {$BOLGE_SUTUNU}, {$TUTAR_SUTUNU}.\n\n## Çıktı\nÇalıştırılabilir tek bir .py dosyası ve nasıl çalıştırılacağını anlatan 2-3 satırlık not.",
      assumptions: ["Sonuç aynı dosyada yeni bir sayfaya yazılır", "Sütun adları bilinmediği için yer tutucu kullanıldı"],
    };
  },
  async prompt_regenerate() { return mock.prompt_finish(); },
  async paste(text) { toast("Yapıştırıldı (önizleme modu)"); return true; },
  async copy(text) { try { await navigator.clipboard.writeText(text); } catch (e) {} return true; },
  async fix_text(p) {
    await fakeProgress(p.level === "yazim" ? ["Yazım kontrolü"] : ["Metin iyileştiriliyor", "Yazım kontrolü"]);
    return { subject: "", body: (p.text || "") + (p.note ? `\n\n(önizleme: "${p.note}" uygulandı)` : ""), warnings: [], notes: p.level === "yazim" ? "2 yazım düzeltmesi" : "Cümleler sadeleştirildi" };
  },
  async template_fill(p) {
    const t = state.templates.find((x) => x.id === p.id);
    return { subject: `${p.values.surec || ""} - ${t.label}`, body: `${p.values.alici ? "Merhaba " + p.values.alici + "," : "Merhaba,"}\n\n(Önizleme modu: "${t.label}" şablonunun metni burada, alanlarla doldurulmuş olarak görünür.)\n\nTeşekkürler, iyi çalışmalar dilerim.\nSaygılarımla,`, warnings: [] };
  },
  async template_adapt(p) {
    await fakeProgress(["Şablon uyarlanıyor", "Yazım kontrolü"]);
    const r = await mock.template_fill(p);
    return { ...r, notes: p.note ? "Not metne işlendi" : "Cümleler hafifçe tazelendi" };
  },
  async close() { toast("Pencere kapanır (önizleme modu)"); setTimeout(() => location.reload(), 900); },
};
function fakeProgress(steps) {
  return new Promise((res) => {
    let i = 0;
    const tick = () => { if (i < steps.length) { window.onProgress(steps[i++]); setTimeout(tick, 650); } else res(); };
    tick();
  });
}
let api = mock;
window.onProgress = (text) => setStatus(text + "…", "shimmer");

// ---------------------------------------------------------------- yardımcılar
function setStatus(text, kind = "") { const s = $("#status"); s.textContent = text; s.className = "status " + kind; }
let toastTimer;
function toast(text) { const t = $("#toast"); t.textContent = text; t.classList.add("show"); clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("show"), 1600); }
function kbd(k) { return `<kbd>${k}</kbd>`; }
function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
function labelOf(key, val) { const f = state.options[key].find((o) => o[0] === val); return f ? f[1] : val; }

let lastReported = 0;
function fitStage() {
  const p = $(".panel.active");
  if (!p) return;
  stage.style.height = p.offsetHeight + "px";
  if (api !== mock) {
    // masaüstünde pencere yüksekliği içeriğe göre ayarlanır (geçiş animasyonu bitince kesin değer)
    const target = Math.ceil(win.offsetHeight - stage.offsetHeight + p.offsetHeight);
    if (Math.abs(target - lastReported) > 1) { lastReported = target; api.resize(target); }
  }
}
new ResizeObserver(fitStage).observe(stage);

// ---------------------------------------------------------------- adım geçişleri
const ORDER = { mode: 0, mail: 1, prompt: 1, fix: 1, preview: 2 };
function go(step) {
  const from = $(".panel.active");
  const to = $(`.panel[data-panel="${step}"]`);
  const back = ORDER[step] < ORDER[state.step];
  state.step = step;
  win.dataset.step = step;
  if (from && from !== to) {
    from.classList.remove("active");
    from.classList.add("leaving");
    if (back) from.style.transform = "translateX(12px)";
    setTimeout(() => { from.classList.remove("leaving"); from.style.transform = ""; }, 220);
  }
  $$(".panel.active").forEach((p) => { if (p !== to) p.classList.remove("active"); });
  to.classList.toggle("from-left", back);
  const activate = () => {
    if (state.step !== step) return; // bu arada başka adıma geçildiyse eski geçişi uygulama
    to.classList.remove("from-left"); to.classList.add("active"); fitStage(); layoutAllHL(true);
  };
  requestAnimationFrame(activate);
  setTimeout(activate, 50); // rAF arka planda bekletilirse diye
  renderChrome();
  if (step === "mail") setTimeout(() => { $("#mailContext").focus({ preventScroll: true }); stage.scrollTop = 0; }, 60);
  if (step === "prompt") setTimeout(() => { $("#promptIdea").focus({ preventScroll: true }); stage.scrollTop = 0; }, 60);
}

function renderChrome() {
  const titles = { mode: "Ne yazalım?", mail: "Mail", prompt: "Prompt", fix: "Metni düzelt",
    preview: state.mode === "mail" ? "Mail önizleme" : state.mode === "fix" ? "Düzeltilmiş metin" : "Prompt önizleme" };
  $("#titleText").textContent = titles[state.step];
  win.dataset.mode = state.step === "mode" ? "" : state.mode === "fix" ? "mail" : state.mode;

  const crumb = $("#crumb");
  if (state.step === "mode") crumb.innerHTML = "PromptGenerator";
  else if (state.mode === "fix") crumb.innerHTML = `Düzelt › <b>${labelOf("fixlevel", state.sel.fixlevel)}</b> · ${labelOf("fixtone", state.sel.fixtone)}`;
  else if (state.mode === "mail" && state.mailSeg === "tpl") {
    const t = state.templates.find((x) => x.id === state.tpl);
    crumb.innerHTML = `Mail › Şablon › <b>${esc(t ? t.label : "seç")}</b>`;
  } else if (state.mode === "mail") crumb.innerHTML = `Mail › <b>${labelOf("tone", state.sel.tone)}</b> · ${labelOf("recipient", state.sel.recipient)} · ${labelOf("length", state.sel.length)} · ${state.sel.lang.toUpperCase()}`;
  else crumb.innerHTML = `Prompt › <b>${labelOf("task", state.sel.task)}</b> · ${labelOf("target", state.sel.target)} · ${labelOf("detail", state.sel.detail)}`;

  const h = $("#hints");
  if (state.step === "mode") h.innerHTML = `<span class="h">Mail ${kbd("M")}</span><span class="h">Prompt ${kbd("P")}</span><span class="sep"></span><span class="h main">Seç ${kbd("↵")}</span>`;
  else if (state.step === "preview") h.innerHTML = `<span class="h">Düzenle ${kbd("E")}</span><span class="h">Kopyala ${kbd("Ctrl")}${kbd("C")}</span><span class="sep"></span><span class="h main">Yapıştır ${kbd("↵")}</span>`;
  else if (state.mode === "mail" && state.mailSeg === "tpl") h.innerHTML = `<span class="h">Şablon ${kbd("1")}–${kbd("9")}</span><span class="h">Uyarla ${kbd("Ctrl")}${kbd("⇧")}${kbd("↵")}</span><span class="sep"></span><span class="h main">Doldur ${kbd("Ctrl")}${kbd("↵")}</span>`;
  else h.innerHTML = `<span class="h">Seçenek ${kbd("↑")}${kbd("↓")}${kbd("←")}${kbd("→")}</span><span class="sep"></span><span class="h main">Yaz ${kbd("Ctrl")}${kbd("↵")}</span>`;
}

// ---------------------------------------------------------------- 1. mod
function chooseMode(mode) {
  if (mode === "fix" && !state.captured) { toast("Önce düzeltmek istediğin metni seç, sonra Ctrl+Space"); return; }
  if (mode === "fix") $("#fixSrc").textContent = state.captured;
  state.mode = mode;
  state.focusGroup = 0;
  go(mode);
}
$$(".mode").forEach((b) => b.addEventListener("click", () => chooseMode(b.dataset.mode)));

// ---------------------------------------------------------------- çip grupları
function renderGroups() {
  $$(".group[data-key]").forEach((g) => {
    const key = g.dataset.key;
    const numbered = Object.values(NUMBERED).includes(key);
    g.innerHTML = `<div class="glabel">${g.dataset.label}</div><div class="chips"><div class="hl nomove"></div>${state.options[key]
      .map(([v, l], i) => `<button class="chip" data-v="${v}" style="--i:${i}">${numbered && i < 9 ? `<span class="n">${i + 1}</span>` : ""}${esc(l)}</button>`)
      .join("")}</div>`;
    $$(".chip", g).forEach((c) => c.addEventListener("click", () => select(key, c.dataset.v)));
  });
  $$(".group[data-key]").forEach((g) => markSel(g.dataset.key, true));
}

function select(key, val) {
  state.sel[key] = val;
  markSel(key, false);
  renderChrome();
}
function markSel(key, instant) {
  const g = $(`.group[data-key="${key}"]`);
  $$(".chip", g).forEach((c) => c.classList.toggle("sel", c.dataset.v === state.sel[key]));
  layoutHL(g, instant);
}
function layoutHL(g, instant) {
  const chip = $(".chip.sel", g);
  const hl = $(".hl", g);
  if (!chip || !hl || !g.offsetParent) return;
  hl.classList.toggle("nomove", !!instant);
  hl.style.width = chip.offsetWidth + "px";
  hl.style.height = chip.offsetHeight + "px";
  hl.style.transform = `translate(${chip.offsetLeft}px, ${chip.offsetTop}px)`;
  if (instant) requestAnimationFrame(() => hl.classList.remove("nomove"));
}
function layoutAllHL(instant) { $$(".panel.active .group[data-key]").forEach((g) => layoutHL(g, instant)); }
window.addEventListener("resize", () => layoutAllHL(true));

function moveSel(key, delta) {
  const opts = state.options[key];
  const i = opts.findIndex((o) => o[0] === state.sel[key]);
  select(key, opts[(i + delta + opts.length) % opts.length][0]);
}
function setFocusGroup(i) {
  const keys = GROUPS[state.mode];
  state.focusGroup = (i + keys.length) % keys.length;
  $$(".group").forEach((g) => g.classList.toggle("focus", g.dataset.key === keys[state.focusGroup]));
}

// ---------------------------------------------------------------- imleç ışığı
document.addEventListener("pointermove", (e) => {
  const el = e.target.closest && e.target.closest(".spot");
  if (!el) return;
  const r = el.getBoundingClientRect();
  el.style.setProperty("--mx", e.clientX - r.left + "px");
  el.style.setProperty("--my", e.clientY - r.top + "px");
});

// ---------------------------------------------------------------- üretim
function startBusy() {
  state.busy = true;
  busyFx(true);
  $("#skeleton").hidden = false;
  $("#out").innerHTML = "";
  $("#subject").hidden = true;
  $("#meta").innerHTML = "";
  $("#refine").innerHTML = "";
  $("#assumptions").hidden = true;
  $("#understood").hidden = true;
}
function endBusy(ok = true) {
  state.busy = false;
  busyFx(false);
  $("#skeleton").hidden = true;
  setStatus(ok ? "Hazır" : "Hata", ok ? "done" : "warn");
}

async function generate(extra = {}) {
  if (state.busy) return;
  try { api.save_prefs && api.save_prefs(state.sel); } catch (e) {}
  if (state.mode === "mail" && state.mailSeg === "tpl") return tplRun(!!extra.adapt);
  if (state.mode === "fix") return fixRun(state.captured, state.sel.fixlevel, state.sel.fixtone, $("#fixNote").value.trim());
  if (state.mode === "mail") {
    const context = $("#mailContext").value.trim();
    if (!context) { shake($("#mailContext").parentElement); return; }
    go("preview");
    startBusy();
    try {
      const r = await api.generate_mail({
        context, tone: state.sel.tone, recipient: state.sel.recipient, length: state.sel.length, lang: state.sel.lang,
        reply: !!(state.captured && $("#replyMode").checked), thread: state.captured && $("#replyMode").checked ? state.captured : "",
        ...extra,
      });
      endBusy();
      showMail(r);
    } catch (e) { endBusy(false); showError(e); }
  } else {
    const idea = $("#promptIdea").value.trim();
    if (!idea) { shake($("#promptIdea").parentElement); return; }
    busyFx(true);
    state.busy = true;
    try {
      const r = await api.prompt_start({ idea, task_type: state.sel.task, target: state.sel.target, detail: state.sel.detail, lang: state.sel.plang });
      if (r.questions && r.questions.length) {
        state.busy = false; busyFx(false); setStatus("Birkaç soru", "warn");
        showQuestions(r.questions);
        return;
      }
      go("preview"); startBusy(); endBusy(); showPrompt(r);
    } catch (e) { state.busy = false; busyFx(false); go("preview"); showError(e); }
  }
}

function shake(el) {
  el.animate([{ transform: "translateX(0)" }, { transform: "translateX(-5px)" }, { transform: "translateX(5px)" }, { transform: "translateX(0)" }], { duration: 220, easing: "ease-out" });
  el.querySelector("textarea")?.focus();
}

function showQuestions(qs) {
  const box = $("#questions");
  box.hidden = false;
  state.answers = {};
  box.innerHTML = `<div class="qtitle">Tam istediğini yazabilmem için şunları netleştirelim (boş bırakırsan varsayımla devam ederim)</div>` +
    qs.map((q, qi) => `<div class="q">${esc(q.question)}<small>Varsayım: ${esc(q.default || "")}</small></div>
      <div class="chips" data-q="${qi}">${q.options.map((o, i) => `<button class="chip" style="--i:${i}" data-o="${esc(o)}">${esc(o)}</button>`).join("")}</div>`).join("") +
    `<div class="refine"><span class="spacer"></span><button class="act primary" id="qgo">Devam ${kbd("Ctrl")}${kbd("↵")}</button></div>`;
  $$(".chips[data-q]", box).forEach((row) => {
    const q = qs[+row.dataset.q];
    $$(".chip", row).forEach((c) => c.addEventListener("click", () => {
      const on = !c.classList.contains("sel");
      $$(".chip", row).forEach((x) => x.classList.remove("sel"));
      c.classList.toggle("sel", on);
      c.style.background = on ? "rgba(167,139,250,0.14)" : "";
      $$(".chip", row).forEach((x) => { if (x !== c) x.style.background = ""; });
      if (on) state.answers[q.question] = c.dataset.o; else delete state.answers[q.question];
    }));
  });
  $("#qgo").addEventListener("click", finishPrompt);
  fitStage();
}

async function finishPrompt() {
  if (state.busy) return;
  $("#questions").hidden = true;
  go("preview");
  startBusy();
  try { const r = await api.prompt_finish({ answers: state.answers }); endBusy(); showPrompt(r); }
  catch (e) { endBusy(false); showError(e); }
}

// kelime kelime akış efekti (sonuç hazır gelse de canlı hissettirir)
function reveal(el, text, done) {
  el.innerHTML = "";
  const parts = text.match(/\S+\s*|\s+/g) || [];
  const caret = document.createElement("span");
  caret.className = "caret";
  el.appendChild(caret);
  let i = 0;
  const per = Math.max(1, Math.ceil(parts.length / 45));
  const step = () => {
    for (let k = 0; k < per && i < parts.length; k++, i++) {
      const s = document.createElement("span");
      s.className = "chunk";
      s.textContent = parts[i];
      el.insertBefore(s, caret);
    }
    fitStage();
    if (i < parts.length) setTimeout(step, 14);
    else { caret.remove(); el.textContent = text; done && done(); }
  };
  step();
}

const actionsHtml = () => `<div class="actions">${state.result && state.result.subject ? `<button class="act" data-copysubj>Konuyu kopyala</button>` : ""}<span class="spacer"></span><button class="act" data-copy>Kopyala ${kbd("Ctrl")}${kbd("C")}</button><button class="act primary" data-paste>Yapıştır ${kbd("↵")}</button></div>`;
function pill(text, kind = "") { return `<span class="pill ${kind}">${esc(text)}</span>`; }

function showMail(r) {
  state.result = r;
  const subj = $("#subject");
  if (r.subject) { subj.hidden = false; subj.innerHTML = `Konu: <b>${esc(r.subject)}</b>`; }
  $("#out").classList.remove("mono");
  reveal($("#out"), r.body, () => {
    const hard = (r.warnings || []).filter((w) => w.hard);
    $("#meta").innerHTML =
      (hard.length ? pill(`${hard.length} uyarı`, "warn") : pill("Kontroller temiz", "ok")) +
      (r.score ? pill(`Doğallık ${r.score}/50`) : "") +
      (r.placeholders || []).map((p) => pill(`Doldur: ${p}`, "warn")).join("") +
      (r.notes ? pill(r.notes) : "");
    if (r.fix) {
      $("#refine").innerHTML = ["Daha kısa", "Daha resmi", "Daha samimi"].map((t, i) => `<button class="act" data-fixrev="${t}">${t} ${kbd("⇧" + (i + 1))}</button>`).join("") +
        `<button class="act" data-regen>Baştan ${kbd("Ctrl")}${kbd("R")}</button>` + actionsHtml();
      bindActions();
      $$("[data-fixrev]").forEach((b) => b.addEventListener("click", () => fixRefine(b.dataset.fixrev)));
      fitStage();
      return;
    }
    if (r.template) {
      $("#refine").innerHTML = `<button class="act" data-tpladapt>Gemini ile uyarla ${kbd("Ctrl")}${kbd("R")}</button>` + actionsHtml();
      bindActions();
      $$("[data-tpladapt]").forEach((b) => b.addEventListener("click", () => tplRun(true)));
      fitStage();
      return;
    }
    $("#refine").innerHTML =
      ["Daha kısa", "Daha resmi", "Daha samimi"].map((t, i) => `<button class="act" data-rev="${t}">${t} ${kbd("⇧" + (i + 1))}</button>`).join("") +
      `<button class="act" data-regen>Yeniden ${kbd("Ctrl")}${kbd("R")}</button>` + actionsHtml();
    bindActions();
    fitStage();
  });
}

function showPrompt(r) {
  state.result = r;
  const u = $("#understood");
  u.hidden = false;
  u.textContent = "Anladığım: " + r.understood;
  $("#out").classList.add("mono");
  reveal($("#out"), r.prompt, () => {
    const a = $("#assumptions");
    a.hidden = !(r.assumptions && r.assumptions.length);
    a.innerHTML = `<div class="glabel">Varsayımlar · düzeltip yeniden üretebilirsin</div><div class="alist">${(r.assumptions || [])
      .map((x, i) => `<div class="arow" style="animation-delay:${i * 30}ms"><span data-i="${i}">${esc(x)}</span><button data-edit="${i}">Düzenle</button><button data-del="${i}">Sil</button></div>`).join("")}</div>`;
    $$("[data-edit]", a).forEach((b) => b.addEventListener("click", () => {
      const s = $(`span[data-i="${b.dataset.edit}"]`, a);
      s.contentEditable = "true"; s.focus(); document.getSelection().selectAllChildren(s);
    }));
    $$("[data-del]", a).forEach((b) => b.addEventListener("click", () => { b.parentElement.remove(); fitStage(); }));
    $("#refine").innerHTML = `<button class="act" data-regen>Varsayımlarla yeniden üret ${kbd("Ctrl")}${kbd("R")}</button>` + actionsHtml();
    bindActions();
    fitStage();
  });
}

function showError(e) {
  $("#skeleton").hidden = true;
  $("#out").classList.remove("mono");
  $("#out").textContent = "Bir sorun oldu: " + (e && e.message ? e.message : e);
  $("#refine").innerHTML = `<button class="act" data-regen>Tekrar dene</button>`;
  bindActions();
}

function currentText() {
  const out = $("#out").innerText.trim();
  if (state.mode === "mail" && state.result && state.result.subject && !state.captured) return out; // konu ayrıca gösterilir, gövde yapıştırılır
  return out;
}

function bindActions() {
  $$("[data-rev]").forEach((b) => b.addEventListener("click", () => refine(b.dataset.rev)));
  $$("[data-regen]").forEach((b) => b.addEventListener("click", regenerate));
  $$("[data-copy]").forEach((b) => b.addEventListener("click", copyOut));
  $$("[data-copysubj]").forEach((b) => b.addEventListener("click", async () => { await api.copy(state.result.subject); toast("Konu kopyalandı"); }));
  $$("[data-paste]").forEach((b) => b.addEventListener("click", pasteOut));
}

async function refine(label) {
  const map = { "Daha kısa": "Daha kısa yap", "Daha resmi": "Daha resmi yap", "Daha samimi": "Daha samimi yap" };
  startBusy();
  try { const r = await api.generate_mail({ revision: map[label] || label, previous: state.result }); endBusy(); showMail(r); }
  catch (e) { endBusy(false); showError(e); }
}

async function regenerate() {
  if (state.mode === "mail" && state.result && state.result.template) return tplRun(true);
  if (state.mode === "fix") return generate();
  if (state.mode === "mail") { go("mail"); return generate(); }
  const assumptions = $$("#assumptions span[data-i]").map((s) => s.innerText.trim()).filter(Boolean);
  startBusy();
  try { const r = await api.prompt_regenerate({ assumptions }); endBusy(); showPrompt(r); }
  catch (e) { endBusy(false); showError(e); }
}

async function copyOut() { await api.copy(currentText()); toast("Kopyalandı"); }
async function pasteOut() {
  const text = currentText();
  if (!text) return;
  win.classList.add("closing");
  setTimeout(() => api.paste(text), 90);
}
function toggleEdit() {
  const out = $("#out");
  const on = out.contentEditable !== "true";
  out.contentEditable = on ? "true" : "false";
  out.classList.toggle("editing", on);
  if (on) out.focus();
}

// ---------------------------------------------------------------- seçili metni düzelt
async function fixRun(text, level, tone, note) {
  if (state.busy) return;
  if (!text) { toast("Düzeltilecek metin yok"); return; }
  try { api.save_prefs && api.save_prefs(state.sel); } catch (e) {}
  go("preview");
  startBusy();
  try {
    const r = await api.fix_text({ text, level, tone, note });
    endBusy();
    showMail({ ...r, fix: true });
  } catch (e) { endBusy(false); showError(e); }
}
function fixRefine(label) {
  const map = { "Daha kısa": ["", "Anlamı koruyarak daha kısa yap"], "Daha resmi": ["resmi", ""], "Daha samimi": ["samimi", ""] };
  const [tone, note] = map[label] || ["", label];
  return fixRun($("#out").innerText.trim(), "iyilestir", tone, note);
}
$$("[data-capact]").forEach((b) => b.addEventListener("click", () => {
  if (b.dataset.capact === "fix") return chooseMode("fix");
  $("#replyMode").checked = true;
  chooseMode("mail");
}));

// ---------------------------------------------------------------- şablonlar
function setSeg(seg) {
  state.mailSeg = seg;
  $$("#mailSeg .seg-btn").forEach((b) => b.classList.toggle("on", b.dataset.seg === seg));
  const on = $(`#mailSeg .seg-btn[data-seg="${seg}"]`);
  const hl = $("#mailSeg .seg-hl");
  hl.style.width = on.offsetWidth + "px";
  hl.style.transform = `translateX(${on.offsetLeft - 3}px)`;
  $("#freeForm").hidden = seg !== "free";
  $("#tplForm").hidden = seg !== "tpl";
  if (seg === "tpl" && !state.tpl && state.templates.length) selectTpl(state.templates[0].id);
  renderChrome();
  requestAnimationFrame(() => { layoutAllHL(true); fitStage(); });
  if (seg === "free") setTimeout(() => $("#mailContext").focus({ preventScroll: true }), 30);
}
$$("#mailSeg .seg-btn").forEach((b) => b.addEventListener("click", () => setSeg(b.dataset.seg)));

function renderTemplates() {
  const box = $("#tplChips");
  box.innerHTML = `<div class="hl nomove"></div>` + state.templates.map((t, i) =>
    `<button class="chip" data-tpl="${t.id}" style="--i:${i}">${i < 9 ? `<span class="n">${i + 1}</span>` : ""}${esc(t.label)}${t.source === "taslak" ? ` <span class="badge">taslak</span>` : ""}</button>`).join("");
  $$("[data-tpl]", box).forEach((c) => c.addEventListener("click", () => selectTpl(c.dataset.tpl)));
}

function selectTpl(id) {
  state.tpl = id;
  const t = state.templates.find((x) => x.id === id);
  const box = $("#tplChips");
  $$("[data-tpl]", box).forEach((c) => c.classList.toggle("sel", c.dataset.tpl === id));
  const chip = $(".chip.sel", box), hl = $(".hl", box);
  if (chip && hl) { hl.style.width = chip.offsetWidth + "px"; hl.style.height = chip.offsetHeight + "px"; hl.style.transform = `translate(${chip.offsetLeft}px, ${chip.offsetTop}px)`; }
  $("#tplFields").innerHTML = t.fields.map((f) => {
    const req = f.required ? " <i>*</i>" : "";
    if (f.type === "bool") return `<label class="tf check"><label class="switch"><input type="checkbox" data-f="${f.key}"><span></span></label>${esc(f.label)}</label>`;
    const wide = f.type === "textarea" || f.type === "list" ? " wide" : "";
    const ph = esc(f.placeholder || (f.type === "list" ? "Her satır bir madde" : ""));
    const input = f.type === "textarea" || f.type === "list"
      ? `<textarea rows="${f.type === "list" ? 3 : 2}" data-f="${f.key}" placeholder="${ph}"></textarea>`
      : `<input type="text" data-f="${f.key}" placeholder="${ph}">`;
    return `<div class="tf${wide}"><label>${esc(f.label)}${req}</label>${input}</div>`;
  }).join("");
  $$("#tplFields [data-f]").forEach((el) => el.addEventListener("input", () => el.closest(".tf").classList.remove("err")));
  const src = $("#tplSrc");
  src.textContent = t.source === "taslak" ? "Taslak şablon: gerçek örnek maille güncellenecek" : "Kendi gönderdiğin maillerden";
  src.classList.toggle("draft", t.source === "taslak");
  renderChrome();
  requestAnimationFrame(fitStage);
  setTimeout(() => { const first = $("#tplFields input[type=text], #tplFields textarea"); first && first.focus({ preventScroll: true }); }, 30);
}

function tplValues() {
  const vals = {};
  $$("#tplFields [data-f]").forEach((el) => { vals[el.dataset.f] = el.type === "checkbox" ? el.checked : el.value.trim(); });
  return vals;
}

async function tplRun(adapt) {
  if (state.busy) return;
  // önizlemeden "uyarla" denirse son doldurulan şablon kullanılır
  const fromPreview = state.step === "preview" && state.lastTpl;
  const id = fromPreview ? state.lastTpl.id : state.tpl;
  const values = fromPreview ? state.lastTpl.values : tplValues();
  const t = state.templates.find((x) => x.id === id);
  if (!t) return;
  if (!fromPreview) {
    const missing = t.fields.filter((f) => f.required && !String(values[f.key] || "").trim());
    if (missing.length) {
      missing.forEach((f) => $(`#tplFields [data-f="${f.key}"]`).closest(".tf").classList.add("err"));
      shake($("#tplFields"));
      toast("Zorunlu alan: " + missing.map((f) => f.label).join(", "));
      return;
    }
  }
  const note = $("#tplNote").value.trim();
  const useLLM = adapt || !!note;
  state.lastTpl = { id, values };
  go("preview");
  startBusy();
  try {
    const r = useLLM ? await api.template_adapt({ id, values, note }) : await api.template_fill({ id, values });
    endBusy();
    showMail({ ...r, template: true });
  } catch (e) { endBusy(false); showError(e); }
}
$("#tplFill").addEventListener("click", () => tplRun(false));
$("#tplAdapt").addEventListener("click", () => tplRun(true));

// ---------------------------------------------------------------- klavye
document.addEventListener("keydown", (e) => {
  const typing = e.target.matches("textarea, [contenteditable='true']");
  if (e.key === "Escape") {
    e.preventDefault();
    if ($("#out").contentEditable === "true") return toggleEdit();
    if (state.step === "preview") return go(state.mode);
    if (state.step !== "mode") return go("mode");
    win.classList.add("closing");
    return setTimeout(() => api.close(), 90);
  }
  if (state.step === "mode") {
    const k = e.key.toLowerCase();
    if (k === "m") return chooseMode("mail");
    if (k === "p") return chooseMode("prompt");
    if (k === "d") return chooseMode("fix");
    if (k === "y" && state.captured) { $("#replyMode").checked = true; return chooseMode("mail"); }
    const modes = $$(".mode");
    const cur = modes.findIndex((m) => m.classList.contains("kb"));
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      modes.forEach((m) => m.classList.remove("kb"));
      modes[cur === 0 ? 1 : 0].classList.add("kb");
      return;
    }
    if (e.key === "Enter") return chooseMode(cur === 1 ? "prompt" : "mail");
    return;
  }
  if (state.step === "mail" || state.step === "prompt" || state.step === "fix") {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      if (state.mode === "mail") return generate({ adapt: e.shiftKey });
      return $("#questions").hidden ? generate() : finishPrompt();
    }
    if (state.mode === "mail" && !typing && (e.key.toLowerCase() === "t" || e.key.toLowerCase() === "f")) {
      return setSeg(e.key.toLowerCase() === "t" ? "tpl" : "free");
    }
    if (state.mode === "mail" && state.mailSeg === "tpl" && !typing) {
      if (/^[1-9]$/.test(e.key) && state.templates[+e.key - 1]) return selectTpl(state.templates[+e.key - 1].id);
      if (e.key === "Enter") { e.preventDefault(); return tplRun(false); }
      return;
    }
    if (typing && e.target.tagName === "TEXTAREA" && e.altKey === false) {
      if ((e.key === "ArrowUp" && e.target.selectionStart === 0) ) { e.preventDefault(); e.target.blur(); setFocusGroup(GROUPS[state.mode].length - 1); }
      return;
    }
    if (typing) return;
    const keys = GROUPS[state.mode];
    if (e.key === "ArrowDown") { e.preventDefault(); if (state.focusGroup === keys.length - 1) { $$(".group").forEach((g) => g.classList.remove("focus")); return $(".panel.active textarea").focus(); } return setFocusGroup(state.focusGroup + 1); }
    if (e.key === "ArrowUp") { e.preventDefault(); return setFocusGroup(state.focusGroup - 1); }
    if (e.key === "ArrowRight") { e.preventDefault(); setFocusGroup(state.focusGroup); return moveSel(keys[state.focusGroup], 1); }
    if (e.key === "ArrowLeft") { e.preventDefault(); setFocusGroup(state.focusGroup); return moveSel(keys[state.focusGroup], -1); }
    if (/^[1-9]$/.test(e.key)) {
      const key = NUMBERED[state.mode];
      const opt = state.options[key][+e.key - 1];
      if (opt) select(key, opt[0]);
      return;
    }
    if (e.key === "Enter") { e.preventDefault(); return generate(); }
    return;
  }
  if (state.step === "preview") {
    if (typing) { if (e.key === "Enter" && e.ctrlKey) { e.preventDefault(); toggleEdit(); } return; }
    if (state.busy) return;
    if (e.key === "Enter") { e.preventDefault(); return pasteOut(); }
    if (e.key.toLowerCase() === "e") { e.preventDefault(); return toggleEdit(); }
    if (e.key.toLowerCase() === "c" && e.ctrlKey && !String(document.getSelection())) { e.preventDefault(); return copyOut(); }
    if (e.key.toLowerCase() === "r" && e.ctrlKey) { e.preventDefault(); return regenerate(); }
    if (e.shiftKey && state.mode === "fix" && /^Digit[1-3]$/.test(e.code)) {
      e.preventDefault();
      return fixRefine(["Daha kısa", "Daha resmi", "Daha samimi"][+e.code.slice(-1) - 1]);
    }
    if (e.shiftKey && state.mode === "mail" && /^Digit[1-3]$/.test(e.code)) {
      e.preventDefault();
      return refine(["Daha kısa", "Daha resmi", "Daha samimi"][+e.code.slice(-1) - 1]);
    }
  }
});
$("#back").addEventListener("click", () => go(state.step === "preview" ? state.mode : "mode"));

// ---------------------------------------------------------------- başlangıç
async function boot(realApi) {
  if (realApi) { api = realApi; document.body.classList.add("native"); }
  else document.body.classList.add("standalone");
  const init = await api.init();
  state.options = { ...DEFAULT_OPTIONS, ...(init.options || {}) };
  state.options.fixtone = [["", "Tonu koru"], ...state.options.tone];
  Object.assign(state.sel, init.defaults || {});
  applyCapture(init.captured || "");
  state.templates = init.templates || MOCK_TEMPLATES;
  renderGroups();
  renderTemplates();
  go("mode");
}
function applyCapture(text) {
  state.captured = text;
  $("#captureBox").hidden = !text;
  $("#captureText").textContent = text;
  $("#replyToggle").hidden = !text;
}
// Python her kısayolda pencereyi göstermeden önce bunu çağırır: yeni seçim + ilk ekrana dönüş
window.resetForShow = (captured, mode, hideOnly) => {
  win.classList.remove("closing"); busyFx(false);
  if (hideOnly) return;
  win.style.animation = "none"; void win.offsetWidth; win.style.animation = "";
  $("#mailContext").value = ""; $("#promptIdea").value = ""; $("#tplNote").value = ""; $("#fixNote").value = "";
  $$("#tplFields [data-f]").forEach((el) => { if (el.type === "checkbox") el.checked = false; else el.value = ""; });
  $("#questions").hidden = true;
  applyCapture(captured || "");
  setStatus("");
  if (mode) chooseMode(mode); else go("mode");
};

// Pencere göründüğü anda: açılış animasyonu ve klavye odağı (Python beklemeden çağırır)
window.onShown = () => {
  win.classList.remove("closing");
  win.style.animation = "none"; void win.offsetWidth; win.style.animation = "";
  window.focus(); document.body.focus();
};
// Seçili metin pencere açıldıktan sonra gelir
window.setCaptured = (text) => { applyCapture(text || ""); fitStage(); };

// Pencereyi sürükle: üst/alt çubuğa (buton dışında) basılınca taşımayı Windows'a devret
document.addEventListener("pointerdown", (e) => {
  if (e.button !== 0 || api === mock || !api.start_drag) return;
  if (!e.target.closest(".top, .bar") || e.target.closest("button, a, input, textarea, [contenteditable='true']")) return;
  e.preventDefault();
  api.start_drag();
});

let booted = false;
window.addEventListener("pywebviewready", () => { if (!booted) { booted = true; boot(window.pywebview.api); } });
setTimeout(() => { if (!booted && !window.pywebview) { booted = true; boot(null); } }, 250);
