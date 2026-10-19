"use strict";

const state = {
  csrfToken: null,
  authMode: "login",
  soundEnabled: localStorage.getItem("anger-sound-muted") !== "true",
  theme: localStorage.getItem("anger-theme") || "dark",
  shredding: false,
};

const elements = {
  landingPanel: document.querySelector("#landing-panel"),
  appPanel: document.querySelector("#app-panel"),
  pageShell: document.querySelector(".page-shell"),
  authForm: document.querySelector("#auth-form"),
  authMessage: document.querySelector("#auth-message"),
  authSubmit: document.querySelector("#auth-submit"),
  passwordHint: document.querySelector("#password-hint"),
  passwordInput: document.querySelector("#password"),
  showLogin: document.querySelector("#show-login"),
  showRegister: document.querySelector("#show-register"),
  userName: document.querySelector("#user-name"),
  accountMenu: document.querySelector("#account-menu"),
  profileForm: document.querySelector("#profile-form"),
  profileUsername: document.querySelector("#profile-username"),
  profileMessage: document.querySelector("#profile-message"),
  logoutButton: document.querySelector("#logout-button"),
  themeButtons: document.querySelectorAll("[data-theme-choice]"),
  textInput: document.querySelector("#anger-text"),
  charCount: document.querySelector("#char-count"),
  shredButton: document.querySelector("#shred-button"),
  shredMessage: document.querySelector("#shred-message"),
  soundToggle: document.querySelector("#sound-toggle"),
  soundIcon: document.querySelector("#sound-icon"),
  soundLabel: document.querySelector("#sound-label"),
  stage: document.querySelector("#shred-stage"),
  payload: document.querySelector("#payload"),
  payloadText: document.querySelector("#payload-text"),
  shredParticles: document.querySelector("#shred-particles"),
  firePaper: document.querySelector("#fire-paper"),
  fireText: document.querySelector("#fire-text"),
  fireAsh: document.querySelector("#fire-ash"),
  blackholePaper: document.querySelector("#blackhole-paper"),
  blackholeText: document.querySelector("#blackhole-text"),
  blackholeFragments: document.querySelector("#blackhole-fragments"),
  starfield: document.querySelector("#starfield"),
  stageCaption: document.querySelector("#stage-caption"),
  todayCopy: document.querySelector("#today-copy"),
  historyOpen: document.querySelector("#history-open"),
  historyDialog: document.querySelector("#history-dialog"),
  historyClose: document.querySelector("#history-close"),
  historyMessage: document.querySelector("#history-message"),
  historyList: document.querySelector("#history-list"),
  deleteAllButton: document.querySelector("#delete-all-button"),
  deleteAccountButton: document.querySelector("#delete-account-button"),
};

async function requestApi(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (["POST", "PUT", "PATCH", "DELETE"].includes(method) && state.csrfToken) {
    headers.set("X-CSRF-Token", state.csrfToken);
  }
  const response = await fetch(path, {
    ...options,
    method,
    headers,
    credentials: "same-origin",
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || "요청을 처리하지 못했어요. 잠시 후 다시 시도해주세요.");
  }
  return payload;
}

function setAuthMode(mode) {
  state.authMode = mode;
  const registering = mode === "register";
  elements.showLogin.classList.toggle("is-active", !registering);
  elements.showRegister.classList.toggle("is-active", registering);
  elements.showLogin.setAttribute("aria-selected", String(!registering));
  elements.showRegister.setAttribute("aria-selected", String(registering));
  elements.authSubmit.textContent = registering ? "회원가입" : "로그인";
  elements.passwordHint.hidden = !registering;
  elements.passwordInput.autocomplete = registering ? "new-password" : "current-password";
  elements.passwordInput.pattern = registering ? "(?=.*[A-Za-z])(?=.*[0-9]).{8,256}" : "";
  elements.passwordInput.title = registering ? "영문과 숫자를 모두 포함한 8자 이상의 비밀번호를 입력해주세요." : "";
  elements.authMessage.textContent = "";
}

