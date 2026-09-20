/**
 * QuantumConnect Enterprise Bridge
 * This SDK allows developers to embed the QuantumConnect chat into any application.
 */
const QuantumConnect = (() => {
    let _config = {
        serverUrl: window.location.origin,
        container: 'body',
        username: null,
        theme: null,
        onMessage: null
    };

    let _iframe = null;

    const init = (config) => {
        _config = { ..._config, ...config };
        console.log("QuantumConnect | Initializing Bridge to:", _config.serverUrl);
        
        // Create the Widget Element
        const container = document.querySelector(_config.container);
        if (!container) throw new Error("QuantumConnect | Container not found");

        const widgetWrapper = document.createElement('div');
        widgetWrapper.id = "quantum-chat-widget";
        widgetWrapper.style.cssText = `
            width: 100%;
            height: 100%;
            border: none;
            overflow: hidden;
            display: flex;
            flex-direction: column;
        `;

        // Construct URL with params
        let url = new URL(_config.serverUrl);
        url.searchParams.set('widget', 'true');
        if (_config.username) url.searchParams.set('user', _config.username);
        if (_config.theme) url.searchParams.set('accent', _config.theme);

        _iframe = document.createElement('iframe');
        _iframe.src = url.toString();
        _iframe.style.cssText = `
            flex: 1;
            border: none;
            width: 100%;
            height: 100%;
        `;

        widgetWrapper.appendChild(_iframe);
        container.appendChild(widgetWrapper);

        // Listen for messages from the chat
        window.addEventListener('message', (event) => {
            if (event.origin !== new URL(_config.serverUrl).origin) return;
            
            if (event.data.type === 'NEW_MESSAGE' && _config.onMessage) {
                _config.onMessage(event.data.payload);
            }
        });
    };

    const sendMessage = (text) => {
        if (_iframe && _iframe.contentWindow) {
            _iframe.contentWindow.postMessage({ type: 'SEND_MSG', text }, '*');
        }
    };

    return {
        init,
        sendMessage
    };
})();

// Export for modern and legacy environments
if (typeof module !== 'undefined' && module.exports) {
    module.exports = QuantumConnect;
} else {
    window.QuantumConnect = QuantumConnect;
}
