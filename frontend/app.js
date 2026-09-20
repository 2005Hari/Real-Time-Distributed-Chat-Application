/**
 * QuantumConnect web client.
 *
 * Talks to the backend over one WebSocket (register, public/private messages, typing,
 * presence) and plain HTTP for file uploads. The backend URL comes from config.js.
 */
(() => {
    'use strict';

    const CFG = window.QC_CONFIG;
    const PUBLIC = 'public';
    const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
    const MAX_MESSAGES_KEPT = 500;
    const HEARTBEAT_MS = 20000;   // ping interval; keeps idle hosting proxies from dropping the socket
    const STALE_MS = 55000;       // no frame for this long => connection is dead, reconnect
    const TYPING_SEND_MS = 2000;  // throttle for outgoing typing events
    const TYPING_SHOW_MS = 4000;  // how long an incoming typing indicator lasts
    const GROUP_WINDOW_MS = 5 * 60 * 1000;
    const EMOJIS = ['😀', '😂', '🥹', '😍', '😎', '🤔', '😅', '😭', '😡', '🥳', '🙌', '👍', '👎', '👏', '🙏', '💪',
        '🔥', '✨', '🎉', '💯', '❤️', '💔', '😴', '🤯', '👀', '🚀', '✅', '❌', '⚡', '☕', '🍕', '🎧'];

    const $ = (id) => document.getElementById(id);
    const el = {
        authScreen: $('auth-screen'), authForm: $('auth-form'), authBtn: $('auth-btn'),
        authNote: $('auth-note'), authError: $('auth-error'), username: $('username-input'), server: $('server-input'),
        password: $('password-input'), invite: $('invite-input'), inviteField: $('invite-field'), authHint: $('auth-hint'),
        tabLogin: $('tab-login'), tabRegister: $('tab-register'),
        mainApp: $('main-app'), scrim: $('scrim'), menuBtn: $('menu-btn'),
        navPublic: $('nav-public'), badgePublic: $('badge-public'), dmList: $('dm-list'),
        onlineList: $('online-list'), onlineCount: $('online-count'),
        myAvatar: $('my-avatar'), myName: $('my-name'), myStatus: $('my-status'), signout: $('signout-btn'),
        chat: $('chat'), chatTitle: $('chat-title'), chatSub: $('chat-sub'),
        connPill: $('conn-pill'), connPillText: $('conn-pill-text'),
        banner: $('conn-banner'), bannerText: $('banner-text'), bannerBtn: $('banner-btn'),
        messages: $('messages'), jump: $('jump-btn'), typing: $('typing'), uploads: $('uploads'),
        composer: $('composer'), input: $('msg-input'), send: $('send-btn'),
        attach: $('attach-btn'), file: $('file-input'), emojiBtn: $('emoji-btn'), emojiPop: $('emoji-pop'),
        toast: $('toast')
    };

    // ---------- helpers ----------
    const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

    const store = {
        get(key) { try { return localStorage.getItem(key); } catch { return null; } },
        set(key, value) { try { localStorage.setItem(key, value); } catch { /* storage unavailable */ } },
        remove(key) { try { localStorage.removeItem(key); } catch { /* storage unavailable */ } }
    };

    const hue = (name) => {
        let hash = 0;
        for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
        return `hsl(${Math.abs(hash) % 360}, 55%, 46%)`;
    };
    const initial = (name) => (name || '?').trim().charAt(0).toUpperCase() || '?';

    const avatarHtml = (name, { small = false, online = null } = {}) =>
        `<span class="avatar${small ? ' sm' : ''}" style="background:${hue(name)}">${esc(initial(name))}` +
        (online === null ? '' : `<span class="presence${online ? ' on' : ''}"></span>`) + `</span>`;

    const fmtTime = (d) => d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const fmtDay = (d) => {
        const today = new Date();
        const yesterday = new Date(today.getTime() - 86400000);
        if (d.toDateString() === today.toDateString()) return 'Today';
        if (d.toDateString() === yesterday.toDateString()) return 'Yesterday';
        return d.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });
    };

    const previewText = (content) =>
        String(content || '').startsWith('__FILE__') ? '📎 Attachment' : String(content || '').replace(/\s+/g, ' ').slice(0, 60);

    const linkify = (escaped) => escaped.replace(
        /(https?:\/\/[^\s<]+[^\s<.,;:!?)"'\]])/g,
        '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>');

    // ws://host/ws  <->  http://host
    const wsToHttp = (wsUrl) => wsUrl.replace(/^ws/i, 'http').replace(/\/ws\/?$/, '').replace(/\/+$/, '');
    const normalizeWs = (input) => {
        let url = input.trim().replace(/\/+$/, '');
        if (!/^[a-z]+:\/\//i.test(url)) url = (location.protocol === 'https:' ? 'wss://' : 'ws://') + url;
        url = url.replace(/^http/i, 'ws');
        return url.endsWith('/ws') ? url : url + '/ws';
    };

    let toastTimer = null;
    function toast(text) {
        el.toast.textContent = text;
        el.toast.hidden = false;
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => { el.toast.hidden = true; }, 3200);
    }

    // ---------- state ----------
    const publicConv = () => ({ key: PUBLIC, kind: 'public', title: 'General', messages: [], unread: 0, loaded: true });
    const state = {
        ws: null, wsUrl: '', apiBase: CFG.HTTP_URL,
        status: 'idle',            // idle | connecting | open | reconnecting | replaced
        everOpened: false,
        name: '', myId: null,
        token: store.get('qc_token') || null,   // signed session token issued by /api/login or /api/register
        convs: new Map([[PUBLIC, publicConv()]]),
        active: PUBLIC,
        online: [],                // [{user_id, username}]
        typing: new Map(),         // scope -> Map(senderId -> {name, timer})
        retry: 0, retryTimer: null, heartbeat: null, lastRx: 0, lastTypingSent: 0,
        pendingOpen: null          // username whose DM the user just asked to open
    };

    const activeConv = () => state.convs.get(state.active) || state.convs.get(PUBLIC);
    const isOpen = () => state.status === 'open' && state.ws && state.ws.readyState === WebSocket.OPEN;

    function resetState() {
        state.convs = new Map([[PUBLIC, publicConv()]]);
        Object.assign(state, {
            active: PUBLIC, online: [], myId: null, everOpened: false, pendingOpen: null, retry: 0
        });
        state.typing.clear();
    }

    // ---------- sign-in ----------
    let authMode = 'login';   // 'login' | 'register'

    const authNote = (text) => { el.authNote.textContent = text; };
    const authError = (text) => { el.authError.textContent = text; };
    function authBusy(busy) {
        el.authBtn.disabled = busy;
        el.authBtn.textContent = busy ? 'Please wait…' : (authMode === 'register' ? 'Create account' : 'Sign in');
    }

    function setAuthMode(mode) {
        authMode = mode;
        const register = mode === 'register';
        el.tabLogin.classList.toggle('active', !register);
        el.tabRegister.classList.toggle('active', register);
        el.tabLogin.setAttribute('aria-selected', String(!register));
        el.tabRegister.setAttribute('aria-selected', String(register));
        el.inviteField.hidden = !register;
        el.authHint.hidden = !register;
        el.password.autocomplete = register ? 'new-password' : 'current-password';
        el.password.placeholder = register ? 'At least 8 characters' : 'Your password';
        authError('');
        authBusy(false);
    }
    function authFail(text) {
        authBusy(false);
        authNote('');
        authError(text);
        state.status = 'idle';
    }

    async function wakeServer() {
        // Free hosting sleeps when idle; a plain HTTP request wakes it before we open the socket.
        const ctrl = new AbortController();
        const timer = setTimeout(() => ctrl.abort(), 75000);
        try {
            await fetch(state.apiBase + '/health', { mode: 'no-cors', cache: 'no-store', signal: ctrl.signal });
        } catch { /* fall through and let the socket attempt report the real error */ }
        finally { clearTimeout(timer); }
    }

    // Point at the chosen backend and wake it up if it is asleep (shows progress on the sign-in card)
    async function prepareConnection(message) {
        state.wsUrl = normalizeWs(el.server.value || CFG.WS_URL);
        state.apiBase = wsToHttp(state.wsUrl);
        authError('');
        authBusy(true);
        authNote(message);
        const slow = setTimeout(() => authNote('Waking up the server. Free hosting can take up to a minute…'), 3000);
        await wakeServer();
        clearTimeout(slow);
    }

    function connectSocket() {
        state.status = 'connecting';
        state.everOpened = false;
        openSocket();
    }

    const errorText = (res, data) => typeof data.detail === 'string' ? data.detail :
        res.status === 422 ? 'Please check what you entered.' : 'Something went wrong. Please try again.';

    async function submitAuth() {
        const username = el.username.value.replace(/\s+/g, ' ').trim();
        const password = el.password.value;
        if (!username || !password) return authError('Enter your username and password.');

        await prepareConnection('Connecting…');

        let res, data;
        try {
            res = await fetch(`${state.apiBase}/api/${authMode}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    username, password,
                    invite_code: authMode === 'register' ? el.invite.value.trim() : undefined
                })
            });
            data = await res.json().catch(() => ({}));
        } catch {
            return authFail('Could not reach the server. Check your connection and try again.');
        }
        if (!res.ok) return authFail(errorText(res, data));

        state.token = data.token;
        state.name = data.username;
        store.set('qc_token', data.token);
        store.set('qc_name', data.username);
        el.password.value = '';
        el.invite.value = '';
        connectSocket();
    }

    // A saved token lets a returning user skip the form
    async function resumeSession() {
        await prepareConnection('Signing you in…');
        connectSocket();
    }

    function enterApp() {
        el.authScreen.classList.add('leaving');
        setTimeout(() => { if (state.everOpened) el.authScreen.style.display = 'none'; }, 400);
        el.mainApp.classList.add('visible');
        authBusy(false);
        authNote('');
        el.myName.textContent = state.name;
        el.myAvatar.textContent = initial(state.name);
        el.myAvatar.style.background = hue(state.name);
        if (!matchMedia('(max-width: 768px)').matches) el.input.focus();
    }

    function signOut() {
        state.status = 'idle';
        state.token = null;
        store.remove('qc_token');
        stopHeartbeat();
        clearTimeout(state.retryTimer);
        if (state.ws) { try { state.ws.close(1000); } catch { /* already closed */ } state.ws = null; }
        resetState();
        closeDrawer();
        el.mainApp.classList.remove('visible');
        el.authScreen.style.display = 'flex';
        requestAnimationFrame(() => el.authScreen.classList.remove('leaving'));
        el.password.value = '';
        setAuthMode('login');
        authNote('');
        el.username.value = store.get('qc_name') || '';
        (el.username.value ? el.password : el.username).focus();
    }

    // The server rejected our session (expired, or the account is gone): back to the sign-in form
    function forceSignOut(message) {
        signOut();
        authError(message || 'Please sign in again.');
    }

    // ---------- socket lifecycle ----------
    function openSocket() {
        clearTimeout(state.retryTimer);
        if (state.ws) { try { state.ws.close(); } catch { /* ignore */ } }

        let ws;
        try {
            ws = new WebSocket(state.wsUrl);
        } catch {
            return authFail('That server address is not valid.');
        }
        state.ws = ws;

        ws.onopen = () => ws.send(JSON.stringify({ type: 'register', token: state.token }));
        ws.onmessage = (event) => {
            state.lastRx = Date.now();
            let data;
            try { data = JSON.parse(event.data); } catch { return; }
            handleProtocol(data);
        };
        ws.onclose = (event) => onSocketClosed(ws, event);
        ws.onerror = () => { /* onclose follows and handles it */ };
    }

    function onSocketClosed(ws, event) {
        if (ws !== state.ws) return;                       // a newer socket already replaced this one
        stopHeartbeat();
        if (state.status === 'idle' || state.status === 'replaced') return;
        if (event && event.code === 4403) return authFail('This site is not allowed to use that server.');
        if (!state.everOpened) return authFail('Could not reach the server. Check the address and try again.');
        scheduleReconnect();
    }

    function scheduleReconnect() {
        state.status = 'reconnecting';
        const delay = Math.min(1000 * 2 ** state.retry, 15000) + Math.random() * 500;
        state.retry++;
        renderConnection();
        clearTimeout(state.retryTimer);
        state.retryTimer = setTimeout(openSocket, delay);
    }

    function reconnectNow() {
        if (state.status === 'idle') return;
        state.status = 'reconnecting';
        renderConnection();
        openSocket();
    }

    function startHeartbeat() {
        stopHeartbeat();
        state.lastRx = Date.now();
        state.heartbeat = setInterval(() => {
            if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return;
            if (Date.now() - state.lastRx > STALE_MS) { state.ws.close(); return; }
            state.ws.send(JSON.stringify({ type: 'ping' }));
        }, HEARTBEAT_MS);
    }
    function stopHeartbeat() { clearInterval(state.heartbeat); state.heartbeat = null; }

    function send(payload) {
        if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return false;
        state.ws.send(JSON.stringify(payload));
        return true;
    }

    // ---------- protocol ----------
    function handleProtocol(data) {
        switch (data.type) {
            case 'welcome': return onWelcome(data);
            case 'public_message': return addMessage(PUBLIC, data);
            case 'private_message': return onPrivateMessage(data);
            case 'private_chat_start': return onPrivateChatStart(data);
            case 'user_list':
                state.online = data.users || [];
                renderSidebar();
                return renderHeader();
            case 'typing':
                if (data.sender_id !== state.myId) noteTyping(data.scope === 'public' ? PUBLIC : data.scope, data.sender_id, data.sender);
                return;
            case 'replaced':
                state.status = 'replaced';
                stopHeartbeat();
                return renderConnection();
            case 'auth_error':
                return forceSignOut(data.message);
            case 'error':
                return toast(data.message || 'Something went wrong.');
            default: // pong and unknown frames only refresh lastRx
        }
    }

    function onWelcome(data) {
        const firstTime = !state.everOpened;
        state.myId = data.user_id;
        state.name = data.username;
        state.everOpened = true;
        state.status = 'open';
        state.retry = 0;

        const pub = state.convs.get(PUBLIC);
        pub.messages = data.history || [];

        for (const chat of data.chats || []) {
            const conv = ensureDm(chat.chat_id, chat.other_user, chat.other_user_id);
            conv.lastText = previewText(chat.last_message);
            conv.lastTs = chat.last_message_time;
        }
        // Anything cached for DMs may have missed messages while offline; refetch on open.
        for (const conv of state.convs.values()) if (conv.kind === 'dm') { conv.loaded = false; conv.messages = []; }

        if (firstTime) enterApp();
        startHeartbeat();
        renderConnection();
        renderSidebar();
        renderHeader();
        renderMessages();
        if (activeConv().kind === 'dm') requestHistory(activeConv());
    }

    function ensureDm(chatId, otherName, otherId) {
        let conv = state.convs.get(chatId);
        if (!conv) {
            conv = { key: chatId, kind: 'dm', otherName, otherId, messages: [], unread: 0, loaded: false, lastText: '', lastTs: null };
            state.convs.set(chatId, conv);
        } else {
            if (otherName) conv.otherName = otherName;
            if (otherId) conv.otherId = otherId;
        }
        return conv;
    }

    function onPrivateMessage(data) {
        const mine = data.sender_id === state.myId;
        const conv = ensureDm(data.chat_id, mine ? data.recipient : data.sender, mine ? data.recipient_id : data.sender_id);
        addMessage(conv.key, data);
    }

    function onPrivateChatStart(data) {
        const conv = ensureDm(data.chat_id, data.other_user, data.other_user_id);
        conv.messages = data.history || [];
        conv.loaded = true;
        const last = conv.messages[conv.messages.length - 1];
        if (last) { conv.lastText = previewText(last.content); conv.lastTs = last.timestamp; }

        if (state.pendingOpen === data.other_user) {
            state.pendingOpen = null;
            setActive(conv.key);
        } else if (state.active === conv.key) {
            renderHeader();
            renderMessages();
        }
        renderSidebar();
    }

    const requestHistory = (conv) => send({ type: 'private_request', recipient: conv.otherName });

    // ---------- messages ----------
    function addMessage(key, msg) {
        const conv = state.convs.get(key);
        if (!conv) return;
        const own = msg.sender_id === state.myId;

        conv.messages.push(msg);
        if (conv.messages.length > MAX_MESSAGES_KEPT) conv.messages.shift();
        conv.lastText = previewText(msg.content);
        conv.lastTs = msg.timestamp;
        if (!own) clearTyping(key, msg.sender_id);

        if (key === state.active) {
            const stick = own || nearBottom();
            clearEmpty();
            appendMessageDom(msg);
            if (stick) scrollToBottom(); else el.jump.hidden = false;
            if (!own && document.hidden) conv.unread++;
        } else if (!own) {
            conv.unread++;
        }
        renderSidebar();
        updateTitle();
    }

    let lastRendered = null;   // {senderId, time, day} of the newest message in the DOM

    function renderMessages() {
        const conv = activeConv();
        el.messages.classList.add('bulk');
        el.messages.innerHTML = '';
        lastRendered = null;
        if (!conv.messages.length) {
            const text = conv.loaded ? (conv.kind === 'public' ? 'No messages yet. Say hello!' : `No messages with ${esc(conv.otherName)} yet.`) : 'Loading messages…';
            el.messages.innerHTML = `<div class="empty">${text}</div>`;
        } else {
            conv.messages.forEach((m) => appendMessageDom(m));
        }
        scrollToBottom();
        requestAnimationFrame(() => el.messages.classList.remove('bulk'));
    }

    function clearEmpty() {
        const empty = el.messages.querySelector('.empty');
        if (empty) empty.remove();
    }

    function appendMessageDom(msg) {
        const time = new Date(msg.timestamp);
        const valid = !isNaN(time);
        const day = valid ? time.toDateString() : '';
        const own = msg.sender_id === state.myId;

        if (valid && (!lastRendered || lastRendered.day !== day)) {
            const sep = document.createElement('div');
            sep.className = 'day-sep';
            sep.textContent = fmtDay(time);
            el.messages.appendChild(sep);
            lastRendered = null;
        }
        const grouped = !!lastRendered && lastRendered.senderId === msg.sender_id &&
            valid && (time - lastRendered.time) < GROUP_WINDOW_MS;

        const row = document.createElement('div');
        row.className = `msg ${own ? 'own' : 'other'}${grouped ? ' grouped' : ''}`;
        row.innerHTML = `
            ${avatarHtml(msg.sender)}
            <div class="msg-body">
                ${grouped ? '' : `<div class="msg-meta"><span class="msg-name">${esc(own ? 'You' : msg.sender)}</span><span>${valid ? fmtTime(time) : ''}</span></div>`}
                <div class="bubble" ${valid ? `title="${esc(time.toLocaleString())}"` : ''}>${renderContent(msg.content)}</div>
            </div>`;
        el.messages.appendChild(row);
        lastRendered = { senderId: msg.sender_id, time: valid ? time : 0, day };
    }

    function renderContent(content) {
        content = String(content || '');
        if (content.startsWith('__FILE__')) {
            const [head, path = '', name = 'file', caption = ''] = content.split('|_|');
            const kind = head.slice('__FILE__'.length);
            const cleanPath = path.replace(/^\/+/, '');
            if (/^uploads\/[\w.-]+$/.test(cleanPath)) {
                const url = esc(`${state.apiBase}/${cleanPath}`);
                const cap = caption ? `<div class="caption">${esc(caption)}</div>` : '';
                if (kind === 'image') return `${cap}<img class="media-img" src="${url}" data-full="${url}" alt="${esc(name)}">`;
                if (kind === 'audio') return `<audio controls preload="metadata" src="${url}"></audio>`;
                if (kind === 'video') return `<video controls preload="metadata" src="${url}"></video>`;
                return `<a class="file-card" href="${url}" target="_blank" rel="noopener noreferrer">
                    <span class="file-icon">📄</span>
                    <span><div class="file-name">${esc(name)}</div><div class="file-sub">Open file</div></span></a>`;
            }
        }
        return linkify(esc(content));
    }

    // ---------- scrolling ----------
    const nearBottom = () => el.messages.scrollHeight - el.messages.scrollTop - el.messages.clientHeight < 80;
    const scrollToBottom = () => { el.messages.scrollTop = el.messages.scrollHeight; el.jump.hidden = true; };

    // Images finish loading after they are appended; keep the view pinned if the user was at the bottom.
    let pinned = true;
    el.messages.addEventListener('scroll', () => {
        pinned = nearBottom();
        if (pinned) el.jump.hidden = true;
    }, { passive: true });
    el.jump.addEventListener('click', scrollToBottom);
    el.messages.addEventListener('load', (e) => { if (e.target.tagName === 'IMG' && pinned) scrollToBottom(); }, true);
    el.messages.addEventListener('click', (e) => {
        if (e.target.classList.contains('media-img')) window.open(e.target.dataset.full, '_blank', 'noopener');
    });

    // ---------- typing indicators ----------
    function noteTyping(scope, senderId, name) {
        let bucket = state.typing.get(scope);
        if (!bucket) state.typing.set(scope, bucket = new Map());
        const prev = bucket.get(senderId);
        if (prev) clearTimeout(prev.timer);
        bucket.set(senderId, { name, timer: setTimeout(() => clearTyping(scope, senderId), TYPING_SHOW_MS) });
        renderTyping();
    }

    function clearTyping(scope, senderId) {
        const bucket = state.typing.get(scope);
        const entry = bucket && bucket.get(senderId);
        if (!entry) return;
        clearTimeout(entry.timer);
        bucket.delete(senderId);
        renderTyping();
    }

    function renderTyping() {
        const bucket = state.typing.get(state.active);
        const names = bucket ? [...bucket.values()].map((v) => v.name) : [];
        el.typing.textContent = names.length === 0 ? '' :
            names.length === 1 ? `${names[0]} is typing…` :
            names.length === 2 ? `${names[0]} and ${names[1]} are typing…` : 'Several people are typing…';
    }

    function sendTyping() {
        const now = Date.now();
        if (!isOpen() || now - state.lastTypingSent < TYPING_SEND_MS) return;
        state.lastTypingSent = now;
        send({ type: 'typing', scope: state.active });
    }

    // ---------- sending ----------
    function sendToConv(conv, content) {
        if (!isOpen()) { toast('Not connected yet. Your message was not sent.'); return false; }
        return conv.kind === 'public'
            ? send({ type: 'public_message', content })
            : send({ type: 'private_message', chat_id: conv.key, content });
    }

    function submitComposer() {
        const text = el.input.value.trim();
        if (!text) return;
        if (sendToConv(activeConv(), text)) {
            el.input.value = '';
            autosize();
            state.lastTypingSent = 0;
        }
    }

    el.composer.addEventListener('submit', (e) => { e.preventDefault(); submitComposer(); });
    el.input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); submitComposer(); }
    });
    el.input.addEventListener('input', () => { autosize(); if (el.input.value.trim()) sendTyping(); });
    function autosize() {
        el.input.style.height = 'auto';
        el.input.style.height = Math.min(el.input.scrollHeight, 132) + 'px';
    }

    // ---------- uploads ----------
    const fileKind = (file) => file.type.startsWith('image/') ? 'image' :
        file.type.startsWith('audio/') ? 'audio' : file.type.startsWith('video/') ? 'video' : 'file';

    function uploadFile(file) {
        if (!file) return;
        if (!isOpen()) return toast('Not connected yet. Try again in a moment.');
        if (file.size > MAX_UPLOAD_BYTES) return toast('That file is too large (max 10 MB).');

        const conv = activeConv();   // deliver to the chat it was started from, even if the user switches
        const pill = document.createElement('span');
        pill.className = 'upload-pill';
        const label = file.name.length > 24 ? file.name.slice(0, 21) + '…' : file.name;
        pill.textContent = `Uploading ${label} 0%`;
        el.uploads.appendChild(pill);

        const xhr = new XMLHttpRequest();
        xhr.open('POST', `${state.apiBase}/upload?filename=${encodeURIComponent(file.name)}`);
        xhr.setRequestHeader('Authorization', `Bearer ${state.token}`);
        xhr.upload.onprogress = (e) => {
            if (e.lengthComputable) pill.textContent = `Uploading ${label} ${Math.round((e.loaded / e.total) * 100)}%`;
        };
        xhr.onerror = () => { pill.remove(); toast('Upload failed. Check your connection.'); };
        xhr.onload = () => {
            pill.remove();
            if (xhr.status === 401) return forceSignOut('Your session has expired. Please sign in again.');
            if (xhr.status === 413) return toast('That file is too large (max 10 MB).');
            if (xhr.status !== 200) return toast('Upload failed.');
            try {
                const data = JSON.parse(xhr.responseText);
                const safeName = String(data.name).replace(/\|_\|/g, '_');
                sendToConv(conv, `__FILE__${fileKind(file)}|_|${data.url}|_|${safeName}|_|`);
            } catch { toast('Upload failed.'); }
        };
        const form = new FormData();
        form.append('file', file);
        xhr.send(form);
    }

    el.attach.addEventListener('click', () => el.file.click());
    el.file.addEventListener('change', () => { uploadFile(el.file.files[0]); el.file.value = ''; });
    el.input.addEventListener('paste', (e) => {
        const file = e.clipboardData && e.clipboardData.files[0];
        if (file) { e.preventDefault(); uploadFile(file); }
    });
    ['dragenter', 'dragover'].forEach((type) => el.chat.addEventListener(type, (e) => {
        if (!e.dataTransfer || ![...e.dataTransfer.types].includes('Files')) return;
        e.preventDefault();
        el.chat.classList.add('dragging');
    }));
    el.chat.addEventListener('dragleave', (e) => {
        if (!e.relatedTarget || !el.chat.contains(e.relatedTarget)) el.chat.classList.remove('dragging');
    });
    el.chat.addEventListener('drop', (e) => {
        e.preventDefault();
        el.chat.classList.remove('dragging');
        if (e.dataTransfer.files[0]) uploadFile(e.dataTransfer.files[0]);
    });

    // ---------- emoji ----------
    el.emojiPop.innerHTML = EMOJIS.map((e) => `<button type="button" aria-label="${e}">${e}</button>`).join('');
    el.emojiBtn.addEventListener('click', (e) => { e.stopPropagation(); el.emojiPop.hidden = !el.emojiPop.hidden; });
    el.emojiPop.addEventListener('click', (e) => {
        const button = e.target.closest('button');
        if (!button) return;
        el.input.setRangeText(button.textContent, el.input.selectionStart, el.input.selectionEnd, 'end');
        autosize();
        el.input.focus();
    });
    document.addEventListener('click', (e) => { if (!el.emojiPop.contains(e.target)) el.emojiPop.hidden = true; });

    // ---------- conversations ----------
    function setActive(key) {
        const conv = state.convs.get(key);
        if (!conv) return;
        state.active = key;
        conv.unread = 0;
        renderHeader();
        renderMessages();
        renderSidebar();
        renderTyping();
        updateTitle();
        closeDrawer();
        if (conv.kind === 'dm' && !conv.loaded) requestHistory(conv);
        if (!matchMedia('(max-width: 768px)').matches) el.input.focus();
    }

    function openDmWith(username) {
        if (username === state.name) return;
        const existing = [...state.convs.values()].find((c) => c.kind === 'dm' && c.otherName === username);
        if (existing) return setActive(existing.key);
        state.pendingOpen = username;
        if (!send({ type: 'private_request', recipient: username })) toast('Not connected yet.');
    }

    el.navPublic.addEventListener('click', () => setActive(PUBLIC));
    el.dmList.addEventListener('click', (e) => {
        const item = e.target.closest('[data-key]');
        if (item) setActive(item.dataset.key);
    });
    el.onlineList.addEventListener('click', (e) => {
        const item = e.target.closest('[data-name]');
        if (item) openDmWith(item.dataset.name);
    });

    // ---------- rendering ----------
    function renderSidebar() {
        const pub = state.convs.get(PUBLIC);
        el.navPublic.classList.toggle('active', state.active === PUBLIC);
        el.badgePublic.hidden = !pub.unread;
        el.badgePublic.textContent = pub.unread > 99 ? '99+' : pub.unread;

        const onlineIds = new Set(state.online.map((u) => u.user_id));
        const dms = [...state.convs.values()].filter((c) => c.kind === 'dm')
            .sort((a, b) => (Date.parse(b.lastTs) || 0) - (Date.parse(a.lastTs) || 0) || a.otherName.localeCompare(b.otherName));

        el.dmList.innerHTML = dms.length ? dms.map((c) => `
            <button type="button" class="nav-item${state.active === c.key ? ' active' : ''}" data-key="${esc(c.key)}">
                ${avatarHtml(c.otherName, { small: true, online: onlineIds.has(c.otherId) })}
                <span class="nav-text"><span class="nav-name">${esc(c.otherName)}</span>${c.lastText ? `<span class="nav-preview">${esc(c.lastText)}</span>` : ''}</span>
                ${c.unread ? `<span class="badge">${c.unread > 99 ? '99+' : c.unread}</span>` : ''}
            </button>`).join('') : '<div class="nav-empty">No conversations yet. Pick someone below.</div>';

        el.onlineCount.textContent = state.online.length;
        el.onlineList.innerHTML = state.online.map((u) => `
            <button type="button" class="nav-item" data-name="${esc(u.username)}"${u.user_id === state.myId ? ' disabled' : ''}>
                ${avatarHtml(u.username, { small: true, online: true })}
                <span class="nav-text"><span class="nav-name">${esc(u.username)}${u.user_id === state.myId ? ' (you)' : ''}</span></span>
            </button>`).join('');
    }

    function renderHeader() {
        const conv = activeConv();
        if (conv.kind === 'public') {
            el.chatTitle.textContent = 'General';
            const n = state.online.length;
            el.chatSub.textContent = n ? `${n} online` : '';
        } else {
            el.chatTitle.textContent = conv.otherName;
            el.chatSub.textContent = state.online.some((u) => u.user_id === conv.otherId)
                ? 'Online' : 'Offline. They will see your messages when they are back.';
        }
    }

    function renderConnection() {
        const s = state.status;
        const live = s === 'open';
        el.connPill.dataset.state = live ? 'live' : (s === 'replaced' ? 'offline' : 'connecting');
        el.connPillText.textContent = live ? 'Live' : (s === 'replaced' ? 'Disconnected' : 'Reconnecting…');
        el.myStatus.textContent = live ? 'Online' : (s === 'replaced' ? 'Disconnected' : 'Reconnecting…');
        el.send.disabled = !live;
        el.input.placeholder = live ? 'Type a message' : 'Waiting for connection…';

        el.banner.hidden = live;
        if (s === 'replaced') {
            el.bannerText.textContent = 'This account was opened in another tab or window.';
            el.bannerBtn.textContent = 'Use this tab';
        } else if (!live) {
            el.bannerText.textContent = `Connection lost. Reconnecting${state.retry > 1 ? ` (attempt ${state.retry})` : ''}…`;
            el.bannerBtn.textContent = 'Retry now';
        }
    }

    function updateTitle() {
        let total = 0;
        state.convs.forEach((c) => { total += c.unread; });
        document.title = total ? `(${total}) QuantumConnect` : 'QuantumConnect';
    }

    // ---------- mobile drawer ----------
    const closeDrawer = () => document.body.classList.remove('drawer-open');
    el.menuBtn.addEventListener('click', () => document.body.classList.toggle('drawer-open'));
    el.scrim.addEventListener('click', closeDrawer);
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') { closeDrawer(); el.emojiPop.hidden = true; }
    });

    // ---------- wiring ----------
    el.authForm.addEventListener('submit', (e) => { e.preventDefault(); submitAuth(); });
    el.tabLogin.addEventListener('click', () => setAuthMode('login'));
    el.tabRegister.addEventListener('click', () => setAuthMode('register'));
    el.signout.addEventListener('click', signOut);
    el.bannerBtn.addEventListener('click', reconnectNow);

    // Come back fast when the tab wakes up or the network returns instead of waiting for backoff.
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) return;
        const conv = activeConv();
        if (conv.unread) { conv.unread = 0; renderSidebar(); updateTitle(); }
        if (state.status === 'reconnecting') reconnectNow();
    });
    window.addEventListener('online', () => { if (state.status === 'reconnecting') reconnectNow(); });

    // ---------- embedding (quantum-bridge.js) ----------
    const params = new URLSearchParams(location.search);
    const isWidget = params.get('widget') === 'true';
    if (isWidget) {
        document.body.classList.add('widget-mode');
        const accent = params.get('accent');
        if (accent) document.documentElement.style.setProperty('--accent', accent);
    }
    window.addEventListener('message', (event) => {
        // Only the embedding page may drive the widget, and only when signed in
        if (!isWidget || event.source !== window.parent || !isOpen()) return;
        if (event.data && event.data.type === 'SEND_MSG' && event.data.text) {
            sendToConv(activeConv(), String(event.data.text).slice(0, 4000));
        }
    });

    // ---------- init ----------
    el.server.value = CFG.WS_URL;
    el.username.value = params.get('user') || store.get('qc_name') || '';   // ?user= only pre-fills the form
    setAuthMode('login');
    renderSidebar();
    renderConnection();
    if (state.token) resumeSession();
})();