function showMessage(element, message, kind = "") {
  element.textContent = message;
  element.classList.toggle("is-error", kind === "error");
  element.classList.toggle("is-success", kind === "success");
}

function setSignedIn(user) {
  elements.landingPanel.hidden = true;
  elements.appPanel.hidden = false;
  elements.userName.textContent = user.username;
  elements.profileUsername.value = user.username;
  document.body.classList.add("is-signed-in");
}

function setSignedOut() {
  state.csrfToken = null;
  elements.landingPanel.hidden = false;
  elements.appPanel.hidden = true;
  elements.accountMenu.open = false;
  elements.historyDialog.close();
  elements.historyList.replaceChildren();
  document.body.classList.remove("is-signed-in");
}

function makeEmptyHistory(message = "아직 파쇄한 기록이 없어요.") {
  const empty = document.createElement("p");
  empty.className = "empty-history";
  empty.textContent = message;
  return empty;
}

function updateCharacterCount() {
  const count = Array.from(elements.textInput.value).length;
  elements.charCount.textContent = count.toLocaleString("ko-KR") + " / 5,000";
  return count;
}

function updateStats(stats) {
  const charCount = Number(stats.charCount) || 0;
  const shredCount = Number(stats.shredCount) || 0;
  elements.todayCopy.textContent =
    "오늘 총 " + charCount.toLocaleString("ko-KR") + "자가 파쇄되었어요 · " +
    shredCount.toLocaleString("ko-KR") + "회";
}

async function refreshStats() {
  try {
    updateStats(await requestApi("/api/stats"));
  } catch {
    elements.todayCopy.textContent = "오늘 파쇄한 기록을 불러오지 못했어요.";
  }
}

function getSelectedMode() {
  return document.querySelector('input[name="mode"]:checked').value;
}

function getModeLabel(mode) {
  return {
    shredder: "문서 파쇄",
    blackhole: "블랙홀",
    fire: "불태우기",
  }[mode] || "파쇄";
}

function formatDate(value) {
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).format(new Date(value));
}

function createHistoryCard(entry) {
  const details = document.createElement("details");
  details.className = "history-entry";

  const summary = document.createElement("summary");
  const mode = document.createElement("strong");
  mode.className = "history-mode mode-tag-" + entry.mode;
  mode.textContent = getModeLabel(entry.mode);

  const time = document.createElement("time");
  time.dateTime = entry.createdAt;
  time.textContent = formatDate(entry.createdAt);

  const chevron = document.createElement("span");
  chevron.className = "history-chevron";
  chevron.setAttribute("aria-hidden", "true");
  chevron.textContent = "⌄";
  summary.append(mode, time, chevron);

  const content = document.createElement("div");
  content.className = "history-content";

  const savedText = document.createElement("p");
  savedText.className = "saved-text";
  savedText.textContent = entry.text;

  const actions = document.createElement("div");
  actions.className = "history-actions";

  const shredAgainButton = document.createElement("button");
  shredAgainButton.type = "button";
  shredAgainButton.className = "small-button";
  shredAgainButton.textContent = "다시 파쇄하기";
  shredAgainButton.addEventListener("click", async () => {
    elements.textInput.value = entry.text;
    const radio = document.querySelector('input[name="mode"][value="' + entry.mode + '"]');
    if (radio) radio.checked = true;
    updateModeSelection();
    updateCharacterCount();
    elements.historyDialog.close();
    await submitShred(entry);
  });

  const deleteButton = document.createElement("button");
  deleteButton.type = "button";
  deleteButton.className = "small-button danger-button";
  deleteButton.textContent = "기록 삭제하기";
  deleteButton.addEventListener("click", async () => {
    try {
      await requestApi("/api/entries/" + entry.id, { method: "DELETE" });
      await loadEntries();
      showMessage(elements.historyMessage, "기록을 삭제했어요.", "success");
    } catch (error) {
      showMessage(elements.historyMessage, error.message, "error");
    }
  });

  actions.append(shredAgainButton, deleteButton);
  content.append(savedText, actions);
  details.append(summary, content);
  return details;
}

