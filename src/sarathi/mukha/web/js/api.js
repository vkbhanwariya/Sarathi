/**
 * HTTP and Server-Sent Events (SSE) transport client for Mukha.
 */

import { elements } from "./dom.js";
import { state } from "./state.js";

export async function apiGet(url) {
    try {
        const res = await fetch(url);
        return await res.json();
    } catch (err) {
        console.error(`API GET failed for ${url}:`, err);
        return { ok: false, error: err.message };
    }
}

export async function apiPost(url, body = {}) {
    try {
        const res = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        return await res.json();
    } catch (err) {
        console.error(`API POST failed for ${url}:`, err);
        return { ok: false, error: err.message };
    }
}

export function setSSEBadge(isLive) {
    if (!elements.sseStatusBadge || !elements.sseStatusLabel) return;
    if (isLive) {
        elements.sseStatusBadge.className = "sse-badge";
        elements.sseStatusLabel.textContent = "SSE LIVE";
    } else {
        elements.sseStatusBadge.className = "sse-badge polling";
        elements.sseStatusLabel.textContent = "POLLING";
    }
}

let lastStateJson = null;

export function getPollInterval() {
    if (document.visibilityState === "hidden") return 3000;
    if (state.activeRunStatus === "RUNNING") return 500;
    return 1500;
}

export async function pollState(onStateUpdate) {
    if (state.sseActive) return; // SSE handles active state updates

    const res = await apiGet("/api/state");
    if (res && res.ok && res.state) {
        const rev = res.state_revision !== undefined ? res.state_revision : res.state.state_revision;
        const currentJson = JSON.stringify(res.state);
        if (currentJson !== lastStateJson || (rev && rev > state.lastRevision)) {
            lastStateJson = currentJson;
            if (rev) state.lastRevision = rev;
            state.lastState = res.state;
            if (typeof onStateUpdate === "function") {
                onStateUpdate(res.state);
            }
        }
    }

    clearTimeout(state.pollTimer);
    state.pollTimer = setTimeout(() => pollState(onStateUpdate), getPollInterval());
}

export function initSSE(onStateUpdate) {
    if (typeof EventSource === "undefined") {
        setSSEBadge(false);
        pollState(onStateUpdate);
        return;
    }

    try {
        if (state.sseSource) {
            state.sseSource.close();
        }

        const es = new EventSource("/api/events");
        state.sseSource = es;

        es.onopen = () => {
            state.sseActive = true;
            setSSEBadge(true);
        };

        es.addEventListener("state", (e) => {
            try {
                const data = JSON.parse(e.data);
                if (data && data.ok && data.state) {
                    const rev = data.state_revision !== undefined ? data.state_revision : data.state.state_revision;
                    if (rev) state.lastRevision = Math.max(state.lastRevision, rev);
                    if (typeof onStateUpdate === "function") {
                        onStateUpdate(data.state);
                    }
                }
            } catch (err) {
                console.error("Malformed SSE state payload:", err);
            }
        });

        es.addEventListener("ping", () => {
            // Heartbeat acknowledged
        });

        es.onerror = () => {
            state.sseActive = false;
            setSSEBadge(false);
            es.close();
            state.sseSource = null;
            // Fall back to adaptive polling and retry SSE reconnect after 5s
            pollState(onStateUpdate);
            setTimeout(() => initSSE(onStateUpdate), 5000);
        };
    } catch (err) {
        console.warn("Failed to initialize SSE, using polling:", err);
        setSSEBadge(false);
        pollState(onStateUpdate);
    }
}
