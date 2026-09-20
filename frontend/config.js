/**
 * QuantumConnect frontend configuration.
 *
 * After deploying the backend to Render, set BACKEND_URL to its public URL
 * (https, no trailing slash) and redeploy the frontend on Vercel.
 * The WebSocket URL (wss://.../ws) is derived from it automatically.
 */
window.QC_CONFIG = (() => {
    const PRODUCTION_BACKEND_URL = "https://real-time-distributed-chat-application-78mv.onrender.com";
    const LOCAL_BACKEND_URL = "http://localhost:8000";

    const isLocal = ["localhost", "127.0.0.1"].includes(window.location.hostname);
    const httpUrl = (isLocal ? LOCAL_BACKEND_URL : PRODUCTION_BACKEND_URL).replace(/\/+$/, "");

    return {
        HTTP_URL: httpUrl,
        WS_URL: httpUrl.replace(/^http/i, "ws") + "/ws"
    };
})();