async function loadEntries() {
  const data = await requestApi("/api/entries");
  elements.historyList.replaceChildren();
  if (!data.entries.length) {
    elements.historyList.append(makeEmptyHistory());
    return;
  }
  for (const entry of data.entries) {
    elements.historyList.append(createHistoryCard(entry));
  }
}

function updateModeSelection() {
  for (const option of document.querySelectorAll(".mode-option")) {
    option.classList.toggle("is-selected", option.querySelector("input").checked);
  }
}

function setTheme(theme) {
  state.theme = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = state.theme;
  localStorage.setItem("anger-theme", state.theme);
  for (const button of elements.themeButtons) {
    button.setAttribute("aria-pressed", String(button.dataset.themeChoice === state.theme));
  }
}

function setSoundEnabled(enabled) {
  state.soundEnabled = enabled;
  localStorage.setItem("anger-sound-muted", String(!enabled));
  elements.soundToggle.setAttribute("aria-pressed", String(enabled));
  elements.soundLabel.textContent = enabled ? "소리 켜짐" : "소리 꺼짐";
  elements.soundIcon.textContent = enabled ? "♫" : "♪";
  elements.soundToggle.classList.toggle("is-muted", !enabled);
}

async function playModeSound(mode) {
  if (!state.soundEnabled) return;
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) return;
  try {
    const audioContext = new AudioContextClass();
    await audioContext.resume();
    const now = audioContext.currentTime;
    const gain = audioContext.createGain();
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(0.16, now + 0.04);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.85);
    gain.connect(audioContext.destination);

    if (mode === "blackhole") {
      const oscillator = audioContext.createOscillator();
      oscillator.type = "sine";
      oscillator.frequency.setValueAtTime(180, now);
      oscillator.frequency.exponentialRampToValueAtTime(42, now + 0.8);
      oscillator.connect(gain);
      oscillator.start(now);
      oscillator.stop(now + 0.86);
    } else {
      const buffer = audioContext.createBuffer(1, audioContext.sampleRate, audioContext.sampleRate);
      const channel = buffer.getChannelData(0);
      for (let index = 0; index < channel.length; index += 1) {
        channel[index] = (Math.random() * 2 - 1) * (1 - index / channel.length);
      }
      const noise = audioContext.createBufferSource();
      noise.buffer = buffer;
      const filter = audioContext.createBiquadFilter();
      filter.type = mode === "fire" ? "lowpass" : "bandpass";
      filter.frequency.setValueAtTime(mode === "fire" ? 900 : 1800, now);
      filter.Q.value = mode === "fire" ? 0.7 : 0.8;
      noise.connect(filter);
      filter.connect(gain);
      noise.start(now);
      noise.stop(now + 0.86);
    }
    window.setTimeout(() => audioContext.close().catch(() => {}), 1100);
  } catch {
    // Some browsers may block audio until a later user gesture.
  }
}

function populateSceneParticles(container, count, className, makeStyle) {
  container.replaceChildren();
  const fragment = document.createDocumentFragment();
  for (let index = 0; index < count; index += 1) {
    const particle = document.createElement("span");
    particle.className = className;
    const values = makeStyle(index);
    for (const [property, value] of Object.entries(values)) {
      particle.style.setProperty(property, value);
    }
    fragment.append(particle);
  }
  container.append(fragment);
}

function seedShredderScene() {
  populateSceneParticles(elements.shredParticles, 48, "shred-particle", () => ({
    "--x": Math.round(Math.random() * 400 - 200) + "px",
    "--width": (4 + Math.random() * 9).toFixed(1) + "px",
    "--height": Math.round(48 + Math.random() * 92) + "px",
    "--fall": Math.round(70 + Math.random() * 170) + "px",
    "--sway": Math.round(Math.random() * 100 - 50) + "px",
    "--rotation": Math.round(Math.random() * 130 - 65) + "deg",
    "--delay": (1.05 + Math.random() * 0.75).toFixed(2) + "s",
  }));
}

function seedFireScene() {
  populateSceneParticles(elements.fireAsh, 56, "ash-particle", () => ({
    "--x": Math.round(Math.random() * 260 - 130) + "px",
    "--y": Math.round(Math.random() * 130 - 65) + "px",
    "--drift": Math.round(Math.random() * 300 - 150) + "px",
    "--rise": Math.round(120 + Math.random() * 350) + "px",
    "--rotation": Math.round(Math.random() * 720 - 360) + "deg",
    "--size": (2 + Math.random() * 5).toFixed(1) + "px",
    "--delay": (2.65 + Math.random() * 0.55).toFixed(2) + "s",
  }));
}

function seedSpaceScene() {
  populateSceneParticles(elements.starfield, 115, "space-star", () => ({
    "--x": (Math.random() * 100).toFixed(2) + "%",
    "--y": (Math.random() * 100).toFixed(2) + "%",
    "--size": (0.8 + Math.random() * 2.3).toFixed(1) + "px",
    "--twinkle": (1.3 + Math.random() * 3.7).toFixed(2) + "s",
    "--delay": (-Math.random() * 4).toFixed(2) + "s",
  }));
  populateSceneParticles(elements.blackholeFragments, 34, "blackhole-fragment", () => {
    const maxY = Math.min(window.innerHeight * 0.4, 360);
    const y = -Math.round(20 + Math.random() * Math.max(0, maxY - 20));
    const xSpread = Math.min(Math.abs(y) * 0.36, Math.min(window.innerWidth * 0.14, 130));
    const x = Math.round(Math.random() * xSpread * 2 - xSpread);
    const radius = Math.hypot(x, y);
    const angle = Math.atan2(y, x);
    const orbitPoint = (radiusScale, turnDegrees) => {
      const orbitAngle = angle + turnDegrees * Math.PI / 180;
      return {
        x: radius * radiusScale * Math.cos(orbitAngle),
        y: radius * radiusScale * Math.sin(orbitAngle),
      };
    };
    const arc1 = orbitPoint(0.83, -150);
    const arc2 = orbitPoint(0.62, -300);
    const arc3 = orbitPoint(0.41, -450);
    const arc4 = orbitPoint(0.2, -600);
    return {
      "--x": x + "px",
      "--y": y + "px",
      "--arc-1-x": (arc1.x - x).toFixed(1) + "px",
      "--arc-1-y": (arc1.y - y).toFixed(1) + "px",
      "--arc-2-x": (arc2.x - x).toFixed(1) + "px",
      "--arc-2-y": (arc2.y - y).toFixed(1) + "px",
      "--arc-3-x": (arc3.x - x).toFixed(1) + "px",
      "--arc-3-y": (arc3.y - y).toFixed(1) + "px",
      "--arc-4-x": (arc4.x - x).toFixed(1) + "px",
      "--arc-4-y": (arc4.y - y).toFixed(1) + "px",
      "--start-z": (180 + Math.random() * 100).toFixed(1) + "px",
      "--arc-1-z": "100px",
      "--arc-2-z": "-40px",
      "--arc-3-z": "-260px",
      "--arc-4-z": "-650px",
      "--pull-z": "-1250px",
      "--pull-x": -x + "px",
      "--pull-y": -y + "px",
      "--width": (10 + Math.random() * 20).toFixed(1) + "px",
      "--height": (14 + Math.random() * 30).toFixed(1) + "px",
      "--rotation": Math.round(Math.random() * 260 - 130) + "deg",
      "--delay": (2.7 + Math.random() * 0.4).toFixed(2) + "s",
      "--duration": (2.05 + Math.random() * 0.35).toFixed(2) + "s",
    };
  });
}

function playShredAnimation(text, mode) {
  document.body.classList.add("is-animating");
  elements.pageShell.inert = true;
  elements.stage.hidden = false;
  elements.stage.className = "shred-stage mode-" + mode;
  elements.payloadText.textContent = text;
  elements.fireText.textContent = text;
  elements.blackholeText.textContent = text;
  elements.stageCaption.textContent = {
    shredder: "문서가 가느다란 조각으로 파쇄되는 중",
    fire: "종이가 까맣게 타고 재가 흩어지는 중",
    blackhole: "우주 한가운데로 종이가 빨려 들어가는 중",
  }[mode] || "파쇄하는 중";

  if (mode === "shredder") seedShredderScene();
  if (mode === "fire") seedFireScene();
  if (mode === "blackhole") seedSpaceScene();

  elements.stage.focus({ preventScroll: true });
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const duration = reducedMotion ? 1200 : {
    shredder: 5100,
    fire: 5200,
    blackhole: 5600,
  }[mode] || 5100;

  window.requestAnimationFrame(() => elements.stage.classList.add("animate-now"));
  return new Promise((resolve) => {
    window.setTimeout(() => {
      elements.stage.className = "shred-stage";
      elements.payloadText.textContent = "";
      elements.fireText.textContent = "";
      elements.blackholeText.textContent = "";
      elements.shredParticles.replaceChildren();
      elements.fireAsh.replaceChildren();
      elements.blackholeFragments.replaceChildren();
      elements.starfield.replaceChildren();
      elements.stageCaption.textContent = "";
      elements.stage.hidden = true;
      elements.pageShell.inert = false;
      document.body.classList.remove("is-animating");
      resolve();
    }, duration);
  });
}

async function submitShred(replayEntry = null) {
  const text = replayEntry ? replayEntry.text : elements.textInput.value;
  const mode = replayEntry ? replayEntry.mode : getSelectedMode();
  if (!text.trim()) {
    showMessage(elements.shredMessage, "먼저 파쇄할 내용을 적어주세요.", "error");
    elements.textInput.focus();
    return;
  }
  if (Array.from(text).length > 5000) {
    showMessage(elements.shredMessage, "내용은 5,000자까지 입력할 수 있어요.", "error");
    return;
  }
  if (state.shredding) return;

  state.shredding = true;
  elements.shredButton.disabled = true;
  showMessage(elements.shredMessage, "마음을 가볍게 보내는 중이에요.");
  try {
    await requestApi("/api/entries", {
      method: "POST",
      body: JSON.stringify({ text, mode }),
    });
    await Promise.all([playShredAnimation(text, mode), playModeSound(mode)]);
    elements.textInput.value = "";
    updateCharacterCount();
    showMessage(elements.shredMessage, "파쇄했어요. 오늘의 기록에서 다시 볼 수 있어요.", "success");
    await Promise.all([loadEntries(), refreshStats()]);
  } catch (error) {
    showMessage(elements.shredMessage, error.message, "error");
  } finally {
    state.shredding = false;
    elements.shredButton.disabled = false;
    elements.shredButton.focus({ preventScroll: true });
  }
}

async function handleAuthSubmit(event) {
  event.preventDefault();
  const formData = new FormData(elements.authForm);
  const route = state.authMode === "register" ? "/api/register" : "/api/login";
  elements.authSubmit.disabled = true;
  showMessage(elements.authMessage, state.authMode === "register" ? "계정을 만들고 있어요." : "로그인하는 중이에요.");
  try {
    const result = await requestApi(route, {
      method: "POST",
      body: JSON.stringify({
        username: formData.get("username"),
        password: formData.get("password"),
      }),
    });
    state.csrfToken = result.csrfToken;
    setSignedIn(result.user);
    elements.authForm.reset();
    await loadEntries();
    await refreshStats();
  } catch (error) {
    showMessage(elements.authMessage, error.message, "error");
  } finally {
    elements.authSubmit.disabled = false;
  }
}

async function initializeSession() {
  try {
    const result = await requestApi("/api/me");
    state.csrfToken = result.csrfToken;
    setSignedIn(result.user);
    await loadEntries();
    await refreshStats();
  } catch {
    setSignedOut();
  }
}

async function handleLogout() {
  try {
    await requestApi("/api/logout", { method: "POST", body: "{}" });
    elements.accountMenu.open = false;
    setSignedOut();
    showMessage(elements.authMessage, "로그아웃했어요.", "success");
  } catch (error) {
    showMessage(elements.shredMessage, error.message, "error");
  }
}

async function updateProfile(event) {
  event.preventDefault();
  const username = elements.profileUsername.value.trim();
  try {
    const result = await requestApi("/api/profile", {
      method: "PATCH",
      body: JSON.stringify({ username }),
    });
    setSignedIn(result.user);
    showMessage(elements.profileMessage, "아이디를 저장했어요.", "success");
  } catch (error) {
    showMessage(elements.profileMessage, error.message, "error");
  }
}

async function deleteAllEntries() {
  if (!window.confirm("파쇄 기록을 모두 삭제할까요?")) return;
  try {
    await requestApi("/api/entries", { method: "DELETE" });
    await loadEntries();
    showMessage(elements.historyMessage, "모든 기록을 삭제했어요.", "success");
    await refreshStats();
  } catch (error) {
    showMessage(elements.historyMessage, error.message, "error");
  }
}

async function deleteAccount() {
  if (!window.confirm("계정과 모든 파쇄 기록을 영구 삭제할까요? 이 작업은 되돌릴 수 없어요.")) return;
  try {
    await requestApi("/api/account", { method: "DELETE", body: "{}" });
    setSignedOut();
    showMessage(elements.authMessage, "계정을 삭제했어요.", "success");
  } catch (error) {
    showMessage(elements.profileMessage, error.message, "error");
  }
}

function bindEvents() {
  elements.showLogin.addEventListener("click", () => setAuthMode("login"));
  elements.showRegister.addEventListener("click", () => setAuthMode("register"));
  elements.authForm.addEventListener("submit", handleAuthSubmit);
  elements.profileForm.addEventListener("submit", updateProfile);
  elements.logoutButton.addEventListener("click", handleLogout);
  elements.textInput.addEventListener("input", updateCharacterCount);
  elements.shredButton.addEventListener("click", () => submitShred());
  elements.soundToggle.addEventListener("click", () => setSoundEnabled(!state.soundEnabled));

  elements.historyOpen.addEventListener("click", async () => {
    elements.accountMenu.open = false;
    showMessage(elements.historyMessage, "");
    try {
      await loadEntries();
    } catch (error) {
      elements.historyList.replaceChildren(makeEmptyHistory(error.message));
    }
    elements.historyDialog.showModal();
  });

  elements.historyClose.addEventListener("click", () => elements.historyDialog.close());
  elements.historyDialog.addEventListener("click", (event) => {
    if (event.target === elements.historyDialog) elements.historyDialog.close();
  });
  elements.deleteAllButton.addEventListener("click", deleteAllEntries);
  elements.deleteAccountButton.addEventListener("click", deleteAccount);

  for (const button of elements.themeButtons) {
    button.addEventListener("click", () => setTheme(button.dataset.themeChoice));
  }
  for (const radio of document.querySelectorAll('input[name="mode"]')) {
    radio.addEventListener("change", updateModeSelection);
  }

  document.addEventListener("click", (event) => {
    if (!elements.accountMenu.contains(event.target)) elements.accountMenu.open = false;
  });
}

bindEvents();
setAuthMode("login");
setTheme(state.theme);
setSoundEnabled(state.soundEnabled);
updateCharacterCount();
updateModeSelection();
refreshStats();
initializeSession();
